"""
metadata.py
Etapa de enriquecimento de metadados (Fase 3): descobre capa, ano e gênero
da música para incluir no pacote UltraStar.

FILOSOFIA DE DESIGN (decisão sênior): metadados são ENRIQUECIMENTO, nunca
REQUISITO. Nenhuma falha aqui (rede fora, música não encontrada, imagem
corrompida) pode derrubar o pipeline - na pior das hipóteses, o pacote sai
sem capa/ano/gênero, o que é perfeitamente válido no formato UltraStar.
Toda função aqui trata suas próprias exceções e degrada graciosamente.

ESTRATÉGIA EM CASCATA (da fonte mais confiável/barata para a mais custosa):
  1. Tags EMBUTIDAS no arquivo de áudio (via mutagen) - offline,
     instantâneo, e frequentemente a melhor fonte (o FLAC de teste do
     Raimundos, por exemplo, já trazia capa 1280x1280, ano e gênero
     embutidos). Sempre tentada primeiro.
  2. MusicBrainz + Cover Art Archive - APIs abertas, sem chave, usadas só
     para preencher o que faltou na etapa 1. Requer rede.

REGRAS DO MUSICBRAINZ (respeitadas aqui, senão eles bloqueiam o IP):
  - User-Agent identificável e honesto é OBRIGATÓRIO.
  - Rate limit de ~1 requisição por segundo. Serializamos e espaçamos as
    chamadas para nunca exceder isso.
  - O Cover Art Archive (coverartarchive.org) não tem rate limit próprio,
    mas responde com redirect 307 para a imagem real (no Internet Archive) -
    o `requests` segue o redirect automaticamente.
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass
from pathlib import Path

import requests
from mutagen import File as MutagenFile
from PIL import Image

# User-Agent honesto e identificável, como o MusicBrainz exige. Inclui uma
# forma de contato (o repositório) - é assim que projetos sérios se
# identificam para a API deles.
_USER_AGENT = "USKMaker/0.1 (https://github.com/prof-walterfr/USKMaker)"
_MB_BASE = "https://musicbrainz.org/ws/2"
_CAA_BASE = "https://coverartarchive.org"
_MB_MIN_INTERVAL = 1.1  # segundos entre chamadas ao MusicBrainz (margem sobre o limite de 1/s)
# Timeout curto (06/07/2026): metadados são enriquecimento opcional, não
# vale travar a pipeline muitos segundos esperando um servidor que pode não
# ter o dado. 6s é suficiente para respostas normais do MusicBrainz/CAA e
# faz a busca "desistir" rápido quando a música não está catalogada
# (antes eram 15s por request, somando ~16s de espera visível em músicas
# sem metadados - ver teste "Paulinho Moska").
_HTTP_TIMEOUT = 6  # segundos

_last_mb_call = 0.0


@dataclass
class SongMetadata:
    year: int | None = None
    genre: str | None = None
    cover_path: Path | None = None  # caminho local da capa já salva, se houver
    source: str = "nenhuma"  # "arquivo", "musicbrainz", "arquivo+musicbrainz", "nenhuma"


def _respect_mb_rate_limit() -> None:
    """Garante o intervalo mínimo entre chamadas ao MusicBrainz."""
    global _last_mb_call
    elapsed = time.monotonic() - _last_mb_call
    if elapsed < _MB_MIN_INTERVAL:
        time.sleep(_MB_MIN_INTERVAL - elapsed)
    _last_mb_call = time.monotonic()


# ---------------------------------------------------------------------------
# Fonte 1: tags embutidas no arquivo (mutagen)
# ---------------------------------------------------------------------------

def _extract_embedded(audio_path: Path, out_cover_path: Path) -> SongMetadata:
    """
    Lê ano, gênero e capa embutidos no arquivo de áudio. Retorna o que
    conseguir; campos ausentes ficam None. Nunca lança exceção pra cima.
    """
    meta = SongMetadata()
    try:
        f = MutagenFile(str(audio_path))
        if f is None:
            return meta

        tags = f.tags or {}

        # Ano e gênero: os nomes de tag variam por formato (Vorbis comment
        # no FLAC/OGG usa 'date'/'genre'; ID3 no MP3 usa 'TDRC'/'TCON').
        # mutagen.File(...).tags expõe de formas diferentes - tentamos as
        # chaves mais comuns de forma tolerante.
        def _first_tag(*keys) -> str | None:
            for key in keys:
                try:
                    val = tags.get(key)
                except Exception:
                    val = None
                if val:
                    # pode vir como lista ou objeto - normaliza para string
                    s = str(val[0]) if isinstance(val, list) else str(val)
                    if s.strip():
                        return s.strip()
            return None

        year_raw = _first_tag("date", "DATE", "year", "TDRC", "originaldate")
        if year_raw:
            # extrai só os 4 dígitos do ano de algo como "2000-01-01"
            import re
            m = re.search(r"\d{4}", year_raw)
            if m:
                meta.year = int(m.group())

        meta.genre = _first_tag("genre", "GENRE", "TCON")

        # Capa embutida: também varia por formato.
        cover_bytes = _extract_embedded_cover_bytes(f)
        if cover_bytes:
            saved = _save_cover_image(cover_bytes, out_cover_path)
            if saved:
                meta.cover_path = out_cover_path

        if meta.year or meta.genre or meta.cover_path:
            meta.source = "arquivo"
    except Exception as e:
        print(f"[metadata] aviso: falha ao ler tags embutidas ({e}) - seguindo sem elas.")

    return meta


def _extract_embedded_cover_bytes(mutagen_file) -> bytes | None:
    """Extrai os bytes da capa embutida, lidando com os formatos comuns."""
    try:
        # FLAC / OGG: objeto tem .pictures
        pictures = getattr(mutagen_file, "pictures", None)
        if pictures:
            return pictures[0].data

        tags = mutagen_file.tags
        if tags is None:
            return None

        # MP3 (ID3): frames APIC:
        for key in tags.keys():
            if str(key).startswith("APIC"):
                return tags[key].data

        # MP4/M4A: capa fica em 'covr'
        if "covr" in tags:
            covr = tags["covr"]
            if covr:
                return bytes(covr[0])
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Fonte 2: MusicBrainz + Cover Art Archive
# ---------------------------------------------------------------------------

def _mb_find_release_mbid(artist: str, title: str) -> str | None:
    """
    Procura no MusicBrainz o release mais provável para (artista, título)
    e retorna o MBID do release. Retorna None se nada plausível for achado.

    SELEÇÃO INTELIGENTE (melhoria 06/07/2026): a versão anterior pegava
    simplesmente o PRIMEIRO release da primeira gravação retornada. Isso
    trazia problemas de qualidade - num teste real ("20 e poucos anos" -
    Raimundos), o primeiro match era um relançamento/coletânea de 2003 em
    vez do álbum original ("MTV ao Vivo", 2000). Agora, entre todos os
    releases candidatos das gravações retornadas, preferimos:
      1. Os que têm data de lançamento conhecida (descartar sem data).
      2. Entre esses, o MAIS ANTIGO - que quase sempre é o lançamento
         original, não um relançamento/coletânea posterior. O ano do
         lançamento original é o que um usuário espera ver na tag #YEAR.
    Isso não afeta o caso em que o arquivo já traz o ano correto embutido
    (a cascata sempre prioriza o arquivo), mas melhora o resultado quando
    o MusicBrainz é a única fonte de ano disponível.
    """
    _respect_mb_rate_limit()
    query = f'recording:"{title}" AND artist:"{artist}"'
    try:
        resp = requests.get(
            f"{_MB_BASE}/recording",
            params={"query": query, "fmt": "json", "limit": 10},
            headers={"User-Agent": _USER_AGENT},
            timeout=_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[metadata] aviso: busca no MusicBrainz falhou ({e}) - seguindo sem ela.")
        return None

    # Coleta todos os releases candidatos (de todas as gravações retornadas),
    # com sua data quando disponível. A busca de 'recording' já traz um
    # resumo de cada release embutido, incluindo o campo 'date'.
    candidates: list[tuple[str, str]] = []  # (mbid, date_str)
    fallback_mbid: str | None = None
    for rec in data.get("recordings", []):
        for release in rec.get("releases", []):
            mbid = release.get("id")
            if not mbid:
                continue
            if fallback_mbid is None:
                fallback_mbid = mbid  # primeiro visto, usado se nenhum tiver data
            date_str = release.get("date") or ""
            if date_str:
                candidates.append((mbid, date_str))

    if candidates:
        # ordena por data (string ISO "AAAA-MM-DD" ordena cronologicamente
        # como texto) e pega o mais antigo
        candidates.sort(key=lambda c: c[1])
        return candidates[0][0]

    # nenhum release tinha data - cai no primeiro visto (melhor que nada)
    return fallback_mbid


def _mb_fetch_year_genre(release_mbid: str) -> tuple[int | None, str | None]:
    """Busca ano e gênero de um release específico no MusicBrainz."""
    _respect_mb_rate_limit()
    try:
        resp = requests.get(
            f"{_MB_BASE}/release/{release_mbid}",
            params={"fmt": "json", "inc": "genres"},
            headers={"User-Agent": _USER_AGENT},
            timeout=_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[metadata] aviso: lookup de release no MusicBrainz falhou ({e}).")
        return None, None

    year = None
    date = data.get("date") or ""
    import re
    m = re.search(r"\d{4}", date)
    if m:
        year = int(m.group())

    genre = None
    genres = data.get("genres") or []
    if genres:
        # pega o gênero com maior "count" (mais votado pela comunidade)
        best = max(genres, key=lambda g: g.get("count", 0))
        genre = best.get("name")
        if genre:
            genre = genre.title()

    return year, genre


def _caa_download_cover(release_mbid: str, out_cover_path: Path) -> Path | None:
    """
    Baixa a capa frontal do Cover Art Archive para o release dado.
    O endpoint /front redireciona (307) para a imagem real - requests
    segue automaticamente. Retorna o caminho salvo, ou None.
    """
    try:
        resp = requests.get(
            f"{_CAA_BASE}/release/{release_mbid}/front-500",
            headers={"User-Agent": _USER_AGENT},
            timeout=_HTTP_TIMEOUT,
            allow_redirects=True,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        if _save_cover_image(resp.content, out_cover_path):
            return out_cover_path
    except Exception as e:
        print(f"[metadata] aviso: download da capa no Cover Art Archive falhou ({e}).")
    return None


# ---------------------------------------------------------------------------
# Utilitário de imagem
# ---------------------------------------------------------------------------

def _save_cover_image(image_bytes: bytes, out_path: Path) -> bool:
    """
    Valida os bytes como imagem (via Pillow), converte para JPEG e salva.
    Padroniza tudo para JPEG - formato universalmente aceito pelo UltraStar
    e evita surpresas com PNG/WEBP em engines mais antigos.
    Retorna True se salvou com sucesso.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = img.convert("RGB")
        # capa quadrada não é obrigatória, mas capas muito grandes só pesam
        # o pacote sem ganho visível no jogo - limita o lado maior a 600px.
        max_side = 600
        if max(img.size) > max_side:
            ratio = max_side / max(img.size)
            new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
            img = img.resize(new_size, Image.LANCZOS)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(out_path), "JPEG", quality=88)
        return True
    except Exception as e:
        print(f"[metadata] aviso: imagem de capa inválida/não processável ({e}).")
        return False


# ---------------------------------------------------------------------------
# Orquestração pública
# ---------------------------------------------------------------------------

def fetch_metadata(
    audio_path: Path,
    artist: str,
    title: str,
    out_cover_path: Path,
    use_network: bool = True,
) -> SongMetadata:
    """
    Descobre metadados em cascata: primeiro tags embutidas, depois
    MusicBrainz/CAA para o que faltar. Nunca lança exceção - sempre retorna
    um SongMetadata (possivelmente todo vazio, se nada for encontrado).

    audio_path: arquivo de áudio ORIGINAL (não o stem separado) - é ele que
                carrega as tags embutidas.
    out_cover_path: onde salvar a capa (ex.: "Artista - Título [CO].jpg").
    use_network: se False, usa só as tags embutidas (modo offline).
    """
    meta = _extract_embedded(audio_path, out_cover_path)

    need_year = meta.year is None
    need_genre = meta.genre is None
    need_cover = meta.cover_path is None

    if use_network and (need_year or need_genre or need_cover):
        release_mbid = _mb_find_release_mbid(artist, title)
        if release_mbid:
            used_mb = False
            if need_year or need_genre:
                mb_year, mb_genre = _mb_fetch_year_genre(release_mbid)
                if need_year and mb_year:
                    meta.year = mb_year
                    used_mb = True
                if need_genre and mb_genre:
                    meta.genre = mb_genre
                    used_mb = True
            if need_cover:
                cover = _caa_download_cover(release_mbid, out_cover_path)
                if cover:
                    meta.cover_path = cover
                    used_mb = True
            if used_mb:
                meta.source = "arquivo+musicbrainz" if meta.source == "arquivo" else "musicbrainz"

    return meta


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fase 3: teste isolado de busca de metadados")
    parser.add_argument("--file", required=True, help="Arquivo de áudio original")
    parser.add_argument("--artist", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--out-cover", default="./work/cover_test.jpg")
    parser.add_argument("--no-network", action="store_true", help="Usar só tags embutidas")
    args = parser.parse_args()

    result = fetch_metadata(
        Path(args.file), args.artist, args.title, Path(args.out_cover),
        use_network=not args.no_network,
    )
    print("=" * 50)
    print(f"Fonte:  {result.source}")
    print(f"Ano:    {result.year}")
    print(f"Gênero: {result.genre}")
    print(f"Capa:   {result.cover_path}")

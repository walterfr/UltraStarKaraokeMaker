"""
download.py
Etapa 1 da pipeline: obter um arquivo de áudio local a partir de um link do
YouTube, ou simplesmente validar/normalizar um mp3 já fornecido pelo usuário.

FASE 3 (complemento, 06/07/2026): agora suporta também baixar o VÍDEO do
YouTube (opcional, opt-in via flag), para incluir no pacote UltraStar e ter
fundo animado no jogo (tag #VIDEO). O download de vídeo é opcional porque é
custoso (arquivos grandes, mais banda/tempo) e a maioria dos pacotes quer só
letra+áudio - quem não pede vídeo não paga esse custo.

Uso isolado (teste manual):
    python -m pipeline.download --url "https://youtu.be/XXXXX" --out ./work/raw
    python -m pipeline.download --url "https://youtu.be/XXXXX" --out ./work/raw --with-video
    python -m pipeline.download --file "C:/musicas/minha_musica.mp3" --out ./work/raw
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from .proc_utils import ffmpeg_exe, run_subprocess

# Quantas vezes tentar de novo quando o YouTube recusa de forma TRANSITÓRIA.
# 403 no meio do download é um modo de falha conhecido e INTERMITENTE do lado
# do YouTube (yt-dlp issue #17395, aberta): a mesma URL costuma funcionar numa
# nova tentativa, sem mudar nada. Uma tentativa extra é barata; várias só
# fariam o usuário esperar mais por algo que não vai melhorar sozinho.
YT_DLP_RETRIES = 1

# Trechos que marcam uma falha TRANSITÓRIA (vale tentar de novo). Qualquer
# outra coisa - vídeo privado, removido, restrição de idade - é permanente e
# repetir só gastaria o tempo do usuário.
_TRANSIENT_MARKERS = (
    "403", "forbidden", "unable to download video data",
    "timed out", "timeout", "connection reset", "temporarily",
    "429", "too many requests",
)

# Falhas permanentes que têm uma explicação ÚTIL em português. O objetivo é o
# usuário ler UMA linha e saber o que fazer, em vez de um traceback de Python.
_KNOWN_CAUSES = (
    ("sign in to confirm your age",
     "O vídeo tem restrição de idade e exige login no YouTube."),
    ("private video",
     "O vídeo é privado."),
    ("video unavailable",
     "O vídeo não está disponível (removido ou bloqueado na sua região)."),
    ("sign in to confirm you",
     "O YouTube pediu verificação de robô para este download."),
    ("requested format is not available",
     "O YouTube não ofereceu nenhum formato compatível para este vídeo."),
    ("403", "O YouTube recusou o download (403). Costuma ser temporário."),
)


def _extract_yt_dlp_error(output: str) -> str:
    """
    Pesca a linha que interessa da saída do yt-dlp.

    O yt-dlp escreve o motivo real numa linha "ERROR: ..." no meio de dezenas
    de linhas de progresso. Sem isto, o que chega ao usuário é o traceback do
    subprocess.CalledProcessError - que mostra o COMANDO inteiro e esconde o
    MOTIVO. Foi exatamente o que aconteceu num relato real (02/09/2026): o
    "HTTP Error 403: Forbidden" estava lá, enterrado.
    """
    for line in reversed((output or "").splitlines()):
        if line.strip().upper().startswith("ERROR:"):
            return line.strip()[6:].strip()
    return ""


def _friendly_download_error(raw: str) -> str:
    """Traduz o erro do yt-dlp para uma frase acionável (ou devolve o cru)."""
    low = raw.lower()
    for marker, explanation in _KNOWN_CAUSES:
        if marker in low:
            return explanation
    return raw or "o yt-dlp falhou sem dizer o motivo"


def run_yt_dlp(cmd: list[str], what: str = "o vídeo") -> None:
    """
    Roda o yt-dlp, tentando de novo em falha transitória e reportando o
    motivo REAL em vez do traceback do subprocesso.

    POR QUE ISTO EXISTE (relato real, 02/09/2026): um download falhou com
    "HTTP Error 403: Forbidden" e o usuário recebeu na tela o
    CalledProcessError cru - a linha de comando inteira com todos os
    argumentos, e nenhuma pista do motivo. Quem não programa não tem como
    ler aquilo. O motivo estava no log, mas ninguém deveria precisar abrir
    o log para descobrir que o YouTube simplesmente recusou.
    """
    import subprocess

    last_error = ""
    for attempt in range(YT_DLP_RETRIES + 1):
        try:
            run_subprocess(cmd)
            return
        except subprocess.CalledProcessError as e:
            output = (e.stderr or "") + "\n" + (e.output or "")
            last_error = _extract_yt_dlp_error(output)
            transient = any(m in last_error.lower() for m in _TRANSIENT_MARKERS)

            if transient and attempt < YT_DLP_RETRIES:
                print(
                    f"[download] O YouTube recusou ({last_error}). "
                    f"Isso costuma ser temporário - tentando mais uma vez..."
                )
                continue

            detalhe = _friendly_download_error(last_error)
            dica = (
                " Se persistir, use o modo ARQUIVO LOCAL (baixe a música por "
                "fora e aponte o app para ela) ou atualize o yt-dlp - o YouTube "
                "muda com frequência e o yt-dlp precisa acompanhar."
            )
            raise RuntimeError(
                f"Não consegui baixar {what} do YouTube. {detalhe}{dica}"
            ) from None


@dataclass
class SourceAudio:
    """
    Resultado da etapa 1. `audio_wav` é sempre preenchido; `video_path` só
    quando o vídeo foi baixado do YouTube (fonte local nunca traz vídeo,
    e download de vídeo é opt-in).
    """
    audio_wav: Path
    video_path: Path | None = None


def _yt_dlp_base_cmd() -> list[str]:
    # yt-dlp invocado como MÓDULO do interpretador atual (sys.executable -m
    # yt_dlp), não pelo nome "yt-dlp" no PATH. Ver histórico de bug detalhado
    # abaixo - resumindo: via Tauri o venv não está ativado, então o
    # executável "yt-dlp" não está no PATH, mas o módulo yt_dlp está
    # instalado no venv e é encontrado por sys.executable. Nome do módulo
    # usa underscore (yt_dlp), o comando usa hífen (yt-dlp).
    base = [sys.executable, "-m", "yt_dlp"]
    # --no-playlist: um link de "watch" do YouTube costuma vir com "&list=..."
    # (Mix/rádio automático, ou uma playlist de verdade). Sem esta flag, o
    # yt-dlp baixa a LISTA INTEIRA - o usuário cola um clipe e recebe uma dúzia
    # de músicas. O USKMaker sempre processa UMA música por URL, então baixar a
    # lista nunca é o que se quer. Vai no comando BASE para valer em todos os
    # downloads (áudio, vídeo e fundo).
    base += ["--no-playlist"]
    # Aponta o yt-dlp para o ffmpeg EMBUTIDO do USKMaker quando houver (o
    # yt-dlp usa ffmpeg para extrair áudio e mesclar vídeo+áudio). Sem a var,
    # ele procura no PATH como antes. --ffmpeg-location aceita o caminho do
    # binário ou da pasta.
    ff = os.environ.get("USKMAKER_FFMPEG")
    if ff:
        base += ["--ffmpeg-location", ff]
    return base


def download_from_youtube(url: str, out_dir: Path) -> Path:
    """
    Baixa SÓ o áudio (melhor qualidade) de um vídeo do YouTube e converte
    para .wav. Usado quando o usuário não pediu o vídeo no pacote - é o
    caminho mais leve.

    Retorna o caminho do arquivo .wav gerado.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    # Nome FIXO ("audio.wav"), não "%(title)s.%(ext)s". BUG REAL achado por
    # relato de usuário (Todilo, issue #12, 04/08/2026): com nome por título,
    # o retorno da função era "o .wav mais recente por mtime na pasta raw" -
    # se essa pasta já tivesse QUALQUER outro .wav (de um teste anterior com
    # outra música, reprocessamento, etc.), a heurística podia devolver o
    # arquivo ERRADO. Aconteceu de verdade: o log dele mostra "Áudio em:
    # ...BTS Video Grammofon.wav" no meio do processamento de uma música
    # SUECA completamente diferente - alinhou a letra contra o áudio errado,
    # 0 âncora exata, 61% interpolado. Nome fixo elimina a ambiguidade: só
    # existe UM .wav possível nesta pasta, sem precisar adivinhar qual é.
    output_template = str(out_dir / "audio.%(ext)s")
    audio_wav = out_dir / "audio.wav"

    # HISTÓRICO DE BUG (06/07/2026): antes chamava "yt-dlp" direto pelo nome,
    # dependendo de ele estar no PATH. Funcionava com o venv ATIVADO, mas
    # quebrava via Tauri com FileNotFoundError [WinError 2] - o Tauri chama o
    # python.exe do venv DIRETAMENTE, sem ativar o venv. Corrigido invocando
    # como módulo (ver _yt_dlp_base_cmd).
    cmd = _yt_dlp_base_cmd() + [
        "-x",  # extrair só o áudio
        "--audio-format", "wav",
        "--audio-quality", "0",  # melhor qualidade
        "-o", output_template,
        url,
    ]

    # NOTA: se o YouTube pedir autenticação (idade/região), gere um cookies.txt
    # e adicione "--cookies", "cookies.txt" na lista acima.

    run_yt_dlp(cmd, "o áudio")

    if not audio_wav.exists():
        raise RuntimeError("yt-dlp rodou mas " + str(audio_wav) + " não foi encontrado.")
    return audio_wav


def download_from_youtube_with_video(url: str, out_dir: Path, max_resolution: int = 0) -> SourceAudio:
    """
    Baixa o VÍDEO do YouTube (preferindo mp4) UMA vez e extrai o áudio dele
    localmente via ffmpeg - assim há apenas UMA transferência de rede, em
    vez de baixar áudio e vídeo separadamente.

    max_resolution > 0 limita a altura do vídeo baixado (mesma convenção do
    download_background_video, que já usa isso) - sem teto, o yt-dlp pode
    trazer 4K só pra virar fundo de karaokê, gastando banda/disco à toa.
    0 = sem limite (comportamento anterior).

    Retorna SourceAudio com audio_wav E video_path preenchidos.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    # Basename FIXO ("video.*"), não "%(title)s.*" - mesmo bug real do
    # download_from_youtube (ver comentário lá): "arquivo mais recente por
    # mtime na pasta" podia devolver um vídeo de OUTRA música que já
    # estivesse na pasta. A extensão final varia (mp4/webm/mkv conforme o
    # que o YouTube oferece), então não dá pra fixar ela também - mas o
    # PREFIXO fixo já garante que só o arquivo desta chamada casa com o glob.
    output_template = str(out_dir / "video.%(ext)s")

    # Baixa o melhor vídeo mp4 + melhor áudio m4a e combina em mp4. O formato
    # mp4 é o que o UltraStar lê melhor; se o YouTube só tiver webm, o yt-dlp
    # ainda entrega webm e o UltraStar moderno também lê, mas mp4 é o alvo
    # preferencial por compatibilidade máxima.
    if max_resolution > 0:
        video_format = (
            f"bestvideo[ext=mp4][height<={max_resolution}]+bestaudio[ext=m4a]/"
            f"best[ext=mp4][height<={max_resolution}]/best[height<={max_resolution}]"
        )
    else:
        video_format = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
    cmd = _yt_dlp_base_cmd() + [
        "-f", video_format,
        "--merge-output-format", "mp4",
        "-o", output_template,
        url,
    ]
    run_yt_dlp(cmd, "o vídeo")

    # SÓ containers de vídeo entram aqui. O .wav extraído logo abaixo é
    # escrito NESTA pasta com o mesmo prefixo "video." - e numa SEGUNDA
    # geração na mesma pasta (intermediários mantidos, "Gerar de novo") ele
    # é o "video.*" mais recente, porque o yt-dlp nem toca no .mp4 que já
    # estava baixado. O caminho do vídeo virava então o próprio .wav, e o
    # ffmpeg recebia a mesma coisa como entrada E saída:
    #   "Output ... same as Input #0 - exiting / cannot edit files in-place"
    # Bug real relatado pelo usuário em 08/09/2026.
    video_candidates = [
        p for p in out_dir.glob("video.*") if p.suffix.lower() != ".wav"
    ]
    if not video_candidates:
        raise RuntimeError("yt-dlp rodou mas nenhum vídeo foi encontrado em " + str(out_dir))
    video_path = max(video_candidates, key=lambda p: p.stat().st_mtime)

    # Extrai o áudio do vídeo já baixado (sem nova transferência de rede),
    # para .wav, mantendo consistência com o resto da pipeline.
    audio_wav = out_dir / (video_path.stem + ".wav")
    cmd_extract = [ffmpeg_exe(), "-y", "-i", str(video_path), "-vn", str(audio_wav)]
    run_subprocess(cmd_extract)

    if not audio_wav.exists():
        raise RuntimeError(f"Falha ao extrair áudio do vídeo baixado: {video_path}")

    return SourceAudio(audio_wav=audio_wav, video_path=video_path)


def download_background_video(url_or_query: str, out_dir: Path) -> Path | None:
    """
    Baixa SÓ a trilha de VÍDEO do YouTube, para servir de fundo (#VIDEO) de
    um pacote cujo áudio veio de arquivo local (caso típico: coleção ripada
    de CD com qualidade melhor que a do YouTube; o clipe é só ilustração).

    `url_or_query` pode ser uma URL do YouTube OU uma busca no formato
    "ytsearch1:artista título" (yt-dlp resolve a busca e baixa o 1º
    resultado - geralmente o clipe oficial, que é o mais relevante).

    Diferenças para download_from_youtube_with_video:
      - NÃO baixa a trilha de áudio (o áudio do pacote é o arquivo local do
        usuário; vídeo sem áudio é menor e o UltraStar toca o vídeo mudo de
        qualquer forma). Se só existir stream combinado, cai para ele.
      - NÃO-FATAL: qualquer falha (sem resultado, rede, formato) retorna
        None - o pacote segue normalmente só com a capa (#COVER), que já é
        o fallback natural do jogo quando não há #VIDEO.
      - Limita a 1080p: fundo de karaokê não precisa de 4K, e o arquivo
        fica muito menor.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # Reaproveita download anterior (mesma filosofia das etapas raw/stems:
    # reprocessar uma música não deve baixar tudo de novo).
    existing = sorted(out_dir.glob("bgvideo.*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if existing:
        print(f"[OK] Videoclipe de fundo já baixado, reaproveitando: {existing[0]}")
        return existing[0]

    # nome fixo (em pasta própria) - evita a heurística de "arquivo mais
    # recente por extensão" usada na pasta raw, que poderia confundir com
    # outros artefatos
    output_template = str(out_dir / "bgvideo.%(ext)s")

    cmd = _yt_dlp_base_cmd() + [
        "-f", "bestvideo[ext=mp4][height<=1080]/bestvideo[height<=1080]/best[ext=mp4]/best",
        # --no-playlist agora está no comando base (_yt_dlp_base_cmd)
        "-o", output_template,
        url_or_query,
    ]
    try:
        # Também passa pelo run_yt_dlp: ganha a retentativa em falha
        # transitória. Continua NÃO-FATAL - o fundo é um extra, e um pacote
        # sem videoclipe é perfeitamente válido.
        run_yt_dlp(cmd, "o videoclipe de fundo")
    except Exception as e:
        print(f"[AVISO] Download do videoclipe de fundo falhou (seguindo sem vídeo): {e}")
        return None

    candidates = sorted(out_dir.glob("bgvideo.*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        print("[AVISO] yt-dlp rodou mas nenhum vídeo de fundo foi encontrado (seguindo sem vídeo).")
        return None
    return candidates[0]


def normalize_local_file(file_path: Path, out_dir: Path) -> Path:
    """
    Para um mp3/wav local: copia para a pasta de trabalho e garante .wav
    (via ffmpeg) para manter consistência com o resto da pipeline.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    dest_wav = out_dir / (file_path.stem + ".wav")

    if file_path.suffix.lower() == ".wav":
        shutil.copy(file_path, dest_wav)
        return dest_wav

    # NOTA sobre o ffmpeg vs yt-dlp: o ffmpeg é um BINÁRIO de sistema (não um
    # módulo Python), instalado no PATH global do Windows - por isso ele
    # continua funcionando via Tauri mesmo sem o venv ativado, e não precisa
    # do mesmo tratamento "sys.executable -m ..." que aplicamos ao yt-dlp.
    cmd = [ffmpeg_exe(), "-y", "-i", str(file_path), str(dest_wav)]
    run_subprocess(cmd)
    return dest_wav


def get_source_audio(
    url: str | None,
    file: str | None,
    out_dir: Path,
    with_video: bool = False,
    max_video_resolution: int = 0,
) -> SourceAudio:
    """
    Ponto de entrada da etapa 1. Sempre retorna um SourceAudio.

    with_video: só tem efeito para fonte YouTube. Quando True, baixa o vídeo
    e o inclui no resultado (para virar #VIDEO no pacote). Para fonte local
    (--file), não há vídeo a incluir e o flag é ignorado.
    max_video_resolution: teto de altura (px) do vídeo, só usado com
    with_video=True. 0 = sem limite.
    """
    if not url and not file:
        raise ValueError("Forneça --url (YouTube) ou --file (mp3/wav local).")

    if url:
        if with_video:
            return download_from_youtube_with_video(url, out_dir, max_resolution=max_video_resolution)
        return SourceAudio(audio_wav=download_from_youtube(url, out_dir))

    # fonte local: nunca há vídeo
    return SourceAudio(audio_wav=normalize_local_file(Path(file), out_dir))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Etapa 1: obter áudio fonte (Fase 0 - teste isolado)")
    parser.add_argument("--url", help="Link do YouTube")
    parser.add_argument("--file", help="Caminho de mp3/wav local")
    parser.add_argument("--out", default="./work/raw", help="Pasta de saída")
    parser.add_argument("--with-video", action="store_true", help="Baixar também o vídeo (só YouTube)")
    args = parser.parse_args()

    result = get_source_audio(args.url, args.file, Path(args.out), with_video=args.with_video)
    print(f"[OK] Áudio pronto em: {result.audio_wav}")
    if result.video_path:
        print(f"[OK] Vídeo baixado em: {result.video_path}")

# -*- coding: utf-8 -*-
"""
fetch_assets.py — baixa capa/fundo/vídeo faltantes de um pacote JÁ EXISTENTE.

Usado pela tela de revisão para sugerir e baixar os assets que faltam num
pacote (nosso, com song_data.json, OU de terceiro, só com o .txt). É LEVE: só
rede (MusicBrainz/Cover Art Archive, fanart.tv, yt-dlp) — nada de GPU ou
modelos de IA. Por isso roda como script avulso chamado pelo Rust (igual ao
read_tags.py), sem passar pelo sidecar persistente.

USO:
    python fetch_assets.py --out-dir DIR --title T --artist A --want cover,bg,video

Imprime UM JSON no stdout:
    {"cover": "<nome>|null", "bg": "...", "video": "...", "errors": ["..."]}

Nunca sai com traceback: qualquer falha por asset vira uma entrada em "errors"
e o download segue para os outros. O caminho de saída é a pasta do pacote
escolhida pelo usuário; os nomes seguem a convenção "[CO]/[BG]" já usada.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from pipeline.download import download_background_video  # noqa: E402
from pipeline.metadata import fetch_metadata  # noqa: E402
from pipeline.proc_utils import ensure_ffmpeg_on_path  # noqa: E402

_AUDIO_EXTS = (".ogg", ".mp3", ".m4a", ".opus", ".wav", ".flac", ".webm")
_VIDEO_EXTS = (".mp4", ".webm", ".mkv")


def _find_chart_txt(d: Path) -> Path | None:
    """O .txt do chart (ignora auxiliares '_*')."""
    for p in sorted(d.glob("*.txt")):
        if not p.name.startswith("_"):
            return p
    return None


def _base_name(d: Path) -> str:
    """Nome-base dos arquivos do pacote: o stem do .txt, ou o do áudio, ou a
    própria pasta (todos já sanitizados quando o pacote foi criado)."""
    txt = _find_chart_txt(d)
    if txt:
        return txt.stem
    for p in d.iterdir():
        if p.suffix.lower() in _AUDIO_EXTS and not p.name.startswith("_"):
            return p.stem
    return d.name


def _find_audio(d: Path) -> Path | None:
    for p in d.iterdir():
        if p.suffix.lower() in _AUDIO_EXTS and not p.name.startswith("_"):
            return p
    return None


def _upsert_header(txt: Path, key: str, value: str) -> None:
    """Insere/atualiza um header '#KEY:value' no .txt UltraStar. Se a chave já
    existe, substitui; senão insere antes da primeira linha de nota."""
    if not txt.exists():
        return
    lines = txt.read_text(encoding="utf-8").splitlines()
    up = key.upper()
    for i, ln in enumerate(lines):
        if ln.strip().upper().startswith(f"#{up}:"):
            lines[i] = f"#{key}:{value}"
            txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return
    # não existia: insere antes da 1ª linha que não é header
    idx = next((i for i, ln in enumerate(lines)
                if not ln.strip().startswith("#")), len(lines))
    lines.insert(idx, f"#{key}:{value}")
    txt.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _update_json(d: Path, field: str, name: str) -> None:
    """Atualiza um campo de nome de arquivo no song_data.json, se existir (para
    a nossa tela de revisão refletir o asset novo)."""
    j = d / "song_data.json"
    if not j.exists():
        return
    try:
        data = json.loads(j.read_text(encoding="utf-8"))
        data[field] = name
        j.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass  # json corrompido não deve travar o download


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--artist", required=True)
    ap.add_argument("--want", required=True, help="cover,bg,video (vírgula)")
    args = ap.parse_args()

    ensure_ffmpeg_on_path()  # yt-dlp/ffmpeg cru (ver proc_utils)
    d = Path(args.out_dir)
    want = {w.strip() for w in args.want.split(",") if w.strip()}
    base = _base_name(d)
    txt = _find_chart_txt(d)
    result: dict = {"cover": None, "bg": None, "video": None, "errors": []}

    # O Rust lê SÓ o JSON da última linha do stdout. fetch_metadata e o yt-dlp
    # imprimem avisos/progresso no stdout - desviamos tudo isso para o stderr
    # (diagnóstico) para que o stdout contenha apenas o JSON final.
    with contextlib.redirect_stdout(sys.stderr):
        _download(d, args.artist, args.title, want, base, txt, result)

    print(json.dumps(result, ensure_ascii=False))
    return 0


def _download(d: Path, artist: str, title: str, want: set, base: str,
              txt: Path | None, result: dict) -> None:
    # Capa e/ou fundo: fetch_metadata baixa a capa (MusicBrainz/CAA) e, com
    # FANARTTV_API_KEY, o fundo 16:9. Uma chamada cobre os dois.
    if want & {"cover", "bg"}:
        try:
            cover_out = d / f"{base} [CO].jpg"
            bg_out = (d / f"{base} [BG].jpg") if "bg" in want else None
            meta = fetch_metadata(
                audio_path=_find_audio(d) or d,
                artist=artist, title=title,
                out_cover_path=cover_out, use_network=True, out_bg_path=bg_out,
            )
            if "cover" in want and meta.cover_path and Path(meta.cover_path).exists():
                result["cover"] = cover_out.name
                _upsert_header(txt, "COVER", cover_out.name) if txt else None
                _update_json(d, "cover_filename", cover_out.name)
            elif "cover" in want:
                result["errors"].append("cover: não encontrada")
            if "bg" in want:
                if meta.background_path and Path(meta.background_path).exists():
                    result["bg"] = bg_out.name
                    _upsert_header(txt, "BACKGROUND", bg_out.name) if txt else None
                    _update_json(d, "background_filename", bg_out.name)
                else:
                    result["errors"].append("bg: não encontrado (requer FANARTTV_API_KEY)")
        except Exception as e:  # noqa: BLE001
            result["errors"].append(f"cover/bg: {e}")

    # Vídeo: clipe do YouTube por busca "artista título".
    if "video" in want:
        try:
            got = download_background_video(f"ytsearch1:{artist} {title}", d)
            if got and Path(got).exists():
                # download_background_video salva como "bgvideo.ext"; renomeia
                # para o padrão do pacote e referencia no header.
                final = d / f"{base}{Path(got).suffix.lower()}"
                if Path(got).resolve() != final.resolve():
                    Path(got).replace(final)
                result["video"] = final.name
                _upsert_header(txt, "VIDEO", final.name) if txt else None
                _update_json(d, "video_filename", final.name)
            else:
                result["errors"].append("video: nenhum clipe encontrado")
        except Exception as e:  # noqa: BLE001
            result["errors"].append(f"video: {e}")


if __name__ == "__main__":
    sys.exit(main())

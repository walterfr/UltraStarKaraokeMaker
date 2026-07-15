#!/usr/bin/env python3
"""
read_tags.py
Lê as tags básicas (título, artista, álbum, ano, gênero) de um arquivo de
áudio e imprime como JSON. O app chama isto ao selecionar um arquivo local,
para PRÉ-PREENCHER o formulário (só os campos que o usuário ainda não digitou).

Depende só de `mutagen` (leve e rápido) - de propósito NÃO importa o resto da
pipeline (whisperx/torch/etc.), para responder em fração de segundo.

Uso:   python read_tags.py <caminho-do-arquivo-de-audio>
Saída: JSON {"title","artist","album","year","genre"} (campos ausentes = null).
Nunca sai com traceback: em qualquer erro imprime {} e encerra com código 0
(ler tags é uma conveniência - falhar aqui não deve incomodar o usuário).
"""
from __future__ import annotations

import json
import re
import sys


def _first(tags, *keys):
    """Primeiro valor não-vazio entre `keys`, normalizado para string.

    Cobre as diferenças de nome de tag entre formatos: chaves "fáceis" e
    minúsculas do mutagen easy=True (title/artist/album/date/genre) e as
    cruas por formato (ID3 TIT2/TPE1..., MP4 \\xa9nam/\\xa9ART...).
    """
    for key in keys:
        try:
            val = tags.get(key)
        except Exception:
            val = None
        if val:
            s = str(val[0]) if isinstance(val, (list, tuple)) else str(val)
            s = s.strip()
            if s:
                return s
    return None


def read_tags(path: str) -> dict:
    from mutagen import File as MutagenFile

    out = {"title": None, "artist": None, "album": None, "year": None, "genre": None}

    # easy=True normaliza os nomes de tag entre mp3/flac/ogg/m4a. Se não abrir
    # (formato que o modo easy não suporta), cai para o modo cru.
    f = None
    try:
        f = MutagenFile(path, easy=True)
    except Exception:
        f = None
    if f is None or getattr(f, "tags", None) is None:
        try:
            f = MutagenFile(path)
        except Exception:
            f = None
    if f is None:
        return out

    tags = f.tags or {}
    out["title"] = _first(tags, "title", "TITLE", "TIT2", "\xa9nam")
    out["artist"] = _first(tags, "artist", "ARTIST", "TPE1", "\xa9ART")
    out["album"] = _first(tags, "album", "ALBUM", "TALB", "\xa9alb")
    out["genre"] = _first(tags, "genre", "GENRE", "TCON", "\xa9gen")

    year_raw = _first(tags, "date", "DATE", "year", "TDRC", "originaldate", "\xa9day")
    if year_raw:
        m = re.search(r"\d{4}", year_raw)
        if m:
            out["year"] = int(m.group())

    return out


if __name__ == "__main__":
    result: dict = {}
    try:
        if len(sys.argv) >= 2:
            result = read_tags(sys.argv[1])
    except Exception:
        result = {}
    # ensure_ascii=True (padrão): escapa acentos como \uXXXX. Assim a saída é
    # 100% ASCII e sobrevive ao stdout em cp1252 do Windows quando rodado como
    # subprocesso (o Rust lê como UTF-8 e o serde_json decodifica os escapes de
    # volta). Sem isso, "Corazón" saía como bytes cp1252 e virava "Coraz�n".
    sys.stdout.write(json.dumps(result))

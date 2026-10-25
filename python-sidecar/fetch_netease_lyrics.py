#!/usr/bin/env python3
"""
fetch_netease_lyrics.py
Busca letra sincronizada (.lrc) na NetEase Cloud Music (music.163.com)
como fallback quando o LRCLIB não possui a letra.

Depende apenas da biblioteca padrão (urllib, json, re, sys) - sem dependências extras.

Uso:   python fetch_netease_lyrics.py "<artista>" "<titulo>"
Saída: JSON {"ok": bool, "trackName": str, "artistName": str, "duration": float, "syncedLyrics": str, "plainLyrics": str}
"""
from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request

CREDIT_KEYS = (
    "作词",
    "作曲",
    "制作人",
    "编曲",
    "吉他",
    "贝斯",
    "鼓",
    "键盘",
    "和音",
    "录音",
    "混音",
    "母带",
    "written by",
    "lyrics by",
    "composed by",
    "producer",
    "arranged",
    "vocals",
    "guitar",
    "bass",
    "drums",
    "piano",
    "recorded at",
    "mixed by",
    "mastered by",
)


def _clean_lrc(raw_lrc: str) -> str:
    cleaned = []
    for line in raw_lrc.splitlines():
        line_str = line.strip()
        m = re.match(r"^\[(\d+:\d+(?:\.\d+)?)\]\s*(.*)$", line_str)
        if m:
            ts, txt = m.group(1), m.group(2).strip()
            low = txt.lower()
            if ":" in txt and any(k in low for k in CREDIT_KEYS):
                continue
            if any(low.startswith(k) for k in ("written by", "lyrics by", "composed by", "recorded at")):
                continue
            if txt:
                cleaned.append(f"[{ts}] {txt}")
        elif line_str:
            cleaned.append(line_str)
    return "\n".join(cleaned).strip()


def _lrc_to_plain(lrc_text: str) -> str:
    plain_lines = []
    for line in lrc_text.splitlines():
        txt = re.sub(r"\[[^\]]*\]", "", line).strip()
        if txt:
            plain_lines.append(txt)
    return "\n".join(plain_lines)


def search_netease(artist: str, title: str) -> dict:
    empty = {
        "ok": False,
        "trackName": None,
        "artistName": None,
        "duration": None,
        "syncedLyrics": None,
        "plainLyrics": None,
    }
    if not artist.strip() or not title.strip():
        return empty

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://music.163.com/",
        "Cookie": "NMTID=00OAVK3xqDG726ITU6jopU6jF2yMk0AAAGCO8l1BA; playerid=94262567;",
    }

    query_str = f"{artist.strip()} {title.strip()}"
    params = urllib.parse.urlencode({"s": query_str, "type": 1, "offset": 0, "limit": 5})
    url = f"https://music.163.com/api/search/pc?{params}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=7) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            songs = data.get("result", {}).get("songs", [])
            if not songs:
                return empty

            for s in songs:
                sid = s.get("id")
                if not sid:
                    continue
                dur = (s.get("duration") or 0) / 1000.0
                art = (s.get("artists") or [{}])[0].get("name", "")
                track = s.get("name", "")

                lrc_url = f"https://music.163.com/api/song/lyric?id={sid}&lv=1"
                req_lrc = urllib.request.Request(lrc_url, headers=headers)
                try:
                    with urllib.request.urlopen(req_lrc, timeout=6) as resp_lrc:
                        lrc_data = json.loads(resp_lrc.read().decode("utf-8", errors="replace"))
                        raw_lrc = lrc_data.get("lrc", {}).get("lyric", "")
                        if raw_lrc and raw_lrc.strip():
                            cleaned = _clean_lrc(raw_lrc)
                            if cleaned:
                                plain = _lrc_to_plain(cleaned)
                                return {
                                    "ok": True,
                                    "trackName": track,
                                    "artistName": art,
                                    "duration": dur,
                                    "syncedLyrics": cleaned,
                                    "plainLyrics": plain,
                                }
                except Exception:
                    continue
    except Exception:
        return empty

    return empty


def main() -> None:
    if len(sys.argv) < 3:
        print(json.dumps({"ok": False}))
        return
    artist = sys.argv[1]
    title = sys.argv[2]
    res = search_netease(artist, title)
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""Parse a UltraStar .txt chart into a Chart (gold-chart reader for the eval
harness). Ported from usdx-autochart (MIT, Alejololer/usdx-autochart) --
USKMaker only had writers (pipeline/ultrastar_writer.py, rust-core) until now.

Mirrors the grammar in USDX's src/base/USong.pas (ReadTXTHeader + LoadOpenedSong):
  header lines start with '#TAG:value'
  note lines:   <type> <startBeat> <durationBeats> <pitch> <lyric>
  break lines:  - <startBeat> [relativeOffset]
  duet tracks:  P1 / P2 (flattened - see parse())     end marker: E

Timing model (same formula validated against D:\\Canciones Karaoke charts):
  time_s = GAP/1000 + beat * 60 / (fileBPM * 4)
Note lyrics are NOT stripped: trailing/leading spaces mark word boundaries.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

# USDX note type -> leading character (see USong.pas / UMusic.pas TNoteType)
NOTE_CHARS = {
    "normal": ":",
    "golden": "*",
    "freestyle": "F",
    "rap": "R",
    "rapgolden": "G",
}
CHAR_TO_KIND = {v: k for k, v in NOTE_CHARS.items()}


@dataclass
class Note:
    start_beat: int
    duration: int          # in beats
    pitch: int             # integer semitone, 0 = C4
    text: str              # raw lyric, spaces preserved (word boundaries!)
    kind: str = "normal"   # key of NOTE_CHARS


@dataclass
class Line:
    """A sentence. `break_beat` is the beat on the '-' break before it."""
    notes: List[Note] = field(default_factory=list)
    break_beat: Optional[int] = None


@dataclass
class Chart:
    title: str
    artist: str
    bpm: float                  # the raw #BPM header value (the "file BPM")
    gap_ms: float               # #GAP in milliseconds
    audio: str
    lines: List[Line] = field(default_factory=list)
    language: Optional[str] = None
    genre: Optional[str] = None
    year: Optional[int] = None

    def seconds_per_beat(self) -> float:
        return 15.0 / self.bpm  # 60 / (fileBPM * 4)

    def beat_to_time(self, beat: int) -> float:
        return self.gap_ms / 1000.0 + beat * self.seconds_per_beat()


def _to_float(value: str) -> float:
    # USDX StrToFloatI18n accepts both ',' and '.' as the decimal separator.
    return float(value.strip().replace(",", "."))


def parse(text: str) -> Chart:
    """Parse a chart. Duet ``P1``/``P2`` markers are flattened into a single
    ``Chart.lines`` - USKMaker generates single-track charts only today, and a
    flattened [MULTI] gold is exactly what a single player sings when covering
    both parts, so the time-domain ``evaluate`` compares against that. If duet
    generation lands later, re-port usdx-autochart's ``keep_tracks`` mode."""
    header = {}
    lines: List[Line] = []
    cur = Line()  # first sentence has no preceding break
    started = False

    def flush():
        nonlocal cur
        if cur.notes or cur.break_beat is not None:
            lines.append(cur)
        cur = Line()

    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        if line.startswith("#") and not started:
            if ":" in line:
                tag, _, val = line[1:].partition(":")
                header[tag.strip().upper()] = val.strip()
            continue

        token = line[0]
        if token in CHAR_TO_KIND:
            started = True
            # 4 fields + remainder lyric; the lyric may contain/end with spaces
            m = re.match(r"^(.)\s+(-?\d+)\s+(\d+)\s+(-?\d+)\s?(.*)$", line)
            if not m:
                continue
            _, sb, dur, pitch, lyric = m.groups()
            cur.notes.append(
                Note(int(sb), int(dur), int(pitch), lyric, CHAR_TO_KIND[token])
            )
        elif token == "-":
            started = True
            parts = line.split()
            flush()
            cur.break_beat = int(parts[1]) if len(parts) > 1 else None
        elif token in ("E",):
            break
        elif token in ("P", "p"):
            # duet track marker ("P 1"/"P1") - notes keep absolute beats, so
            # just keep appending: the tracks interleave when time-sorted.
            started = True
            continue

    flush()

    audio = header.get("AUDIO") or header.get("MP3") or ""
    return Chart(
        title=header.get("TITLE", ""),
        artist=header.get("ARTIST", ""),
        bpm=_to_float(header["BPM"]) if "BPM" in header else 0.0,
        gap_ms=_to_float(header.get("GAP", "0")),
        audio=audio,
        lines=lines,
        language=header.get("LANGUAGE"),
        genre=header.get("GENRE"),
        year=int(header["YEAR"]) if header.get("YEAR", "").isdigit() else None,
    )


def is_relative(path: str) -> bool:
    """#RELATIVE charts restart beats per line; this parser doesn't model that,
    so callers must skip them."""
    try:
        with open(path, "rb") as f:
            head = f.read(4096).decode("latin-1")
        return bool(re.search(r"(?im)^#RELATIVE\s*:\s*yes", head))
    except OSError:
        return False


def read_file(path: str) -> Chart:
    # Community charts are frequently CP1252; fall through from utf-8.
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                return parse(f.read())
        except UnicodeDecodeError:
            continue
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return parse(f.read())

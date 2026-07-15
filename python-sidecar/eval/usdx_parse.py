# -*- coding: utf-8 -*-
"""Parse a UltraStar .txt chart into a Chart (gold-chart reader for the eval
harness). Ported from usdx-autochart (MIT, Alejololer/usdx-autochart) --
USKMaker only had writers (pipeline/ultrastar_writer.py, rust-core) until now.

Mirrors the grammar in USDX's src/base/USong.pas (ReadTXTHeader + LoadOpenedSong):
  header lines start with '#TAG:value'
  note lines:   <type> <startBeat> <durationBeats> <pitch> <lyric>
  break lines:  - <startBeat> [relativeOffset]
  duet tracks:  P1 / P2     end marker: E

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
    # Duet: with keep_tracks=True, one list of Lines per singer (P1/P2 blocks);
    # `lines` is then empty.
    tracks: Optional[List[List[Line]]] = None
    p1: Optional[str] = None
    p2: Optional[str] = None
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


def parse(text: str, *, keep_tracks: bool = False) -> Chart:
    """Parse a chart. By default duet ``P1``/``P2`` markers are flattened into a
    single ``Chart.lines`` (enough for the flattened time-domain ``evaluate``).
    With ``keep_tracks=True`` the P-blocks are kept as separate ``Chart.tracks``
    (used by ``evaluate_duet`` to score per-singer attribution)."""
    header = {}
    lines: List[Line] = []
    tracks: List[List[Line]] = []
    cur = Line()  # first sentence has no preceding break
    started = False

    def target() -> List[Line]:
        return tracks[-1] if (keep_tracks and tracks) else lines

    def flush():
        nonlocal cur
        if cur.notes or cur.break_beat is not None:
            target().append(cur)
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
            # duet track marker: community charts use "P 1"/"P 2", generated
            # ones "P1"/"P2" - both key on the first char.
            started = True
            if keep_tracks:
                flush()
                tracks.append([])
            continue

    flush()

    audio = header.get("AUDIO") or header.get("MP3") or ""
    p1 = header.get("DUETSINGERP1") or header.get("P1")
    p2 = header.get("DUETSINGERP2") or header.get("P2")
    keep = keep_tracks and bool(tracks)
    return Chart(
        title=header.get("TITLE", ""),
        artist=header.get("ARTIST", ""),
        bpm=_to_float(header["BPM"]) if "BPM" in header else 0.0,
        gap_ms=_to_float(header.get("GAP", "0")),
        audio=audio,
        lines=[] if keep else lines,
        tracks=tracks if keep else None,
        p1=p1,
        p2=p2,
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


def read_file(path: str, *, keep_tracks: bool = False) -> Chart:
    # Community charts are frequently CP1252; fall through from utf-8.
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                return parse(f.read(), keep_tracks=keep_tracks)
        except UnicodeDecodeError:
            continue
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return parse(f.read(), keep_tracks=keep_tracks)

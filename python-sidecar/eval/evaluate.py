# -*- coding: utf-8 -*-
"""Score a generated chart against a reference (gold) chart.

Ported from usdx-autochart (MIT, Alejololer/usdx-autochart) and adapted to
USKMaker's artifacts: the generated side can be either a written .txt or the
canonical ``song_data.json`` (what rust-core renders the .txt from).

Everything is compared in the time domain (seconds) so that differing BPM/GAP
choices between the two charts don't bias the result. Reports note-count ratio,
onset-timing error on matched notes, relative-pitch contour correlation, and a
lyric-similarity ratio.

Scope: single-player evaluation only, matching what USKMaker generates today
(single-track charts). Gold [MULTI] duets are flattened by the parser - both
parts merged in time order, which is exactly what a single player sings when
covering both - and scored with the same metrics. If duet generation lands
later, usdx-autochart's per-singer scoring (``evaluate_duet``: track pairing +
singer-assignment accuracy) can be re-ported from the same MIT source.

CLI:
    python eval/evaluate.py "New Output/Song/song_data.json" "D:/Canciones Karaoke/Artist - Title/Artist - Title.txt"
"""
from __future__ import annotations

import difflib
import json
import re
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import usdx_parse
    from usdx_parse import Chart, Line, Note, CHAR_TO_KIND
else:
    from . import usdx_parse
    from .usdx_parse import Chart, Line, Note, CHAR_TO_KIND


# ---------- loaders ----------

def chart_from_song_data(data: dict) -> Chart:
    """Build a Chart from USKMaker's ``song_data.json`` (the canonical artifact
    the Rust core writes the .txt from). Single-track today."""
    breaks = set(data.get("phrase_breaks_after_index") or [])
    lines: List[Line] = []
    cur = Line()
    for i, n in enumerate(data.get("notes") or []):
        cur.notes.append(Note(
            start_beat=int(n["start_beat"]),
            duration=int(n["duration_beats"]),
            pitch=int(n["pitch"]),
            text=n.get("text", ""),
            kind=CHAR_TO_KIND.get(n.get("note_type", ":"), "normal"),
        ))
        if i in breaks:
            lines.append(cur)
            cur = Line()
    if cur.notes:
        lines.append(cur)
    return Chart(
        title=data.get("title", ""),
        artist=data.get("artist", ""),
        bpm=float(data["bpm"]),
        gap_ms=float(data.get("gap_ms", 0)),
        audio=data.get("mp3_filename", ""),
        lines=lines,
        language=data.get("language"),
    )


def interpolated_fraction(data: dict) -> Optional[float]:
    """Fraction of song_data.json notes whose timing was interpolated (not
    measured) - the pipeline's internal quality signal, reported as a bonus
    metric alongside the gold comparison."""
    notes = data.get("notes") or []
    sourced = [n for n in notes if n.get("source")]
    if not sourced:
        return None
    interp = sum(1 for n in sourced if n["source"] == "interpolated")
    return round(interp / len(sourced), 3)


def load_chart(path: str) -> Tuple[Chart, Optional[dict]]:
    """Load a .txt chart or a song_data.json. Returns (chart, song_data|None)."""
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return chart_from_song_data(data), data
    return usdx_parse.read_file(path), None


# ---------- time-domain scoring (ported as-is) ----------

@dataclass
class TimedNote:
    start: float
    end: float
    pitch: int
    text: str


def _flatten(chart: Chart) -> List[TimedNote]:
    out: List[TimedNote] = []
    for line in chart.lines:
        for n in line.notes:
            out.append(TimedNote(
                chart.beat_to_time(n.start_beat),
                chart.beat_to_time(n.start_beat + n.duration),
                n.pitch, n.text,
            ))
    out.sort(key=lambda t: t.start)
    return out


def _match(gen: List[TimedNote], ref: List[TimedNote], tol: float = 0.3):
    """Greedy nearest-onset matching within `tol` seconds."""
    pairs: List[Tuple[TimedNote, TimedNote]] = []
    used = [False] * len(gen)
    for r in ref:
        best, bestd = -1, tol
        for i, g in enumerate(gen):
            if used[i]:
                continue
            d = abs(g.start - r.start)
            if d < bestd:
                best, bestd = i, d
        if best >= 0:
            used[best] = True
            pairs.append((gen[best], r))
    return pairs


def _norm_text(notes: List[TimedNote]) -> str:
    s = "".join(n.text for n in notes).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^\w\sáéíóúñü]", "", s)).strip()


def _pair_metrics(gen: List[TimedNote], ref: List[TimedNote],
                  onset_tol: float) -> dict:
    """Core metrics for one gen<->ref note-list pairing."""
    pairs = _match(gen, ref, onset_tol)
    onset_err = [abs(g.start - r.start) for g, r in pairs]
    if pairs:
        gmed = statistics.median(g.pitch for g, _ in pairs)
        rmed = statistics.median(r.pitch for _, r in pairs)
        gp = np.array([g.pitch - gmed for g, _ in pairs], dtype=float)
        rp = np.array([r.pitch - rmed for _, r in pairs], dtype=float)
        pitch_corr = float(np.corrcoef(gp, rp)[0, 1]) if len(gp) > 1 and gp.std() and rp.std() else 0.0
        pitch_within2 = float(np.mean(np.abs(gp - rp) <= 2))
    else:
        pitch_corr, pitch_within2 = 0.0, 0.0
    # autojunk=False: difflib's popularity heuristic treats common characters
    # in >200-char strings as junk, making ratios on full lyrics near-random
    lyric = difflib.SequenceMatcher(None, _norm_text(gen), _norm_text(ref),
                                    autojunk=False).ratio()
    return {
        "gen_notes": len(gen),
        "ref_notes": len(ref),
        "note_count_ratio": round(len(gen) / len(ref), 3) if ref else 0.0,
        "matched": len(pairs),
        "match_rate_vs_ref": round(len(pairs) / len(ref), 3) if ref else 0.0,
        "onset_err_ms_median": round(statistics.median(onset_err) * 1000, 1) if onset_err else None,
        "onset_err_ms_mean": round(statistics.mean(onset_err) * 1000, 1) if onset_err else None,
        "pitch_contour_corr": round(pitch_corr, 3),
        "pitch_within_2st_rate": round(pitch_within2, 3),
        "lyric_similarity": round(lyric, 3),
    }


def evaluate(generated: Chart, reference: Chart, onset_tol: float = 0.3) -> dict:
    gen = _flatten(generated)
    ref = _flatten(reference)
    out = _pair_metrics(gen, ref, onset_tol)
    out["gen_span_s"] = round(gen[-1].end - gen[0].start, 1) if gen else 0.0
    out["ref_span_s"] = round(ref[-1].end - ref[0].start, 1) if ref else 0.0
    return out


def format_report(metrics: dict) -> str:
    lines = ["=== generated vs reference ==="]
    for k, v in metrics.items():
        lines.append(f"  {k:24s}: {v}")
    return "\n".join(lines)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Score a generated chart (.txt or song_data.json) against a gold .txt")
    ap.add_argument("generated")
    ap.add_argument("gold")
    ap.add_argument("--tol", type=float, default=0.3, help="onset match tolerance in seconds")
    ap.add_argument("--json", dest="json_out", default=None, help="also write metrics to this JSON file")
    args = ap.parse_args()

    gen_chart, song_data = load_chart(args.generated)
    gold_chart, _ = load_chart(args.gold)

    metrics = evaluate(gen_chart, gold_chart, args.tol)
    if song_data is not None:
        metrics["gen_interpolated_frac"] = interpolated_fraction(song_data)
    print(format_report(metrics))

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(metrics, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())

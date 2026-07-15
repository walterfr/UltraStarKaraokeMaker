# -*- coding: utf-8 -*-
"""Stage-level eval harness: score USKMaker's pipeline stages *independently*
against gold hand-charted UltraStar songs from a local library, instead of only
comparing final output (that's eval/evaluate.py's job).

Ported from usdx-autochart (MIT, Alejololer/usdx-autochart) with the stages
swapped for USKMaker's own (python-sidecar/pipeline/):

  align : align.align_lyrics_to_audio on the cached Demucs vocal stem, with
          lyrics extracted from the gold chart -> word recall + onset/end error
          vs the gold word times, plus the interpolated-word fraction and
          whether the lead-vocal rescue (main.py "Etapa 4b") fired/won -
          the background-choir failure detector.
  pitch : SwiftF0 voiced-median MIDI inside *gold* note boundaries vs gold
          pitch, relative (medians subtracted): within-2-semitones rate +
          contour correlation - isolates pitch error from timing error.
  bpm   : beatgrid.detect_bpm (on the instrumental stem, like main.py) vs the
          gold #BPM header, mod power-of-two multiple.

Stages usdx-autochart replays that USKMaker doesn't have (MMS_FA forced
alignment, syllabify_es proportional spread) are deliberately dropped.

Resumable: the run dir is keyed by n+seed (or the seed set); songs with an
existing result/error JSON are skipped. Demucs stems, alignment, and pitch are
cached per song under <run_dir>/cache/<slug>/ - Demucs is nondeterministic
(randomized shifts), so FIXED stems are what make A/B comparisons between code
versions meaningful. Gold onsets are themselves ~50 ms-grid quantized and
stylistic - differences below ~25-50 ms are noise, not signal.

  python eval/library_replay.py --n 20 --seed 0
  python eval/library_replay.py --seed-set eval/seed_set.json
  python eval/library_replay.py --n 20 --seed 0 --aggregate-only
"""
from __future__ import annotations

import argparse
import csv
import difflib
import json
import math
import os
import random
import re
import shutil
import statistics
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[0]))  # python-sidecar root, for `pipeline`
sys.path.insert(0, str(_HERE))             # eval dir, for sibling usdx_parse

import usdx_parse  # noqa: E402


# gold-chart #LANGUAGE header -> whisper language code; unmapped -> song skipped
LANG_CODES = {
    "spanish": "es", "español": "es", "espanol": "es",
    "english": "en", "french": "fr", "français": "fr", "german": "de",
    "deutsch": "de", "italian": "it", "portuguese": "pt", "português": "pt",
    "japanese": "ja", "korean": "ko", "chinese": "zh",
    "catalan": "ca", "catalán": "ca", "gallego": "gl",
    "dutch": "nl", "swedish": "sv", "finnish": "fi", "russian": "ru",
    "polish": "pl", "turkish": "tr", "latin": "la",
}


def log(msg: str) -> None:
    print(f"[replay] {msg}", flush=True)


def slugify(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")[:80]


def scan_library(lib: str) -> list[dict]:
    """Folders with exactly one .mp3 and a gold (non-MULTI) .txt."""
    songs = []
    for name in sorted(os.listdir(lib)):
        d = os.path.join(lib, name)
        if not os.path.isdir(d):
            continue
        try:
            files = os.listdir(d)
        except OSError:
            continue
        mp3s = [f for f in files if f.lower().endswith(".mp3")]
        txts = [f for f in files if f.lower().endswith(".txt")]
        golds = [f for f in txts if "[multi]" not in f.lower()]
        if len(mp3s) != 1 or not golds:
            continue
        songs.append({
            "name": name,
            "mp3": os.path.join(d, mp3s[0]),
            "gold": os.path.join(d, sorted(golds, key=len)[0]),
        })
    return songs


# ---------- gold chart -> time-domain events ----------

def _key(word: str) -> str:
    w = unicodedata.normalize("NFKD", word.lower())
    w = "".join(c for c in w if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", w)


def gold_words(chart) -> list[dict]:
    """Time-domain words from a parsed gold chart. A note is a syllable; a new
    word starts at a line break, after a note with trailing space, or on a note
    with leading space. '~'/empty notes are holds extending the previous
    syllable. Each word: {text, start, end, line_index}."""
    words: list[dict] = []
    for li, line in enumerate(chart.lines):
        word = None
        prev_trail = False
        for n in line.notes:
            raw, txt = n.text, n.text.strip()
            s = chart.beat_to_time(n.start_beat)
            e = chart.beat_to_time(n.start_beat + n.duration)
            if txt in ("~", ""):  # hold continuation
                if word:
                    word["end"] = max(word["end"], e)
                if raw:
                    prev_trail = raw[-1:].isspace()
                continue
            if word is None or prev_trail or raw[:1].isspace():
                if word:
                    words.append(word)
                word = {"text": txt, "start": s, "end": e, "line_index": li}
            else:
                word["text"] += txt
                word["end"] = max(word["end"], e)
            prev_trail = raw[-1:].isspace() if raw else False
        if word:
            words.append(word)
    return words


def gold_notes(chart) -> list[tuple]:
    """Pitched notes as (start_s, end_s, pitch); freestyle/rap carry no pitch."""
    out = []
    for line in chart.lines:
        for n in line.notes:
            if n.kind in ("normal", "golden"):
                out.append((chart.beat_to_time(n.start_beat),
                            chart.beat_to_time(n.start_beat + n.duration),
                            n.pitch))
    return out


def gold_lyrics_text(gwords: list[dict]) -> str:
    """Plain lyrics (one line per gold chart line) - align.py's input format."""
    by_line: dict[int, list[str]] = defaultdict(list)
    for w in gwords:
        by_line[w["line_index"]].append(w["text"])
    return "\n".join(" ".join(by_line[li]) for li in sorted(by_line)) + "\n"


# ---------- matching + metrics ----------

def match_words(gold: list[dict], hyp: list[dict]) -> list[tuple[int, int]]:
    """Text-match gold<->hypothesis words (difflib on normalized keys).
    Returns (gold_idx, hyp_idx) pairs."""
    ga = [(i, _key(w["text"])) for i, w in enumerate(gold)]
    ha = [(j, _key(w["text"])) for j, w in enumerate(hyp)]
    ga = [(i, k) for i, k in ga if k]
    ha = [(j, k) for j, k in ha if k]
    sm = difflib.SequenceMatcher(a=[k for _, k in ga], b=[k for _, k in ha],
                                 autojunk=False)
    pairs = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag not in ("equal", "replace"):
            continue
        for k in range(min(i2 - i1, j2 - j1)):
            if tag == "replace" and difflib.SequenceMatcher(
                    a=ga[i1 + k][1], b=ha[j1 + k][1]).ratio() < 0.5:
                continue
            pairs.append((ga[i1 + k][0], ha[j1 + k][0]))
    return pairs


def _err_stats(errs: list[float]) -> dict | None:
    if not errs:
        return None
    a = sorted(abs(x) for x in errs)
    return {"n": len(a),
            "median_ms": round(a[len(a) // 2] * 1000, 1),
            "mae_ms": round(sum(a) / len(a) * 1000, 1),
            "p90_ms": round(a[int(0.9 * (len(a) - 1))] * 1000, 1),
            "bias_ms": round(statistics.median(errs) * 1000, 1)}


def timing_stats(gold: list[dict], hyp: list[dict],
                 pairs: list[tuple[int, int]]) -> dict:
    onset = [hyp[j]["start"] - gold[i]["start"] for i, j in pairs]
    end = [hyp[j]["end"] - gold[i]["end"] for i, j in pairs]
    # within_1s is the headline number from previous manual validations
    # (~65-90% is the normal band on good songs). recall is ~1 by
    # construction here (align_lyrics_to_audio emits one timing per lyric
    # word) - it only drops when _key() filters out unmatchable tokens.
    within_1s = (round(sum(1 for x in onset if abs(x) <= 1.0) / len(onset), 3)
                 if onset else 0.0)
    return {"recall": round(len(pairs) / len(gold), 3) if gold else 0.0,
            "within_1s": within_1s,
            "onset": _err_stats(onset), "end": _err_stats(end)}


def pitch_metrics(notes: list[tuple], times, hz, voicing) -> dict:
    """SwiftF0 voiced-median MIDI inside *gold* note boundaries vs gold pitch
    (relative, medians subtracted)."""
    gold_p, est_m = [], []
    for s, e, p in notes:
        mask = (times >= s) & (times < e) & voicing & (hz > 0)
        if mask.sum() < 2:
            continue
        est_m.append(69.0 + 12.0 * math.log2(float(np.median(hz[mask])) / 440.0))
        gold_p.append(p)
    out = {"n_notes": len(notes), "n_scored": len(gold_p),
           "coverage": round(len(gold_p) / len(notes), 3) if notes else 0.0}
    if len(gold_p) >= 10:
        g = np.array(gold_p, float)
        c = np.array(est_m, float)
        g -= np.median(g)
        c -= np.median(c)
        out["within_2st"] = round(float(np.mean(np.abs(g - c) <= 2)), 3)
        out["contour_corr"] = (round(float(np.corrcoef(g, c)[0, 1]), 3)
                               if g.std() and c.std() else 0.0)
    return out


def bpm_metric(est: float | None, file_bpm: float) -> dict | None:
    """Deviation of the estimate from the gold #BPM, mod power-of-two multiple
    (gold file BPMs are often the musical BPM x2/x4 for grid fineness)."""
    if not est or est <= 0 or not file_bpm:
        return None
    k = file_bpm / est
    p = 2.0 ** round(math.log2(k))
    return {"est": round(est, 1), "file_bpm": file_bpm, "mult": p,
            "dev": round(abs(k / p - 1), 4)}


# ---------- per-song run (cached, resumable) ----------

def _cached_stems(mp3: str, cache: Path, device: str) -> tuple[Path, Path]:
    """Demucs stems, separated once and cached: nondeterministic between runs,
    so a fixed stem is what makes cross-run comparisons meaningful."""
    vocals = cache / "vocals.wav"
    instrumental = cache / "no_vocals.wav"
    if vocals.exists() and instrumental.exists():
        return vocals, instrumental
    from pipeline.separate import separate_vocals
    log("  demucs...")
    tmp = cache / "demucs_tmp"
    stems = separate_vocals(Path(mp3), tmp, device=device)
    shutil.move(str(stems.vocals), str(vocals))
    shutil.move(str(stems.instrumental), str(instrumental))
    shutil.rmtree(tmp, ignore_errors=True)
    return vocals, instrumental


def _timings_to_dicts(timings) -> list[dict]:
    return [{"text": t.word, "start": t.start, "end": t.end,
             "source": t.source, "score": t.score} for t in timings]


def _cached_alignment(stem: Path, cache: Path, gwords: list[dict],
                      language: str, device: str) -> dict:
    """align.align_lyrics_to_audio on the cached stem, mirroring main.py's
    Etapa 4b rescue: if >10% of words end up interpolated, isolate the lead
    vocal and re-align, keeping whichever result has fewer interpolated words
    (the pipeline's internal quality signal - no ground truth needed)."""
    aj = cache / "align.json"
    if aj.exists():
        with open(aj, encoding="utf-8") as f:
            return json.load(f)

    from pipeline.align import align_lyrics_to_audio, alignment_stats

    lyrics_path = cache / "lyrics.txt"
    lyrics_path.write_text(gold_lyrics_text(gwords), encoding="utf-8")

    log(f"  align (whisperx, lang={language})...")
    timings = align_lyrics_to_audio(stem, lyrics_path, language=language,
                                    device=device)
    interp = alignment_stats(timings)["by_source"]["interpolated"]
    interp_frac = interp / max(len(timings), 1)

    rescue = {"tried": False, "won": False, "base_interp_frac": round(interp_frac, 3)}
    if interp_frac > 0.10:
        rescue["tried"] = True
        log(f"  rescue: {100 * interp_frac:.0f}% interpolated, isolating lead vocal...")
        try:
            from pipeline.separate import isolate_lead_vocal
            lead = cache / "lead_vocals.wav"
            if not lead.exists():
                lead = isolate_lead_vocal(stem, cache)
            retry = align_lyrics_to_audio(lead, lyrics_path, language=language,
                                          device=device)
            retry_interp = alignment_stats(retry)["by_source"]["interpolated"]
            rescue["lead_interp_frac"] = round(retry_interp / max(len(retry), 1), 3)
            if retry_interp < interp:
                rescue["won"] = True
                timings = retry
        except Exception as e:  # noqa: BLE001 - non-fatal, same as main.py
            rescue["error"] = repr(e)
            log(f"  rescue failed (non-fatal): {e!r}")

    stats = alignment_stats(timings)
    result = {"words": _timings_to_dicts(timings),
              "interp_frac": round(stats["by_source"]["interpolated"]
                                   / max(stats["total"], 1), 3),
              "rescue": rescue}
    with open(aj, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    return result


def _cached_pitch(stem: Path, cache: Path):
    pz = cache / "pitch.npz"
    if pz.exists():
        d = np.load(pz)
        return d["t"], d["hz"], d["voicing"].astype(bool)
    import soundfile as sf
    from pipeline.pitch import PitchExtractor
    log("  pitch (SwiftF0)...")
    duration = sf.info(str(stem)).duration
    track = PitchExtractor().extract_word_track(str(stem), 0.0, duration)
    np.savez_compressed(pz, t=track.timestamps, hz=track.pitch_hz,
                        voicing=track.voicing)
    return track.timestamps, track.pitch_hz, track.voicing


def _run_song(song: dict, run_dir: str, slug: str, device: str) -> dict:
    chart = usdx_parse.read_file(song["gold"])
    gwords = gold_words(chart)
    if len(gwords) < 30:
        raise ValueError(f"only {len(gwords)} gold words")
    language = LANG_CODES.get((chart.language or "").strip().lower())
    if not language:
        raise ValueError(f"unmapped gold #LANGUAGE {chart.language!r}")
    notes = gold_notes(chart)
    cache = Path(run_dir) / "cache" / slug
    cache.mkdir(parents=True, exist_ok=True)

    vocals, instrumental = _cached_stems(song["mp3"], cache, device)
    align_res = _cached_alignment(vocals, cache, gwords, language, device)
    times, hz, voicing = _cached_pitch(vocals, cache)

    try:
        from pipeline.beatgrid import detect_bpm
        bpm_est = detect_bpm(instrumental).bpm
    except Exception:  # noqa: BLE001 - informational metric
        bpm_est = None

    span = gwords[-1]["end"] - gwords[0]["start"]
    hyp = align_res["words"]
    pairs = match_words(gwords, hyp)
    return {
        "song": song["name"],
        "lang_group": song.get("lang_group"),
        "wpm": round(len(gwords) / (span / 60), 1) if span > 0 else None,
        "n_gold_words": len(gwords),
        "align": {"n_words": len(hyp),
                  "interp_frac": align_res["interp_frac"],
                  "rescue": align_res["rescue"],
                  **timing_stats(gwords, hyp, pairs)},
        "pitch": pitch_metrics(notes, times, hz, voicing),
        "bpm": bpm_metric(bpm_est, chart.bpm),
    }


def run_song(song: dict, run_dir: str, device: str) -> None:
    slug = slugify(song["name"])
    rj = os.path.join(run_dir, "results", f"{slug}.json")
    ej = os.path.join(run_dir, "results", f"{slug}.error.json")
    if os.path.exists(rj) or os.path.exists(ej):
        log(f"[skip] {song['name']} (already done)")
        return
    log(f"[run ] {song['name']}")
    try:
        res = _run_song(song, run_dir, slug, device)
        with open(rj, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1, default=float)
    except Exception as e:  # noqa: BLE001 - one bad song must not kill the run
        log(f"       FAILED: {e!r}")
        with open(ej, "w", encoding="utf-8") as f:
            json.dump({"error": repr(e)}, f)
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass


# ---------- sampling ----------

def build_manifest(lib: str, runs_root: str) -> list[dict]:
    """Usable songs with lang_group + gold wpm; cached (one full-library parse)."""
    os.makedirs(runs_root, exist_ok=True)
    path = os.path.join(runs_root, "library_manifest.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
        if m.get("lib") == lib:
            return m["songs"]
    songs = scan_library(lib)
    out = []
    for i, s in enumerate(songs):
        if i and i % 1000 == 0:
            log(f"scanning gold charts {i}/{len(songs)}...")
        try:
            if usdx_parse.is_relative(s["gold"]):
                continue
            chart = usdx_parse.read_file(s["gold"])
            gw = gold_words(chart)
            if len(gw) < 30:
                continue
            span = gw[-1]["end"] - gw[0]["start"]
            if span < 60:
                continue
            code = LANG_CODES.get((chart.language or "").strip().lower(), "other")
            out.append({"name": s["name"], "mp3": s["mp3"], "gold": s["gold"],
                        "lang_group": code if code in ("es", "en") else "other",
                        "wpm": round(len(gw) / (span / 60), 1)})
        except Exception:  # noqa: BLE001 - unparseable gold: not usable
            continue
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"lib": lib, "songs": out}, f, ensure_ascii=False)
    log(f"manifest: {len(out)} usable songs (cached at {path})")
    return out


def stratified_sample(manifest: list[dict], n: int, seed: int):
    """Proportional allocation over lang_group x wpm tercile, seeded."""
    wpms = sorted(s["wpm"] for s in manifest)
    t1, t2 = wpms[len(wpms) // 3], wpms[2 * len(wpms) // 3]

    def terc(w):
        return 0 if w < t1 else (1 if w < t2 else 2)

    strata: dict[tuple, list] = defaultdict(list)
    for s in manifest:
        strata[(s["lang_group"], terc(s["wpm"]))].append(s)
    keys = sorted(strata)
    total = len(manifest)
    alloc = {k: max(1, round(n * len(strata[k]) / total)) for k in keys}
    while sum(alloc.values()) > n:
        k = max(keys, key=lambda k: alloc[k])
        alloc[k] -= 1
    while sum(alloc.values()) < n:
        k = max(keys, key=lambda k: len(strata[k]) - alloc[k])
        alloc[k] += 1
    rng = random.Random(seed)
    sample = []
    for k in keys:
        sample.extend(rng.sample(strata[k], min(alloc[k], len(strata[k]))))
    return sample, (t1, t2)


def seed_set_sample(seed_set_path: str, manifest: list[dict]) -> list[dict]:
    """The curated seed set (eval/seed_set.json): songs referenced by library
    folder name - each dev supplies audio + gold .txt locally; nothing
    copyrighted lives in the repo."""
    with open(seed_set_path, encoding="utf-8") as f:
        seed_set = json.load(f)
    by_name = {s["name"]: s for s in manifest}
    sample = []
    for entry in seed_set["songs"]:
        s = by_name.get(entry["folder"])
        if s:
            sample.append(s)
        else:
            log(f"[miss] seed-set song not in library (or unusable): {entry['folder']}")
    return sample


# ---------- aggregation ----------

FLAT_FIELDS = ["song", "lang_group", "wpm", "n_gold_words",
               "recall", "within_1s", "onset_med_ms", "onset_mae_ms",
               "onset_p90_ms", "bias_ms", "end_med_ms", "interp_frac",
               "rescue_tried", "rescue_won",
               "pitch_coverage", "pitch_within_2st", "pitch_corr",
               "bpm_est", "bpm_mult", "bpm_dev", "error"]

KEY_METRICS = ["within_1s", "onset_med_ms", "interp_frac",
               "pitch_within_2st", "pitch_corr", "bpm_dev"]


def _flat(r: dict) -> dict:
    a = r.get("align") or {}
    ao = a.get("onset") or {}
    ae = a.get("end") or {}
    resc = a.get("rescue") or {}
    pi, bp = r.get("pitch") or {}, r.get("bpm") or {}
    return {
        "n_gold_words": r.get("n_gold_words"),
        "recall": a.get("recall"), "within_1s": a.get("within_1s"),
        "onset_med_ms": ao.get("median_ms"),
        "onset_mae_ms": ao.get("mae_ms"), "onset_p90_ms": ao.get("p90_ms"),
        "bias_ms": ao.get("bias_ms"), "end_med_ms": ae.get("median_ms"),
        "interp_frac": a.get("interp_frac"),
        "rescue_tried": resc.get("tried"), "rescue_won": resc.get("won"),
        "pitch_coverage": pi.get("coverage"),
        "pitch_within_2st": pi.get("within_2st"), "pitch_corr": pi.get("contour_corr"),
        "bpm_est": bp.get("est"), "bpm_mult": bp.get("mult"), "bpm_dev": bp.get("dev"),
    }


def aggregate(sample: list[dict], run_dir: str) -> None:
    rows = []
    for s in sample:
        slug = slugify(s["name"])
        row = {"song": s["name"], "lang_group": s.get("lang_group"),
               "wpm": s.get("wpm")}
        rj = os.path.join(run_dir, "results", f"{slug}.json")
        ej = os.path.join(run_dir, "results", f"{slug}.error.json")
        if os.path.exists(rj):
            with open(rj, encoding="utf-8") as f:
                row.update(_flat(json.load(f)))
        elif os.path.exists(ej):
            with open(ej, encoding="utf-8") as f:
                row["error"] = json.load(f).get("error")
        else:
            row["error"] = "not run"
        rows.append(row)

    csv_path = os.path.join(run_dir, "results.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FLAT_FIELDS)
        w.writeheader()
        w.writerows(rows)

    ok = [r for r in rows if r.get("recall") is not None]
    failed = [r for r in rows if r.get("error")]

    def med_line(rs, label):
        parts = [f"  {label:24s}"]
        for k in KEY_METRICS:
            vals = [r[k] for r in rs if r.get(k) is not None]
            parts.append(f"{statistics.median(vals):9.3f}" if vals else "       --")
        print("".join(parts))

    print(f"\n=== library replay summary ({len(ok)} scored, {len(failed)} failed,"
          f" {len(rows)} total) ===")
    print("  " + " " * 24 + "".join(f"{h:>9s}" for h in
                                    ["w_1s", "onset", "interp", "p_2st",
                                     "p_corr", "bpm_dev"]))
    med_line(ok, "ALL (median)")
    for lg in ("es", "en", "other"):
        rs = [r for r in ok if r["lang_group"] == lg]
        if rs:
            med_line(rs, f"lang={lg} (n={len(rs)})")
    rescued = [r for r in ok if r.get("rescue_tried")]
    if rescued:
        won = sum(1 for r in rescued if r.get("rescue_won"))
        print(f"\n  lead-vocal rescue tried on {len(rescued)}/{len(ok)} songs, won {won}")
    bpm_all = [r for r in ok if r.get("bpm_dev") is not None]
    bpm_good = [r for r in bpm_all if r["bpm_dev"] < 0.02]
    if bpm_all:
        print(f"  BPM estimate within 2% of gold (mod octave): "
              f"{len(bpm_good)}/{len(bpm_all)}")
    for r in failed:
        print(f"  FAILED: {r['song']}: {r['error']}")
    print(f"\n  full table: {csv_path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", default=r"D:\Canciones Karaoke")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--seed-set", default=None,
                    help="path to a curated seed-set JSON (eval/seed_set.json); "
                         "overrides --n/--seed sampling")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--aggregate-only", action="store_true")
    args = ap.parse_args()

    runs_root = str(_HERE.parents[0] / "eval_runs")
    manifest = build_manifest(args.lib, runs_root)
    if not manifest:
        return 2

    if args.seed_set:
        sample = seed_set_sample(args.seed_set, manifest)
        run_dir = os.path.join(runs_root, "replay-seedset")
    else:
        sample, _ = stratified_sample(manifest, args.n, args.seed)
        run_dir = os.path.join(runs_root, f"replay-n{args.n}-seed{args.seed}")
    counts = ", ".join(
        f"{lg}={sum(1 for s in sample if s['lang_group'] == lg)}"
        for lg in ("es", "en", "other"))
    log(f"sample: {len(sample)} songs ({counts})")

    for sub in ("results", "cache"):
        os.makedirs(os.path.join(run_dir, sub), exist_ok=True)

    if not args.aggregate_only:
        for i, song in enumerate(sample, 1):
            log(f"[{i}/{len(sample)}]")
            run_song(song, run_dir, args.device)

    aggregate(sample, run_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())

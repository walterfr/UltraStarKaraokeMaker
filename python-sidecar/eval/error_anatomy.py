# -*- coding: utf-8 -*-
"""Anatomia do erro do CTC: quanto cada detector de linha suspeita acerta.

Cruza o cache de um run do library_replay (align_ctc.json, align.json,
vocals.wav) com os charts gold e mede, por LINHA da letra, quem sinaliza as
linhas erradas (1ª palavra a > 1 s do chart). Os detectores são as funções de
produção de pipeline.ctc_align (words_on_silence, line_start_disagreement,
reflag_lines) - nada é reimplementado aqui. Só leitura; não precisa de GPU.

  python eval/error_anatomy.py [--run-dir eval_runs/replay-seedset]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[0]))
sys.path.insert(0, str(_HERE))

import library_replay as lr  # noqa: E402
import usdx_parse  # noqa: E402
from pipeline import ctc_align as C  # noqa: E402
from pipeline.align import SOURCE_CTC_LOW, WordTiming, _load_lyrics_words_with_line_ends  # noqa: E402
from pipeline.proc_utils import ensure_ffmpeg_on_path  # noqa: E402

WRONG_S = 1.0     # linha/palavra errada: início a mais disto do chart
CONFIRM_S = 0.3   # linha "confirmada": CTC e Whisper a menos disto, sem silêncio
BURST_MIN = 20    # rajada longa de palavras erradas seguidas


def _low_lines(timings, bounds) -> list[bool]:
    return [any(w.source == SOURCE_CTC_LOW for w in timings[a:b]) for a, b in bounds]


def _reflagged(timings, bounds, silent, disagreement=None) -> list[bool]:
    ts = [replace(t) for t in timings]
    C.reflag_lines(ts, silent, disagreement)
    return _low_lines(ts, bounds)


def song_lines(cache: Path, song: dict, skipped: list[str]) -> tuple[list[dict], list[bool]] | None:
    """Registros por linha + erro (> WRONG_S) por palavra casada, na ordem do chart."""
    import whisperx

    a = json.loads((cache / "align_ctc.json").read_text(encoding="utf-8"))
    if a.get("aligner_used") != "ctc":
        return None
    h = a["words"]
    _, line_ends, _ = _load_lyrics_words_with_line_ends(cache / "lyrics.txt", song.get("lang"))
    if len(line_ends) != len(h):
        skipped.append(f"{song['name']}: lyrics.txt tem {len(line_ends)} palavras, align_ctc.json {len(h)}")
        return None
    timings = [WordTiming(word=w["text"], start=w["start"], end=w["end"], score=w["score"] or 0.0,
                          is_line_end=le, source=w["source"]) for w, le in zip(h, line_ends)]
    bounds, start = [], 0
    for k, t in enumerate(timings):
        if t.is_line_end or k == len(timings) - 1:
            bounds.append((start, k + 1))
            start = k + 1

    g = lr.gold_words(usdx_parse.read_file(song["gold"]))
    pairs = lr.match_words(g, h)
    err = {j: h[j]["start"] - g[i]["start"] for i, j in pairs}

    silent = C.words_on_silence(timings, whisperx.load_audio(str(cache / "vocals.wav")))
    wh = cache / "align.json"
    dis = C.line_start_disagreement(
        timings, json.loads(wh.read_text(encoding="utf-8"))["words"] if wh.exists() else [])
    has_w = bool(dis) and dis[0] is not None
    prod_w = has_w and C.should_try_whisper_fallback(timings)

    cols = dict(a=_low_lines(timings, bounds),
                b=[any(silent[x:y]) for x, y in bounds],
                c=_reflagged(timings, bounds, silent),
                d=_reflagged(timings, bounds, silent, dis if prod_w else None),
                e=_reflagged(timings, bounds, silent, dis))
    lines = []
    for li, (x, _) in enumerate(bounds):
        if x not in err:      # 1ª palavra sem par no chart: não dá pra julgar a linha
            continue
        lines.append(dict({k: v[li] for k, v in cols.items()}, wrong=abs(err[x]) > WRONG_S,
                          dis=dis[li], has_w=has_w, prod_w=prod_w, n_lines=len(bounds)))
    return lines, [abs(err[j]) > WRONG_S for _, j in pairs]


def main() -> None:
    root = _HERE.parents[0]
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-dir", type=Path, default=root / "eval_runs" / "replay-seedset")
    ap.add_argument("--manifest", type=Path, default=root / "eval_runs" / "library_manifest.json")
    args = ap.parse_args()
    ensure_ffmpeg_on_path()

    man = {s["name"]: s for s in json.loads(args.manifest.read_text(encoding="utf-8"))["songs"]}
    L: list[dict] = []
    runs: list[int] = []
    skipped: list[str] = []
    songs = prod_w = has_w = n_all = 0
    for p in sorted((args.run_dir / "results").glob("*.json")):
        if p.name.endswith(".error.json"):
            continue
        s = man.get(json.loads(p.read_text(encoding="utf-8"))["song"])
        cache = args.run_dir / "cache" / lr.slugify(s["name"]) if s else None
        if not cache or not (cache / "align_ctc.json").exists():
            continue
        res = song_lines(cache, s, skipped)
        if not res or not res[0]:
            continue
        lines, wrong_words = res
        songs += 1
        prod_w += lines[0]["prod_w"]
        has_w += lines[0]["has_w"]
        n_all += lines[0]["n_lines"]
        L += lines
        cur = 0
        for w in wrong_words + [False]:
            if w:
                cur += 1
            elif cur:
                runs.append(cur)
                cur = 0

    bad = sum(l["wrong"] for l in L)
    print(f"musicas (CTC mantido): {songs} | Whisper em cache: {has_w} | Whisper roda na producao: {prod_w}")
    print(f"linhas: {len(L)} (de {n_all}; {n_all - len(L)} sem a 1a palavra casada com o chart)"
          f" | erradas (> {WRONG_S:g} s): {bad} ({bad / len(L):.1%})")
    print(f"\n{'detector':56s} {'marca':>6s} {'prec':>5s} {'recall':>6s}")
    for key, name in (("a", "(a) flag atual (score de linha < 0.10, como no cache)"),
                      ("b", "(b) so silencio (alguma palavra em silencio)"),
                      ("c", "(c) atual OU silencio"),
                      ("d", "(d) regra de producao (discorda>1s onde ha Whisper)"),
                      ("e", "(e) regra (d) supondo Whisper em toda musica")):
        fl = [l for l in L if l[key]]
        tp = sum(l["wrong"] for l in fl)
        print(f"{name:56s} {len(fl) / len(L):6.1%} {tp / max(1, len(fl)):5.2f} {tp / max(1, bad):6.2f}")
    for name, key in (("Whisper da producao", "prod_w"), ("Whisper em toda musica", "has_w")):
        conf = [l for l in L if l[key] and l["dis"] is not None and l["dis"] <= CONFIRM_S and not l["b"]]
        print(f"confirmadas (concorda <= {CONFIRM_S:g} s, sem silencio; {name}): "
              f"{len(conf) / len(L):.1%} das linhas, erradas {sum(l['wrong'] for l in conf) / max(1, len(conf)):.1%}")
    tot = sum(runs)
    print(f"\nrajadas: {tot} palavras erradas em {len(runs)} rajadas; "
          f"em rajadas >= {BURST_MIN}: {sum(r for r in runs if r >= BURST_MIN) / max(1, tot):.1%}")
    for s in skipped:
        print("pulada:", s)


if __name__ == "__main__":
    main()

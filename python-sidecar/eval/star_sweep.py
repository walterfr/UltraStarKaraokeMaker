"""
star_sweep.py
Varre o custo do curinga ("*", STAR_LOGP) do CTC global (item C2 do AGENTS.md)
sobre os stems e a letra cacheados de um run do harness. Mede só o CTC cru
(bloco global, sem .lrc, sem resgates nem Whisper): é a parte que o STAR_LOGP
mexe. Hipótese da auditoria de 13/11: curinga grátis (0) engole voz cantada e
empurra a letra para depois (76% das rajadas de erro são atrasos).

Variantes: constante (0 = produção, -1, -2, -3, -5), sem curinga ("off") e
"eN" = curinga grátis no silêncio do stem e custo -N onde há voz (mesmo piso
de words_on_silence). Emissões são calculadas uma vez por música (GPU, ~3 s)
e guardadas em cache/<música>/emissions_ctc.pt; o resto é Viterbi na CPU.

    python eval/star_sweep.py --run-dir eval_runs/replay-seedset-2_6_1
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[0]))
sys.path.insert(0, str(_HERE))

import library_replay as lr  # noqa: E402
import usdx_parse  # noqa: E402

VARIANTS = ("0", "-1", "-2", "-3", "-5", "off", "e1", "e2", "e3")


def star_column(variant: str, audio: np.ndarray, n_frames: int, frame_s: float) -> np.ndarray | None:
    """Log-prob do curinga por quadro para a variante (None = sem curinga)."""
    from pipeline.ctc_align import SAMPLE_RATE, SILENCE_FLOOR_DB

    if variant == "off":
        return None
    if not variant.startswith("e"):
        return np.full(n_frames, float(variant), dtype=np.float32)
    hop = int(SAMPLE_RATE * frame_s)
    n = min(n_frames, len(audio) // hop)
    frames = np.asarray(audio[:n * hop], dtype=np.float32).reshape(n, hop)
    db = 10.0 * np.log10((frames ** 2).mean(axis=1) + 1e-12)
    db -= np.percentile(db, 95)
    col = np.zeros(n_frames, dtype=np.float32)
    col[:n] = np.where(db < SILENCE_FLOOR_DB, 0.0, -float(variant[1:]))
    return col


def main() -> None:
    root = _HERE.parents[0]
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--run-dir", type=Path, default=root / "eval_runs" / "replay-seedset-2_6_1")
    ap.add_argument("--manifest", type=Path, default=root / "eval_runs" / "library_manifest.json")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--variants", default=",".join(VARIANTS))
    args = ap.parse_args()

    import torch
    import whisperx
    from pipeline import align as A
    from pipeline.ctc_align import (
        SEP_KEY, align_blocks, compute_emissions, ctc_model_for, fill_missing,
        to_word_timings, tokenize_words,
    )

    variants = args.variants.split(",")
    man = {s["name"]: s for s in json.loads(args.manifest.read_text(encoding="utf-8"))["songs"]}
    rows = []
    for p in sorted((args.run_dir / "results").glob("*.json")):
        if p.name.endswith(".error.json"):
            continue
        s = man.get(json.loads(p.read_text(encoding="utf-8"))["song"])
        cache = args.run_dir / "cache" / lr.slugify(s["name"]) if s else None
        if not cache or not (cache / "lyrics.txt").exists():
            continue
        chart = usdx_parse.read_file(s["gold"])
        gwords = lr.gold_words(chart)
        language = lr.normalize_language(chart.language)
        audio = whisperx.load_audio(str(cache / "vocals.wav"))
        words, line_ends, singers = A._load_lyrics_words_with_line_ends(cache / "lyrics.txt", language)
        model, dictionary = ctc_model_for(language, args.device)
        word_tokens, _ = tokenize_words(words, dictionary, language)
        ep = cache / "emissions_ctc.pt"
        if ep.exists():
            em, frame_s = torch.load(ep)
        else:
            em, frame_s = compute_emissions(model, audio, args.device)
            torch.save((em, frame_s), ep)
        star_id = dictionary["*"]
        blocks = [(0, len(words), 0.0, len(audio) / 16000)]
        row = {"song": s["name"]}
        for v in variants:
            col = star_column(v, audio, em.shape[0], frame_s)
            e = em.clone()
            if col is not None:
                e[:, star_id] = torch.from_numpy(col)
            times = align_blocks(e, frame_s, blocks, word_tokens, line_ends,
                                 None if col is None else star_id, dictionary["-"],
                                 sep_id=dictionary.get(SEP_KEY))
            if all(t is None for t in times):
                row[v] = None
                continue
            hyp = lr._timings_to_dicts(to_word_timings(words, line_ends, singers, fill_missing(times)))
            st = lr.timing_stats(gwords, hyp, lr.match_words(gwords, hyp))
            row[v] = (st["within_1s"], st["onset"]["median_ms"] if st["onset"] else None,
                      st["onset"]["bias_ms"] if st["onset"] else None)
        rows.append(row)
        lr.log(f"[{len(rows)}] {s['name']}: " + " ".join(
            f"{v}={row[v][0]:.3f}" if row[v] else f"{v}=-" for v in variants))

    (args.run_dir / "star_sweep.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    base = variants[0]
    print(f"\n{len(rows)} músicas; w_1s média/mediana, colapsos (<0,5), melhora/piora (>0,05) vs {base}, viés mediano")
    for v in variants:
        ok = [r for r in rows if r.get(v) and r.get(base)]
        w = [r[v][0] for r in ok]
        d = [r[v][0] - r[base][0] for r in ok]
        bias = [r[v][2] for r in ok if r[v][2] is not None]
        print(f"{v:>4}: {statistics.mean(w):.3f} / {statistics.median(w):.3f}  col {sum(x < 0.5 for x in w):2d}  "
              f"+{sum(x > 0.05 for x in d)} -{sum(x < -0.05 for x in d)}  viés {statistics.median(bias):+.0f} ms  (n={len(ok)})")


if __name__ == "__main__":
    main()

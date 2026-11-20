# -*- coding: utf-8 -*-
"""A/B of alternative aligners against the baseline of a library_replay run.

Reuses a finished replay run dir (same --lib/--n/--seed[/--lang]): its CACHED
Demucs stems and gold charts, so every variant is scored on the exact same
audio as the baseline (Demucs is nondeterministic - see README). Nothing is
re-separated; songs without a cached stem are skipped.

  python eval/ab_align.py --lib ~/Documents/songs --n 8 --seed 0 --variant ctc

Per-variant alignments are cached as cache/<slug>/align_<variant>.json.

A "kb-" prefix runs a CTC variant on KBLab's Swedish wav2vec2 instead of
MMS_FA (it knows å/ä/ö), e.g. --lang sv --variant kb-ctc; "-nosep" leaves out
its word separator.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[0]))
sys.path.insert(0, str(_HERE))

import library_replay as lr  # noqa: E402
import usdx_parse  # noqa: E402


import numpy as np  # noqa: E402

from pipeline.ctc_align import (  # noqa: E402
    LANG_CTC_MODELS, MAX_UNMAPPED_FRAC, SAMPLE_RATE, SEP_KEY, STAR_LOGP,
    align_blocks, compute_emissions, fill_missing, get_ctc_model, tokenize_words,
)

KB_SV_MODEL = LANG_CTC_MODELS["sv"]


# --- Variantes experimentais do CTC (só este script usa) ---
# Vieram de pipeline/ctc_align.py (item E4 do AGENTS.md): o CTC híbrido com
# âncoras duras do Whisper e o snap de início de linha perderam para o CTC
# global de produção, mas seguem aqui para o A/B.

def _occurrences(seq: list[str], hay: list[str]) -> int:
    n = len(seq)
    return sum(1 for i in range(len(hay) - n + 1) if hay[i:i + n] == seq)


def hard_anchor_runs(
    anchors: list, words: list[str] | None = None,
    min_run: int = 3, unambiguous_run: int = 8,
) -> list[tuple[int, int]]:
    """
    Faixas [i, j) de palavras com âncora EXATA do Whisper em sequência de pelo
    menos `min_run` palavras seguidas, com inícios crescentes, e em ordem
    temporal entre si. Uma âncora exata sozinha pode ser a ocorrência errada
    de uma palavra comum; três seguidas casando letra e transcrição quase
    nunca são - é o que torna a faixa segura como limite duro pro CTC.

    Com `words` (a letra), uma faixa curta só vale se a SEQUÊNCIA de palavras
    dela aparece UMA vez na letra: em linha repetida (refrão), o difflib pode
    ter casado a transcrição com a repetição errada, e a faixa inteira vira um
    limite duro no lugar errado (medido em "Nothing Else Matters": "what they
    do" casou 26 s depois do gold). Faixa de `unambiguous_run`+ palavras é
    aceita mesmo repetida.

    `anchors` é a saída de align.compute_anchors: (start, end, score, source)
    ou None por palavra.
    """
    from pipeline.align import SOURCE_ANCHOR, _normalize_word

    norm = [_normalize_word(w) for w in words] if words is not None else None

    runs: list[tuple[int, int]] = []
    n = len(anchors)
    k = 0
    while k < n:
        a = anchors[k]
        if a is None or a[3] != SOURCE_ANCHOR:
            k += 1
            continue
        j = k + 1
        while (j < n and anchors[j] is not None and anchors[j][3] == SOURCE_ANCHOR
               and anchors[j][0] >= anchors[j - 1][0]):
            j += 1
        ambiguous = (norm is not None and j - k < unambiguous_run
                     and _occurrences(norm[k:j], norm) > 1)
        if j - k >= min_run and not ambiguous:
            # descarta faixa que volta no tempo em relação à anterior aceita
            if not runs or anchors[k][0] >= anchors[runs[-1][1] - 1][1] - 0.05:
                runs.append((k, j))
        k = j
    return runs


def plan_blocks(
    n_words: int,
    runs: list[tuple[int, int]],
    anchors: list,
    audio_dur: float,
    pad: float = 0.25,
) -> list[tuple[int, int, float, float]]:
    """
    Parte a letra em blocos (i0, i1, t0, t1) que cobrem todas as palavras em
    ordem: cada faixa de âncoras duras vira um bloco com janela = o trecho que
    o Whisper mediu (+ `pad`), e cada vão entre faixas vira um bloco com
    janela = do fim da faixa anterior ao início da seguinte (ou borda do
    áudio). Cada bloco é alinhado sozinho, então um erro não atravessa uma
    faixa dura.
    """
    blocks: list[tuple[int, int, float, float]] = []
    prev_i, prev_t = 0, 0.0
    for i, j in runs:
        run_t0 = max(0.0, anchors[i][0] - pad)
        run_t1 = min(audio_dur, anchors[j - 1][1] + pad)
        if i > prev_i:
            blocks.append((prev_i, i, prev_t, max(prev_t, anchors[i][0])))
        blocks.append((i, j, run_t0, run_t1))
        prev_i, prev_t = j, anchors[j - 1][1]
    if prev_i < n_words:
        blocks.append((prev_i, n_words, prev_t, audio_dur))
    return blocks


def align_lyrics_ctc(
    audio: np.ndarray,
    words: list[str],
    line_ends: list[bool],
    language: str,
    device: str = "cuda",
    use_star: bool = True,
    anchors: list | None = None,
    emissions=None,
    star_logp: float = STAR_LOGP,
    model_name: str | None = None,
    use_sep: bool = True,
) -> list[tuple[float, float, float, bool]] | None:
    """
    Alinha `words` (a letra inteira, na ordem) ao áudio vocal. Devolve um
    (start_s, end_s, score, medido) por palavra, ou None se a letra não cabe
    no vocabulário do modelo (outro alfabeto).

    Sem `anchors`: um único Viterbi global. Com `anchors` (saída de
    align.compute_anchors sobre a transcrição do Whisper): híbrido - faixas de
    âncoras exatas confiáveis viram limites duros e o CTC alinha bloco a bloco
    (ver plan_blocks). `emissions` = (tensor, frame_s) já calculado, pra
    reusar entre variantes - do MESMO modelo que `model_name` escolhe
    (get_ctc_model). `use_sep` só vale para modelo com separador de palavras.
    """
    model, dictionary = get_ctc_model(device, model_name)
    word_tokens, unmapped = tokenize_words(words, dictionary, language)
    if unmapped > MAX_UNMAPPED_FRAC:
        return None
    star_id = dictionary.get("*") if use_star else None

    em, frame_s = emissions if emissions is not None else compute_emissions(model, audio, device)
    if star_id is not None:
        em = em.clone()
        em[:, star_id] = star_logp
    audio_dur = len(audio) / SAMPLE_RATE
    runs = hard_anchor_runs(anchors, words) if anchors is not None else []
    blocks = plan_blocks(len(words), runs, anchors or [], audio_dur)
    sep_id = dictionary.get(SEP_KEY) if use_sep else None
    times = align_blocks(em, frame_s, blocks, word_tokens, line_ends, star_id, dictionary["-"],
                         sep_id=sep_id)
    if all(t is None for t in times):
        return None
    return fill_missing(times)


def snap_line_starts(
    starts: list[float], ends: list[float], line_ends: list[bool],
    onsets: np.ndarray, max_shift: float = 0.15,
) -> int:
    """
    Puxa o início da 1ª palavra de cada linha para o ataque vocal (voz depois
    de pausa, align.vocal_onsets) mais próximo, se estiver a <= `max_shift`.
    Só a 1ª palavra: dentro da frase cantada em legato não há pausa que marque
    a palavra. Muta `starts` (e `ends` se o início passar do fim). Devolve
    quantas palavras mudaram.
    """
    if len(onsets) == 0:
        return 0
    moved = 0
    for k in range(len(starts)):
        if k > 0 and not line_ends[k - 1]:
            continue
        i = int(np.searchsorted(onsets, starts[k]))
        cands = [onsets[j] for j in (i - 1, i) if 0 <= j < len(onsets)]
        best = min(cands, key=lambda o: abs(o - starts[k]))
        if abs(best - starts[k]) <= max_shift and (k == 0 or best >= ends[k - 1]):
            starts[k] = float(best)
            ends[k] = max(ends[k], starts[k] + 0.02)
            moved += 1
    return moved


def _emissions(cache: Path, audio, device: str, stem_tag: str = "", model_name: str | None = None):
    """CTC emissions over the whole stem, cached (deterministic per stem)."""
    import torch
    tag = "kbsv" if model_name == KB_SV_MODEL else "mms"
    p = cache / f"emissions_{tag}{stem_tag}.pt"
    if p.exists():
        d = torch.load(p)
        return d["em"], d["frame_s"]
    model, _ = get_ctc_model(device, model_name)
    em, frame_s = compute_emissions(model, audio, device)
    torch.save({"em": em, "frame_s": frame_s}, p)
    return em, frame_s


def _whisper_words(cache: Path, audio, language: str, device: str) -> list[dict]:
    """Raw whisper transcription (+ its own wav2vec2 alignment), cached."""
    p = cache / "whisper_words.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    from pipeline.align import transcribe_words
    ww = transcribe_words(audio, language, device)
    ww = [{k: w.get(k) for k in ("word", "start", "end", "score")} for w in ww
          if w.get("start") is not None]
    p.write_text(json.dumps(ww, ensure_ascii=False), encoding="utf-8")
    return ww


def _dedup_lyrics(cache: Path, lyrics: Path) -> Path:
    """Letra com cada linha repetida só na 1ª vez (refrão "escrito uma vez só")."""
    out = cache / "lyrics_dedup.txt"
    seen, keep = set(), []
    for line in lyrics.read_text(encoding="utf-8").splitlines():
        key = line.strip().lower()
        if key and key in seen:
            continue
        seen.add(key)
        keep.append(line)
    out.write_text("\n".join(keep) + "\n", encoding="utf-8")
    return out


def _whisper_path(audio, words, language, device, cache):
    """O alinhador do Whisper (align.py, sem .lrc e sem resgates) a partir da
    transcrição cacheada - a mesma que o `hybrid` usa."""
    from pipeline.align import (compute_anchors, realign_gap_windows,
                                timings_from_anchors, _get_align_model)
    anchors = compute_anchors(_whisper_words(cache, audio, language, device), words)
    timings = timings_from_anchors(anchors, words, language, audio_end=len(audio) / 16000.0)
    model, meta = _get_align_model(language, device)
    realign_gap_windows(timings, model, meta, audio, device, language)
    return timings


def _run_variant(variant: str, cache: Path, lyrics: Path, language: str, device: str):
    import whisperx
    from pipeline.align import _load_lyrics_words_with_line_ends, compute_anchors
    from pipeline.ctc_align import to_word_timings

    # "...+snap" = pós-processo: início de linha puxado pro ataque vocal
    snap = variant.endswith("+snap")
    variant = variant.removesuffix("+snap")
    # "...@lead" = no stem da voz principal isolada (resgate 4b do main.py)
    lead = variant.endswith("@lead")
    variant = variant.removesuffix("@lead")
    # "...~dedup" = letra com as linhas repetidas removidas
    if variant.endswith("~dedup"):
        variant = variant.removesuffix("~dedup")
        lyrics = _dedup_lyrics(cache, lyrics)
    # "kb-..." = modelo sueco do KBLab no lugar do MMS_FA
    model_name = None
    if variant.startswith("kb-"):
        variant = variant.removeprefix("kb-")
        model_name = KB_SV_MODEL
    # "...-nosep" = sem o separador de palavras "|" (só modelo do Hugging Face)
    use_sep = not variant.endswith("-nosep")
    variant = variant.removesuffix("-nosep")
    stem = cache / "vocals.wav"
    if lead:
        stem = cache / "lead_vocals.wav"
        if not stem.exists():
            from pipeline.separate import isolate_lead_vocal
            lr.log("  isolating lead vocal...")
            stem = isolate_lead_vocal(cache / "vocals.wav", cache)
    audio = whisperx.load_audio(str(stem))
    words, line_ends, singers = _load_lyrics_words_with_line_ends(lyrics)
    if variant == "whisper":
        timings = _whisper_path(audio, words, language, device, cache)
        for wt, le in zip(timings, line_ends):
            wt.is_line_end = le
        return timings
    em = _emissions(cache, audio, device, "_lead" if lead else "", model_name)
    anchors = None
    if variant.startswith("hybrid"):
        anchors = compute_anchors(_whisper_words(cache, audio, language, device), words)
    # "...-starN" = custo do coringa -N (log-prob por quadro), ex. ctc-star2
    m = re.search(r"-star([\d.]+)$", variant)
    star_logp = -float(m.group(1)) if m else 0.0
    res = align_lyrics_ctc(audio, words, line_ends, language, device,
                           use_star=not variant.endswith("nostar"),
                           anchors=anchors, emissions=em, star_logp=star_logp,
                           model_name=model_name, use_sep=use_sep)
    if res is None:
        return None
    if snap:
        from pipeline.align import vocal_onsets
        starts, ends = [r[0] for r in res], [r[1] for r in res]
        snap_line_starts(starts, ends, line_ends, vocal_onsets(audio))
        res = [(s, e, sc, m) for s, e, (_, _, sc, m) in zip(starts, ends, res)]
    return to_word_timings(words, line_ends, singers, res)


def _variant_words(variant, cache: Path, gwords, language, device) -> list[dict] | None:
    out = cache / f"align_{variant}.json"
    if out.exists():
        return json.loads(out.read_text(encoding="utf-8"))
    lyrics = cache / "lyrics.txt"
    if not lyrics.exists():
        lyrics.write_text(lr.gold_lyrics_text(gwords), encoding="utf-8")
    timings = _run_variant(variant, cache, lyrics, language, device)
    if timings is None:
        return None
    words = lr._timings_to_dicts(timings)
    out.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    return words


def _fmt(v, w=7):
    return f"{v:>{w}}" if v is not None else f"{'-':>{w}}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", required=True)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--lang", default=None)
    ap.add_argument("--variant", required=True)
    ap.add_argument("--device", default="cuda")
    args = ap.parse_args()
    lr._prefer_safe_ct2_allocator_on_hip()

    runs_root = str(_HERE.parents[0] / "eval_runs")
    manifest = lr.build_manifest(os.path.expanduser(args.lib), runs_root)
    if args.lang:
        manifest = [s for s in manifest if lr.in_lang(s, args.lang)]
    sample, _ = lr.stratified_sample(manifest, args.n, args.seed)
    suffix = f"-{args.lang}" if args.lang else ""
    run_dir = Path(runs_root) / f"replay-n{args.n}-seed{args.seed}{suffix}"

    rows = []
    for song in sample:
        slug = lr.slugify(song["name"])
        cache = run_dir / "cache" / slug
        base_json = run_dir / "results" / f"{slug}.json"
        if not (cache / "vocals.wav").exists() or not base_json.exists():
            lr.log(f"[skip] {song['name']} (no cached baseline)")
            continue
        base = json.loads(base_json.read_text(encoding="utf-8"))["align"]
        chart = usdx_parse.read_file(song["gold"])
        gwords = lr.gold_words(chart)
        language = lr.normalize_language(chart.language)
        lr.log(f"[run ] {song['name']} ({args.variant})")
        hyp = _variant_words(args.variant, cache, gwords, language, args.device)
        if hyp is None:
            lr.log("       variant declined (vocabulary)")
            continue
        st = lr.timing_stats(gwords, hyp, lr.match_words(gwords, hyp))
        rows.append((song["name"], base, st))

    print(f"\n{'song':<42} {'w1s base':>8} {'w1s new':>8}  {'med base':>8} {'med new':>8}"
          f"  {'p90 base':>8} {'p90 new':>8}  {'end base':>8} {'end new':>8}")
    for name, b, n in rows:
        bo, no = b.get("onset") or {}, n.get("onset") or {}
        be, ne = b.get("end") or {}, n.get("end") or {}
        print(f"{name[:42]:<42} {_fmt(b['within_1s'], 8)} {_fmt(n['within_1s'], 8)}  "
              f"{_fmt(bo.get('median_ms'), 8)} {_fmt(no.get('median_ms'), 8)}  "
              f"{_fmt(bo.get('p90_ms'), 8)} {_fmt(no.get('p90_ms'), 8)}  "
              f"{_fmt(be.get('median_ms'), 8)} {_fmt(ne.get('median_ms'), 8)}")
    if rows:
        def med(get):
            vals = [get(r) for r in rows]
            vals = [v for v in vals if v is not None]
            return round(statistics.median(vals), 3) if vals else None
        print(f"{'MEDIAN':<42} {_fmt(med(lambda r: r[1]['within_1s']), 8)} "
              f"{_fmt(med(lambda r: r[2]['within_1s']), 8)}  "
              f"{_fmt(med(lambda r: (r[1].get('onset') or {}).get('median_ms')), 8)} "
              f"{_fmt(med(lambda r: (r[2].get('onset') or {}).get('median_ms')), 8)}  "
              f"{_fmt(med(lambda r: (r[1].get('onset') or {}).get('p90_ms')), 8)} "
              f"{_fmt(med(lambda r: (r[2].get('onset') or {}).get('p90_ms')), 8)}  "
              f"{_fmt(med(lambda r: (r[1].get('end') or {}).get('median_ms')), 8)} "
              f"{_fmt(med(lambda r: (r[2].get('end') or {}).get('median_ms')), 8)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

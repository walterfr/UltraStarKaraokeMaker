# -*- coding: utf-8 -*-
"""
Testes da lógica PURA do ctc_align.py (tokenização, alvo do CTC, blocos entre
âncoras duras) - nada aqui carrega modelo; o Viterbi é testado com emissões
sintéticas pequenas.

Rodar:  python -m pytest tests/ -v
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.align import SOURCE_ANCHOR, SOURCE_FUZZY
from pipeline.ctc_align import (
    build_targets,
    fill_missing,
    hard_anchor_runs,
    plan_blocks,
    spans_to_word_times,
    tokenize_words,
)

DICT = {"-": 0, "a": 1, "b": 2, "o": 3, "s": 4, "'": 5, "*": 6, "c": 7, "e": 8,
        "f": 9, "i": 10, "l": 11, "n": 12, "r": 13, "t": 14, "u": 15, "v": 16,
        "w": 17, "y": 18, "g": 19, "h": 20, "d": 21, "m": 22, "k": 23}


def test_tokenize_folds_accents_and_punctuation():
    toks, unmapped = tokenize_words(["Såb,", "“ab”"], DICT, "sv")
    assert toks == [[4, 1, 2], [1, 2]]
    assert unmapped == 0.0


def test_tokenize_keeps_letters_the_model_knows():
    # vocabulário com å/ä/ö (modelo sueco): o acento não pode cair
    d = dict(DICT, **{"å": 30, "ä": 31, "ö": 32})
    toks, unmapped = tokenize_words(["Såg", "för", "Ärlig"], d, "sv")
    assert toks == [[4, 30, 19], [9, 32, 13], [31, 13, 11, 10, 19]]
    assert unmapped == 0.0
    # sem a letra no vocabulário, cai na leitura latina de sempre
    toks, _ = tokenize_words(["för"], DICT, "sv")
    assert toks == [[9, 3, 13]]


def test_tokenize_never_emits_word_separator():
    d = dict(DICT, **{"|": 40})
    toks, _ = tokenize_words(["a|b"], d, "en")
    assert toks == [[1, 2]]


def test_tokenize_never_emits_blank_or_star():
    toks, _ = tokenize_words(["rock-n-roll", "a*b"], DICT, "en")
    assert all(t not in (0, 6) for w in toks for t in w)


def test_tokenize_expands_numerals():
    toks, _ = tokenize_words(["20"], DICT, "en")
    assert toks == [[14, 17, 8, 12, 14, 18]]  # "twenty"


def test_tokenize_reports_other_scripts():
    _, unmapped = tokenize_words(["привет"], DICT, "ru")
    assert unmapped == 1.0


def test_build_targets_star_at_edges_and_line_ends():
    targets, ranges = build_targets([[1], [2, 3], [4]], [False, True, True], star_id=6)
    assert targets == [6, 1, 2, 3, 6, 4, 6]
    assert ranges == [(1, 2), (2, 4), (5, 6)]


def test_build_targets_without_star():
    targets, ranges = build_targets([[1], [], [4]], [False, False, True], star_id=None)
    assert targets == [1, 4]
    assert ranges == [(0, 1), (1, 1), (1, 2)]


def test_build_targets_word_separator_inside_lines_only():
    # "|" (40) entre palavras da mesma linha; na troca de linha, só o coringa
    targets, ranges = build_targets([[1], [2, 3], [4], [5]], [False, True, False, True],
                                    star_id=6, sep_id=40)
    assert targets == [6, 1, 40, 2, 3, 6, 4, 40, 5, 6]
    assert ranges == [(1, 2), (3, 5), (6, 7), (8, 9)]


def test_build_targets_separator_skips_empty_words():
    targets, ranges = build_targets([[1], [], [4]], [False, False, True], star_id=None, sep_id=40)
    assert targets == [1, 40, 4]
    assert ranges == [(0, 1), (1, 1), (2, 3)]


def test_swedish_gets_its_own_model_others_the_multilingual(monkeypatch):
    import pipeline.ctc_align as C
    loaded = []
    monkeypatch.setattr(C, "get_ctc_model", lambda device, name=None: loaded.append(name) or name)
    assert C.ctc_model_for("sv", "cpu") == "KBLab/wav2vec2-large-voxrex-swedish"
    assert C.ctc_model_for("en", "cpu") is None
    assert loaded == ["KBLab/wav2vec2-large-voxrex-swedish", None]


def test_every_language_model_has_a_pinned_revision():
    import pipeline.ctc_align as C
    for name in C.LANG_CTC_MODELS.values():
        rev = C.HF_MODEL_REVISIONS[name]
        assert len(rev) == 40 and all(c in "0123456789abcdef" for c in rev)


def test_language_model_that_fails_to_load_falls_back_to_multilingual(monkeypatch, capsys):
    import pipeline.ctc_align as C

    def fake(device, name=None):
        if name is not None:
            raise OSError("offline")
        return "mms"
    monkeypatch.setattr(C, "get_ctc_model", fake)
    assert C.ctc_model_for("sv", "cpu") == "mms"
    assert "offline" in capsys.readouterr().out


def test_spans_to_word_times_and_fill_missing():
    spans = [(10, 12, 0.5), (20, 21, 1.0)]
    times = spans_to_word_times(spans, [(0, 1), (1, 1), (1, 2)], frame_s=0.02)
    assert times[0] == pytest.approx((0.2, 0.24, 0.5))
    assert times[1] is None
    filled = fill_missing(times)
    assert filled[1][3] is False
    assert filled[0][1] <= filled[1][0] <= filled[2][0]


def _a(start, src=SOURCE_ANCHOR):
    return (start, start + 0.3, 0.9, src)


def test_hard_runs_need_min_length_and_exact_source():
    anchors = [_a(1), _a(2), None, _a(3), _a(4), _a(5), _a(6, SOURCE_FUZZY)]
    assert hard_anchor_runs(anchors) == [(3, 6)]


def test_hard_runs_reject_repeated_short_phrases():
    words = "never cared for what they do never cared for what they know".split()
    anchors = [None] * len(words)
    for k in (3, 4, 5):  # "what they do" occurs once -> kept
        anchors[k] = _a(float(k))
    assert hard_anchor_runs(anchors, words) == [(3, 6)]
    anchors = [None] * len(words)
    for k in (0, 1, 2):  # "never cared for" occurs twice -> ambiguous
        anchors[k] = _a(float(k))
    assert hard_anchor_runs(anchors, words) == []


def test_hard_runs_drop_runs_going_back_in_time():
    anchors = [_a(10), _a(11), _a(12), None, _a(1), _a(2), _a(3)]
    assert hard_anchor_runs(anchors) == [(0, 3)]


def test_plan_blocks_cover_all_words_in_order():
    anchors = [None, _a(10), _a(11), _a(12), None, None]
    blocks = plan_blocks(6, [(1, 4)], anchors, audio_dur=100.0)
    assert [(b[0], b[1]) for b in blocks] == [(0, 1), (1, 4), (4, 6)]
    assert blocks[0][2:] == (0.0, 10.0)
    assert blocks[1][2] == pytest.approx(9.75)
    assert blocks[2][2:] == (pytest.approx(12.3), 100.0)


def test_forced_align_synthetic():
    torch = pytest.importorskip("torch")
    pytest.importorskip("torchaudio")
    from pipeline.ctc_align import align_blocks

    # 3 tokens (blank=0, a=1, b=2): "a" nos quadros 3-4, "b" nos 8-9
    T = 12
    em = torch.full((T, 3), -10.0)
    em[:, 0] = -0.01
    for f in (3, 4):
        em[f] = torch.tensor([-10.0, -0.01, -10.0])
    for f in (8, 9):
        em[f] = torch.tensor([-10.0, -10.0, -0.01])
    times = align_blocks(em, 0.1, [(0, 2, 0.0, 1.2)], [[1], [2]], [False, True],
                         star_id=None, blank=0)
    assert times[0][0] == pytest.approx(0.3)
    assert times[1][0] == pytest.approx(0.8)


def test_snap_line_starts_only_moves_line_first_words_within_reach():
    import numpy as np
    from pipeline.ctc_align import snap_line_starts

    starts = [1.00, 1.50, 3.00, 6.00]
    ends = [1.40, 2.00, 3.50, 6.50]
    line_ends = [False, True, False, True]
    onsets = np.array([0.90, 1.45, 3.12, 5.50])
    moved = snap_line_starts(starts, ends, line_ends, onsets)
    assert moved == 2
    assert starts == [0.90, 1.50, 3.12, 6.00]  # 1.45 is mid-line; 5.50 too far


def _peaky(T, C, peaks):
    """log-probs [T, C]: blank everywhere except the given {frame: token}."""
    import numpy as np
    lp = np.full((T, C), -10.0, dtype=np.float32)
    lp[:, 0] = -0.01
    for f, tok in peaks.items():
        lp[f] = -10.0
        lp[f, tok] = -0.01
    return lp


def test_viterbi_repeated_token_needs_a_blank_between():
    from pipeline.ctc_align import ctc_viterbi
    lp = _peaky(8, 3, {2: 1, 5: 1})  # "a a" -> two separate spans
    spans = ctc_viterbi(lp, [1, 1], blank=0)
    assert [(s, e) for s, e, _ in spans] == [(2, 3), (5, 6)]


def test_viterbi_matches_torchaudio_on_random_emissions():
    import numpy as np
    torch = pytest.importorskip("torch")
    F = pytest.importorskip("torchaudio.functional")
    from pipeline.ctc_align import ctc_viterbi
    rng = np.random.default_rng(0)
    lp = torch.log_softmax(torch.from_numpy(rng.normal(size=(120, 6)).astype(np.float32)), -1)
    targets = [1, 2, 2, 3, 5, 4, 4, 1]
    labels, scores = F.forced_align(lp.unsqueeze(0), torch.tensor([targets], dtype=torch.int32), blank=0)
    ref = [(s.start, s.end) for s in F.merge_tokens(labels[0], scores[0].exp(), blank=0)]
    assert [(s, e) for s, e, _ in ctc_viterbi(lp.numpy(), targets, blank=0)] == ref


def test_lrc_blocks_bound_each_line_by_the_next_start():
    from pipeline.ctc_align import lrc_blocks
    blocks = lrc_blocks(10, [(0, 5.0), (4, 12.0), (7, 20.0)], audio_dur=60.0, pad=0.3)
    assert blocks == [(0, 4, 4.7, 12.0), (4, 7, 12.0, 20.0), (7, 10, 20.0, 60.0)]


def test_lrc_blocks_unmatched_head_and_backwards_times():
    from pipeline.ctc_align import lrc_blocks
    blocks = lrc_blocks(10, [(3, 8.0), (6, 4.0)], audio_dur=30.0, pad=0.3)
    assert blocks == [(0, 3, 0.0, 8.0), (3, 10, 8.0, 30.0)]  # (6, 4.0) goes back: dropped
    assert lrc_blocks(5, [], audio_dur=9.0) == [(0, 5, 0.0, 9.0)]


def test_lrc_blocks_no_inter_block_overlaps():
    from pipeline.ctc_align import lrc_blocks
    # 4 linhas: 0:32 "Who do you think you are?", 0:35 "Tearing us all apart"
    starts = [(0, 10.0), (5, 20.0), (11, 32.0), (17, 35.0)]
    blocks = lrc_blocks(22, starts, audio_dur=50.0, pad=0.5)
    for k in range(len(blocks) - 1):
        assert blocks[k][3] <= blocks[k + 1][2], f"Bloco {k} sobrepõe com bloco {k+1}!"


def test_fill_missing_enforces_monotonicity():
    from pipeline.ctc_align import fill_missing
    # Inversão artificial vinda de blocos sobrepostos: word 1 antes do fim de word 0
    raw_times = [(32.0, 35.2, 0.8), (34.8, 35.5, 0.9)]
    fixed = fill_missing(raw_times)
    assert fixed[0][0] == 32.0
    assert fixed[0][1] == 35.2
    assert fixed[1][0] >= fixed[0][1], "Segunda palavra não pode começar antes da primeira terminar!"


def _wt(score, line_end=False, source="ctc"):
    from pipeline.align import WordTiming
    return WordTiming(word="w", start=0.0, end=0.1, score=score, is_line_end=line_end, source=source)


def test_flag_low_confidence_lines_marks_whole_lines():
    from pipeline.ctc_align import flag_low_confidence_lines, low_confidence_frac
    ts = [_wt(0.5), _wt(0.4, True), _wt(0.05), _wt(0.02, True), _wt(0.01, source="interpolated"), _wt(0.3, True)]
    assert flag_low_confidence_lines(ts, threshold=0.1) == 2
    assert [w.source for w in ts] == ["ctc", "ctc", "ctc_low", "ctc_low", "interpolated", "ctc"]
    assert low_confidence_frac(ts) == pytest.approx(3 / 6)


def test_syllable_starts_from_letter_times():
    from pipeline.ctc_align import syllable_starts
    # "cabo" -> ["ca", "bo"]: letters c a b o
    tt = [(1.00, 1.02), (1.05, 1.20), (1.30, 1.32), (1.35, 1.50)]
    assert syllable_starts(["ca", "bo"], tt, DICT, "pt") == [1.00, 1.30]


def test_syllable_starts_give_up_when_letters_dont_add_up():
    from pipeline.ctc_align import syllable_starts
    tt = [(1.0, 1.1), (1.2, 1.3), (1.4, 1.5)]
    assert syllable_starts(["ca", "bo"], tt, DICT, "pt") is None     # 4 letters vs 3 spans
    assert syllable_starts(["cabo"], tt, DICT, "pt") is None         # single syllable


def test_trim_premature_word_prefix_drops_stray_leading_letter_before_long_gap():
    from pipeline.ctc_align import spans_to_word_times, word_token_times
    # "wanna": 'w' latched onto previous vocal tail at 0.10..0.20s, then 4s silence before 'a n n a' at 4.20..4.60s
    spans = [
        (5, 10, 0.2),     # 0.10..0.20s ('w')
        (210, 215, 0.9),  # 4.20..4.30s ('a')
        (215, 220, 0.9),  # 4.30..4.40s ('n')
        (220, 225, 0.9),  # 4.40..4.50s ('n')
        (225, 230, 0.9),  # 4.50..4.60s ('a')
    ]
    wt = spans_to_word_times(spans, [(0, 5)], frame_s=0.02)
    assert wt[0] is not None
    assert wt[0][0] == pytest.approx(4.20)
    assert wt[0][1] == pytest.approx(4.60)
    tt = word_token_times(spans, [(0, 5)], frame_s=0.02)
    assert tt[0][0][0] == pytest.approx(4.20)


def test_trim_premature_word_prefix_preserves_melisma_when_tail_is_only_closing_consonant():
    from pipeline.ctc_align import spans_to_word_times, word_token_times
    # "keep" held 1.3s: 'k e e' at 1.00..1.24s, blank during held vowel, closing 'p' at 2.34..2.36s (0.02s <= 0.10s)
    spans = [
        (50, 52, 0.8),    # 1.00..1.04s ('k')
        (52, 57, 0.9),    # 1.04..1.14s ('e')
        (57, 62, 0.9),    # 1.14..1.24s ('e')
        (117, 118, 0.1),  # 2.34..2.36s ('p' - 1 frame closing consonant)
    ]
    wt = spans_to_word_times(spans, [(0, 4)], frame_s=0.02)
    assert wt[0] is not None
    assert wt[0][0] == pytest.approx(1.00)
    assert wt[0][1] == pytest.approx(2.36)
    tt = word_token_times(spans, [(0, 4)], frame_s=0.02)
    assert tt[0][0][0] == pytest.approx(1.00)


def test_verified_lrc_blocks_triggers_when_majority_agrees_but_bridge_drifts():
    from pipeline.ctc_align import verified_lrc_blocks
    lrc_lines = [
        (10.0, "Line one here"),
        (15.0, "Line two here"),
        (20.0, "Line three here"),
        (25.0, "Line four here"),
        (30.0, "Line five here"),
        (50.0, "Crimson and clover"),
    ]
    lyric_lines = [(txt, i * 3) for i, (_, txt) in enumerate(lrc_lines)]
    # First 5 lines agree with LRC, 6th line collapsed 15s early to 35.0s instead of 50.0s
    starts = [10.1, 15.1, 20.0, 25.2, 30.1, 35.0]
    times = [
        (t + i * 0.3, t + (i + 1) * 0.3, 0.9)
        for t in starts
        for i in range(3)
    ]
    blocks = verified_lrc_blocks(times, lyric_lines, lrc_lines, n_words=len(times), audio_dur=65.0)
    assert blocks is not None
    assert len(blocks) == 6


def test_should_try_whisper_fallback_and_prefer_whisper_over_ctc():
    from pipeline.align import WordTiming
    from pipeline.ctc_align import prefer_whisper_over_ctc, should_try_whisper_fallback

    # 1. Confident CTC (low_frac = 0.0, mean_score = 0.8) -> does not trigger Whisper
    good_ctc = [
        WordTiming(word="a", start=1.0, end=1.2, score=0.8, source="ctc"),
        WordTiming(word="b", start=2.0, end=2.2, score=0.8, source="ctc"),
    ]
    assert should_try_whisper_fallback(good_ctc) is False

    # 2. Uncertain CTC (mean_score = 0.15 < 0.25) -> triggers Whisper
    uncertain_ctc = [
        WordTiming(word="a", start=1.0, end=1.2, score=0.20, source="ctc"),
        WordTiming(word="b", start=5.0, end=5.2, score=0.10, source="ctc_low"),
    ]
    assert should_try_whisper_fallback(uncertain_ctc) is True

    # 3. Whisper collapsed (interp_frac = 0.50 >= c_low = 0.50) -> NEVER switch to Whisper
    collapsed_whi = [
        WordTiming(word="a", start=1.0, end=1.2, score=0.70, source="anchor"),
        WordTiming(word="b", start=2.0, end=2.2, score=0.00, source="interpolated"),
    ]
    assert prefer_whisper_over_ctc(uncertain_ctc, collapsed_whi) is False

    # 4. Clean Whisper (interp_frac = 0.0 < 0.08) with much higher score on discordant word -> switch to Whisper
    clean_whi = [
        WordTiming(word="a", start=1.0, end=1.2, score=0.75, source="anchor"),
        WordTiming(word="b", start=2.0, end=2.2, score=0.80, source="anchor"),
    ]
    assert prefer_whisper_over_ctc(uncertain_ctc, clean_whi) is True


def test_detect_line_collapse_identifies_squished_metal_verses():
    from pipeline.ctc_align import detect_line_collapse

    # Normal spacing: LRC spacing matches vocal spacing
    normal_pairs = [
        (0, 10.0, 10.0),
        (5, 13.5, 13.0),
        (10, 17.0, 16.5),
    ]
    assert detect_line_collapse(normal_pairs) is False

    # Rock/Metal collapse: LRC lines 2.5s apart, but CTC squished into 0.8s
    collapsed_pairs = [
        (0, 34.0, 33.13),
        (6, 34.8, 35.64),  # ctc gap 0.8s, lrc gap 2.51s -> colapso!
        (12, 38.0, 39.0),
    ]
    assert detect_line_collapse(collapsed_pairs) is True


def test_verified_lrc_blocks_rescues_collapsed_rock_verses_below_agreement_threshold():
    from pipeline.ctc_align import verified_lrc_blocks

    lrc_lines = [
        (33.13, "I don't wanna stand beside you"),
        (35.64, "I don't wanna try and feel the pain you're going through"),
        (40.00, "Line three in the verse here"),
        (45.00, "Line four in the verse here"),
        (50.00, "Line five in the verse here"),
    ]
    lyric_lines = [(txt, i * 6) for i, (_, txt) in enumerate(lrc_lines)]
    # All lines drifted / collapsed erratically in CTC (agreement < 40%)
    # but line 1 & line 2 are squashed in 0.8s
    starts = [34.0, 34.8, 36.0, 42.0, 48.0]
    times = [
        (t + i * 0.1, t + (i + 1) * 0.1, 0.4)
        for t in starts
        for i in range(6)
    ]
    blocks = verified_lrc_blocks(times, lyric_lines, lrc_lines, n_words=len(times), audio_dur=65.0)
    assert blocks is not None
    assert len(blocks) == 5


def test_verified_lrc_blocks_supports_force_parameter():
    from pipeline.ctc_align import verified_lrc_blocks

    lrc_lines = [
        (10.0, "Line one here"),
        (15.0, "Line two here"),
        (20.0, "Line three here"),
        (25.0, "Line four here"),
        (30.0, "Line five here"),
    ]
    lyric_lines = [(txt, i * 3) for i, (_, txt) in enumerate(lrc_lines)]
    times = [(0.0, 0.1, 0.1)] * (len(lrc_lines) * 3)
    # force=True immediately returns blocks (coverage 30s/45s = 67% > 50%)
    blocks = verified_lrc_blocks(times, lyric_lines, lrc_lines, n_words=len(times), audio_dur=45.0, force=True)
    assert blocks is not None
    assert len(blocks) == 5


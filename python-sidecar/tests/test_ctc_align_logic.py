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
    assert blocks == [(0, 4, 4.7, 12.3), (4, 7, 11.7, 20.3), (7, 10, 19.7, 60.0)]


def test_lrc_blocks_unmatched_head_and_backwards_times():
    from pipeline.ctc_align import lrc_blocks
    blocks = lrc_blocks(10, [(3, 8.0), (6, 4.0)], audio_dur=30.0, pad=0.3)
    assert blocks == [(0, 3, 0.0, 8.3), (3, 10, 7.7, 30.0)]  # (6, 4.0) goes back: dropped
    assert lrc_blocks(5, [], audio_dur=9.0) == [(0, 5, 0.0, 9.0)]


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





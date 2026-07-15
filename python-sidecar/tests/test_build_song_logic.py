# -*- coding: utf-8 -*-
"""
Testes da lógica PURA de build_song.py (divisão de sílabas ponderada por
voz, detecção de melisma, montagem de notas) - sem GPU/modelo/áudio real:
usa PitchTrack sintético (numpy puro) e um PitchExtractor falso.

Rodar:  python -m pytest tests/ -v   (ou python tests/test_build_song_logic.py)
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.align import WordTiming
from pipeline.beatgrid import BeatGrid
from pipeline.build_song import (
    allocate_syllable_durations,
    apply_golden_notes,
    build_notes,
    detect_melisma_notes,
)
from pipeline.pitch import PitchResult, PitchTrack
from pipeline.ultrastar_writer import Note


def _empty_track() -> PitchTrack:
    empty = np.array([])
    return PitchTrack(timestamps=empty, pitch_hz=empty, confidence=empty, voicing=np.array([], dtype=bool))


def _track(timestamps, pitch_hz, voicing, confidence=None) -> PitchTrack:
    timestamps = np.asarray(timestamps, dtype=float)
    return PitchTrack(
        timestamps=timestamps,
        pitch_hz=np.asarray(pitch_hz, dtype=float),
        confidence=np.asarray(confidence if confidence is not None else [0.9] * len(timestamps)),
        voicing=np.asarray(voicing, dtype=bool),
    )


# --------------------------------------------------------------------------
# allocate_syllable_durations
# --------------------------------------------------------------------------

def test_allocate_single_syllable_short_circuits():
    assert allocate_syllable_durations(_empty_track(), 1, 0.0, 1.0) == [(0.0, 1.0)]


def test_allocate_falls_back_to_equal_split_without_frames():
    spans = allocate_syllable_durations(_empty_track(), 3, 0.0, 3.0)
    assert spans == [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)]


def test_allocate_boundary_snaps_away_from_sustained_region():
    # 1ª metade da palavra sem voz, 2ª metade sustentada (vozeada) - a
    # fronteira ingênua (0.5) cortaria bem no meio da região sustentada;
    # o ajuste local deve empurrá-la pra ANTES disso (não pra dentro dela).
    timestamps = [0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95]
    voicing = [False, False, False, False, False, True, True, True, True, True]
    track = _track(timestamps, pitch_hz=[220.0] * 10, voicing=voicing)

    spans = allocate_syllable_durations(track, 2, 0.0, 1.0, search_fraction=0.4)

    assert len(spans) == 2
    boundary = spans[0][1]
    assert boundary < 0.5, "fronteira deve sair do meio ingênuo, não cortar a região sustentada"
    assert spans[1][0] == boundary and spans[1][1] == 1.0
    # a sílaba sustentada (2ª) deve ficar com MAIS tempo que a naive (0.5s)
    assert (spans[1][1] - spans[1][0]) > 0.5


# --------------------------------------------------------------------------
# detect_melisma_notes
# --------------------------------------------------------------------------

def test_melisma_skipped_for_short_syllable():
    track = _track([0.05], pitch_hz=[220.0], voicing=[True])
    runs = detect_melisma_notes(track, 0.0, 0.1, min_syllable_duration_for_melisma=0.30)
    assert runs == [(0.0, 0.1)]


def test_melisma_no_split_when_pitch_constant():
    timestamps = np.arange(0.025, 0.6, 0.05)
    track = _track(timestamps, pitch_hz=[220.0] * len(timestamps), voicing=[True] * len(timestamps))
    runs = detect_melisma_notes(track, 0.0, 0.6)
    assert runs == [(0.0, 0.6)]


def test_melisma_splits_on_sustained_pitch_jump():
    # 1ª metade da sílaba em 220Hz, 2ª metade em 440Hz (1 oitava = 12
    # semitons, bem acima da tolerância) - deve virar nota + "~".
    timestamps = list(np.arange(0.025, 0.3, 0.05)) + list(np.arange(0.325, 0.6, 0.05))
    pitch_hz = [220.0] * 6 + [440.0] * 6
    track = _track(timestamps, pitch_hz=pitch_hz, voicing=[True] * 12)

    runs = detect_melisma_notes(track, 0.0, 0.6)

    assert len(runs) >= 2
    assert runs[0][0] == 0.0
    assert runs[-1][1] == 0.6
    assert runs[0][1] < runs[-1][0]  # fronteiras distintas, não colapsadas


def test_melisma_merges_brief_pitch_blip():
    # um "blip" de 1 quadro (bem menor que min_extension_s) não deve virar
    # sua própria nota "~" isolada - funde com o vizinho.
    timestamps = list(np.arange(0.025, 0.3, 0.05)) + [0.31] + list(np.arange(0.35, 0.6, 0.05))
    pitch_hz = [220.0] * 6 + [500.0] + [220.0] * 5
    track = _track(timestamps, pitch_hz=pitch_hz, voicing=[True] * len(timestamps))

    runs = detect_melisma_notes(track, 0.0, 0.6, min_extension_s=0.15)

    # o blip de 1 quadro não sobrevive como run isolado
    assert all((end - start) >= 0.0 for start, end in runs)
    assert len(runs) <= 2


def test_melisma_gap_forces_split_even_with_same_pitch():
    # cenário real ("ver" "roubando" o tempo de "ser"): pitch igual dos 2
    # lados (não daria pra separar só pela tolerância de semitons), mas há
    # uma LACUNA de voz real no meio (ex.: a consoante surda "s" de "ser")
    # - isso sozinho já deve forçar a fronteira, "~" não pode atravessá-la.
    first_half = list(np.arange(0.025, 0.3, 0.05))   # hop normal de 0.05
    second_half = list(np.arange(0.5, 0.8, 0.05))     # começa depois de uma lacuna de 0.225s
    timestamps = first_half + second_half
    track = _track(timestamps, pitch_hz=[220.0] * len(timestamps), voicing=[True] * len(timestamps))

    runs = detect_melisma_notes(track, 0.0, 0.8)

    assert len(runs) >= 2, "lacuna de voz deve forçar um novo run mesmo com pitch idêntico"
    assert runs[0][1] <= 0.35 and runs[-1][0] >= 0.45  # fronteira cai dentro da lacuna


def test_melisma_gap_split_survives_even_when_short():
    # a fronteira baseada em lacuna NUNCA pode ser desfeita pela fusão de
    # runs curtos - senão o "ser" da vida volta a ser engolido pelo "ver".
    first_half = list(np.arange(0.025, 0.3, 0.05))
    tiny_tail_after_gap = [0.5, 0.55]  # run curtíssimo (< min_extension_s) mas separado por lacuna
    timestamps = first_half + tiny_tail_after_gap
    track = _track(timestamps, pitch_hz=[220.0] * len(timestamps), voicing=[True] * len(timestamps))

    runs = detect_melisma_notes(track, 0.0, 0.6, min_extension_s=0.15)

    assert len(runs) == 2, "run curto NÃO deve ser fundido de volta quando a fronteira é uma lacuna de voz"


# --------------------------------------------------------------------------
# build_notes: filtro de pontuação + bookkeeping de fim de linha
# --------------------------------------------------------------------------

class _StubPitchExtractor:
    """Nunca lê áudio de verdade - devolve um track vazio (silêncio), o que
    força o fallback de divisão igual e nunca detecta melisma. Isola o
    teste na ESTRUTURA das notas (filtro de pontuação, is_line_end), não na
    análise acústica (já coberta pelos testes acima)."""

    def extract_word_track(self, audio_path, start_s, end_s):
        return _empty_track()

    def summarize_track_window(self, track, start_s, end_s):
        return PitchResult(ultrastar_pitch=0, confidence=1.0, raw_hz=0.0)


def _wt(word, start, end, is_line_end=False):
    return WordTiming(word=word, start=start, end=end, score=0.9, is_line_end=is_line_end)


def test_build_notes_skips_punctuation_only_word():
    word_timings = [
        _wt("pa", 0.0, 0.2),
        _wt("'", 0.2, 0.21),  # token só-pontuação, ex.: "pa ' recorrer" na letra
        _wt("recorrer", 0.21, 0.6, is_line_end=True),
    ]
    grid = BeatGrid(bpm=120.0)
    notes, phrase_breaks = build_notes(word_timings, Path("dummy.wav"), grid, 0, _StubPitchExtractor())

    assert all(n.text.strip() != "'" for n in notes)
    assert phrase_breaks == [len(notes) - 1]


def test_build_notes_keeps_phrase_break_when_last_word_is_punctuation_only():
    # a palavra que fecha a linha é só pontuação - o marcador de quebra de
    # frase não pode sumir por causa disso (bug já corrigido uma vez antes).
    word_timings = [
        _wt("hola", 1.0, 1.2),
        _wt("'", 1.2, 1.21, is_line_end=True),
    ]
    grid = BeatGrid(bpm=120.0)
    notes, phrase_breaks = build_notes(word_timings, Path("dummy.wav"), grid, 0, _StubPitchExtractor())

    assert len(notes) > 0
    assert phrase_breaks == [len(notes) - 1]


# --------------------------------------------------------------------------
# apply_golden_notes (auto-golden: notas mais longas viram "*", espalhadas)
# --------------------------------------------------------------------------
def _mknotes(durs, types=None):
    types = types or [":"] * len(durs)
    return [
        Note(start_beat=i * 20, duration_beats=d, pitch=60, text="la", note_type=t)
        for i, (d, t) in enumerate(zip(durs, types))
    ]


def test_golden_picks_longest_non_adjacent():
    notes = _mknotes([1, 5, 1, 8, 1, 3, 1, 10, 1, 6])
    apply_golden_notes(notes, golden_fraction=0.30, min_duration_beats=2)
    golden = [i for i, n in enumerate(notes) if n.note_type == "*"]
    # orçamento = int(0.30*10+0.5) = 3; as 3 mais longas (10,8,6) nos índices 7,3,9
    assert golden == [3, 7, 9]


def test_golden_never_two_adjacent():
    notes = _mknotes([10, 9, 8, 7])  # todas longas E adjacentes
    apply_golden_notes(notes, golden_fraction=1.0, min_duration_beats=2)
    golden = sorted(i for i, n in enumerate(notes) if n.note_type == "*")
    assert all(b - a >= 2 for a, b in zip(golden, golden[1:]))  # nunca vizinhas
    assert golden == [0, 2]  # 10 e 8; as vizinhas (9, 7) são puladas


def test_golden_skips_freestyle():
    notes = _mknotes([20, 3, 20], types=[":", "F", "F"])
    apply_golden_notes(notes, golden_fraction=1.0, min_duration_beats=2)
    assert notes[0].note_type == "*"
    # "F" nunca vira golden, mesmo sendo a nota mais longa
    assert notes[2].note_type == "F"


def test_golden_skips_short_notes():
    notes = _mknotes([1, 1, 1, 1])  # todas abaixo da duração mínima
    apply_golden_notes(notes, golden_fraction=0.5, min_duration_beats=2)
    assert all(n.note_type == ":" for n in notes)


def test_golden_no_scoreable_returns_unchanged():
    notes = _mknotes([20, 20], types=["F", "F"])
    apply_golden_notes(notes)
    assert all(n.note_type == "F" for n in notes)


def test_golden_budget_scales_with_fraction():
    notes = _mknotes([5] * 100)
    apply_golden_notes(notes, golden_fraction=0.05, min_duration_beats=2)
    n_gold = sum(1 for n in notes if n.note_type == "*")
    assert n_gold == 5  # int(0.05*100+0.5) = 5, espalhadas em índices pares


if __name__ == "__main__":
    import inspect
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn()
                print(f"  ok: {name}")
            except AssertionError as e:
                failed += 1
                print(f"FALHOU: {name}: {e}")
    print("FALHAS:", failed)
    sys.exit(1 if failed else 0)

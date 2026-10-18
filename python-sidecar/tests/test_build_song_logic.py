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
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.align import WordTiming
from pipeline.beatgrid import BeatGrid
from pipeline.build_song import (
    allocate_syllable_durations,
    apply_golden_notes,
    build_notes,
    detect_melisma_notes,
    fix_rounding_overlaps,
    snap_octave_outliers,
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
    #
    # A sílaba era de 0,6 s quando o piso de extensão era 0,15 s. Com a
    # calibração de 17/07/2026 o piso subiu pra 0,25 s, e cada metade daquele
    # fixture media EXATAMENTE 0,25 s - encostava no limite e fundia por erro
    # de float. Alongada pra 1,0 s: testa a mesma INTENÇÃO (salto grande de
    # pitch parte a sílaba) sem ficar em cima do fio da navalha.
    timestamps = list(np.arange(0.025, 0.5, 0.05)) + list(np.arange(0.525, 1.0, 0.05))
    pitch_hz = [220.0] * 10 + [440.0] * 10
    track = _track(timestamps, pitch_hz=pitch_hz, voicing=[True] * 20)

    runs = detect_melisma_notes(track, 0.0, 1.0)

    assert len(runs) >= 2
    assert runs[0][0] == 0.0
    assert runs[-1][1] == 1.0
    assert runs[0][1] < runs[-1][0]  # fronteiras distintas, não colapsadas


def test_melisma_merges_brief_pitch_blip():
    # um "blip" de 1 quadro (bem menor que min_extension_s) não deve virar
    # sua própria nota "~" isolada - funde com o vizinho.
    timestamps = list(np.arange(0.025, 0.3, 0.05)) + [0.31] + list(np.arange(0.35, 0.6, 0.05))
    pitch_hz = [220.0] * 6 + [500.0] + [220.0] * 5
    track = _track(timestamps, pitch_hz=pitch_hz, voicing=[True] * len(timestamps))

    # min_syllable explícito: o teste é da proteção de lacuna, não do limiar
    # de duração (recalibrado pra 0,80 s em 01/10/2026)
    runs = detect_melisma_notes(track, 0.0, 0.6, min_extension_s=0.15,
                                min_syllable_duration_for_melisma=0.45)

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

    # min_syllable explícito: o teste é da proteção de lacuna, não do limiar
    # de duração (recalibrado pra 0,80 s em 01/10/2026)
    runs = detect_melisma_notes(track, 0.0, 0.6, min_extension_s=0.15,
                                min_syllable_duration_for_melisma=0.45)

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


# --------------------------------------------------------------------------
# snap_octave_outliers (consistência de oitava: dobra erros de oitava isolados)
# --------------------------------------------------------------------------
def _pitches(notes):
    return [n.pitch for n in notes]


def test_octave_snaps_isolated_high_note():
    notes = _mknotes([4, 4, 4, 4, 4])
    for n, p in zip(notes, [60, 60, 72, 60, 60]):
        n.pitch = p
    snap_octave_outliers(notes)
    assert _pitches(notes) == [60, 60, 60, 60, 60]  # o 72 (oitava acima) volta


def test_octave_snaps_isolated_low_note():
    notes = _mknotes([4] * 5)
    for n, p in zip(notes, [60, 60, 48, 60, 60]):
        n.pitch = p
    snap_octave_outliers(notes)
    assert _pitches(notes) == [60, 60, 60, 60, 60]  # o 48 (oitava abaixo) sobe


def test_octave_snaps_two_octaves():
    notes = _mknotes([4] * 5)
    for n, p in zip(notes, [60, 60, 84, 60, 60]):
        n.pitch = p
    snap_octave_outliers(notes)
    assert _pitches(notes) == [60, 60, 60, 60, 60]  # 84 (duas oitavas) volta


def test_octave_leaves_real_interval_untouched():
    # um salto de quinta (7 semitons) NÃO é erro de oitava - fica intacto
    notes = _mknotes([4] * 5)
    for n, p in zip(notes, [60, 60, 67, 60, 60]):
        n.pitch = p
    snap_octave_outliers(notes)
    assert _pitches(notes) == [60, 60, 67, 60, 60]


def test_octave_leaves_sustained_high_region():
    # um trecho agudo SUSTENTADO puxa a própria mediana - nada é dobrado
    notes = _mknotes([4] * 10)
    original = [60, 60, 60, 60, 72, 72, 72, 72, 72, 72]
    for n, p in zip(notes, original):
        n.pitch = p
    snap_octave_outliers(notes)
    assert _pitches(notes) == original


# --------------------------------------------------------------------------
# fix_rounding_overlaps
# --------------------------------------------------------------------------

def _beats(spec):
    return [Note(start_beat=s, duration_beats=d, pitch=0, text="la", note_type=":") for s, d in spec]


def _spans(notes):
    return [(n.start_beat, n.duration_beats) for n in notes]


def test_overlap_de_arredondamento_encolhe_a_anterior():
    notes = _beats([(0, 5), (4, 5), (8, 3), (10, 4)])
    fix_rounding_overlaps(notes)
    assert _spans(notes) == [(0, 4), (4, 4), (8, 2), (10, 4)]


def test_notas_de_1_beat_no_mesmo_beat_sao_empurradas_em_fila():
    # o caso do HISTÓRICO DE BUG 1: sem margem pra encolher, empurra a próxima
    notes = _beats([(10, 1), (10, 1), (10, 1), (20, 2)])
    fix_rounding_overlaps(notes)
    assert _spans(notes) == [(10, 1), (11, 1), (12, 1), (20, 2)]


def test_um_tempo_errado_nao_arrasta_o_resto_da_musica():
    # HISTÓRICO DE BUG 2: uma nota 400 beats atrasada arrastava as 3 seguintes
    # pra depois dela (esmagadas em 1 beat) e o validador não via mais nada.
    spec = [(0, 8), (10, 8), (20, 8), (420, 8), (30, 8), (40, 8), (50, 8)]
    notes = _beats(spec)
    fix_rounding_overlaps(notes)
    assert _spans(notes) == spec, "nenhuma nota deveria ter sido mexida"
    # e o problema continua VISÍVEL pro validador (nota 3 x nota 4)
    assert notes[4].start_beat < notes[3].start_beat + notes[3].duration_beats



def test_dourada_minima_e_medida_em_tempo_nao_em_beats():
    """
    O acoplamento sutil da mudanca de faixa de BPM (16/07/2026): a duracao
    minima pra dourar era "2 beats" fixo, e 2 beats so valiam ~273 ms por
    acidente da faixa antiga ([90,180)). Com a grade ~2x mais fina, o mesmo
    "2" viraria ~136 ms e douraria notas curtas demais - mudando o criterio
    sem ninguem pedir. Em TEMPO, o criterio e o mesmo em qualquer BPM.
    """
    from pipeline.beatgrid import BeatGrid
    from pipeline.build_song import GOLDEN_MIN_DURATION_S, golden_min_beats

    # o mesmo limiar em segundos, em BPMs diferentes, tem que dar a mesma
    # duracao real (a menos do arredondamento pra beat inteiro)
    for bpm in (110.0, 220.0, 246.1, 400.0):
        grid = BeatGrid(bpm=bpm)
        beats = golden_min_beats(grid)
        segundos = beats * 60.0 / (bpm * 4)
        assert abs(segundos - GOLDEN_MIN_DURATION_S) < 0.05, (
            f"BPM {bpm}: {beats} beats = {segundos:.3f}s, esperado ~{GOLDEN_MIN_DURATION_S}s"
        )

    # e na faixa nova o valor em beats de fato subiu (grade mais fina)
    assert golden_min_beats(BeatGrid(bpm=220.0)) > golden_min_beats(BeatGrid(bpm=110.0))


def test_dourada_minima_nunca_e_zero():
    from pipeline.beatgrid import BeatGrid
    from pipeline.build_song import golden_min_beats

    assert golden_min_beats(BeatGrid(bpm=1.0)) >= 1


# --- #GAP arredondado ------------------------------------------------------

def test_gap_arredonda_para_10ms():
    """
    Gravavamos o GAP cru (ex.: 1927), sugerindo precisao de 1 ms que nao
    existe - ele vem do inicio da 1a palavra medida pelo alinhador, cujo erro
    tipico e de dezenas de ms (onset mediano de 88 ms na biblioteca gold).
    10 ms e a convencao da comunidade (UltraSinger #29) e fica MUITO abaixo do
    limiar de percepcao (~25 ms), entao nao e audivel.
    """
    from pipeline.build_song import round_gap_ms

    assert round_gap_ms(1927) == 1930
    assert round_gap_ms(1924) == 1920
    assert round_gap_ms(1925) == 1930  # meio pra cima
    assert round_gap_ms(0) == 0


def test_gap_arredondado_nunca_muda_mais_que_meio_passo():
    # o arredondamento nao pode introduzir erro perceptivel: no maximo 5 ms,
    # contra os ~25 ms do limiar de percepcao
    from pipeline.build_song import GAP_ROUND_MS, round_gap_ms

    for g in range(0, 5000, 7):
        assert abs(round_gap_ms(g) - g) <= GAP_ROUND_MS / 2


def test_gap_arredondado_e_sempre_multiplo_do_passo():
    from pipeline.build_song import GAP_ROUND_MS, round_gap_ms

    for g in (0, 1, 4, 5, 9, 1927, 32399, 99999):
        assert round_gap_ms(g) % GAP_ROUND_MS == 0


# --- calibracao do melisma contra charts a mao -----------------------------

def test_melisma_calibrado_contra_charts_a_mao():
    """
    Trava a calibracao (17/07/2026), medida em 1444 charts do USDB:
    produziamos "~" em 15,2% das notas (mediana) contra 5,0% dos humanos - 3x
    mais, e a issue #233 do UltraSinger mostra que excesso irrita o jogador.

    A causa era a tolerancia de 1 semitom: VIBRATO oscila mais que isso
    sozinho, entao liamos vibrato como mudanca de nota. Nao "melhorar" estes
    valores sem medir de novo contra a biblioteca gold.
    """
    from pipeline.build_song import (
        MELISMA_MIN_EXTENSION_S,
        MELISMA_MIN_SYLLABLE_S,
        MELISMA_PITCH_TOLERANCE_ST,
    )

    # 2 st = um tom inteiro: acima do vibrato, abaixo de um salto real.
    # Abaixo disso volta a pegar vibrato; 3 st ja e terca menor e perde melisma.
    assert 1.5 <= MELISMA_PITCH_TOLERANCE_ST <= 2.5
    # silaba mais curta que isso nao esta "sustentada"
    assert MELISMA_MIN_SYLLABLE_S >= 0.40
    # um "~" curto demais nao se percebe como nota
    assert MELISMA_MIN_EXTENSION_S >= 0.20


def test_silaba_curta_nunca_vira_melisma():
    # o portao mais barato: abaixo do minimo, devolve o intervalo inteiro sem
    # nem olhar o pitch
    from pipeline.build_song import MELISMA_MIN_SYLLABLE_S

    ts = list(np.arange(0.01, 1.0, 0.02))
    track = _track(ts, pitch_hz=[220.0] * len(ts), voicing=[True] * len(ts))
    curta = MELISMA_MIN_SYLLABLE_S - 0.05
    assert detect_melisma_notes(track, 0.0, curta) == [(0.0, curta)]


def test_deriva_de_pitch_nao_parte_a_nota_sustentada():
    """
    A CAUSA REAL do excesso de "~" (medida, 17/07/2026): uma nota sustentada
    que ESCORREGA de pitch - glissando/portamento, coisa que cantor faz o
    tempo todo - era partida em duas pela tolerancia de 1 semitom.

    Este teste DISCRIMINA: com tol=1,0 (o valor antigo) a mesma silaba vira 2
    notas; com o valor calibrado, 1. Sem isso o teste passaria nos dois e nao
    provaria nada - foi o que aconteceu com o teste de vibrato que escrevi
    antes (vibrato NUNCA parte a silaba, em profundidade nenhuma: as
    micro-divisoes sao curtas demais e o min_extension_s ja as fundia).
    """
    t = np.arange(0.01, 1.2, 0.02)
    semi = np.linspace(0, 3.0, len(t))          # sobe 3 semitons na silaba
    hz = 220.0 * (2 ** (semi / 12.0))
    track = _track(t, pitch_hz=hz, voicing=[True] * len(t))

    # com o limiar ANTIGO, a deriva partia a nota
    antigo = detect_melisma_notes(
        track, 0.0, 1.2, min_extension_s=0.15,
        pitch_tolerance_semitones=1.0, min_syllable_duration_for_melisma=0.30,
    )
    assert len(antigo) == 2, "o teste precisa discriminar - reveja o fixture"

    # com o calibrado, continua uma nota sustentada
    assert len(detect_melisma_notes(track, 0.0, 1.2)) == 1

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


# ---------------------------------------------------------------------------
# merge_flat_continuations
# ---------------------------------------------------------------------------

from pipeline.build_song import merge_flat_continuations  # noqa: E402


def _n(start, dur, pitch, text, kind=":"):
    return Note(start_beat=start, duration_beats=dur, pitch=pitch, text=text, note_type=kind)


def test_flat_continuations_fold_into_the_attack_note():
    notes = [_n(0, 4, 2, "you"), _n(4, 4, 2, "~"), _n(9, 4, 2, "~ "), _n(14, 2, 5, "next ")]
    out, breaks = merge_flat_continuations(notes, [3], max_gap_beats=3)
    assert [(n.start_beat, n.duration_beats, n.text) for n in out] == [(0, 13, "you "), (14, 2, "next ")]
    assert breaks == [1]


def test_continuation_that_changes_pitch_is_kept():
    notes = [_n(0, 4, 2, "you"), _n(4, 4, 4, "~"), _n(8, 4, 4, "~ ")]
    out, _ = merge_flat_continuations(notes, [], max_gap_beats=3)
    assert [(n.pitch, n.text) for n in out] == [(2, "you"), (4, "~ ")]


def test_no_merge_across_long_gap_word_boundary_or_phrase_break():
    long_gap = [_n(0, 4, 2, "ver"), _n(10, 4, 2, "~ ")]
    assert len(merge_flat_continuations(long_gap, [], max_gap_beats=3)[0]) == 2
    word_end = [_n(0, 4, 2, "ver "), _n(4, 4, 2, "~ ")]
    assert len(merge_flat_continuations(word_end, [], max_gap_beats=3)[0]) == 2
    line_end = [_n(0, 4, 2, "ver"), _n(4, 4, 2, "~ ")]
    assert len(merge_flat_continuations(line_end, [0], max_gap_beats=3)[0]) == 2


def test_freestyle_and_normal_are_not_mixed():
    notes = [_n(0, 4, 2, "you"), _n(4, 4, 2, "~ ", kind="F")]
    assert len(merge_flat_continuations(notes, [], max_gap_beats=3)[0]) == 2


# ---------------------------------------------------------------------------
# fim da palavra seguindo a voz (SUSTAIN_*)
# ---------------------------------------------------------------------------

from pipeline.build_song import extend_end_while_voiced, sustain_limit  # noqa: E402


def _voiced_track(t0, t1, voiced_until, holes=(), hop=0.01):
    ts = np.arange(t0, t1, hop)
    v = ts < voiced_until
    for a, b in holes:
        v[(ts >= a) & (ts < b)] = False
    return PitchTrack(timestamps=ts, pitch_hz=np.full(ts.size, 220.0),
                      confidence=v.astype(float), voicing=v)


def test_sustain_limit_needs_room_and_stops_before_next_word():
    assert sustain_limit(1.0, 1.10) is None            # next word right after
    assert sustain_limit(1.0, 1.30) == pytest.approx(1.20)  # next - gap
    assert sustain_limit(1.0, 5.0) == pytest.approx(1.40)   # capped
    assert sustain_limit(1.0, None) == pytest.approx(1.40)  # last word


def test_end_follows_the_voice_up_to_the_limit():
    tr = _voiced_track(0.5, 2.0, voiced_until=1.25)
    assert extend_end_while_voiced(tr, 1.0, 1.40) == pytest.approx(1.25, abs=0.011)
    tr = _voiced_track(0.5, 2.0, voiced_until=1.9)
    assert extend_end_while_voiced(tr, 1.0, 1.40) == pytest.approx(1.40)


def test_end_crosses_short_dropout_but_not_long_silence_and_never_shrinks():
    tr = _voiced_track(0.5, 2.0, voiced_until=1.30, holes=[(1.10, 1.13)])
    assert extend_end_while_voiced(tr, 1.0, 1.40) == pytest.approx(1.30, abs=0.011)
    tr = _voiced_track(0.5, 2.0, voiced_until=1.30, holes=[(1.05, 1.15)])
    assert extend_end_while_voiced(tr, 1.0, 1.40) == pytest.approx(1.05, abs=0.011)
    tr = _voiced_track(0.5, 2.0, voiced_until=0.8)
    assert extend_end_while_voiced(tr, 1.0, 1.40) == 1.0


from pipeline.build_song import ctc_syllable_spans  # noqa: E402


def test_ctc_syllable_spans_use_measured_starts():
    spans = ctc_syllable_spans([1.02, 1.30, 1.55], 3, 1.00, 2.00)
    assert spans == [(1.00, 1.30), (1.30, 1.55), (1.55, 2.00)]


def test_ctc_syllable_spans_reject_untrustworthy_input():
    assert ctc_syllable_spans(None, 2, 1.0, 2.0) is None
    assert ctc_syllable_spans([1.0, 1.5], 3, 1.0, 2.0) is None      # wrong count
    assert ctc_syllable_spans([1.0, 1.99], 2, 1.0, 2.0) is None     # last one too short
    assert ctc_syllable_spans([1.0, 2.5], 2, 1.0, 2.0) is None      # outside the word
    assert ctc_syllable_spans([1.0], 1, 1.0, 2.0) is None           # single syllable
    assert ctc_syllable_spans([1.0, 3.0], 2, 1.0, 3.5) is None      # non-final syllable > 1.20s


def test_melisma_discards_single_frame_blip_after_voicing_gap():
    ts = np.arange(0.0, 1.0, 0.02)
    voicing = np.zeros(len(ts), dtype=bool)
    voicing[:15] = True      # 0.00..0.28s voiced
    voicing[30] = True       # single frame blip at 0.60s after >80ms gap
    voicing[40:] = True      # 0.80..0.98s voiced
    track = _track(ts, pitch_hz=[220.0] * len(ts), voicing=voicing)
    spans = detect_melisma_notes(track, 0.0, 1.0)
    assert all(end > start for start, end in spans)


def test_rescue_isolated_short_freestyle_inside_sung_phrase():
    from pipeline.build_song import rescue_isolated_short_freestyle

    notes = [
        _n(0, 3, 5, "start "),
        _n(4, 2, 0, "how ", kind="F"),
        _n(7, 4, 7, "now "),
    ]
    out = rescue_isolated_short_freestyle(notes, [2])
    assert out[1].note_type == ":"
    assert out[1].pitch == 5


def test_merge_short_connected_lines_removes_mid_sentence_break():
    from pipeline.build_song import merge_short_connected_lines

    # 240 BPM => 1 beat = 0.0625s. Gap of 1 beat (0.0625s) <= 0.20s between two short connected lines:
    grid = BeatGrid(bpm=240.0)
    notes = [
        _n(0, 2, 4, "Are "),
        _n(2, 2, 4, "you "),
        _n(4, 2, 5, "gon"),
        _n(6, 2, 5, "na "),
        _n(9, 2, 7, "Live "),
        _n(11, 2, 7, "your "),
        _n(13, 3, 6, "life "),
    ]
    assert merge_short_connected_lines(notes, [3, 6], grid) == [6]
    # Sentence-ending punctuation ("?") keeps the break:
    notes_punct = [
        _n(0, 2, 4, "Why? "),
        _n(3, 2, 7, "Live "),
    ]
    assert merge_short_connected_lines(notes_punct, [0, 1], grid) == [0, 1]


def test_build_song_sets_creator():
    from pipeline.build_song import build_song

    grid = BeatGrid(bpm=120.0)
    song = build_song(
        title="Test",
        artist="Artist",
        mp3_filename="test.ogg",
        word_timings=[],
        vocals_wav_path=Path("dummy.wav"),
        grid=grid,
        creator="USKMaker v0.24.1",
    )
    assert song.creator == "USKMaker v0.24.1"
    assert "#CREATOR:USKMaker v0.24.1" in song.to_txt()


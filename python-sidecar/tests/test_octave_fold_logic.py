# -*- coding: utf-8 -*-
"""
fold_octave_outliers_to_context (build_song.py): segunda rede de oitava.

Regressão real (29/09/2026): com o threshold do SwiftF0 em 0.55, "Ne" em Rick
Astley saiu com pitch 36 (três oitavas acima de uma melodia entre -4 e 10), e
o snap_octave_outliers deixou passar - só tenta ±2 oitavas e usa o pitch 0 de
enfeite das vizinhas freestyle. Os casos abaixo reproduzem esse contexto e as
proteções contra achatar salto melódico real. Lógica pura, sem modelo.

Rodar:  python -m pytest tests/ -v   (ou python tests/test_octave_fold_logic.py)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.build_song import fold_octave_outliers_to_context, snap_octave_outliers
from pipeline.ultrastar_writer import Note


def _notes(spec, singer=0):
    """spec: lista de pitches; 'F' antes do número (ex.: 'F0') = freestyle."""
    out = []
    for i, s in enumerate(spec):
        s = str(s)
        free = s.startswith("F")
        out.append(Note(start_beat=4 * i, duration_beats=2, pitch=int(s.lstrip("F")),
                        text="la ", note_type="F" if free else ":", singer=singer))
    return out


def _pitches(notes):
    return [n.pitch for n in notes]


def test_caso_real_rick_astley_tres_oitavas_entre_freestyles():
    # contexto real (nota 554 do chart): vizinhas imediatas são "F" com pitch 0
    spec = [-1, -2, "F0", "F0", -4, "F0", 36, "F0", -3, -4, 3, 2, "F0"]
    notes = _notes(spec)
    # o snap antigo não pega (motivo do bug)...
    assert snap_octave_outliers(_notes(spec))[6].pitch == 36
    fold_octave_outliers_to_context(notes)
    # ...a dobra nova traz pra perto da mediana local, mesma classe de nota
    assert notes[6].pitch == 0
    assert (36 - notes[6].pitch) % 12 == 0
    # e nada mais mudou
    assert [p for i, p in enumerate(_pitches(notes)) if i != 6] == \
           [p for i, p in enumerate(_pitches(_notes(spec))) if i != 6]


def test_dobra_uma_oitava_isolada():
    notes = _notes([10, 12, 11, 7, 24, 7, 10, 10, 7])
    fold_octave_outliers_to_context(notes)
    assert _pitches(notes) == [10, 12, 11, 7, 12, 7, 10, 10, 7]


def test_dobra_oitava_abaixo():
    notes = _notes([0, 0, -4, 6, 0, 0, -12, 5, 4, 0, 0])
    fold_octave_outliers_to_context(notes)
    assert notes[6].pitch == 0


def test_freestyle_nunca_e_mexida_nem_referencia():
    # a F de pitch 30 não muda; e as F de pitch 0 não puxam a mediana:
    # a nota 7 está no meio de uma melodia em ~7, fica como está
    notes = _notes([7, 8, "F30", "F0", "F0", "F0", 6, 7, 9, 8])
    fold_octave_outliers_to_context(notes)
    assert _pitches(notes) == [7, 8, 30, 0, 0, 0, 6, 7, 9, 8]


def test_salto_real_ate_o_limiar_fica():
    # nota isolada a 10 semitons da mediana (sétima menor): ainda é salto que
    # melodia real faz (Rick Astley, "say goodbye", chega a 9) - não mexe
    original = [0, 0, 0, 0, 10, 0, 0, 0, 0]
    notes = _notes(original)
    fold_octave_outliers_to_context(notes)
    assert _pitches(notes) == original


def test_salto_de_oitava_com_companhia_fica():
    # oitava real: o cantor sobe e FICA lá (a nota seguinte continua no agudo)
    original = [0, 1, 0, 2, 12, 13, 0, 1, 0]
    notes = _notes(original)
    fold_octave_outliers_to_context(notes)
    assert _pitches(notes) == original


def test_nota_aguda_sustentada_com_continuacao_fica():
    # "~" da mesma sílaba a 1 semitom: não é nota isolada
    original = [2, 0, 2, 0, 14, 13, 2, 0, 2]
    notes = _notes(original)
    fold_octave_outliers_to_context(notes)
    assert _pitches(notes) == original


def test_mais_de_oitava_e_meia_dobra_mesmo_em_par():
    # duas oitavas longe das vizinhas: nem com companhia isso é melodia
    notes = _notes([0, 2, 0, 2, 24, 25, 0, 2, 0, 2])
    fold_octave_outliers_to_context(notes)
    assert _pitches(notes) == [0, 2, 0, 2, 0, 1, 0, 2, 0, 2]


def test_regiao_aguda_longa_puxa_a_propria_mediana():
    original = [0, 0, 0, 0, 12, 12, 12, 12, 12, 12]
    notes = _notes(original)
    fold_octave_outliers_to_context(notes)
    assert _pitches(notes) == original


def test_dueto_nao_mistura_cantores():
    # P1 grave e P2 uma oitava acima, alternando notas. Misturando os dois, a
    # nota 13 de P2 ficaria a ~12 da mediana e isolada (vizinhas de P1 em 0/1)
    # e seria dobrada; com a referência só do mesmo cantor, ela está em casa.
    pitches = [0, 1, 12, 1, 13, 0, 12, 1, 0]
    singers = [1, 1, 2, 1, 2, 1, 2, 1, 1]
    notes = _notes(pitches)
    for n, s in zip(notes, singers):
        n.singer = s
    fold_octave_outliers_to_context(notes)
    assert _pitches(notes) == pitches
    # controle: o mesmo desenho num cantor só É dobrado (o teste discrimina)
    solo = fold_octave_outliers_to_context(_notes(pitches))
    assert solo[4].pitch == 1


def test_sem_contexto_suficiente_nao_mexe():
    notes = _notes([0, 36])
    fold_octave_outliers_to_context(notes)
    assert _pitches(notes) == [0, 36]
    assert fold_octave_outliers_to_context([]) == []


def test_dobra_sempre_preserva_a_classe_de_nota():
    spec = [3, 5, 4, 41, 5, 3, -20, 4, 6, 5, 29, 4, 3]
    notes = _notes(spec)
    fold_octave_outliers_to_context(notes)
    for antes, depois in zip(spec, _pitches(notes)):
        assert (antes - depois) % 12 == 0
    assert _pitches(notes) == [3, 5, 4, 5, 5, 3, 4, 4, 6, 5, 5, 4, 3]


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

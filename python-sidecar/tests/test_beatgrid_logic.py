# -*- coding: utf-8 -*-
"""
Testes da lógica PURA do beatgrid.py: correção de oitava do BPM (meio/dobro)
e a fórmula de conversão segundo<->beat. Nada aqui carrega librosa nem áudio
(fold_bpm_to_octave e seconds_to_beat são puros).

Rodar:  python -m pytest tests/ -v   (ou python tests/test_beatgrid_logic.py)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.beatgrid import BeatGrid, detect_bpm, fold_bpm_to_octave


def test_fold_mantem_bpm_ja_na_faixa():
    # valores dentro de [200, 400) passam intactos
    for bpm in (200.0, 220.0, 246.1, 300.0, 399.9):
        assert fold_bpm_to_octave(bpm) == bpm


def test_fold_dobra_ate_a_grade_fina():
    # O andamento musical típico (60-180) fica ABAIXO da faixa alvo e é
    # dobrado - não porque a detecção errou, mas porque o #BPM do UltraStar é
    # a unidade da GRADE: gravar 110 dá um beat de 136 ms (~35 ms de erro
    # médio de quantização por nota); 220 dá 68 ms. Ver beatgrid.py.
    assert fold_bpm_to_octave(110.0) == 220.0
    assert fold_bpm_to_octave(123.05) == 246.1
    assert fold_bpm_to_octave(60.0) == 240.0
    assert fold_bpm_to_octave(45.0) == 360.0  # 45 -> 90 -> 180 -> 360


def test_fold_corrige_dobro():
    # detecção que veio alta demais é reduzida à faixa
    assert fold_bpm_to_octave(400.0) == 200.0
    assert fold_bpm_to_octave(800.0) == 200.0
    assert fold_bpm_to_octave(520.0) == 260.0


def test_fold_sempre_cai_na_faixa_alvo():
    # qualquer valor razoável termina em [200, 400)
    for raw in (30.0, 50.5, 95.0, 110.0, 133.7, 210.0, 355.0, 417.0, 900.0):
        out = fold_bpm_to_octave(raw)
        assert 200.0 <= out < 400.0


def test_faixa_alvo_tem_exatamente_uma_oitava():
    # a largura ser 1 oitava (200*2 == 400) é o que torna o dobramento
    # determinístico: todo BPM mapeia pra UM único valor na faixa.
    from pipeline.beatgrid import _OCTAVE_MAX_BPM, _OCTAVE_MIN_BPM

    assert _OCTAVE_MIN_BPM * 2 == _OCTAVE_MAX_BPM


def test_fold_e_idempotente():
    # dobrar o que já foi dobrado não muda nada - é o que faz o fluxo
    # "rode, veja o BPM, redigite ele no campo manual" ser estável.
    for raw in (110.0, 123.05, 45.0, 800.0):
        once = fold_bpm_to_octave(raw)
        assert fold_bpm_to_octave(once) == once


def test_fold_ignora_valores_invalidos():
    assert fold_bpm_to_octave(0.0) == 0.0
    assert fold_bpm_to_octave(-120.0) == -120.0


def test_bpm_manual_e_literal():
    """
    O --bpm do usuário vai pro #BPM EXATAMENTE como veio, mesmo fora da faixa
    alvo - inclusive quando dobrá-lo daria notas mais precisas. O campo é a
    saída de emergência pra quando a automação erra; uma saída de emergência
    que "corrige" o que o usuário digitou não é saída de emergência.

    (Nem toca no áudio: o caminho manual retorna antes de carregar o arquivo,
    por isso o caminho abaixo nem precisa existir.)
    """
    assert detect_bpm(Path("nao-existe.wav"), manual_bpm=110.0).bpm == 110.0
    assert detect_bpm(Path("nao-existe.wav"), manual_bpm=60.0).bpm == 60.0
    # e um valor JÁ na faixa também passa igual, obviamente
    assert detect_bpm(Path("nao-existe.wav"), manual_bpm=246.1).bpm == 246.1


def test_seconds_to_beat_usa_fator_4_e_desconta_gap():
    grid = BeatGrid(bpm=120.0)
    # beats_por_segundo = 120*4/60 = 8; em 1s após o gap => 8 beats
    assert grid.seconds_to_beat(1.0, gap_ms=0.0) == 8
    # gap de 1000ms desconta 1s: em 2.0s => (2.0-1.0)*8 = 8 beats
    assert grid.seconds_to_beat(2.0, gap_ms=1000.0) == 8
    # antes do gap não fica negativo
    assert grid.seconds_to_beat(0.5, gap_ms=1000.0) == 0


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

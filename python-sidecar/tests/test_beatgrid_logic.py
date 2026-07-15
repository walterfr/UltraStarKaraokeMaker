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

from pipeline.beatgrid import BeatGrid, fold_bpm_to_octave


def test_fold_mantem_bpm_ja_na_faixa():
    # valores plausíveis dentro de [90, 180) passam intactos
    for bpm in (90.0, 100.0, 120.0, 128.0, 179.9):
        assert fold_bpm_to_octave(bpm) == bpm


def test_fold_corrige_metade():
    # BPM detectado como metade do real (< 90) é dobrado até a faixa
    assert fold_bpm_to_octave(45.0) == 90.0
    assert fold_bpm_to_octave(60.0) == 120.0
    assert fold_bpm_to_octave(70.0) == 140.0
    assert fold_bpm_to_octave(43.5) == 174.0  # 43.5 -> 87 -> 174


def test_fold_corrige_dobro():
    # BPM detectado como o dobro do real (>= 180) é reduzido à faixa
    assert fold_bpm_to_octave(180.0) == 90.0
    assert fold_bpm_to_octave(240.0) == 120.0
    assert fold_bpm_to_octave(260.0) == 130.0
    assert fold_bpm_to_octave(300.0) == 150.0


def test_fold_sempre_cai_na_oitava_alvo():
    # qualquer valor razoável termina em [90, 180)
    for raw in (30.0, 50.5, 95.0, 133.7, 210.0, 355.0):
        out = fold_bpm_to_octave(raw)
        assert 90.0 <= out < 180.0


def test_fold_ignora_valores_invalidos():
    assert fold_bpm_to_octave(0.0) == 0.0
    assert fold_bpm_to_octave(-120.0) == -120.0


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

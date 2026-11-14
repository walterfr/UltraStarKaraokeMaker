# -*- coding: utf-8 -*-
"""
Testes do modo verificação (C7, --verify-alignment) na Etapa 4 com CTC.

A opção só acrescenta UM Whisper quando o CTC fica sem arbitragem, e só para
o sinal de linha suspeita (_reflag_ctc_lines). Nada aqui carrega modelo: as
funções pesadas são trocadas por falsas que registram as chamadas.

Rodar:  python -m pytest tests/ -v
"""
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
import pipeline.ctc_align as ctc_align

CTC = ["ctc"]
WHI = ["whi"]
STEMS = types.SimpleNamespace(vocals=Path("vocals.wav"))


@pytest.fixture
def calls(monkeypatch):
    rec = {"whisper_plain": 0, "whisper_full": 0, "reflag": [], "fallback": False, "whisper_raises": False}

    def fake_plain(*a, **k):
        rec["whisper_plain"] += 1
        if rec["whisper_raises"]:
            raise RuntimeError("sem VRAM")
        return WHI

    def fake_full(*a, **k):
        rec["whisper_full"] += 1
        return WHI, STEMS

    monkeypatch.setattr(main, "_align_with_ctc", lambda stems, *a, **k: (CTC, stems))
    monkeypatch.setattr(main, "align_lyrics_to_audio", fake_plain)
    monkeypatch.setattr(main, "_align_with_whisper", fake_full)
    monkeypatch.setattr(main, "_reflag_ctc_lines",
                        lambda wt, vocals, whisper_timings=None: rec["reflag"].append(whisper_timings))
    monkeypatch.setattr(main, "_report_ctc_alignment", lambda wt: None)
    monkeypatch.setattr(main, "_report_whisper_alignment", lambda wt: None)
    monkeypatch.setattr(main, "resolve_whisper_device", lambda d: d)
    monkeypatch.setattr(main, "resolve_whisper_model", lambda m, d: "medium")
    monkeypatch.setattr(ctc_align, "should_try_whisper_fallback", lambda *a, **k: rec["fallback"])
    monkeypatch.setattr(ctc_align, "prefer_whisper_over_ctc", lambda *a, **k: False)
    monkeypatch.setattr(ctc_align, "low_confidence_frac", lambda wt: 0.3)
    return rec


def _run(verify):
    return main._align_stage_ctc(
        STEMS, None, Path("work"), "letra.txt", "pt", "cpu", False, "auto", None,
        verify_alignment=verify,
    )


def test_desligado_nao_roda_whisper(calls):
    word_timings, _ = _run(False)
    assert word_timings is CTC
    assert calls["whisper_plain"] == 0 and calls["whisper_full"] == 0
    assert calls["reflag"] == [None]


def test_ligado_com_ctc_mantido_roda_whisper_uma_vez(calls):
    word_timings, _ = _run(True)
    assert word_timings is CTC  # nunca troca o alinhador
    assert calls["whisper_plain"] == 1 and calls["whisper_full"] == 0
    assert calls["reflag"] == [WHI]


def test_ligado_e_whisper_falha_segue_sem_ele(calls):
    calls["whisper_raises"] = True
    word_timings, _ = _run(True)
    assert word_timings is CTC
    assert calls["whisper_plain"] == 1
    assert calls["reflag"] == [None]


def test_ligado_na_arbitragem_nao_roda_whisper_extra(calls):
    calls["fallback"] = True
    word_timings, _ = _run(True)
    assert word_timings is CTC  # prefer_whisper_over_ctc falso: CTC mantido
    assert calls["whisper_plain"] == 0 and calls["whisper_full"] == 1
    assert calls["reflag"] == [WHI]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

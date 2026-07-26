# -*- coding: utf-8 -*-
"""
Test de main.romanize_notes: kana/kanji -> romaji (Hepburn), texto latino passa
direto, e o espaço de fim-de-palavra (fronteira do UltraStar) é preservado.

Pula se o pykakasi não estiver instalado (dep opcional da opção Romanizar).

Rodar:  python tests/test_romanize.py
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


class _Note:
    def __init__(self, text):
        self.text = text


def _skip_if_no_pykakasi():
    try:
        import pykakasi  # noqa: F401
    except ImportError:
        print("SKIP test_romanize (pykakasi não instalado)")
        sys.exit(0)


def test_romaniza_kana_e_kanji_preserva_espaco_e_latino():
    from main import romanize_notes
    notes = [_Note("か"), _Note("漢字 "), _Note("de "), _Note("bad")]
    romanize_notes(notes)
    assert notes[0].text == "ka"
    assert notes[1].text == "kanji "   # espaço de fim-de-palavra mantido
    assert notes[2].text == "de "      # já latino, passa direto
    assert notes[3].text == "bad"


def test_texto_vazio_ou_so_espaco_nao_quebra():
    from main import romanize_notes
    notes = [_Note(""), _Note("   ")]
    romanize_notes(notes)  # não deve levantar
    assert notes[0].text == ""


if __name__ == "__main__":
    _skip_if_no_pykakasi()
    test_romaniza_kana_e_kanji_preserva_espaco_e_latino()
    test_texto_vazio_ou_so_espaco_nao_quebra()
    print("OK test_romanize")

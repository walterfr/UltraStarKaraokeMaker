# -*- coding: utf-8 -*-
"""
Test de main.romanize_notes: cada idioma suportado vira alfabeto latino no
sistema padrão dele (japonês/Hepburn, chinês/Pinyin, coreano/Revised
Romanization, russo+ucraniano/transliteração, hindi/IAST, grego/genérica).
Texto já latino passa direto, idioma sem conversor (ex.: "en"/"pt") não faz
nada, e o espaço de fim-de-palavra (fronteira do UltraStar) é preservado.

Cada bloco pula sozinho se a lib daquele idioma não estiver instalada (deps
opcionais da opção Romanizar).

Rodar:  python tests/test_romanize.py
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


class _Note:
    def __init__(self, text):
        self.text = text


def _has(module: str) -> bool:
    try:
        __import__(module)
        return True
    except ImportError:
        return False


def test_japones_preserva_espaco_e_latino():
    if not _has("pykakasi"):
        print("SKIP ja (pykakasi não instalado)"); return
    from main import romanize_notes
    notes = [_Note("か"), _Note("漢字 "), _Note("de "), _Note("bad")]
    romanize_notes(notes, "ja")
    assert notes[0].text == "ka"
    assert notes[1].text == "kanji "   # espaço de fim-de-palavra mantido
    assert notes[2].text == "de "      # já latino, passa direto
    assert notes[3].text == "bad"


def test_chines_pinyin():
    if not _has("pypinyin"):
        print("SKIP zh (pypinyin não instalado)"); return
    from main import romanize_notes
    notes = [_Note("你好")]
    romanize_notes(notes, "zh")
    assert notes[0].text == "nǐ hǎo"


def test_coreano_revised_romanization():
    if not _has("korean_romanizer"):
        print("SKIP ko (korean-romanizer não instalado)"); return
    from main import romanize_notes
    notes = [_Note("안녕")]
    romanize_notes(notes, "ko")
    assert notes[0].text == "annyeong"


def test_russo_e_ucraniano_transliteracao():
    if not _has("transliterate"):
        print("SKIP ru/uk (transliterate não instalado)"); return
    from main import romanize_notes
    notes_ru = [_Note("привет")]
    romanize_notes(notes_ru, "ru")
    assert notes_ru[0].text == "privet"

    notes_uk = [_Note("привіт")]
    romanize_notes(notes_uk, "uk")
    assert notes_uk[0].text == "pryvit"


def test_hindi_iast():
    if not _has("indic_transliteration"):
        print("SKIP hi (indic-transliteration não instalado)"); return
    from main import romanize_notes
    notes = [_Note("नमस्ते")]
    romanize_notes(notes, "hi")
    assert notes[0].text == "namaste"


def test_grego_transliteracao():
    if not _has("unidecode"):
        print("SKIP el (unidecode não instalado)"); return
    from main import romanize_notes
    notes = [_Note("γειά")]
    romanize_notes(notes, "el")
    assert notes[0].text == "geia"


def test_idioma_sem_conversor_nao_mexe():
    from main import romanize_notes
    notes = [_Note("hello "), _Note("olá ")]
    romanize_notes(notes, "en")
    assert notes[0].text == "hello "
    romanize_notes(notes, "pt")
    assert notes[1].text == "olá "


def test_texto_vazio_ou_so_espaco_nao_quebra():
    from main import romanize_notes
    notes = [_Note(""), _Note("   ")]
    romanize_notes(notes, "ja")  # não deve levantar, mesmo sem lib
    assert notes[0].text == ""


if __name__ == "__main__":
    test_japones_preserva_espaco_e_latino()
    test_chines_pinyin()
    test_coreano_revised_romanization()
    test_russo_e_ucraniano_transliteracao()
    test_hindi_iast()
    test_grego_transliteracao()
    test_idioma_sem_conversor_nao_mexe()
    test_texto_vazio_ou_so_espaco_nao_quebra()
    print("OK test_romanize")

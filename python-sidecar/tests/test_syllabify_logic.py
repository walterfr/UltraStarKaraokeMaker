# -*- coding: utf-8 -*-
"""
Testes de split_word_syllables (syllabify.py) - sem GPU/modelo, só a lógica
de hifenização + tratamento de pontuação.

Rodar:  python -m pytest tests/ -v   (ou python tests/test_syllabify_logic.py)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.syllabify import split_word_syllables


def test_punctuation_only_token_yields_no_syllables():
    # um "'" isolado por espaço na letra não tem conteúdo cantável
    assert split_word_syllables("'") == []
    assert split_word_syllables("...") == []


def test_internal_punctuation_stays_unsplit():
    # contração com apóstrofo NO MEIO: a hifenização pt_BR não sabe lidar
    # com isso e isolaria o "'" como se fosse sílaba própria - mantemos a
    # palavra inteira como uma sílaba só em vez de arriscar isso.
    assert split_word_syllables("It's") == ["It's"]
    assert split_word_syllables("d'água") == ["d'água"]


def test_normal_word_still_hyphenates():
    syllables = split_word_syllables("coração")
    assert len(syllables) >= 3
    assert "".join(syllables) == "coração"


def test_edge_punctuation_still_preserved_on_real_syllables():
    syllables = split_word_syllables("saudade,")
    assert syllables[-1].endswith(",")
    assert "".join(syllables) == "saudade,"


def test_empty_word_yields_empty_list():
    assert split_word_syllables("") == []


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


def test_english_uses_english_hyphenation():
    # pt_BR split English words into extra notes ("lo-ve"); en_US doesn't
    assert split_word_syllables("love", "en") == ["love"]
    assert split_word_syllables("different", "en") == ["dif", "fer", "ent"]


def test_english_sung_contractions_keep_punctuation():
    assert split_word_syllables("Gonna,", "en") == ["Gon", "na,"]


def test_swedish_uses_swedish_hyphenation():
    assert split_word_syllables("kärleken", "sv") == ["kär", "le", "ken"]


def test_unknown_language_keeps_pt_br():
    assert split_word_syllables("coração", "xx") == split_word_syllables("coração")


def test_english_two_syllable_words_missed_by_tex_hyphenation():
    assert split_word_syllables("around?", "en") == ["a", "round?"]
    assert split_word_syllables("Over", "en") == ["O", "ver"]
    assert split_word_syllables("clover", "en") == ["clo", "ver"]
    assert split_word_syllables("tonight", "en") == ["to", "night"]


def test_english_colloquial_g_drop_in_words_split_cleanly():
    assert split_word_syllables("Lookin'", "en") == ["Look", "in'"]
    assert split_word_syllables("wonderin'", "en") == ["won", "der", "in'"]
    assert split_word_syllables("Thinkin'", "en") == ["Think", "in'"]


# -*- coding: utf-8 -*-
"""
Testes do modo dueto: parse das tags P1:/P2:/P1&P2: na letra (align.py),
propagacao do cantor ate a nota, e a escrita do formato de dueto no writer
(headers #P1/#P2, dois blocos P1/P2, nota "ambos" nos dois). O writer Python
e o ORACULO byte-a-byte do rust-core, entao o que trava aqui trava os dois.

Rodar:  python -m pytest tests/test_duet_logic.py -v
        (ou este arquivo direto: python tests/test_duet_logic.py)
"""
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from pipeline.align import (
    _parse_singer_tag,
    _load_lyrics_words_with_line_ends,
    count_singer_tagged_lines,
)
from pipeline.ultrastar_writer import Note, Song
from main import split_duet_artists


# --- parse da tag de cantor -------------------------------------------------

def test_tag_p1_p2_e_ambos():
    assert _parse_singer_tag("P1: hello") == (1, "hello")
    assert _parse_singer_tag("P2:world") == (2, "world")
    assert _parse_singer_tag("P1&P2: both") == (3, "both")
    assert _parse_singer_tag("p1 & p2 : x") == (3, "x")
    assert _parse_singer_tag("P3: y") == (3, "y")
    assert _parse_singer_tag("BOTH: z") == (3, "z")
    assert _parse_singer_tag("Ambos: w") == (3, "w")


def test_tag_ausente_ou_falso_positivo():
    assert _parse_singer_tag("no tag here") == (None, "no tag here")
    # ":" e obrigatorio - uma letra que comeca com "Programa" nao e tag
    assert _parse_singer_tag("Programa de indio") == (None, "Programa de indio")
    # "P1" sem ":" nao dispara
    assert _parse_singer_tag("P1 sem dois pontos") == (None, "P1 sem dois pontos")


def _write(lyr):
    f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
    f.write(lyr)
    f.close()
    return Path(f.name)


def test_carry_over_e_remocao_da_tag():
    # linha sem tag herda o cantor da anterior; a tag some das palavras
    p = _write("P1: you are\nto be true\nP2: cant take\nP1&P2: i love\nplain\n")
    words, ends, singers = _load_lyrics_words_with_line_ends(p)
    p.unlink()
    assert words == ["you", "are", "to", "be", "true", "cant", "take",
                     "i", "love", "plain"]
    assert singers == [1, 1, 1, 1, 1, 2, 2, 3, 3, 3]  # heranca do anterior
    # "true" e "are" sao fins de linha; "plain" tambem
    assert ends == [False, True, False, False, True, False, True,
                    False, True, True]


def test_antes_da_primeira_tag_assume_p1():
    p = _write("no tag yet\nP2: agora sim\n")
    _, _, singers = _load_lyrics_words_with_line_ends(p)
    p.unlink()
    # "no tag yet" (linha 1, sem tag) -> P1 default; "agora sim" -> P2
    assert singers == [1, 1, 1, 2, 2]


def test_count_singer_tagged_lines():
    p = _write("P1: a\nsem tag\nP2: b\nP1&P2: c\n")
    assert count_singer_tagged_lines(p) == 3
    p.unlink()
    p2 = _write("nada\naqui\n")
    assert count_singer_tagged_lines(p2) == 0
    p2.unlink()


# --- writer: formato de dueto ----------------------------------------------

def _duet_song():
    notes = [
        Note(0, 4, 5, "la ", singer=1),
        Note(4, 4, 5, "oh ", singer=3),   # ambos
        Note(8, 4, 7, "na ", singer=2),
        Note(12, 4, 7, "end ", singer=1),
    ]
    return Song("T", "A", "t.ogg", bpm=300, gap_ms=1000, language="pt",
                notes=notes, phrase_breaks_after_index=[1, 2],
                duet=True, p1_name="Elton", p2_name="Kiki")


def test_headers_p1_p2_entre_artist_e_mp3():
    txt = _duet_song().to_txt()
    assert "#ARTIST:A\n#P1:Elton\n#P2:Kiki\n#MP3:t.ogg" in txt


def test_dois_blocos_e_um_unico_E():
    txt = _duet_song().to_txt()
    assert "\nP1\n" in txt and "\nP2\n" in txt
    assert txt.index("\nP1\n") < txt.index("\nP2\n")
    assert txt.rstrip().endswith("\nE")
    assert txt.count("\nE") == 1  # um unico marcador de fim


def test_nota_ambos_aparece_nos_dois_blocos_e_exclusivas_nao():
    txt = _duet_song().to_txt()
    p1 = txt.index("\nP1\n")
    p2 = txt.index("\nP2\n")
    bloco_p1 = txt[p1:p2]
    bloco_p2 = txt[p2:]
    # "oh" (ambos) nos dois; "end" (P1) so no P1; "na" (P2) so no P2
    assert "5 oh " in bloco_p1 and "5 oh " in bloco_p2
    assert "7 end " in bloco_p1 and "7 end " not in bloco_p2
    assert "7 na " in bloco_p2 and "7 na " not in bloco_p1


def test_sem_quebra_orfa_no_fim_do_bloco():
    # a nota 2 ("na") e fim de linha (phrase_break) e e a ULTIMA do bloco P2:
    # nao pode sair um "- " orfao depois dela
    txt = _duet_song().to_txt()
    bloco_p2 = txt[txt.index("\nP2\n"):]
    linhas = bloco_p2.strip().splitlines()
    assert not linhas[-1].startswith("- "), f"quebra orfa: {linhas[-1]!r}"


def test_solo_inalterado_sem_duet():
    notes = [Note(0, 4, 5, "la ", singer=0), Note(4, 4, 5, "la ", singer=0)]
    txt = Song("T", "A", "t.ogg", bpm=300, notes=notes,
               phrase_breaks_after_index=[0]).to_txt()
    assert "#P1:" not in txt and "\nP1\n" not in txt


# --- derivacao dos nomes P1/P2 do #ARTIST ----------------------------------

def test_split_duet_artists():
    assert split_duet_artists("Elton John & Kiki Dee") == ("Elton John", "Kiki Dee")
    assert split_duet_artists("Eminem feat. Dido") == ("Eminem", "Dido")
    assert split_duet_artists("Simon and Garfunkel") == ("Simon", "Garfunkel")
    assert split_duet_artists("Single Artist") == (None, None)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"[OK]   {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"[FAIL] {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} testes passaram")
    sys.exit(1 if failed else 0)

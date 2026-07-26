# -*- coding: utf-8 -*-
"""
Test do writer song.ini do export YARG (main.write_song_ini). Lógica testável:
seção [song], charter fixo, e a emissão CONDICIONAL dos campos opcionais
(song_length/year/genre só saem quando presentes) — a spec do YARG marca todos
como opcionais, então não emitir "year=" vazio importa.

Rodar:  python tests/test_yarg_ini.py
"""
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from main import write_song_ini


def _write(**kw) -> str:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "song.ini"
        write_song_ini(p, "Titulo", "Artista", **kw)
        return p.read_text(encoding="utf-8")


def test_minimo_so_campos_obrigatorios():
    txt = _write()
    assert txt.startswith("[song]\n")
    assert "name=Titulo" in txt
    assert "artist=Artista" in txt
    assert "charter=USKMaker" in txt
    # nenhum opcional presente -> nenhuma linha vazia dele
    assert "song_length=" not in txt
    assert "year=" not in txt
    assert "genre=" not in txt


def test_opcionais_emitidos_quando_presentes():
    txt = _write(length_ms=214000, year=1998, genre="Rock")
    assert "song_length=214000" in txt
    assert "year=1998" in txt
    assert "genre=Rock" in txt


def test_zero_e_none_nao_emitem():
    # year=0 / genre="" são falsy -> não devem virar linha
    txt = _write(length_ms=None, year=0, genre="")
    assert "song_length=" not in txt
    assert "year=" not in txt
    assert "genre=" not in txt


if __name__ == "__main__":
    test_minimo_so_campos_obrigatorios()
    test_opcionais_emitidos_quando_presentes()
    test_zero_e_none_nao_emitem()
    print("OK test_yarg_ini")

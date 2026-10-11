# -*- coding: utf-8 -*-
"""
Testes puros da escolha de release/resultado em pipeline/metadata.py - nada
aqui acessa a rede; as respostas são montadas no formato das APIs.

Rodar:  python -m pytest tests/ -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.metadata import _pick_itunes_result, _pick_release_mbid  # noqa: E402


def _rel(mbid, date, title, primary="Album", secondary=None, artist="Oskar Linnros",
         status="Official"):
    return {"id": mbid, "date": date, "title": title, "status": status,
            "artist-credit": [{"name": artist}],
            "release-group": {"primary-type": primary, "secondary-types": secondary or []}}


def _various(mbid, date, title, status="Official"):
    return _rel(mbid, date, title, secondary=["Compilation"], artist="Various Artists",
                status=status)


# A resposta real do MusicBrainz para "Oskar Linnros - Från och med Du"
# (01/10/2026), na ordem em que veio: 9 das 13 releases são coletâneas.
LINNROS = [{"releases": [
    _various("absolute-hits", "", "Absolute Hits 2010"),
    _various("absolute-64", "2010", "Absolute Music 64"),
    _various("summer-hits", "2010", "Absolute Summer Hits 2010"),
    _rel("single", "2010-05-10", "Från och med Du", primary="Single"),
    _rel("vilja-bli", "2010-06-09", "Vilja bli"),
    _rel("remix", "2010-08-04", "Från och med Du (Adrian Lux remix)", primary="Single"),
    _various("dance-autumn", "2010-09-15", "Absolute Dance Autumn 2010"),
    _various("rix", "2011", "Rix FM - Bäst musik just nu 2011"),
    _various("sommarplagor", "2020-05-06", "Sommarplågor", status="Withdrawn"),
    _various("sommarhits", "2020-06-26", "Sommarhits 2020"),
]}]


def test_artist_album_beats_same_year_compilations():
    # bug real: saía a capa de "Absolute Summer Hits 2010"
    assert _pick_release_mbid(LINNROS) == "vilja-bli"


def test_year_only_date_does_not_beat_a_full_date_of_that_year():
    recs = [{"releases": [_rel("year-only", "2010", "A"), _rel("full", "2010-05-10", "B")]}]
    assert _pick_release_mbid(recs) == "full"


def test_original_live_album_beats_later_compilation():
    # o caso que criou a regra do "mais antigo" (Raimundos, "MTV ao Vivo"):
    # a gravação só existe ao vivo: o ao vivo ganha da coletânea
    recs = [{"releases": [
        _rel("colet", "2003-01-01", "Coletânea", secondary=["Compilation"]),
        _rel("mtv", "2000-01-01", "MTV ao Vivo", secondary=["Live"]),
    ]}]
    assert _pick_release_mbid(recs) == "mtv"


def test_studio_album_beats_earlier_live_recording():
    # "Nothing Else Matters": a gravação ao vivo de 1993 ganhava pela data
    recs = [{"releases": [
        _rel("jakarta", "1993-04-11", "1993-04-11: Jakarta", secondary=["Live"]),
        _rel("black", "2021-09-10", "Metallica"),
    ]}]
    assert _pick_release_mbid(recs) == "black"


def test_earliest_wins_among_equal_releases():
    recs = [{"releases": [_rel("reissue", "2015-01-01", "A"), _rel("orig", "1999-03-01", "A")]}]
    assert _pick_release_mbid(recs) == "orig"


def test_official_beats_withdrawn():
    recs = [{"releases": [_rel("withdrawn", "2001", "A", status="Withdrawn"),
                          _rel("official", "2005", "A")]}]
    assert _pick_release_mbid(recs) == "official"


def test_only_compilations_still_gives_a_cover():
    recs = [{"releases": [_various("b", "2012", "B"), _various("a", "2011-02-02", "A")]}]
    assert _pick_release_mbid(recs) == "a"


def test_no_releases():
    assert _pick_release_mbid([]) is None
    assert _pick_release_mbid([{"releases": [{"title": "sem id"}]}]) is None


def test_itunes_skips_various_artists_collections():
    results = [
        {"collectionName": "Strictly CAZZETTE (Mixed Version)", "collectionArtistName": "Various Artists"},
        {"collectionName": "Levels - Single"},
    ]
    assert _pick_itunes_result(results)["collectionName"] == "Levels - Single"


def test_itunes_only_compilations_falls_back_to_first():
    results = [{"collectionName": "X", "collectionArtistName": "Various Artists"}]
    assert _pick_itunes_result(results)["collectionName"] == "X"
    assert _pick_itunes_result([]) is None


def test_extract_embedded_cover_ogg_vorbis():
    import base64
    from mutagen.flac import Picture
    from pipeline.metadata import _extract_embedded_cover_bytes

    class DummyOggFile:
        def __init__(self, tags):
            self.tags = tags

    fake_png = b"\x89PNG\r\n\x1a\nfakeimagebytes"

    # 1. Vorbis COVERART tag (base64 de imagem pura)
    b64_cover = base64.b64encode(fake_png).decode("ascii")
    dummy = DummyOggFile({"coverart": [b64_cover]})
    assert _extract_embedded_cover_bytes(dummy) == fake_png

    # 2. METADATA_BLOCK_PICTURE tag (base64 de bloco Picture FLAC)
    pic = Picture()
    pic.data = fake_png
    pic.type = 3
    pic.mime = "image/png"
    b64_pic = base64.b64encode(pic.write()).decode("ascii")
    dummy_mbp = DummyOggFile({"metadata_block_picture": [b64_pic]})
    assert _extract_embedded_cover_bytes(dummy_mbp) == fake_png


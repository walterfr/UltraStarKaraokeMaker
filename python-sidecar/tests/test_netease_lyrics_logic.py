# -*- coding: utf-8 -*-
"""Testes da lógica de busca e limpeza de letra sincronizada da NetEase."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fetch_netease_lyrics import _clean_lrc, _lrc_to_plain, search_netease


def test_clean_lrc_removes_credits_and_metadata():
    raw = """
[00:00.000] 作词 : Chris Martin
[00:01.000] 作曲 : Jonny Buckland
[00:02.000] 制作人 : Ken Nelson
[00:03.000] Written by : Coldplay
[00:10.500] Look at the stars
[00:15.200] Look how they shine for you
[05:00.000] Lead Vocals : Chris Martin
[05:01.000] Recorded at Abbey Road
"""
    cleaned = _clean_lrc(raw)
    lines = cleaned.splitlines()
    assert len(lines) == 2
    assert lines[0] == "[00:10.500] Look at the stars"
    assert lines[1] == "[00:15.200] Look how they shine for you"


def test_lrc_to_plain():
    lrc = """
[00:10.500] Look at the stars
[00:15.200] Look how they shine for you
"""
    plain = _lrc_to_plain(lrc)
    assert plain == "Look at the stars\nLook how they shine for you"


def test_search_netease_empty_inputs():
    res = search_netease("", "")
    assert res["ok"] is False
    assert res["syncedLyrics"] is None

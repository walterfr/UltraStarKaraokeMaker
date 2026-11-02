# -*- coding: utf-8 -*-
"""read_tags.py devolve a duração do áudio (mostrador Música x Letra)."""
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from read_tags import read_tags


def _write_silence_wav(path: Path, seconds: float, rate: int = 8000) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))


def test_duration_from_untagged_wav(tmp_path):
    p = tmp_path / "silence.wav"
    _write_silence_wav(p, 3.0)
    out = read_tags(str(p))
    assert out["duration"] is not None
    assert abs(out["duration"] - 3.0) < 0.05
    assert out["title"] is None


def test_missing_file_has_null_duration(tmp_path):
    out = read_tags(str(tmp_path / "nao_existe.mp3"))
    assert out["duration"] is None

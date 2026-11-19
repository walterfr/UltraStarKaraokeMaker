"""Fallback de nomes do _separate_with_roformer: o stem de acompanhamento
("no_vocals", "(other)_vocals_...") não pode ser confundido com o vocal."""
import sys
import types

from pipeline.separate import _separate_with_roformer


def _fake_separator(names):
    class Separator:
        def __init__(self, output_dir, output_format):
            self.dir = output_dir

        def load_model(self, model_filename):
            pass

        def separate(self, path, custom_output_names):
            from pathlib import Path
            for n in names:
                (Path(self.dir) / n).write_bytes(b"x")
            return names

    mod = types.ModuleType("audio_separator.separator")
    mod.Separator = Separator
    return mod


def _run(tmp_path, monkeypatch, names):
    monkeypatch.setitem(sys.modules, "audio_separator", types.ModuleType("audio_separator"))
    monkeypatch.setitem(sys.modules, "audio_separator.separator", _fake_separator(names))
    return _separate_with_roformer(tmp_path / "song.wav", tmp_path)


def test_other_stem_vira_instrumental(tmp_path, monkeypatch):
    # Ordem ruim de propósito: o acompanhamento vem antes e também contém "vocals".
    names = ["song_(other)_vocals_mel_band_roformer.wav", "song_(vocals)_vocals_mel_band_roformer.wav"]
    stems = _run(tmp_path, monkeypatch, names)
    d = tmp_path / "roformer" / "song"
    assert stems.vocals == d / "vocals.wav" and stems.instrumental == d / "no_vocals.wav"
    assert not (d / names[0]).exists() and not (d / names[1]).exists()


def test_no_vocals_nao_vira_vocal(tmp_path, monkeypatch):
    names = ["song_no_vocals_x.wav", "song_vocals_x.wav"]
    stems = _run(tmp_path, monkeypatch, names)
    assert stems.vocals.exists() and stems.instrumental.exists()

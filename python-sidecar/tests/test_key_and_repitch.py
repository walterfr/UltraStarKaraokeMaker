# -*- coding: utf-8 -*-
"""
Testes para:
  1. Detecção de tom musical (detect_key_from_chroma / parse_key_string / quantize_pitch_to_key)
  2. Header #TAGS no ultrastar_writer
  3. Corte de silêncio interno em sílabas médias (detect_melisma_notes) e gate acústico RMS (_frame_audible_mask)
  4. Cálculo de Score Vocal (0-10.000) e Re-pitch de notas (repitch.py)
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.beatgrid import (
     _KRUMHANSL_MAJOR,
    _KRUMHANSL_MINOR,
    detect_key_from_chroma,
    parse_key_string,
    quantize_pitch_to_key,
)
from pipeline.build_song import detect_melisma_notes
from pipeline.pitch import PitchResult, PitchTrack, _frame_audible_mask
from pipeline.repitch import calculate_vocal_adherence_score, repitch_notes_from_audio
from pipeline.ultrastar_writer import Note, Song


def test_detect_key_from_chroma_identifies_major_and_minor_and_transpose():
    # C major (shift 0)
    assert detect_key_from_chroma(_KRUMHANSL_MAJOR) == "C major"
    # A minor (shift 9: A)
    a_minor_chroma = np.roll(_KRUMHANSL_MINOR, 9)
    assert detect_key_from_chroma(a_minor_chroma) == "A minor"
    # Com transpose +2 semitons, C major vira D major
    assert detect_key_from_chroma(_KRUMHANSL_MAJOR, transpose=2) == "D major"
    # Com transpose -3 semitons, C major vira A major
    assert detect_key_from_chroma(_KRUMHANSL_MAJOR, transpose=-3) == "A major"
    # Vetor nulo ou constante devolve None
    assert detect_key_from_chroma(np.zeros(12)) is None


def test_parse_and_quantize_pitch_to_key():
    assert parse_key_string("C major") == (0, "major")
    assert parse_key_string("key: F# minor") == (6, "minor")
    assert parse_key_string("invalid") is None

    # Em Dó maior (C=0, D=2, E=4, F=5, G=7, A=9, B=11):
    # Notas da escala ficam intactas:
    for p in (0, 2, 4, 5, 7, 9, 11, 12, -3):
        assert quantize_pitch_to_key(p, "C major") == p

    # C# (pitch=1) está entre C (0) e D (2):
    # Se vizinha está em D (2) ou E (4), puxa para 2; se vizinha está em C (0), puxa para 0
    assert quantize_pitch_to_key(1, "C major", neighbor_pitch=4) == 2
    assert quantize_pitch_to_key(1, "C major", neighbor_pitch=0) == 0


def test_song_to_txt_writes_tags_header():
    song = Song(
        title="Title",
        artist="Artist",
        mp3_filename="song.ogg",
        bpm=240.0,
        tags="key: A minor",
    )
    txt = song.to_txt()
    assert "#TAGS:key: A minor\n#CREATOR:" in txt


def test_medium_syllable_splits_on_internal_silence_but_not_pitch_drift():
    # Sílaba de 0,60 s (< MELISMA_MIN_SYLLABLE_S = 0,80 s):
    # 1) Com voz contínua e salto de 1 oitava, NÃO divide (preserva limiar de 0,80s para pitch)
    ts_cont = np.arange(0.02, 0.60, 0.02)
    hz_jump = [220.0 if t < 0.30 else 440.0 for t in ts_cont]
    track_cont = PitchTrack(
        timestamps=ts_cont,
        pitch_hz=np.asarray(hz_jump),
        confidence=np.full(ts_cont.size, 0.9),
        voicing=np.ones(ts_cont.size, dtype=bool),
    )
    assert detect_melisma_notes(track_cont, 0.0, 0.60) == [(0.0, 0.60)]

    # 2) Com buraco real de silêncio interno de 0,20 s (0,18..0,38s sem voz), DIVIDE em 2 notas (~)
    ts_gap = np.concatenate([np.arange(0.02, 0.18, 0.02), np.arange(0.38, 0.58, 0.02)])
    track_gap = PitchTrack(
        timestamps=ts_gap,
        pitch_hz=np.full(ts_gap.size, 220.0),
        confidence=np.full(ts_gap.size, 0.9),
        voicing=np.ones(ts_gap.size, dtype=bool),
    )
    runs = detect_melisma_notes(track_gap, 0.0, 0.60)
    assert len(runs) == 2
    assert runs[0][1] <= 0.20 and runs[1][0] >= 0.36


def test_frame_audible_mask_gates_deep_silence_hole():
    sr = 16000
    # 0.6s de áudio: 0.0..0.2s seno alto (0.5), 0.2..0.4s silêncio (0.0), 0.4..0.6s seno alto (0.5)
    t = np.arange(int(0.6 * sr)) / sr
    sig = np.sin(2 * np.pi * 220.0 * t) * 0.5
    sig[(t >= 0.20) & (t < 0.40)] = 0.0

    rel_ts = np.array([0.10, 0.30, 0.50])
    mask = _frame_audible_mask(sig, sr, rel_ts)
    assert list(mask) == [True, False, True]


class _MockPitchExtractor:
    def __init__(self, pitches_by_index: list[int]):
        self._pitches = pitches_by_index
        self._idx = 0

    def extract_segment_pitch(self, audio_path: str, start_s: float, end_s: float) -> PitchResult:
        p = self._pitches[min(self._idx, len(self._pitches) - 1)]
        self._idx += 1
        return PitchResult(ultrastar_pitch=p, confidence=0.90, raw_hz=440.0)


def test_vocal_score_and_repitch():
    # Chart com 4 notas (2 frases) todas com pitch 0 (tapped chart antigo),
    # enquanto a voz real canta [4, 5, 7, 9]:
    notes = [
        Note(start_beat=0, duration_beats=4, pitch=0, text="la "),
        Note(start_beat=6, duration_beats=4, pitch=0, text="le "),
        Note(start_beat=12, duration_beats=4, pitch=0, text="li "),
        Note(start_beat=18, duration_beats=4, pitch=0, text="lo ", note_type="*"),
    ]
    res = repitch_notes_from_audio(
        notes=notes,
        phrase_breaks=[1, 3],
        bpm=240.0,
        gap_ms=0,
        audio_path="dummy.wav",
        pitch_extractor=_MockPitchExtractor([4, 5, 7, 9]),
    )
    assert res.updated_count == 4
    assert [n["pitch"] for n in res.notes] == [4, 5, 7, 9]
    assert res.before_score.accurate == 0
    assert res.after_score.simple == 10000
    assert res.after_score.accurate == 10000

    # Se o chart estiver 1 oitava acima ([16, 17, 19, 21]) da voz ([4, 5, 7, 9]):
    # simple_score dá 10.000 (mesma classe de nota), accurate_score dá 0:
    octave_off_notes = [
        Note(start_beat=0, duration_beats=4, pitch=16, text="la "),
        Note(start_beat=6, duration_beats=4, pitch=17, text="le "),
    ]
    score = calculate_vocal_adherence_score(octave_off_notes, [0, 1], [4, 5])
    assert score.simple == 10000
    assert score.accurate == 0

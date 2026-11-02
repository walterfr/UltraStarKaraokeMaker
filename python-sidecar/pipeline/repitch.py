"""
repitch.py
Re-extração de pitches (SwiftF0) para notas já existentes e cálculo do Score
de Aderência Vocal (0-10.000 pontos no padrão UltraStar: 9.000 de notas/golden
+ 1.000 de bônus de frase).

Permite:
  1. Consertar os pitches de um chart/pacote mantendo os tempos e sílabas que
     o usuário já ajustou na tela de revisão (ou importou de um .txt legado).
  2. Medir objetivamente quão bem os pitches das notas batem com a faixa vocal
     isolada (Simple = classe de nota ignorando oitava; Accurate = oitava exata).

Uso via CLI (chamado pelo comando Tauri `repitch_song`):
    python -m pipeline.repitch --dir "C:/caminho/pacote"
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from .beatgrid import BeatGrid
from .build_song import fold_octave_outliers_to_context, snap_octave_outliers
from .pitch import PitchExtractor
from .ultrastar_writer import Note

MAX_SONG_SCORE = 10000
MAX_LINE_BONUS = 1000


@dataclass
class VocalScore:
    simple: int    # 0..10000 (ignora oitava, tolerância ±1 semitom na classe de nota)
    accurate: int  # 0..10000 (oitava exata, tolerância ±1 semitom)


@dataclass
class RepitchResult:
    notes: list[dict]
    updated_count: int
    voiced_count: int
    before_score: VocalScore
    after_score: VocalScore


def _note_weight(note_type: str, duration_beats: int) -> int:
    dur = max(1, int(duration_beats))
    if note_type in ("*", "G"):
        return dur * 2
    if note_type in (":", "R"):
        return dur
    return 0


def _matches_simple(chart_pitch: int, measured_pitch: int, tol_semitones: int = 1) -> bool:
    diff = (chart_pitch - measured_pitch) % 12
    pc_dist = min(diff, 12 - diff)
    return pc_dist <= tol_semitones


def _matches_accurate(chart_pitch: int, measured_pitch: int, tol_semitones: int = 1) -> bool:
    return abs(chart_pitch - measured_pitch) <= tol_semitones


def calculate_vocal_adherence_score(
    notes: list[Note],
    phrase_breaks: list[int],
    measured_pitches: list[int | None],
) -> VocalScore:
    """
    Calcula a pontuação UltraStar (0-10.000) que a própria voz da gravação
    atingiria cantando `notes`.
    """
    scoreable_indices = [
        i for i, n in enumerate(notes)
        if _note_weight(n.note_type, n.duration_beats) > 0
        and i < len(measured_pitches)
        and measured_pitches[i] is not None
    ]
    if not scoreable_indices:
        return VocalScore(simple=0, accurate=0)

    # Divide em frases pelos phrase_breaks para calcular o bônus de linha (1.000 pts)
    breaks = set(phrase_breaks)
    phrases: list[list[int]] = []
    cur: list[int] = []
    for i in range(len(notes)):
        if i in scoreable_indices:
            cur.append(i)
        if i in breaks or i == len(notes) - 1:
            if cur:
                phrases.append(cur)
                cur = []
    if cur:
        phrases.append(cur)

    has_line_bonus = len(phrases) > 1
    note_pool = MAX_SONG_SCORE - MAX_LINE_BONUS if has_line_bonus else MAX_SONG_SCORE
    line_pool = MAX_LINE_BONUS if has_line_bonus else 0

    total_weight = sum(_note_weight(notes[i].note_type, notes[i].duration_beats) for i in scoreable_indices)
    if total_weight <= 0:
        return VocalScore(simple=0, accurate=0)

    simple_weight = 0
    accurate_weight = 0
    for i in scoreable_indices:
        w = _note_weight(notes[i].note_type, notes[i].duration_beats)
        mp = measured_pitches[i]
        assert mp is not None
        if _matches_simple(notes[i].pitch, mp):
            simple_weight += w
        if _matches_accurate(notes[i].pitch, mp):
            accurate_weight += w

    simple_line_pts = 0.0
    accurate_line_pts = 0.0
    if has_line_bonus and phrases:
        per_phrase = line_pool / len(phrases)
        for ph in phrases:
            ph_total = sum(_note_weight(notes[i].note_type, notes[i].duration_beats) for i in ph)
            if ph_total <= 0:
                continue
            ph_simple = sum(
                _note_weight(notes[i].note_type, notes[i].duration_beats)
                for i in ph
                if _matches_simple(notes[i].pitch, measured_pitches[i])  # type: ignore[arg-type]
            )
            ph_acc = sum(
                _note_weight(notes[i].note_type, notes[i].duration_beats)
                for i in ph
                if _matches_accurate(notes[i].pitch, measured_pitches[i])  # type: ignore[arg-type]
            )
            if ph_simple / ph_total >= 0.80:
                simple_line_pts += per_phrase
            if ph_acc / ph_total >= 0.80:
                accurate_line_pts += per_phrase

    simple_total = min(
        MAX_SONG_SCORE,
        round(note_pool * (simple_weight / total_weight) + simple_line_pts),
    )
    accurate_total = min(
        MAX_SONG_SCORE,
        round(note_pool * (accurate_weight / total_weight) + accurate_line_pts),
    )
    return VocalScore(simple=int(simple_total), accurate=int(accurate_total))


def repitch_notes_from_audio(
    notes: list[Note],
    phrase_breaks: list[int],
    bpm: float,
    gap_ms: int,
    audio_path: Path | str,
    pitch_extractor: PitchExtractor | None = None,
) -> RepitchResult:
    """
    Re-extrai o pitch de cada nota pontuável a partir de `audio_path`, aplica
    consistência de oitava e calcula o Score Vocal antes e depois.
    """
    extractor = pitch_extractor or PitchExtractor()
    grid = BeatGrid(bpm=bpm)
    audio_str = str(audio_path)

    measured_pitches: list[int | None] = []
    for n in notes:
        if n.note_type == "F":
            measured_pitches.append(None)
            continue
        start_s = grid.beat_to_seconds(n.start_beat, gap_ms)
        end_s = grid.beat_to_seconds(n.start_beat + max(1, n.duration_beats), gap_ms)
        res = extractor.extract_segment_pitch(audio_str, start_s, max(start_s + 0.02, end_s))
        if res.confidence >= 0.5:
            measured_pitches.append(res.ultrastar_pitch)
        else:
            measured_pitches.append(None)

    before_score = calculate_vocal_adherence_score(notes, phrase_breaks, measured_pitches)

    new_notes = [copy.deepcopy(n) for n in notes]
    for i, n in enumerate(new_notes):
        if n.note_type != "F" and measured_pitches[i] is not None:
            n.pitch = int(measured_pitches[i])  # type: ignore[arg-type]

    new_notes = snap_octave_outliers(new_notes)
    new_notes = fold_octave_outliers_to_context(new_notes)

    updated_count = sum(
        1 for orig, upd in zip(notes, new_notes)
        if orig.note_type != "F" and orig.pitch != upd.pitch
    )
    voiced_count = sum(1 for mp in measured_pitches if mp is not None)
    after_score = calculate_vocal_adherence_score(new_notes, phrase_breaks, measured_pitches)

    return RepitchResult(
        notes=[asdict(n) for n in new_notes],
        updated_count=updated_count,
        voiced_count=voiced_count,
        before_score=before_score,
        after_score=after_score,
    )


def resolve_package_vocal_audio(out_dir: Path, song_dict: dict) -> Path | None:
    """
    Procura a melhor fonte vocal disponível na pasta do pacote:
      1. _work/stems/htdemucs/*/vocals.wav
      2. vocals_filename no pacote (ex.: 'Artista - Música [VOC].ogg')
      3. mp3_filename no pacote (fallback quando os intermediários foram limpos)
    """
    stems_dir = out_dir / "_work" / "stems" / "htdemucs"
    if stems_dir.is_dir():
        for child in stems_dir.iterdir():
            cand = child / "vocals.wav"
            if cand.is_file():
                return cand
    voc_fn = song_dict.get("vocals_filename")
    if voc_fn:
        cand = out_dir / voc_fn
        if cand.is_file():
            return cand
    mp3_fn = song_dict.get("mp3_filename")
    if mp3_fn:
        cand = out_dir / mp3_fn
        if cand.is_file():
            return cand
    return None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Re-calcula pitches e score vocal de um pacote UltraStar")
    parser.add_argument("--dir", required=True, help="Diretório do pacote")
    args = parser.parse_args()

    out_dir = Path(args.dir)
    in_json = out_dir / "_repitch_in.json"
    if not in_json.is_file():
        in_json = out_dir / "song_data.json"
    if not in_json.is_file():
        print(f"Arquivo song_data.json não encontrado em {out_dir}", file=sys.stderr)
        return 1

    song_dict = json.loads(in_json.read_text(encoding="utf-8"))
    audio_path = resolve_package_vocal_audio(out_dir, song_dict)
    if audio_path is None:
        print(f"Áudio vocal não encontrado em {out_dir}", file=sys.stderr)
        return 1

    notes = [
        Note(
            start_beat=int(n["start_beat"]),
            duration_beats=int(n["duration_beats"]),
            pitch=int(n["pitch"]),
            text=str(n["text"]),
            note_type=str(n.get("note_type", ":")),
            source=n.get("source"),
            score=n.get("score"),
            singer=int(n.get("singer", 0)),
        )
        for n in song_dict.get("notes", [])
    ]
    phrase_breaks = [int(b) for b in song_dict.get("phrase_breaks_after_index", [])]
    bpm = float(song_dict["bpm"])
    gap_ms = int(song_dict.get("gap_ms", 0))

    result = repitch_notes_from_audio(
        notes=notes,
        phrase_breaks=phrase_breaks,
        bpm=bpm,
        gap_ms=gap_ms,
        audio_path=audio_path,
    )
    print(json.dumps(asdict(result), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

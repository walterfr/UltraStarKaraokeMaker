"""
pitch.py
Etapa 5 da pipeline: extrair a frequência fundamental (F0) do vocal isolado
e converter para o formato de pitch do UltraStar (semitons relativos a C4=0).

API REAL do swift-f0 (corrigida em 05/07/2026 após erro de suposição inicial -
a API original documentada no código era ilustrativa e estava errada):

    from swift_f0 import SwiftF0

    detector = SwiftF0(confidence_threshold=0.9, fmin=46.875, fmax=2093.75)
    result = detector.detect_from_array(audio_array, sample_rate)  # ou detect_from_file(path)

    # PitchResult é um conjunto de arrays paralelos, um valor por frame:
    #   result.pitch_hz    -> F0 estimado (Hz) por frame
    #   result.confidence  -> confiança do modelo (0-1) por frame
    #   result.timestamps  -> centro de cada frame em segundos
    #   result.voicing     -> bool por frame (já usa confidence_threshold internamente)

Não existe parâmetro `model_size` (isso era uma suposição incorreta de quem
escreveu a primeira versão deste arquivo). O detector sempre roda o mesmo
modelo; o que se ajusta é o threshold de confiança e a faixa de frequência.

NOTA para canto: fmin/fmax padrão (46.875-2093.75 Hz, G1 a C7) já cobre bem
a faixa vocal humana em canto. Se detectar oitava errada com frequência,
considere restringir a faixa pra tessitura conhecida do cantor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import soundfile as sf
from swift_f0 import SwiftF0

_MIDI_C4 = 60  # UltraStar: pitch 0 == C4 == MIDI 60


@dataclass
class PitchResult:
    ultrastar_pitch: int   # valor pronto para o .txt (relativo a C4=0)
    confidence: float
    raw_hz: float


@dataclass
class PitchTrack:
    """
    Dados de pitch quadro-a-quadro (não colapsados a uma mediana), usados
    para decidir COMO uma palavra se divide em sílabas/notas (build_song.py)
    em vez de simplesmente dividir a duração igualmente. `timestamps` é
    ABSOLUTO (segundos desde o início do áudio, não relativo ao segmento
    extraído) para poder ser comparado direto com os tempos de WordTiming.
    """
    timestamps: np.ndarray
    pitch_hz: np.ndarray
    confidence: np.ndarray
    voicing: np.ndarray  # bool


def hz_to_ultrastar_pitch(hz: float) -> int:
    """Converte Hz -> semitom relativo a C4 (pitch 0 do UltraStar)."""
    if hz <= 0:
        return 0
    midi_note = 69 + 12 * math.log2(hz / 440.0)  # 440Hz = A4 = MIDI 69
    return round(midi_note - _MIDI_C4)


class PitchExtractor:
    def __init__(
        self,
        confidence_threshold: float = 0.85,
        # 0.85 em vez do padrão 0.9 da lib: canto tende a puxar a confiança
        # um pouco pra baixo em notas com vibrato/vogal esticada (mesmo
        # padrão que já observamos no alinhamento fonético do whisperx -
        # ver nota em align.py). Ajustar se estiver descartando notas boas.
        fmin: float = 46.875,
        fmax: float = 2093.75,
    ):
        self.model = SwiftF0(confidence_threshold=confidence_threshold, fmin=fmin, fmax=fmax)

    def extract_segment_pitch(self, audio_path: str, start_s: float, end_s: float) -> PitchResult:
        track = self.extract_word_track(audio_path, start_s, end_s)
        return self.summarize_track_window(track, start_s, end_s)

    def extract_word_track(self, audio_path: str, start_s: float, end_s: float) -> PitchTrack:
        """
        Roda o detector de pitch UMA VEZ sobre o intervalo (tipicamente uma
        PALAVRA inteira) e devolve os quadros crus, sem colapsar a uma
        mediana - build_song.py usa isso para decidir onde estão os limites
        reais de cada sílaba e onde há sustentação (melisma), em vez de só
        dividir a duração da palavra igualmente entre as sílabas.
        """
        y, sr = sf.read(audio_path)
        start_sample = int(start_s * sr)
        end_sample = int(end_s * sr)
        segment = y[start_sample:end_sample]

        if segment.size == 0:
            empty = np.array([])
            return PitchTrack(timestamps=empty, pitch_hz=empty, confidence=empty, voicing=np.array([], dtype=bool))

        result = self.model.detect_from_array(segment, sr)
        return PitchTrack(
            timestamps=np.asarray(result.timestamps) + start_s,  # absoluto
            pitch_hz=np.asarray(result.pitch_hz),
            confidence=np.asarray(result.confidence),
            voicing=np.asarray(result.voicing, dtype=bool),
        )

    def summarize_track_window(self, track: PitchTrack, start_s: float, end_s: float) -> PitchResult:
        """
        Colapsa os quadros de `track` que caem em [start_s, end_s) para um
        PitchResult (mediana Hz + confiança média dos quadros vozeados) -
        mesma lógica que `extract_segment_pitch` fazia inline, mas reusável
        para qualquer subjanela (sílaba, run de melisma) sem reler o áudio.
        """
        if track.timestamps.size == 0:
            return PitchResult(ultrastar_pitch=0, confidence=0.0, raw_hz=0.0)

        in_window = (track.timestamps >= start_s) & (track.timestamps < end_s)
        mask = in_window & track.voicing
        voiced_hz = track.pitch_hz[mask]
        voiced_conf = track.confidence[mask]

        if voiced_hz.size == 0:
            return PitchResult(ultrastar_pitch=0, confidence=0.0, raw_hz=0.0)

        median_hz = float(np.median(voiced_hz))
        avg_confidence = float(np.mean(voiced_conf))

        return PitchResult(
            ultrastar_pitch=hz_to_ultrastar_pitch(median_hz),
            confidence=avg_confidence,
            raw_hz=median_hz,
        )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Etapa 5: teste isolado de pitch em um trecho")
    parser.add_argument("--vocals", required=True)
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--end", type=float, required=True)
    args = parser.parse_args()

    extractor = PitchExtractor()
    result = extractor.extract_segment_pitch(args.vocals, args.start, args.end)
    print(f"[OK] Hz={result.raw_hz:.1f}  pitch UltraStar={result.ultrastar_pitch}  confiança={result.confidence:.2f}")

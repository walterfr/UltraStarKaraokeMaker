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
        y, sr = sf.read(audio_path)
        start_sample = int(start_s * sr)
        end_sample = int(end_s * sr)
        segment = y[start_sample:end_sample]

        if segment.size == 0:
            return PitchResult(ultrastar_pitch=0, confidence=0.0, raw_hz=0.0)

        result = self.model.detect_from_array(segment, sr)

        voiced_hz = result.pitch_hz[result.voicing]
        voiced_conf = result.confidence[result.voicing]

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

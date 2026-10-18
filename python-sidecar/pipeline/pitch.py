"""
pitch.py
Etapa 5 da pipeline: extrair a frequência fundamental (F0) do vocal isolado
e converter para o formato de pitch do UltraStar (semitons relativos a C4=0).

API REAL do swift-f0 0.2.x (atualizada em 20/09/2026 - a 0.2.0 QUEBROU a API
da 0.1.x em três pontos de uma vez; ver nota de migração no fim deste bloco):

    from swift_f0 import SwiftF0

    detector = SwiftF0()                                   # sem parâmetros de análise
    result = detector.detect(audio_array, sample_rate,     # ou detect_file(path)
                             fmin=46.875, fmax=2093.75)

    # PitchResult é um conjunto de arrays paralelos, um valor por frame:
    #   result.pitch_hz    -> F0 estimado (Hz) por frame
    #   result.confidence  -> confiança do modelo (0-1) por frame
    #   result.timestamps  -> centro de cada frame em segundos
    #   result.audio       -> o áudio já reamostrado para 16 kHz

Não existe parâmetro `model_size` (isso era uma suposição incorreta de quem
escreveu a primeira versão deste arquivo). O detector sempre roda o mesmo
modelo; o que se ajusta é o threshold de confiança e a faixa de frequência.

MIGRAÇÃO 0.1.x -> 0.2.0 (relatado pelo usuário: "SwiftF0.__init__() got an
unexpected keyword argument 'confidence_threshold'", depois de um update das
bibliotecas). Três mudanças, não uma - a mensagem de erro só mostra a
primeira:
  1. o construtor não aceita mais confidence_threshold/fmin/fmax;
  2. `detect_from_array` virou `detect`, e é ela que recebe fmin/fmax;
  3. `result.voicing` DEIXOU DE EXISTIR - quem decide o que é vozeado agora
     somos nós, comparando `confidence` com o nosso threshold.

Conferido antes de migrar, com as duas versões instaladas lado a lado e o
mesmo áudio: num sinal parecido com voz (série harmônica com vibrato), a
0.2.0 concorda com a 0.1.2 em 124 dos 125 quadros no threshold de 0.85, com
diferença mediana de 1,3 Hz no F0. (Num seno PURO as duas divergem muito - a
0.2.0 tem bem menos confiança num tom artificial.)

CORREÇÃO (29/09/2026): em CANTO REAL a escala de confiança da 0.2.0 é bem
mais baixa que a da 0.1.2 - o sinal sintético acima não mostrava isso, e
manter 0.85 fazia ~60% das notas saírem freestyle ("F", não pontua). Medido
nos stems de vocal do Demucs de 4 músicas (pop masculino, pop feminino, rock,
MPB), as duas versões lado a lado no MESMO áudio:

    música          quadros   mediana conf 0.1.2 / 0.2.0   F0 igual (mediana)
    Rick Astley       13315        0.87 / 0.60               9,7 cents
    (as outras três com o mesmo padrão; F0 difere < 11 cents em todas)

    Quadros vozeados da 0.1.2@0.85 que a 0.2.0 recupera (recall), e F1:
    threshold 0.2.0    0.40   0.50   0.55   0.60   0.70   0.85
    F1 médio (4)       0.82   0.82   0.82   0.81   0.78   0.68
    recall (pior)      0.90   0.82   0.78   0.72   0.57   0.32

O F1 fica num platô entre ~0.40 e ~0.55 e cai depois; 0.55 é o ponto do platô
com mais concordância de F0 com a 0.1.2. Em Rick Astley (alinhamento fixo,
só o threshold mudando): notas freestyle 59,8% -> 21,2%, tempo cantado que
pontua 62 s -> 108 s, sem perder concordância de pitch com um detector
independente (UltraSinger/swift-f0 0.1.2: 65% -> 63% mesma classe de nota).
Só o threshold mudou de escala: o F0 é praticamente o mesmo.

OBS: a 0.2.0 também passou a devolver `timestamps` no INÍCIO do quadro (a
0.1.2 devolvia o centro) - 8 ms de diferença, irrelevante para o UltraStar.

NOTA para canto: fmin/fmax padrão (46.875-2093.75 Hz, G1 a C7) já cobre bem
a faixa vocal humana em canto. Se detectar oitava errada com frequência,
considere restringir a faixa pra tessitura conhecida do cantor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

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


def _read_window(audio_path: str, start_s: float, end_s: float) -> tuple[np.ndarray, int]:
    """
    Lê do disco SÓ o trecho [start_s, end_s) do arquivo, em vez do arquivo
    inteiro. Os mesmos índices de amostra que o fatiamento antigo
    (`y[int(start_s*sr):int(end_s*sr)]`) usava, então o trecho sai idêntico.

    Por quê: extract_word_track roda UMA VEZ POR PALAVRA (150-400 por música),
    e antes cada chamada relia o stem de vocal inteiro (~40 MB num WAV de 4
    min) só para usar meio segundo dele. MEDIDO (24/09/2026): 300 leituras do
    arquivo inteiro = 29 s; 300 leituras só do trecho = 0,05 s. Era tempo
    perdido em toda geração, sem mudar nada no resultado.
    """
    import soundfile as sf

    with sf.SoundFile(audio_path) as f:
        sr = f.samplerate
        start_sample = max(0, int(start_s * sr))
        end_sample = min(f.frames, int(end_s * sr))
        if end_sample <= start_sample:
            return np.zeros((0,) if f.channels == 1 else (0, f.channels)), sr
        f.seek(start_sample)
        return f.read(end_sample - start_sample), sr


class PitchExtractor:
    def __init__(
        self,
        confidence_threshold: float = 0.55,
        # Calibrado para a escala da swift-f0 0.2.x (ver CORREÇÃO no topo do
        # arquivo): reproduz o que 0.85 fazia na 0.1.x. Não voltar para 0.85 -
        # na 0.2 isso descarta a maior parte dos quadros bons de canto. Fica
        # acima do corte de 0.5 do build_song.py (confiança média -> ":"/"F"),
        # então uma nota só vira "F" quando não tem NENHUM quadro vozeado.
        fmin: float = 46.875,
        fmax: float = 2093.75,
    ):
        from swift_f0 import SwiftF0

        # Desde a 0.2.0 o detector não recebe nada na construção: a faixa de
        # frequência vai em cada chamada de detect(), e o threshold é nosso.
        self.model = SwiftF0()
        self.confidence_threshold = confidence_threshold
        self.fmin = fmin
        self.fmax = fmax

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
        segment, sr = _read_window(audio_path, start_s, end_s)

        if segment.size == 0:
            empty = np.array([])
            return PitchTrack(timestamps=empty, pitch_hz=empty, confidence=empty, voicing=np.array([], dtype=bool))

        if hasattr(self.model, "detect"):
            result = self.model.detect(segment, sr, fmin=self.fmin, fmax=self.fmax)
        else:
            self.model.fmin = self.fmin
            self.model.fmax = self.fmax
            result = self.model.detect_from_array(segment, sr)
        confidence = np.asarray(result.confidence)
        return PitchTrack(
            timestamps=np.asarray(result.timestamps) + start_s,  # absoluto
            pitch_hz=np.asarray(result.pitch_hz),
            confidence=confidence,
            # A 0.2.0 não devolve mais `voicing`: o corte é nosso, e é o mesmo
            # que a 0.1.x fazia internamente com o threshold que passávamos.
            voicing=confidence >= self.confidence_threshold,
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

        in_window = (track.timestamps >= start_s) & (track.timestamps <= end_s)
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

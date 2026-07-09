"""
beatgrid.py
Etapa 3 da pipeline: detectar BPM e construir o grid de beats que será usado
para converter timestamps (segundos) em "beats" no formato UltraStar.

IMPORTANTE: a detecção automática de BPM erra com frequência (meio/dobro do
tempo real, sincopa, mudanças de andamento). Trate o valor daqui como um
"palpite inicial" - o main.py permite sobrescrever via --bpm manual.

BUG CRÍTICO CORRIGIDO (05/07/2026, 3ª rodada de testes - problema de
sincronia relatado pelo usuário: a letra "andava" 4x mais rápido que a
música real, mostrando palavras do fim da música pouco depois do começo):

A fórmula OFICIAL do formato UltraStar (confirmada em múltiplas fontes,
incluindo ultrastar.de e a issue #39 do repositório UltraStar-Deluxe/Play)
é:

    tempo_real_segundos = beat * 60 / (BPM_do_arquivo * 4) + GAP/1000

Ou seja, o PRÓPRIO MOTOR DO JOGO já multiplica o #BPM do arquivo por 4
internamente para obter a resolução fina de "beat". O #BPM gravado no
.txt deve ser o BPM REAL/BRUTO da música (ex.: 123.05), NÃO pré-multiplicado
por nós.

A versão anterior deste código multiplicava o BPM por 4 (`ultrastar_bpm`)
E gravava esse valor já multiplicado na tag #BPM do .txt - fazendo o motor
do jogo aplicar a multiplicação por 4 UMA SEGUNDA VEZ em cima disso,
resultando em o jogo tocar a música ~4x mais rápido internamente do que o
áudio real - por isso palavras do fim da música apareciam segundos depois
do início.

CORREÇÃO: `bpm` agora é sempre o valor BRUTO (o que vai direto pro #BPM do
.txt). A multiplicação por 4 acontece SOMENTE dentro de seconds_to_beat(),
como parte da fórmula oficial de conversão segundo<->beat - nunca é gravada
como um valor "pré-multiplicado" separado.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import librosa


@dataclass
class BeatGrid:
    bpm: float  # BPM BRUTO/real da música - é isto (e só isto) que vai para #BPM no .txt

    def seconds_to_beat(self, seconds: float, gap_ms: float) -> int:
        """
        Converte um timestamp em segundos para "beat" UltraStar, já
        descontando o #GAP (offset em milissegundos antes do beat 0).

        Fórmula oficial (invertida): beat = (seconds - gap_s) * bpm * 4 / 60
        O fator "* 4" é fixo, exigido pelo próprio motor do jogo - não é
        uma escolha nossa, e não deve ser aplicado de novo em nenhum outro
        lugar (como gravar bpm*4 na tag #BPM - isso duplicaria o fator).
        """
        gap_s = gap_ms / 1000.0
        adjusted_seconds = max(0.0, seconds - gap_s)
        beats_per_second = (self.bpm * 4) / 60.0
        return round(adjusted_seconds * beats_per_second)


def detect_bpm(vocal_or_full_wav: Path, manual_bpm: float | None = None) -> BeatGrid:
    if manual_bpm:
        bpm = manual_bpm
    else:
        y, sr = librosa.load(str(vocal_or_full_wav), sr=None)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        # A partir do librosa 0.10/0.11, beat_track pode retornar o tempo
        # como um array numpy (ex.: array([123.05])) em vez de um float puro.
        # np.asarray(...).item() lida com os dois casos (array ou escalar).
        bpm = float(np.asarray(tempo).item())

    return BeatGrid(bpm=bpm)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Etapa 3: detecção de BPM (Fase 0 - teste isolado)")
    parser.add_argument("--input", required=True, help="Arquivo de áudio (idealmente o instrumental)")
    parser.add_argument("--bpm", type=float, default=None, help="Forçar um BPM manual (recomendado revisar sempre)")
    args = parser.parse_args()

    grid = detect_bpm(Path(args.input), args.bpm)
    print(f"[OK] BPM detectado: {grid.bpm:.2f}  (este é o valor exato que vai para #BPM no .txt)")
    print("Lembrete: confira este valor ouvindo a música com um metrônomo antes de confiar cegamente.")

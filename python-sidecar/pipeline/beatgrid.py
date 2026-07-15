"""
beatgrid.py
Etapa 3 da pipeline: detectar BPM e construir o grid de beats que será usado
para converter timestamps (segundos) em "beats" no formato UltraStar.

IMPORTANTE: a detecção automática de BPM erra com frequência (meio/dobro do
tempo real, sincopa, mudanças de andamento). Trate o valor daqui como um
"palpite inicial" - o main.py permite sobrescrever via --bpm manual.

CORREÇÃO DE OITAVA (12/07/2026): o erro mais comum do librosa é retornar
exatamente metade ou o dobro do tempo real (o "octave error" clássico de MIR).
fold_bpm_to_octave() dobra/reduz por 2 até o BPM cair na oitava alvo
[90, 180), alinhada ao prior start_bpm=120 do beat_track. A sincronia das
notas NÃO depende disso (o offset vem do alinhamento forçado, não da grade),
mas o valor gravado em #BPM fica mais fiel e a granularidade da grade fica
consistente entre músicas. Só age quando o valor está fora da faixa; um BPM
manual (--bpm) é sempre respeitado como veio.

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


# Faixa "alvo" (uma oitava completa) para corrigir o erro de meio/dobro do
# librosa. beat_track usa start_bpm=120 como prior, então sua saída já se
# agrupa em torno de 120; usar [90, 180) mantém intactos os valores que já
# caem nessa oitava e só corrige os casos claramente divididos (< 90) ou
# duplicados (>= 180). A largura é exatamente uma oitava (90*2 == 180), então
# o dobramento é determinístico: todo BPM mapeia para um único valor na faixa.
_OCTAVE_MIN_BPM = 90.0
_OCTAVE_MAX_BPM = 180.0


def fold_bpm_to_octave(
    bpm: float,
    min_bpm: float = _OCTAVE_MIN_BPM,
    max_bpm: float = _OCTAVE_MAX_BPM,
) -> float:
    """
    Corrige o erro de oitava (meio/dobro) da detecção automática de BPM,
    dobrando/reduzindo por 2 até o valor cair na faixa [min_bpm, max_bpm).

    O erro mais comum do detector é retornar exatamente metade ou o dobro do
    tempo real (o "octave error" clássico de MIR). Como o offset temporal de
    cada nota vem do alinhamento forçado (WhisperX), e não da grade de beats,
    a sincronia não muda com a oitava - mas o valor gravado em #BPM fica mais
    fiel ao andamento real e a granularidade da grade fica consistente entre
    músicas.

    Só age quando o valor está fora da oitava alvo; um BPM já plausível
    (ex.: 128) passa intacto. Retorna o valor possivelmente ajustado.
    """
    if bpm <= 0:
        return bpm
    corrected = bpm
    # Guarda de segurança contra loop infinito caso min/max sejam inválidos.
    for _ in range(16):
        if corrected < min_bpm:
            corrected *= 2.0
        elif corrected >= max_bpm:
            corrected /= 2.0
        else:
            break
    return corrected


def detect_bpm(vocal_or_full_wav: Path, manual_bpm: float | None = None) -> BeatGrid:
    if manual_bpm:
        # BPM informado manualmente é respeitado como está - o usuário sabe o
        # andamento real e pode querer justamente uma oitava específica.
        return BeatGrid(bpm=manual_bpm)

    y, sr = librosa.load(str(vocal_or_full_wav), sr=None)
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    # A partir do librosa 0.10/0.11, beat_track pode retornar o tempo
    # como um array numpy (ex.: array([123.05])) em vez de um float puro.
    # np.asarray(...).item() lida com os dois casos (array ou escalar).
    raw_bpm = float(np.asarray(tempo).item())
    bpm = fold_bpm_to_octave(raw_bpm)
    if abs(bpm - raw_bpm) > 0.01:
        print(
            f"[BPM] Correcao de oitava: {raw_bpm:.2f} -> {bpm:.2f} "
            f"(faixa alvo {_OCTAVE_MIN_BPM:.0f}-{_OCTAVE_MAX_BPM:.0f})"
        )

    return BeatGrid(bpm=bpm)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Etapa 3: detecção de BPM (Fase 0 - teste isolado)")
    parser.add_argument("--input", required=True, help="Arquivo de áudio (idealmente o instrumental)")
    parser.add_argument("--bpm", type=float, default=None, help="Forçar um BPM manual (recomendado revisar sempre)")
    args = parser.parse_args()

    grid = detect_bpm(Path(args.input), args.bpm)
    print(f"[OK] BPM detectado: {grid.bpm:.2f}  (este é o valor exato que vai para #BPM no .txt)")
    print("Lembrete: confira este valor ouvindo a música com um metrônomo antes de confiar cegamente.")

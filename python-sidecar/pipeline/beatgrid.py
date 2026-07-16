"""
beatgrid.py
Etapa 3 da pipeline: detectar BPM e construir o grid de beats que será usado
para converter timestamps (segundos) em "beats" no formato UltraStar.

IMPORTANTE: a detecção automática de BPM erra com frequência (meio/dobro do
tempo real, sincopa, mudanças de andamento). Trate o valor daqui como um
"palpite inicial" - o main.py permite sobrescrever via --bpm manual.

OITAVA / RESOLUÇÃO DA GRADE (faixa alvo revisada em 16/07/2026): o
fold_bpm_to_octave() dobra/reduz o BPM por 2 até cair em [200, 400). Isso
corrige o erro de meio/dobro do librosa E, o que importa mais, põe o #BPM na
faixa dos charts feitos à mão.

O #BPM do UltraStar não é o andamento musical: é a UNIDADE DA GRADE (o motor
usa `tempo = beat*60/(BPM*4)`, então o beat dura `60/(BPM*4)`). Como o
seconds_to_beat ARREDONDA, uma grade grossa vira erro de sincronia em toda
nota - medido: a faixa antiga [90,180) injetava ~35 ms de erro médio (65% das
notas acima de 25 ms), contra ~17 ms na faixa nova. Ver a tabela completa no
docstring de fold_bpm_to_octave.

O BPM manual (--bpm) é LITERAL - vai pro #BPM exatamente como veio, mesmo
fora da faixa. O campo é a saída de emergência pra quando a automação erra;
uma saída de emergência que "corrige" o que o usuário digitou não serve pra
nada. Quando o valor fica fora da faixa, o log só AVISA que a grade fica mais
grossa - sem mexer no número.

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


# Faixa "alvo" (uma oitava completa) do #BPM gravado. NÃO é o andamento
# musical - é a unidade da grade de beats, e a faixa alta é o que dá a
# resolução fina dos charts feitos à mão. Ver o docstring de
# fold_bpm_to_octave, que traz a medição.
_OCTAVE_MIN_BPM = 200.0
_OCTAVE_MAX_BPM = 400.0


def fold_bpm_to_octave(
    bpm: float,
    min_bpm: float = _OCTAVE_MIN_BPM,
    max_bpm: float = _OCTAVE_MAX_BPM,
) -> float:
    """
    Dobra/reduz o BPM por 2 até cair na faixa [min_bpm, max_bpm).

    Faz DUAS coisas ao mesmo tempo:

    1. Corrige o erro de oitava (meio/dobro) da detecção - o "octave error"
       clássico de MIR, modo de falha mais comum do librosa.beat.beat_track.
    2. Põe o #BPM na faixa que os charts feitos à mão usam, o que MELHORA A
       SINCRONIA. Isto é contraintuitivo e merece explicação.

    O #BPM do UltraStar não é o andamento musical: é a UNIDADE DA GRADE. O
    motor converte por `tempo = beat*60/(BPM*4)`, então o beat (a menor
    posição representável) dura `60/(BPM*4)`. Gravar o andamento "real" da
    música dá uma grade GROSSA, e como seconds_to_beat ARREDONDA, isso vira
    erro de sincronia em toda nota.

    MEDIDO ("20 e poucos anos", 362 tempos reais do alinhamento):

        #BPM     1 beat    erro médio   erro máx   notas com erro > 25 ms
        110       136 ms     35,1 ms     68,0 ms          65%     <- a faixa antiga
        220        68 ms     16,7 ms     34,0 ms          27%
        440        34 ms      8,3 ms     17,0 ms           0%

    Ou seja: a faixa antiga [90,180) injetava ~35 ms de erro em CADA nota, de
    graça - da mesma ordem do erro do próprio alinhador. (A versão anterior
    deste docstring afirmava que "a sincronia não muda com a oitava". Estava
    errado: não muda o *alinhamento*, mas muda o arredondamento pra grade, que
    é o que o jogador ouve.)

    POR QUE [200,400): é a faixa que a comunidade usa de verdade. O usdb_syncer
    (que baixa/nomeia os milhares de charts do USDB) tem BPM_THRESHOLD=200 e
    dobra o BPM até passar disso; a issue #166 deles só quer reduzir acima de
    500. E o nosso próprio eval/seed_set.json descreve os charts gold como
    "BPM range 184-417 (fine-grid hand charts)" - os dados já diziam isso.

    A largura é exatamente uma oitava (200*2 == 400), então o dobramento é
    determinístico: todo BPM mapeia para um único valor na faixa.

    Só age quando o valor está fora da faixa. Retorna o valor ajustado.
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
        # O BPM manual é LITERAL: vai pro #BPM exatamente como o usuário
        # digitou. Se ele pediu 110, é 110 - o campo é a saída de emergência
        # pra quando a automação erra, e uma saída de emergência que "corrige"
        # o que o usuário escreveu não é saída de emergência nenhuma.
        #
        # A automação dobra pra [200,400) porque o #BPM é a unidade da grade
        # (ver fold_bpm_to_octave); quem digita um valor fora dessa faixa fica
        # com uma grade mais grossa, e isso é escolha dele. Só avisamos, pra
        # não ser surpresa silenciosa - sem mexer no valor.
        if not (_OCTAVE_MIN_BPM <= manual_bpm < _OCTAVE_MAX_BPM):
            beat_ms = 60000.0 / (manual_bpm * 4) if manual_bpm > 0 else 0.0
            print(
                f"[BPM] Manual {manual_bpm:.2f} usado como veio. Nota: fora da "
                f"faixa {_OCTAVE_MIN_BPM:.0f}-{_OCTAVE_MAX_BPM:.0f} a grade fica "
                f"mais grossa (1 beat = {beat_ms:.0f} ms), o que arredonda mais "
                f"as notas. Um múltiplo por 2 do mesmo andamento dá a mesma "
                f"música com notas mais precisas."
            )
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

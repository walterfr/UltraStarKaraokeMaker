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

from .i18n import t


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

    def beat_to_seconds(self, beat: int | float, gap_ms: float) -> float:
        """
        Converte um 'beat' UltraStar de volta para timestamp em segundos,
        reincorporando o #GAP. Fórmula oficial:
        tempo_real_segundos = beat * 60 / (BPM * 4) + GAP/1000
        """
        gap_s = gap_ms / 1000.0
        return (beat * 60.0) / (self.bpm * 4.0) + gap_s


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
            print(t("beatgrid.manual_out_of_range", bpm=manual_bpm, lo=_OCTAVE_MIN_BPM,
                    hi=_OCTAVE_MAX_BPM, beat_ms=beat_ms))
        return BeatGrid(bpm=manual_bpm)

    import librosa

    y, sr = librosa.load(str(vocal_or_full_wav), sr=None)
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    # A partir do librosa 0.10/0.11, beat_track pode retornar o tempo
    # como um array numpy (ex.: array([123.05])) em vez de um float puro.
    # np.asarray(...).item() lida com os dois casos (array ou escalar).
    raw_bpm = float(np.asarray(tempo).item())
    bpm = fold_bpm_to_octave(raw_bpm)
    if abs(bpm - raw_bpm) > 0.01:
        print(t("beatgrid.octave_fix", raw=raw_bpm, bpm=bpm, lo=_OCTAVE_MIN_BPM,
                hi=_OCTAVE_MAX_BPM))

    return BeatGrid(bpm=bpm)


NOTE_NAMES: tuple[str, ...] = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
MAJOR_SCALE_SEMITONES: tuple[int, ...] = (0, 2, 4, 5, 7, 9, 11)
MINOR_SCALE_SEMITONES: tuple[int, ...] = (0, 2, 3, 5, 7, 8, 10)

# Perfis tonais de Krumhansl-Kessler (maiores e menores) - discriminam melhor a
# tônica de uma escala do que uma máscara binária [1,0,1,...] (que confunde tons
# relativos como C major e A minor, pois têm exatamente as mesmas 7 notas).
_KRUMHANSL_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_KRUMHANSL_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def detect_key_from_chroma(chroma_avg: np.ndarray, transpose: int = 0) -> str | None:
    """
    Estima o tom musical ('C major', 'A minor', ...) a partir de um vetor médio
    de 12 classes de altura (C..B), correlacionando contra os 24 perfis de
    Krumhansl-Kessler. Se `transpose` != 0, aplica o deslocamento de semitons
    na tônica resultante.
    """
    vec = np.asarray(chroma_avg, dtype=float).reshape(-1)
    if vec.size != 12 or not np.all(np.isfinite(vec)) or float(np.std(vec)) < 1e-9:
        return None

    best_corr = -2.0
    best_root = 0
    best_mode = "major"

    for shift in range(12):
        maj_prof = np.roll(_KRUMHANSL_MAJOR, shift)
        min_prof = np.roll(_KRUMHANSL_MINOR, shift)
        maj_c = float(np.corrcoef(vec, maj_prof)[0, 1])
        min_c = float(np.corrcoef(vec, min_prof)[0, 1])
        if maj_c > best_corr:
            best_corr = maj_c
            best_root = shift
            best_mode = "major"
        if min_c > best_corr:
            best_corr = min_c
            best_root = shift
            best_mode = "minor"

    final_root = (best_root + int(transpose)) % 12
    return f"{NOTE_NAMES[final_root]} {best_mode}"


def detect_musical_key(
    audio_path: Path | str,
    transpose: int = 0,
    duration_s: float = 90.0,
) -> str | None:
    """
    Detecta o tom musical de um arquivo de áudio (idealmente o mix ou
    instrumental) analisando até os primeiros `duration_s` segundos.
    Falhas retornam None sem interromper o pipeline.
    """
    try:
        import librosa

        y, sr = librosa.load(str(audio_path), sr=22050, mono=True, duration=duration_s)
        if y.size == 0:
            return None
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        if chroma.size == 0:
            return None
        chroma_avg = np.mean(chroma, axis=1)
        return detect_key_from_chroma(chroma_avg, transpose=transpose)
    except Exception:
        return None


def parse_key_string(key_str: str | None) -> tuple[int, str] | None:
    """
    Extrai (root_idx, mode) de strings como 'C major', 'F# minor' ou
    'key: A minor'. Retorna None se não reconhecer.
    """
    if not key_str:
        return None
    raw = key_str.strip()
    if raw.lower().startswith("key:"):
        raw = raw[4:].strip()
    parts = raw.split()
    if len(parts) < 2:
        return None
    note_part = parts[0].upper()
    mode_part = parts[1].lower()
    if note_part not in NOTE_NAMES or mode_part not in ("major", "minor"):
        return None
    return NOTE_NAMES.index(note_part), mode_part


def quantize_pitch_to_key(
    pitch: int,
    key_str: str,
    neighbor_pitch: int | None = None,
) -> int:
    """
    Ajusta um pitch UltraStar (relativo a C4=0) para o grau válido mais próximo
    da escala dada por `key_str` ('C major', 'A minor', ...). Em qualquer
    escala diatônica maior ou menor natural, toda nota fora da escala está a
    exatamente 1 semitom de distância de dois graus válidos (pitch - 1 e
    pitch + 1); desempata pelo mais próximo de `neighbor_pitch` (ou pelo lado
    da tônica).
    """
    parsed = parse_key_string(key_str)
    if parsed is None:
        return pitch
    root_idx, mode = parsed
    scale = MAJOR_SCALE_SEMITONES if mode == "major" else MINOR_SCALE_SEMITONES
    allowed_pcs = {(root_idx + iv) % 12 for iv in scale}

    pc = pitch % 12
    if pc in allowed_pcs:
        return pitch

    candidates = [c for c in (pitch - 1, pitch + 1) if (c % 12) in allowed_pcs]
    if not candidates:
        return pitch
    if len(candidates) == 1 or neighbor_pitch is None:
        return candidates[0]
    return min(candidates, key=lambda c: abs(c - neighbor_pitch))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Etapa 3: detecção de BPM (Fase 0 - teste isolado)")
    parser.add_argument("--input", required=True, help="Arquivo de áudio (idealmente o instrumental)")
    parser.add_argument("--bpm", type=float, default=None, help="Forçar um BPM manual (recomendado revisar sempre)")
    args = parser.parse_args()

    grid = detect_bpm(Path(args.input), args.bpm)
    print(f"[OK] BPM detectado: {grid.bpm:.2f}  (este é o valor exato que vai para #BPM no .txt)")
    print("Lembrete: confira este valor ouvindo a música com um metrônomo antes de confiar cegamente.")

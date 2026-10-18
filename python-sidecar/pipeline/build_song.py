"""
build_song.py
Etapa 6: junta tudo (timings de palavras, sílabas, pitch, grid de beats)
e monta o objeto Song pronto para exportar via ultrastar_writer.

Fluxo:
    word_timings (align.py, já com is_line_end marcado por palavra)
        -> para cada palavra, quebra em sílabas (syllabify.py)
        -> extrai UM track de pitch quadro-a-quadro pra palavra inteira
           (pitch.py) e usa ele pra decidir os limites reais das sílabas
           por conteúdo VOZEADO (allocate_syllable_durations), não por
           divisão igual de tempo - e pra detectar sustentação/melisma
           dentro de cada sílaba (detect_melisma_notes), emitindo notas de
           continuação "~" quando o pitch varia numa sílaba longa
        -> converte tempo (segundos) -> beat (beatgrid.py)
        -> monta lista de Note (com espaçamento/convenção de continuação
           correta - ver nota abaixo)
        -> corrige overlaps residuais de arredondamento (fix_rounding_overlaps)
        -> marca phrase_breaks_after_index nas palavras de fim de linha
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from .align import SOURCE_CTC, SOURCE_CTC_LOW, WordTiming
from .beatgrid import BeatGrid
from .i18n import t
from .pitch import PitchExtractor, PitchTrack
from .syllabify import split_word_syllables
from .ultrastar_writer import Note, Song, detect_chorus_preview_medley


def fix_rounding_overlaps(notes: list[Note]) -> list[Note]:
    """
    Corrige overlaps de 1 (raramente mais) beat causados por arredondamento
    independente de cada sílaba na conversão segundos->beat (round() aplicado
    isoladamente em cada start/end, sem checar a vizinha).

    Descoberto em teste real ("Sangue Latino", 05/07/2026): ~20-23 overlaps
    em ~190 notas, todos de 1 beat.

    HISTÓRICO DE BUG (mesmo teste, 2ª rodada): a primeira versão desta
    função só encolhia o FINAL da nota anterior, e falhava silenciosamente
    sempre que essa nota já estava na duração mínima (1 beat) - não havia
    mais margem pra encolher, e o overlap persistia sem que a função
    acusasse erro. Correção: quando o encolhimento não é suficiente pra
    zerar o overlap, o restante ("residual") empurra o INÍCIO da próxima
    nota pra frente, garantindo que o overlap sempre seja eliminado por
    completo, não só "quando há margem para isso".

    HISTÓRICO DE BUG 2 (24/09/2026, revisão do projeto): o empurrão acima não
    tinha limite. Se UMA nota vinha com o tempo errado lá do alinhamento (ex.:
    400 beats atrasada, na frente de notas que na verdade vêm antes dela), o
    empurrão arrastava TODAS as notas seguintes pra depois dela e esmagava
    cada uma pra 1 beat - e depois disso o validador de overlaps não achava
    mais nada pra avisar. Um erro local virava um trecho inteiro estragado,
    e em silêncio. MEDIDO rodando o código real: 1 tempo errado arrastou 4 de
    7 notas.

    Correção: o arredondamento NUNCA inverte a ordem (round() é monotônico e
    as palavras chegam em ordem), então só o arredondamento produz notas que
    começam no mesmo beat ou se sobrepõem - nunca uma nota que começa ANTES
    da anterior. Quando os inícios ORIGINAIS estão invertidos, isso é um
    tempo errado vindo de antes, não arredondamento: o par fica intocado,
    um aviso vai pro log, e o validador da tela de revisão aponta o problema
    na hora de salvar. Os casos de arredondamento continuam exatamente como
    antes (inclusive o empurrão em cadeia de notas de 1 beat no mesmo lugar).
    """
    # Inícios ORIGINAIS, antes de qualquer empurrão desta função: é com eles
    # que se reconhece uma inversão de verdade (ver o docstring).
    original_starts = [n.start_beat for n in notes]
    out_of_order: list[int] = []

    for i in range(len(notes) - 1):
        if original_starts[i + 1] < original_starts[i]:
            # Inversão: não é arredondamento, é um tempo errado lá atrás.
            # Não mexe em nenhuma das duas notas - deixa pro validador.
            out_of_order.append(i)
            continue

        current_end = notes[i].start_beat + notes[i].duration_beats
        next_start = notes[i + 1].start_beat
        if next_start < current_end:
            overlap = current_end - next_start

            # encolhe a nota anterior o quanto der, sem passar do mínimo de 1 beat
            max_shrink = notes[i].duration_beats - 1
            shrink = min(overlap, max_shrink)
            notes[i].duration_beats -= shrink

            # o que sobrou do overlap (se a nota anterior não tinha mais
            # margem) empurra o início da próxima nota pra frente
            residual = overlap - shrink
            if residual > 0:
                notes[i + 1].start_beat += residual

    if out_of_order:
        pares = ", ".join(f"{i}/{i + 1}" for i in out_of_order)
        # Antes saíam as duas línguas juntas (o log era todo em português, mas
        # havia usuário lendo em inglês). Desde 29/09/2026 o log segue o
        # idioma da interface - ver pipeline/i18n.py - e sai uma linha só.
        print(t("build_song.out_of_order", n=len(out_of_order), pairs=pares))

    return notes


def allocate_syllable_durations(
    track: PitchTrack,
    num_syllables: int,
    word_start: float,
    word_end: float,
    search_fraction: float = 0.4,
) -> list[tuple[float, float]]:
    """
    Divide [word_start, word_end) em `num_syllables` trechos. Parte da
    divisão IGUAL por tempo (comportamento de antes) e ajusta cada
    fronteira INTERNA pro ponto de menor energia vocal mais perto dela,
    dentro de uma janela de busca (`search_fraction` da duração média de
    uma sílaba pra cada lado) - fronteira de sílaba real tende a cair numa
    transição de baixa energia (consoante/respiração), não no meio de uma
    vogal sustentada. É isso que deixa uma sílaba sustentada ("ra" em
    "vulneraaaable") ficar com a fronteira seguinte empurrada pra depois
    dela em vez de cortada ao meio pela divisão cega por tempo.

    IMPORTANTE: a fronteira só é ajustada DENTRO da janela de busca - isto
    é deliberadamente um refinamento local e limitado da divisão igual, não
    uma tentativa de redescobrir a sílaba certa de qualquer distância (isso
    exigiria alinhamento fonético de verdade, fora do escopo aqui).

    Sem quadros utilizáveis no intervalo (silêncio total/trecho
    instrumental), cai na divisão igual pura - comportamento de antes desta
    função existir.
    """
    if num_syllables <= 1:
        return [(word_start, word_end)]

    equal_dur = (word_end - word_start) / num_syllables
    naive_boundaries = [word_start + i * equal_dur for i in range(num_syllables + 1)]

    in_word = (track.timestamps >= word_start) & (track.timestamps < word_end)
    timestamps = track.timestamps[in_word]
    voicing = track.voicing[in_word]

    if timestamps.size == 0:
        return [(naive_boundaries[i], naive_boundaries[i + 1]) for i in range(num_syllables)]

    weights = np.where(voicing, 1.0, 0.0)  # aproximação binária de energia vocal por quadro
    search_window = equal_dur * search_fraction

    boundaries = [word_start]
    for i in range(1, num_syllables):
        target = naive_boundaries[i]
        lo = max(boundaries[-1], target - search_window)
        hi = min(word_end, target + search_window)
        in_search = (timestamps >= lo) & (timestamps < hi)

        if not np.any(in_search):
            cut = max(target, boundaries[-1])
        else:
            local_ts = timestamps[in_search]
            local_w = weights[in_search]
            # entre pontos empatados na menor energia, prefere o mais perto
            # do alvo original (ajuste mínimo necessário, não o mais cedo)
            min_w = local_w.min()
            candidates = local_ts[local_w == min_w]
            best_ts = float(candidates[np.argmin(np.abs(candidates - target))])
            cut = max(best_ts, boundaries[-1])
        boundaries.append(cut)
    boundaries.append(word_end)

    return [(boundaries[i], boundaries[i + 1]) for i in range(num_syllables)]


# CALIBRAÇÃO DO MELISMA (17/07/2026) - os defaults de detect_melisma_notes
# abaixo foram MEDIDOS contra 1444 charts feitos à mão do USDB, não escolhidos
# no olho.
#
# O problema: produzíamos "~" em 15,2% das notas (mediana); os humanos fazem
# 5,0%. Três vezes mais - e a issue #233 do UltraSinger mostra que excesso de
# "~" irrita o jogador de verdade.
#
# A causa principal era `pitch_tolerance_semitones=1.0`: partia a sílaba na
# DERIVA de pitch. Uma nota sustentada que escorrega ~3 semitons ao longo da
# sílaba (glissando/portamento - coisa que cantor faz o tempo todo) virava
# duas notas; com 2,0 de tolerância continua uma só. Verificado com deriva
# sintética: a 3 st o limiar antigo parte, o novo não.
#
# NÃO era vibrato, embora fosse a hipótese óbvia (e a primeira que testei):
# vibrato NUNCA parte a sílaba, em profundidade nenhuma, nem com tolerância
# 1,0 - as micro-divisões que ele cria são curtas demais e o min_extension_s
# já as fundia. Fica registrado pra ninguém "explicar" isso com vibrato de
# novo.
#
# Varredura nas mesmas 20 músicas (mediana da fração de "~"):
#     tol=1,0 sil=0,30 ext=0,15 -> 15,2%   (era isto)
#     tol=2,0 sil=0,30 ext=0,15 -> 10,1%
#     tol=3,0 sil=0,30 ext=0,15 ->  7,7%   (3 st = terça menor: perderia melisma real)
#     tol=1,0 sil=0,45 ext=0,15 -> 10,4%
#     tol=2,0 sil=0,45 ext=0,25 ->  6,5%   <- escolhido
#
# E a distribuição INTEIRA passou a bater, não só a mediana:
#                mediana   média    p90     máx
#     depois       6,5%    8,2%   16,6%   20,1%
#     à mão        5,0%    7,3%   17,7%   67,1%
# O p90 casar (16,6 vs 17,7) é o que mostra que a FORMA alinhou - acertar só a
# mediana seria sorte.
#
# Cada valor tem razão musical, não é curva ajustada:
#   - 2,0 st (um tom inteiro): acima do vibrato, abaixo de um salto real;
#   - 0,45 s: sílaba mais curta que isso não está "sustentada";
#   - 0,25 s: um "~" de 150 ms é curto demais pra se perceber como nota.
#
# Diferença que FICA e é esperada: 14% dos charts à mão não têm "~" nenhum
# (charter que não usa a convenção); nós sempre produzimos algum, porque
# medimos variação de pitch real. Não é erro - é o limite de medir vs. estilo.
#
# RECALIBRAÇÃO (01/10/2026): com as sílabas medidas pelo CTC (ver
# ctc_syllable_spans) e a divisão silábica por idioma, as primeiras sílabas
# de cada palavra ficaram mais longas e o "~" voltou a subir: 8,9% das notas
# (charts à mão desta biblioteca en/sv: 3,6%). Varredura dos três limiares em
# 24 músicas (16 de ajuste + 8 guardadas). Quem manda é a duração mínima da
# sílaba: 0,45 -> 0,80 s leva o "~" a 4,7% (guardadas: 11,3% -> 6,9%, charts
# 2,7%) sem custo real na precisão das notas (F1 0,873 -> 0,879; guardadas
# 0,829 -> 0,824). Tolerância e extensão mudaram pouco na varredura e ficam.
MELISMA_MIN_EXTENSION_S = 0.25
MELISMA_PITCH_TOLERANCE_ST = 2.0
MELISMA_MIN_SYLLABLE_S = 0.80


# FIM DA PALAVRA SEGUINDO A VOZ (30/09/2026) - o alinhamento CTC marca o fim da
# palavra no último quadro em que ele "vê" a letra, e numa vogal sustentada o
# modelo (treinado em fala) larga a letra antes da voz parar. MEDIDO contra
# charts feitos à mão (16 músicas, 3401 palavras bem colocadas): em média o fim
# do CTC está certo (+23 ms), mas nas palavras que o chart segura >= 1 s o fim
# sai 155 ms cedo na mediana, e metade delas > 150 ms cedo.
#
# A correção só ESTICA (nunca encurta): segue a voz (quadros vozeados do pitch
# track) depois do fim, tolerando falha curta, até SUSTAIN_MAX_EXTENSION_S e
# parando SUSTAIN_GAP_BEFORE_NEXT_S antes da próxima palavra - e só quando há
# pelo menos SUSTAIN_MIN_ROOM_S até ela (esticar tudo passava do ponto: palavra
# curta já termina um pouco TARDE, +43 ms). Ajustado numa amostra de 8 músicas
# e conferido noutra: erro mediano do fim 89 -> 84 ms e 86 -> 72 ms; palavras
# longas terminando > 150 ms cedo 46% -> 35% e 54% -> 36%.
SUSTAIN_MIN_ROOM_S = 0.15
SUSTAIN_GAP_BEFORE_NEXT_S = 0.10
SUSTAIN_MAX_EXTENSION_S = 0.40
SUSTAIN_MAX_HOLE_S = 0.04


def sustain_limit(word_end: float, next_start: float | None) -> float | None:
    """
    Até onde o fim da palavra pode ir seguindo a voz, ou None se não há espaço
    (a próxima palavra vem logo em seguida).
    """
    if next_start is not None and next_start - word_end < SUSTAIN_MIN_ROOM_S:
        return None
    limit = word_end + SUSTAIN_MAX_EXTENSION_S
    if next_start is not None:
        limit = min(limit, next_start - SUSTAIN_GAP_BEFORE_NEXT_S)
    return limit if limit > word_end else None


def extend_end_while_voiced(track: PitchTrack, word_end: float, limit: float) -> float:
    """
    Novo fim da palavra: o último quadro vozeado depois de `word_end` (antes de
    `limit`), atravessando falhas de voz de até SUSTAIN_MAX_HOLE_S. Nunca
    devolve menos que `word_end`.
    """
    ts = track.timestamps
    if ts.size < 2:
        return word_end
    dt = float(np.median(np.diff(ts)))
    order = np.argsort(ts)
    ts, voiced = ts[order], track.voicing[order]
    i = int(np.searchsorted(ts, word_end))
    new_end, hole = word_end, 0.0
    while i < ts.size and ts[i] < limit:
        if voiced[i]:
            new_end, hole = float(ts[i]) + dt, 0.0
        else:
            hole += dt
            if hole > SUSTAIN_MAX_HOLE_S:
                break
        i += 1
    return max(word_end, min(new_end, limit))


# Duração mínima de uma sílaba vinda do alinhamento por letra do CTC; abaixo
# disso a divisão medida é tratada como suspeita e cai na de energia/pitch.
# Teto para sílaba NÃO-final (1,2 s): sílaba inicial esticada por segundos
# indica que o CTC prendeu a 1ª letra na linha anterior ("wan" de 2,5 s, "miss"
# de 5,3 s).
CTC_SYLLABLE_MIN_S = 0.03
CTC_SYLLABLE_MAX_NONFINAL_S = 1.20


def ctc_syllable_spans(
    starts: list[float] | None,
    num_syllables: int,
    word_start: float,
    word_end: float,
) -> list[tuple[float, float]] | None:
    """
    Trechos das sílabas a partir dos inícios MEDIDOS pelo CTC (1ª letra de
    cada sílaba, WordTiming.syllable_starts). A 1ª sílaba começa no início da
    palavra e a última vai até o fim dela. None quando não dá pra confiar
    (contagem diferente, fora da palavra, sílaba curta demais ou sílaba
    não-final esticada demais) - aí vale a divisão por energia/pitch de
    allocate_syllable_durations.
    """
    if not starts or len(starts) != num_syllables or num_syllables < 2:
        return None
    bounds = [word_start] + list(starts[1:]) + [word_end]
    if any(b - a < CTC_SYLLABLE_MIN_S for a, b in zip(bounds, bounds[1:])):
        return None
    if any(b - a > CTC_SYLLABLE_MAX_NONFINAL_S for a, b in zip(bounds[:-2], bounds[1:-1])):
        return None
    return [(bounds[i], bounds[i + 1]) for i in range(num_syllables)]


def merge_flat_continuations(
    notes: list[Note],
    phrase_breaks: list[int],
    max_gap_beats: int,
) -> tuple[list[Note], list[int]]:
    """
    Funde um "~" na nota anterior quando os dois têm o MESMO pitch (e o mesmo
    tipo): uma continuação que não muda de nota não carrega melodia nenhuma, só
    aparece na tela como "you~~~". Devolve (notas, phrase_breaks remapeados -
    eles são índices de nota).

    De onde vêm (medido 30/09/2026, "a-ha - Take On Me": 14,6% de "~" contra
    4,0% no chart feito à mão): detect_melisma_notes parte a sílaba em toda
    LACUNA de voz e nunca funde o trecho que começa numa lacuna (proteção do
    caso "Ama De Mi Sol", ver lá). Em voz soprosa/falsete a leitura de pitch
    falha por poucos quadros no meio da sustentação, e cada falha vira mais um
    "~" - no mesmo pitch: "talking" [2, 2, 2], "me)" [-3, -3, -3, -3].

    Só funde com lacuna < `max_gap_beats` entre as notas; lacuna maior fica
    como está (pausa de verdade, ou a fronteira de palavra que aquela proteção
    existe pra marcar). Nunca funde por cima de uma quebra de frase.
    """
    breaks = set(phrase_breaks)
    out: list[Note] = []
    new_index: list[int] = []  # índice antigo -> índice novo
    for k, note in enumerate(notes):
        prev = out[-1] if out else None
        if (
            prev is not None
            and note.text.strip() == "~"
            and note.pitch == prev.pitch
            and note.note_type == prev.note_type
            and not prev.text.endswith(" ")
            and (k - 1) not in breaks
            and note.start_beat - (prev.start_beat + prev.duration_beats) < max_gap_beats
        ):
            prev.duration_beats = note.start_beat + note.duration_beats - prev.start_beat
            prev.text += note.text[len(note.text.rstrip()):]  # herda o espaço final
            new_index.append(len(out) - 1)
            continue
        out.append(note)
        new_index.append(len(out) - 1)
    return out, sorted({new_index[b] for b in phrase_breaks})


def detect_melisma_notes(
    track: PitchTrack,
    syl_start: float,
    syl_end: float,
    min_extension_s: float = MELISMA_MIN_EXTENSION_S,
    pitch_tolerance_semitones: float = MELISMA_PITCH_TOLERANCE_ST,
    min_syllable_duration_for_melisma: float = MELISMA_MIN_SYLLABLE_S,
    max_voiced_gap_frames: float = 2.5,
) -> list[tuple[float, float]]:
    """
    Decide se uma sílaba vira UMA nota ou uma nota + continuações "~"
    (melisma) - a convenção real do UltraStar pra sílabas sustentadas
    (confirmada em cartas feitas à mão: uma sílaba longa vira uma nota de
    ataque seguida de notas "~" acompanhando o pitch enquanto ele varia).
    Sílabas curtas demais pra plausivelmente sustentar devolvem o próprio
    intervalo inteiro (sem melisma - comportamento de hoje).

    BUG REAL CORRIGIDO (teste real, "Ama De Mi Sol", 13/07/2026): além do
    salto de pitch, uma LACUNA na voz (trecho sem quadro vozeado no meio da
    sílaba) também força um novo run, mesmo com pitch parecido dos dois
    lados. Sem isso, quando o limite de PALAVRA já está errado (ex.: "ver"
    "roubando" o tempo de "ser" por erro do alinhador), o melisma atravessa
    a lacuna vozeada da consoante surda "s" de "ser" e decora o trecho
    inteiro com "~" como se fosse uma sustentação legítima de "ver" -
    piorando visualmente um bug que já existia no timing por palavra. Uma
    lacuna de voz é sinal de possível fronteira de sílaba/palavra; "~"
    nunca deve atravessar uma.
    """
    if syl_end - syl_start < min_syllable_duration_for_melisma:
        return [(syl_start, syl_end)]

    in_syl = (track.timestamps >= syl_start) & (track.timestamps < syl_end) & track.voicing
    timestamps = track.timestamps[in_syl]
    pitch_hz = track.pitch_hz[in_syl]

    if timestamps.size < 2:
        return [(syl_start, syl_end)]

    # hop nominal do track inteiro (não só os quadros vozeados) - calibra o
    # que conta como "lacuna grande demais" sem depender de um valor fixo
    # de frame_ms do detector de pitch (que pode variar entre modelos).
    all_hops = np.diff(np.sort(track.timestamps))
    nominal_hop = float(np.median(all_hops)) if all_hops.size else 0.02
    max_voiced_gap_s = max_voiced_gap_frames * nominal_hop

    semitones = 12 * np.log2(pitch_hz / 440.0)

    # agrupa quadros vozeados consecutivos que ficam dentro da tolerância de
    # semitons da média do grupo corrente E sem lacuna de voz entre eles -
    # salto grande de pitch OU lacuna = nota/sílaba realmente diferente, não
    # apenas vibrato/deriva natural da sustentação.
    runs: list[list[int]] = [[0]]
    run_started_by_gap: list[bool] = [False]
    run_mean = float(semitones[0])
    for i in range(1, len(semitones)):
        pitch_ok = abs(semitones[i] - run_mean) <= pitch_tolerance_semitones
        gap_ok = (timestamps[i] - timestamps[i - 1]) <= max_voiced_gap_s
        if pitch_ok and gap_ok:
            runs[-1].append(i)
            run_mean = float(np.mean(semitones[runs[-1]]))
        else:
            runs.append([i])
            run_started_by_gap.append(not gap_ok)
            run_mean = float(semitones[i])

    spans = [(float(timestamps[r[0]]), float(timestamps[r[-1]])) for r in runs]

    # funde runs curtos demais (< min_extension_s) no vizinho anterior -
    # evita gerar um "~" de fração de segundo por ruído da leitura de pitch.
    # NUNCA funde um run que começou por causa de uma LACUNA de voz - isso
    # desfaria justamente a proteção de fronteira de palavra acima. Porém, um
    # blip isolado de 1 único quadro (end <= start, duração zero) após lacuna
    # é espúrio de silêncio/respiração (gerava notas "F ... 1 0 ~" fantasma) e
    # é descartado.
    merged = [spans[0]]
    for idx in range(1, len(spans)):
        start, end = spans[idx]
        if not run_started_by_gap[idx] and (end - start) < min_extension_s:
            merged[-1] = (merged[-1][0], end)
        elif run_started_by_gap[idx] and end <= start:
            continue
        else:
            merged.append((start, end))

    if len(merged) > 1 and merged[0][1] <= merged[0][0]:
        merged.pop(0)

    if len(merged) <= 1:
        return [(syl_start, syl_end)]

    # estica o 1º trecho pra trás até o início real da sílaba e o último
    # pra frente até o fim real (quadros vozeados não cobrem a sílaba
    # inteira - há ataque/consoante antes do 1º quadro vozeado)
    return [(syl_start, merged[0][1])] + merged[1:-1] + [(merged[-1][0], syl_end)]


# Fração das notas pontuáveis marcadas como "golden" ("*", bônus de pontuação
# ~2x). Calibrado nos charts feitos à mão da comunidade (medido em ABBA, Vicente
# Fernández, 50 Cent, Morat, Bad Bunny, 3 Doors Down, etc.): a golden cai
# tipicamente em ~2-6% das notas (mediana ~4-5%), concentrada nas notas mais
# LONGAS/sustentadas e em ganchos repetidos. Automatizamos o padrão DOMINANTE (as
# mais longas); ganchos repetidos exigiriam detecção de refrão (fora do escopo).
# É só camada de score: NÃO altera pitch nem tempo, então é aditivo e seguro.
GOLDEN_FRACTION_DEFAULT = 0.05
# Duração mínima para uma nota poder ser dourada, EM SEGUNDOS.
#
# Era "2 beats" fixo, o que só funcionava por acidente: 2 beats valiam ~273 ms
# na faixa de BPM antiga ([90,180)). Com a faixa nova ([200,400), grade ~2x
# mais fina - ver beatgrid.py) o mesmo "2" passaria a significar ~136 ms e
# dobraria notas curtas demais, mudando o critério sem ninguém pedir. Em
# tempo, o critério é o mesmo em qualquer BPM.
# Passo de arredondamento do #GAP, em milissegundos.
#
# Gravávamos o valor cru (ex.: "#GAP:1927"), o que sugere precisão de 1 ms que
# não existe: o GAP vem do início da 1ª palavra medida pelo alinhador, cujo
# erro típico é de dezenas de ms (medido na biblioteca gold: onset mediano de
# 88 ms). Milissegundo ali é ruído com cara de exatidão.
#
# 10 ms é a convenção da comunidade - o UltraSinger tem a mesma issue (#29,
# "Round #GAP to nearest 10 ms", fechada: "More accuracy is not needed IMHO").
# E é seguro: 10 ms está MUITO abaixo do limiar de percepção de dessincronia
# (~25 ms), então o arredondamento não é audível.
GAP_ROUND_MS = 10


def round_gap_ms(gap_ms: int) -> int:
    """
    Arredonda o #GAP para o múltiplo de GAP_ROUND_MS mais próximo.

    Usa `int(x + 0.5)` em vez de `round()` porque o round() do Python é
    BANCÁRIO (arredonda .5 para o par mais próximo): round(192.5) devolve 192,
    não 193. Aqui a diferença é de 5 ms - irrelevante pro áudio, mas o
    comportamento surpreende quem lê. É a mesma pegadinha que já mordeu o
    orçamento das notas douradas (`int(fraction*len + 0.5)`), então vale a
    consistência.
    """
    return int(gap_ms / GAP_ROUND_MS + 0.5) * GAP_ROUND_MS


GOLDEN_MIN_DURATION_S = 0.27


def golden_min_beats(grid: BeatGrid, min_seconds: float = GOLDEN_MIN_DURATION_S) -> int:
    """Converte a duração mínima da dourada (em segundos) para beats do grid."""
    return max(1, round(min_seconds * grid.bpm * 4 / 60.0))


def apply_golden_notes(
    notes: list[Note],
    golden_fraction: float = GOLDEN_FRACTION_DEFAULT,
    min_duration_beats: int = 2,
) -> list[Note]:
    """
    Marca como golden ("*") as notas MAIS LONGAS, até um orçamento proporcional
    ao total de notas pontuáveis, espalhando-as (nunca duas adjacentes na
    sequência). Reproduz o que os charters à mão fazem: a nota sustentada é o
    "momento de destaque". Muta a lista in-place e a devolve.

    - Só considera notas normais (":") - NUNCA doura freestyle ("F", que não
      pontua). Continuações de melisma ("~") PODEM ser golden (charts reais
      douram trechos sustentados, inclusive "~").
    - `min_duration_beats`: ignora notas curtas demais (dourar 1 beat não é
      "destaque" e não é o que os charts fazem). O default de 2 só serve pros
      testes puros; quem chama de verdade (build_notes) passa o valor derivado
      do grid via golden_min_beats(), porque "curta demais" é uma medida de
      TEMPO e beat só vira tempo quando se sabe o BPM.
    - Orçamento com arredondamento meio-pra-cima (evita o banker's rounding do
      round() zerar músicas curtas).
    """
    scoreable = [i for i, n in enumerate(notes) if n.note_type == ":"]
    if not scoreable:
        return notes
    budget = int(golden_fraction * len(scoreable) + 0.5)
    if budget <= 0:
        return notes

    candidates = [i for i in scoreable if notes[i].duration_beats >= min_duration_beats]
    # mais longas primeiro; empate -> índice menor (determinístico).
    candidates.sort(key=lambda i: (-notes[i].duration_beats, i))

    chosen: set[int] = set()
    for i in candidates:
        if len(chosen) >= budget:
            break
        # espalha: não marca duas notas vizinhas na sequência como golden.
        if (i - 1) in chosen or (i + 1) in chosen:
            continue
        chosen.add(i)

    for i in chosen:
        notes[i].note_type = "*"
    return notes


# Consistência de oitava. O SwiftF0 às vezes detecta a oitava errada em notas
# isoladas (medido: em "ABBA - Dancing Queen", separar a voz NÃO mexe no pitch —
# mediana 0 semitons — mas ~4,4% das notas têm saltos de oitava; o problema é do
# detector, não de contaminação de harmonia, então a correção é no pós-proc).
# tol: quão perto das DUAS vizinhas o valor dobrado precisa ficar (terça maior);
# min_improvement: quão melhor a dobra precisa ser pra valer.
OCTAVE_SNAP_TOL = 4
OCTAVE_SNAP_MIN_IMPROVEMENT = 6


def snap_octave_outliers(
    notes: list[Note],
    tol: int = OCTAVE_SNAP_TOL,
    min_improvement: int = OCTAVE_SNAP_MIN_IMPROVEMENT,
) -> list[Note]:
    """
    Corrige erros de OITAVA isolados: uma nota cujo pitch está ~1-2 oitavas longe
    das DUAS vizinhas imediatas é dobrada (±12/±24 semitons) de volta pra perto
    delas. Conserta a instabilidade de oitava do SwiftF0 sem estragar saltos
    melódicos legítimos.

    Só dobra quando o valor dobrado fica perto de AMBAS as vizinhas (a pior das
    duas distâncias <= `tol`) E isso melhora a pior distância em mais de
    `min_improvement` semitons. Isso protege três casos que uma mediana de janela
    erraria: (1) FRONTEIRA de região — a nota casa com uma vizinha, então dobrar
    pra outra não fica perto das duas; (2) nota BOA ao lado de um erro — dobrá-la
    "no meio" não a deixa perto das duas; (3) intervalo real até a sexta — melhora
    <= 6, não passa do limite. Extremos (sem as duas vizinhas) ficam como estão.
    Referência usa os pitches ORIGINAIS (snapshot): ordem não importa. In-place.
    """
    n = len(notes)
    if n < 3:
        return notes
    ref = [nt.pitch for nt in notes]  # snapshot antes de qualquer dobra
    for i in range(1, n - 1):
        left, right = ref[i - 1], ref[i + 1]
        p = notes[i].pitch
        best, best_dev = p, max(abs(p - left), abs(p - right))
        for k in (-2, -1, 1, 2):
            cand = p + 12 * k
            dev = max(abs(cand - left), abs(cand - right))
            if dev < best_dev:
                best, best_dev = cand, dev
        orig_dev = max(abs(p - left), abs(p - right))
        if best_dev <= tol and orig_dev - best_dev > min_improvement:
            notes[i].pitch = int(best)
    return notes


# SEGUNDA REDE DE OITAVA (29/09/2026). O snap_octave_outliers acima deixa
# escapar um tipo de erro que ficou mais comum depois que o threshold de
# confiança do SwiftF0 caiu de 0.85 pra 0.55 (ver pitch.py): mais quadros
# contam como vozeados, e uma sílaba de vez em quando sai com a oitava
# totalmente errada. Caso real (Rick Astley - Never Gonna Give You Up, notas
# todas entre -4 e 10): "Ne" saiu com pitch 36, TRÊS oitavas acima. Não custa
# ponto (o jogo pontua classe de nota, ignorando a oitava), mas na trilha de
# notas aparece lá em cima, sozinha, e o chart parece quebrado.
#
# Por que o snap não pegou - três motivos, todos vistos nesse caso:
#   1. só tenta ±1 e ±2 oitavas: 36-24 = 12 ainda fica longe das vizinhas;
#   2. as vizinhas IMEDIATAS eram freestyle ("F", pitch 0 de enfeite, porque
#      não tinham quadro vozeado nenhum) - o snap usa o pitch delas como se
#      fosse medido;
#   3. exige ficar perto das DUAS vizinhas (tol 4); quando elas mesmas estão
#      separadas por um intervalo maior que isso, nenhuma dobra passa.
#
# Esta função olha um CONTEXTO maior e só com notas que pontuam: a mediana de
# até OCTAVE_FOLD_WINDOW notas pontuáveis de cada lado (do mesmo cantor, pra
# não misturar voz masculina e feminina num dueto). Nota longe demais dessa
# mediana é dobrada de oitava em oitava até cair perto dela - MESMA classe de
# nota, então a pontuação não muda nada; só o desenho.
#
# Proteção de salto melódico REAL (a oitava pode ser de verdade dentro de uma
# frase), em dois degraus:
#   - desvio > OCTAVE_FOLD_MAX_DEV e <= OCTAVE_FOLD_ALWAYS_DEV: só dobra se a
#     nota estiver ISOLADA - nenhuma vizinha pontuável imediata a até
#     OCTAVE_FOLD_ISOLATION_TOL semitons dela. Um salto real vem com contexto
#     (a nota seguinte continua no agudo, ou é o "~" da mesma sílaba); um erro
#     do detector é uma nota sozinha;
#   - desvio > OCTAVE_FOLD_ALWAYS_DEV (mais de oitava e meia da mediana local):
#     dobra sempre. Voz cantando duas oitavas longe das 8 notas em volta não é
#     melodia, é o detector - e o erro às vezes vem em par (a sílaba e o "~"
#     dela), que a regra de isolamento sozinha deixaria passar.
#
# CALIBRAÇÃO (29/09/2026, threshold 0.55, alinhamento fixo, só esta função
# variando), em 4 músicas: Rick Astley, Adele - Rolling in the Deep, Nirvana -
# Smells Like Teen Spirit, Marisa Monte - Ainda Bem (1537 notas pontuáveis).
# Desvio de cada nota pra mediana das 8 vizinhas: a massa das notas fica em
# ±8 (salto real mais longe visto: 9, no "say goodbye" do Rick; em ~10 há
# casos ambíguos); fora disso aparecem ±12, ±24, ±36 - o padrão de erro de
# oitava. Daí os limiares:
#   - MAX_DEV 10: estritamente acima do maior salto real visto (9) e dos
#     ambíguos (10); com 9 a regra já dobrava duas notas duvidosas (Adele
#     "your" 10->-2, Nirvana "do" -5->7), então fica 10;
#   - ALWAYS_DEV 18: oitava e meia; o maior desvio de nota real visto é ~10;
#   - ISOLATION_TOL 4 (terça maior): mesma tolerância do snap acima;
#   - WINDOW 4: 8 notas ~ uma linha da letra, sem depender do "-" da frase
#     (há frases de 2-3 notas pontuáveis, curtas demais pra ter mediana).
#
#     música     notas >12 da mediana da música   notas mudadas
#     Rick            1 -> 0  ([36])                    1
#     Adele           5 -> 0  ([24,24,-12,24,24])       5
#     Nirvana         1 -> 0  ([36])                    3
#     Marisa Monte    2 -> 0  ([-15,34])                2
# As 11 notas mudadas mantêm a classe de nota; todas as outras ficam
# idênticas. O que SOBRA de propósito: pares de notas (a sílaba e a vizinha)
# uma oitava abaixo da frase, ex. Nirvana "we are" -11/-12 no meio de 1s -
# pode ser erro em par, mas também pode ser real, e a regra de isolamento
# prefere não mexer (desvio ~12-14, longe do absurdo de 36).
OCTAVE_FOLD_WINDOW = 4
OCTAVE_FOLD_MAX_DEV = 10
OCTAVE_FOLD_ALWAYS_DEV = 18
OCTAVE_FOLD_ISOLATION_TOL = 4


def fold_octave_outliers_to_context(
    notes: list[Note],
    window: int = OCTAVE_FOLD_WINDOW,
    max_dev: int = OCTAVE_FOLD_MAX_DEV,
    always_dev: int = OCTAVE_FOLD_ALWAYS_DEV,
    isolation_tol: int = OCTAVE_FOLD_ISOLATION_TOL,
) -> list[Note]:
    """
    Dobra por oitavas inteiras (±12k, mantendo a classe de nota) a nota
    pontuável cujo pitch está a mais de `max_dev` semitons da mediana das até
    `window` notas pontuáveis de cada lado (mesmo cantor). Ver o bloco de
    comentário acima pra regra completa e o porquê.

    - Freestyle ("F") nunca é referência nem é mexida: o pitch dela é um 0 de
      enfeite, não uma medida.
    - Precisa de pelo menos 2 vizinhas pontuáveis pra ter mediana confiável;
      com menos, não mexe.
    - Referência usa os pitches ORIGINAIS (snapshot): a ordem não importa e
      uma dobra não puxa a próxima. In-place, devolve a mesma lista.
    """
    ref = [nt.pitch for nt in notes]  # snapshot antes de qualquer dobra
    groups: dict[int, list[int]] = {}
    for i, nt in enumerate(notes):
        if nt.note_type != "F":
            groups.setdefault(nt.singer, []).append(i)

    for idx in groups.values():
        for pos, i in enumerate(idx):
            neigh = idx[max(0, pos - window):pos] + idx[pos + 1:pos + 1 + window]
            if len(neigh) < 2:
                continue
            med = float(np.median([ref[j] for j in neigh]))
            dev = ref[i] - med
            if abs(dev) <= max_dev:
                continue
            if abs(dev) <= always_dev:
                adjacent = idx[max(0, pos - 1):pos] + idx[pos + 1:pos + 2]
                if any(abs(ref[i] - ref[j]) <= isolation_tol for j in adjacent):
                    continue  # tem companhia no mesmo registro: salto real
            k = int(np.floor(dev / 12 + 0.5))  # oitavas até a mediana (meio pra cima)
            if k:
                notes[i].pitch = int(ref[i] - 12 * k)
    return notes


_SENTENCE_END_CHARS = (".", "?", "!", ",", ";", ":", ")", "]", '"', "”")


def _line_display_text(slice_notes: list[Note]) -> str:
    raw = "".join(n.text.replace("~", "") for n in slice_notes)
    return re.sub(r"\s+", " ", raw).strip()


def rescue_isolated_short_freestyle(
    notes: list[Note],
    phrase_breaks: list[int],
    max_beats: int = 3,
) -> list[Note]:
    """
    Sílabas curtas (<= `max_beats` beats, ex.: palavras funcionais "I", "my",
    "a", "to", "it", "up", "how") no meio de uma frase cantada às vezes saem
    sem quadro vozeado suficiente no SwiftF0 e viram "F" (pitch 0) isoladas.
    Quando há vizinha pontuável imediata na MESMA frase (mesmo cantor),
    herda o pitch dela e vira ":" - evita buracos de freestyle avulso na
    melodia sem tocar em trechos realmente falados/longos.
    """
    if len(notes) < 2:
        return notes
    breaks = set(phrase_breaks)
    orig_types = [n.note_type for n in notes]
    orig_pitches = [n.pitch for n in notes]
    for i, nt in enumerate(notes):
        if orig_types[i] != "F" or nt.duration_beats > max_beats:
            continue
        prev_idx = i - 1 if i > 0 and (i - 1) not in breaks else None
        next_idx = i + 1 if i + 1 < len(notes) and i not in breaks else None
        cands: list[tuple[int, int]] = []
        if prev_idx is not None and orig_types[prev_idx] != "F" and notes[prev_idx].singer == nt.singer:
            gap = max(0, nt.start_beat - (notes[prev_idx].start_beat + notes[prev_idx].duration_beats))
            cands.append((gap, orig_pitches[prev_idx]))
        if next_idx is not None and orig_types[next_idx] != "F" and notes[next_idx].singer == nt.singer:
            gap = max(0, notes[next_idx].start_beat - (nt.start_beat + nt.duration_beats))
            cands.append((gap, orig_pitches[next_idx]))
        if cands:
            cands.sort(key=lambda x: x[0])
            nt.pitch = int(cands[0][1])
            nt.note_type = ":"
    return notes


def merge_short_connected_lines(
    notes: list[Note],
    phrase_breaks: list[int],
    grid: BeatGrid,
    max_gap_s: float = 0.20,
    max_first_chars: int = 22,
    max_combined_chars: int = 42,
    max_combined_notes: int = 12,
) -> list[int]:
    """
    Junta quebras de linha no meio da frase ("Are you gonna / Live your life
    wonderin'", "Our house in the / Middle of the street") comuns em letras
    do LRCLIB/YouTube formatadas para tela vertical. Só remove a quebra
    quando a 1ª metade é curta (<= 22 chars), não termina em pontuação de
    pausa, a soma cabe confortavelmente numa linha do UltraStar (<= 42 chars
    e <= 12 notas) e o cantor emenda sem pausa respiratória (gap <= 0,20 s).
    """
    if not notes or not phrase_breaks or grid.bpm <= 0:
        return phrase_breaks
    sorted_breaks = sorted(b for b in set(phrase_breaks) if 0 <= b < len(notes))
    ranges: list[tuple[int, int]] = []
    start = 0
    for b in sorted_breaks:
        if b >= start:
            ranges.append((start, b))
            start = b + 1
    if start < len(notes):
        ranges.append((start, len(notes) - 1))
    if len(ranges) < 2:
        return phrase_breaks

    beat_s = 60.0 / (grid.bpm * 4.0)
    merged: list[tuple[int, int]] = [ranges[0]]
    for b0, b1 in ranges[1:]:
        a0, a1 = merged[-1]
        text_a = _line_display_text(notes[a0 : a1 + 1])
        text_b = _line_display_text(notes[b0 : b1 + 1])
        combined = f"{text_a} {text_b}".strip()
        gap_beats = notes[b0].start_beat - (notes[a1].start_beat + notes[a1].duration_beats)
        gap_s = gap_beats * beat_s
        if (
            text_a
            and text_b
            and notes[a1].singer == notes[b0].singer
            and not text_a.endswith(_SENTENCE_END_CHARS)
            and len(text_a) <= max_first_chars
            and len(combined) <= max_combined_chars
            and (b1 - a0 + 1) <= max_combined_notes
            and gap_s <= max_gap_s
            and text_a.lower() != text_b.lower()
        ):
            merged[-1] = (a0, b1)
        else:
            merged.append((b0, b1))

    had_trailing = (len(notes) - 1) in sorted_breaks
    out = [end_idx for _, end_idx in merged[:-1]]
    if had_trailing and merged:
        out.append(merged[-1][1])
    return out


def build_notes(
    word_timings: list[WordTiming],
    vocals_wav_path: Path,
    grid: BeatGrid,
    gap_ms: int,
    pitch_extractor: PitchExtractor,
    language: str | None = None,
) -> tuple[list[Note], list[int]]:
    """
    Retorna (notes, phrase_breaks_after_index).

    BUG ESTRUTURAL CORRIGIDO (05/07/2026, 2ª rodada de testes): esta função
    nunca preenchia phrase_breaks - o .txt saía sem NENHUM marcador "-" no
    arquivo inteiro, fazendo a música inteira virar uma "linha" só. Isso
    quebrava a rolagem de notas tanto no UltraStar Deluxe quanto no
    UltraStar Play (ambos desenham a letra por linha/frase curta). Agora
    usamos wt.is_line_end (propagado desde align.py) pra marcar o fim de
    cada nota que corresponde ao fim de uma linha da letra original.
    """
    notes: list[Note] = []
    phrase_breaks: list[int] = []

    for idx, wt in enumerate(word_timings):
        syllables = split_word_syllables(wt.word, language)
        # sílabas 100% pontuação (ex.: um "'" isolado por espaço na letra)
        # não têm conteúdo cantável e não devem virar nota própria.
        syllables = [s for s in syllables if any(c.isalnum() for c in s)]

        if syllables:
            word_start, word_end = wt.start, max(wt.start + 0.01, wt.end)
            # Palavra do CTC: o fim pode seguir a voz (ver SUSTAIN_*). A MESMA
            # leitura de pitch cobre o trecho extra - só a janela fica maior.
            limit = None
            if wt.source in (SOURCE_CTC, SOURCE_CTC_LOW):
                nxt = word_timings[idx + 1].start if idx + 1 < len(word_timings) else None
                limit = sustain_limit(word_end, nxt)
            track = pitch_extractor.extract_word_track(str(vocals_wav_path), word_start, limit or word_end)
            # Sílabas e melisma saem do trecho ORIGINAL da palavra; a cauda
            # sustentada só alonga a ÚLTIMA nota dela (ver o fim do laço). Se a
            # cauda entrasse no melisma, a queda de tom do fim da nota virava
            # mais "~": medido, 7,2% -> 9,3% de "~" nas mesmas 16 músicas.
            sustained_end = extend_end_while_voiced(track, word_end, limit) if limit is not None else word_end
            syllable_spans = (
                ctc_syllable_spans(wt.syllable_starts, len(syllables), word_start, word_end)
                or allocate_syllable_durations(track, len(syllables), word_start, word_end)
            )

            for i, (syl, (syl_start, syl_end)) in enumerate(zip(syllables, syllable_spans)):
                is_last_syllable_of_word = (i == len(syllables) - 1)
                runs = detect_melisma_notes(track, syl_start, syl_end)

                for run_idx, (run_start, run_end) in enumerate(runs):
                    pitch_result = pitch_extractor.summarize_track_window(track, run_start, run_end)

                    start_beat = grid.seconds_to_beat(run_start, gap_ms)
                    end_beat = grid.seconds_to_beat(run_end, gap_ms)
                    duration_beats = max(1, end_beat - start_beat)  # nunca duração zero

                    # Continuação de melisma ("~") sem voz/confiança suficiente
                    # nunca deve virar "F ... 0 ~" isolado: incorpora na nota
                    # anterior da mesma sílaba.
                    if run_idx > 0 and pitch_result.confidence < 0.5 and notes:
                        notes[-1].duration_beats = max(
                            notes[-1].duration_beats, end_beat - notes[-1].start_beat
                        )
                        continue

                    # CONVENÇÃO DE ESPAÇAMENTO (revista 12/07/2026): sílabas
                    # de uma mesma palavra têm texto CONCATENADO na tela; um
                    # espaço no início/fim marca a fronteira entre palavras.
                    # A 1ª nota de uma sílaba carrega o texto dela; notas de
                    # continuação (sustentação/melisma) usam "~" - convenção
                    # real do UltraStar pra pitch variando numa nota longa.
                    text = syl if run_idx == 0 else "~"

                    notes.append(
                        Note(
                            start_beat=start_beat,
                            duration_beats=duration_beats,
                            pitch=pitch_result.ultrastar_pitch,
                            text=text,
                            note_type=":" if pitch_result.confidence >= 0.5 else "F",
                            # nota de baixa confiança de pitch vira "F" (freestyle,
                            # não pontua) em vez de arriscar uma nota errada -
                            # decisão conservadora para revisar manualmente depois.
                            source=wt.source,
                            # proveniência do timing (herdada da palavra inteira) -
                            # a tela de revisão usa para destacar notas estimadas.
                            score=wt.score,
                            # cantor da linha (dueto): todas as notas de uma
                            # palavra herdam o cantor dela.
                            singer=wt.singer,
                        )
                    )

                if is_last_syllable_of_word:
                    if sustained_end > word_end:
                        end_beat = grid.seconds_to_beat(sustained_end, gap_ms)
                        notes[-1].duration_beats = max(notes[-1].duration_beats,
                                                       end_beat - notes[-1].start_beat)
                    notes[-1].text += " "

        if wt.is_line_end and notes:
            phrase_breaks.append(len(notes) - 1)

    notes = fix_rounding_overlaps(notes)
    notes = rescue_isolated_short_freestyle(notes, phrase_breaks)
    notes = snap_octave_outliers(notes)
    notes = fold_octave_outliers_to_context(notes)
    # depois das correções de oitava (elas também deixam vizinhos iguais) e
    # antes da dourada (que escolhe pelas notas mais longas)
    notes, phrase_breaks = merge_flat_continuations(
        notes, phrase_breaks,
        max_gap_beats=max(1, round(MELISMA_MIN_EXTENSION_S * grid.bpm * 4 / 60.0)),
    )
    phrase_breaks = merge_short_connected_lines(notes, phrase_breaks, grid)
    notes = apply_golden_notes(notes, min_duration_beats=golden_min_beats(grid))

    return notes, phrase_breaks


def build_song(
    title: str,
    artist: str,
    mp3_filename: str,
    word_timings: list[WordTiming],
    vocals_wav_path: Path,
    grid: BeatGrid,
    gap_ms: int = 0,
    language: str = "Portuguese",
    year: int | None = None,
    genre: str | None = None,
    cover_filename: str | None = None,
    video_filename: str | None = None,
    background_filename: str | None = None,
    audio_url: str | None = None,
    video_url: str | None = None,
    cover_url: str | None = None,
    video_gap: float | None = None,
    vocals_filename: str | None = None,
    instrumental_filename: str | None = None,
    duet: bool = False,
    p1_name: str | None = None,
    p2_name: str | None = None,
    transpose: int = 0,
    creator: str = "USKMaker",
) -> Song:
    pitch_extractor = PitchExtractor()

    # GAP automático (convenção UltraStar, 12/07/2026): joga o offset real do
    # início do canto para a tag #GAP e faz a PRIMEIRA nota começar no beat ~0.
    # Assim, re-sincronizar com um áudio de lead-in diferente (ex.: versão de
    # álbum vs. do clipe) é só ajustar o #GAP, sem arrastar todas as notas.
    # Usa o MENOR início entre as palavras para garantir que nenhuma nota caia
    # em beat negativo (o seconds_to_beat satura em 0). O gap_ms recebido (hoje
    # sempre 0) entra como ajuste fino adicional sobre esse offset.
    first_start = min((wt.start for wt in word_timings), default=0.0)
    effective_gap_ms = round_gap_ms(max(0, round(first_start * 1000)) + gap_ms)

    notes, phrase_breaks = build_notes(word_timings, vocals_wav_path, grid, effective_gap_ms, pitch_extractor,
                                       language=language)

    # Tom fixo: transpõe a melodia inteira N semitons, uniforme, DEPOIS de toda
    # a estimativa/dobra de pitch. Casa com o áudio deslocado pelo mesmo N em
    # convert_audio (rubberband). Shift uniforme mantém intervalos e voicing.
    if transpose:
        for n in notes:
            n.pitch += transpose

    preview_start, medley_start_beat, medley_end_beat = detect_chorus_preview_medley(
        word_timings, notes, grid, effective_gap_ms, duet=duet
    )

    return Song(
        title=title,
        artist=artist,
        mp3_filename=mp3_filename,
        # BUG CORRIGIDO (05/07/2026, 3ª rodada): usava grid.ultrastar_bpm
        # (bpm*4), duplicando a multiplicação por 4 que o motor do jogo já
        # faz sozinho (ver nota detalhada em beatgrid.py). Agora usa o BPM
        # BRUTO diretamente - é isso que a tag #BPM do .txt espera.
        bpm=grid.bpm,
        gap_ms=effective_gap_ms,
        language=language,
        # Fase 3: metadados enriquecidos (todos opcionais - o Song só
        # emite a tag correspondente no .txt se o valor não for None).
        year=year,
        genre=genre,
        cover_filename=cover_filename,
        video_filename=video_filename,
        background_filename=background_filename,
        audio_url=audio_url,
        video_url=video_url,
        cover_url=cover_url,
        video_gap=video_gap,
        preview_start=preview_start,
        medley_start_beat=medley_start_beat,
        medley_end_beat=medley_end_beat,
        vocals_filename=vocals_filename,
        instrumental_filename=instrumental_filename,
        creator=creator,
        notes=notes,
        phrase_breaks_after_index=phrase_breaks,
        duet=duet,
        p1_name=p1_name,
        p2_name=p2_name,
    )

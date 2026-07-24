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

from pathlib import Path

import numpy as np

from .align import WordTiming
from .beatgrid import BeatGrid
from .pitch import PitchExtractor, PitchTrack
from .syllabify import split_word_syllables
from .ultrastar_writer import Note, Song


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
    """
    for i in range(len(notes) - 1):
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
MELISMA_MIN_EXTENSION_S = 0.25
MELISMA_PITCH_TOLERANCE_ST = 2.0
MELISMA_MIN_SYLLABLE_S = 0.45


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
    # desfaria justamente a proteção de fronteira de palavra acima.
    merged = [spans[0]]
    for idx in range(1, len(spans)):
        start, end = spans[idx]
        if not run_started_by_gap[idx] and (end - start) < min_extension_s:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))

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


def build_notes(
    word_timings: list[WordTiming],
    vocals_wav_path: Path,
    grid: BeatGrid,
    gap_ms: int,
    pitch_extractor: PitchExtractor,
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

    for wt in word_timings:
        syllables = split_word_syllables(wt.word)
        # sílabas 100% pontuação (ex.: um "'" isolado por espaço na letra)
        # não têm conteúdo cantável e não devem virar nota própria.
        syllables = [s for s in syllables if any(c.isalnum() for c in s)]

        if syllables:
            word_start, word_end = wt.start, max(wt.start + 0.01, wt.end)
            track = pitch_extractor.extract_word_track(str(vocals_wav_path), word_start, word_end)
            syllable_spans = allocate_syllable_durations(track, len(syllables), word_start, word_end)

            for i, (syl, (syl_start, syl_end)) in enumerate(zip(syllables, syllable_spans)):
                is_last_syllable_of_word = (i == len(syllables) - 1)
                runs = detect_melisma_notes(track, syl_start, syl_end)

                for run_idx, (run_start, run_end) in enumerate(runs):
                    pitch_result = pitch_extractor.summarize_track_window(track, run_start, run_end)

                    start_beat = grid.seconds_to_beat(run_start, gap_ms)
                    end_beat = grid.seconds_to_beat(run_end, gap_ms)
                    duration_beats = max(1, end_beat - start_beat)  # nunca duração zero

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
                    notes[-1].text += " "

        if wt.is_line_end and notes:
            phrase_breaks.append(len(notes) - 1)

    notes = fix_rounding_overlaps(notes)
    notes = snap_octave_outliers(notes)
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
    vocals_filename: str | None = None,
    instrumental_filename: str | None = None,
    duet: bool = False,
    p1_name: str | None = None,
    p2_name: str | None = None,
    transpose: int = 0,
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

    notes, phrase_breaks = build_notes(word_timings, vocals_wav_path, grid, effective_gap_ms, pitch_extractor)

    # Tom fixo: transpõe a melodia inteira N semitons, uniforme, DEPOIS de toda
    # a estimativa/dobra de pitch. Casa com o áudio deslocado pelo mesmo N em
    # convert_to_ogg (rubberband). Shift uniforme mantém intervalos e voicing.
    if transpose:
        for n in notes:
            n.pitch += transpose

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
        vocals_filename=vocals_filename,
        instrumental_filename=instrumental_filename,
        notes=notes,
        phrase_breaks_after_index=phrase_breaks,
        duet=duet,
        p1_name=p1_name,
        p2_name=p2_name,
    )

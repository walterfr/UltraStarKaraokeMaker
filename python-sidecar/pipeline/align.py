"""
align.py
Etapa 4 (o coração do diferencial do USKMaker): alinhar a LETRA JÁ FORNECIDA
pelo usuário ao áudio vocal isolado, obtendo timestamp de início/fim por
palavra. Isso é "forced alignment", diferente de "transcrição" (o UltraSinger
transcreve do zero; aqui, o texto já é conhecido e confiável).

HISTÓRICO DE ESTRATÉGIAS:

1ª ABORDAGEM (mapeamento proporcional) - descartada: dividia a letra real em
pedaços e substituía o texto de cada segmento do Whisper proporcionalmente
por CONTAGEM de palavras. Palavras curtas/comuns ("e", "a", "o") podiam
"grudar" no timestamp de uma ocorrência ERRADA em outro lugar da música.
Confirmado em dois testes reais (Sangue Latino, "20 e poucos anos").

2ª ABORDAGEM (âncora + interpolação, 06/07/2026): o Whisper transcreve
LIVREMENTE e essa transcrição própria é alinhada (timestamps acústicos
reais); difflib.SequenceMatcher casa a transcrição com a letra real; cada
palavra casada vira "âncora" com timestamp medido; as demais são
interpoladas linearmente entre âncoras vizinhas. Erro fica confinado a
janelas pequenas, mas trechos longos sem âncora ficavam com distribuição
uniforme (irreal) e qualquer palavra que o Whisper grafasse diferente
("tá" vs "está") perdia a âncora sem necessidade.

3ª ABORDAGEM (atual, 09/07/2026) - refinamento em quatro passes:
  1. ÂNCORAS EXATAS: como antes (SequenceMatcher sobre palavras
     normalizadas), timestamps medidos pelo whisperx para todo match exato.
  2. ÂNCORAS FUZZY: dentro dos blocos que o diff marcou como "replace"
     (Whisper ouviu ALGO ali, mas grafou diferente), casa palavras
     quase-iguais (similaridade de caracteres, pareamento monotônico por
     programação dinâmica). Insight: se o Whisper ouviu "cara" onde a letra
     diz "casa", o EVENTO ACÚSTICO é o mesmo - o timestamp é bom, só a
     grafia difere. Recupera "pra"/"para", "tá"/"está", plurais etc.
  3. REALINHAMENTO ACÚSTICO DOS GAPS: para cada sequência de palavras ainda
     sem âncora, roda whisperx.align() de novo SÓ na janela de áudio entre
     as âncoras vizinhas, com o texto real que falta. O wav2vec2 faz forced
     alignment de verdade dentro da janela - a palavra passa a ser MEDIDA,
     não estimada. Resolve inclusive o caso de pausa instrumental no meio
     do gap (a interpolação linear espalhava palavras pela pausa; o
     alinhador acústico as localiza do lado certo).
  4. INTERPOLAÇÃO PONDERADA (último fallback): o que ainda restar é
     interpolado entre âncoras vizinhas com peso proporcional ao nº de
     sílabas (aproximado por grupos de vogais) - "coração" ganha mais tempo
     que "e" - em vez da distribuição uniforme antiga.

DESCOBERTA IMPORTANTE (validada em teste real - "Sangue Latino", 05/07/2026):
- O score de confiança do whisperx.align() vem sistematicamente baixo
  (às vezes 0.00-0.35) em trechos CANTADOS, mesmo quando o timestamp está
  correto. O modelo fonético (wav2vec2 CTC) foi treinado em fala; vogais
  esticadas, vibrato e variação de pitch derrubam a confiança sem indicar
  erro real de timing. NÃO use o score sozinho como critério de descarte -
  trate como "baixa certeza fonética", candidato a checagem manual.
- Palavras INTERPOLADAS (fallback final) sempre recebem score=0.0 -
  sinal DIFERENTE do score fonético baixo: "não foi medida, foi estimada".

DESCOBERTA CRÍTICA #2 (teste real - "Sangue Latino", 05/07/2026, 2ª rodada):
- O .txt sem NENHUM marcador de quebra de linha ("-") carrega mas as notas
  NÃO rolam na tela de canto (UltraStar Deluxe E Play). Corrigido propagando
  qual palavra é a ÚLTIMA de cada linha da letra original (is_line_end).

TODO conhecido:
- Alternativa mais "pura" de forced alignment (sem depender do Whisper para
  segmentação): Montreal Forced Aligner (MFA) ou aeneas. Só vale investigar
  se o passe de realinhamento acústico ainda deixar casos ruins em PT-BR.

Uso isolado (teste manual):
    python -m pipeline.align --vocals ./work/stems/htdemucs/musica/vocals.wav \
        --lyrics ./work/lyrics.txt --language pt --out ./work/align.json
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path

# Fontes de timestamp, da mais confiável para a menos:
SOURCE_ANCHOR = "anchor"          # match exato com a transcrição livre (medido)
SOURCE_FUZZY = "fuzzy"            # match aproximado de grafia (medido)
SOURCE_REALIGN = "realign"        # 2º passe de forced alignment na janela (medido)
SOURCE_LRC = "lrc"                # início de linha do .lrc (LRCLIB) - semi-medido
SOURCE_INTERPOLATED = "interpolated"  # estimado entre vizinhos (NÃO medido)


@dataclass
class WordTiming:
    word: str
    start: float  # segundos
    end: float    # segundos
    score: float  # confiança FONÉTICA do alinhamento (0-1) quando MEDIDA
    # pelo whisperx. Quando INTERPOLADA é sempre 0.0 - um sinal diferente
    # do score fonético baixo, significa "estimada, não medida".
    is_line_end: bool = False  # True se esta é a última palavra de uma
    # linha/frase da letra original - usado pelo build_song.py para saber
    # onde inserir os marcadores de quebra de frase ("-") no .txt final.
    anchored: bool = True  # True = timestamp MEDIDO no áudio (âncora exata,
    # fuzzy ou realinhamento de janela); False = interpolado/estimado.
    source: str = SOURCE_ANCHOR  # qual passe produziu o timestamp - ver
    # constantes SOURCE_* acima. Diagnóstico/revisão manual futura.


def _load_lyrics_words_with_line_ends(lyrics_path: Path) -> tuple[list[str], list[bool]]:
    """
    Lê o arquivo de letra e retorna duas listas paralelas:
      - as palavras, na ordem em que aparecem (sem marcadores especiais)
      - um bool por palavra: True se ela é a ÚLTIMA palavra da sua linha
        (ou seja, onde deve entrar um marcador de quebra de frase "-" no
        .txt final do UltraStar).
    """
    text = lyrics_path.read_text(encoding="utf-8")
    words: list[str] = []
    line_ends: list[bool] = []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        line_words = line.split()
        for i, w in enumerate(line_words):
            words.append(w)
            line_ends.append(i == len(line_words) - 1)

    return words, line_ends


_LRC_TS_RE = re.compile(r"\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]")


def parse_lrc(text: str) -> list[tuple[float, str]]:
    """
    Faz o parse de uma letra sincronizada .lrc (formato LRCLIB) numa lista
    ordenada de (segundos, texto_da_linha). Ignora linhas de metadado
    ([ar:], [ti:], [length:] etc. - o "tag" ali dentro é alfabético, não um
    timestamp) e linhas sem texto (só o timestamp). Uma mesma linha pode ter
    vários timestamps (refrão repetido) - cada um vira uma entrada.
    """
    out: list[tuple[float, str]] = []
    for raw in text.splitlines():
        stamps = list(_LRC_TS_RE.finditer(raw))
        if not stamps:
            continue
        # o texto é o que vem depois do último timestamp da linha
        content = raw[stamps[-1].end():].strip()
        if not content:
            continue
        for m in stamps:
            minutes = int(m.group(1))
            seconds = int(m.group(2))
            frac_raw = m.group(3) or "0"
            # normaliza a fração para milissegundos (2 dígitos = centésimos)
            frac = float(f"0.{frac_raw}")
            out.append((minutes * 60 + seconds + frac, content))
    out.sort(key=lambda p: p[0])
    return out


def _lyric_lines_with_start_index(lyrics_path: Path) -> list[tuple[str, int]]:
    """
    Retorna, para cada linha NÃO vazia da letra, o par (texto_da_linha,
    índice da PRIMEIRA palavra da linha na lista global de palavras). Usa
    exatamente a mesma segmentação de _load_lyrics_words_with_line_ends
    (strip + split), então os índices batem com aquela lista de palavras.
    """
    text = lyrics_path.read_text(encoding="utf-8")
    lines: list[tuple[str, int]] = []
    word_idx = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        line_words = line.split()
        if line_words:
            lines.append((line, word_idx))
            word_idx += len(line_words)
    return lines


def _normalize_line(text: str) -> str:
    """Normaliza uma LINHA inteira para comparar letra real x linha do .lrc."""
    return re.sub(r"[^\wÀ-ÿ]+", " ", text.lower()).strip()


def match_lrc_to_lines(
    lyric_lines: list[str],
    lrc_lines: list[tuple[float, str]],
) -> dict[int, float]:
    """
    Casa as linhas da letra real com as linhas do .lrc (na ordem), devolvendo
    um dicionário {índice_da_linha_da_letra: tempo_de_início_em_s}.

    Usa difflib sobre o texto normalizado das linhas e aproveita só os blocos
    "equal" (correspondência confiável 1:1) - assim linhas de metadado,
    refrões escritos de forma diferente ou pequenas divergências simplesmente
    não recebem âncora, em vez de casar errado.
    """
    if not lyric_lines or not lrc_lines:
        return {}
    a = [_normalize_line(t) for t in lyric_lines]
    b = [_normalize_line(t) for _, t in lrc_lines]
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    result: dict[int, float] = {}
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            continue
        for off in range(i2 - i1):
            result[i1 + off] = lrc_lines[j1 + off][0]
    return result


def seed_line_anchors(
    anchors: list[Anchor | None],
    lyric_lines: list[tuple[str, int]],
    lrc_lines: list[tuple[float, str]],
    tolerance: float = 0.6,
) -> int:
    """
    Semeia âncoras de linha (LRCLIB) na PRIMEIRA palavra de cada linha da
    letra que ainda não tem timestamp medido, respeitando monotonicidade em
    relação às âncoras vizinhas já existentes. Muta `anchors` in-place e
    retorna quantas âncoras foram semeadas.

    Só entra onde o Whisper NÃO mediu nada (anchors[i] is None) - as âncoras
    exatas/fuzzy do áudio são mais precisas que o início de linha do .lrc e
    têm prioridade. O valor do .lrc brilha justamente nos vãos que o Whisper
    deixou (trechos mal transcritos, sem match), encurtando as janelas de
    interpolação e dando limites corretos ao realinhamento acústico (passe 3).
    """
    line_texts = [t for t, _ in lyric_lines]
    matched = match_lrc_to_lines(line_texts, lrc_lines)
    if not matched:
        return 0

    n = len(anchors)
    seeded = 0
    for line_idx, (_, start_word) in enumerate(lyric_lines):
        t = matched.get(line_idx)
        if t is None or start_word >= n or anchors[start_word] is not None:
            continue
        # âncora medida imediatamente anterior/posterior (não-None)
        prev_end = None
        for k in range(start_word - 1, -1, -1):
            if anchors[k] is not None:
                prev_end = anchors[k][1]
                break
        next_start = None
        for k in range(start_word + 1, n):
            if anchors[k] is not None:
                next_start = anchors[k][0]
                break
        # monotonicidade: o tempo do .lrc precisa caber entre os vizinhos
        if prev_end is not None and t < prev_end - tolerance:
            continue
        if next_start is not None and t > next_start + tolerance:
            continue
        end = t + 0.25
        if next_start is not None:
            end = min(end, max(t + 0.02, next_start - 0.02))
        anchors[start_word] = (t, end, 0.0, SOURCE_LRC)
        seeded += 1
    return seeded


def _normalize_word(word: str) -> str:
    """
    Normaliza uma palavra para comparação (minúsculas, sem pontuação),
    preservando acentos - remover acentos criaria falsos positivos entre
    palavras diferentes em português (ex.: "e" vs "é").
    """
    return re.sub(r"[^\wÀ-ÿ]", "", word.lower())


_VOWEL_GROUP_RE = re.compile(r"[aeiouyáàâãäéèêëíìîïóòôõöúùûü]+", re.IGNORECASE)


def _syllable_weight(word: str) -> int:
    """
    Estimativa barata do nº de sílabas (grupos de vogais) para ponderar a
    interpolação - não precisa ser hifenização perfeita, só capturar que
    "coração" dura mais que "e". Mínimo 1.
    """
    return max(1, len(_VOWEL_GROUP_RE.findall(_normalize_word(word))))


# Cada âncora é (start, end, score, source); None = ainda sem timestamp medido.
Anchor = tuple[float, float, float, str]


def _fold_accents(word: str) -> str:
    """
    Remove acentos SÓ para a comparação fuzzy ("tá" deve casar com "está").
    O match EXATO continua preservando acentos (ver _normalize_word) - lá,
    remover acentos criaria falsos positivos em palavras de 1 letra ("e" vs
    "é"); aqui, palavras de 1 letra já ficam fora do fuzzy.
    """
    return "".join(
        c for c in unicodedata.normalize("NFD", word) if unicodedata.category(c) != "Mn"
    )


def _fuzzy_pairs(
    whisper_block: list[str],
    real_block: list[str],
    threshold: float = 0.6,
) -> list[tuple[int, int]]:
    """
    Pareamento monotônico ótimo (programação dinâmica, estilo LCS) entre dois
    blocos de palavras normalizadas, maximizando a soma das similaridades de
    caracteres acima de `threshold`. Retorna pares (idx_whisper, idx_real).

    Palavras de 1 caractere ficam de fora (similaridade de caracteres não
    diz nada útil sobre "e"/"a"/"o").
    """
    n, m = len(whisper_block), len(real_block)
    if n == 0 or m == 0 or n * m > 250_000:
        return []

    whisper_folded = [_fold_accents(w) for w in whisper_block]
    real_folded = [_fold_accents(w) for w in real_block]

    sims = [[0.0] * m for _ in range(n)]
    for i, a in enumerate(whisper_folded):
        if len(a) < 2:
            continue
        for j, b in enumerate(real_folded):
            if len(b) < 2:
                continue
            r = difflib.SequenceMatcher(None, a, b).ratio()
            if r >= threshold:
                sims[i][j] = r

    # dp[i][j] = melhor soma usando whisper_block[i:] e real_block[j:]
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            best = max(dp[i + 1][j], dp[i][j + 1])
            if sims[i][j] > 0.0:
                best = max(best, sims[i][j] + dp[i + 1][j + 1])
            dp[i][j] = best

    pairs: list[tuple[int, int]] = []
    i = j = 0
    while i < n and j < m:
        if sims[i][j] > 0.0 and abs(dp[i][j] - (sims[i][j] + dp[i + 1][j + 1])) < 1e-9:
            pairs.append((i, j))
            i += 1
            j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            i += 1
        else:
            j += 1
    return pairs


def compute_anchors(
    whisper_words: list[dict],
    real_words: list[str],
) -> list[Anchor | None]:
    """
    Passes 1 e 2: âncoras exatas (SequenceMatcher) + âncoras fuzzy dentro
    dos blocos "replace", seguidas da demoção de âncoras suspeitas.

    Retorna uma lista paralela a `real_words`: (start, end, score, source)
    para palavras com timestamp medido, None para as demais.
    """
    whisper_norm = [_normalize_word(w.get("word", "")) for w in whisper_words]
    real_norm = [_normalize_word(w) for w in real_words]

    matcher = difflib.SequenceMatcher(None, whisper_norm, real_norm, autojunk=False)
    anchors: list[Anchor | None] = [None] * len(real_words)

    def _anchor_from(w: dict, source: str) -> Anchor:
        return (
            float(w.get("start", 0.0)),
            float(w.get("end", 0.0)),
            float(w.get("score", 0.0)),
            source,
        )

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                anchors[j1 + offset] = _anchor_from(whisper_words[i1 + offset], SOURCE_ANCHOR)
        elif tag == "replace":
            # O Whisper OUVIU algo neste trecho, só grafou diferente - se a
            # grafia for parecida, o evento acústico é o mesmo e o timestamp
            # medido vale ("cara" ouvido onde a letra diz "casa").
            for bi, bj in _fuzzy_pairs(whisper_norm[i1:i2], real_norm[j1:j2]):
                anchors[j1 + bj] = _anchor_from(whisper_words[i1 + bi], SOURCE_FUZZY)

    _demote_suspicious_anchors(anchors, real_norm)
    return anchors


def _demote_suspicious_anchors(anchors: list[Anchor | None], real_norm: list[str]) -> None:
    """
    Demove (vira None) âncoras EXATAS de palavras muito curtas (<= 2 chars)
    que estão isoladas no meio de um gap grande: um "e"/"de" casado sozinho
    dentro de um trecho que o Whisper inteiro errou tem boa chance de ser a
    ocorrência errada, e uma âncora errada envenena a interpolação E parte a
    janela do realinhamento acústico no lugar errado. Sem ela, o passe de
    realinhamento mede o trecho inteiro de uma vez.
    """
    n = len(anchors)
    for j in range(n):
        a = anchors[j]
        if a is None or a[3] != SOURCE_ANCHOR or len(real_norm[j]) > 2:
            continue
        if (j > 0 and anchors[j - 1] is not None) or (j + 1 < n and anchors[j + 1] is not None):
            continue  # não está isolada
        # tamanho do gap ao redor (vizinhos None contíguos de cada lado)
        before = 0
        k = j - 1
        while k >= 0 and anchors[k] is None:
            before += 1
            k -= 1
        after = 0
        k = j + 1
        while k < n and anchors[k] is None:
            after += 1
            k += 1
        if before >= 3 and after >= 3:
            anchors[j] = None


def timings_from_anchors(
    anchors: list[Anchor | None],
    real_words: list[str],
) -> list[WordTiming]:
    """
    Passe 4 (fallback final): converte âncoras em WordTiming, interpolando
    as palavras sem âncora entre as âncoras vizinhas com peso proporcional
    ao nº estimado de sílabas. Processa gap a gap (não palavra a palavra).
    """
    n = len(real_words)
    results: list[WordTiming | None] = [None] * n

    for idx in range(n):
        a = anchors[idx]
        if a is not None:
            start, end, score, source = a
            results[idx] = WordTiming(
                word=real_words[idx], start=start, end=end,
                score=score, anchored=True, source=source,
            )

    # processa cada run contígua de índices sem âncora
    idx = 0
    while idx < n:
        if results[idx] is not None:
            idx += 1
            continue
        run_start = idx
        while idx < n and results[idx] is None:
            idx += 1
        run = list(range(run_start, idx))

        prev_idx = run_start - 1  # ancorado ou -1
        next_idx = idx            # ancorado ou n

        weights = [_syllable_weight(real_words[k]) for k in run]

        if prev_idx >= 0 and next_idx < n:
            prev_end = anchors[prev_idx][1]
            next_start = anchors[next_idx][0]
            span = max(0.05 * (len(run) + 1), next_start - prev_end)
            # reserva uma "respiração" média antes da âncora seguinte, para
            # não colar a última palavra interpolada na próxima medida
            breath = sum(weights) / len(weights)
            total = sum(weights) + breath
            t = prev_end
            for k, w in zip(run, weights):
                dur = span * w / total
                results[k] = WordTiming(
                    word=real_words[k], start=t, end=t + dur,
                    score=0.0, anchored=False, source=SOURCE_INTERPOLATED,
                )
                t += dur
        elif prev_idx >= 0:
            # fim da música sem âncora seguinte: encadeia para frente a
            # partir da última âncora, ~0.15s por sílaba
            t = anchors[prev_idx][1]
            for k, w in zip(run, weights):
                dur = min(0.8, max(0.2, 0.15 * w))
                results[k] = WordTiming(
                    word=real_words[k], start=t, end=t + dur,
                    score=0.0, anchored=False, source=SOURCE_INTERPOLATED,
                )
                t += dur
        elif next_idx < n:
            # início da música sem âncora anterior: encadeia para trás,
            # terminando na primeira âncora
            t = anchors[next_idx][0]
            for k, w in zip(reversed(run), reversed(weights)):
                dur = min(0.8, max(0.2, 0.15 * w))
                start = max(0.0, t - dur)
                results[k] = WordTiming(
                    word=real_words[k], start=start, end=t,
                    score=0.0, anchored=False, source=SOURCE_INTERPOLATED,
                )
                t = start
        else:
            # nenhuma âncora em toda a música - não deveria acontecer (o
            # realinhamento de janela cobre esse caso antes), evita crash
            t = 0.0
            for k, w in zip(run, weights):
                dur = min(0.8, max(0.2, 0.15 * w))
                results[k] = WordTiming(
                    word=real_words[k], start=t, end=t + dur,
                    score=0.0, anchored=False, source=SOURCE_INTERPOLATED,
                )
                t += dur

    return results  # type: ignore[return-value]


def anchor_and_interpolate(
    whisper_words: list[dict],
    real_words: list[str],
) -> list[WordTiming]:
    """
    Estratégia completa SEM o passe acústico de janela (passes 1, 2 e 4).
    Mantida como função pura (testável sem GPU); o realinhamento acústico
    (passe 3) é aplicado por cima em align_lyrics_to_audio.
    """
    anchors = compute_anchors(whisper_words, real_words)
    return timings_from_anchors(anchors, real_words)


def realign_gap_windows(
    timings: list[WordTiming],
    align_model,
    align_metadata: dict,
    audio,
    device: str,
) -> int:
    """
    Passe 3: para cada run contígua de palavras INTERPOLADAS, roda
    whisperx.align() na janela de áudio entre as palavras medidas vizinhas,
    com o texto real que falta - forced alignment de verdade, localizado.
    Muta `timings` in-place; retorna quantas palavras foram promovidas a
    SOURCE_REALIGN.

    Janela = [fim da última palavra MEDIDA antes da run, início da primeira
    palavra MEDIDA depois]. Sem vizinho medido, usa o começo/fim do áudio -
    o que cobre inclusive o caso extremo de música inteira sem âncora
    (vira um forced alignment global).
    """
    import whisperx  # import local: função só roda no caminho com GPU/modelo

    sample_rate = 16000  # whisperx.audio.SAMPLE_RATE
    audio_duration = float(len(audio)) / sample_rate

    n = len(timings)
    promoted = 0
    idx = 0
    while idx < n:
        if timings[idx].source != SOURCE_INTERPOLATED:
            idx += 1
            continue
        run_start = idx
        while idx < n and timings[idx].source == SOURCE_INTERPOLATED:
            idx += 1
        run = list(range(run_start, idx))

        win_start = timings[run_start - 1].end if run_start > 0 else 0.0
        win_end = timings[idx].start if idx < n else audio_duration
        win_start = max(0.0, min(win_start, audio_duration))
        win_end = max(0.0, min(win_end, audio_duration))

        # janela precisa de espaço mínimo para o CTC ter o que medir
        if win_end - win_start < 0.10 + 0.08 * len(run):
            continue

        segment = {
            "start": win_start,
            "end": win_end,
            "text": " ".join(timings[k].word for k in run),
        }
        try:
            result = whisperx.align(
                [segment], align_model, align_metadata, audio, device,
                interpolate_method="nearest", return_char_alignments=False,
            )
        except Exception:
            continue  # janela problemática não pode derrubar a pipeline

        words_out = [w for seg in result.get("segments", []) for w in seg.get("words", [])]
        if len(words_out) != len(run):
            continue  # mapeamento ambíguo - fica com a interpolação

        # valida antes de aplicar: timestamps presentes, dentro da janela
        # (com folga) e monotônicos
        new_times: list[tuple[float, float, float]] = []
        ok = True
        last_start = win_start - 0.001
        for w in words_out:
            ws, we = w.get("start"), w.get("end")
            if ws is None or we is None:
                ok = False
                break
            ws, we = float(ws), float(we)
            if ws < win_start - 0.5 or we > win_end + 0.5 or ws < last_start:
                ok = False
                break
            last_start = ws
            new_times.append((ws, max(we, ws + 0.02), float(w.get("score", 0.0))))
        if not ok:
            continue

        for k, (ws, we, score) in zip(run, new_times):
            timings[k].start = ws
            timings[k].end = we
            timings[k].score = score
            timings[k].anchored = True
            timings[k].source = SOURCE_REALIGN
            promoted += 1

    return promoted


def alignment_stats(timings: list[WordTiming]) -> dict:
    """Resumo por fonte + maiores runs ainda interpoladas (diagnóstico)."""
    counts = {s: 0 for s in (SOURCE_ANCHOR, SOURCE_FUZZY, SOURCE_REALIGN, SOURCE_LRC, SOURCE_INTERPOLATED)}
    for t in timings:
        counts[t.source] = counts.get(t.source, 0) + 1

    runs: list[int] = []
    cur = 0
    for t in timings:
        if t.source == SOURCE_INTERPOLATED:
            cur += 1
        elif cur:
            runs.append(cur)
            cur = 0
    if cur:
        runs.append(cur)
    runs.sort(reverse=True)

    return {"total": len(timings), "by_source": counts, "interpolated_runs": runs[:5]}


# Caches de modelo em nível de módulo: num processo de vida longa (server.py),
# os modelos pesados do WhisperX (Whisper + wav2vec2) são carregados UMA vez e
# reusados nas músicas seguintes - é daqui que vem o ganho de "modelos quentes"
# da fila. Num run avulso (python main.py) o processo morre no fim e o cache
# simplesmente não chega a ser reaproveitado - sem prejuízo. Os modelos são
# stateless entre chamadas (transcribe/align não guardam estado da música
# anterior), então cachear é seguro.
_WHISPER_CACHE: dict = {}
_ALIGN_CACHE: dict = {}


def _get_whisper_model(size: str, device: str, compute_type: str):
    import whisperx
    key = (size, device, compute_type)
    if key not in _WHISPER_CACHE:
        _WHISPER_CACHE[key] = whisperx.load_model(size, device, compute_type=compute_type)
    return _WHISPER_CACHE[key]


def _get_align_model(language: str, device: str):
    import whisperx
    key = (language, device)
    if key not in _ALIGN_CACHE:
        _ALIGN_CACHE[key] = whisperx.load_align_model(language_code=language, device=device)
    return _ALIGN_CACHE[key]


def align_lyrics_to_audio(
    vocals_wav: Path,
    lyrics_path: Path,
    language: str = "pt",
    device: str = "cuda",
    whisper_model_size: str = "medium",
    realign_gaps: bool = True,
    synced_lyrics_path: Path | None = None,
) -> list[WordTiming]:
    """
    Retorna uma lista de WordTiming na ordem da letra fornecida, usando a
    estratégia de 4 passes (ver docstring do módulo).

    Se `synced_lyrics_path` apontar para uma letra sincronizada .lrc (vinda do
    LRCLIB), os tempos de início de cada linha são semeados como âncoras nos
    vãos que o Whisper não mediu - encurta a interpolação e dá limites melhores
    ao realinhamento acústico.
    """
    import whisperx

    # float16 é ótimo na GPU (RTX 4060), mas o faster-whisper NÃO suporta
    # float16 na CPU - lá o correto é int8. (Na GPU, use "int8" se faltar VRAM.)
    compute_type = "float16" if device == "cuda" else "int8"

    # 1) Transcrição LIVRE (sem substituir nada) - queremos saber o que o
    #    Whisper de fato reconheceu no áudio, com timestamps de alta
    #    confiança para o que ele acertar.
    whisper_model = _get_whisper_model(whisper_model_size, device, compute_type)
    audio = whisperx.load_audio(str(vocals_wav))
    transcription = whisper_model.transcribe(audio, language=language)

    # 2) Alinha a transcrição PRÓPRIA do Whisper (não a letra real) - dá
    #    timestamps precisos para tudo que foi efetivamente reconhecido.
    align_model, metadata = _get_align_model(language, device)
    aligned = whisperx.align(
        transcription["segments"], align_model, metadata, audio, device, return_char_alignments=False
    )

    whisper_words: list[dict] = []
    for seg in aligned["segments"]:
        for w in seg.get("words", []):
            whisper_words.append(w)

    # 3) Âncoras exatas + fuzzy sobre a letra real.
    real_words, line_end_flags = _load_lyrics_words_with_line_ends(lyrics_path)
    anchors = compute_anchors(whisper_words, real_words)

    # 3b) Âncoras de linha do .lrc (LRCLIB), se houver: preenchem os vãos que
    #     o Whisper não mediu, antes da interpolação e do realinhamento.
    if synced_lyrics_path is not None and Path(synced_lyrics_path).exists():
        lrc_lines = parse_lrc(Path(synced_lyrics_path).read_text(encoding="utf-8"))
        lyric_lines = _lyric_lines_with_start_index(lyrics_path)
        seeded = seed_line_anchors(anchors, lyric_lines, lrc_lines)
        if seeded:
            print(f"[INFO] Âncoras de linha do .lrc: {seeded} inícios de linha semeados.")

    word_timings = timings_from_anchors(anchors, real_words)

    # 4) Realinhamento acústico das janelas ainda interpoladas (reusa o
    #    modelo wav2vec2 já carregado).
    if realign_gaps:
        promoted = realign_gap_windows(word_timings, align_model, metadata, audio, device)
        if promoted:
            print(f"[INFO] Realinhamento de janela: {promoted} palavras medidas no 2º passe.")

    for wt, is_end in zip(word_timings, line_end_flags):
        wt.is_line_end = is_end

    return word_timings


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Etapa 4: forced alignment letra<->áudio (teste isolado)")
    parser.add_argument("--vocals", required=True, help="Arquivo .wav do vocal isolado")
    parser.add_argument("--lyrics", required=True, help="Arquivo .txt com a letra (uma linha por frase)")
    parser.add_argument("--language", default="pt")
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    parser.add_argument("--whisper_model", default="medium")
    parser.add_argument("--no-realign", action="store_true",
                        help="Desliga o passe de realinhamento acústico das janelas (para comparar)")
    parser.add_argument("--out", default="./work/align.json")
    args = parser.parse_args()

    timings = align_lyrics_to_audio(
        Path(args.vocals), Path(args.lyrics), args.language, args.device,
        args.whisper_model, realign_gaps=not args.no_realign,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps([asdict(t) for t in timings], ensure_ascii=False, indent=2), encoding="utf-8")

    stats = alignment_stats(timings)
    by = stats["by_source"]
    line_ends = sum(1 for t in timings if t.is_line_end)
    print(
        f"[OK] {stats['total']} palavras: {by[SOURCE_ANCHOR]} âncora exata, "
        f"{by[SOURCE_FUZZY]} fuzzy, {by[SOURCE_REALIGN]} realinhadas (2º passe), "
        f"{by[SOURCE_INTERPOLATED]} interpoladas; {line_ends} fins de linha. Salvo em {out_path}"
    )
    if by[SOURCE_INTERPOLATED]:
        pct = 100 * by[SOURCE_INTERPOLATED] / stats["total"]
        print(f"[INFO] {pct:.1f}% interpoladas (maiores sequências: {stats['interpolated_runs']}).")
        for t in timings:
            if t.source == SOURCE_INTERPOLATED:
                print(f"   '{t.word}' @ {t.start:.2f}s (interpolada)")

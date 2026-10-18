"""
ctc_align.py
Alinhamento GLOBAL letra<->áudio por CTC (experimental, 30/09/2026).

O align.py parte da transcrição LIVRE do Whisper e só usa a letra real nos
vãos que ele não reconheceu. Aqui é o contrário: a letra inteira é alinhada
de uma vez contra as emissões de um modelo acústico calculadas UMA vez sobre
a música toda (Viterbi de forced alignment, torchaudio.functional.forced_align).
Não existe "palavra que o Whisper não ouviu": toda palavra da letra recebe um
lugar no áudio, e a ordem da letra é garantida pela própria busca.

Modelo: MMS_FA do torchaudio (wav2vec2 multilíngue treinado para forced
alignment em ~1100 idiomas, vocabulário latino a-z + apóstrofo). Para os
idiomas de LANG_CTC_MODELS, um wav2vec2 próprio do idioma no lugar dele. Idiomas com
outro alfabeto precisariam de romanização (uroman) - fora do escopo por ora:
quando a letra não cabe no vocabulário, `align_lyrics_ctc` devolve None e o
chamador fica com o caminho de sempre.

Token "*" (star): o MMS_FA traz um token coringa que absorve áudio que não
é letra (ad-lib, coro, respiração). Opcionalmente é inserido entre as linhas
da letra, para o que se canta entre uma linha e outra não ter que ser
"engolido" pelas palavras vizinhas.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import numpy as np

from .align import SOURCE_CTC, SOURCE_CTC_LOW
from .numerals import expand_numeral

# Linha cuja média de score CTC das palavras fica abaixo disto é marcada
# SOURCE_CTC_LOW. MEDIDO (30/09/2026, 8 músicas, 407 linhas, 40 com erro
# mediano > 1 s): < 0,10 marca 20% das linhas e pega 85% das erradas
# (precisão 0,41 contra 10% de base). Abaixo disso a cobertura cai rápido
# (0,05: pega 47%); acima, marca linha boa demais (0,20: 33% das linhas).
LOW_LINE_SCORE = 0.10

SAMPLE_RATE = 16000

# Letras que o NFKD não decompõe em base + acento, mas que têm leitura latina
# óbvia pro vocabulário a-z.
_SPECIAL_FOLDS = {"ß": "ss", "æ": "ae", "ø": "o", "œ": "oe", "đ": "d", "ł": "l",
                  "þ": "th", "ð": "d", "ı": "i"}

# Custo (log-prob por quadro) do token coringa "*". O torchaudio usa 0
# (probabilidade 1: o coringa é "de graça", melhor que qualquer letra ou o
# blank), e isso deixa o Viterbi espremer uma linha inteira em poucos quadros
# e cobrir o resto com "*" quando a evidência acústica da linha é fraca.
STAR_LOGP = 0.0

# fração máxima de letras (da letra inteira) fora do vocabulário antes de
# desistir - acima disso não é "um símbolo perdido", é outro alfabeto
MAX_UNMAPPED_FRAC = 0.05


def _fold(c: str) -> str:
    c = _SPECIAL_FOLDS.get(c, c)
    return "".join(x for x in unicodedata.normalize("NFKD", c) if not unicodedata.combining(x))


def _word_chars(word: str, language: str, keep: frozenset[str] | set[str] = frozenset()) -> str:
    """Palavra -> só os caracteres que o modelo conhece (minúsculas, sem acento,
    números por extenso). Pode devolver "" (palavra só de pontuação).
    Letras em `keep` (o vocabulário do modelo) não perdem o acento: o modelo
    sueco conhece å/ä/ö, o MMS_FA não."""
    w = word.lower().replace("’", "'").replace("`", "'")
    digits = re.sub(r"[^\w']", "", w)
    if any(c.isdigit() for c in digits):
        w = " ".join(expand_numeral(digits, language))
    return "".join(c if c in keep else _fold(c) for c in w)


_RESERVED = frozenset("-*|")  # blank, coringa, separador de palavras


def tokenize_words(
    words: list[str], dictionary: dict[str, int], language: str
) -> tuple[list[list[int]], float]:
    """
    Converte cada palavra em ids do vocabulário. Devolve (tokens por palavra,
    fração de letras descartadas por estarem fora do vocabulário).
    """
    per_word: list[list[int]] = []
    letters = unmapped = 0
    for word in words:
        ids = []
        for c in _word_chars(word, language, dictionary.keys()):
            # "-" é o blank e "*" o coringa no vocabulário do MMS_FA: o hífen
            # de "rock-n-roll" não pode virar o token blank
            if c in dictionary and c not in _RESERVED:
                ids.append(dictionary[c])
                letters += 1
            elif c.isalpha():
                unmapped += 1
                letters += 1
        per_word.append(ids)
    frac = unmapped / letters if letters else 1.0
    return per_word, frac


def build_targets(
    word_tokens: list[list[int]],
    line_ends: list[bool],
    star_id: int | None,
    sep_id: int | None = None,
) -> tuple[list[int], list[tuple[int, int]]]:
    """
    Sequência-alvo do CTC + faixa [ini, fim) de cada palavra dentro dela.
    Com `star_id`, um token coringa entra antes da 1ª palavra, depois de cada
    fim de linha e no fim - ele não pertence a palavra nenhuma. O da ponta é
    o que importa mais: sem ele, a introdução instrumental que vaza no stem
    precisa ser "explicada" por letra, e as primeiras palavras grudam no 0 s
    (medido em "Nothing Else Matters": "So close" em 0,0 s, gold 61 s).

    Com `sep_id`, o separador de palavras do modelo ("|" nos wav2vec2 do
    Hugging Face) entra entre duas palavras da mesma linha - também fora das
    palavras. Na troca de linha quem separa é o coringa.
    """
    targets: list[int] = [star_id] if star_id is not None else []
    ranges: list[tuple[int, int]] = []
    for k, ids in enumerate(word_tokens):
        if sep_id is not None and ids and ranges and targets and targets[-1] not in (star_id, sep_id):
            targets.append(sep_id)
        start = len(targets)
        targets.extend(ids)
        ranges.append((start, len(targets)))
        if star_id is not None and line_ends[k]:
            targets.append(star_id)
    if star_id is not None and targets[-1] != star_id:
        targets.append(star_id)
    return targets, ranges


MAX_INTRA_WORD_GAP_S = 0.8
MAX_PREMATURE_PREFIX_S = 0.4


def _trim_premature_word_prefix(
    spans: list[tuple[int, int, float]], frame_s: float
) -> list[tuple[int, int, float]]:
    """
    Quando o CTC prende a(s) primeira(s) letra(s) de uma palavra na cauda vocal
    da linha anterior antes de uma pausa longa (> 0,8 s) e alinha o resto da
    palavra segundos depois (caso real: "wanna" com "wan" em 213,5 s e "na" em
    216,2 s; "missing" com "miss" em 88,3 s e "ing" em 93,6 s), descarta o
    prefixo prematuro curto (<= 0,4 s) para a palavra não esticar por segundos
    de silêncio ou melisma da linha anterior.
    """
    if len(spans) < 2 or frame_s <= 0:
        return spans
    for k in range(len(spans) - 1):
        gap_s = (spans[k + 1][0] - spans[k][1]) * frame_s
        prefix_dur_s = (spans[k][1] - spans[0][0]) * frame_s
        if gap_s > MAX_INTRA_WORD_GAP_S and prefix_dur_s <= MAX_PREMATURE_PREFIX_S:
            return spans[k + 1 :]
    return spans


def spans_to_word_times(
    token_spans: list[tuple[int, int, float]],
    ranges: list[tuple[int, int]],
    frame_s: float,
) -> list[tuple[float, float, float] | None]:
    """
    (ini_frame, fim_frame, score) por token alvo -> (start_s, end_s, score) por
    palavra. Palavra sem nenhum token (só pontuação) vira None. Score da
    palavra = média dos scores dos seus tokens ponderada pela duração.
    """
    out: list[tuple[float, float, float] | None] = []
    for a, b in ranges:
        if a == b:
            out.append(None)
            continue
        spans = _trim_premature_word_prefix(token_spans[a:b], frame_s)
        dur = sum(e - s for s, e, _ in spans)
        score = sum((e - s) * sc for s, e, sc in spans) / dur if dur else 0.0
        out.append((spans[0][0] * frame_s, spans[-1][1] * frame_s, float(score)))
    return out


def word_token_times(
    token_spans: list[tuple[int, int, float]],
    ranges: list[tuple[int, int]],
    frame_s: float,
) -> list[list[tuple[float, float]]]:
    """(ini_s, fim_s) de cada letra alinhada, agrupadas por palavra."""
    return [
        [(sp[0] * frame_s, sp[1] * frame_s) for sp in _trim_premature_word_prefix(token_spans[a:b], frame_s)]
        for a, b in ranges
    ]


def syllable_starts(
    syllables: list[str],
    token_times: list[tuple[float, float]],
    dictionary: dict[str, int],
    language: str,
) -> list[float] | None:
    """
    Início de cada sílaba = instante em que o CTC alinhou a 1ª letra dela.
    As letras de cada sílaba são contadas com a MESMA tokenização da palavra
    (tokenize_words), então a soma tem que bater com as letras alinhadas da
    palavra; se não bater (número por extenso, hífen, etc.), ou alguma sílaba
    ficar sem letra, devolve None e quem chama fica com a divisão de antes.
    """
    if len(syllables) < 2:
        return None
    per_syl, _ = tokenize_words(syllables, dictionary, language)
    counts = [len(t) for t in per_syl]
    if 0 in counts or sum(counts) != len(token_times):
        return None
    starts, k = [], 0
    for c in counts:
        starts.append(token_times[k][0])
        k += c
    if any(b <= a for a, b in zip(starts, starts[1:])):
        return None
    return starts


def fill_missing(times: list[tuple[float, float, float] | None]) -> list[tuple[float, float, float, bool]]:
    """Palavras sem token herdam um ponto entre as vizinhas medidas (duração
    zero-ish). Devolve (start, end, score, medido)."""
    out: list[tuple[float, float, float, bool]] = []
    last_end = 0.0
    n = len(times)
    for k, t in enumerate(times):
        if t is not None:
            out.append((t[0], t[1], t[2], True))
            last_end = t[1]
            continue
        nxt = next((times[j][0] for j in range(k + 1, n) if times[j] is not None), last_end)
        s = last_end
        e = max(s, min(nxt, s + 0.05))
        out.append((s, e, 0.0, False))
    return out


# ---------------- partes que precisam de torch/modelo ----------------

_MODEL_CACHE: dict = {}


def _get_mms_model(device: str):
    key = device
    if key not in _MODEL_CACHE:
        from torchaudio.pipelines import MMS_FA
        model = MMS_FA.get_model(with_star=True).to(device).eval()
        _MODEL_CACHE[key] = (model, MMS_FA.get_dict(star="*"))
    return _MODEL_CACHE[key]


# Separador de palavras no `dictionary` de um modelo do Hugging Face (o "|"
# dos wav2vec2 CTC). O MMS_FA não tem.
SEP_KEY = "|"


class _HFCTCModel:
    """
    wav2vec2 CTC do Hugging Face com a MESMA interface do modelo MMS_FA
    with_star do torchaudio, para o compute_emissions servir aos dois:
    `model(x) -> (emissões [1, T, C+1], None)`, com uma última coluna do
    coringa "*" fixa em 0 - o compute_emissions renormaliza todas menos ela.
    """

    def __init__(self, model, normalize: bool):
        self.model = model
        self.normalize = normalize

    def __call__(self, x):
        import torch
        if self.normalize:  # do_normalize do feature extractor do modelo
            x = (x - x.mean(dim=-1, keepdim=True)) / torch.sqrt(x.var(dim=-1, keepdim=True) + 1e-7)
        logits = self.model(x).logits
        return torch.cat([logits, torch.zeros_like(logits[..., :1])], dim=-1), None


# Commit fixo de cada modelo do Hugging Face: sem ele o from_pretrained baixa
# o que estiver no `main` do repositório no dia - um modelo diferente do que
# foi medido, sem aviso. É o commit com que LANG_CTC_MODELS foi medido.
HF_MODEL_REVISIONS = {
    "KBLab/wav2vec2-large-voxrex-swedish": "ca70e31c06a2617bf7fe3b4fb5d387d2b19b2983",
}


def _get_hf_model(name: str, device: str):
    """
    (modelo, dicionário) de um wav2vec2 CTC do Hugging Face, no formato do
    _get_mms_model: letras em minúsculas, "-" = blank (o <pad>), "*" = a
    coluna extra do coringa e SEP_KEY = o separador de palavras. Só modelo
    com commit em HF_MODEL_REVISIONS (KeyError se não tiver).
    """
    key = (name, device)
    if key not in _MODEL_CACHE:
        from transformers import Wav2Vec2FeatureExtractor, Wav2Vec2ForCTC, Wav2Vec2CTCTokenizer
        rev = HF_MODEL_REVISIONS[name]
        tok = Wav2Vec2CTCTokenizer.from_pretrained(name, revision=rev)
        fe = Wav2Vec2FeatureExtractor.from_pretrained(name, revision=rev)
        model = Wav2Vec2ForCTC.from_pretrained(name, revision=rev).to(device).eval()
        vocab = tok.get_vocab()
        dictionary = {k.lower(): v for k, v in vocab.items()
                      if len(k) == 1 and k != tok.word_delimiter_token}
        dictionary["-"] = tok.pad_token_id
        dictionary["*"] = model.config.vocab_size
        dictionary[SEP_KEY] = vocab[tok.word_delimiter_token]
        _MODEL_CACHE[key] = (_HFCTCModel(model, fe.do_normalize), dictionary)
    return _MODEL_CACHE[key]


def get_ctc_model(device: str, model_name: str | None = None):
    """`model_name` None = MMS_FA; senão um wav2vec2 CTC do Hugging Face."""
    return _get_mms_model(device) if model_name is None else _get_hf_model(model_name, device)


# Modelo acústico do idioma, no lugar do MMS_FA multilíngue. Sueco: o mesmo
# wav2vec2 do KBLab que o WhisperX já usa no caminho do Whisper (ou seja, quem
# gera em sueco já o baixa), e o vocabulário dele tem å/ä/ö - o MMS_FA só tem
# a-z, e "så"/"sa", "för"/"for" viravam a mesma coisa.
#
# MEDIDO (01/10/2026, 7 músicas suecas com chart feito à mão, mesmos stems;
# a 8ª da amostra tem o chart deslocado e ficou de fora): palavras a até 1 s,
# mediana 0,981 -> 1,000 (média 0,947 -> 0,982); p90 do erro de início
# 145 -> 123 ms; fim da palavra 95 -> 86 ms. O MMS_FA errava linhas inteiras
# por segundos em 2 das 7 (p90 2,0 s e 1,3 s -> 0,2 s e 0,6 s); em 1 das 7 o
# sueco foi pior (p90 160 -> 722 ms). A mediana do erro de início fica 7 ms
# pior (44 -> 51 ms). E o score dele é mais alto: nenhuma das 8 passou de 35%
# de palavras de confiança baixa (o MMS_FA passou numa, que ia cair pro
# Whisper), então o LOW_LINE_SCORE e o limite do retorno valem como estão.
LANG_CTC_MODELS = {"sv": "KBLab/wav2vec2-large-voxrex-swedish"}


def ctc_model_for(language: str, device: str):
    """
    (modelo, dicionário) para o idioma. Se o modelo do idioma não carrega (sem
    internet no primeiro uso, por exemplo), fica o MMS_FA - ainda é o CTC, e o
    caminho do Whisper precisaria do mesmo modelo para alinhar.
    """
    name = LANG_CTC_MODELS.get(language)
    if name is not None:
        try:
            return get_ctc_model(device, name)
        except Exception as e:  # noqa: BLE001 - qualquer falha de download/carga
            from .i18n import t as _t
            print(_t("align.ctc_model_fallback", model=name, err=e))
    return get_ctc_model(device)


def compute_emissions(
    model, audio: np.ndarray, device: str,
    chunk_s: float = 30.0, context_s: float = 2.0,
):
    """
    Log-probabilidades por quadro sobre o áudio INTEIRO, em blocos de
    `chunk_s` com `context_s` de contexto de cada lado (descartado na
    costura) - música de 5 min não cabe de uma vez na atenção do wav2vec2.
    Devolve (emissions [T, C] float32 na CPU, segundos por quadro).
    """
    import torch

    n = len(audio)
    wav = torch.from_numpy(np.ascontiguousarray(audio, dtype=np.float32))
    chunk = int(chunk_s * SAMPLE_RATE)
    ctx = int(context_s * SAMPLE_RATE)
    pieces = []
    stride = None
    with torch.inference_mode():
        for s in range(0, n, chunk):
            e = min(n, s + chunk)
            s0, e0 = max(0, s - ctx), min(n, e + ctx)
            x = wav[s0:e0].unsqueeze(0).to(device)
            em, _ = model(x)
            em = em[0].float().cpu()
            per_frame = (e0 - s0) / em.shape[0]  # amostras por quadro (~320)
            stride = stride or per_frame
            a = int(round((s - s0) / per_frame))
            b = int(round((e - s0) / per_frame))
            pieces.append(em[a:b])
    emissions = torch.cat(pieces, dim=0)
    # O modelo "with_star" do torchaudio devolve log-probs das letras + uma
    # coluna final do "*" fixa em 0 (probabilidade 1). Renormaliza só as
    # letras (sem o "*"), pra coluna do coringa poder receber um custo
    # próprio em align (ver STAR_LOGP).
    emissions[:, :-1] = torch.log_softmax(emissions[:, :-1], dim=-1)
    return emissions, (stride or 320.0) / SAMPLE_RATE


def ctc_viterbi(log_probs: np.ndarray, targets: list[int], blank: int = 0) -> list[tuple[int, int, float]]:
    """
    Forced alignment CTC (Viterbi) sobre `log_probs` [T, C]: o caminho mais
    provável que emite exatamente `targets`, com blanks opcionais entre eles.
    Devolve um (ini_quadro, fim_quadro, score) por token alvo; score = média
    da probabilidade do token nos quadros dele (mesmo contrato do
    torchaudio.functional.merge_tokens).

    Implementação própria em vez do torchaudio.functional.forced_align: ele
    foi descontinuado e SAI no torchaudio 2.9 (aviso do próprio torchaudio
    2.8). Estados = alvo intercalado com blanks (2L+1); a cada quadro um
    estado vem de si mesmo, do anterior, ou de dois antes quando pula um
    blank entre tokens diferentes.
    """
    lp = np.asarray(log_probs, dtype=np.float32)
    T = lp.shape[0]
    L = len(targets)
    S = 2 * L + 1
    ext = np.full(S, blank, dtype=np.int64)
    ext[1::2] = targets
    # pular o blank só entre tokens diferentes (repetido exige blank no meio)
    can_skip = np.zeros(S, dtype=bool)
    can_skip[3::2] = ext[3::2] != ext[1:-2:2]

    neg = np.float32(-1e30)
    score = np.full(S, neg, dtype=np.float32)
    score[0] = lp[0, blank]
    if S > 1:
        score[1] = lp[0, ext[1]]
    back = np.zeros((T, S), dtype=np.int8)  # 0 = fica, 1 = veio de s-1, 2 = de s-2
    for t in range(1, T):
        stay = score
        step = np.concatenate(([neg], score[:-1]))
        skip = np.where(can_skip, np.concatenate(([neg, neg], score[:-2])), neg)
        best = np.maximum(stay, np.maximum(step, skip))
        back[t] = np.where(best == stay, 0, np.where(best == step, 1, 2))
        score = best + lp[t, ext]

    s_ = int(S - 1 if S == 1 or score[S - 1] >= score[S - 2] else S - 2)
    path = np.empty(T, dtype=np.int64)
    for t in range(T - 1, -1, -1):
        path[t] = s_
        s_ -= int(back[t, s_])

    spans: list[tuple[int, int, float]] = []
    probs = np.exp(lp[np.arange(T), ext[path]])
    for j in range(L):
        frames = np.nonzero(path == 2 * j + 1)[0]
        if frames.size == 0:  # não acontece com caminho válido
            return []
        spans.append((int(frames[0]), int(frames[-1]) + 1, float(probs[frames].mean())))
    return spans


def forced_align_spans(emissions, targets: list[int], blank: int = 0) -> list[tuple[int, int, float]]:
    """Viterbi; um (ini, fim, score) por token alvo, em quadros."""
    em = emissions.numpy() if hasattr(emissions, "numpy") else emissions
    return ctc_viterbi(em, targets, blank=blank)


def _occurrences(seq: list[str], hay: list[str]) -> int:
    n = len(seq)
    return sum(1 for i in range(len(hay) - n + 1) if hay[i:i + n] == seq)


def hard_anchor_runs(
    anchors: list, words: list[str] | None = None,
    min_run: int = 3, unambiguous_run: int = 8,
) -> list[tuple[int, int]]:
    """
    Faixas [i, j) de palavras com âncora EXATA do Whisper em sequência de pelo
    menos `min_run` palavras seguidas, com inícios crescentes, e em ordem
    temporal entre si. Uma âncora exata sozinha pode ser a ocorrência errada
    de uma palavra comum; três seguidas casando letra e transcrição quase
    nunca são - é o que torna a faixa segura como limite duro pro CTC.

    Com `words` (a letra), uma faixa curta só vale se a SEQUÊNCIA de palavras
    dela aparece UMA vez na letra: em linha repetida (refrão), o difflib pode
    ter casado a transcrição com a repetição errada, e a faixa inteira vira um
    limite duro no lugar errado (medido em "Nothing Else Matters": "what they
    do" casou 26 s depois do gold). Faixa de `unambiguous_run`+ palavras é
    aceita mesmo repetida.

    `anchors` é a saída de align.compute_anchors: (start, end, score, source)
    ou None por palavra.
    """
    from .align import SOURCE_ANCHOR, _normalize_word

    norm = [_normalize_word(w) for w in words] if words is not None else None

    runs: list[tuple[int, int]] = []
    n = len(anchors)
    k = 0
    while k < n:
        a = anchors[k]
        if a is None or a[3] != SOURCE_ANCHOR:
            k += 1
            continue
        j = k + 1
        while (j < n and anchors[j] is not None and anchors[j][3] == SOURCE_ANCHOR
               and anchors[j][0] >= anchors[j - 1][0]):
            j += 1
        ambiguous = (norm is not None and j - k < unambiguous_run
                     and _occurrences(norm[k:j], norm) > 1)
        if j - k >= min_run and not ambiguous:
            # descarta faixa que volta no tempo em relação à anterior aceita
            if not runs or anchors[k][0] >= anchors[runs[-1][1] - 1][1] - 0.05:
                runs.append((k, j))
        k = j
    return runs


def plan_blocks(
    n_words: int,
    runs: list[tuple[int, int]],
    anchors: list,
    audio_dur: float,
    pad: float = 0.25,
) -> list[tuple[int, int, float, float]]:
    """
    Parte a letra em blocos (i0, i1, t0, t1) que cobrem todas as palavras em
    ordem: cada faixa de âncoras duras vira um bloco com janela = o trecho que
    o Whisper mediu (+ `pad`), e cada vão entre faixas vira um bloco com
    janela = do fim da faixa anterior ao início da seguinte (ou borda do
    áudio). Cada bloco é alinhado sozinho, então um erro não atravessa uma
    faixa dura.
    """
    blocks: list[tuple[int, int, float, float]] = []
    prev_i, prev_t = 0, 0.0
    for i, j in runs:
        run_t0 = max(0.0, anchors[i][0] - pad)
        run_t1 = min(audio_dur, anchors[j - 1][1] + pad)
        if i > prev_i:
            blocks.append((prev_i, i, prev_t, max(prev_t, anchors[i][0])))
        blocks.append((i, j, run_t0, run_t1))
        prev_i, prev_t = j, anchors[j - 1][1]
    if prev_i < n_words:
        blocks.append((prev_i, n_words, prev_t, audio_dur))
    return blocks


def _align_block(emissions, frame_s, t0, t1, word_tokens, line_ends, star_id, blank, sep_id=None):
    """
    Alinha um bloco de palavras dentro de [t0, t1). Devolve (tempos por
    palavra, tempos das letras por palavra), ou None se não cabe.
    """
    targets, ranges = build_targets(word_tokens, line_ends, star_id, sep_id)
    if not ranges:
        return [], []
    f0 = max(0, int(t0 / frame_s))
    f1 = min(emissions.shape[0], int(np.ceil(t1 / frame_s)))
    if not targets:
        return [None] * len(ranges), [[] for _ in ranges]
    repeats = sum(1 for a, b in zip(targets, targets[1:]) if a == b)
    if f1 - f0 < len(targets) + repeats:
        return None
    spans = forced_align_spans(emissions[f0:f1], targets, blank=blank)
    if len(spans) != len(targets):
        return None
    shifted = [(s + f0, e + f0, sc) for s, e, sc in spans]
    return spans_to_word_times(shifted, ranges, frame_s), word_token_times(shifted, ranges, frame_s)


def align_blocks(
    emissions, frame_s: float, blocks: list[tuple[int, int, float, float]],
    word_tokens: list[list[int]], line_ends: list[bool],
    star_id: int | None, blank: int, return_tokens: bool = False, sep_id: int | None = None,
):
    """
    Alinha cada bloco na sua janela. Bloco que não cabe na janela (mais
    tokens que quadros) é fundido com o vizinho e tentado de novo - no limite
    vira o alinhamento global de antes. Com `return_tokens`, devolve também
    os tempos das letras de cada palavra (ver word_token_times).
    """
    blocks = list(blocks)
    results: list[tuple[list, list]] = []
    k = 0
    while k < len(blocks):
        i0, i1, t0, t1 = blocks[k]
        res = _align_block(emissions, frame_s, t0, t1, word_tokens[i0:i1],
                           line_ends[i0:i1], star_id, blank, sep_id)
        if res is not None:
            results.append(res)
            k += 1
            continue
        if k + 1 < len(blocks):
            n0, n1, u0, u1 = blocks[k + 1]
            blocks[k:k + 2] = [(i0, n1, t0, max(t1, u1))]
        elif k > 0:
            p0, p1, u0, u1 = blocks[k - 1]
            blocks[k - 1:k + 1] = [(p0, i1, u0, max(t1, u1))]
            results.pop()
            k -= 1
        else:
            # nem o global coube
            empty = [None] * (i1 - i0)
            return (empty, [[] for _ in empty]) if return_tokens else empty
    times = [t for r, _ in results for t in r]
    if return_tokens:
        return times, [tt for _, r in results for tt in r]
    return times


def align_lyrics_ctc(
    audio: np.ndarray,
    words: list[str],
    line_ends: list[bool],
    language: str,
    device: str = "cuda",
    use_star: bool = True,
    anchors: list | None = None,
    emissions=None,
    star_logp: float = STAR_LOGP,
    model_name: str | None = None,
    use_sep: bool = True,
) -> list[tuple[float, float, float, bool]] | None:
    """
    Alinha `words` (a letra inteira, na ordem) ao áudio vocal. Devolve um
    (start_s, end_s, score, medido) por palavra, ou None se a letra não cabe
    no vocabulário do modelo (outro alfabeto).

    Sem `anchors`: um único Viterbi global. Com `anchors` (saída de
    align.compute_anchors sobre a transcrição do Whisper): híbrido - faixas de
    âncoras exatas confiáveis viram limites duros e o CTC alinha bloco a bloco
    (ver plan_blocks). `emissions` = (tensor, frame_s) já calculado, pra
    reusar entre variantes - do MESMO modelo que `model_name` escolhe
    (get_ctc_model). `use_sep` só vale para modelo com separador de palavras.
    """
    model, dictionary = get_ctc_model(device, model_name)
    word_tokens, unmapped = tokenize_words(words, dictionary, language)
    if unmapped > MAX_UNMAPPED_FRAC:
        return None
    star_id = dictionary.get("*") if use_star else None

    em, frame_s = emissions if emissions is not None else compute_emissions(model, audio, device)
    if star_id is not None:
        em = em.clone()
        em[:, star_id] = star_logp
    audio_dur = len(audio) / SAMPLE_RATE
    runs = hard_anchor_runs(anchors, words) if anchors is not None else []
    blocks = plan_blocks(len(words), runs, anchors or [], audio_dur)
    sep_id = dictionary.get(SEP_KEY) if use_sep else None
    times = align_blocks(em, frame_s, blocks, word_tokens, line_ends, star_id, dictionary["-"],
                         sep_id=sep_id)
    if all(t is None for t in times):
        return None
    return fill_missing(times)


def snap_line_starts(
    starts: list[float], ends: list[float], line_ends: list[bool],
    onsets: np.ndarray, max_shift: float = 0.15,
) -> int:
    """
    Puxa o início da 1ª palavra de cada linha para o ataque vocal (voz depois
    de pausa, align.vocal_onsets) mais próximo, se estiver a <= `max_shift`.
    Só a 1ª palavra: dentro da frase cantada em legato não há pausa que marque
    a palavra. Muta `starts` (e `ends` se o início passar do fim). Devolve
    quantas palavras mudaram.
    """
    if len(onsets) == 0:
        return 0
    moved = 0
    for k in range(len(starts)):
        if k > 0 and not line_ends[k - 1]:
            continue
        i = int(np.searchsorted(onsets, starts[k]))
        cands = [onsets[j] for j in (i - 1, i) if 0 <= j < len(onsets)]
        best = min(cands, key=lambda o: abs(o - starts[k]))
        if abs(best - starts[k]) <= max_shift and (k == 0 or best >= ends[k - 1]):
            starts[k] = float(best)
            ends[k] = max(ends[k], starts[k] + 0.02)
            moved += 1
    return moved


def lrc_blocks(
    n_words: int,
    line_starts: list[tuple[int, float]],
    audio_dur: float,
    pad: float = 0.3,
) -> list[tuple[int, int, float, float]]:
    """
    Blocos (i0, i1, t0, t1) a partir dos inícios de linha de um .lrc APROVADO
    pelo usuário: `line_starts` = (índice da 1ª palavra da linha, tempo),
    casados via align.match_lrc_to_lines. Cada bloco vai do início de uma
    linha casada até o início da próxima (com `pad` de folga), então o CTC não
    pode tirar uma linha do lugar que o usuário conferiu de ouvido. Tempos que
    voltam no tempo são descartados.
    """
    starts: list[tuple[int, float]] = []
    for i, t in sorted(line_starts):
        if 0 < i < n_words and (not starts or t > starts[-1][1]):
            starts.append((i, t))
        elif i == 0 and not starts:
            starts.append((0, t))
    if not starts:
        return [(0, n_words, 0.0, audio_dur)]
    blocks: list[tuple[int, int, float, float]] = []
    if starts[0][0] > 0:
        blocks.append((0, starts[0][0], 0.0, starts[0][1] + pad))
    for k, (i, t) in enumerate(starts):
        nxt_i, nxt_t = starts[k + 1] if k + 1 < len(starts) else (n_words, audio_dur)
        blocks.append((i, nxt_i, max(0.0, t - pad), min(audio_dur, nxt_t + pad)))
    return blocks


def flag_low_confidence_lines(timings: list, threshold: float = LOW_LINE_SCORE) -> int:
    """
    Marca SOURCE_CTC_LOW nas palavras de linhas (pelo is_line_end) cuja média
    de score fica abaixo de `threshold`. Só mexe em palavras SOURCE_CTC.
    Devolve quantas palavras foram marcadas.
    """
    flagged = 0
    line: list = []
    for k, wt in enumerate(timings):
        line.append(wt)
        if wt.is_line_end or k == len(timings) - 1:
            ctc = [w for w in line if w.source == SOURCE_CTC]
            if ctc and sum(w.score for w in line) / len(line) < threshold:
                for w in ctc:
                    w.source = SOURCE_CTC_LOW
                    flagged += 1
            line = []
    return flagged


def low_confidence_frac(timings: list) -> float:
    """Fração das palavras em linha de confiança baixa (ou não medidas)."""
    from .align import SOURCE_INTERPOLATED
    bad = sum(1 for w in timings if w.source in (SOURCE_CTC_LOW, SOURCE_INTERPOLATED))
    return bad / max(len(timings), 1)


def verified_lrc_blocks(
    times: list[tuple[float, float, float] | None],
    lyric_lines: list[tuple[str, int]],
    lrc_lines: list[tuple[float, str]],
    n_words: int,
    audio_dur: float,
    pad: float = 1.5,
    drift_threshold: float = 2.0,
) -> list[tuple[int, int, float, float]] | None:
    """
    Para um .lrc NÃO aprovado manualmente (ex.: vindo do LRCLIB): confirma se
    os tempos do .lrc batem com o alinhamento CTC global (a menos de um
    deslocamento constante de até 15 s) em pelo menos 40% das linhas (e >= 5
    linhas). Se confirmar E alguma linha tiver derivado mais que
    `drift_threshold` s (ex.: ponte precedida de pausa instrumental em que o
    Viterbi global puxou o verso 15 s pra trás, caso real "Jimmy Eat World -
    A Praise Chorus"), devolve os blocos com `pad` folgado (1,5 s) para
    restringir as linhas desgarradas à janela certa sem engessar o resto.
    """
    from . import align as A

    if not lrc_lines or A.lrc_duration_mismatch(lrc_lines, audio_dur):
        return None
    matched = A.match_lrc_to_lines([t for t, _ in lyric_lines], lrc_lines)
    if len(matched) < A.LRC_OFFSET_MIN_LINES:
        return None

    diffs: list[float] = []
    pairs: list[tuple[int, float, float]] = []
    for li, (_, start_word) in enumerate(lyric_lines):
        t_lrc = matched.get(li)
        if t_lrc is None or start_word >= len(times):
            continue
        wt = times[start_word]
        if wt is None:
            continue
        diffs.append(wt[0] - t_lrc)
        pairs.append((start_word, wt[0], t_lrc))

    if len(diffs) < A.LRC_OFFSET_MIN_LINES:
        return None

    sorted_diffs = sorted(diffs)
    best_lo = best_hi = j = 0
    tol = 0.75
    for i in range(len(sorted_diffs)):
        while sorted_diffs[i] - sorted_diffs[j] > 2 * tol:
            j += 1
        if i - j > best_hi - best_lo:
            best_lo, best_hi = j, i
    cluster = sorted_diffs[best_lo : best_hi + 1]
    if (
        len(cluster) < A.LRC_OFFSET_MIN_LINES
        or len(cluster) / len(diffs) < A.LRC_OFFSET_MIN_AGREE_FRAC
    ):
        return None

    offset = float(np.median(cluster))
    if abs(offset) > A.LRC_OFFSET_MAX_SHIFT_S:
        return None
    if abs(offset) < A.LRC_OFFSET_MIN_SHIFT_S:
        offset = 0.0

    has_drift = any(abs(ctc_s - (t_lrc + offset)) > drift_threshold for _, ctc_s, t_lrc in pairs)
    if not has_drift:
        return None

    starts = [(lyric_lines[li][1], max(0.0, t + offset)) for li, t in matched.items()]
    return lrc_blocks(n_words, starts, audio_dur, pad=pad)


def align_lyrics_ctc_to_audio(
    vocals_wav: Path,
    lyrics_path: Path,
    language: str,
    device: str = "cuda",
    synced_lyrics_path: Path | None = None,
):
    """
    Ponto de entrada do app (main.py, Etapa 4): list[WordTiming] alinhada por
    CTC global, com linhas de confiança baixa marcadas SOURCE_CTC_LOW. None se
    a letra não cabe no vocabulário do modelo (outro alfabeto) - o chamador
    cai no align.align_lyrics_to_audio de sempre.

    Um .lrc APROVADO pelo usuário ([uskmapproved:1]) define os blocos direto
    (pad curto de 0,3 s). Um .lrc não aprovado (LRCLIB) passa primeiro pelo
    alinhamento global e só vira blocos (pad folgado de 1,5 s) se concordar com
    a gravação e houver linha desgarrada (> 2 s de desvio, ex.: ponte após
    pausa instrumental).
    """
    import whisperx

    from . import align as A
    from .i18n import t as _t

    audio = whisperx.load_audio(str(vocals_wav))
    words, line_ends, singers = A._load_lyrics_words_with_line_ends(lyrics_path)
    if not words:
        return None
    model, dictionary = ctc_model_for(language, device)
    word_tokens, unmapped = tokenize_words(words, dictionary, language)
    if unmapped > MAX_UNMAPPED_FRAC:
        return None
    star_id = dictionary["*"]
    audio_dur = len(audio) / SAMPLE_RATE

    blocks = [(0, len(words), 0.0, audio_dur)]
    lrc_text = None
    approved_lrc = False
    if synced_lyrics_path is not None and Path(synced_lyrics_path).exists():
        lrc_text = Path(synced_lyrics_path).read_text(encoding="utf-8")
        if A.lrc_is_approved(lrc_text):
            approved_lrc = True
            lyric_lines = A._lyric_lines_with_start_index(lyrics_path)
            matched = A.match_lrc_to_lines([t for t, _ in lyric_lines], A.parse_lrc(lrc_text))
            starts = [(lyric_lines[li][1], t) for li, t in matched.items()]
            blocks = lrc_blocks(len(words), starts, audio_dur)
            print(_t("align.ctc_lrc_blocks", n=len(starts)))

    em, frame_s = compute_emissions(model, audio, device)
    em[:, star_id] = STAR_LOGP
    times, token_times = align_blocks(em, frame_s, blocks, word_tokens, line_ends, star_id,
                                      dictionary["-"], return_tokens=True,
                                      sep_id=dictionary.get(SEP_KEY))
    if lrc_text and not approved_lrc and not all(t is None for t in times):
        lyric_lines = A._lyric_lines_with_start_index(lyrics_path)
        rescued_blocks = verified_lrc_blocks(
            times, lyric_lines, A.parse_lrc(lrc_text), len(words), audio_dur
        )
        if rescued_blocks is not None:
            print(_t("align.ctc_lrc_blocks", n=len(rescued_blocks)))
            times, token_times = align_blocks(
                em, frame_s, rescued_blocks, word_tokens, line_ends, star_id,
                dictionary["-"], return_tokens=True,
                sep_id=dictionary.get(SEP_KEY),
            )
    if all(t is None for t in times):
        return None
    timings = to_word_timings(words, line_ends, singers, fill_missing(times))
    attach_syllable_starts(timings, token_times, dictionary, language)
    flag_low_confidence_lines(timings)
    return timings


def attach_syllable_starts(timings: list, token_times: list, dictionary: dict[str, int],
                           language: str) -> int:
    """
    Preenche WordTiming.syllable_starts a partir das letras alinhadas, com a
    MESMA divisão silábica do build_song (split_word_syllables sem as sílabas
    só de pontuação). Devolve quantas palavras receberam.
    """
    from .syllabify import split_word_syllables

    n = 0
    for wt, tt in zip(timings, token_times):
        syls = [x for x in split_word_syllables(wt.word, language) if any(c.isalnum() for c in x)]
        wt.syllable_starts = syllable_starts(syls, tt, dictionary, language) if tt else None
        n += wt.syllable_starts is not None
    return n


def to_word_timings(words, line_ends, singers, res):
    from .align import WordTiming, SOURCE_INTERPOLATED
    return [
        WordTiming(word=w, start=s, end=e, score=sc, is_line_end=le, anchored=m,
                   source=SOURCE_CTC if m else SOURCE_INTERPOLATED, singer=sg)
        for w, (s, e, sc, m), le, sg in zip(words, res, line_ends, singers)
    ]


def align_file(vocals_wav: Path, lyrics_path: Path, language: str, device: str = "cuda",
               use_star: bool = True):
    """Atalho: carrega áudio + letra e devolve list[WordTiming] (ou None)."""
    import whisperx

    from .align import _load_lyrics_words_with_line_ends

    audio = whisperx.load_audio(str(vocals_wav))
    words, line_ends, singers = _load_lyrics_words_with_line_ends(lyrics_path)
    res = align_lyrics_ctc(audio, words, line_ends, language, device, use_star)
    return None if res is None else to_word_timings(words, line_ends, singers, res)

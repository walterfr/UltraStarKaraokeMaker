# -*- coding: utf-8 -*-
"""Stage-level eval harness: score USKMaker's pipeline stages *independently*
against gold hand-charted UltraStar songs from a local library, instead of only
comparing final output (that's eval/evaluate.py's job).

Ported from usdx-autochart (MIT, Alejololer/usdx-autochart) with the stages
swapped for USKMaker's own (python-sidecar/pipeline/):

  align : align.align_lyrics_to_audio on the cached Demucs vocal stem, with
          lyrics extracted from the gold chart -> word recall + onset/end error
          vs the gold word times, plus the interpolated-word fraction and
          whether the lead-vocal rescue (main.py "Etapa 4b") fired/won -
          the background-choir failure detector.
  pitch : SwiftF0 voiced-median MIDI inside *gold* note boundaries vs gold
          pitch, relative (medians subtracted): within-2-semitones rate +
          contour correlation - isolates pitch error from timing error.
  bpm   : beatgrid.detect_bpm (on the instrumental stem, like main.py) vs the
          gold #BPM header, mod power-of-two multiple.

Stages usdx-autochart replays that USKMaker doesn't have (MMS_FA forced
alignment, syllabify_es proportional spread) are deliberately dropped.

Resumable: the run dir is keyed by n+seed (or the seed set); songs with an
existing result/error JSON are skipped. Demucs stems, alignment, and pitch are
cached per song under <run_dir>/cache/<slug>/ - Demucs is nondeterministic
(randomized shifts), so FIXED stems are what make A/B comparisons between code
versions meaningful. Gold onsets are themselves ~50 ms-grid quantized and
stylistic - differences below ~25-50 ms are noise, not signal.

  python eval/library_replay.py --n 20 --seed 0
  python eval/library_replay.py --seed-set eval/seed_set.json
  python eval/library_replay.py --n 20 --seed 0 --aggregate-only
"""
from __future__ import annotations

import argparse
import csv
import difflib
import json
import math
import os
import random
import re
import shutil
import statistics
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[0]))  # python-sidecar root, for `pipeline`
sys.path.insert(0, str(_HERE))             # eval dir, for sibling usdx_parse

import usdx_parse  # noqa: E402


# gold-chart #LANGUAGE header -> whisper language code; unmapped -> song skipped
LANG_CODES = {
    "spanish": "es", "español": "es", "espanol": "es",
    "english": "en", "french": "fr", "français": "fr", "german": "de",
    "deutsch": "de", "italian": "it", "portuguese": "pt", "português": "pt",
    "japanese": "ja", "korean": "ko", "chinese": "zh",
    "catalan": "ca", "catalán": "ca", "gallego": "gl",
    "dutch": "nl", "swedish": "sv", "finnish": "fi", "russian": "ru",
    "polish": "pl", "turkish": "tr", "latin": "la",
}

# Códigos ISO-639-1 que o whisper aceita direto. Charts reais escrevem o
# #LANGUAGE dos dois jeitos - o nome por extenso E o código.
_ISO_CODES = frozenset(LANG_CODES.values())


def normalize_language(raw: str | None) -> str | None:
    """
    #LANGUAGE do chart -> código do whisper, ou None se não der pra saber.

    O header é texto livre, e o que os charts REAIS trazem (medido numa
    biblioteca de 1439 músicas do USDB) não é só "Portuguese":

        'pt'                   70   <- código ISO, não nome
        'Portuguese (Brazil)'  22   <- qualificador entre parênteses
        'Japanese (romanized)'  3   <- idem
        'English, French'       2   <- multi-valor

    Um mapa exato de nomes descartava tudo isso em silêncio (a música só
    "falhava"), e o pior é que 'pt' era o caso MAIS comum depois do inglês -
    justo o idioma que mais nos interessa medir.
    """
    if not raw:
        return None
    value = raw.strip().lower()
    if not value:
        return None
    # 'English, French' / 'English/French' -> o primeiro; medir no idioma
    # principal é melhor que descartar a música
    value = re.split(r"[,/;]", value)[0].strip()
    # 'Portuguese (Brazil)' -> 'portuguese'
    value = re.sub(r"\s*\([^)]*\)", "", value).strip()
    if value in LANG_CODES:
        return LANG_CODES[value]
    if value in _ISO_CODES:
        return value
    return None


# O console do Windows decodifica em cp1252, e nomes de música/mensagens de
# erro trazem caractere que não cabe lá (apóstrofo tipográfico, acento, CJK,
# ou o próprio U+FFFD de um chart já corrompido na origem). Sem isto, o print
# levanta UnicodeEncodeError - e o pior é ONDE isso acontece: no log do
# except, MASCARANDO o erro de verdade com um erro de codificação. Aconteceu
# de verdade rodando a biblioteca real (16/07/2026). Mesmo fix do main.py.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def log(msg: str) -> None:
    print(f"[replay] {msg}", flush=True)


class UnmeasurableSong(Exception):
    """
    A música não dá pra medir, e a culpa NÃO é do pipeline.

    Existe pra separar duas coisas que o harness misturava: "o USKMaker errou"
    de "esta entrada da biblioteca está torta". Sem essa distinção, o agregado
    culpa o pipeline por dado ruim - e foi exatamente o que aconteceu na
    primeira rodada real (ver os detectores abaixo).
    """


# Idiomas cuja escrita NÃO é latina. Se a letra do chart vem em alfabeto
# latino nesses idiomas, ela está romanizada.
_NON_LATIN_SCRIPT = frozenset({"ja", "ko", "zh", "ru"})


def is_romanized_chart(language: str, gwords: list[dict]) -> bool:
    """
    Chart de idioma de escrita não-latina com a letra em ROMAJI/romanização.

    CASO REAL ("Abingdon boys school - Innocent sorrow (TV)"): o chart diz
    #LANGUAGE:Japanese, mas a letra é "Sake ta mune no kizuguchi ni". Mandamos
    language='ja' pro whisper, que transcreve em kana/kanji - zero caractere em
    comum com o alfabeto latino, nenhuma âncora possível. Resultado: w_1s
    0.000, onset 35 s, 89% interpoladas - como se o pipeline tivesse falhado,
    quando o que está errado é a premissa.

    Romanizar chart ja/ko é convenção da comunidade (é o que dá pra cantar),
    então isto não é raro. Medir esses charts exigiria transliterar a saída do
    whisper - até lá, pular com o motivo explícito é mais honesto que reportar
    zero.
    """
    if language not in _NON_LATIN_SCRIPT:
        return False
    texto = "".join(w["text"] for w in gwords[:40])
    letras = [c for c in texto if c.isalpha()]
    if not letras:
        return False
    latinas = sum(1 for c in letras if ord(c) < 0x250)  # latim + latim estendido
    return latinas / len(letras) > 0.8


def audio_chart_mismatch(audio_path: str, chart) -> str | None:
    """
    Devolve o motivo se o áudio claramente não é a versão que o chart mede.

    O critério é o CONCLUSIVO: se o chart tem nota depois do fim do áudio, ele
    não cabe - é outra edição da música, ponto. (Um áudio mais LONGO que o
    chart é normal: outro, aplausos, fade.)

    CASO REAL: "RuPaul - Supermodel" tem chart até 270,4 s e áudio de 248,5 s;
    o harness pontuava onset de 50 s como se fosse erro nosso. A biblioteca do
    usdb_syncer pega o áudio do YouTube, e o vídeo pode ser uma edição
    diferente da que o charter cronometrou.

    Não conclui nada quando não dá pra ler a duração - na dúvida, mede.
    """
    try:
        fim_chart = chart.beat_to_time(
            max(n.start_beat + n.duration for line in chart.lines for n in line.notes)
        )
    except ValueError:
        return None
    dur = _audio_duration(audio_path)
    if dur is None:
        return None
    # tolerância: o chart pode legitimamente terminar em cima do fim do áudio
    if fim_chart > dur + 2.0:
        return (
            f"áudio não bate com o chart: o chart vai até {fim_chart:.1f}s mas o "
            f"áudio tem {dur:.1f}s - é outra versão da música"
        )
    return None


def _audio_duration(path: str) -> float | None:
    """Duração em segundos via ffprobe; None se não der pra saber."""
    import subprocess

    from pipeline.proc_utils import ffmpeg_exe

    ffprobe = ffmpeg_exe().replace("ffmpeg", "ffprobe")
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=60,
        )
        if out.returncode != 0:
            return None
        return float(out.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def offset_data_mismatch(gold: list[dict], hyp: list[dict],
                         pairs: list[tuple[int, int]], *, min_pairs: int = 30,
                         raw_ceiling: float = 0.5,
                         fit_floor: float = 0.85) -> str | None:
    """
    Detecta o caso "áudio deslocado": o alinhamento está internamente CERTO,
    mas o áudio baixado tem outro silêncio inicial (ou anda em velocidade um
    pouco diferente) do que o charter cronometrou. Aí TODO onset erra pelo
    mesmo offset e o w_1s desaba - sem o pipeline ter errado nada.

    CASO REAL (n=60): Paul McCartney, Queen e Aerosmith pontuavam onset de
    ~67 s como falha nossa; medindo, nosso ≈ 1,00*gold + 67 s - offset
    CONSTANTE. O portão de duração (audio_chart_mismatch) não pega: a duração
    total bate, o que difere é o offset INTERNO.

    Devolve o motivo (string) se for deslocamento de dado; None se não.
    Só dispara quando: (a) o w_1s CRU é ruim (< raw_ceiling) - senão mede-se
    normal, não há offset a remover; (b) um ajuste linear h≈a*g+b, com a perto
    de 1, deixa >= fit_floor das palavras dentro de 1 s; (c) o ajuste MELHORA
    muito sobre o cru. Alinhamento genuinamente quebrado (Whisper errou a
    letra) é uma nuvem espalhada - nenhuma reta a encaixa em 1 s -> não
    dispara, e continua contando como falha nossa, que é o certo.
    """
    if len(pairs) < min_pairs:
        return None
    g = [gold[i]["start"] for i, _ in pairs]
    h = [hyp[j]["start"] for _, j in pairs]
    n = len(g)
    raw_within = sum(1 for gi, hi in zip(g, h) if abs(hi - gi) <= 1.0) / n
    if raw_within >= raw_ceiling:
        return None  # já mede bem - não há deslocamento sistemático a remover
    import numpy as np
    a, b = (float(x) for x in np.polyfit(g, h, 1))
    if not 0.85 <= a <= 1.18:
        return None  # velocidade absurda: não é a mesma performance
    resid = [hi - (a * gi + b) for gi, hi in zip(g, h)]
    fit_within = sum(1 for r in resid if abs(r) <= 1.0) / n
    if fit_within < fit_floor or (fit_within - raw_within) < 0.3:
        return None
    return (f"áudio deslocado do chart: removendo um offset linear "
            f"(nosso ≈ {a:.2f}*gold {b:+.1f}s), {100 * fit_within:.0f}% das "
            f"palavras caem em 1 s (cru: {100 * raw_within:.0f}%) - é outra "
            f"edição/velocidade do áudio, não erro de alinhamento")


def slugify(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")[:80]


# Extensões de áudio que o ffmpeg (e portanto demucs/librosa) lê sem drama.
# NÃO é "o que o UltraStar aceita" - é o que ESTE harness consegue processar.
_AUDIO_EXTS = (".mp3", ".m4a", ".ogg", ".opus", ".wav", ".flac", ".aac", ".webm")

# Sufixos de faixa separada (convenção usdb_syncer/nossa): NUNCA são o áudio
# principal da música. Sem isto, uma pasta sincronizada com separação ligada
# tem 3 áudios e o harness ou desiste dela ou escolhe o errado.
_STEM_SUFFIXES = ("[voc]", "[instr]")


def _pick_audio(dir_path: str, files: list[str], gold_path: str) -> str | None:
    """
    Descobre qual arquivo é o áudio da música.

    Ordem: o que o PRÓPRIO CHART declara (#AUDIO/#MP3) -> heurística de um
    único áudio na pasta. Perguntar ao chart não é refinamento, é o certo: ele
    é a fonte da verdade sobre o próprio pacote, e evita as duas armadilhas de
    adivinhar por extensão:
      - o usdb_syncer baixa em M4A por PADRÃO (não mp3), então exigir .mp3
        descartava silenciosamente uma biblioteca inteira baixada com os
        defaults;
      - com separação de faixas ligada (lá e aqui) a pasta tem 3 áudios, e
        "exatamente um" nunca bate.
    """
    try:
        declared = usdx_parse.read_file(gold_path).audio.strip()
    except Exception:
        declared = ""
    if declared:
        # o header é um nome relativo à pasta da música (spec, seção 3.2)
        cand = os.path.join(dir_path, declared)
        if os.path.isfile(cand):
            return cand
        # o chart pode citar um nome que não veio junto (áudio não baixado, ou
        # renomeado): cai pra heurística em vez de desistir
    audios = [
        f for f in files
        if f.lower().endswith(_AUDIO_EXTS)
        and not any(s in f.lower() for s in _STEM_SUFFIXES)
    ]
    if len(audios) == 1:
        return os.path.join(dir_path, audios[0])
    return None


def scan_library(lib: str) -> list[dict]:
    """
    Pastas com um gold .txt (não-MULTI) e um áudio identificável.

    O áudio sai do header #AUDIO/#MP3 do próprio chart (ver _pick_audio); a
    chave do dict continua "mp3" por compatibilidade com o resto do módulo,
    mas o arquivo pode ser qualquer formato que o ffmpeg leia.
    """
    songs = []
    for name in sorted(os.listdir(lib)):
        d = os.path.join(lib, name)
        if not os.path.isdir(d):
            continue
        try:
            files = os.listdir(d)
        except OSError:
            continue
        txts = [f for f in files if f.lower().endswith(".txt")]
        golds = [f for f in txts if "[multi]" not in f.lower()]
        if not golds:
            continue
        gold = os.path.join(d, sorted(golds, key=len)[0])
        audio = _pick_audio(d, files, gold)
        if not audio:
            continue
        songs.append({"name": name, "mp3": audio, "gold": gold})
    return songs


# ---------- gold chart -> time-domain events ----------

def _key(word: str) -> str:
    w = unicodedata.normalize("NFKD", word.lower())
    w = "".join(c for c in w if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", w)


def gold_words(chart) -> list[dict]:
    """Time-domain words from a parsed gold chart. A note is a syllable; a new
    word starts at a line break, after a note with trailing space, or on a note
    with leading space. '~'/empty notes are holds extending the previous
    syllable. Each word: {text, start, end, line_index}."""
    words: list[dict] = []
    for li, line in enumerate(chart.lines):
        word = None
        prev_trail = False
        for n in line.notes:
            raw, txt = n.text, n.text.strip()
            s = chart.beat_to_time(n.start_beat)
            e = chart.beat_to_time(n.start_beat + n.duration)
            if txt in ("~", ""):  # hold continuation
                if word:
                    word["end"] = max(word["end"], e)
                if raw:
                    prev_trail = raw[-1:].isspace()
                continue
            if word is None or prev_trail or raw[:1].isspace():
                if word:
                    words.append(word)
                word = {"text": txt, "start": s, "end": e, "line_index": li}
            else:
                word["text"] += txt
                word["end"] = max(word["end"], e)
            prev_trail = raw[-1:].isspace() if raw else False
        if word:
            words.append(word)
    return words


def gold_notes(chart) -> list[tuple]:
    """Pitched notes as (start_s, end_s, pitch); freestyle/rap carry no pitch."""
    out = []
    for line in chart.lines:
        for n in line.notes:
            if n.kind in ("normal", "golden"):
                out.append((chart.beat_to_time(n.start_beat),
                            chart.beat_to_time(n.start_beat + n.duration),
                            n.pitch))
    return out


def gold_lyrics_text(gwords: list[dict]) -> str:
    """Plain lyrics (one line per gold chart line) - align.py's input format."""
    by_line: dict[int, list[str]] = defaultdict(list)
    for w in gwords:
        by_line[w["line_index"]].append(w["text"])
    return "\n".join(" ".join(by_line[li]) for li in sorted(by_line)) + "\n"


# ---------- matching + metrics ----------

def match_words(gold: list[dict], hyp: list[dict]) -> list[tuple[int, int]]:
    """Text-match gold<->hypothesis words (difflib on normalized keys).
    Returns (gold_idx, hyp_idx) pairs."""
    ga = [(i, _key(w["text"])) for i, w in enumerate(gold)]
    ha = [(j, _key(w["text"])) for j, w in enumerate(hyp)]
    ga = [(i, k) for i, k in ga if k]
    ha = [(j, k) for j, k in ha if k]
    sm = difflib.SequenceMatcher(a=[k for _, k in ga], b=[k for _, k in ha],
                                 autojunk=False)
    pairs = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag not in ("equal", "replace"):
            continue
        for k in range(min(i2 - i1, j2 - j1)):
            if tag == "replace" and difflib.SequenceMatcher(
                    a=ga[i1 + k][1], b=ha[j1 + k][1]).ratio() < 0.5:
                continue
            pairs.append((ga[i1 + k][0], ha[j1 + k][0]))
    return pairs


def _err_stats(errs: list[float]) -> dict | None:
    if not errs:
        return None
    a = sorted(abs(x) for x in errs)
    return {"n": len(a),
            "median_ms": round(a[len(a) // 2] * 1000, 1),
            "mae_ms": round(sum(a) / len(a) * 1000, 1),
            "p90_ms": round(a[int(0.9 * (len(a) - 1))] * 1000, 1),
            "bias_ms": round(statistics.median(errs) * 1000, 1)}


def timing_stats(gold: list[dict], hyp: list[dict],
                 pairs: list[tuple[int, int]]) -> dict:
    onset = [hyp[j]["start"] - gold[i]["start"] for i, j in pairs]
    end = [hyp[j]["end"] - gold[i]["end"] for i, j in pairs]
    # within_1s is the headline number from previous manual validations
    # (~65-90% is the normal band on good songs). recall is ~1 by
    # construction here (align_lyrics_to_audio emits one timing per lyric
    # word) - it only drops when _key() filters out unmatchable tokens.
    within_1s = (round(sum(1 for x in onset if abs(x) <= 1.0) / len(onset), 3)
                 if onset else 0.0)
    return {"recall": round(len(pairs) / len(gold), 3) if gold else 0.0,
            "within_1s": within_1s,
            "onset": _err_stats(onset), "end": _err_stats(end)}


def pitch_metrics(notes: list[tuple], times, hz, voicing) -> dict:
    """
    SwiftF0 voiced-median MIDI inside *gold* note boundaries vs gold pitch
    (relative, medians subtracted).

    Reporta DUAS taxas de acerto, e a diferença entre elas importa:

    - `within_2st`: comparação absoluta (a de sempre).
    - `within_2st_mod12`: distância CIRCULAR de 12 semitons, que é como o
      jogo compara. A spec v1 é explícita: "Game implementations MAY decide to
      compare pitches independently of the octave (i.e. compare pitches
      modulo 12)". Ou seja, a OITAVA ABSOLUTA DO GOLD NÃO É VERDADE
      FUNDAMENTAL - o charter escreve a oitava que quiser porque o jogo não
      liga, e punir nossa medição por discordar dela mede a preferência dele,
      não a nossa qualidade.

    MEDIDO (Shakira - Estoy aquí): o erro cru se agrupa em múltiplos exatos de
    oitava (64 notas em -12, 54 em -24) - o contorno bate, a oitava não.
    within_2st 0.181 -> 0.430 no mod12.

    Na mediana das 20 músicas o efeito é pequeno (0.878 -> 0.895), então isto
    NÃO é desculpa geral: "Nelly Furtado - Maneater" fica em 0.025 mesmo
    mod12, e continua sem explicação (ver issue #7).
    """
    gold_p, est_m = [], []
    for s, e, p in notes:
        mask = (times >= s) & (times < e) & voicing & (hz > 0)
        if mask.sum() < 2:
            continue
        est_m.append(69.0 + 12.0 * math.log2(float(np.median(hz[mask])) / 440.0))
        gold_p.append(p)
    out = {"n_notes": len(notes), "n_scored": len(gold_p),
           "coverage": round(len(gold_p) / len(notes), 3) if notes else 0.0}
    if len(gold_p) >= 10:
        g = np.array(gold_p, float)
        c = np.array(est_m, float)
        g -= np.median(g)
        c -= np.median(c)
        out["within_2st"] = round(float(np.mean(np.abs(g - c) <= 2)), 3)
        # distância circular em 12 semitons = como o jogo compara (ver docstring)
        d = np.abs(c - g) % 12.0
        d = np.minimum(d, 12.0 - d)
        out["within_2st_mod12"] = round(float(np.mean(d <= 2)), 3)
        out["contour_corr"] = (round(float(np.corrcoef(g, c)[0, 1]), 3)
                               if g.std() and c.std() else 0.0)
    return out


def bpm_metric(est: float | None, file_bpm: float) -> dict | None:
    """Deviation of the estimate from the gold #BPM, mod power-of-two multiple
    (gold file BPMs are often the musical BPM x2/x4 for grid fineness)."""
    if not est or est <= 0 or not file_bpm:
        return None
    k = file_bpm / est
    p = 2.0 ** round(math.log2(k))
    return {"est": round(est, 1), "file_bpm": file_bpm, "mult": p,
            "dev": round(abs(k / p - 1), 4)}


# ---------- per-song run (cached, resumable) ----------

def _cached_stems(mp3: str, cache: Path, device: str) -> tuple[Path, Path]:
    """Demucs stems, separated once and cached: nondeterministic between runs,
    so a fixed stem is what makes cross-run comparisons meaningful."""
    vocals = cache / "vocals.wav"
    instrumental = cache / "no_vocals.wav"
    if vocals.exists() and instrumental.exists():
        return vocals, instrumental
    from pipeline.separate import separate_vocals
    log("  demucs...")
    tmp = cache / "demucs_tmp"
    stems = separate_vocals(Path(mp3), tmp, device=device)
    shutil.move(str(stems.vocals), str(vocals))
    shutil.move(str(stems.instrumental), str(instrumental))
    shutil.rmtree(tmp, ignore_errors=True)
    return vocals, instrumental


def _timings_to_dicts(timings) -> list[dict]:
    return [{"text": t.word, "start": t.start, "end": t.end,
             "source": t.source, "score": t.score} for t in timings]


def _cached_alignment(stem: Path, cache: Path, gwords: list[dict],
                      language: str, device: str) -> dict:
    """align.align_lyrics_to_audio on the cached stem, mirroring main.py's
    Etapa 4b rescue: if >10% of words end up interpolated, isolate the lead
    vocal and re-align, keeping whichever result has fewer interpolated words
    (the pipeline's internal quality signal - no ground truth needed)."""
    aj = cache / "align.json"
    if aj.exists():
        with open(aj, encoding="utf-8") as f:
            return json.load(f)

    from pipeline.align import align_lyrics_to_audio, alignment_stats

    lyrics_path = cache / "lyrics.txt"
    lyrics_path.write_text(gold_lyrics_text(gwords), encoding="utf-8")

    log(f"  align (whisperx, lang={language})...")
    timings = align_lyrics_to_audio(stem, lyrics_path, language=language,
                                    device=device)
    interp = alignment_stats(timings)["by_source"]["interpolated"]
    interp_frac = interp / max(len(timings), 1)

    rescue = {"tried": False, "won": False, "base_interp_frac": round(interp_frac, 3)}
    if interp_frac > 0.10:
        rescue["tried"] = True
        log(f"  rescue: {100 * interp_frac:.0f}% interpolated, isolating lead vocal...")
        try:
            from pipeline.separate import isolate_lead_vocal
            lead = cache / "lead_vocals.wav"
            if not lead.exists():
                lead = isolate_lead_vocal(stem, cache)
            retry = align_lyrics_to_audio(lead, lyrics_path, language=language,
                                          device=device)
            retry_interp = alignment_stats(retry)["by_source"]["interpolated"]
            rescue["lead_interp_frac"] = round(retry_interp / max(len(retry), 1), 3)
            if retry_interp < interp:
                rescue["won"] = True
                timings = retry
        except Exception as e:  # noqa: BLE001 - non-fatal, same as main.py
            rescue["error"] = repr(e)
            log(f"  rescue failed (non-fatal): {e!r}")

    stats = alignment_stats(timings)
    result = {"words": _timings_to_dicts(timings),
              "interp_frac": round(stats["by_source"]["interpolated"]
                                   / max(stats["total"], 1), 3),
              "rescue": rescue}
    with open(aj, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    return result


def _cached_pitch(stem: Path, cache: Path):
    pz = cache / "pitch.npz"
    if pz.exists():
        d = np.load(pz)
        return d["t"], d["hz"], d["voicing"].astype(bool)
    import soundfile as sf
    from pipeline.pitch import PitchExtractor
    log("  pitch (SwiftF0)...")
    duration = sf.info(str(stem)).duration
    track = PitchExtractor().extract_word_track(str(stem), 0.0, duration)
    np.savez_compressed(pz, t=track.timestamps, hz=track.pitch_hz,
                        voicing=track.voicing)
    return track.timestamps, track.pitch_hz, track.voicing


def _run_song(song: dict, run_dir: str, slug: str, device: str) -> dict:
    chart = usdx_parse.read_file(song["gold"])
    gwords = gold_words(chart)
    if len(gwords) < 30:
        raise ValueError(f"only {len(gwords)} gold words")
    language = normalize_language(chart.language)
    if not language:
        raise ValueError(f"unmapped gold #LANGUAGE {chart.language!r}")
    if is_romanized_chart(language, gwords):
        raise UnmeasurableSong(
            f"chart romanizado: #LANGUAGE={chart.language!r} mas a letra está em "
            f"alfabeto latino - o whisper transcreveria em outro sistema de escrita"
        )
    audio_problem = audio_chart_mismatch(song["mp3"], chart)
    if audio_problem:
        raise UnmeasurableSong(audio_problem)
    notes = gold_notes(chart)
    cache = Path(run_dir) / "cache" / slug
    cache.mkdir(parents=True, exist_ok=True)

    vocals, instrumental = _cached_stems(song["mp3"], cache, device)
    align_res = _cached_alignment(vocals, cache, gwords, language, device)
    times, hz, voicing = _cached_pitch(vocals, cache)

    try:
        from pipeline.beatgrid import detect_bpm
        bpm_est = detect_bpm(instrumental).bpm
    except Exception:  # noqa: BLE001 - informational metric
        bpm_est = None

    span = gwords[-1]["end"] - gwords[0]["start"]
    hyp = align_res["words"]
    pairs = match_words(gwords, hyp)
    offset_problem = offset_data_mismatch(gwords, hyp, pairs)
    if offset_problem:
        raise UnmeasurableSong(offset_problem)
    return {
        "song": song["name"],
        "lang_group": song.get("lang_group"),
        "wpm": round(len(gwords) / (span / 60), 1) if span > 0 else None,
        "n_gold_words": len(gwords),
        "align": {"n_words": len(hyp),
                  "interp_frac": align_res["interp_frac"],
                  "rescue": align_res["rescue"],
                  **timing_stats(gwords, hyp, pairs)},
        "pitch": pitch_metrics(notes, times, hz, voicing),
        "bpm": bpm_metric(bpm_est, chart.bpm),
    }


def run_song(song: dict, run_dir: str, device: str) -> None:
    slug = slugify(song["name"])
    rj = os.path.join(run_dir, "results", f"{slug}.json")
    ej = os.path.join(run_dir, "results", f"{slug}.error.json")
    if os.path.exists(rj) or os.path.exists(ej):
        log(f"[skip] {song['name']} (already done)")
        return
    log(f"[run ] {song['name']}")
    try:
        res = _run_song(song, run_dir, slug, device)
        with open(rj, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1, default=float)
    except UnmeasurableSong as e:
        # NÃO é falha do pipeline: a entrada da biblioteca é que não permite
        # medir. Fica marcado no .error.json pra não sumir do relatório nem
        # ser confundido com erro nosso.
        log(f"       PULADA (dado, não pipeline): {e}")
        with open(ej, "w", encoding="utf-8") as f:
            json.dump({"error": str(e), "unmeasurable": True}, f, ensure_ascii=False)
    except Exception as e:  # noqa: BLE001 - one bad song must not kill the run
        log(f"       FAILED: {e!r}")
        with open(ej, "w", encoding="utf-8") as f:
            json.dump({"error": repr(e)}, f, ensure_ascii=False)
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass


# ---------- sampling ----------

def build_manifest(lib: str, runs_root: str) -> list[dict]:
    """Usable songs with lang_group + gold wpm; cached (one full-library parse)."""
    os.makedirs(runs_root, exist_ok=True)
    path = os.path.join(runs_root, "library_manifest.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
        if m.get("lib") == lib:
            return m["songs"]
    songs = scan_library(lib)
    out = []
    for i, s in enumerate(songs):
        if i and i % 1000 == 0:
            log(f"scanning gold charts {i}/{len(songs)}...")
        try:
            if usdx_parse.is_relative(s["gold"]):
                continue
            chart = usdx_parse.read_file(s["gold"])
            gw = gold_words(chart)
            if len(gw) < 30:
                continue
            span = gw[-1]["end"] - gw[0]["start"]
            if span < 60:
                continue
            code = LANG_CODES.get((chart.language or "").strip().lower(), "other")
            out.append({"name": s["name"], "mp3": s["mp3"], "gold": s["gold"],
                        "lang_group": code if code in ("es", "en") else "other",
                        "wpm": round(len(gw) / (span / 60), 1)})
        except Exception:  # noqa: BLE001 - unparseable gold: not usable
            continue
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"lib": lib, "songs": out}, f, ensure_ascii=False)
    log(f"manifest: {len(out)} usable songs (cached at {path})")
    return out


def stratified_sample(manifest: list[dict], n: int, seed: int):
    """Proportional allocation over lang_group x wpm tercile, seeded."""
    wpms = sorted(s["wpm"] for s in manifest)
    t1, t2 = wpms[len(wpms) // 3], wpms[2 * len(wpms) // 3]

    def terc(w):
        return 0 if w < t1 else (1 if w < t2 else 2)

    strata: dict[tuple, list] = defaultdict(list)
    for s in manifest:
        strata[(s["lang_group"], terc(s["wpm"]))].append(s)
    keys = sorted(strata)
    total = len(manifest)
    alloc = {k: max(1, round(n * len(strata[k]) / total)) for k in keys}
    while sum(alloc.values()) > n:
        k = max(keys, key=lambda k: alloc[k])
        alloc[k] -= 1
    while sum(alloc.values()) < n:
        k = max(keys, key=lambda k: len(strata[k]) - alloc[k])
        alloc[k] += 1
    rng = random.Random(seed)
    sample = []
    for k in keys:
        sample.extend(rng.sample(strata[k], min(alloc[k], len(strata[k]))))
    return sample, (t1, t2)


def seed_set_sample(seed_set_path: str, manifest: list[dict]) -> list[dict]:
    """The curated seed set (eval/seed_set.json): songs referenced by library
    folder name - each dev supplies audio + gold .txt locally; nothing
    copyrighted lives in the repo."""
    with open(seed_set_path, encoding="utf-8") as f:
        seed_set = json.load(f)
    by_name = {s["name"]: s for s in manifest}
    sample = []
    for entry in seed_set["songs"]:
        s = by_name.get(entry["folder"])
        if s:
            sample.append(s)
        else:
            log(f"[miss] seed-set song not in library (or unusable): {entry['folder']}")
    return sample


# ---------- aggregation ----------

FLAT_FIELDS = ["song", "lang_group", "wpm", "n_gold_words",
               "recall", "within_1s", "onset_med_ms", "onset_mae_ms",
               "onset_p90_ms", "bias_ms", "end_med_ms", "interp_frac",
               "rescue_tried", "rescue_won",
               "pitch_coverage", "pitch_within_2st", "pitch_within_2st_mod12",
               "pitch_corr",
               "bpm_est", "bpm_mult", "bpm_dev", "error",
               # True = a música foi pulada por problema de DADO (chart
               # romanizado, áudio de outra versão), não por erro do pipeline.
               "unmeasurable"]

KEY_METRICS = ["within_1s", "onset_med_ms", "interp_frac",
               "pitch_within_2st", "pitch_within_2st_mod12", "pitch_corr", "bpm_dev"]


def _flat(r: dict) -> dict:
    a = r.get("align") or {}
    ao = a.get("onset") or {}
    ae = a.get("end") or {}
    resc = a.get("rescue") or {}
    pi, bp = r.get("pitch") or {}, r.get("bpm") or {}
    return {
        "n_gold_words": r.get("n_gold_words"),
        "recall": a.get("recall"), "within_1s": a.get("within_1s"),
        "onset_med_ms": ao.get("median_ms"),
        "onset_mae_ms": ao.get("mae_ms"), "onset_p90_ms": ao.get("p90_ms"),
        "bias_ms": ao.get("bias_ms"), "end_med_ms": ae.get("median_ms"),
        "interp_frac": a.get("interp_frac"),
        "rescue_tried": resc.get("tried"), "rescue_won": resc.get("won"),
        "pitch_coverage": pi.get("coverage"),
        "pitch_within_2st": pi.get("within_2st"),
        "pitch_within_2st_mod12": pi.get("within_2st_mod12"),
        "pitch_corr": pi.get("contour_corr"),
        "bpm_est": bp.get("est"), "bpm_mult": bp.get("mult"), "bpm_dev": bp.get("dev"),
    }


def aggregate(sample: list[dict], run_dir: str) -> None:
    rows = []
    for s in sample:
        slug = slugify(s["name"])
        row = {"song": s["name"], "lang_group": s.get("lang_group"),
               "wpm": s.get("wpm")}
        rj = os.path.join(run_dir, "results", f"{slug}.json")
        ej = os.path.join(run_dir, "results", f"{slug}.error.json")
        if os.path.exists(rj):
            with open(rj, encoding="utf-8") as f:
                row.update(_flat(json.load(f)))
        elif os.path.exists(ej):
            with open(ej, encoding="utf-8") as f:
                err = json.load(f)
            row["error"] = err.get("error")
            row["unmeasurable"] = bool(err.get("unmeasurable"))
        else:
            row["error"] = "not run"
        rows.append(row)

    csv_path = os.path.join(run_dir, "results.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FLAT_FIELDS)
        w.writeheader()
        w.writerows(rows)

    ok = [r for r in rows if r.get("recall") is not None]
    # "pulada por dado" NÃO conta como falha nossa - misturar as duas coisas
    # faz o relatório culpar o pipeline por biblioteca torta.
    unmeasurable = [r for r in rows if r.get("unmeasurable")]
    failed = [r for r in rows if r.get("error") and not r.get("unmeasurable")]

    def med_line(rs, label):
        parts = [f"  {label:24s}"]
        for k in KEY_METRICS:
            vals = [r[k] for r in rs if r.get(k) is not None]
            parts.append(f"{statistics.median(vals):9.3f}" if vals else "       --")
        print("".join(parts))

    print(f"\n=== library replay summary ({len(ok)} scored, {len(failed)} failed,"
          f" {len(unmeasurable)} skipped (data), {len(rows)} total) ===")
    for r in unmeasurable:
        print(f"  [dado] {r['song'][:44]}: {r['error']}")
    # os rótulos TÊM que espelhar KEY_METRICS, na mesma ordem - o med_line
    # imprime por KEY_METRICS, e um cabeçalho fora de sincronia faz a tabela
    # inteira mentir em silêncio (aconteceu ao adicionar o p_2st12).
    assert len(KEY_METRICS) == 7, "cabeçalho abaixo precisa acompanhar KEY_METRICS"
    print("  " + " " * 24 + "".join(f"{h:>9s}" for h in
                                    ["w_1s", "onset", "interp", "p_2st",
                                     "p_2st12", "p_corr", "bpm_dev"]))
    med_line(ok, "ALL (median)")
    for lg in ("es", "en", "other"):
        rs = [r for r in ok if r["lang_group"] == lg]
        if rs:
            med_line(rs, f"lang={lg} (n={len(rs)})")
    rescued = [r for r in ok if r.get("rescue_tried")]
    if rescued:
        won = sum(1 for r in rescued if r.get("rescue_won"))
        print(f"\n  lead-vocal rescue tried on {len(rescued)}/{len(ok)} songs, won {won}")
    bpm_all = [r for r in ok if r.get("bpm_dev") is not None]
    bpm_good = [r for r in bpm_all if r["bpm_dev"] < 0.02]
    if bpm_all:
        print(f"  BPM estimate within 2% of gold (mod octave): "
              f"{len(bpm_good)}/{len(bpm_all)}")
    for r in failed:
        print(f"  FAILED: {r['song']}: {r['error']}")
    print(f"\n  full table: {csv_path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", default=r"D:\Canciones Karaoke")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--seed-set", default=None,
                    help="path to a curated seed-set JSON (eval/seed_set.json); "
                         "overrides --n/--seed sampling")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--aggregate-only", action="store_true")
    args = ap.parse_args()

    runs_root = str(_HERE.parents[0] / "eval_runs")
    manifest = build_manifest(args.lib, runs_root)
    if not manifest:
        return 2

    if args.seed_set:
        sample = seed_set_sample(args.seed_set, manifest)
        run_dir = os.path.join(runs_root, "replay-seedset")
    else:
        sample, _ = stratified_sample(manifest, args.n, args.seed)
        run_dir = os.path.join(runs_root, f"replay-n{args.n}-seed{args.seed}")
    counts = ", ".join(
        f"{lg}={sum(1 for s in sample if s['lang_group'] == lg)}"
        for lg in ("es", "en", "other"))
    log(f"sample: {len(sample)} songs ({counts})")

    for sub in ("results", "cache"):
        os.makedirs(os.path.join(run_dir, sub), exist_ok=True)

    if not args.aggregate_only:
        for i, song in enumerate(sample, 1):
            log(f"[{i}/{len(sample)}]")
            run_song(song, run_dir, args.device)

    aggregate(sample, run_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())

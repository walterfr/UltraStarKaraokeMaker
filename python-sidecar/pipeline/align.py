"""
align.py
Etapa 4 (o coração do diferencial do USKMaker): alinhar a LETRA JÁ FORNECIDA
pelo usuário ao áudio vocal isolado, obtendo timestamp de início/fim por
palavra. Isso é "forced alignment", diferente de "transcrição" (o UltraSinger
transcreve do zero; aqui, o texto já é conhecido e confiável).

REESCRITA (06/07/2026, 3ª rodada de testes) - troca de estratégia de
alinhamento:

ABORDAGEM ANTIGA (mapeamento proporcional): dividia a letra real em pedaços
e substituía o texto de cada segmento do Whisper por um desses pedaços,
proporcionalmente por CONTAGEM de palavras. Funcionava bem na maior parte
da música, mas tinha um ponto fraco real: palavras curtas/muito comuns
("e", "a", "o") podiam ficar "grudadas" no timestamp de uma ocorrência
ERRADA da mesma palavra em outro lugar da música, já que a distribuição
proporcional não tem nenhuma forma de saber se a palavra que ela está
posicionando ali é realmente aquela ocorrência específica. Confirmado em
dois testes reais diferentes (Sangue Latino, "20 e poucos anos") - a letra
"trava" numa palavra isolada com timestamp muito adiantado/atrasado, e só
"pula" quando a próxima palavra corretamente posicionada aparece.

ABORDAGEM NOVA (âncora + interpolação):
  1. Deixa o Whisper transcrever o áudio LIVREMENTE (sem substituir nada) e
     alinha essa transcrição própria - isso dá timestamps de alta confiança
     para tudo que o Whisper efetivamente RECONHECEU no áudio (mesmo que a
     ortografia/pontuação não bata 100% com a letra real).
  2. Compara essa transcrição do Whisper com a letra real fornecida pelo
     usuário usando difflib.SequenceMatcher (mesma família de algoritmo do
     `diff` do Unix) - isso encontra os trechos onde as duas sequências de
     palavras REALMENTE coincidem, sem exigir correspondência perfeita em
     toda a música.
  3. Para cada palavra da letra real que teve uma correspondência exata
     (uma "âncora"), usa o timestamp que o Whisper mediu de verdade no
     áudio - alta confiança, baseado em detecção acústica real.
  4. Para palavras SEM correspondência (o Whisper errou/não reconheceu),
     interpola o timestamp linearmente entre a âncora anterior e a
     seguinte mais próximas - o erro fica contido a um intervalo pequeno
     (entre duas âncoras vizinhas), não mais espalhado pela música toda.

Isso reduz drasticamente o tipo de erro visto nos testes reais: em vez de
uma palavra isolada "roubar" o timestamp de uma ocorrência errada em
qualquer lugar da música, o pior caso agora é uma palavra sem âncora
própria ficar com um timestamp interpolado dentro de uma janela pequena e
localizada (entre as duas âncoras vizinhas mais próximas).

DESCOBERTA IMPORTANTE (validada em teste real - "Sangue Latino", 05/07/2026):
- O score de confiança do whisperx.align() vem sistematicamente baixo
  (às vezes 0.00-0.35) em trechos CANTADOS, mesmo quando o timestamp está
  correto. Isso é esperado: o modelo de alinhamento fonético (wav2vec2 CTC)
  foi treinado majoritariamente em fala, não em canto - vogais esticadas,
  vibrato e variação de pitch distorcem a pronúncia de um jeito que a fala
  normal não distorce, derrubando a confiança do modelo sem indicar erro
  real de timing.
- CONCLUSÃO PRÁTICA: não use o `score` sozinho como critério de "isso está
  errado, descartar". Ele é mais um indicador de "baixa certeza fonética",
  não de "timing incorreto". Trate os avisos de baixa confiança como
  candidatos a checagem manual (ouvir o trecho), não como erros confirmados.
  Na abordagem nova, palavras INTERPOLADAS (sem âncora) sempre recebem
  score=0.0 explicitamente - é um sinal DIFERENTE do score fonético baixo
  do whisperx, significa "esta palavra não foi medida, foi estimada".

DESCOBERTA CRÍTICA #2 (teste real - "Sangue Latino", 05/07/2026, 2ª rodada):
- O UltraStar Deluxe e o UltraStar Play carregavam a música (reconheciam o
  arquivo, mostravam capa/metadados) mas as notas NÃO rolavam na tela real
  de canto, em AMBOS os engines. Causa raiz: o .txt gerado não tinha NENHUM
  marcador de quebra de linha ("-") no arquivo inteiro. Corrigido propagando
  qual palavra é a ÚLTIMA de cada linha da letra original (is_line_end).

TODO conhecido:
- A interpolação linear entre âncoras é uma aproximação simples. Para
  trechos LONGOS sem nenhuma âncora (o Whisper errou muitas palavras
  seguidas), a distribuição fica uniforme mesmo que o ritmo real da fala
  não seja uniforme - ainda é um alvo razoável para a futura tela de
  revisão manual (Fase 4) ajustar.
- Alternativa mais "pura" de forced alignment (sem depender do Whisper para
  segmentação): Montreal Forced Aligner (MFA) ou aeneas. Vale comparar
  qualidade em PT-BR se a abordagem de âncora+interpolação ainda deixar
  muitos casos sem âncora.

Uso isolado (teste manual):
    python -m pipeline.align --vocals ./work/stems/htdemucs/musica/vocals.wav \
        --lyrics ./work/lyrics.txt --language pt --out ./work/align.json
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path

import whisperx


@dataclass
class WordTiming:
    word: str
    start: float  # segundos
    end: float    # segundos
    score: float  # confiança FONÉTICA do alinhamento (0-1) quando ANCORADA
    # (medida de verdade pelo whisperx). Quando INTERPOLADA (sem
    # correspondência no que o Whisper reconheceu), é sempre 0.0 - um sinal
    # diferente do score fonético baixo, significa "estimada, não medida".
    is_line_end: bool = False  # True se esta é a última palavra de uma
    # linha/frase da letra original - usado pelo build_song.py para saber
    # onde inserir os marcadores de quebra de frase ("-") no .txt final.
    anchored: bool = True  # False = timestamp interpolado (sem
    # correspondência direta na transcrição do Whisper) - útil para
    # diagnóstico/revisão manual futura.


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


def _normalize_word(word: str) -> str:
    """
    Normaliza uma palavra para comparação (minúsculas, sem pontuação),
    preservando acentos - remover acentos criaria falsos positivos entre
    palavras diferentes em português (ex.: "e" vs "é").
    """
    return re.sub(r"[^\w\u00C0-\u00FF]", "", word.lower())


def anchor_and_interpolate(
    whisper_words: list[dict],
    real_words: list[str],
) -> list[WordTiming]:
    """
    Núcleo da nova estratégia de alinhamento (ver docstring do módulo).

    `whisper_words`: saída bruta do whisperx.align() sobre a TRANSCRIÇÃO
    PRÓPRIA do Whisper (não substituída) - cada item tem 'word'/'start'/
    'end'/'score'.
    `real_words`: a letra fornecida pelo usuário, palavra por palavra.

    Usa difflib.SequenceMatcher para achar os trechos onde a transcrição
    do Whisper e a letra real coincidem (as "âncoras"), e interpola
    linearmente as palavras sem correspondência usando as âncoras vizinhas
    mais próximas.
    """
    whisper_norm = [_normalize_word(w.get("word", "")) for w in whisper_words]
    real_norm = [_normalize_word(w) for w in real_words]

    matcher = difflib.SequenceMatcher(None, whisper_norm, real_norm, autojunk=False)

    # anchors[j] = (start, end, score) para a palavra real_words[j], ou
    # None se ainda não tem correspondência direta
    anchors: list[tuple[float, float, float] | None] = [None] * len(real_words)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            continue
        for offset in range(i2 - i1):
            w = whisper_words[i1 + offset]
            anchors[j1 + offset] = (
                float(w.get("start", 0.0)),
                float(w.get("end", 0.0)),
                float(w.get("score", 0.0)),
            )

    n = len(real_words)
    results: list[WordTiming] = []

    for idx in range(n):
        anchor = anchors[idx]
        if anchor is not None:
            start, end, score = anchor
            anchored = True
        else:
            anchored = False
            score = 0.0

            prev_idx = idx - 1
            while prev_idx >= 0 and anchors[prev_idx] is None:
                prev_idx -= 1
            next_idx = idx + 1
            while next_idx < n and anchors[next_idx] is None:
                next_idx += 1

            if prev_idx >= 0 and next_idx < n:
                prev_end = anchors[prev_idx][1]
                next_start = anchors[next_idx][0]
                gap_words = next_idx - prev_idx  # nº de "slots" entre as âncoras
                position = idx - prev_idx  # posição desta palavra dentro do gap
                span = max(0.05, next_start - prev_end)
                per_word = span / gap_words
                start = prev_end + per_word * (position - 1)
                end = start + per_word
            elif prev_idx >= 0:
                # não há âncora seguinte (fim da música sem correspondência) -
                # estende um pouco a partir da última âncora conhecida
                prev_end = anchors[prev_idx][1]
                start = prev_end
                end = start + 0.3
            elif next_idx < n:
                # não há âncora anterior (início da música sem correspondência)
                next_start = anchors[next_idx][0]
                end = next_start
                start = max(0.0, end - 0.3)
            else:
                # nenhuma âncora em toda a música - não deveria acontecer na
                # prática, mas evita crash
                start, end = 0.0, 0.3

        results.append(
            WordTiming(
                word=real_words[idx],
                start=start,
                end=end,
                score=score,
                anchored=anchored,
            )
        )

    return results


def align_lyrics_to_audio(
    vocals_wav: Path,
    lyrics_path: Path,
    language: str = "pt",
    device: str = "cuda",
    whisper_model_size: str = "medium",
) -> list[WordTiming]:
    """
    Retorna uma lista de WordTiming na ordem da letra fornecida, usando a
    estratégia de âncora+interpolação (ver docstring do módulo).
    """
    compute_type = "float16"  # bom para RTX 4060; usar "int8" se faltar VRAM

    # 1) Transcrição LIVRE (sem substituir nada) - queremos saber o que o
    #    Whisper de fato reconheceu no áudio, com timestamps de alta
    #    confiança para o que ele acertar.
    whisper_model = whisperx.load_model(whisper_model_size, device, compute_type=compute_type)
    audio = whisperx.load_audio(str(vocals_wav))
    transcription = whisper_model.transcribe(audio, language=language)

    # 2) Alinha a transcrição PRÓPRIA do Whisper (não a letra real) - dá
    #    timestamps precisos para tudo que foi efetivamente reconhecido.
    align_model, metadata = whisperx.load_align_model(language_code=language, device=device)
    aligned = whisperx.align(
        transcription["segments"], align_model, metadata, audio, device, return_char_alignments=False
    )

    whisper_words: list[dict] = []
    for seg in aligned["segments"]:
        for w in seg.get("words", []):
            whisper_words.append(w)

    # 3) Ancora a letra real nas palavras que o Whisper reconheceu, e
    #    interpola o resto.
    real_words, line_end_flags = _load_lyrics_words_with_line_ends(lyrics_path)
    word_timings = anchor_and_interpolate(whisper_words, real_words)

    for wt, is_end in zip(word_timings, line_end_flags):
        wt.is_line_end = is_end

    return word_timings


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Etapa 4: forced alignment letra<->áudio (Fase 0 - teste isolado)")
    parser.add_argument("--vocals", required=True, help="Arquivo .wav do vocal isolado")
    parser.add_argument("--lyrics", required=True, help="Arquivo .txt com a letra (uma linha por frase)")
    parser.add_argument("--language", default="pt")
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    parser.add_argument("--whisper_model", default="medium")
    parser.add_argument("--out", default="./work/align.json")
    args = parser.parse_args()

    timings = align_lyrics_to_audio(
        Path(args.vocals), Path(args.lyrics), args.language, args.device, args.whisper_model
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps([asdict(t) for t in timings], ensure_ascii=False, indent=2), encoding="utf-8")

    anchored_count = sum(1 for t in timings if t.anchored)
    interpolated_count = len(timings) - anchored_count
    line_ends = sum(1 for t in timings if t.is_line_end)
    print(
        f"[OK] {len(timings)} palavras processadas ({anchored_count} ancoradas, "
        f"{interpolated_count} interpoladas, {line_ends} marcadas como fim de linha). "
        f"Salvo em {out_path}"
    )
    if interpolated_count:
        pct = 100 * interpolated_count / len(timings)
        print(f"[INFO] {pct:.1f}% das palavras foram interpoladas (sem correspondência direta no Whisper).")
        print("Palavras interpoladas ficam confinadas entre duas âncoras vizinhas - revisar se muitas seguidas:")
        for t in timings:
            if not t.anchored:
                print(f"   '{t.word}' @ {t.start:.2f}s (interpolada)")

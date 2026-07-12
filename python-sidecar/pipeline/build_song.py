"""
build_song.py
Etapa 6: junta tudo (timings de palavras, sílabas, pitch, grid de beats)
e monta o objeto Song pronto para exportar via ultrastar_writer.

Fluxo:
    word_timings (align.py, já com is_line_end marcado por palavra)
        -> para cada palavra, quebra em sílabas (syllabify.py)
        -> distribui o tempo da palavra proporcionalmente entre as sílabas
        -> extrai pitch de cada sílaba (pitch.py)
        -> converte tempo (segundos) -> beat (beatgrid.py)
        -> monta lista de Note (com espaçamento/convenção de continuação
           correta - ver nota abaixo)
        -> corrige overlaps residuais de arredondamento (fix_rounding_overlaps)
        -> marca phrase_breaks_after_index nas palavras de fim de linha
"""

from __future__ import annotations

from pathlib import Path

from .align import WordTiming
from .beatgrid import BeatGrid
from .pitch import PitchExtractor
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
        if not syllables:
            continue

        word_duration = max(0.01, wt.end - wt.start)
        syllable_duration = word_duration / len(syllables)

        for i, syl in enumerate(syllables):
            syl_start = wt.start + i * syllable_duration
            syl_end = syl_start + syllable_duration

            pitch_result = pitch_extractor.extract_segment_pitch(
                str(vocals_wav_path), syl_start, syl_end
            )

            start_beat = grid.seconds_to_beat(syl_start, gap_ms)
            end_beat = grid.seconds_to_beat(syl_end, gap_ms)
            duration_beats = max(1, end_beat - start_beat)  # nunca duração zero

            # CONVENÇÃO DE ESPAÇAMENTO (revista 12/07/2026):
            # No UltraStar, as sílabas de uma mesma palavra são notas
            # separadas cujo texto é CONCATENADO na tela; um espaço no
            # início/fim marca a fronteira entre palavras. Basta, então,
            # não pôr espaço entre as sílabas de uma palavra e um espaço no
            # fim da última - "Ju"+"rei " vira "Jurei ".
            #
            # CORREÇÃO (12/07/2026): a versão anterior prefixava "~" em toda
            # sílaba de continuação ("Ju"+"~rei"), o que o jogo exibe LITERAL
            # como "Ju~rei". No formato UltraStar o "~" é reservado para
            # MELISMA - a MESMA sílaba/vogal esticada até outra nota/pitch
            # (ex.: "you're~") - e aparece na tela. Usá-lo como mero separador
            # de sílabas era incorreto (a tela de revisão até removia o "~" ao
            # exibir, o que mascarava o problema; no jogo os tis apareciam).
            is_last_syllable_of_word = (i == len(syllables) - 1)
            text = syl
            if is_last_syllable_of_word:
                text += " "

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
                )
            )

        if wt.is_line_end and notes:
            phrase_breaks.append(len(notes) - 1)

    notes = fix_rounding_overlaps(notes)

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
    effective_gap_ms = max(0, round(first_start * 1000)) + gap_ms

    notes, phrase_breaks = build_notes(word_timings, vocals_wav_path, grid, effective_gap_ms, pitch_extractor)

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
        notes=notes,
        phrase_breaks_after_index=phrase_breaks,
    )

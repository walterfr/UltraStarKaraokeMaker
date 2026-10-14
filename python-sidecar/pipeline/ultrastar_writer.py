"""
ultrastar_writer.py
Escreve o arquivo .txt no formato oficial UltraStar, seguindo a spec:
https://github.com/UltraStar-Deluxe/format

Header obrigatório: #TITLE, #ARTIST, #MP3, #BPM (mais #GAP na prática, embora
tecnicamente opcional, quase sempre necessário). #VERSION não é
estritamente obrigatório (arquivos "sem versão" ainda são suportados), mas
incluímos por boa prática - é o primeiro header em qualquer arquivo
profissional de referência (ex.: usdb.animux.de).

Corpo: cada nota é uma linha
    <tipo> <start_beat> <duração_em_beats> <pitch> <texto>
Tipo:
    ":" nota normal
    "*" nota dourada (golden note - bônus de pontuação)
    "F" freestyle (não pontua)
Fim de frase:
    "- <beat>" (opcionalmente "- <beat> <end_beat>")
Fim do arquivo (opcional mas recomendado): "E"

FASE 1 (05/07/2026): o dono canônico do formato .txt está migrando para
Rust (rust-core/src/ultrastar_writer.rs). Esta classe Python agora serve
principalmente para:
  1. Exportar o JSON intermediário (to_json_dict/write_json) que o Rust
     consome.
  2. Servir de referência/oráculo para comparar a saída do Rust byte-a-byte
     (o método to_txt() daqui continua funcionando, útil para regressão).
Novas mudanças na spec devem ser feitas primeiro aqui OU no Rust, mas
sempre replicadas nos dois até o Python deixar de escrever o .txt de vez
(quando a Fase 2 - integração Tauri - estiver completa).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .align import WordTiming
    from .beatgrid import BeatGrid

from .i18n import t


@dataclass
class Note:
    start_beat: int
    duration_beats: int
    pitch: int
    text: str
    note_type: str = ":"  # ":" normal | "*" golden | "F" freestyle
    source: str | None = None  # proveniência do timestamp da palavra de
    # origem (anchor/fuzzy/realign/interpolated - ver align.py). Vai para o
    # JSON intermediário para a tela de revisão colorir por confiança;
    # NUNCA é escrito no .txt (não faz parte do formato UltraStar).
    score: float | None = None  # confiança FONÉTICA medida (WordTiming.score
    # em align.py), herdada da palavra de origem. Mesmo contrato do `source`
    # acima: só diagnóstico pra tela de revisão, nunca vai pro .txt. Permite
    # sinalizar uma âncora MEDIDA (source != interpolated) mas com score
    # baixo - um match que existe mas é suspeito, diferente de "não medido".
    singer: int = 0  # 0 = solo; 1 = P1; 2 = P2; 3 = ambos. Só relevante em
    # modo dueto: decide em qual bloco (P1/P2) a nota é escrita. "Ambos" (3)
    # vai nos DOIS blocos - os dois jogadores cantam a mesma nota.


@dataclass
class Song:
    title: str
    artist: str
    mp3_filename: str
    bpm: float  # BPM BRUTO/real da música (NÃO multiplicar por 4 - o motor
    # do jogo já faz isso sozinho, conforme a fórmula oficial do formato:
    # tempo_real = beat*60/(BPM*4). Ver nota detalhada em beatgrid.py -
    # bug de multiplicação duplicada corrigido em 05/07/2026.
    gap_ms: int = 0
    version: str = "1.0.0"
    genre: str | None = None
    year: int | None = None
    language: str | None = None
    cover_filename: str | None = None
    video_filename: str | None = None
    background_filename: str | None = None
    audio_url: str | None = None
    video_url: str | None = None
    cover_url: str | None = None
    video_gap: float | None = None
    preview_start: float | None = None
    medley_start_beat: int | None = None
    medley_end_beat: int | None = None
    # Faixas separadas (a cappella / playback), opcionais. A spec v1 (apêndice
    # A.3) permite ao player usá-las no lugar do #MP3 pra oferecer volume
    # separado de voz-guia e instrumental - o karaokê "de verdade": subir a voz
    # pra aprender, zerar pra cantar sozinho.
    vocals_filename: str | None = None
    instrumental_filename: str | None = None
    creator: str = "USKMaker"
    notes: list[Note] = field(default_factory=list)
    # índices em `notes` onde deve haver quebra de frase (fim de linha da letra)
    phrase_breaks_after_index: list[int] = field(default_factory=list)
    # Dueto (opt-in): quando True, escreve os headers #P1/#P2 e o corpo em dois
    # blocos ("P1" + notas do cantor 1, "P2" + notas do cantor 2), pela tag de
    # cantor de cada nota. Nomes dos cantores (opcionais) vão nos headers.
    duet: bool = False
    p1_name: str | None = None
    p2_name: str | None = None

    def to_txt(self) -> str:
        lines: list[str] = []

        lines.append(f"#VERSION:{self.version}")
        lines.append(f"#TITLE:{self.title}")
        lines.append(f"#ARTIST:{self.artist}")
        # Dueto: #P1/#P2 nomeiam os dois cantores. É a convenção que 100% dos
        # duetos reais da comunidade (USDB) usam - a spec também aceita
        # #DUETSINGERP1/P2, mas ninguém escreve assim.
        if self.duet:
            lines.append(f"#P1:{self.p1_name or 'P1'}")
            lines.append(f"#P2:{self.p2_name or 'P2'}")
        lines.append(f"#MP3:{self.mp3_filename}")
        # #AUDIO é o MESMO arquivo do #MP3, duplicado de propósito: na spec v1
        # o #MP3 é obrigatório e o #AUDIO opcional, mas "implementações DEVEM
        # desconsiderar o #MP3 se o #AUDIO estiver presente"; na v2 o #AUDIO
        # vira core. Escrever os dois serve player novo e antigo.
        # Espelha o rust-core/src/ultrastar_writer.rs, que é quem escreve o
        # .txt final no app - os dois têm que sair iguais.
        lines.append(f"#AUDIO:{self.mp3_filename}")
        if self.audio_url:
            lines.append(f"#AUDIOURL:{self.audio_url}")
        lines.append(f"#BPM:{self._format_number(self.bpm)}")
        lines.append(f"#GAP:{self.gap_ms}")
        if self.preview_start is not None:
            lines.append(f"#PREVIEWSTART:{self._format_number(self.preview_start)}")
        if self.medley_start_beat is not None and self.medley_end_beat is not None:
            lines.append(f"#MEDLEYSTARTBEAT:{self.medley_start_beat}")
            lines.append(f"#MEDLEYENDBEAT:{self.medley_end_beat}")

        if self.genre:
            lines.append(f"#GENRE:{self.genre}")
        if self.year:
            lines.append(f"#YEAR:{self.year}")
        if self.language:
            lines.append(f"#LANGUAGE:{self.language}")
        if self.cover_filename:
            lines.append(f"#COVER:{self.cover_filename}")
        if self.cover_url:
            lines.append(f"#COVERURL:{self.cover_url}")
        if self.video_filename:
            lines.append(f"#VIDEO:{self.video_filename}")
        if self.video_url:
            lines.append(f"#VIDEOURL:{self.video_url}")
        if self.video_gap is not None:
            lines.append(f"#VIDEOGAP:{self._format_number(self.video_gap)}")
        if self.background_filename:
            lines.append(f"#BACKGROUND:{self.background_filename}")
        if self.vocals_filename:
            lines.append(f"#VOCALS:{self.vocals_filename}")
        if self.instrumental_filename:
            lines.append(f"#INSTRUMENTAL:{self.instrumental_filename}")
        lines.append(f"#CREATOR:{self.creator}")

        phrase_break_set = set(self.phrase_breaks_after_index)
        if self.duet:
            # Dois blocos: "P1" + notas do cantor 1, "P2" + notas do cantor 2.
            # Cada bloco carrega beats ABSOLUTOS (cobre a música inteira); o
            # player sobrepõe os dois pelo beat. Notas "ambos" (3) entram nos
            # dois. É a estrutura dos duetos reais (Elton John, Stan, etc.).
            lines.append("P1")
            lines.extend(self._body_lines(phrase_break_set, {1, 3}))
            lines.append("P2")
            lines.extend(self._body_lines(phrase_break_set, {2, 3}))
        else:
            lines.extend(self._body_lines(phrase_break_set, None))

        lines.append("E")
        return "\n".join(lines)

    def _body_lines(self, phrase_break_set: set[int],
                    singers: set[int] | None) -> list[str]:
        """
        Linhas do corpo (notas + quebras "-") para um subconjunto de cantores.
        `singers=None` => todas as notas (modo solo). A quebra de frase só é
        emitida quando há uma PRÓXIMA nota no MESMO bloco - senão um "-" órfão
        no fim do bloco quebraria a rolagem.
        """
        block = [(i, n) for i, n in enumerate(self.notes)
                 if singers is None or n.singer in singers]
        out: list[str] = []
        for pos, (i, note) in enumerate(block):
            out.append(
                f"{note.note_type} {note.start_beat} {note.duration_beats} "
                f"{note.pitch} {note.text}"
            )
            if i in phrase_break_set and pos + 1 < len(block):
                out.append(f"- {block[pos + 1][1].start_beat}")
        return out

    @staticmethod
    def _format_number(value: float) -> str:
        # UltraStar aceita tanto "150" quanto "150,5" (vírgula) como separador
        # decimal legado, mas ponto também é aceito pela maioria dos players
        # modernos. Usamos ponto por simplicidade / compatibilidade ampla.
        if value == int(value):
            return str(int(value))
        return f"{value:.2f}"

    def validate_no_overlap(self) -> list[str]:
        """
        Verifica a regra da spec: notas não podem se sobrepor
        (start da próxima >= fim da anterior). Retorna lista de avisos.
        """
        warnings = []
        for i in range(len(self.notes) - 1):
            current_end = self.notes[i].start_beat + self.notes[i].duration_beats
            next_start = self.notes[i + 1].start_beat
            if next_start < current_end:
                warnings.append(t("writer.overlap", i=i, end=current_end,
                                  j=i + 1, start=next_start))
        return warnings

    def write(self, path: str) -> None:
        warnings = self.validate_no_overlap()
        if warnings:
            print(t("writer.overlaps_header"))
            for w in warnings:
                print("  -", w)

        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(self.to_txt())

    def to_json_dict(self) -> dict:
        """
        Serializa para o formato JSON intermediário que o rust-core (Fase 1)
        consome para gerar o .txt final. Nomes de campo em snake_case,
        espelhando exatamente os nomes usados nas structs Rust
        correspondentes (ver rust-core/src/ultrastar_writer.rs).
        """
        return asdict(self)

    def write_json(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_json_dict(), f, ensure_ascii=False, indent=2)


def detect_chorus_preview_medley(
    word_timings: list[WordTiming],
    notes: list[Note],
    grid: BeatGrid,
    gap_ms: int,
    duet: bool = False,
) -> tuple[float | None, int | None, int | None]:
    """
    Detecta automaticamente o refrão mais provável da música analisando repetições
    de linhas na letra, determinando:
      - preview_start: timestamp em segundos para prévia de áudio nos menus (#PREVIEWSTART)
      - medley_start_beat: beat inicial do refrão para o modo Medley (#MEDLEYSTARTBEAT)
      - medley_end_beat: beat final do refrão para o modo Medley (#MEDLEYENDBEAT)

    Regras da comunidade UltraStar:
      - Refrão para medley deve ter entre 8 e 60 segundos. Se > 60s, emite apenas preview_start.
      - Se < 8s, descarta o candidato (muito curto para um refrão real).
      - Em duetos, UltraStar Deluxe não suporta modo Medley; emite apenas preview_start.
    """
    if not word_timings or not notes:
        return None, None, None

    # Agrupa WordTiming em linhas pelo marcador is_line_end
    lines: list[list[WordTiming]] = []
    current_line: list[WordTiming] = []
    for wt in word_timings:
        current_line.append(wt)
        if wt.is_line_end:
            lines.append(current_line)
            current_line = []
    if current_line:
        lines.append(current_line)

    normalized_lines: list[tuple[int, str, float, float]] = []
    for i, line_wts in enumerate(lines):
        raw_text = " ".join(wt.word for wt in line_wts)
        clean = re.sub(r"[^\w\s]", "", raw_text.lower()).strip()
        clean = re.sub(r"\s+", " ", clean)
        if clean:
            start_t = line_wts[0].start
            end_t = line_wts[-1].end
            normalized_lines.append((i, clean, start_t, end_t))

    if len(normalized_lines) < 2:
        return None, None, None

    n_lines = len(normalized_lines)
    best_candidate: tuple[float, float, float] | None = None
    best_score = -1

    # Busca blocos de k linhas repetidas (de 8 até 1)
    max_k = min(8, n_lines // 2)
    for k in range(max_k, 0, -1):
        for i in range(n_lines - k + 1):
            block_sig = tuple(normalized_lines[x][1] for x in range(i, i + k))
            total_chars = sum(len(s) for s in block_sig)
            if total_chars < 12:
                continue

            occurrences: list[int] = []
            j = 0
            while j <= n_lines - k:
                if tuple(normalized_lines[x][1] for x in range(j, j + k)) == block_sig:
                    occurrences.append(j)
                    j += k
                else:
                    j += 1

            if len(occurrences) >= 2:
                first_occ = occurrences[0]
                start_s = normalized_lines[first_occ][2]
                end_s = normalized_lines[first_occ + k - 1][3]
                dur_s = end_s - start_s

                if dur_s < 8.0:
                    continue

                score = len(occurrences) * total_chars
                if score > best_score:
                    best_score = score
                    best_candidate = (start_s, end_s, dur_s)

    if best_candidate is None:
        return None, None, None

    start_s, end_s, dur_s = best_candidate
    preview_start = round(max(0.0, start_s), 2)

    # Se > 60s ou em dueto, emite apenas preview_start
    if duet or dur_s > 60.0:
        return preview_start, None, None

    raw_start_beat = grid.seconds_to_beat(start_s, gap_ms)
    raw_end_beat = grid.seconds_to_beat(end_s, gap_ms)

    # Encontra notas que pertencem ao intervalo do refrão
    candidate_notes = [
        n for n in notes
        if n.start_beat >= raw_start_beat - 4 and n.start_beat <= raw_end_beat + 4
    ]

    if candidate_notes:
        medley_start_beat = min(n.start_beat for n in candidate_notes)
        medley_end_beat = max(n.start_beat + n.duration_beats for n in candidate_notes)
    else:
        medley_start_beat = raw_start_beat
        medley_end_beat = raw_end_beat

    # Alinha preview_start exatamente ao início da nota do refrão
    preview_start = round(max(0.0, grid.beat_to_seconds(medley_start_beat, gap_ms)), 2)

    return preview_start, medley_start_beat, medley_end_beat

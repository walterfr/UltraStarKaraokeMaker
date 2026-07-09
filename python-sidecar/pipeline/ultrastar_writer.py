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
from dataclasses import dataclass, field, asdict


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
    creator: str = "USKMaker"
    notes: list[Note] = field(default_factory=list)
    # índices em `notes` onde deve haver quebra de frase (fim de linha da letra)
    phrase_breaks_after_index: list[int] = field(default_factory=list)

    def to_txt(self) -> str:
        lines: list[str] = []

        lines.append(f"#VERSION:{self.version}")
        lines.append(f"#TITLE:{self.title}")
        lines.append(f"#ARTIST:{self.artist}")
        lines.append(f"#MP3:{self.mp3_filename}")
        lines.append(f"#BPM:{self._format_number(self.bpm)}")
        lines.append(f"#GAP:{self.gap_ms}")

        if self.genre:
            lines.append(f"#GENRE:{self.genre}")
        if self.year:
            lines.append(f"#YEAR:{self.year}")
        if self.language:
            lines.append(f"#LANGUAGE:{self.language}")
        if self.cover_filename:
            lines.append(f"#COVER:{self.cover_filename}")
        if self.video_filename:
            lines.append(f"#VIDEO:{self.video_filename}")
        if self.background_filename:
            lines.append(f"#BACKGROUND:{self.background_filename}")
        lines.append(f"#CREATOR:{self.creator}")

        phrase_break_set = set(self.phrase_breaks_after_index)
        for i, note in enumerate(self.notes):
            lines.append(
                f"{note.note_type} {note.start_beat} {note.duration_beats} {note.pitch} {note.text}"
            )
            if i in phrase_break_set and i + 1 < len(self.notes):
                next_start = self.notes[i + 1].start_beat
                lines.append(f"- {next_start}")

        lines.append("E")
        return "\n".join(lines)

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
                warnings.append(
                    f"Sobreposição entre nota {i} (fim={current_end}) e nota {i+1} (início={next_start})"
                )
        return warnings

    def write(self, path: str) -> None:
        warnings = self.validate_no_overlap()
        if warnings:
            print("[ATENÇÃO] Overlaps detectados antes de salvar:")
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

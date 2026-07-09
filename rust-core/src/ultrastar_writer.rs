//! ultrastar_writer.rs
//! Fase 1: reescrita em Rust do gerador de .txt UltraStar, portado do
//! python-sidecar/pipeline/ultrastar_writer.py.
//!
//! Todas as correções descobertas durante os testes reais da Fase 0 (Python)
//! já vêm incorporadas aqui desde o início, para não repetir os mesmos bugs:
//!   - #VERSION no header (boa prática, arquivos profissionais têm).
//!   - `bpm` é sempre o valor BRUTO/real da música. O motor do jogo já
//!     multiplica por 4 internamente (fórmula oficial:
//!     tempo_real = beat*60/(BPM*4)) - NUNCA gravar bpm*4 aqui.
//!   - Marcadores de quebra de frase ("-") via phrase_breaks_after_index -
//!     sem isso, o jogo trata a música inteira como uma única linha e a
//!     rolagem de notas quebra (bug real encontrado em teste, 05/07/2026).
//!   - Convenção de espaçamento: sílabas de continuação de palavra levam
//!     "~" e ficam sem espaço antes; a última sílaba de cada palavra leva
//!     espaço no final (isso é responsabilidade de quem monta as Notes,
//!     não deste módulo, mas documentado aqui para contexto).

use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::fs;
use std::io;
use std::path::Path;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Note {
    pub start_beat: i64,
    pub duration_beats: i64,
    pub pitch: i64,
    pub text: String,
    #[serde(default = "default_note_type")]
    pub note_type: String, // ":" normal | "*" golden | "F" freestyle
    /// Proveniência do timestamp da palavra de origem
    /// (anchor/fuzzy/realign/interpolated - ver align.py do sidecar).
    /// Diagnóstico para a tela de revisão colorir por confiança; NUNCA é
    /// escrito no .txt. Opcional para compatibilidade com JSONs antigos.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source: Option<String>,
}

fn default_note_type() -> String {
    ":".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Song {
    pub title: String,
    pub artist: String,
    pub mp3_filename: String,
    /// BPM BRUTO/real da música. NÃO multiplicar por 4 - ver nota do módulo.
    pub bpm: f64,
    #[serde(default)]
    pub gap_ms: i64,
    #[serde(default = "default_version")]
    pub version: String,
    #[serde(default)]
    pub genre: Option<String>,
    #[serde(default)]
    pub year: Option<i64>,
    #[serde(default)]
    pub language: Option<String>,
    #[serde(default)]
    pub cover_filename: Option<String>,
    #[serde(default)]
    pub video_filename: Option<String>,
    #[serde(default)]
    pub background_filename: Option<String>,
    #[serde(default = "default_creator")]
    pub creator: String,
    #[serde(default)]
    pub notes: Vec<Note>,
    /// Índices em `notes` onde deve haver quebra de frase (fim de linha da letra)
    #[serde(default)]
    pub phrase_breaks_after_index: Vec<usize>,
}

fn default_version() -> String {
    "1.0.0".to_string()
}

fn default_creator() -> String {
    "USKMaker".to_string()
}

impl Song {
    /// Formata um número como o UltraStar espera: inteiro sem casas
    /// decimais quando o valor é exato, ou 2 casas decimais fixas.
    /// Espelha exatamente `Song._format_number` do Python.
    pub fn format_number(value: f64) -> String {
        if value == value.trunc() {
            format!("{}", value as i64)
        } else {
            format!("{:.2}", value)
        }
    }

    /// Verifica a regra da spec: notas não podem se sobrepor
    /// (start da próxima >= fim da anterior). Retorna avisos, não erros -
    /// espelha o comportamento do Python (avisa mas ainda escreve o arquivo).
    pub fn validate_no_overlap(&self) -> Vec<String> {
        let mut warnings = Vec::new();
        for i in 0..self.notes.len().saturating_sub(1) {
            let current_end = self.notes[i].start_beat + self.notes[i].duration_beats;
            let next_start = self.notes[i + 1].start_beat;
            if next_start < current_end {
                warnings.push(format!(
                    "Sobreposição entre nota {} (fim={}) e nota {} (início={})",
                    i, current_end, i + 1, next_start
                ));
            }
        }
        warnings
    }

    pub fn to_txt(&self) -> String {
        let mut lines: Vec<String> = Vec::new();

        lines.push(format!("#VERSION:{}", self.version));
        lines.push(format!("#TITLE:{}", self.title));
        lines.push(format!("#ARTIST:{}", self.artist));
        lines.push(format!("#MP3:{}", self.mp3_filename));
        lines.push(format!("#BPM:{}", Self::format_number(self.bpm)));
        lines.push(format!("#GAP:{}", self.gap_ms));

        if let Some(genre) = &self.genre {
            lines.push(format!("#GENRE:{}", genre));
        }
        if let Some(year) = &self.year {
            lines.push(format!("#YEAR:{}", year));
        }
        if let Some(language) = &self.language {
            lines.push(format!("#LANGUAGE:{}", language));
        }
        if let Some(cover) = &self.cover_filename {
            lines.push(format!("#COVER:{}", cover));
        }
        if let Some(video) = &self.video_filename {
            lines.push(format!("#VIDEO:{}", video));
        }
        if let Some(bg) = &self.background_filename {
            lines.push(format!("#BACKGROUND:{}", bg));
        }
        lines.push(format!("#CREATOR:{}", self.creator));

        let phrase_break_set: HashSet<usize> =
            self.phrase_breaks_after_index.iter().cloned().collect();

        for (i, note) in self.notes.iter().enumerate() {
            lines.push(format!(
                "{} {} {} {} {}",
                note.note_type, note.start_beat, note.duration_beats, note.pitch, note.text
            ));
            if phrase_break_set.contains(&i) && i + 1 < self.notes.len() {
                let next_start = self.notes[i + 1].start_beat;
                lines.push(format!("- {}", next_start));
            }
        }

        lines.push("E".to_string());
        lines.join("\n")
    }

    /// Grava o .txt em disco. Usa `\n` puro (LF), igual ao writer Python
    /// (que usa `newline="\n"` explicitamente) - `fs::write` do Rust não
    /// faz nenhuma tradução automática de quebra de linha, então o
    /// comportamento já é consistente por padrão nesse ponto.
    pub fn write<P: AsRef<Path>>(&self, path: P) -> io::Result<()> {
        let warnings = self.validate_no_overlap();
        if !warnings.is_empty() {
            eprintln!("[ATENÇÃO] Overlaps detectados antes de salvar:");
            for w in &warnings {
                eprintln!("  - {}", w);
            }
        }
        fs::write(path, self.to_txt())
    }

    /// Lê o JSON intermediário exportado pelo python-sidecar
    /// (build_song.py -> Song.write_json).
    pub fn from_json_file<P: AsRef<Path>>(path: P) -> io::Result<Song> {
        let content = fs::read_to_string(path)?;
        serde_json::from_str(&content).map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))
    }

    pub fn from_json_str(content: &str) -> serde_json::Result<Song> {
        serde_json::from_str(content)
    }
}

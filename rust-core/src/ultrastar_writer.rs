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
    /// Confiança fonética medida (WordTiming.score no sidecar), herdada da
    /// palavra de origem. Mesmo contrato do `source` acima: só diagnóstico
    /// pra tela de revisão, nunca vai pro .txt. Opcional pelo mesmo motivo.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub score: Option<f64>,
    /// Cantor da nota em modo dueto: 0 solo, 1 P1, 2 P2, 3 ambos. Decide em
    /// qual bloco (P1/P2) a nota é escrita; "ambos" vai nos dois. Ignorado
    /// fora do modo dueto. Opcional para compatibilidade com JSONs antigos.
    #[serde(default)]
    pub singer: i64,
}

fn default_note_type() -> String {
    ":".to_string()
}

/// Duas notas vizinhas que se sobrepõem no tempo: a primeira termina depois
/// de a segunda começar. Índices são posições em `Song.notes`, e os tempos
/// são BEATS (a mesma unidade da tela de revisão).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NoteOverlap {
    pub first_index: usize,
    pub first_end_beat: i64,
    pub second_index: usize,
    pub second_start_beat: i64,
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
    #[serde(default)]
    pub audio_url: Option<String>,
    #[serde(default)]
    pub video_url: Option<String>,
    #[serde(default)]
    pub cover_url: Option<String>,
    #[serde(default)]
    pub video_gap: Option<f64>,
    #[serde(default)]
    pub preview_start: Option<f64>,
    #[serde(default)]
    pub medley_start_beat: Option<i64>,
    #[serde(default)]
    pub medley_end_beat: Option<i64>,
    /// Faixas separadas (a cappella / playback), opcionais. A spec v1 (apêndice
    /// A.3) permite ao player usá-las no lugar do #MP3 pra dar volume separado
    /// de voz-guia e instrumental. Vêm do Demucs, que a pipeline já roda.
    #[serde(default)]
    pub vocals_filename: Option<String>,
    #[serde(default)]
    pub instrumental_filename: Option<String>,
    #[serde(default)]
    pub tags: Option<String>,
    #[serde(default = "default_creator")]
    pub creator: String,
    #[serde(default)]
    pub notes: Vec<Note>,
    /// Índices em `notes` onde deve haver quebra de frase (fim de linha da letra)
    #[serde(default)]
    pub phrase_breaks_after_index: Vec<usize>,
    /// Dueto (opt-in): quando true, escreve os headers #P1/#P2 e o corpo em
    /// dois blocos ("P1" + notas do cantor 1, "P2" + notas do cantor 2), pela
    /// tag `singer` de cada nota. Ver ultrastar_writer.py (o oráculo).
    #[serde(default)]
    pub duet: bool,
    #[serde(default)]
    pub p1_name: Option<String>,
    #[serde(default)]
    pub p2_name: Option<String>,
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
    /// Sobreposições encontradas, em DADOS - sem texto.
    ///
    /// A mensagem para o usuário mora em quem tem idioma: o app (src-tauri)
    /// monta o aviso em PT ou EN a partir daqui. Este crate não conhece
    /// idioma nenhum, e não deveria: fixar a frase aqui foi o que fez os
    /// avisos de validação chegarem em português a quem usa o app em inglês
    /// (relatado pelo usuário, 07/09/2026).
    pub fn find_overlaps(&self) -> Vec<NoteOverlap> {
        let mut found = Vec::new();
        for i in 0..self.notes.len().saturating_sub(1) {
            let current_end = self.notes[i].start_beat + self.notes[i].duration_beats;
            let next_start = self.notes[i + 1].start_beat;
            if next_start < current_end {
                found.push(NoteOverlap {
                    first_index: i,
                    first_end_beat: current_end,
                    second_index: i + 1,
                    second_start_beat: next_start,
                });
            }
        }
        found
    }

    /// Mesmas sobreposições já escritas em português, para o CLI deste crate
    /// (`write_txt` imprime no stderr). O app NÃO usa isto - ver find_overlaps.
    pub fn validate_no_overlap(&self) -> Vec<String> {
        self.find_overlaps()
            .into_iter()
            .map(|o| {
                format!(
                    "Sobreposição entre nota {} (fim={}) e nota {} (início={})",
                    o.first_index, o.first_end_beat, o.second_index, o.second_start_beat
                )
            })
            .collect()
    }

    pub fn to_txt(&self) -> String {
        let mut lines: Vec<String> = Vec::new();

        lines.push(format!("#VERSION:{}", self.version));
        lines.push(format!("#TITLE:{}", self.title));
        lines.push(format!("#ARTIST:{}", self.artist));
        // Dueto: #P1/#P2 nomeiam os cantores. É a convenção da comunidade
        // (USDB); a spec também aceita #DUETSINGERP1/P2, mas ninguém usa.
        if self.duet {
            lines.push(format!(
                "#P1:{}",
                self.p1_name.as_deref().unwrap_or("P1")
            ));
            lines.push(format!(
                "#P2:{}",
                self.p2_name.as_deref().unwrap_or("P2")
            ));
        }
        lines.push(format!("#MP3:{}", self.mp3_filename));
        // #AUDIO é o mesmo arquivo do #MP3, escrito de propósito em duplicata.
        // Na spec v1 (a publicada) o #MP3 é OBRIGATÓRIO e o #AUDIO é opcional
        // (apêndice A.1), mas com uma regra clara: "implementações DEVEM
        // desconsiderar o #MP3 se o #AUDIO estiver presente". Na v2 o #AUDIO
        // vira header core e o #MP3 sai. Escrever os dois é o único jeito de
        // servir os players novos e os antigos ao mesmo tempo - e não há risco
        // de divergirem, porque apontam para o mesmo arquivo.
        //
        // NÃO subir o #VERSION por causa disto: a v2 se declara NÃO PUBLICADA
        // ("may change significantly"), então 1.0.0 continua sendo o certo.
        lines.push(format!("#AUDIO:{}", self.mp3_filename));
        if let Some(audio_url) = &self.audio_url {
            lines.push(format!("#AUDIOURL:{}", audio_url));
        }
        lines.push(format!("#BPM:{}", Self::format_number(self.bpm)));
        lines.push(format!("#GAP:{}", self.gap_ms));
        if let Some(preview_start) = self.preview_start {
            lines.push(format!("#PREVIEWSTART:{}", Self::format_number(preview_start)));
        }
        if let (Some(medley_start), Some(medley_end)) = (self.medley_start_beat, self.medley_end_beat) {
            lines.push(format!("#MEDLEYSTARTBEAT:{}", medley_start));
            lines.push(format!("#MEDLEYENDBEAT:{}", medley_end));
        }

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
        if let Some(cover_url) = &self.cover_url {
            lines.push(format!("#COVERURL:{}", cover_url));
        }
        if let Some(video) = &self.video_filename {
            lines.push(format!("#VIDEO:{}", video));
        }
        if let Some(video_url) = &self.video_url {
            lines.push(format!("#VIDEOURL:{}", video_url));
        }
        if let Some(video_gap) = self.video_gap {
            lines.push(format!("#VIDEOGAP:{}", Self::format_number(video_gap)));
        }
        if let Some(bg) = &self.background_filename {
            lines.push(format!("#BACKGROUND:{}", bg));
        }
        if let Some(vocals) = &self.vocals_filename {
            lines.push(format!("#VOCALS:{}", vocals));
        }
        if let Some(instrumental) = &self.instrumental_filename {
            lines.push(format!("#INSTRUMENTAL:{}", instrumental));
        }
        if let Some(tags) = &self.tags {
            if !tags.is_empty() {
                lines.push(format!("#TAGS:{}", tags));
            }
        }
        lines.push(format!("#CREATOR:{}", self.creator));

        let phrase_break_set: HashSet<usize> =
            self.phrase_breaks_after_index.iter().cloned().collect();

        if self.duet {
            // Dois blocos, com beats absolutos cada; o player os sobrepõe pelo
            // beat. Notas "ambos" (3) entram nos dois. Espelha o to_txt do
            // Python (o oráculo de regressão byte-a-byte).
            lines.push("P1".to_string());
            lines.extend(self.body_lines(&phrase_break_set, Some(&[1, 3])));
            lines.push("P2".to_string());
            lines.extend(self.body_lines(&phrase_break_set, Some(&[2, 3])));
        } else {
            lines.extend(self.body_lines(&phrase_break_set, None));
        }

        lines.push("E".to_string());
        lines.join("\n")
    }

    /// Linhas do corpo (notas + quebras "-") para um subconjunto de cantores.
    /// `singers=None` => todas as notas (solo). A quebra só sai quando há uma
    /// PRÓXIMA nota no MESMO bloco - senão um "-" órfão quebra a rolagem.
    fn body_lines(&self, phrase_break_set: &HashSet<usize>,
                  singers: Option<&[i64]>) -> Vec<String> {
        let block: Vec<(usize, &Note)> = self
            .notes
            .iter()
            .enumerate()
            .filter(|(_, n)| match singers {
                None => true,
                Some(s) => s.contains(&n.singer),
            })
            .collect();
        let mut out: Vec<String> = Vec::new();
        for (pos, (i, note)) in block.iter().enumerate() {
            out.push(format!(
                "{} {} {} {} {}",
                note.note_type, note.start_beat, note.duration_beats, note.pitch, note.text
            ));
            if phrase_break_set.contains(i) && pos + 1 < block.len() {
                out.push(format!("- {}", block[pos + 1].1.start_beat));
            }
        }
        out
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

    /// Lê um chart no formato UltraStar (.txt) e constrói a struct `Song`.
    /// Suporta cabeçalhos (#TITLE, #ARTIST, #BPM, #GAP, etc.), notas (:, *, F, R, G),
    /// quebras de linha/frase (-) e marcadores P1/P2 (dueto).
    pub fn from_txt_str(content: &str) -> Result<Song, String> {
        let mut title = String::new();
        let mut artist = String::new();
        let mut mp3_filename = String::new();
        let mut bpm = 0.0;
        let mut gap_ms: i64 = 0;
        let mut version = default_version();
        let mut genre: Option<String> = None;
        let mut year: Option<i64> = None;
        let mut language: Option<String> = None;
        let mut cover_filename: Option<String> = None;
        let mut video_filename: Option<String> = None;
        let mut background_filename: Option<String> = None;
        let mut audio_url: Option<String> = None;
        let mut video_url: Option<String> = None;
        let mut cover_url: Option<String> = None;
        let mut video_gap: Option<f64> = None;
        let mut preview_start: Option<f64> = None;
        let mut medley_start_beat: Option<i64> = None;
        let mut medley_end_beat: Option<i64> = None;
        let mut vocals_filename: Option<String> = None;
        let mut instrumental_filename: Option<String> = None;
        let mut tags: Option<String> = None;
        let mut creator = default_creator();
        let mut p1_name: Option<String> = None;
        let mut p2_name: Option<String> = None;
        let mut duet = false;
        let mut current_singer: i64 = 0;

        let mut notes: Vec<Note> = Vec::new();
        let mut phrase_breaks_after_index: Vec<usize> = Vec::new();

        for line in content.lines() {
            let trimmed = line.trim();
            if trimmed.is_empty() {
                continue;
            }

            if line.starts_with('#') {
                if let Some((tag, val)) = line[1..].split_once(':') {
                    let tag = tag.trim().to_uppercase();
                    let val = val.trim();
                    match tag.as_str() {
                        "TITLE" => title = val.to_string(),
                        "ARTIST" => artist = val.to_string(),
                        "MP3" => mp3_filename = val.to_string(),
                        "BPM" => {
                            let norm = val.replace(',', ".");
                            bpm = norm.parse::<f64>().unwrap_or(0.0);
                        }
                        "GAP" => {
                            let norm = val.replace(',', ".");
                            gap_ms = norm.parse::<f64>().map(|v| v.round() as i64).unwrap_or(0);
                        }
                        "VERSION" => version = val.to_string(),
                        "GENRE" => genre = Some(val.to_string()),
                        "YEAR" => year = val.parse::<i64>().ok(),
                        "LANGUAGE" => language = Some(val.to_string()),
                        "COVER" => cover_filename = Some(val.to_string()),
                        "VIDEO" => video_filename = Some(val.to_string()),
                        "BACKGROUND" => background_filename = Some(val.to_string()),
                        "AUDIOURL" => audio_url = Some(val.to_string()),
                        "VIDEOURL" => video_url = Some(val.to_string()),
                        "COVERURL" => cover_url = Some(val.to_string()),
                        "VIDEOGAP" => {
                            video_gap = val.replace(',', ".").parse::<f64>().ok();
                        }
                        "PREVIEWSOUND" | "START" => {
                            preview_start = val.replace(',', ".").parse::<f64>().ok();
                        }
                        "MEDLEYSTARTBEAT" => medley_start_beat = val.parse::<i64>().ok(),
                        "MEDLEYENDBEAT" => medley_end_beat = val.parse::<i64>().ok(),
                        "VOCALS" => vocals_filename = Some(val.to_string()),
                        "INSTRUMENTAL" => instrumental_filename = Some(val.to_string()),
                        "TAGS" => tags = Some(val.to_string()),
                        "CREATOR" => creator = val.to_string(),
                        "P1" => {
                            duet = true;
                            p1_name = Some(val.to_string());
                        }
                        "P2" => {
                            duet = true;
                            p2_name = Some(val.to_string());
                        }
                        _ => {}
                    }
                }
                continue;
            }

            if trimmed == "P1" {
                duet = true;
                current_singer = 1;
                continue;
            }
            if trimmed == "P2" {
                duet = true;
                current_singer = 2;
                continue;
            }
            if trimmed == "E" {
                break;
            }
            if trimmed.starts_with('-') {
                if !notes.is_empty() {
                    let last_idx = notes.len() - 1;
                    if !phrase_breaks_after_index.contains(&last_idx) {
                        phrase_breaks_after_index.push(last_idx);
                    }
                }
                continue;
            }

            let first_char = match line.chars().next() {
                Some(c) => c,
                None => continue,
            };

            if [':', '*', 'F', 'R', 'G'].contains(&first_char) {
                let note_type = first_char.to_string();
                let rest = line[first_char.len_utf8()..].trim_start();
                let mut parts = rest.splitn(4, |c: char| c.is_ascii_whitespace());
                let start_str = match parts.next() {
                    Some(s) if !s.is_empty() => s,
                    _ => continue,
                };
                let dur_str = match parts.next() {
                    Some(s) if !s.is_empty() => s,
                    _ => continue,
                };
                let pitch_str = match parts.next() {
                    Some(s) if !s.is_empty() => s,
                    _ => continue,
                };
                let text_str = parts.next().unwrap_or("");

                let start_beat = start_str.parse::<i64>().unwrap_or(0);
                let duration_beats = dur_str.parse::<i64>().unwrap_or(1);
                let pitch = pitch_str.parse::<i64>().unwrap_or(0);

                notes.push(Note {
                    start_beat,
                    duration_beats,
                    pitch,
                    text: text_str.to_string(),
                    note_type,
                    source: None,
                    score: None,
                    singer: current_singer,
                });
            }
        }

        if title.is_empty() && artist.is_empty() && notes.is_empty() {
            return Err("Arquivo UltraStar não contém cabeçalhos nem notas válidas".to_string());
        }

        Ok(Song {
            title,
            artist,
            mp3_filename,
            bpm,
            gap_ms,
            version,
            genre,
            year,
            language,
            cover_filename,
            video_filename,
            background_filename,
            audio_url,
            video_url,
            cover_url,
            video_gap,
            preview_start,
            medley_start_beat,
            medley_end_beat,
            vocals_filename,
            instrumental_filename,
            tags,
            creator,
            notes,
            phrase_breaks_after_index,
            duet,
            p1_name,
            p2_name,
        })
    }

    pub fn from_txt_file<P: AsRef<Path>>(path: P) -> Result<Song, String> {
        let content = fs::read_to_string(path.as_ref())
            .map_err(|e| format!("Falha ao ler {}: {}", path.as_ref().display(), e))?;
        Self::from_txt_str(&content)
    }
}

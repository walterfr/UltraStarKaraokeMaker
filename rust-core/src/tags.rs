use std::path::Path;
use serde::{Deserialize, Serialize};
use lofty::file::{AudioFile, TaggedFileExt};
use lofty::read_from_path;
use lofty::tag::{Accessor, ItemKey};

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct AudioTags {
    pub title: Option<String>,
    pub artist: Option<String>,
    pub album: Option<String>,
    pub year: Option<u32>,
    pub genre: Option<String>,
    pub duration: Option<f64>,
}

/// Extrai ano de 4 dígitos a partir de uma string de data (ex.: "2021-05-12", "2021").
fn parse_year(s: &str) -> Option<u32> {
    for part in s.split(|c: char| !c.is_ascii_digit()) {
        if part.len() == 4 {
            if let Ok(y) = part.parse::<u32>() {
                if (1900..=2099).contains(&y) {
                    return Some(y);
                }
            }
        }
    }
    None
}

/// Lê tags básicas (título, artista, álbum, ano, gênero, duração) de um arquivo
/// de áudio local. Se o arquivo não existir ou não for um áudio suportado, devolve AudioTags vazia.
pub fn read_audio_tags<P: AsRef<Path>>(path: P) -> AudioTags {
    let path = path.as_ref();
    let tagged_file = match read_from_path(path) {
        Ok(f) => f,
        Err(_) => return AudioTags::default(),
    };

    let mut tags = AudioTags::default();

    // Duração das propriedades de áudio
    let duration = tagged_file.properties().duration().as_secs_f64();
    if duration > 0.0 {
        tags.duration = Some((duration * 100.0).round() / 100.0);
    }

    if let Some(tag) = tagged_file.primary_tag().or_else(|| tagged_file.first_tag()) {
        tags.title = tag.title().map(|s| s.trim().to_string()).filter(|s| !s.is_empty());
        tags.artist = tag.artist().map(|s| s.trim().to_string()).filter(|s| !s.is_empty());
        tags.album = tag.album().map(|s| s.trim().to_string()).filter(|s| !s.is_empty());
        tags.genre = tag.genre().map(|s| s.trim().to_string()).filter(|s| !s.is_empty());

        let raw_date = tag.get_string(ItemKey::RecordingDate)
            .or_else(|| tag.get_string(ItemKey::Year))
            .or_else(|| tag.get_string(ItemKey::OriginalReleaseDate));

        if let Some(date_str) = raw_date {
            tags.year = parse_year(date_str);
        }
    }

    tags
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_year() {
        assert_eq!(parse_year("2021-05-12"), Some(2021));
        assert_eq!(parse_year("1998"), Some(1998));
        assert_eq!(parse_year("May 1985"), Some(1985));
        assert_eq!(parse_year("invalid"), None);
        assert_eq!(parse_year("1899"), None);
        assert_eq!(parse_year("2105"), None);
    }

    #[test]
    fn test_non_existent_file_returns_default() {
        let tags = read_audio_tags("non_existent_file_12345.mp3");
        assert_eq!(tags, AudioTags::default());
        assert!(tags.title.is_none());
        assert!(tags.duration.is_none());
    }
}

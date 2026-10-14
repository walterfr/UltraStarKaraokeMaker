//! midi_writer.rs
//! Exporta Song no formato Standard MIDI File (.mid) com letras sincronizadas
//! (meta-eventos 0x05 - Lyric), compatível com DAWs, MuseScore, Synthesizer V
//! e players de MIDI Karaoke (.kar).

use crate::ultrastar_writer::{Note, Song};
use std::collections::HashSet;
use std::fs;
use std::io;
use std::path::Path;

pub const PPQ: u16 = 480;
pub const TICKS_PER_BEAT: u32 = 120; // 480 / 4

fn write_vlq(mut value: u32, out: &mut Vec<u8>) {
    let mut buf = [0u8; 5];
    let mut pos = 0;
    buf[pos] = (value & 0x7F) as u8;
    value >>= 7;
    while value > 0 {
        pos += 1;
        buf[pos] = 0x80 | ((value & 0x7F) as u8);
        value >>= 7;
    }
    for i in (0..=pos).rev() {
        out.push(buf[i]);
    }
}

#[derive(Debug, Clone)]
enum MidiMessage {
    TrackName(String),
    SetTempo(u32), // microssegundos por semínima (quarter note)
    Lyric(String),
    NoteOn { channel: u8, note: u8, velocity: u8 },
    NoteOff { channel: u8, note: u8 },
    EndOfTrack,
}

#[derive(Debug, Clone)]
struct TimedEvent {
    tick: u32,
    priority: u8,
    msg: MidiMessage,
}

fn encode_track(events: &[TimedEvent]) -> Vec<u8> {
    let mut data = Vec::new();
    let mut current_tick = 0u32;

    for ev in events {
        let delta = ev.tick.saturating_sub(current_tick);
        current_tick = ev.tick;
        write_vlq(delta, &mut data);

        match &ev.msg {
            MidiMessage::TrackName(name) => {
                data.push(0xFF);
                data.push(0x03);
                write_vlq(name.len() as u32, &mut data);
                data.extend_from_slice(name.as_bytes());
            }
            MidiMessage::SetTempo(us_per_quarter) => {
                data.push(0xFF);
                data.push(0x51);
                data.push(0x03);
                data.push(((us_per_quarter >> 16) & 0xFF) as u8);
                data.push(((us_per_quarter >> 8) & 0xFF) as u8);
                data.push((us_per_quarter & 0xFF) as u8);
            }
            MidiMessage::Lyric(text) => {
                data.push(0xFF);
                data.push(0x05);
                write_vlq(text.len() as u32, &mut data);
                data.extend_from_slice(text.as_bytes());
            }
            MidiMessage::NoteOn {
                channel,
                note,
                velocity,
            } => {
                data.push(0x90 | (channel & 0x0F));
                data.push(*note);
                data.push(*velocity);
            }
            MidiMessage::NoteOff { channel, note } => {
                data.push(0x80 | (channel & 0x0F));
                data.push(*note);
                data.push(0x00);
            }
            MidiMessage::EndOfTrack => {
                data.push(0xFF);
                data.push(0x2F);
                data.push(0x00);
            }
        }
    }

    let mut chunk = Vec::with_capacity(8 + data.len());
    chunk.extend_from_slice(b"MTrk");
    chunk.extend_from_slice(&(data.len() as u32).to_be_bytes());
    chunk.extend_from_slice(&data);
    chunk
}

fn encode_header(format: u16, ntracks: u16, division: u16) -> Vec<u8> {
    let mut h = Vec::with_capacity(14);
    h.extend_from_slice(b"MThd");
    h.extend_from_slice(&6u32.to_be_bytes());
    h.extend_from_slice(&format.to_be_bytes());
    h.extend_from_slice(&ntracks.to_be_bytes());
    h.extend_from_slice(&division.to_be_bytes());
    h
}

fn build_track_events(
    notes: &[&Note],
    is_line_start: &[bool],
    gap_ticks: u32,
    track_name: Option<&str>,
    channel: u8,
    tempo_us: Option<u32>,
) -> Vec<TimedEvent> {
    let mut events = Vec::new();

    if let Some(tempo) = tempo_us {
        events.push(TimedEvent {
            tick: 0,
            priority: 0,
            msg: MidiMessage::SetTempo(tempo),
        });
    }

    if let Some(name) = track_name {
        events.push(TimedEvent {
            tick: 0,
            priority: 1,
            msg: MidiMessage::TrackName(name.to_string()),
        });
    }

    for (idx, note) in notes.iter().enumerate() {
        let start_tick = gap_ticks + (note.start_beat.max(0) as u32) * TICKS_PER_BEAT;
        let dur_ticks = (note.duration_beats.max(1) as u32) * TICKS_PER_BEAT;
        let end_tick = start_tick + dur_ticks;

        let raw_text = note.text.as_str();
        let lyric_text = if raw_text.trim() == "~" {
            String::new()
        } else if is_line_start.get(idx).copied().unwrap_or(false) && !raw_text.starts_with('/') {
            format!("/{}", raw_text)
        } else {
            raw_text.to_string()
        };

        events.push(TimedEvent {
            tick: start_tick,
            priority: 2,
            msg: MidiMessage::Lyric(lyric_text),
        });

        if note.note_type != "F" {
            // UltraStar pitch 0 = C4 = MIDI note 60
            let midi_pitch = (note.pitch + 60).clamp(0, 127) as u8;
            events.push(TimedEvent {
                tick: start_tick,
                priority: 4,
                msg: MidiMessage::NoteOn {
                    channel,
                    note: midi_pitch,
                    velocity: 100,
                },
            });
            events.push(TimedEvent {
                tick: end_tick,
                priority: 3,
                msg: MidiMessage::NoteOff {
                    channel,
                    note: midi_pitch,
                },
            });
        }
    }

    let max_tick = events.iter().map(|e| e.tick).max().unwrap_or(0);
    events.push(TimedEvent {
        tick: max_tick,
        priority: 99,
        msg: MidiMessage::EndOfTrack,
    });

    events.sort_by(|a, b| a.tick.cmp(&b.tick).then_with(|| a.priority.cmp(&b.priority)));
    events
}

impl Song {
    /// Converte a música em um arquivo Standard MIDI File (SMF) com letra embutida.
    pub fn to_midi(&self) -> Vec<u8> {
        let bpm = self.bpm.max(1.0);
        let us_per_quarter = (60_000_000.0 / bpm).round().clamp(1.0, 16_777_215.0) as u32;
        let gap_ms = self.gap_ms.max(0);
        // gap_ms para ticks: 1 semínima = 480 ticks = 60000/bpm ms => 1 ms = (480*bpm)/60000 ticks = (8*bpm)/1000 ticks
        let gap_ticks = ((gap_ms as f64) * 8.0 * bpm / 1000.0).round().max(0.0) as u32;

        let phrase_breaks: HashSet<usize> = self.phrase_breaks_after_index.iter().cloned().collect();

        if self.duet {
            // Formato 1: Track 0 = Conductor, Track 1 = P1, Track 2 = P2
            let mut out = Vec::new();
            out.extend_from_slice(&encode_header(1, 3, PPQ));

            // Track 0: Conductor
            let mut cond_events = Vec::new();
            cond_events.push(TimedEvent {
                tick: 0,
                priority: 0,
                msg: MidiMessage::TrackName(self.title.clone()),
            });
            cond_events.push(TimedEvent {
                tick: 0,
                priority: 1,
                msg: MidiMessage::SetTempo(us_per_quarter),
            });
            cond_events.push(TimedEvent {
                tick: 0,
                priority: 99,
                msg: MidiMessage::EndOfTrack,
            });
            out.extend_from_slice(&encode_track(&cond_events));

            // Filtra notas P1 e P2 preservando flags de quebra de frase
            let (p1_notes, p1_starts) = self.filter_singer_notes(&[1, 3], &phrase_breaks);
            let p1_name = self.p1_name.as_deref().unwrap_or("P1");
            let p1_events = build_track_events(&p1_notes, &p1_starts, gap_ticks, Some(p1_name), 0, None);
            out.extend_from_slice(&encode_track(&p1_events));

            let (p2_notes, p2_starts) = self.filter_singer_notes(&[2, 3], &phrase_breaks);
            let p2_name = self.p2_name.as_deref().unwrap_or("P2");
            let p2_events = build_track_events(&p2_notes, &p2_starts, gap_ticks, Some(p2_name), 1, None);
            out.extend_from_slice(&encode_track(&p2_events));

            out
        } else {
            // Formato 0: faixa única com tempo + notas + letra
            let mut out = Vec::new();
            out.extend_from_slice(&encode_header(0, 1, PPQ));

            let mut is_line_start = Vec::with_capacity(self.notes.len());
            for i in 0..self.notes.len() {
                let start = (i == 0) || (i > 0 && phrase_breaks.contains(&(i - 1)));
                is_line_start.push(start);
            }
            let note_refs: Vec<&Note> = self.notes.iter().collect();
            let events = build_track_events(
                &note_refs,
                &is_line_start,
                gap_ticks,
                Some(&self.title),
                0,
                Some(us_per_quarter),
            );
            out.extend_from_slice(&encode_track(&events));
            out
        }
    }

    fn filter_singer_notes<'a>(
        &'a self,
        singers: &[i64],
        phrase_breaks: &HashSet<usize>,
    ) -> (Vec<&'a Note>, Vec<bool>) {
        let mut notes = Vec::new();
        let mut is_start = Vec::new();
        let mut prev_global_idx: Option<usize> = None;

        for (idx, note) in self.notes.iter().enumerate() {
            if singers.contains(&note.singer) {
                let start = match prev_global_idx {
                    None => true,
                    Some(p_idx) => {
                        // Se houve phrase break entre p_idx e idx
                        (p_idx..idx).any(|k| phrase_breaks.contains(&k))
                    }
                };
                notes.push(note);
                is_start.push(start);
                prev_global_idx = Some(idx);
            }
        }
        (notes, is_start)
    }

    /// Grava a representação MIDI (.mid) em disco.
    pub fn write_midi(&self, path: impl AsRef<Path>) -> io::Result<()> {
        fs::write(path, self.to_midi())
    }
}

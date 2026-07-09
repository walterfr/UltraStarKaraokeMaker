//! uskmaker-core
//! Fase 1: núcleo Rust do USKMaker. Por enquanto contém só o
//! ultrastar_writer (geração do .txt a partir do JSON intermediário
//! exportado pelo python-sidecar). Na Fase 2, este crate ganha o
//! sidecar.rs (orquestração do processo Python via Tauri) e é
//! incorporado ao src-tauri/.

pub mod ultrastar_writer;

pub use ultrastar_writer::{Note, Song};

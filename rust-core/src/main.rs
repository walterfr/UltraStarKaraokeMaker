//! uskmaker-writer (bin)
//! CLI standalone para testar o ultrastar_writer.rs isoladamente, sem
//! precisar do Tauri ainda (isso é Fase 2). Lê o JSON intermediário
//! exportado pelo python-sidecar (song_data.json) e escreve o .txt final.
//!
//! USO:
//!     cargo run --bin uskmaker-writer -- caminho/song_data.json caminho/saida.txt

use std::env;
use std::process;
use uskmaker_core::Song;

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 3 {
        eprintln!("Uso: uskmaker-writer <entrada.json> <saida.txt>");
        process::exit(1);
    }

    let json_path = &args[1];
    let txt_path = &args[2];

    let song = match Song::from_json_file(json_path) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("Erro ao ler JSON '{}': {}", json_path, e);
            process::exit(1);
        }
    };

    if let Err(e) = song.write(txt_path) {
        eprintln!("Erro ao escrever .txt '{}': {}", txt_path, e);
        process::exit(1);
    }

    println!("[OK] .txt gerado em: {}", txt_path);
}

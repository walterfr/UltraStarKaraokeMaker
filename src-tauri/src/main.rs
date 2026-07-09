// USKMaker - src-tauri/src/main.rs
// Fase 2: integração Tauri + sidecar Python.
//
// Fluxo:
//   1. Frontend chama `run_pipeline` com os dados do formulário.
//   2. Rust grava a letra num arquivo temporário e invoca o venv Python
//      (python-sidecar/main.py) como subprocesso.
//   3. Quando o Python termina (e já exportou song_data.json - ver Fase 1),
//      o Rust lê esse JSON com uskmaker_core::Song e É QUEM ESCREVE o .txt
//      final - o Python deixa de ser o dono do formato de saída a partir
//      daqui, cumprindo o objetivo original de arquitetura do projeto.
//
// BUG CRÍTICO CORRIGIDO (06/07/2026) - captura de saída do processo Python:
// A primeira versão usava `Stdio::piped()` (pipe assíncrono/"overlapped"
// do Tokio) para capturar stdout/stderr do Python em tempo real. Isso
// causava `OSError: [Errno 22] Invalid argument` do lado Python ao tentar
// escrever no pipe - causa raiz: o Tokio cria esse pipe em modo
// "overlapped" (I/O assíncrono do Windows) para poder ler de forma
// assíncrona, mas o processo Python escreve nele de forma SÍNCRONA/
// bloqueante. Essa mistura (escrita síncrona num handle criado para I/O
// assíncrono) é um cenário conhecido de gerar exatamente esse erro no
// Windows. Isso não tinha solução razoável do lado Python (tentamos
// capturar a saída dos subprocessos internos, imprimir linha por linha,
// forçar line-buffering - nada disso resolveu, porque a causa era
// estrutural do lado Rust).
//
// CORREÇÃO: em vez de conectar o Python direto a um pipe assíncrono, a
// saída dele é redirecionada para um ARQUIVO em disco (escrita síncrona
// normal, sem conflito nenhum de modo de I/O). O Rust "acompanha" esse
// arquivo periodicamente (como um `tail -f`), retransmitindo cada linha
// nova para o frontend via evento `pipeline-log`. Mais simples e muito
// mais robusto no Windows.
//
// SIMPLIFICAÇÃO CONHECIDA (Fase 2, ainda não é produção): o caminho do
// python-sidecar é resolvido via CARGO_MANIFEST_DIR (pasta irmã de
// src-tauri dentro do repositório). Isso funciona bem em desenvolvimento,
// mas não sobrevive a um build empacotado para distribuição - quando
// chegarmos lá, o caminho correto é compilar o python-sidecar com
// PyInstaller e referenciá-lo via `externalBin` do Tauri (sidecar de
// verdade, não só "chamar python instalado").

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::{Deserialize, Serialize};
use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use tauri::Window;
use tokio::process::Command;
use tokio::sync::watch;
use tokio::time::{sleep, Duration};
use uskmaker_core::Song;

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PipelineInput {
    youtube_url: Option<String>,
    file_path: Option<String>,
    lyrics_text: String,
    title: String,
    artist: String,
    language: String,
    bpm: Option<f64>,
    out_dir: String,
    #[serde(default)]
    with_video: bool,
    #[serde(default)]
    clean_work: bool,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
struct PipelineResult {
    txt_path: String,
    audio_path: String,
    out_dir: String,
    // Fase 3: metadados incluídos no pacote, para a UI exibir um resumo
    // ("capa incluída", ano, gênero) ao final. Todos opcionais - vêm do
    // song_data.json, que por sua vez veio da cascata de metadados do
    // Python (tags embutidas -> MusicBrainz/CAA).
    cover_path: Option<String>,
    year: Option<i64>,
    genre: Option<String>,
}

/// Pasta do python-sidecar, resolvida a partir da pasta deste crate
/// (src-tauri) em tempo de compilação. Ver nota de simplificação no topo
/// do arquivo.
fn sidecar_root() -> PathBuf {
    let manifest_dir = env!("CARGO_MANIFEST_DIR");
    Path::new(manifest_dir).join("..").join("python-sidecar")
}

fn venv_python() -> PathBuf {
    sidecar_root().join("venv").join("Scripts").join("python.exe")
}

/// Acompanha um arquivo de log que está sendo escrito por outro processo
/// (como um `tail -f`), emitindo cada linha nova via evento `pipeline-log`
/// assim que aparece. Para quando `stop_rx` sinaliza (processo terminou),
/// mas ainda faz uma última leitura antes de sair, para não perder
/// nenhuma linha final que tenha sido escrita entre o último poll e o
/// processo terminar.
async fn tail_file_and_emit(window: Window, path: PathBuf, mut stop_rx: watch::Receiver<bool>) {
    let mut last_pos: u64 = 0;
    let mut leftover = String::new();

    loop {
        read_new_lines(&path, &mut last_pos, &mut leftover, &window);

        if *stop_rx.borrow() {
            break;
        }

        tokio::select! {
            _ = sleep(Duration::from_millis(200)) => {}
            _ = stop_rx.changed() => {}
        }
    }

    // uma última leitura, para pegar qualquer coisa escrita entre o
    // último poll e o processo terminar
    read_new_lines(&path, &mut last_pos, &mut leftover, &window);
    if !leftover.trim().is_empty() {
        let _ = window.emit("pipeline-log", leftover.trim_end().to_string());
    }
}

fn read_new_lines(path: &Path, last_pos: &mut u64, leftover: &mut String, window: &Window) {
    let Ok(mut file) = File::open(path) else {
        return; // arquivo pode não existir ainda no primeiro poll - tudo bem
    };
    if file.seek(SeekFrom::Start(*last_pos)).is_err() {
        return;
    }
    let mut buf = String::new();
    // Se der erro (ex.: leu no meio de um caractere UTF-8 multibyte sendo
    // escrito), simplesmente ignora este poll - pega na próxima rodada.
    if file.read_to_string(&mut buf).is_err() || buf.is_empty() {
        return;
    }
    *last_pos += buf.len() as u64;
    leftover.push_str(&buf);

    while let Some(idx) = leftover.find('\n') {
        let line: String = leftover.drain(..=idx).collect();
        let line = line.trim_end_matches(['\r', '\n']);
        let _ = window.emit("pipeline-log", line.to_string());
    }
}

#[tauri::command]
async fn run_pipeline(window: Window, input: PipelineInput) -> Result<PipelineResult, String> {
    let sidecar_dir = sidecar_root();
    let python_exe = venv_python();

    if !python_exe.exists() {
        return Err(format!(
            "Python do venv não encontrado em '{}'. Confira se o venv do python-sidecar foi criado (ver README).",
            python_exe.display()
        ));
    }

    let out_dir = PathBuf::from(&input.out_dir);
    std::fs::create_dir_all(&out_dir)
        .map_err(|e| format!("Erro ao criar pasta de saída '{}': {}", out_dir.display(), e))?;

    let lyrics_path = out_dir.join("_lyrics_input.txt");
    std::fs::write(&lyrics_path, &input.lyrics_text)
        .map_err(|e| format!("Erro ao gravar arquivo de letra: {}", e))?;

    // Arquivo de log combinado (stdout+stderr) que o Python escreve de
    // forma síncrona normal - ver nota grande no topo do arquivo sobre
    // por que isso substituiu Stdio::piped().
    let log_path = out_dir.join("_process_output.log");
    let stdout_file = File::create(&log_path)
        .map_err(|e| format!("Erro ao criar arquivo de log '{}': {}", log_path.display(), e))?;
    let stderr_file = stdout_file
        .try_clone()
        .map_err(|e| format!("Erro ao clonar handle do arquivo de log: {}", e))?;

    let mut cmd = Command::new(&python_exe);
    cmd.current_dir(&sidecar_dir)
        .arg("main.py")
        .arg("--lyrics")
        .arg(&lyrics_path)
        .arg("--title")
        .arg(&input.title)
        .arg("--artist")
        .arg(&input.artist)
        .arg("--language")
        .arg(&input.language)
        .arg("--out")
        .arg(&out_dir)
        .stdout(stdout_file)
        .stderr(stderr_file);

    if let Some(bpm) = input.bpm {
        cmd.arg("--bpm").arg(bpm.to_string());
    }

    if input.with_video {
        cmd.arg("--with-video");
    }

    if input.clean_work {
        cmd.arg("--clean-work");
    }

    match (&input.youtube_url, &input.file_path) {
        (Some(url), _) if !url.trim().is_empty() => {
            cmd.arg("--url").arg(url);
        }
        (_, Some(file)) if !file.trim().is_empty() => {
            cmd.arg("--file").arg(file);
        }
        _ => {
            return Err("Forneça um link do YouTube ou um arquivo de áudio local.".into());
        }
    }

    let mut child = cmd
        .spawn()
        .map_err(|e| format!("Erro ao iniciar o processo Python: {}", e))?;

    let (stop_tx, stop_rx) = watch::channel(false);
    let tail_window = window.clone();
    let tail_log_path = log_path.clone();
    let tail_task = tokio::spawn(tail_file_and_emit(tail_window, tail_log_path, stop_rx));

    let status = child
        .wait()
        .await
        .map_err(|e| format!("Erro ao aguardar o processo Python: {}", e))?;

    let _ = stop_tx.send(true);
    let _ = tail_task.await;

    if !status.success() {
        return Err(format!(
            "Pipeline Python terminou com erro (código {:?}). Veja o log acima para detalhes \
             (também salvo em '{}' e em 'pipeline_debug.log' na pasta de saída).",
            status.code(),
            log_path.display()
        ));
    }

    // O Python já exportou song_data.json (Fase 1) - a partir daqui, o
    // Rust é quem escreve o .txt final, usando o mesmo rust-core validado
    // contra dados reais.
    let json_path = out_dir.join("song_data.json");
    let song = Song::from_json_file(&json_path)
        .map_err(|e| format!("Erro ao ler JSON intermediário '{}': {}", json_path.display(), e))?;

    let txt_path = out_dir.join(format!("{} - {}.txt", input.artist, input.title));
    song.write(&txt_path)
        .map_err(|e| format!("Erro ao escrever .txt final: {}", e))?;

    let audio_path = out_dir.join(&song.mp3_filename);

    // Fase 3: se o Python salvou uma capa, ela está na pasta de saída com o
    // nome referenciado na tag #COVER do song. Confirma que o arquivo
    // existe de fato antes de reportar à UI (a capa é opcional - pode não
    // ter sido encontrada em nenhuma fonte).
    let cover_path = song.cover_filename.as_ref().and_then(|name| {
        let p = out_dir.join(name);
        if p.exists() {
            Some(p.to_string_lossy().to_string())
        } else {
            None
        }
    });

    Ok(PipelineResult {
        txt_path: txt_path.to_string_lossy().to_string(),
        audio_path: audio_path.to_string_lossy().to_string(),
        out_dir: out_dir.to_string_lossy().to_string(),
        cover_path,
        year: song.year,
        genre: song.genre.clone(),
    })
}

#[tauri::command]
fn open_folder(path: String) -> Result<(), String> {
    // Windows-only por enquanto (Fase 2 é dev no Windows) - abre o
    // Explorer na pasta de saída informada.
    std::process::Command::new("explorer")
        .arg(path)
        .spawn()
        .map_err(|e| format!("Erro ao abrir a pasta: {}", e))?;
    Ok(())
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![run_pipeline, open_folder])
        .run(tauri::generate_context!())
        .expect("erro ao rodar a aplicação Tauri");
}

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
// DISTRIBUIÇÃO (07/07/2026): o caminho do python-sidecar agora é resolvido
// em CASCATA, suportando dev e produção com o mesmo binário:
//   1. DEV: CARGO_MANIFEST_DIR/../python-sidecar com venv local (o fluxo
//      de desenvolvimento continua idêntico ao que sempre foi).
//   2. PRODUÇÃO (app instalado): o CÓDIGO do sidecar é empacotado como
//      resource do Tauri (só os .py, poucos KB) e o VENV é criado pelo
//      usuário via scripts/setup-sidecar.ps1 em %LOCALAPPDATA%\USKMaker\venv
//      (fora do Program Files, que é somente-leitura). Decisão consciente:
//      NÃO usamos PyInstaller - empacotar torch CUDA geraria um binário de
//      vários GB (não cabe em release do GitHub, limite 2 GB/arquivo) e o
//      PyInstaller é frágil com whisperx/demucs. O venv real, criado na
//      máquina do usuário com o build de torch certo pro hardware dele
//      (CUDA ou CPU), é mais robusto e mais leve de distribuir.
// Detalhe do Tauri v1: resources declarados com "../" são instalados sob
// uma pasta "_up_" dentro do resource_dir - a resolução checa esse caminho.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::{Deserialize, Serialize};
use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use tauri::Window;
use tokio::process::Command;
use tokio::sync::watch;
use tokio::time::{sleep, Duration};
use uskmaker_core::Song;

/// Flag do Windows para criar subprocessos sem janela de console piscando
/// (CREATE_NO_WINDOW) - relevante porque o app roda como GUI.
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// Estado compartilhado da geração em andamento - existe para o botão
/// Cancelar da UI. Guardamos só o PID (não o Child inteiro) porque o
/// run_pipeline precisa continuar dono do handle para dar .wait().
#[derive(Default)]
struct PipelineState {
    child_pid: Mutex<Option<u32>>,
    cancel_requested: AtomicBool,
}

/// Mensagem-sentinela que o frontend usa para distinguir "cancelado pelo
/// usuário" (informativo, azul) de erro real (vermelho).
const CANCELLED_MSG: &str = "__CANCELADO__";

/// Remove caracteres inválidos em nomes de pasta/arquivo do Windows
/// (< > : " / \ | ? *), além de espaços e pontos nas bordas (pastas
/// terminadas em ponto/espaço são problemáticas no Explorer).
fn sanitize_path_component(s: &str) -> String {
    let cleaned: String = s
        .chars()
        .map(|c| match c {
            '<' | '>' | ':' | '"' | '/' | '\\' | '|' | '?' | '*' => '_',
            c if (c as u32) < 0x20 => '_',
            c => c,
        })
        .collect();
    cleaned.trim().trim_end_matches('.').trim().to_string()
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PipelineInput {
    youtube_url: Option<String>,
    file_path: Option<String>,
    lyrics_text: String,
    /// Letra sincronizada .lrc (LRCLIB), opcional. Quando presente, o sidecar
    /// usa os tempos de início de linha como âncoras no alinhamento.
    #[serde(default)]
    synced_lyrics: Option<String>,
    title: String,
    artist: String,
    language: String,
    bpm: Option<f64>,
    out_dir: String,
    #[serde(default)]
    with_video: bool,
    /// Fonte local: baixar um videoclipe do YouTube só para o fundo
    /// (#VIDEO) - o áudio do pacote continua sendo o arquivo local.
    #[serde(default)]
    bg_video: bool,
    /// URL específica do videoclipe de fundo; vazia = busca automática
    /// por artista + título no YouTube.
    #[serde(default)]
    bg_video_url: Option<String>,
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
    // UX (07/2026): estatísticas de confiança do alinhamento para o
    // resultado rico - quantas notas foram MEDIDAS no áudio vs ESTIMADAS
    // (interpoladas). Vêm do campo `source` de cada nota do song_data.json.
    notes_total: usize,
    notes_estimated: usize,
}

/// Resolução em cascata do sidecar (ver nota DISTRIBUIÇÃO no topo).
/// Retorna (pasta do código python, caminho do python.exe do venv).
fn resolve_sidecar(app: &tauri::AppHandle) -> Result<(PathBuf, PathBuf), String> {
    // 1) DEV: pasta irmã do repositório, com venv local (fluxo clássico).
    let dev_code = Path::new(env!("CARGO_MANIFEST_DIR")).join("..").join("python-sidecar");
    let dev_python = dev_code.join("venv").join("Scripts").join("python.exe");
    if dev_python.exists() {
        return Ok((dev_code, dev_python));
    }

    // 2) PRODUÇÃO: código nos resources do app + venv no LOCALAPPDATA.
    let resource_dir = app
        .path_resolver()
        .resource_dir()
        .ok_or_else(|| "Não foi possível localizar a pasta de resources do app.".to_string())?;
    // Tauri v1 instala resources declarados com "../" sob "_up_".
    let code_candidates = [
        resource_dir.join("_up_").join("python-sidecar"),
        resource_dir.join("python-sidecar"),
    ];
    let code_dir = code_candidates
        .iter()
        .find(|p| p.join("main.py").exists())
        .cloned()
        .ok_or_else(|| {
            "Código do sidecar não encontrado nos resources do app (reinstale o USKMaker).".to_string()
        })?;

    let local_app_data = std::env::var("LOCALAPPDATA")
        .map_err(|_| "Variável LOCALAPPDATA não definida.".to_string())?;
    let venv_python = Path::new(&local_app_data)
        .join("USKMaker")
        .join("venv")
        .join("Scripts")
        .join("python.exe");

    if !venv_python.exists() {
        return Err(format!(
            "O ambiente de IA ainda não foi configurado.\n\n\
             Execute o script 'setup-sidecar.ps1' (na pasta de instalação do USKMaker) \
             uma única vez para instalar as dependências. Esperado em: {}",
            venv_python.display()
        ));
    }

    Ok((code_dir, venv_python))
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
    // BUG CORRIGIDO (10/07/2026): a versão anterior usava read_to_string,
    // que FALHA se houver qualquer byte não-UTF-8 - e sem avançar last_pos,
    // falhava para sempre: a UI ficava sem NENHUMA linha de log. Era o que
    // acontecia quando o Python escrevia em cp1252 (ex.: o "—" das réguas
    // do rich vira 0x97). Agora lemos BYTES e convertemos com perdas
    // (from_utf8_lossy): um caractere estranho vira "�", mas o log flui.
    // O run_pipeline também passou a exportar PYTHONUTF8=1, então o caso
    // nem deve mais ocorrer - isto aqui é a rede de segurança.
    let mut bytes = Vec::new();
    if file.read_to_end(&mut bytes).is_err() || bytes.is_empty() {
        return;
    }
    let buf = String::from_utf8_lossy(&bytes).into_owned();
    *last_pos += bytes.len() as u64;
    leftover.push_str(&buf);

    while let Some(idx) = leftover.find('\n') {
        let line: String = leftover.drain(..=idx).collect();
        let line = line.trim_end_matches(['\r', '\n']);
        let _ = window.emit("pipeline-log", line.to_string());
    }
}

#[tauri::command]
async fn run_pipeline(
    app: tauri::AppHandle,
    window: Window,
    state: tauri::State<'_, PipelineState>,
    input: PipelineInput,
) -> Result<PipelineResult, String> {
    let (sidecar_dir, python_exe) = resolve_sidecar(&app)?;
    state.cancel_requested.store(false, Ordering::SeqCst);

    // UX (07/2026): o pacote vai para uma SUBPASTA "Artista - Título" dentro
    // da pasta escolhida - padrão das coleções UltraStar (uma pasta por
    // música dentro do diretório Songs do jogo). Reprocessar a mesma música
    // cai na mesma subpasta e reaproveita os intermediários.
    let package_folder = sanitize_path_component(&format!("{} - {}", input.artist, input.title));
    let out_dir = PathBuf::from(&input.out_dir).join(package_folder);
    std::fs::create_dir_all(&out_dir)
        .map_err(|e| format!("Erro ao criar pasta de saída '{}': {}", out_dir.display(), e))?;

    let lyrics_path = out_dir.join("_lyrics_input.txt");
    std::fs::write(&lyrics_path, &input.lyrics_text)
        .map_err(|e| format!("Erro ao gravar arquivo de letra: {}", e))?;

    // Letra sincronizada (.lrc) opcional, vinda do LRCLIB. Só grava se veio
    // conteúdo de fato - assim o sidecar só recebe --synced-lyrics quando há
    // algo para semear.
    let synced_path = match input.synced_lyrics.as_deref().map(str::trim) {
        Some(lrc) if !lrc.is_empty() => {
            let p = out_dir.join("_synced_lyrics.lrc");
            std::fs::write(&p, lrc)
                .map_err(|e| format!("Erro ao gravar letra sincronizada: {}", e))?;
            Some(p)
        }
        _ => None,
    };

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
        // Força o Python a escrever stdout/stderr em UTF-8 mesmo redirecionado
        // para arquivo (sem isso o Windows usa cp1252 e o tail de log quebrava
        // nos caracteres fora do ASCII - ver nota em read_new_lines).
        .env("PYTHONUTF8", "1")
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

    match &input.bg_video_url {
        Some(url) if !url.trim().is_empty() => {
            cmd.arg("--bg-video-url").arg(url.trim());
        }
        _ if input.bg_video => {
            cmd.arg("--bg-video");
        }
        _ => {}
    }

    if input.clean_work {
        cmd.arg("--clean-work");
    }

    if let Some(ref p) = synced_path {
        cmd.arg("--synced-lyrics").arg(p);
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

    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);

    let mut child = cmd
        .spawn()
        .map_err(|e| format!("Erro ao iniciar o processo Python: {}", e))?;

    // registra o PID para o botão Cancelar da UI
    *state.child_pid.lock().unwrap() = child.id();

    let (stop_tx, stop_rx) = watch::channel(false);
    let tail_window = window.clone();
    let tail_log_path = log_path.clone();
    let tail_task = tokio::spawn(tail_file_and_emit(tail_window, tail_log_path, stop_rx));

    let status = child
        .wait()
        .await
        .map_err(|e| format!("Erro ao aguardar o processo Python: {}", e))?;

    *state.child_pid.lock().unwrap() = None;

    let _ = stop_tx.send(true);
    let _ = tail_task.await;

    if !status.success() {
        // cancelamento pedido pela UI não é erro - devolve a sentinela para
        // o frontend mostrar um aviso neutro em vez de caixa vermelha
        if state.cancel_requested.load(Ordering::SeqCst) {
            return Err(CANCELLED_MSG.to_string());
        }
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

    let notes_total = song.notes.len();
    let notes_estimated = song
        .notes
        .iter()
        .filter(|n| n.source.as_deref() == Some("interpolated"))
        .count();

    Ok(PipelineResult {
        txt_path: txt_path.to_string_lossy().to_string(),
        audio_path: audio_path.to_string_lossy().to_string(),
        out_dir: out_dir.to_string_lossy().to_string(),
        cover_path,
        year: song.year,
        genre: song.genre.clone(),
        notes_total,
        notes_estimated,
    })
}

/// Cancela a geração em andamento: mata a ÁRVORE de processos do sidecar
/// (taskkill /T) - só matar o python.exe deixaria ffmpeg/yt-dlp filhos
/// órfãos rodando. O run_pipeline percebe a morte no .wait() e devolve a
/// sentinela CANCELLED_MSG em vez de erro.
#[tauri::command]
async fn cancel_pipeline(state: tauri::State<'_, PipelineState>) -> Result<(), String> {
    state.cancel_requested.store(true, Ordering::SeqCst);
    let pid = *state.child_pid.lock().unwrap();
    let Some(pid) = pid else {
        return Ok(()); // nada rodando - cancelamento vira no-op
    };
    let mut kill = Command::new("taskkill");
    kill.args(["/PID", &pid.to_string(), "/T", "/F"]);
    #[cfg(windows)]
    kill.creation_flags(CREATE_NO_WINDOW);
    kill.output()
        .await
        .map_err(|e| format!("Erro ao cancelar o processo: {}", e))?;
    Ok(())
}

// ---------------------------------------------------------------------------
// Checagem de ambiente (UX): roda na abertura do app para o usuário descobrir
// problemas de instalação ANTES de gastar minutos numa geração que vai falhar.
// ---------------------------------------------------------------------------

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct EnvCheck {
    sidecar_ok: bool,
    sidecar_msg: String,
    ffmpeg_ok: bool,
    /// libvorbis é necessário para gerar o .ogg do pacote
    vorbis_ok: bool,
    /// nome da GPU NVIDIA, ou None = processamento em CPU (bem mais lento)
    gpu_name: Option<String>,
}

#[tauri::command]
async fn check_environment(app: tauri::AppHandle) -> Result<EnvCheck, String> {
    let (sidecar_ok, sidecar_msg) = match resolve_sidecar(&app) {
        Ok((_, python)) => (true, python.display().to_string()),
        Err(e) => (false, e),
    };

    let mut ffmpeg_cmd = Command::new("ffmpeg");
    ffmpeg_cmd.arg("-version");
    #[cfg(windows)]
    ffmpeg_cmd.creation_flags(CREATE_NO_WINDOW);
    let (ffmpeg_ok, vorbis_ok) = match ffmpeg_cmd.output().await {
        Ok(out) if out.status.success() => {
            let text = String::from_utf8_lossy(&out.stdout).to_string();
            (true, text.contains("libvorbis"))
        }
        _ => (false, false),
    };

    let mut gpu_cmd = Command::new("nvidia-smi");
    gpu_cmd.args(["--query-gpu=name", "--format=csv,noheader"]);
    #[cfg(windows)]
    gpu_cmd.creation_flags(CREATE_NO_WINDOW);
    let gpu_name = match gpu_cmd.output().await {
        Ok(out) if out.status.success() => {
            let name = String::from_utf8_lossy(&out.stdout).lines().next().unwrap_or("").trim().to_string();
            if name.is_empty() { None } else { Some(name) }
        }
        _ => None,
    };

    Ok(EnvCheck {
        sidecar_ok,
        sidecar_msg,
        ffmpeg_ok,
        vorbis_ok,
        gpu_name,
    })
}

// ---------------------------------------------------------------------------
// Tela de revisão manual (estilo Yass) - Fase 4.
//
// O contrato continua o mesmo da arquitetura original: o song_data.json é a
// fonte da verdade e o rust-core é o único que escreve o .txt. A tela de
// revisão carrega esse JSON, deixa o usuário ajustar notas/tempos/quebras na
// UI e, ao salvar, regrava o JSON E regenera o .txt pelo mesmo caminho de
// código já validado - nada de segunda implementação do formato.
// ---------------------------------------------------------------------------

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct ReviewData {
    song: Song,
    /// Áudio do pacote (.ogg) - None se o arquivo sumiu da pasta.
    audio_path: Option<String>,
    /// Stem vocal isolado (se a pasta _work foi mantida) - ouvir só a voz
    /// facilita muito conferir o timing das sílabas.
    vocals_path: Option<String>,
    out_dir: String,
}

#[tauri::command]
fn load_song(out_dir: String) -> Result<ReviewData, String> {
    let dir = PathBuf::from(&out_dir);
    let json_path = dir.join("song_data.json");
    if !json_path.exists() {
        return Err(format!(
            "Não encontrei 'song_data.json' em '{}'. Selecione a pasta de um pacote \
             gerado pelo USKMaker (a mesma escolhida como saída na geração).",
            dir.display()
        ));
    }
    let song = Song::from_json_file(&json_path)
        .map_err(|e| format!("Erro ao ler '{}': {}", json_path.display(), e))?;

    let audio = dir.join(&song.mp3_filename);
    let audio_path = audio
        .exists()
        .then(|| audio.to_string_lossy().to_string());

    // O stem vocal fica em _work/stems/htdemucs/<nome da música>/vocals.wav
    // quando o usuário NÃO marcou "remover intermediários".
    let mut vocals_path = None;
    let stems_dir = dir.join("_work").join("stems").join("htdemucs");
    if let Ok(entries) = std::fs::read_dir(&stems_dir) {
        for entry in entries.flatten() {
            let candidate = entry.path().join("vocals.wav");
            if candidate.exists() {
                vocals_path = Some(candidate.to_string_lossy().to_string());
                break;
            }
        }
    }

    Ok(ReviewData {
        song,
        audio_path,
        vocals_path,
        out_dir: dir.to_string_lossy().to_string(),
    })
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct SaveResult {
    txt_path: String,
    /// Avisos de validação (ex.: notas sobrepostas) - o arquivo é escrito
    /// mesmo assim, espelhando o comportamento de sempre do rust-core.
    warnings: Vec<String>,
}

#[tauri::command]
fn save_song(out_dir: String, song: Song) -> Result<SaveResult, String> {
    let dir = PathBuf::from(&out_dir);

    let json_path = dir.join("song_data.json");
    let json = serde_json::to_string_pretty(&song)
        .map_err(|e| format!("Erro ao serializar o song_data.json: {}", e))?;
    std::fs::write(&json_path, json)
        .map_err(|e| format!("Erro ao gravar '{}': {}", json_path.display(), e))?;

    let txt_path = dir.join(format!("{} - {}.txt", song.artist, song.title));
    song.write(&txt_path)
        .map_err(|e| format!("Erro ao escrever '{}': {}", txt_path.display(), e))?;

    Ok(SaveResult {
        txt_path: txt_path.to_string_lossy().to_string(),
        warnings: song.validate_no_overlap(),
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
        .manage(PipelineState::default())
        .invoke_handler(tauri::generate_handler![
            run_pipeline,
            open_folder,
            load_song,
            save_song,
            cancel_pipeline,
            check_environment
        ])
        .run(tauri::generate_context!())
        .expect("erro ao rodar a aplicação Tauri");
}

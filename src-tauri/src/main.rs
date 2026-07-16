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
use std::process::Stdio;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use tauri::{Manager, Window};
use tokio::io::AsyncWriteExt;
use tokio::process::{ChildStdin, Command};
use tokio::sync::watch;
use tokio::time::{sleep, Duration};
use uskmaker_core::Song;

/// Flag do Windows para criar subprocessos sem janela de console piscando
/// (CREATE_NO_WINDOW) - relevante porque o app roda como GUI.
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// Trait que expõe `.creation_flags()` no `std::process::Command` (o do
/// tokio já traz o método embutido).
#[cfg(windows)]
use std::os::windows::process::CommandExt as _;

/// Sidecar Python PERSISTENTE: fica vivo entre músicas para manter os modelos
/// de IA quentes (ver server.py + caches em pipeline/align.py). O Rust manda
/// cada job pela stdin e espera o arquivo de status aparecer na pasta de saída.
struct ServerHandle {
    child: tokio::process::Child,
    stdin: ChildStdin,
}

/// Estado compartilhado da geração em andamento. `server` guarda o sidecar
/// persistente (reusado entre jobs da fila); `child_pid` é o PID dele, usado
/// pelo botão Cancelar (que mata a árvore e força um respawn frio no próximo
/// job); `cancel_requested` distingue cancelamento de erro real.
#[derive(Default)]
struct PipelineState {
    server: tokio::sync::Mutex<Option<ServerHandle>>,
    child_pid: Mutex<Option<u32>>,
    cancel_requested: AtomicBool,
}

/// Mensagem-sentinela que o frontend usa para distinguir "cancelado pelo
/// usuário" (informativo, azul) de erro real (vermelho).
const CANCELLED_MSG: &str = "__CANCELADO__";

/// Traduz as mensagens de erro que chegam à interface. O Rust não passa pelo
/// i18n do frontend (i18n.tsx), então os templates PT/EN moram aqui. Os
/// placeholders `{path}`/`{err}`/`{venv}`/`{log}` são preenchidos com
/// `.replace()` no ponto de uso. `lang` vem do frontend ("pt" ou "en").
fn tr(lang: &str, key: &str) -> &'static str {
    let en = lang == "en";
    match key {
        "res_dir" => if en { "Could not locate the app's resources folder." } else { "Não foi possível localizar a pasta de resources do app." },
        "code_missing" => if en { "Sidecar code not found in the app resources (reinstall USKMaker)." } else { "Código do sidecar não encontrado nos resources do app (reinstale o USKMaker)." },
        "localappdata" => if en { "LOCALAPPDATA variable is not set." } else { "Variável LOCALAPPDATA não definida." },
        "env_not_setup" => if en { "The AI environment isn't set up yet.\n\nRun the 'setup-sidecar.ps1' script (in the USKMaker install folder) once to install the dependencies. Expected at: {venv}" } else { "O ambiente de IA ainda não foi configurado.\n\nExecute o script 'setup-sidecar.ps1' (na pasta de instalação do USKMaker) uma única vez para instalar as dependências. Esperado em: {venv}" },
        "server_start" => if en { "Error starting the persistent sidecar: {err}" } else { "Erro ao iniciar o sidecar persistente: {err}" },
        "server_stdin" => if en { "Couldn't get the sidecar's stdin." } else { "Não consegui obter a stdin do sidecar." },
        "server_send" => if en { "Error sending the job to the sidecar: {err}" } else { "Erro ao enviar job ao sidecar: {err}" },
        "outdir_create" => if en { "Error creating output folder '{path}': {err}" } else { "Erro ao criar pasta de saída '{path}': {err}" },
        "write_lyrics" => if en { "Error writing the lyrics file: {err}" } else { "Erro ao gravar arquivo de letra: {err}" },
        "write_synced" => if en { "Error writing the synced lyrics: {err}" } else { "Erro ao gravar letra sincronizada: {err}" },
        "need_source" => if en { "Provide a YouTube link or a local audio file." } else { "Forneça um link do YouTube ou um arquivo de áudio local." },
        "job_serialize" => if en { "Error serializing the job: {err}" } else { "Erro ao serializar o job: {err}" },
        "server_died" => if en { "The sidecar exited unexpectedly before finishing. See the log at '{log}'." } else { "O sidecar encerrou inesperadamente antes de concluir. Veja o log em '{log}'." },
        "pipeline_fail" => if en { "Failed to generate the package: {err}\n(full log at '{log}' and in 'pipeline_debug.log')." } else { "Falha ao gerar o pacote: {err}\n(log completo em '{log}' e em 'pipeline_debug.log')." },
        "read_json" => if en { "Error reading intermediate JSON '{path}': {err}" } else { "Erro ao ler JSON intermediário '{path}': {err}" },
        "write_txt_final" => if en { "Error writing the final .txt: {err}" } else { "Erro ao escrever .txt final: {err}" },
        "cancel_fail" => if en { "Error cancelling the process: {err}" } else { "Erro ao cancelar o processo: {err}" },
        "no_song_json" => if en { "Couldn't find 'song_data.json' in '{path}'. Select the folder of a package generated by USKMaker (the same one chosen as the output)." } else { "Não encontrei 'song_data.json' em '{path}'. Selecione a pasta de um pacote gerado pelo USKMaker (a mesma escolhida como saída na geração)." },
        "read_file" => if en { "Error reading '{path}': {err}" } else { "Erro ao ler '{path}': {err}" },
        "json_serialize" => if en { "Error serializing song_data.json: {err}" } else { "Erro ao serializar o song_data.json: {err}" },
        "write_file" => if en { "Error writing '{path}': {err}" } else { "Erro ao gravar '{path}': {err}" },
        "write_txt_path" => if en { "Error writing '{path}': {err}" } else { "Erro ao escrever '{path}': {err}" },
        "open_folder" => if en { "Error opening the folder: {err}" } else { "Erro ao abrir a pasta: {err}" },
        "setup_spawn" => if en { "Error starting the setup: {err}" } else { "Erro ao iniciar o setup: {err}" },
        "setup_failed" => if en { "Setup failed. See the log at '{log}'." } else { "O setup falhou. Veja o log em '{log}'." },
        "read_tags" => if en { "Error reading the file's tags: {err}" } else { "Erro ao ler as tags do arquivo: {err}" },
        "deps_missing" => if en { "The AI environment is incomplete: the libraries {mods} are missing (the setup didn't finish). Run 'Set up AI environment' again." } else { "O ambiente de IA está incompleto: faltam as bibliotecas {mods} (o setup não terminou). Rode 'Configurar ambiente de IA' de novo." },
        _ => "",
    }
}

/// Açúcar: `tr` já com a substituição de `{err}` (caso mais comum).
fn tr_err(lang: &str, key: &str, e: &impl std::fmt::Display) -> String {
    tr(lang, key).replace("{err}", &e.to_string())
}

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

/// Caminho do ffmpeg EMBUTIDO do USKMaker (`%LOCALAPPDATA%\USKMaker\bin\ffmpeg.exe`),
/// obtido pelo setup. `None` = não existe → o pipeline cai para o ffmpeg do
/// PATH (compatível com instalações antigas). Passado ao sidecar via env
/// `USKMAKER_FFMPEG`, removendo a exigência de ffmpeg no PATH do sistema.
fn resolve_ffmpeg() -> Option<PathBuf> {
    let local_app_data = std::env::var("LOCALAPPDATA").ok()?;
    let p = Path::new(&local_app_data)
        .join("USKMaker")
        .join("bin")
        .join("ffmpeg.exe");
    p.exists().then_some(p)
}

/// Resolução em cascata do sidecar (ver nota DISTRIBUIÇÃO no topo).
/// Retorna (pasta do código python, caminho do python.exe do venv).
fn resolve_sidecar(app: &tauri::AppHandle, lang: &str) -> Result<(PathBuf, PathBuf), String> {
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
        .ok_or_else(|| tr(lang, "res_dir").to_string())?;
    // Tauri v1 instala resources declarados com "../" sob "_up_".
    let code_candidates = [
        resource_dir.join("_up_").join("python-sidecar"),
        resource_dir.join("python-sidecar"),
    ];
    let code_dir = code_candidates
        .iter()
        .find(|p| p.join("main.py").exists())
        .cloned()
        .ok_or_else(|| tr(lang, "code_missing").to_string())?;

    let local_app_data = std::env::var("LOCALAPPDATA")
        .map_err(|_| tr(lang, "localappdata").to_string())?;
    let venv_python = Path::new(&local_app_data)
        .join("USKMaker")
        .join("venv")
        .join("Scripts")
        .join("python.exe");

    if !venv_python.exists() {
        return Err(tr(lang, "env_not_setup").replace("{venv}", &venv_python.display().to_string()));
    }

    Ok((code_dir, venv_python))
}

/// Localiza o script de setup (setup-sidecar.ps1), tanto em dev quanto no app
/// instalado (resources do Tauri, sob `_up_/scripts`).
fn resolve_setup_script(app: &tauri::AppHandle, lang: &str) -> Result<PathBuf, String> {
    let dev = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("scripts")
        .join("setup-sidecar.ps1");
    if dev.exists() {
        return Ok(dev);
    }
    let resource_dir = app
        .path_resolver()
        .resource_dir()
        .ok_or_else(|| tr(lang, "res_dir").to_string())?;
    let candidates = [
        resource_dir.join("_up_").join("scripts").join("setup-sidecar.ps1"),
        resource_dir.join("scripts").join("setup-sidecar.ps1"),
    ];
    candidates
        .iter()
        .find(|p| p.exists())
        .cloned()
        .ok_or_else(|| tr(lang, "code_missing").to_string())
}

/// Acompanha um arquivo de log que está sendo escrito por outro processo
/// (como um `tail -f`), emitindo cada linha nova via evento `pipeline-log`
/// assim que aparece. Para quando `stop_rx` sinaliza (processo terminou),
/// mas ainda faz uma última leitura antes de sair, para não perder
/// nenhuma linha final que tenha sido escrita entre o último poll e o
/// processo terminar.
async fn tail_file_and_emit(
    window: Window,
    path: PathBuf,
    mut stop_rx: watch::Receiver<bool>,
    event: &'static str,
) {
    let mut last_pos: u64 = 0;
    let mut leftover = String::new();

    loop {
        read_new_lines(&path, &mut last_pos, &mut leftover, &window, event);

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
    read_new_lines(&path, &mut last_pos, &mut leftover, &window, event);
    if !leftover.trim().is_empty() {
        let _ = window.emit(event, leftover.trim_end().to_string());
    }
}

fn read_new_lines(
    path: &Path,
    last_pos: &mut u64,
    leftover: &mut String,
    window: &Window,
    event: &'static str,
) {
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
        let _ = window.emit(event, line.to_string());
    }
}

/// Garante que o sidecar persistente está vivo (spawna se necessário) e envia
/// um job (uma linha JSON) pela stdin dele. Mantém o handle em `state.server`
/// para reuso entre músicas da fila - é isso que preserva os modelos quentes.
async fn ensure_server_and_send(
    app: &tauri::AppHandle,
    state: &tauri::State<'_, PipelineState>,
    lang: &str,
    job_line: &str,
) -> Result<(), String> {
    let mut guard = state.server.lock().await;

    // (re)spawn se não há servidor ou se o anterior já morreu (cancelamento,
    // crash) - o primeiro job após um respawn paga de novo o load dos modelos.
    let alive = match guard.as_mut() {
        Some(h) => matches!(h.child.try_wait(), Ok(None)),
        None => false,
    };
    if !alive {
        let (code_dir, python_exe) = resolve_sidecar(app, lang)?;
        // stdout/stderr do servidor vão para um log de SESSÃO (só diagnóstico);
        // a saída de cada job é capturada pelo próprio Python no log do job.
        let session_log = code_dir.join("_server_session.log");
        let (out, err) = match File::create(&session_log) {
            Ok(f) => {
                let e = f.try_clone().ok();
                (Stdio::from(f), e.map(Stdio::from).unwrap_or_else(Stdio::null))
            }
            Err(_) => (Stdio::null(), Stdio::null()),
        };
        let mut cmd = Command::new(&python_exe);
        cmd.current_dir(&code_dir)
            .env("PYTHONUTF8", "1")
            .arg("-u") // sem buffer: jobs pela stdin chegam na hora
            .arg("server.py")
            .stdin(Stdio::piped())
            .stdout(out)
            .stderr(err);
        // ffmpeg embutido (se houver): o sidecar e seus filhos (ffmpeg/yt-dlp)
        // herdam esta env e deixam de depender do ffmpeg no PATH.
        if let Some(ff) = resolve_ffmpeg() {
            cmd.env("USKMAKER_FFMPEG", &ff);
        }
        #[cfg(windows)]
        cmd.creation_flags(CREATE_NO_WINDOW);
        let mut child = cmd
            .spawn()
            .map_err(|e| tr_err(lang, "server_start", &e))?;
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| tr(lang, "server_stdin").to_string())?;
        *state.child_pid.lock().unwrap() = child.id();
        *guard = Some(ServerHandle { child, stdin });
    }

    let handle = guard.as_mut().unwrap();
    handle
        .stdin
        .write_all(job_line.as_bytes())
        .await
        .map_err(|e| tr_err(lang, "server_send", &e))?;
    handle
        .stdin
        .write_all(b"\n")
        .await
        .map_err(|e| tr_err(lang, "server_send", &e))?;
    handle
        .stdin
        .flush()
        .await
        .map_err(|e| tr_err(lang, "server_send", &e))?;
    Ok(())
}

#[tauri::command]
async fn run_pipeline(
    app: tauri::AppHandle,
    window: Window,
    state: tauri::State<'_, PipelineState>,
    input: PipelineInput,
    lang: String,
) -> Result<PipelineResult, String> {
    let lang = lang.as_str();
    state.cancel_requested.store(false, Ordering::SeqCst);

    // UX (07/2026): o pacote vai para uma SUBPASTA "Artista - Título" dentro
    // da pasta escolhida - padrão das coleções UltraStar (uma pasta por
    // música dentro do diretório Songs do jogo). Reprocessar a mesma música
    // cai na mesma subpasta e reaproveita os intermediários.
    let package_folder = sanitize_path_component(&format!("{} - {}", input.artist, input.title));
    let out_dir = PathBuf::from(&input.out_dir).join(package_folder);
    std::fs::create_dir_all(&out_dir).map_err(|e| {
        tr(lang, "outdir_create")
            .replace("{path}", &out_dir.display().to_string())
            .replace("{err}", &e.to_string())
    })?;

    let lyrics_path = out_dir.join("_lyrics_input.txt");
    std::fs::write(&lyrics_path, &input.lyrics_text)
        .map_err(|e| tr_err(lang, "write_lyrics", &e))?;

    // Letra sincronizada (.lrc) opcional, vinda do LRCLIB. Só grava se veio
    // conteúdo de fato - assim o sidecar só recebe --synced-lyrics quando há
    // algo para semear.
    let synced_path = match input.synced_lyrics.as_deref().map(str::trim) {
        Some(lrc) if !lrc.is_empty() => {
            let p = out_dir.join("_synced_lyrics.lrc");
            std::fs::write(&p, lrc)
                .map_err(|e| tr_err(lang, "write_synced", &e))?;
            Some(p)
        }
        _ => None,
    };

    // Valida a fonte antes de tocar no sidecar (mesma checagem de sempre).
    let url = input
        .youtube_url
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty());
    let file = input
        .file_path
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty());
    if url.is_none() && file.is_none() {
        return Err(tr(lang, "need_source").to_string());
    }

    // Log por-job que o SERVIDOR Python escreve (o Rust faz tail dele) e o
    // arquivo-sinal de conclusão. Remove versões antigas para não confundir o
    // tail nem ler um status de execução anterior nesta mesma pasta.
    let log_path = out_dir.join("_process_output.log");
    let status_path = out_dir.join("_job_status.json");
    let _ = std::fs::remove_file(&log_path);
    let _ = std::fs::remove_file(&status_path);

    // Monta o job (uma linha JSON) para o sidecar persistente.
    let job = serde_json::json!({
        "url": url,
        "file": file,
        "lyrics_path": lyrics_path.to_string_lossy(),
        "title": input.title,
        "artist": input.artist,
        "language": input.language,
        "out_dir": out_dir.to_string_lossy(),
        "bpm": input.bpm,
        "gap_ms": 0,
        // "auto": o sidecar usa CUDA se houver, senão cai para CPU (máquinas
        // sem GPU NVIDIA quebravam com "Torch not compiled with CUDA").
        "device": "auto",
        "with_video": input.with_video,
        "bg_video": input.bg_video,
        "bg_video_url": input.bg_video_url.as_deref().map(str::trim).filter(|s| !s.is_empty()),
        "clean_work": input.clean_work,
        "synced_lyrics_path": synced_path.as_ref().map(|p| p.to_string_lossy().to_string()),
    });
    let job_line = serde_json::to_string(&job)
        .map_err(|e| tr_err(lang, "job_serialize", &e))?;

    ensure_server_and_send(&app, &state, lang, &job_line).await?;

    // tail do log do job (reusa o mecanismo à prova de balas de sempre)
    let (stop_tx, stop_rx) = watch::channel(false);
    let tail_task = tokio::spawn(tail_file_and_emit(window.clone(), log_path.clone(), stop_rx, "pipeline-log"));

    // Espera o sidecar sinalizar a conclusão do job (arquivo de status),
    // observando também cancelamento e morte inesperada do servidor.
    let job_status = loop {
        if let Ok(txt) = std::fs::read_to_string(&status_path) {
            if let Ok(v) = serde_json::from_str::<serde_json::Value>(&txt) {
                break v;
            }
        }
        if state.cancel_requested.load(Ordering::SeqCst) {
            let _ = stop_tx.send(true);
            let _ = tail_task.await;
            return Err(CANCELLED_MSG.to_string());
        }
        // se o servidor morreu sozinho (crash) e não deixou status, aborta
        {
            let mut guard = state.server.lock().await;
            let dead = match guard.as_mut() {
                Some(h) => matches!(h.child.try_wait(), Ok(Some(_)) | Err(_)),
                None => true,
            };
            if dead && !status_path.exists() {
                *guard = None;
                let _ = stop_tx.send(true);
                let _ = tail_task.await;
                if state.cancel_requested.load(Ordering::SeqCst) {
                    return Err(CANCELLED_MSG.to_string());
                }
                return Err(tr(lang, "server_died").replace("{log}", &log_path.display().to_string()));
            }
        }
        sleep(Duration::from_millis(150)).await;
    };

    let _ = stop_tx.send(true);
    let _ = tail_task.await;

    if job_status.get("status").and_then(|s| s.as_str()) != Some("ok") {
        let fallback = if lang == "en" { "unknown sidecar error" } else { "erro desconhecido no sidecar" };
        let msg = job_status
            .get("message")
            .and_then(|m| m.as_str())
            .unwrap_or(fallback);
        return Err(tr(lang, "pipeline_fail")
            .replace("{err}", msg)
            .replace("{log}", &log_path.display().to_string()));
    }

    // O Python já exportou song_data.json (Fase 1) - a partir daqui, o
    // Rust é quem escreve o .txt final, usando o mesmo rust-core validado
    // contra dados reais.
    let json_path = out_dir.join("song_data.json");
    let song = Song::from_json_file(&json_path).map_err(|e| {
        tr(lang, "read_json")
            .replace("{path}", &json_path.display().to_string())
            .replace("{err}", &e.to_string())
    })?;

    let txt_path = out_dir.join(format!("{} - {}.txt", input.artist, input.title));
    song.write(&txt_path)
        .map_err(|e| tr_err(lang, "write_txt_final", &e))?;

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
/// persistente (taskkill /T) - além do python.exe do servidor, derruba os
/// filhos (Demucs/ffmpeg/yt-dlp) do job atual. O servidor morre junto, então
/// limpamos o handle: o próximo job da fila respawna um servidor novo (frio).
/// O run_pipeline percebe cancel_requested no laço de espera e devolve a
/// sentinela CANCELLED_MSG em vez de erro.
#[tauri::command]
async fn cancel_pipeline(state: tauri::State<'_, PipelineState>, lang: String) -> Result<(), String> {
    state.cancel_requested.store(true, Ordering::SeqCst);
    let pid = *state.child_pid.lock().unwrap();
    // esquece o handle do servidor (foi morto) para forçar respawn no próximo job
    *state.server.lock().await = None;
    *state.child_pid.lock().unwrap() = None;
    let Some(pid) = pid else {
        return Ok(()); // nada rodando - cancelamento vira no-op
    };
    let mut kill = Command::new("taskkill");
    kill.args(["/PID", &pid.to_string(), "/T", "/F"]);
    #[cfg(windows)]
    kill.creation_flags(CREATE_NO_WINDOW);
    kill.output()
        .await
        .map_err(|e| tr_err(&lang, "cancel_fail", &e))?;
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

/// Confere se as bibliotecas do pipeline estão REALMENTE instaladas no venv.
/// Devolve Err(lista de módulos faltando) quando algo não está lá.
///
/// POR QUE ISTO EXISTE (bug real reportado 16/07/2026): o `resolve_sidecar` só
/// verifica se o `python.exe` do venv EXISTE. Um setup que criou o venv mas
/// morreu no meio (caso real: sem Git instalado, o `pip install` do whisperx —
/// que vem de `git+https://...` — falha) deixava o app com o strip VERDE de
/// "✓ Ambiente de IA" e SEM o botão de configurar, mas a geração morria com
/// "o sidecar encerrou inesperadamente" e sem nem criar o log (o server.py
/// morre no `import whisperx`, antes de abrir o arquivo de log).
///
/// Usa `find_spec` (só procura o módulo, NÃO importa) - rápido o bastante para
/// a checagem de abertura; importar o whisperx carregaria o torch inteiro.
async fn probe_sidecar_deps(python: &Path) -> Result<(), String> {
    const PROBE: &str = "import importlib.util as u,sys;\
mods=['whisperx','demucs','librosa','mutagen','swift_f0','yt_dlp'];\
missing=[m for m in mods if u.find_spec(m) is None];\
print(','.join(missing));\
sys.exit(1 if missing else 0)";

    let mut cmd = Command::new(python);
    cmd.arg("-c").arg(PROBE);
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);

    match cmd.output().await {
        Ok(out) if out.status.success() => Ok(()),
        Ok(out) => {
            let missing = String::from_utf8_lossy(&out.stdout).trim().to_string();
            Err(if missing.is_empty() { "?".to_string() } else { missing })
        }
        // o python do venv existe mas nem roda: trata como ambiente quebrado
        Err(e) => Err(e.to_string()),
    }
}

#[tauri::command]
async fn check_environment(app: tauri::AppHandle, lang: String) -> Result<EnvCheck, String> {
    let (sidecar_ok, sidecar_msg) = match resolve_sidecar(&app, &lang) {
        Ok((_, python)) => match probe_sidecar_deps(&python).await {
            Ok(()) => (true, python.display().to_string()),
            Err(missing) => (false, tr(&lang, "deps_missing").replace("{mods}", &missing)),
        },
        Err(e) => (false, e),
    };

    // Prefere o ffmpeg embutido; cai para o do PATH se não houver.
    let ffmpeg_bin = resolve_ffmpeg().unwrap_or_else(|| PathBuf::from("ffmpeg"));
    let mut ffmpeg_cmd = Command::new(&ffmpeg_bin);
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

/// Setup in-app do ambiente de IA: roda o setup-sidecar.ps1 em modo NÃO
/// interativo (-Unattended) e transmite o progresso para a UI via evento
/// "setup-log". Substitui o passo manual de "clicar com o direito no .ps1"
/// (que segue disponível como fallback). O script baixa o uv, cria o venv com
/// Python 3.12, baixa o ffmpeg embutido e instala as dependências.
#[tauri::command]
async fn setup_environment(app: tauri::AppHandle, window: Window, lang: String) -> Result<(), String> {
    let script = resolve_setup_script(&app, &lang)?;

    let local_app_data =
        std::env::var("LOCALAPPDATA").map_err(|_| tr(&lang, "localappdata").to_string())?;
    let usk_dir = Path::new(&local_app_data).join("USKMaker");
    std::fs::create_dir_all(&usk_dir).map_err(|e| tr_err(&lang, "setup_spawn", &e))?;
    let log_path = usk_dir.join("setup.log");
    let _ = std::fs::remove_file(&log_path);
    let stdout_file = File::create(&log_path).map_err(|e| tr_err(&lang, "setup_spawn", &e))?;
    let stderr_file = stdout_file.try_clone().map_err(|e| tr_err(&lang, "setup_spawn", &e))?;

    // `-Command` com `*>&1` faz TODA a saída do PowerShell (inclusive o
    // Write-Host, que é o stream de Information) ir para o stdout capturado no
    // arquivo tailado - senão as linhas coloridas de progresso se perderiam.
    let ps_cmd = format!("& '{}' -Unattended *>&1", script.display());
    let mut cmd = Command::new("powershell");
    cmd.args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"])
        .arg(&ps_cmd)
        .stdout(stdout_file)
        .stderr(stderr_file);
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);

    let mut child = cmd.spawn().map_err(|e| tr_err(&lang, "setup_spawn", &e))?;

    let (stop_tx, stop_rx) = watch::channel(false);
    let tail = tokio::spawn(tail_file_and_emit(
        window.clone(),
        log_path.clone(),
        stop_rx,
        "setup-log",
    ));

    let status = child.wait().await.map_err(|e| tr_err(&lang, "setup_spawn", &e))?;
    let _ = stop_tx.send(true);
    let _ = tail.await;

    if !status.success() {
        return Err(tr(&lang, "setup_failed").replace("{log}", &log_path.display().to_string()));
    }
    Ok(())
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
fn load_song(out_dir: String, lang: String) -> Result<ReviewData, String> {
    let dir = PathBuf::from(&out_dir);
    let json_path = dir.join("song_data.json");
    if !json_path.exists() {
        return Err(tr(&lang, "no_song_json").replace("{path}", &dir.display().to_string()));
    }
    let song = Song::from_json_file(&json_path).map_err(|e| {
        tr(&lang, "read_file")
            .replace("{path}", &json_path.display().to_string())
            .replace("{err}", &e.to_string())
    })?;

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
fn save_song(out_dir: String, song: Song, lang: String) -> Result<SaveResult, String> {
    let dir = PathBuf::from(&out_dir);

    let json_path = dir.join("song_data.json");
    let json = serde_json::to_string_pretty(&song)
        .map_err(|e| tr_err(&lang, "json_serialize", &e))?;
    std::fs::write(&json_path, json).map_err(|e| {
        tr(&lang, "write_file")
            .replace("{path}", &json_path.display().to_string())
            .replace("{err}", &e.to_string())
    })?;

    let txt_path = dir.join(format!("{} - {}.txt", song.artist, song.title));
    song.write(&txt_path).map_err(|e| {
        tr(&lang, "write_txt_path")
            .replace("{path}", &txt_path.display().to_string())
            .replace("{err}", &e.to_string())
    })?;

    Ok(SaveResult {
        txt_path: txt_path.to_string_lossy().to_string(),
        warnings: song.validate_no_overlap(),
    })
}

/// Apaga os arquivos auxiliares (não essenciais) da pasta de UMA música já
/// finalizada: os intermediários `.json` (song_data.json / _job_status.json),
/// os logs `.log` (pipeline_debug.log / _process_output.log) e a letra
/// sincronizada `.lrc`. Preserva o essencial do pacote: o `.txt` do UltraStar,
/// o áudio (.ogg), a capa e o vídeo.
///
/// ATENÇÃO: remover o song_data.json inviabiliza a tela de revisão manual
/// desse pacote (ela lê exatamente esse arquivo). É opt-in e o usuário é
/// avisado disso na interface. Best-effort: falha em um arquivo não derruba
/// os demais nem o comando.
/// Decide se um arquivo da pasta do pacote é AUXILIAR (pode ser apagado) a
/// partir do nome. Auxiliares: intermediários `.json` (song_data.json /
/// _job_status.json), logs `.log` (pipeline_debug.log / _process_output.log),
/// a letra sincronizada `.lrc` e a cópia da letra de entrada
/// (`_lyrics_input.txt`, o único auxiliar em .txt). O `.txt` do UltraStar tem
/// outro nome e NÃO começa com "_", então é preservado — assim como .ogg,
/// capa e vídeo. Função pura para poder ser testada isoladamente.
fn is_aux_package_file(file_name: &str) -> bool {
    if file_name == "_lyrics_input.txt" {
        return true;
    }
    let ext = std::path::Path::new(file_name)
        .extension()
        .and_then(|e| e.to_str())
        .map(|e| e.to_ascii_lowercase());
    matches!(ext.as_deref(), Some("json") | Some("log") | Some("lrc"))
}

#[tauri::command]
fn clean_song_extras(dir: String) -> Result<(), String> {
    let dir_path = std::path::Path::new(&dir);
    let entries = match std::fs::read_dir(dir_path) {
        Ok(e) => e,
        // pasta inexistente/ilegível: nada a fazer, não é erro fatal
        Err(_) => return Ok(()),
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if !path.is_file() {
            continue;
        }
        let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
        if is_aux_package_file(name) {
            let _ = std::fs::remove_file(&path);
        }
    }
    Ok(())
}

#[cfg(test)]
mod clean_extras_tests {
    use super::{clean_song_extras, is_aux_package_file};

    #[test]
    fn classifica_auxiliares_e_preserva_essenciais() {
        // Espelha exatamente os nomes de uma pasta real gerada pelo pipeline.
        let apagar = [
            "_lyrics_input.txt",
            "_process_output.log",
            "pipeline_debug.log",
            "song_data.json",
            "_job_status.json",
            "_synced_lyrics.lrc",
        ];
        let manter = [
            "Rita Lee - Sangue Latino.txt",
            "Rita Lee - Sangue Latino (rust).txt",
            "Rita Lee - Sangue Latino.ogg",
            "Rita Lee - Sangue Latino [CO].jpg",
            "Rita Lee - Sangue Latino.mp4",
        ];
        for f in apagar {
            assert!(is_aux_package_file(f), "deveria apagar: {f}");
        }
        for f in manter {
            assert!(!is_aux_package_file(f), "deveria manter: {f}");
        }
    }

    #[test]
    fn remove_de_uma_pasta_real_so_os_auxiliares() {
        // Cria uma pasta temporária com os MESMOS arquivos de um pacote real e
        // roda o comando de verdade; confirma que só os auxiliares somem.
        let base = std::env::temp_dir().join(format!("usk_clean_test_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&base);
        std::fs::create_dir_all(&base).unwrap();

        let essenciais = [
            "Rita Lee - Sangue Latino.txt",
            "Rita Lee - Sangue Latino.ogg",
            "Rita Lee - Sangue Latino [CO].jpg",
            "Rita Lee - Sangue Latino.mp4",
        ];
        let auxiliares = [
            "_lyrics_input.txt",
            "_process_output.log",
            "pipeline_debug.log",
            "song_data.json",
        ];
        for f in essenciais.iter().chain(auxiliares.iter()) {
            std::fs::write(base.join(f), b"x").unwrap();
        }

        clean_song_extras(base.to_string_lossy().to_string()).unwrap();

        for f in essenciais {
            assert!(base.join(f).exists(), "essencial sumiu: {f}");
        }
        for f in auxiliares {
            assert!(!base.join(f).exists(), "auxiliar sobrou: {f}");
        }
        let _ = std::fs::remove_dir_all(&base);
    }
}

/// Lê as tags básicas (título/artista/álbum/ano/gênero) de um arquivo de
/// áudio local, para o app pré-preencher o formulário ao selecionar o arquivo.
/// Roda o leitor leve `read_tags.py` (só mutagen) no python do sidecar e
/// devolve o JSON como está. É uma conveniência: se o ambiente ainda não foi
/// configurado (sem venv) ou algo falhar, o frontend simplesmente ignora.
#[tauri::command]
fn read_audio_tags(
    app: tauri::AppHandle,
    path: String,
    lang: String,
) -> Result<serde_json::Value, String> {
    let (code_dir, python_exe) = resolve_sidecar(&app, &lang)?;
    let script = code_dir.join("read_tags.py");

    let mut cmd = std::process::Command::new(&python_exe);
    cmd.arg(&script).arg(&path);
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);

    let output = cmd.output().map_err(|e| tr_err(&lang, "read_tags", &e))?;
    let stdout = String::from_utf8_lossy(&output.stdout);
    // read_tags.py nunca sai com traceback (imprime {} em erro); mesmo assim,
    // se a saída não for JSON válido, devolvemos um objeto vazio.
    Ok(serde_json::from_str(stdout.trim()).unwrap_or_else(|_| serde_json::json!({})))
}

#[tauri::command]
fn open_folder(path: String, lang: String) -> Result<(), String> {
    // Windows-only por enquanto (Fase 2 é dev no Windows) - abre o
    // Explorer na pasta de saída informada.
    std::process::Command::new("explorer")
        .arg(path)
        .spawn()
        .map_err(|e| tr_err(&lang, "open_folder", &e))?;
    Ok(())
}

fn main() {
    let app = tauri::Builder::default()
        .manage(PipelineState::default())
        .invoke_handler(tauri::generate_handler![
            run_pipeline,
            open_folder,
            clean_song_extras,
            read_audio_tags,
            load_song,
            save_song,
            cancel_pipeline,
            check_environment,
            setup_environment
        ])
        .build(tauri::generate_context!())
        .expect("erro ao construir a aplicação Tauri");

    app.run(|app_handle, event| {
        // Ao fechar o app, mata o sidecar persistente para não deixar um
        // Python órfão segurando ~GBs de VRAM com os modelos carregados.
        if let tauri::RunEvent::ExitRequested { .. } = event {
            let state = app_handle.state::<PipelineState>();
            let pid = state.child_pid.lock().ok().and_then(|g| *g);
            if let Some(pid) = pid {
                let mut kill = std::process::Command::new("taskkill");
                kill.args(["/PID", &pid.to_string(), "/T", "/F"]);
                #[cfg(windows)]
                kill.creation_flags(CREATE_NO_WINDOW);
                let _ = kill.output();
            }
        }
    });
}

//! Teclado MIDI da Revisão, lido direto pelo sistema (Windows, via `midir`/WinMM).
//!
//! POR QUE NÃO SÓ A WEB MIDI: desde o Chromium 124 TODA a Web MIDI passa por
//! um pedido de permissão, e o WebView2 só expõe tipo de permissão para MIDI
//! com SysEx - o pedido comum pode ser negado sem prompt nenhum, e o teclado
//! simplesmente não aparece. Lendo pelo Rust não há permissão a pedir. O
//! frontend (`src/review/midiKeyboard.ts`) tenta este caminho primeiro no
//! Windows e cai na Web MIDI se ele falhar.
//!
//! Uma thread dona das conexões: abre todas as entradas, repassa cada mensagem
//! como evento `midi-message` (os bytes crus) e a cada 2 s confere se um
//! teclado foi plugado/desplugado - se a lista mudou, reconecta e avisa com
//! `midi-devices` (os nomes). `midi_stop` encerra a thread, e com ela as
//! conexões. As conexões nunca saem da thread, então não precisam ser `Send`.

use std::sync::mpsc::Sender;
use std::sync::Mutex;
use tauri::Window;

#[derive(Default)]
pub struct MidiState {
    stop: Mutex<Option<Sender<()>>>,
}

fn stop_running(state: &MidiState) {
    if let Ok(mut guard) = state.stop.lock() {
        if let Some(tx) = guard.take() {
            let _ = tx.send(());
        }
    }
}

#[cfg(windows)]
mod native {
    use midir::{MidiInput, MidiInputConnection};
    use tauri::{Emitter, Window};

    pub fn port_names() -> Vec<String> {
        match MidiInput::new("USKMaker") {
            Ok(probe) => probe
                .ports()
                .iter()
                .enumerate()
                .map(|(i, p)| probe.port_name(p).unwrap_or_else(|_| format!("MIDI {}", i + 1)))
                .collect(),
            Err(_) => Vec::new(),
        }
    }

    /// Conecta todas as entradas. Porta que não abre (o WinMM é exclusivo:
    /// outro programa, como uma DAW, pode estar com ela) fica de fora.
    pub fn connect_all(window: &Window) -> (Vec<MidiInputConnection<()>>, Vec<String>) {
        let mut conns = Vec::new();
        let mut names = Vec::new();
        let Ok(probe) = MidiInput::new("USKMaker") else {
            return (conns, names);
        };
        for (i, port) in probe.ports().iter().enumerate() {
            let name = probe.port_name(port).unwrap_or_else(|_| format!("MIDI {}", i + 1));
            // connect() consome o MidiInput: um por porta
            let Ok(input) = MidiInput::new("USKMaker") else { continue };
            let w = window.clone();
            let res = input.connect(
                port,
                "uskmaker-review",
                move |_stamp, message, _| {
                    let _ = w.emit("midi-message", message.to_vec());
                },
                (),
            );
            if let Ok(conn) = res {
                conns.push(conn);
                names.push(name);
            }
        }
        (conns, names)
    }
}

/// Abre o teclado MIDI. Devolve os nomes das entradas conectadas (pode ser
/// vazio: a thread segue vigiando e conecta o teclado quando ele for plugado).
/// `async`: roda fora da thread principal (espera até 5 s a thread abrir as portas).
#[tauri::command(async)]
pub fn midi_start(window: Window, state: tauri::State<'_, MidiState>) -> Result<Vec<String>, String> {
    stop_running(&state);
    #[cfg(windows)]
    {
        use std::sync::mpsc::channel;
        use std::time::Duration;
        use tauri::Emitter;
        let (stop_tx, stop_rx) = channel::<()>();
        let (ready_tx, ready_rx) = channel::<Vec<String>>();
        std::thread::Builder::new()
            .name("uskmaker-midi".into())
            .spawn(move || {
                let (mut conns, mut names) = native::connect_all(&window);
                let _ = ready_tx.send(names.clone());
                loop {
                    match stop_rx.recv_timeout(Duration::from_secs(2)) {
                        Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {
                            // plugou/desplugou? (comparar nomes é barato)
                            if native::port_names() != names {
                                conns.clear(); // fecha as antigas antes de reabrir
                                let (c, n) = native::connect_all(&window);
                                conns = c;
                                names = n;
                                let _ = window.emit("midi-devices", names.clone());
                            }
                        }
                        _ => break, // midi_stop (ou o estado sumiu): encerra e solta as conexões
                    }
                }
                drop(conns);
            })
            .map_err(|e| e.to_string())?;
        let names = ready_rx.recv_timeout(Duration::from_secs(5)).map_err(|e| e.to_string())?;
        if let Ok(mut guard) = state.stop.lock() {
            *guard = Some(stop_tx);
        }
        Ok(names)
    }
    #[cfg(not(windows))]
    {
        let _ = window;
        Err("MIDI nativo só no Windows - use a Web MIDI".into())
    }
}

/// Fecha o teclado MIDI (encerra a thread e as conexões).
#[tauri::command]
pub fn midi_stop(state: tauri::State<'_, MidiState>) {
    stop_running(&state);
}

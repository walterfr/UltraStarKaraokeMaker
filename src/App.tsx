import { useEffect, useMemo, useRef, useState } from "react";
import { invoke, convertFileSrc } from "@tauri-apps/api/tauri";
import { listen } from "@tauri-apps/api/event";
import { open as openDialog } from "@tauri-apps/api/dialog";
import { appWindow, PhysicalPosition, PhysicalSize } from "@tauri-apps/api/window";
import ReviewScreen from "./review/ReviewScreen";

// USKMaker - tela principal.
//
// REFORMULAÇÃO DE UX (07/2026) - princípios aplicados:
// - PREVENIR ANTES DE GASTAR GPU: a letra é analisada em tempo real no
//   formulário ((2x), [Refrão], timestamps LRC...) - avisos que antes só
//   apareciam depois de minutos de processamento agora aparecem ao digitar.
//   A checagem de ambiente (sidecar/ffmpeg/GPU) roda na abertura do app.
// - A ESPERA É A UX: gerar leva minutos. A barra genérica virou uma lista
//   de etapas com estado individual (feita/rodando/pendente), duração
//   típica e cronômetro; o log cru fica colapsado ("detalhes técnicos") e
//   só abre sozinho quando há erro. Cancelar de verdade (mata a árvore de
//   processos) em vez de fechar o app.
// - MEMÓRIA: preferências do formulário (pasta de saída, idioma, flags) e
//   tamanho/posição da janela persistem entre sessões (localStorage).

type SourceMode = "youtube" | "file";

interface PipelineResult {
  txtPath: string;
  audioPath: string;
  outDir: string;
  coverPath: string | null;
  year: number | null;
  genre: string | null;
  notesTotal: number;
  notesEstimated: number;
}

interface EnvCheck {
  sidecarOk: boolean;
  sidecarMsg: string;
  ffmpegOk: boolean;
  vorbisOk: boolean;
  gpuName: string | null;
}

// Sentinela que o Rust devolve quando a geração foi cancelada pela UI -
// distingue "cancelado" (aviso neutro) de erro real (caixa vermelha).
const CANCELLED_MSG = "__CANCELADO__";

const SETTINGS_KEY = "uskmaker-settings";
const WINDOW_KEY = "uskmaker-window";

interface PersistedSettings {
  sourceMode: SourceMode;
  language: string;
  outDir: string;
  withVideo: boolean;
  bgVideo: boolean;
  cleanWork: boolean;
}

function loadSettings(): Partial<PersistedSettings> {
  try {
    return JSON.parse(localStorage.getItem(SETTINGS_KEY) ?? "{}");
  } catch {
    return {};
  }
}

// As 6 etapas do pipeline Python, com a duração típica que o usuário deve
// esperar - transforma "travou?" em "está no prazo". Os índices casam com
// as linhas "Etapa X/6" do log.
const PIPELINE_STEPS = [
  { label: "Obter áudio", hint: "segundos (arquivo) · ~1 min (YouTube)" },
  { label: "Separar vocal do instrumental", hint: "~1–3 min na GPU, o passo mais longo" },
  { label: "Detectar BPM", hint: "segundos" },
  { label: "Alinhar letra ao áudio", hint: "~1–2 min" },
  { label: "Buscar capa, ano e gênero", hint: "segundos" },
  { label: "Extrair pitch e montar o pacote", hint: "~1 min" },
];

// Padrões na letra que historicamente causam pacote ruim - detectados AO
// DIGITAR, antes de gastar minutos de GPU. Cada um tem uma explicação
// acionável (o que fazer, não só "está errado").
const LYRIC_CHECKS: { pattern: RegExp; msg: string }[] = [
  {
    pattern: /\(\s*\d+\s*[xX]\s*\)|\(\s*[xX]\s*\d+\s*\)/,
    msg: "Marcação \"(2x)\" encontrada — o alinhador não entende repetição implícita. Cole o trecho repetido por extenso, tantas vezes quanto ele é cantado.",
  },
  {
    pattern: /\(\s*bis\s*\)/i,
    msg: "Marcação \"(bis)\" encontrada — substitua pela repetição escrita por extenso.",
  },
  {
    pattern: /^\s*\[[^\]]+\]\s*$/m,
    msg: "Linha de seção como \"[Refrão]\"/\"[Verse]\" encontrada — remova; o arquivo deve conter apenas o texto cantado.",
  },
  {
    pattern: /\[\d{1,2}:\d{2}/,
    msg: "Timestamps de arquivo .lrc encontrados (\"[00:12]\") — cole a letra pura, sem marcações de tempo; a sincronização é feita pelo próprio USKMaker.",
  },
];

function analyzeLyrics(text: string): { lines: number; words: number; warnings: string[] } {
  const lines = text.split("\n").filter((l) => l.trim()).length;
  const words = text.split(/\s+/).filter(Boolean).length;
  const warnings = LYRIC_CHECKS.filter((c) => c.pattern.test(text)).map((c) => c.msg);
  return { lines, words, warnings };
}

function App() {
  const saved = useMemo(loadSettings, []);
  const [sourceMode, setSourceMode] = useState<SourceMode>(saved.sourceMode ?? "youtube");
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [filePath, setFilePath] = useState("");
  const [lyricsText, setLyricsText] = useState("");
  const [title, setTitle] = useState("");
  const [artist, setArtist] = useState("");
  const [language, setLanguage] = useState(saved.language ?? "pt");
  const [bpm, setBpm] = useState("");
  const [withVideo, setWithVideo] = useState(saved.withVideo ?? false);
  const [bgVideo, setBgVideo] = useState(saved.bgVideo ?? false);
  const [bgVideoUrl, setBgVideoUrl] = useState("");
  const [cleanWork, setCleanWork] = useState(saved.cleanWork ?? true);
  const [outDir, setOutDir] = useState(saved.outDir ?? "");

  const [isRunning, setIsRunning] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [cancelled, setCancelled] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PipelineResult | null>(null);
  const [currentStep, setCurrentStep] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [env, setEnv] = useState<EnvCheck | null>(null);
  const [reviewDir, setReviewDir] = useState<string | null>(null);

  const logEndRef = useRef<HTMLDivElement>(null);
  const startedAtRef = useRef(0);

  const lyricsInfo = useMemo(() => analyzeLyrics(lyricsText), [lyricsText]);

  // ------------------------------------------------ persistência leve
  useEffect(() => {
    const settings: PersistedSettings = { sourceMode, language, outDir, withVideo, bgVideo, cleanWork };
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  }, [sourceMode, language, outDir, withVideo, bgVideo, cleanWork]);

  // tamanho/posição da janela entre sessões
  useEffect(() => {
    (async () => {
      try {
        const w = JSON.parse(localStorage.getItem(WINDOW_KEY) ?? "null");
        if (w && w.width > 400 && w.height > 300) {
          await appWindow.setSize(new PhysicalSize(w.width, w.height));
          if (typeof w.x === "number" && typeof w.y === "number" && w.x > -50 && w.y > -50) {
            await appWindow.setPosition(new PhysicalPosition(w.x, w.y));
          }
        }
      } catch {
        /* estado de janela corrompido - ignora e usa o padrão */
      }
    })();

    let timer: ReturnType<typeof setTimeout>;
    const persistWindow = async () => {
      try {
        const size = await appWindow.outerSize();
        const pos = await appWindow.outerPosition();
        localStorage.setItem(
          WINDOW_KEY,
          JSON.stringify({ width: size.width, height: size.height, x: pos.x, y: pos.y })
        );
      } catch {
        /* janela pode estar fechando */
      }
    };
    const debounced = () => {
      clearTimeout(timer);
      timer = setTimeout(persistWindow, 400);
    };
    const unlistenResize = appWindow.onResized(debounced);
    const unlistenMove = appWindow.onMoved(debounced);
    return () => {
      clearTimeout(timer);
      unlistenResize.then((f) => f());
      unlistenMove.then((f) => f());
    };
  }, []);

  // --------------------------------------------- checagem de ambiente
  useEffect(() => {
    invoke<EnvCheck>("check_environment")
      .then(setEnv)
      .catch(() => setEnv(null)); // sem checagem não é fatal - só não mostra o cartão
  }, []);

  // ------------------------------------------------------ log + passos
  useEffect(() => {
    const unlistenPromise = listen<string>("pipeline-log", (event) => {
      const line = event.payload;
      setLogs((prev) => [...prev, line]);
      const match = line.match(/Etapa\s+(\d+)\/(\d+)/);
      if (match) {
        setCurrentStep(parseInt(match[1], 10));
      }
    });
    return () => {
      unlistenPromise.then((unlisten) => unlisten());
    };
  }, []);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  // cronômetro da geração
  useEffect(() => {
    if (!isRunning) return;
    const id = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAtRef.current) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, [isRunning]);

  async function pickFile() {
    const selected = await openDialog({
      multiple: false,
      filters: [{ name: "Áudio/Vídeo", extensions: ["mp3", "wav", "mp4", "m4a", "flac"] }],
    });
    if (typeof selected === "string") {
      setFilePath(selected);
    }
  }

  async function pickOutDir() {
    const selected = await openDialog({ directory: true, multiple: false });
    if (typeof selected === "string") {
      setOutDir(selected);
    }
  }

  function validate(): string | null {
    if (sourceMode === "youtube" && !youtubeUrl.trim()) {
      return "Informe o link do YouTube.";
    }
    if (sourceMode === "file" && !filePath.trim()) {
      return "Selecione um arquivo de áudio/vídeo local.";
    }
    if (!lyricsText.trim()) return "Cole a letra da música.";
    if (!title.trim()) return "Informe o título.";
    if (!artist.trim()) return "Informe o artista.";
    if (!outDir.trim()) return "Escolha a pasta de saída.";
    return null;
  }

  async function handleSubmit() {
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }

    setError(null);
    setResult(null);
    setLogs([]);
    setCurrentStep(0);
    setElapsed(0);
    setCancelled(false);
    setCancelling(false);
    setIsRunning(true);
    startedAtRef.current = Date.now();
    appWindow.setTitle(`USKMaker — Gerando: ${artist.trim()} - ${title.trim()}`);

    try {
      const pipelineResult = await invoke<PipelineResult>("run_pipeline", {
        input: {
          youtubeUrl: sourceMode === "youtube" ? youtubeUrl.trim() : null,
          filePath: sourceMode === "file" ? filePath.trim() : null,
          lyricsText,
          title: title.trim(),
          artist: artist.trim(),
          language,
          bpm: bpm.trim() ? parseFloat(bpm) : null,
          outDir: outDir.trim(),
          withVideo: sourceMode === "youtube" ? withVideo : false,
          bgVideo: sourceMode === "file" ? bgVideo : false,
          bgVideoUrl: sourceMode === "file" && bgVideo ? bgVideoUrl.trim() || null : null,
          cleanWork,
        },
      });
      setResult(pipelineResult);
      setCurrentStep(PIPELINE_STEPS.length + 1);
    } catch (err) {
      if (err === CANCELLED_MSG) {
        setCancelled(true);
        setCurrentStep(0);
      } else {
        setError(typeof err === "string" ? err : "Erro desconhecido ao rodar o pipeline.");
      }
    } finally {
      setIsRunning(false);
      setCancelling(false);
      appWindow.setTitle("USKMaker");
    }
  }

  async function handleCancel() {
    setCancelling(true);
    try {
      await invoke("cancel_pipeline");
    } catch {
      setCancelling(false); // falhou ao matar - deixa tentar de novo
    }
  }

  async function openOutputFolder() {
    if (!result) return;
    await invoke("open_folder", { path: result.outDir });
  }

  async function pickPackageToReview() {
    const selected = await openDialog({ directory: true, multiple: false });
    if (typeof selected === "string") {
      setReviewDir(selected);
    }
  }

  if (reviewDir) {
    return <ReviewScreen outDir={reviewDir} onClose={() => setReviewDir(null)} />;
  }

  const envProblems: string[] = [];
  if (env) {
    if (!env.sidecarOk) envProblems.push(env.sidecarMsg);
    if (!env.ffmpegOk)
      envProblems.push(
        "ffmpeg não encontrado no PATH — instale (https://www.gyan.dev/ffmpeg/builds/) e reinicie o app."
      );
    else if (!env.vorbisOk)
      envProblems.push(
        "O ffmpeg instalado não tem suporte a libvorbis (necessário para o áudio .ogg do pacote) — use um build \"full\"."
      );
  }

  const minutes = Math.floor(elapsed / 60);
  const seconds = String(elapsed % 60).padStart(2, "0");

  return (
    <div>
      <h1>USKMaker</h1>
      <p className="subtitle">
        Gere pacotes UltraStar (letra sincronizada + pitch) a partir de um link do YouTube ou arquivo local.{" "}
        <button className="link-button" onClick={pickPackageToReview} disabled={isRunning}>
          Revisar um pacote já gerado...
        </button>
      </p>

      {env && envProblems.length === 0 && (
        <p className="env-strip ok">
          ✓ Ambiente de IA &nbsp;·&nbsp; ✓ ffmpeg{env.vorbisOk ? " (vorbis)" : ""} &nbsp;·&nbsp;{" "}
          {env.gpuName ? `✓ GPU ${env.gpuName}` : "⚠ sem GPU NVIDIA — processamento em CPU (lento)"}
        </p>
      )}
      {envProblems.length > 0 && (
        <div className="error-box env-problems">
          <strong>Ambiente incompleto — a geração vai falhar até resolver:</strong>
          <ul>
            {envProblems.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="source-toggle">
        <button
          className={sourceMode === "youtube" ? "active" : ""}
          onClick={() => setSourceMode("youtube")}
          disabled={isRunning}
        >
          Link do YouTube
        </button>
        <button
          className={sourceMode === "file" ? "active" : ""}
          onClick={() => setSourceMode("file")}
          disabled={isRunning}
        >
          Arquivo local
        </button>
      </div>

      {sourceMode === "youtube" ? (
        <div className="field-group">
          <label>Link do YouTube</label>
          <input
            type="text"
            value={youtubeUrl}
            onChange={(e) => setYoutubeUrl(e.target.value)}
            placeholder="https://www.youtube.com/watch?v=..."
            disabled={isRunning}
          />
          <label className="checkbox-line">
            <input
              type="checkbox"
              checked={withVideo}
              onChange={(e) => setWithVideo(e.target.checked)}
              disabled={isRunning}
            />
            Incluir o vídeo no pacote (fundo animado no jogo — download maior e mais lento)
          </label>
        </div>
      ) : (
        <div className="field-group">
          <label>Arquivo de áudio/vídeo</label>
          <div className="file-picker">
            <input type="text" value={filePath} readOnly placeholder="Nenhum arquivo selecionado" />
            <button onClick={pickFile} disabled={isRunning}>
              Procurar...
            </button>
          </div>
          <label className="checkbox-line">
            <input
              type="checkbox"
              checked={bgVideo}
              onChange={(e) => setBgVideo(e.target.checked)}
              disabled={isRunning}
            />
            Baixar videoclipe do YouTube para o fundo (o áudio continua sendo o seu arquivo; sem
            vídeo disponível, fica só a capa)
          </label>
          {bgVideo && (
            <input
              type="text"
              value={bgVideoUrl}
              onChange={(e) => setBgVideoUrl(e.target.value)}
              placeholder="Link do videoclipe (opcional — em branco, busca automática por artista + título)"
              disabled={isRunning}
            />
          )}
        </div>
      )}

      <div className="field-group">
        <label>
          Letra da música (uma linha por frase cantada) — repita refrões por extenso, tantas vezes
          quanto forem cantados
          {lyricsInfo.lines > 0 && (
            <span className="lyrics-count">
              {lyricsInfo.lines} {lyricsInfo.lines === 1 ? "linha" : "linhas"} · {lyricsInfo.words}{" "}
              palavras
            </span>
          )}
        </label>
        <textarea
          value={lyricsText}
          onChange={(e) => setLyricsText(e.target.value)}
          placeholder={"Cole a letra aqui...\nUma linha por frase/verso.\nRefrões repetidos devem ser colados de novo, por extenso."}
          disabled={isRunning}
        />
        {lyricsInfo.warnings.map((w, i) => (
          <p key={i} className="lyrics-warning">
            ⚠ {w}
          </p>
        ))}
      </div>

      <div className="row">
        <div className="field-group">
          <label>Título</label>
          <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} disabled={isRunning} />
        </div>
        <div className="field-group">
          <label>Artista</label>
          <input type="text" value={artist} onChange={(e) => setArtist(e.target.value)} disabled={isRunning} />
        </div>
      </div>

      <div className="row">
        <div className="field-group">
          <label>Idioma</label>
          <select value={language} onChange={(e) => setLanguage(e.target.value)} disabled={isRunning}>
            <option value="pt">Português</option>
            <option value="en">Inglês</option>
            <option value="es">Espanhol</option>
          </select>
        </div>
        <div className="field-group">
          <label>BPM manual (opcional)</label>
          <input
            type="number"
            value={bpm}
            onChange={(e) => setBpm(e.target.value)}
            placeholder="Deixe em branco para detectar automaticamente"
            disabled={isRunning}
          />
        </div>
      </div>

      <div className="field-group">
        <label>Pasta de saída</label>
        <div className="file-picker">
          <input type="text" value={outDir} readOnly placeholder="Nenhuma pasta selecionada" />
          <button onClick={pickOutDir} disabled={isRunning}>
            Escolher pasta...
          </button>
        </div>
        <label className="checkbox-line">
          <input
            type="checkbox"
            checked={cleanWork}
            onChange={(e) => setCleanWork(e.target.checked)}
            disabled={isRunning}
          />
          Remover arquivos intermediários ao final (economiza espaço; deixe desmarcado para reprocessar mais rápido)
        </label>
      </div>

      {!isRunning ? (
        <button className="submit-button" onClick={handleSubmit}>
          Gerar pacote UltraStar
        </button>
      ) : (
        <div className="running-actions">
          <button className="submit-button" disabled>
            Gerando... ({minutes}:{seconds})
          </button>
          <button className="cancel-button" onClick={handleCancel} disabled={cancelling}>
            {cancelling ? "Cancelando..." : "Cancelar"}
          </button>
        </div>
      )}

      {(isRunning || (currentStep > 0 && !result)) && (
        <ol className="steps-list">
          {PIPELINE_STEPS.map((step, i) => {
            const n = i + 1;
            const state = n < currentStep ? "done" : n === currentStep && isRunning ? "running" : "pending";
            return (
              <li key={n} className={`step ${state}`}>
                <span className="step-icon">
                  {state === "done" ? "✓" : state === "running" ? <span className="spinner" /> : "○"}
                </span>
                <span className="step-label">{step.label}</span>
                <span className="step-hint">{state === "running" ? step.hint : ""}</span>
              </li>
            );
          })}
        </ol>
      )}

      {cancelled && (
        <div className="info-box">
          Geração cancelada. Os arquivos parciais ficaram na pasta de saída e serão reaproveitados
          se você gerar de novo com a mesma pasta.
        </div>
      )}

      {logs.length > 0 && (
        <details className="log-details" open={!!error}>
          <summary>Detalhes técnicos ({logs.length} linhas de log)</summary>
          <div className="log-console">
            {logs.map((line, i) => (
              <div key={i}>{line}</div>
            ))}
            <div ref={logEndRef} />
          </div>
        </details>
      )}

      {error && (
        <div className="error-box">
          <strong>Erro:</strong> {error}
        </div>
      )}

      {result && (
        <div className="result-box rich">
          {result.coverPath && (
            <img className="result-cover" src={convertFileSrc(result.coverPath)} alt="Capa do álbum" />
          )}
          <div className="result-body">
            <h3>Pacote gerado com sucesso!</h3>
            <p className="metadata-summary">
              {result.year ? `${result.year} · ` : ""}
              {result.genre ? `${result.genre} · ` : ""}
              {result.notesTotal - result.notesEstimated} notas medidas no áudio
              {result.notesEstimated > 0 && (
                <strong className="estimated-badge">
                  {" "}
                  · {result.notesEstimated} estimadas — vale revisar
                </strong>
              )}
            </p>
            <p className="result-paths">
              {result.txtPath}
              <br />
              {result.audioPath}
            </p>
            <div className="result-actions">
              <button className="submit-button compact" onClick={() => setReviewDir(result.outDir)}>
                Revisar alinhamento
              </button>
              <button className="secondary" onClick={openOutputFolder}>
                Abrir pasta
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;

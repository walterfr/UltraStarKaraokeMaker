import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/tauri";
import { listen } from "@tauri-apps/api/event";
import { open as openDialog } from "@tauri-apps/api/dialog";
import ReviewScreen from "./review/ReviewScreen";

// USKMaker - Fase 2: primeira UI real, chamando o pipeline Python (via
// Rust/Tauri) e o rust-core (ultrastar_writer) para o .txt final.
// Ainda é uma UI mínima - o objetivo desta fase é provar a integração
// ponta a ponta, não polir a experiência (isso fica para depois).

type SourceMode = "youtube" | "file";

interface PipelineResult {
  txtPath: string;
  audioPath: string;
  outDir: string;
  coverPath: string | null;
  year: number | null;
  genre: string | null;
}

function App() {
  const [sourceMode, setSourceMode] = useState<SourceMode>("youtube");
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [filePath, setFilePath] = useState("");
  const [lyricsText, setLyricsText] = useState("");
  const [title, setTitle] = useState("");
  const [artist, setArtist] = useState("");
  const [language, setLanguage] = useState("pt");
  const [bpm, setBpm] = useState("");
  const [withVideo, setWithVideo] = useState(false);
  const [cleanWork, setCleanWork] = useState(true);
  const [outDir, setOutDir] = useState("");

  const [isRunning, setIsRunning] = useState(false);
  // Fase 4: quando não-nulo, a tela de revisão manual substitui o formulário.
  const [reviewDir, setReviewDir] = useState<string | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PipelineResult | null>(null);
  // Progresso: extraído das linhas de log "Etapa X/6" que o Python emite.
  const [currentStep, setCurrentStep] = useState(0);
  const totalSteps = 6;

  const logEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const unlistenPromise = listen<string>("pipeline-log", (event) => {
      const line = event.payload;
      setLogs((prev) => [...prev, line]);
      // Detecta "Etapa X/6" nas linhas de log para mover a barra de progresso.
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
    setIsRunning(true);

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
          cleanWork,
        },
      });
      setResult(pipelineResult);
      setCurrentStep(totalSteps);
    } catch (err) {
      setError(typeof err === "string" ? err : "Erro desconhecido ao rodar o pipeline.");
    } finally {
      setIsRunning(false);
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

  return (
    <div>
      <h1>USKMaker</h1>
      <p className="subtitle">
        Gere pacotes UltraStar (letra sincronizada + pitch) a partir de um link do YouTube ou arquivo local.{" "}
        <button className="link-button" onClick={pickPackageToReview} disabled={isRunning}>
          Revisar um pacote já gerado...
        </button>
      </p>

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
        </div>
      )}

      <div className="field-group">
        <label>
          Letra da música (uma linha por frase cantada) — repita refrões por extenso, tantas vezes
          quanto forem cantados; não use "(2x)"
        </label>
        <textarea
          value={lyricsText}
          onChange={(e) => setLyricsText(e.target.value)}
          placeholder={"Cole a letra aqui...\nUma linha por frase/verso.\nRefrões repetidos devem ser colados de novo, por extenso."}
          disabled={isRunning}
        />
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

      <button className="submit-button" onClick={handleSubmit} disabled={isRunning}>
        {isRunning ? "Gerando..." : "Gerar pacote UltraStar"}
      </button>

      {(isRunning || currentStep > 0) && (
        <div className="progress-wrap">
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{ width: `${(currentStep / totalSteps) * 100}%` }}
            />
          </div>
          <span className="progress-label">
            {currentStep >= totalSteps
              ? "Concluído"
              : currentStep > 0
              ? `Etapa ${currentStep} de ${totalSteps}`
              : "Iniciando..."}
          </span>
        </div>
      )}

      {logs.length > 0 && (
        <div className="log-console">
          {logs.map((line, i) => (
            <div key={i}>{line}</div>
          ))}
          <div ref={logEndRef} />
        </div>
      )}

      {error && (
        <div className="error-box">
          <strong>Erro:</strong> {error}
        </div>
      )}

      {result && (
        <div className="result-box">
          <h3>Pacote gerado com sucesso!</h3>
          <p>
            <strong>.txt:</strong> {result.txtPath}
          </p>
          <p>
            <strong>Áudio:</strong> {result.audioPath}
          </p>
          <p className="metadata-summary">
            <strong>Metadados:</strong>{" "}
            {result.coverPath ? "capa incluída" : "sem capa"}
            {" · "}
            {result.year ? `ano ${result.year}` : "ano —"}
            {" · "}
            {result.genre ? result.genre : "gênero —"}
          </p>
          <button className="secondary" onClick={openOutputFolder}>
            Abrir pasta
          </button>{" "}
          <button className="secondary" onClick={() => setReviewDir(result.outDir)}>
            Revisar alinhamento
          </button>
        </div>
      )}
    </div>
  );
}

export default App;

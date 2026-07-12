import { useEffect, useMemo, useRef, useState } from "react";
import { invoke, convertFileSrc } from "@tauri-apps/api/tauri";
import { listen } from "@tauri-apps/api/event";
import { open as openDialog, ask } from "@tauri-apps/api/dialog";
import { writeText } from "@tauri-apps/api/clipboard";
import { fetch as httpFetch, ResponseType } from "@tauri-apps/api/http";
import { appWindow, PhysicalPosition, PhysicalSize } from "@tauri-apps/api/window";
import { getVersion } from "@tauri-apps/api/app";
import ReviewScreen from "./review/ReviewScreen";
import { useI18n, StrKey } from "./i18n";

// USKMaker - tela principal.
//
// UX (07/2026): prevenção antes de gastar GPU (validação de letra ao digitar,
// checagem de ambiente na abertura), espera legível (lista de etapas com
// estado + cronômetro + cancelar de verdade), memória entre sessões
// (preferências e janela) e resultado rico. Interface bilíngue PT/EN
// (ver i18n.tsx) com splash e página "Sobre".

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

type QueueStatus = "pending" | "running" | "done" | "error" | "cancelled";

interface QueueItem {
  id: number;
  artist: string;
  title: string;
  // snapshot dos dados do formulário no momento em que foi enfileirada -
  // o mesmo objeto que run_pipeline recebe.
  input: Record<string, unknown>;
  status: QueueStatus;
  result?: PipelineResult;
  error?: string;
}

const CANCELLED_MSG = "__CANCELADO__";
// Chave Pix "copia e cola" (BR Code, CRC16 validado) para apoio via a página Sobre.
const PIX_PAYLOAD =
  "00020101021126400014br.gov.bcb.pix0118walterfr@gmail.com5204000053039865802BR5915WALTER REBOUCAS6009FORTALEZA62070503***63045603";
const SETTINGS_KEY = "uskmaker-settings";
const WINDOW_KEY = "uskmaker-window";

/// Resposta do LRCLIB (https://lrclib.net/docs) - API aberta, sem chave.
interface LrclibTrack {
  plainLyrics: string | null;
  syncedLyrics: string | null;
  instrumental?: boolean;
}

/// Converte um .lrc em letra "plana" (uma linha por frase, sem timestamps) -
/// usado quando o LRCLIB só devolve a versão sincronizada.
function lrcToPlain(lrc: string): string {
  return lrc
    .split("\n")
    .map((l) => l.replace(/\[[^\]]*\]/g, "").trim())
    .filter(Boolean)
    .join("\n");
}

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

// Padrões na letra que historicamente causam pacote ruim - detectados AO
// DIGITAR, antes de gastar minutos de GPU (mensagens em i18n.tsx).
const LYRIC_CHECKS: { pattern: RegExp; key: StrKey }[] = [
  { pattern: /\(\s*\d+\s*[xX]\s*\)|\(\s*[xX]\s*\d+\s*\)/, key: "lyricWarn2x" },
  { pattern: /\(\s*bis\s*\)/i, key: "lyricWarnBis" },
  { pattern: /^\s*\[[^\]]+\]\s*$/m, key: "lyricWarnSection" },
  { pattern: /\[\d{1,2}:\d{2}/, key: "lyricWarnLrc" },
];

const STEP_KEYS: { label: StrKey; hint: StrKey }[] = [
  { label: "step1", hint: "step1Hint" },
  { label: "step2", hint: "step2Hint" },
  { label: "step3", hint: "step3Hint" },
  { label: "step4", hint: "step4Hint" },
  { label: "step5", hint: "step5Hint" },
  { label: "step6", hint: "step6Hint" },
];

function LogoMark({ size = 40 }: { size?: number }) {
  // marca simples e própria: microfone estilizado + estrela (UltraStar)
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" fill="none" aria-hidden="true">
      <rect x="18" y="6" width="12" height="20" rx="6" fill="#4f8ef7" />
      <path d="M12 22v2a12 12 0 0 0 24 0v-2" stroke="#7fabf9" strokeWidth="3" strokeLinecap="round" />
      <line x1="24" y1="38" x2="24" y2="43" stroke="#7fabf9" strokeWidth="3" strokeLinecap="round" />
      <path d="M37 8l1.6 3.4L42 13l-3.4 1.6L37 18l-1.6-3.4L32 13l3.4-1.6L37 8z" fill="#c9a227" />
    </svg>
  );
}

function App() {
  const { t, lang, setLang } = useI18n();
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

  // Letra sincronizada (.lrc) do LRCLIB: guardada crua e enviada ao pipeline,
  // onde os tempos de início de linha viram âncoras do alinhamento. Editar a
  // letra depois da busca é seguro: linhas divergentes simplesmente não casam.
  const [syncedLyrics, setSyncedLyrics] = useState<string | null>(null);
  const [lyricsSearching, setLyricsSearching] = useState(false);
  const [lyricsSearchMsg, setLyricsSearchMsg] = useState<{ kind: "ok" | "warn" | "err"; text: string } | null>(null);

  // Fila de músicas: enfileira várias e processa em série, sem reabrir o app.
  // O frontend é dono da fila (loop chamando run_pipeline por item); o sidecar
  // persistente do Rust mantém os modelos quentes entre uma música e outra.
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const nextIdRef = useRef(1);

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

  // Setup in-app do ambiente de IA (uv + ffmpeg + libs), quando não configurado.
  const [settingUp, setSettingUp] = useState(false);
  const [setupLog, setSetupLog] = useState<string[]>([]);
  const [setupDone, setSetupDone] = useState(false);
  const [setupError, setSetupError] = useState<string | null>(null);

  // splash: visível na abertura, some com fade (leve - overlay, sem janela extra)
  const [splashState, setSplashState] = useState<"show" | "fade" | "gone">("show");
  const [showAbout, setShowAbout] = useState(false);
  const [appVersion, setAppVersion] = useState("");
  const [pixCopied, setPixCopied] = useState(false);

  async function copyPix() {
    try {
      await writeText(PIX_PAYLOAD);
      setPixCopied(true);
      setTimeout(() => setPixCopied(false), 2500);
    } catch {
      /* clipboard indisponível - silencioso */
    }
  }

  const logEndRef = useRef<HTMLDivElement>(null);
  const startedAtRef = useRef(0);

  const lyricsInfo = useMemo(() => {
    const lines = lyricsText.split("\n").filter((l) => l.trim()).length;
    const words = lyricsText.split(/\s+/).filter(Boolean).length;
    const warnings = LYRIC_CHECKS.filter((c) => c.pattern.test(lyricsText)).map((c) => t(c.key));
    return { lines, words, warnings };
  }, [lyricsText, t]);

  // ------------------------------------------------------------- splash
  useEffect(() => {
    const fadeTimer = setTimeout(() => setSplashState("fade"), 1300);
    const goneTimer = setTimeout(() => setSplashState("gone"), 1850);
    return () => {
      clearTimeout(fadeTimer);
      clearTimeout(goneTimer);
    };
  }, []);

  useEffect(() => {
    getVersion().then(setAppVersion).catch(() => setAppVersion(""));
  }, []);

  // ------------------------------------------------ persistência leve
  useEffect(() => {
    const settings: PersistedSettings = { sourceMode, language, outDir, withVideo, bgVideo, cleanWork };
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  }, [sourceMode, language, outDir, withVideo, bgVideo, cleanWork]);

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
  // Refaz ao trocar de idioma para a mensagem de erro (se houver) vir traduzida.
  useEffect(() => {
    invoke<EnvCheck>("check_environment", { lang })
      .then(setEnv)
      .catch(() => setEnv(null));
  }, [lang]);

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

  // progresso do setup in-app (evento separado do log da pipeline)
  useEffect(() => {
    const unlistenPromise = listen<string>("setup-log", (event) => {
      setSetupLog((prev) => [...prev, event.payload]);
    });
    return () => {
      unlistenPromise.then((unlisten) => unlisten());
    };
  }, []);

  async function handleSetup() {
    setSettingUp(true);
    setSetupLog([]);
    setSetupError(null);
    setSetupDone(false);
    try {
      await invoke("setup_environment", { lang });
      const e = await invoke<EnvCheck>("check_environment", { lang });
      setEnv(e);
      if (e.sidecarOk) setSetupDone(true);
    } catch (err) {
      setSetupError(typeof err === "string" ? err : t("unknownError"));
    } finally {
      setSettingUp(false);
    }
  }

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

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
      filters: [{ name: t("fileFilterName"), extensions: ["mp3", "wav", "mp4", "m4a", "flac"] }],
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

  async function searchLyrics() {
    if (!artist.trim() || !title.trim()) {
      setLyricsSearchMsg({ kind: "err", text: t("lyricsNeedArtistTitle") });
      return;
    }
    if (lyricsText.trim()) {
      const ok = await ask(t("lyricsOverwriteConfirm"), { title: "USKMaker" });
      if (!ok) return;
    }
    setLyricsSearching(true);
    setLyricsSearchMsg(null);
    try {
      const resp = await httpFetch<LrclibTrack>("https://lrclib.net/api/get", {
        method: "GET",
        timeout: 20,
        responseType: ResponseType.JSON,
        query: { artist_name: artist.trim(), track_name: title.trim() },
        // o LRCLIB pede que clientes se identifiquem
        headers: { "Lrclib-Client": "USKMaker/0.1.0 (https://github.com/walterfr/UltraStarKaraokeMaker)" },
      });
      if (!resp.ok) {
        if (resp.status === 404) {
          setLyricsSearchMsg({ kind: "warn", text: t("lyricsNotFound") });
        } else {
          setLyricsSearchMsg({ kind: "err", text: t("lyricsSearchError", { msg: `HTTP ${resp.status}` }) });
        }
        return;
      }
      const synced = resp.data.syncedLyrics?.trim() || null;
      const plain = resp.data.plainLyrics?.trim() || (synced ? lrcToPlain(synced) : "");
      if (!plain) {
        // inclui o caso instrumental=true (faixa sem letra)
        setLyricsSearchMsg({ kind: "warn", text: t("lyricsNotFound") });
        return;
      }
      setLyricsText(plain);
      setSyncedLyrics(synced);
      setLyricsSearchMsg(
        synced
          ? { kind: "ok", text: t("lyricsFoundSynced") }
          : { kind: "warn", text: t("lyricsFoundPlain") }
      );
    } catch (err) {
      setLyricsSearchMsg({ kind: "err", text: t("lyricsSearchError", { msg: String(err) }) });
    } finally {
      setLyricsSearching(false);
    }
  }

  function validate(): string | null {
    if (sourceMode === "youtube" && !youtubeUrl.trim()) return t("valNeedYoutube");
    if (sourceMode === "file" && !filePath.trim()) return t("valNeedFile");
    if (!lyricsText.trim()) return t("valNeedLyrics");
    if (!title.trim()) return t("valNeedTitle");
    if (!artist.trim()) return t("valNeedArtist");
    if (!outDir.trim()) return t("valNeedOutDir");
    return null;
  }

  // Snapshot dos campos do formulário no objeto que run_pipeline espera.
  function buildInput(): Record<string, unknown> {
    return {
      youtubeUrl: sourceMode === "youtube" ? youtubeUrl.trim() : null,
      filePath: sourceMode === "file" ? filePath.trim() : null,
      lyricsText,
      syncedLyrics,
      title: title.trim(),
      artist: artist.trim(),
      language,
      bpm: bpm.trim() ? parseFloat(bpm) : null,
      outDir: outDir.trim(),
      withVideo: sourceMode === "youtube" ? withVideo : false,
      bgVideo: sourceMode === "file" ? bgVideo : false,
      bgVideoUrl: sourceMode === "file" && bgVideo ? bgVideoUrl.trim() || null : null,
      cleanWork,
    };
  }

  // Limpa só os campos da MÚSICA (mantém pasta de saída, idioma e checkboxes),
  // para digitar a próxima sem reabrir o app - usado ao enfileirar.
  function clearSongFields() {
    setYoutubeUrl("");
    setFilePath("");
    setLyricsText("");
    setSyncedLyrics(null);
    setLyricsSearchMsg(null);
    setTitle("");
    setArtist("");
    setBpm("");
    setBgVideoUrl("");
  }

  function makeQueueItem(): QueueItem {
    return {
      id: nextIdRef.current++,
      artist: artist.trim(),
      title: title.trim(),
      input: buildInput(),
      status: "pending",
    };
  }

  function addToQueue() {
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }
    setError(null);
    setQueue((q) => [...q, makeQueueItem()]);
    clearSongFields();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function patchItem(id: number, patch: Partial<QueueItem>) {
    setQueue((q) => q.map((it) => (it.id === id ? { ...it, ...patch } : it)));
  }

  function removeFromQueue(id: number) {
    setQueue((q) => q.filter((it) => it.id !== id));
  }

  function clearDoneFromQueue() {
    setQueue((q) => q.filter((it) => it.status === "pending" || it.status === "running"));
  }

  // Processa em série todos os itens `pending` da lista fornecida. Cancelar
  // interrompe a fila; um erro em uma música NÃO derruba as demais.
  async function processQueue(list: QueueItem[]) {
    setIsRunning(true);
    setCancelling(false);
    for (const item of list) {
      if (item.status !== "pending") continue;
      patchItem(item.id, { status: "running" });
      setResult(null);
      setError(null);
      setLogs([]);
      setCurrentStep(0);
      setElapsed(0);
      setCancelled(false);
      setCancelling(false);
      startedAtRef.current = Date.now();
      appWindow.setTitle(t("windowGenerating", { song: `${item.artist} - ${item.title}` }));

      try {
        const res = await invoke<PipelineResult>("run_pipeline", { input: item.input, lang });
        patchItem(item.id, { status: "done", result: res });
        setResult(res);
        setCurrentStep(STEP_KEYS.length + 1);
      } catch (err) {
        if (err === CANCELLED_MSG) {
          patchItem(item.id, { status: "cancelled" });
          setCancelled(true);
          setCurrentStep(0);
          break; // cancelamento interrompe a fila inteira
        }
        const msg = typeof err === "string" ? err : t("unknownError");
        patchItem(item.id, { status: "error", error: msg });
        setError(msg);
        // segue para o próximo item (uma música ruim não trava o lote)
      }
    }
    setIsRunning(false);
    setCancelling(false);
    appWindow.setTitle("USKMaker");
  }

  async function handleGenerate() {
    if (isRunning) return;
    const formErr = validate();
    const pending = queue.filter((it) => it.status === "pending");

    // Se o formulário está preenchido, a música atual entra como último item.
    let current: QueueItem | null = null;
    if (!formErr) {
      current = makeQueueItem();
    } else if (pending.length === 0) {
      setError(formErr);
      return;
    }
    setError(null);

    const full = current ? [...queue, current] : queue;
    if (current) {
      setQueue(full);
      clearSongFields();
    }
    await processQueue(full);
  }

  async function handleCancel() {
    setCancelling(true);
    try {
      await invoke("cancel_pipeline", { lang });
    } catch {
      setCancelling(false);
    }
  }

  // Limpa os campos da música (preferências como pasta de saída e idioma ficam)
  // para emendar a próxima geração sem reabrir o app.
  function resetForm() {
    setYoutubeUrl("");
    setFilePath("");
    setLyricsText("");
    setSyncedLyrics(null);
    setLyricsSearchMsg(null);
    setTitle("");
    setArtist("");
    setBpm("");
    setBgVideoUrl("");
    setResult(null);
    setError(null);
    setLogs([]);
    setCurrentStep(0);
    setElapsed(0);
    setCancelled(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function handleClear() {
    // sem pacote gerado, a letra digitada ainda não foi usada — confirma antes de descartar
    if (!result && lyricsText.trim()) {
      const ok = await ask(t("clearConfirm"), { title: "USKMaker" });
      if (!ok) return;
    }
    resetForm();
  }

  async function openOutputFolder() {
    if (!result) return;
    await invoke("open_folder", { path: result.outDir, lang });
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
    if (!env.ffmpegOk) envProblems.push(t("envNoFfmpeg"));
    else if (!env.vorbisOk) envProblems.push(t("envNoVorbis"));
  }

  const minutes = Math.floor(elapsed / 60);
  const seconds = String(elapsed % 60).padStart(2, "0");

  return (
    <div>
      {splashState !== "gone" && (
        <div className={`splash ${splashState === "fade" ? "fade" : ""}`}>
          <LogoMark size={72} />
          <h1 className="splash-title">USKMaker</h1>
          <p className="splash-tagline">UltraStar Karaoke Maker</p>
        </div>
      )}

      {showAbout && (
        <div className="about-overlay" onClick={() => setShowAbout(false)}>
          <div className="about-box" onClick={(e) => e.stopPropagation()}>
            <LogoMark size={56} />
            <h2>{t("aboutTitle")}</h2>
            {appVersion && <p className="about-version">{t("aboutVersion", { v: appVersion })}</p>}
            <p className="about-tagline">{t("aboutTagline")}</p>
            <p className="about-heart">{t("aboutMadeWith")}</p>
            <p className="about-links">
              <a href="https://github.com/walterfr/UltraStarKaraokeMaker" target="_blank" rel="noreferrer">
                GitHub
              </a>
              {" · "}
              <a href="https://www.instagram.com/prof.walterfr" target="_blank" rel="noreferrer">
                @prof.walterfr
              </a>
            </p>
            <p className="about-support">
              {t("aboutSupport")}{" "}
              <a href="https://github.com/sponsors/walterfr" target="_blank" rel="noreferrer">
                GitHub Sponsors
              </a>
              {" · "}
              <a href="https://ko-fi.com/walterfr" target="_blank" rel="noreferrer">
                Ko-fi
              </a>
              {" · "}
              <a href="https://buymeacoffee.com/walterfr" target="_blank" rel="noreferrer">
                Buy Me a Coffee
              </a>
              {" · "}
              <button className="link-button" onClick={copyPix}>
                {pixCopied ? t("aboutPixCopied") : t("aboutPixCopy")}
              </button>
            </p>
            <button className="secondary" onClick={() => setShowAbout(false)}>
              {t("aboutClose")}
            </button>
          </div>
        </div>
      )}

      <div className="app-header">
        <h1>USKMaker</h1>
        <div className="header-actions">
          <div className="lang-toggle" role="group" aria-label="Idioma / Language">
            <button className={lang === "pt" ? "active" : ""} onClick={() => setLang("pt")}>
              PT
            </button>
            <button className={lang === "en" ? "active" : ""} onClick={() => setLang("en")}>
              EN
            </button>
          </div>
          <button className="info-button" title={t("infoButtonTitle")} onClick={() => setShowAbout(true)}>
            i
          </button>
        </div>
      </div>
      <p className="subtitle">
        {t("subtitle")}{" "}
        <button className="link-button" onClick={pickPackageToReview} disabled={isRunning}>
          {t("reviewExisting")}
        </button>
      </p>

      {env && envProblems.length === 0 && (
        <p className="env-strip ok">
          ✓ {t("envAI")} &nbsp;·&nbsp; ✓ ffmpeg{env.vorbisOk ? " (vorbis)" : ""} &nbsp;·&nbsp;{" "}
          {env.gpuName ? t("envGpu", { name: env.gpuName }) : t("envNoGpu")}
        </p>
      )}
      {envProblems.length > 0 && (
        <div className="error-box env-problems">
          <strong>{t("envIncomplete")}</strong>
          <ul>
            {envProblems.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ul>
          {!settingUp ? (
            <>
              <button className="submit-button compact" onClick={handleSetup}>
                {t("setupButton")}
              </button>
              <p className="field-hint">{t("setupHint")}</p>
            </>
          ) : (
            <div className="setup-progress">
              <p>
                <span className="spinner" /> {t("setupRunning")}
              </p>
              <div className="setup-log">
                {setupLog.slice(-14).map((l, i) => (
                  <div key={i}>{l}</div>
                ))}
              </div>
            </div>
          )}
          {setupError && (
            <p className="lyrics-warning">
              ⚠ {t("setupErrorPrefix")} {setupError}
            </p>
          )}
        </div>
      )}
      {setupDone && env?.sidecarOk && <div className="info-box">{t("setupDone")}</div>}

      <div className="source-toggle">
        <button
          className={sourceMode === "youtube" ? "active" : ""}
          onClick={() => setSourceMode("youtube")}
          disabled={isRunning}
        >
          {t("tabYoutube")}
        </button>
        <button
          className={sourceMode === "file" ? "active" : ""}
          onClick={() => setSourceMode("file")}
          disabled={isRunning}
        >
          {t("tabFile")}
        </button>
      </div>

      {sourceMode === "youtube" ? (
        <div className="field-group">
          <label>{t("youtubeLabel")}</label>
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
            {t("withVideoLabel")}
          </label>
        </div>
      ) : (
        <div className="field-group">
          <label>{t("fileLabel")}</label>
          <div className="file-picker">
            <input type="text" value={filePath} readOnly placeholder={t("filePlaceholder")} />
            <button onClick={pickFile} disabled={isRunning}>
              {t("browse")}
            </button>
          </div>
          <label className="checkbox-line">
            <input
              type="checkbox"
              checked={bgVideo}
              onChange={(e) => setBgVideo(e.target.checked)}
              disabled={isRunning}
            />
            {t("bgVideoLabel")}
          </label>
          {bgVideo && (
            <input
              type="text"
              value={bgVideoUrl}
              onChange={(e) => setBgVideoUrl(e.target.value)}
              placeholder={t("bgVideoUrlPlaceholder")}
              disabled={isRunning}
            />
          )}
        </div>
      )}

      <div className="field-group">
        <label>
          {t("lyricsLabel")}
          {lyricsInfo.lines > 0 && (
            <span className="lyrics-count">
              {t("lyricsCount", {
                lines: lyricsInfo.lines,
                lineWord: lyricsInfo.lines === 1 ? t("lineSingular") : t("linePlural"),
                words: lyricsInfo.words,
              })}
            </span>
          )}
        </label>
        <div className="lyrics-toolbar">
          <button className="mini-button" onClick={searchLyrics} disabled={isRunning || lyricsSearching}>
            {lyricsSearching ? t("searchingLyrics") : t("searchLyrics")}
          </button>
          {lyricsSearchMsg && (
            <span className={`lyrics-status ${lyricsSearchMsg.kind}`}>{lyricsSearchMsg.text}</span>
          )}
        </div>
        <textarea
          value={lyricsText}
          onChange={(e) => setLyricsText(e.target.value)}
          placeholder={t("lyricsPlaceholder")}
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
          <label>{t("titleLabel")}</label>
          <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} disabled={isRunning} />
        </div>
        <div className="field-group">
          <label>{t("artistLabel")}</label>
          <input type="text" value={artist} onChange={(e) => setArtist(e.target.value)} disabled={isRunning} />
        </div>
      </div>

      <div className="row">
        <div className="field-group">
          <label>{t("languageLabel")}</label>
          <select value={language} onChange={(e) => setLanguage(e.target.value)} disabled={isRunning}>
            <option value="pt">{t("langPt")}</option>
            <option value="en">{t("langEn")}</option>
            <option value="es">{t("langEs")}</option>
          </select>
        </div>
        <div className="field-group">
          <label>{t("bpmLabel")}</label>
          <input
            type="number"
            value={bpm}
            onChange={(e) => setBpm(e.target.value)}
            placeholder={t("bpmPlaceholder")}
            disabled={isRunning}
          />
        </div>
      </div>

      <div className="field-group">
        <label>{t("outDirLabel")}</label>
        <div className="file-picker">
          <input type="text" value={outDir} readOnly placeholder={t("outDirPlaceholder")} />
          <button onClick={pickOutDir} disabled={isRunning}>
            {t("outDirPick")}
          </button>
        </div>
        <p className="field-hint">{t("outDirHint")}</p>
        <label className="checkbox-line">
          <input
            type="checkbox"
            checked={cleanWork}
            onChange={(e) => setCleanWork(e.target.checked)}
            disabled={isRunning}
          />
          {t("cleanWorkLabel")}
        </label>
      </div>

      {queue.length > 0 && (
        <div className="queue-panel">
          <div className="queue-head">
            <strong>{t("queueHeader", { n: queue.length })}</strong>
            {!isRunning && queue.some((it) => it.status !== "pending") && (
              <button className="mini-button" onClick={clearDoneFromQueue}>
                {t("queueClearDone")}
              </button>
            )}
          </div>
          <ul className="queue-list">
            {queue.map((it) => (
              <li key={it.id} className={`queue-item ${it.status}`}>
                <span className="queue-icon">
                  {it.status === "done"
                    ? "✓"
                    : it.status === "running"
                    ? <span className="spinner" />
                    : it.status === "error"
                    ? "✗"
                    : it.status === "cancelled"
                    ? "⊘"
                    : "○"}
                </span>
                <span className="queue-name">
                  {it.artist} - {it.title}
                </span>
                <span className={`queue-status ${it.status}`}>{t(`queueStatus${it.status.charAt(0).toUpperCase()}${it.status.slice(1)}` as StrKey)}</span>
                <span className="queue-actions">
                  {it.status === "done" && it.result && (
                    <>
                      <button className="link-button" onClick={() => setReviewDir(it.result!.outDir)}>
                        {t("queueReview")}
                      </button>
                      <button className="link-button" onClick={() => invoke("open_folder", { path: it.result!.outDir, lang })}>
                        {t("queueOpen")}
                      </button>
                    </>
                  )}
                  {it.status === "pending" && !isRunning && (
                    <button className="link-button danger" onClick={() => removeFromQueue(it.id)}>
                      {t("queueRemove")}
                    </button>
                  )}
                  {it.status === "error" && it.error && <span className="queue-error-msg">{it.error}</span>}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {!isRunning ? (
        <div className="running-actions">
          <button className="submit-button" onClick={handleGenerate}>
            {queue.some((it) => it.status === "pending")
              ? t("generateQueue", { n: queue.filter((it) => it.status === "pending").length })
              : t("generate")}
          </button>
          <button className="clear-button" onClick={addToQueue} title={t("queueAdd")}>
            {t("queueAdd")}
          </button>
          <button className="clear-button" onClick={handleClear} title={t("clearConfirm")}>
            {t("clearFields")}
          </button>
        </div>
      ) : (
        <div className="running-actions">
          <button className="submit-button" disabled>
            {t("generating", { time: `${minutes}:${seconds}` })}
          </button>
          <button className="cancel-button" onClick={handleCancel} disabled={cancelling}>
            {cancelling ? t("cancelling") : t("cancel")}
          </button>
        </div>
      )}

      {(isRunning || (currentStep > 0 && !result)) && (
        <ol className="steps-list">
          {STEP_KEYS.map((step, i) => {
            const n = i + 1;
            const state = n < currentStep ? "done" : n === currentStep && isRunning ? "running" : "pending";
            return (
              <li key={n} className={`step ${state}`}>
                <span className="step-icon">
                  {state === "done" ? "✓" : state === "running" ? <span className="spinner" /> : "○"}
                </span>
                <span className="step-label">{t(step.label)}</span>
                <span className="step-hint">{state === "running" ? t(step.hint) : ""}</span>
              </li>
            );
          })}
        </ol>
      )}

      {cancelled && <div className="info-box">{t("cancelledInfo")}</div>}

      {logs.length > 0 && (
        <details className="log-details" open={!!error}>
          <summary>{t("logDetails", { n: logs.length })}</summary>
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
          <strong>{t("errorPrefix")}</strong> {error}
        </div>
      )}

      {result && (
        <div className="result-box rich">
          {result.coverPath && (
            <img className="result-cover" src={convertFileSrc(result.coverPath)} alt="" />
          )}
          <div className="result-body">
            <h3>{t("resultSuccess")}</h3>
            <p className="metadata-summary">
              {result.year ? `${result.year} · ` : ""}
              {result.genre ? `${result.genre} · ` : ""}
              {t("resultNotesMeasured", { n: result.notesTotal - result.notesEstimated })}
              {result.notesEstimated > 0 && (
                <strong className="estimated-badge">
                  {t("resultNotesEstimated", { n: result.notesEstimated })}
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
                {t("resultReview")}
              </button>
              <button className="secondary" onClick={openOutputFolder}>
                {t("resultOpenFolder")}
              </button>
              <button className="secondary" onClick={resetForm}>
                {t("resultNewSong")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;

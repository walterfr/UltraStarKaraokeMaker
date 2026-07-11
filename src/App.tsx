import { useEffect, useMemo, useRef, useState } from "react";
import { invoke, convertFileSrc } from "@tauri-apps/api/tauri";
import { listen } from "@tauri-apps/api/event";
import { open as openDialog } from "@tauri-apps/api/dialog";
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

  // splash: visível na abertura, some com fade (leve - overlay, sem janela extra)
  const [splashState, setSplashState] = useState<"show" | "fade" | "gone">("show");
  const [showAbout, setShowAbout] = useState(false);
  const [appVersion, setAppVersion] = useState("");

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
  useEffect(() => {
    invoke<EnvCheck>("check_environment")
      .then(setEnv)
      .catch(() => setEnv(null));
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

  function validate(): string | null {
    if (sourceMode === "youtube" && !youtubeUrl.trim()) return t("valNeedYoutube");
    if (sourceMode === "file" && !filePath.trim()) return t("valNeedFile");
    if (!lyricsText.trim()) return t("valNeedLyrics");
    if (!title.trim()) return t("valNeedTitle");
    if (!artist.trim()) return t("valNeedArtist");
    if (!outDir.trim()) return t("valNeedOutDir");
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
    appWindow.setTitle(t("windowGenerating", { song: `${artist.trim()} - ${title.trim()}` }));

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
      setCurrentStep(STEP_KEYS.length + 1);
    } catch (err) {
      if (err === CANCELLED_MSG) {
        setCancelled(true);
        setCurrentStep(0);
      } else {
        setError(typeof err === "string" ? err : t("unknownError"));
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
      setCancelling(false);
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
        </div>
      )}

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

      {!isRunning ? (
        <button className="submit-button" onClick={handleSubmit}>
          {t("generate")}
        </button>
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
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;

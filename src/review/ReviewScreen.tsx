import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { invoke, convertFileSrc } from "@tauri-apps/api/tauri";
import { ask } from "@tauri-apps/api/dialog";
import { useI18n } from "../i18n";

// USKMaker - Fase 4: tela de revisão manual do alinhamento (estilo Yass).
//
// Carrega o song_data.json de um pacote gerado e mostra as notas numa
// timeline (x = tempo, y = pitch) sobre a waveform do áudio. O usuário
// ajusta timing/pitch/texto/quebras de frase e salva - o Rust regrava o
// JSON e regenera o .txt pelo mesmo rust-core de sempre.
//
// Decisões de implementação:
// - Canvas imperativo com estado de viewport em refs (não useState): pan,
//   zoom e playhead redesenham dezenas de vezes por segundo; passar isso
//   pelo ciclo de render do React deixaria a interação visivelmente presa.
//   O React cuida só do "chrome" (toolbar, inspetor, mensagens).
// - O áudio toca num <audio> escondido via asset protocol do Tauri
//   (convertFileSrc) - sem cópia de arquivo, sem base64.
// - A waveform é decodificada com Web Audio API uma única vez por arquivo
//   e reduzida a "peaks" (máximo absoluto por bucket) - desenhar as
//   amostras cruas a cada frame seria inviável.
// - Undo/redo por snapshot JSON da música inteira (barato: poucas centenas
//   de notas) - um snapshot por gesto (drag inteiro = 1 undo, não 1 por px).

interface USNote {
  start_beat: number;
  duration_beats: number;
  pitch: number;
  text: string;
  note_type: string; // ":" normal | "*" golden | "F" freestyle
  // Proveniência do timing (align.py): "anchor" | "fuzzy" | "realign" |
  // "interpolated". Ausente em pacotes gerados antes desse campo existir.
  source?: string | null;
  // Confiança fonética medida (WordTiming.score em align.py), herdada da
  // palavra de origem. Ausente em pacotes gerados antes desse campo existir.
  score?: number | null;
}

// Cor de preenchimento por proveniência do timing - o olho do revisor deve
// ir direto para o laranja ("interpolated" = timestamp estimado, não medido
// no áudio). Golden/freestyle têm prioridade sobre a proveniência (são
// informação de jogo, não de confiança).
const SOURCE_COLORS: Record<string, string> = {
  anchor: "#3d6fd6", // medido: match exato com a transcrição
  fuzzy: "#2f9e8f", // medido: match aproximado de grafia
  realign: "#7a5cd6", // medido: 2º passe de forced alignment na janela
  lrc: "#c05a9e", // semi-medido: início de linha da letra sincronizada (LRCLIB)
  interpolated: "#d6802f", // ESTIMADO: interpolação entre vizinhas - revisar!
};
const DEFAULT_NOTE_COLOR = "#3d6fd6";

// Nota MEDIDA (source != interpolated) mas com score fonético baixo - um
// match que existe, mas é suspeito (ex.: casou com o evento acústico
// errado quando vocal de apoio sobrepõe o lead). Cor própria: "nunca medido"
// (laranja, acima) e "medido mas suspeito" (aqui) são falhas diferentes -
// vale a pena o revisor distinguir uma da outra.
const LOW_CONFIDENCE_COLOR = "#d64f4f";
// Conservador de propósito: o próprio align.py documenta que vogais
// cantadas esticadas/vibrato derrubam o score do whisperx mesmo quando o
// timing está correto (score 0.00-0.35 é normal ali). Um threshold baixo
// mira abaixo do "normal-mas-correto" e ainda assim pega mais casos da
// região corrompida do que teria visibilidade nenhuma.
const LOW_SCORE_ANCHOR_THRESHOLD = 0.15;

function isLowConfidenceAnchor(n: USNote): boolean {
  if (n.note_type === "F") return false; // já sinalizado por outro caminho (freestyle)
  if (n.source == null || n.source === "interpolated") return false; // já coberto pela cor "interpolated"
  return typeof n.score === "number" && n.score < LOW_SCORE_ANCHOR_THRESHOLD;
}

interface USSong {
  title: string;
  artist: string;
  mp3_filename: string;
  bpm: number;
  gap_ms: number;
  version: string;
  genre: string | null;
  year: number | null;
  language: string | null;
  cover_filename: string | null;
  video_filename: string | null;
  background_filename: string | null;
  creator: string;
  notes: USNote[];
  phrase_breaks_after_index: number[];
}

interface ReviewData {
  song: USSong;
  audioPath: string | null;
  vocalsPath: string | null;
  outDir: string;
}

interface SaveResult {
  txtPath: string;
  warnings: string[];
}

interface Props {
  outDir: string;
  onClose: () => void;
}

// ---- conversões beat <-> segundos (fórmula oficial do UltraStar:
// tempo_real = gap + beat * 60 / (BPM * 4); o jogo multiplica o BPM da tag
// por 4 internamente) ----
function beatDuration(song: USSong): number {
  return 60 / (song.bpm * 4);
}
function beatToSec(song: USSong, beat: number): number {
  return song.gap_ms / 1000 + beat * beatDuration(song);
}
/** Reduz um AudioBuffer a `buckets` picos (máximo absoluto por janela). */
function computePeaks(buffer: AudioBuffer, buckets: number): Float32Array {
  const data = buffer.getChannelData(0);
  const peaks = new Float32Array(buckets);
  const samplesPerBucket = Math.max(1, Math.floor(data.length / buckets));
  for (let b = 0; b < buckets; b++) {
    let max = 0;
    const start = b * samplesPerBucket;
    const end = Math.min(data.length, start + samplesPerBucket);
    for (let i = start; i < end; i++) {
      const v = Math.abs(data[i]);
      if (v > max) max = v;
    }
    peaks[b] = max;
  }
  return peaks;
}

// Layout vertical do canvas (px, coordenadas lógicas pré-devicePixelRatio)
const RULER_H = 24;
const WAVE_H = 72;
const NOTE_EDGE_PX = 6; // zona de "pegar a borda" para redimensionar
const MIN_PX_PER_SEC = 8;
const MAX_PX_PER_SEC = 800;

// Pitch do UltraStar é relativo ao C4 (dó central): pitch 0 = C4 = MIDI 60.
const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
function pitchName(pitch: number): string {
  const midi = pitch + 60;
  const name = NOTE_NAMES[((midi % 12) + 12) % 12];
  const octave = Math.floor(midi / 12) - 1;
  return `${name}${octave}`;
}

// Um "verso" = trecho entre quebras de frase; alimenta o painel lateral de
// navegação (clicar num verso pula a viewport e seleciona a 1ª nota dele).
interface Verse {
  firstNote: number;
  text: string;
  time: number; // segundos do início do verso
}

function deriveVerses(song: USSong, noTextFallback: string): Verse[] {
  const breaks = new Set(song.phrase_breaks_after_index);
  const verses: Verse[] = [];
  let start = 0;
  for (let i = 0; i < song.notes.length; i++) {
    if (breaks.has(i) || i === song.notes.length - 1) {
      const text = song.notes
        .slice(start, i + 1)
        .map((n) => n.text.replace(/~/g, ""))
        .join("")
        .replace(/\s+/g, " ")
        .trim();
      verses.push({
        firstNote: start,
        text: text || noTextFallback,
        time: beatToSec(song, song.notes[start].start_beat),
      });
      start = i + 1;
    }
  }
  return verses;
}

type DragMode =
  | { kind: "none" }
  | { kind: "seek" }
  | { kind: "pan"; startX: number; viewStart0: number }
  | { kind: "move"; noteIdx: number; startX: number; startY: number; beat0: number; pitch0: number }
  | { kind: "resize"; noteIdx: number; startX: number; dur0: number };

export default function ReviewScreen({ outDir, onClose }: Props) {
  const { t, lang } = useI18n();
  const [song, setSong] = useState<USSong | null>(null);
  const [audioPath, setAudioPath] = useState<string | null>(null);
  const [vocalsPath, setVocalsPath] = useState<string | null>(null);
  const [audioChoice, setAudioChoice] = useState<"mix" | "vocals">("mix");
  const [selected, setSelected] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [dirty, setDirty] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [saving, setSaving] = useState(false);

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const minimapRef = useRef<HTMLCanvasElement | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [activeVerse, setActiveVerse] = useState(0);
  const activeVerseRef = useRef(0);

  // Estado imperativo do editor (ver nota no topo do arquivo).
  const songRef = useRef<USSong | null>(null);
  const selectedRef = useRef<number | null>(null);
  const viewRef = useRef({ start: 0, pxPerSec: 80 });
  const peaksRef = useRef<{ peaks: Float32Array; duration: number } | null>(null);
  const dragRef = useRef<DragMode>({ kind: "none" });
  const dragMovedRef = useRef(false);
  const playUntilRef = useRef<number | null>(null);
  const historyRef = useRef<string[]>([]);
  const redoRef = useRef<string[]>([]);
  const rafRef = useRef<number>(0);

  songRef.current = song;
  selectedRef.current = selected;

  // ---------------------------------------------------------------- carga
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await invoke<ReviewData>("load_song", { outDir, lang });
        if (cancelled) return;
        setSong(data.song);
        setAudioPath(data.audioPath);
        setVocalsPath(data.vocalsPath);
        if (!data.audioPath && data.vocalsPath) setAudioChoice("vocals");
        // enquadra o início da música (primeira nota - 1s)
        if (data.song.notes.length > 0) {
          viewRef.current.start = Math.max(0, beatToSec(data.song, data.song.notes[0].start_beat) - 1);
        }
      } catch (err) {
        if (!cancelled) setError(typeof err === "string" ? err : t("revLoadError"));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [outDir]);

  // ------------------------------------------------------- áudio + peaks
  const currentAudioFile = audioChoice === "vocals" && vocalsPath ? vocalsPath : audioPath;

  useEffect(() => {
    if (!currentAudioFile) return;
    const audio = audioRef.current;
    if (!audio) return;
    const keepTime = audio.currentTime;
    audio.src = convertFileSrc(currentAudioFile);
    audio.load();
    const restore = () => {
      audio.currentTime = keepTime;
    };
    audio.addEventListener("loadedmetadata", restore, { once: true });

    // decodifica a waveform em paralelo (não bloqueia o playback)
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch(convertFileSrc(currentAudioFile));
        const buf = await resp.arrayBuffer();
        const ctx = new AudioContext();
        const decoded = await ctx.decodeAudioData(buf);
        ctx.close();
        if (!cancelled) {
          peaksRef.current = { peaks: computePeaks(decoded, 8000), duration: decoded.duration };
          draw();
        }
      } catch {
        // sem waveform não é fatal - a timeline de notas continua funcionando
        if (!cancelled) peaksRef.current = null;
      }
    })();
    return () => {
      cancelled = true;
      audio.removeEventListener("loadedmetadata", restore);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentAudioFile]);

  // --------------------------------------------------------- mutação/undo
  const pushHistory = useCallback(() => {
    const s = songRef.current;
    if (!s) return;
    historyRef.current.push(JSON.stringify(s));
    if (historyRef.current.length > 200) historyRef.current.shift();
    redoRef.current = [];
  }, []);

  const mutate = useCallback(
    (fn: (draft: USSong) => void, snapshot = true) => {
      const s = songRef.current;
      if (!s) return;
      if (snapshot) pushHistory();
      const draft: USSong = JSON.parse(JSON.stringify(s));
      fn(draft);
      setSong(draft);
      songRef.current = draft;
      setDirty(true);
      setStatusMsg(null);
    },
    [pushHistory]
  );

  const undo = useCallback(() => {
    const s = songRef.current;
    const prev = historyRef.current.pop();
    if (!s || !prev) return;
    redoRef.current.push(JSON.stringify(s));
    const restored: USSong = JSON.parse(prev);
    setSong(restored);
    songRef.current = restored;
    setDirty(true);
    setSelected(null);
  }, []);

  const redo = useCallback(() => {
    const s = songRef.current;
    const next = redoRef.current.pop();
    if (!s || !next) return;
    historyRef.current.push(JSON.stringify(s));
    const restored: USSong = JSON.parse(next);
    setSong(restored);
    songRef.current = restored;
    setDirty(true);
    setSelected(null);
  }, []);

  // ------------------------------------------------------------- desenho
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const s = songRef.current;
    if (!canvas || !s) return;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
      canvas.width = w * dpr;
      canvas.height = h * dpr;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const { start, pxPerSec } = viewRef.current;
    const xOf = (t: number) => (t - start) * pxPerSec;
    const visibleEnd = start + w / pxPerSec;

    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = "#121218";
    ctx.fillRect(0, 0, w, h);

    // --- régua de tempo ---
    ctx.fillStyle = "#1b1b24";
    ctx.fillRect(0, 0, w, RULER_H);
    const tickStep = pxPerSec > 200 ? 0.5 : pxPerSec > 60 ? 1 : pxPerSec > 25 ? 5 : 10;
    ctx.font = "10px system-ui";
    ctx.textBaseline = "top";
    for (let t = Math.floor(start / tickStep) * tickStep; t <= visibleEnd; t += tickStep) {
      if (t < 0) continue;
      const x = xOf(t);
      ctx.strokeStyle = "#33333f";
      ctx.beginPath();
      ctx.moveTo(x, RULER_H - 6);
      ctx.lineTo(x, RULER_H);
      ctx.stroke();
      ctx.fillStyle = "#9a9aa8";
      const mm = Math.floor(t / 60);
      const ss = (t % 60).toFixed(tickStep < 1 ? 1 : 0).padStart(tickStep < 1 ? 4 : 2, "0");
      ctx.fillText(`${mm}:${ss}`, x + 3, 4);
    }

    // --- waveform ---
    const wave = peaksRef.current;
    if (wave) {
      const midY = RULER_H + WAVE_H / 2;
      ctx.fillStyle = "#2b3a55";
      const bucketsPerSec = wave.peaks.length / wave.duration;
      for (let x = 0; x < w; x++) {
        const t0 = start + x / pxPerSec;
        const t1 = start + (x + 1) / pxPerSec;
        if (t1 < 0 || t0 > wave.duration) continue;
        let max = 0;
        const b0 = Math.max(0, Math.floor(t0 * bucketsPerSec));
        const b1 = Math.min(wave.peaks.length - 1, Math.ceil(t1 * bucketsPerSec));
        for (let b = b0; b <= b1; b++) if (wave.peaks[b] > max) max = wave.peaks[b];
        const amp = max * (WAVE_H / 2 - 2);
        ctx.fillRect(x, midY - amp, 1, amp * 2 || 1);
      }
    } else {
      ctx.fillStyle = "#55556a";
      ctx.font = "11px system-ui";
      ctx.fillText("(decodificando waveform...)", 8, RULER_H + WAVE_H / 2 - 6);
    }

    // --- faixa de notas: escala de pitch ---
    const laneTop = RULER_H + WAVE_H + 6;
    const laneH = h - laneTop - 4;
    let pMin = Infinity;
    let pMax = -Infinity;
    for (const n of s.notes) {
      if (n.pitch < pMin) pMin = n.pitch;
      if (n.pitch > pMax) pMax = n.pitch;
    }
    if (!isFinite(pMin)) {
      pMin = 0;
      pMax = 12;
    }
    pMin -= 2;
    pMax += 2;
    if (pMax - pMin < 12) pMax = pMin + 12;
    const semitoneH = laneH / (pMax - pMin + 1);
    const yOfPitch = (p: number) => laneTop + (pMax - p) * semitoneH;

    // linhas de grade de pitch (a cada 2 semitons, sutil)
    ctx.strokeStyle = "#1e1e28";
    for (let p = Math.ceil(pMin / 2) * 2; p <= pMax; p += 2) {
      const y = yOfPitch(p) + semitoneH / 2;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }

    // régua de pitch com nomes de nota (C4, D4...) na borda esquerda -
    // pitch numérico é abstrato; nome de nota é o vocabulário do músico.
    // Com pouco espaço vertical, mostra só os Dós (âncora de oitava).
    ctx.fillStyle = "rgba(18, 18, 24, 0.82)";
    ctx.fillRect(0, laneTop, 30, laneH);
    ctx.font = "9px ui-monospace, monospace";
    ctx.textBaseline = "middle";
    const labelEvery = semitoneH >= 11 ? 1 : semitoneH >= 6 ? 2 : 12;
    for (let p = Math.ceil(pMin); p <= pMax; p++) {
      const isC = ((p + 60) % 12 + 12) % 12 === 0;
      if (labelEvery === 12 ? !isC : p % labelEvery !== 0) continue;
      const y = yOfPitch(p) + semitoneH / 2;
      ctx.fillStyle = isC ? "#9a9aa8" : "#55556a";
      ctx.fillText(pitchName(p), 2, y);
    }

    // --- quebras de frase (linha tracejada no fim da nota marcada) ---
    ctx.strokeStyle = "#5a5a72";
    ctx.setLineDash([4, 4]);
    for (const idx of s.phrase_breaks_after_index) {
      const n = s.notes[idx];
      if (!n) continue;
      const t = beatToSec(s, n.start_beat + n.duration_beats);
      if (t < start || t > visibleEnd) continue;
      const x = xOf(t);
      ctx.beginPath();
      ctx.moveTo(x, RULER_H);
      ctx.lineTo(x, h);
      ctx.stroke();
    }
    ctx.setLineDash([]);

    // --- notas ---
    ctx.font = "11px system-ui";
    ctx.textBaseline = "middle";
    const sel = selectedRef.current;
    for (let i = 0; i < s.notes.length; i++) {
      const n = s.notes[i];
      const t0 = beatToSec(s, n.start_beat);
      const t1 = beatToSec(s, n.start_beat + n.duration_beats);
      if (t1 < start || t0 > visibleEnd) continue;
      const x = xOf(t0);
      const nw = Math.max(3, (t1 - t0) * pxPerSec);
      const y = yOfPitch(n.pitch);
      const nh = Math.max(8, semitoneH - 2);

      ctx.fillStyle =
        n.note_type === "F"
          ? "#4a4a58"
          : n.note_type === "*"
          ? "#c9a227"
          : isLowConfidenceAnchor(n)
          ? LOW_CONFIDENCE_COLOR
          : SOURCE_COLORS[n.source ?? ""] ?? DEFAULT_NOTE_COLOR;
      ctx.beginPath();
      ctx.roundRect(x, y, nw, nh, 3);
      ctx.fill();

      if (i === sel) {
        ctx.strokeStyle = "#ff9f43";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.roundRect(x - 1, y - 1, nw + 2, nh + 2, 4);
        ctx.stroke();
        ctx.lineWidth = 1;
      }

      // texto da sílaba: acima da nota, para não depender da largura dela
      ctx.fillStyle = i === sel ? "#ffd9b0" : "#c9c9d6";
      ctx.fillText(n.text.trim(), x + 1, y - 8);
    }

    // --- playhead ---
    const audio = audioRef.current;
    if (audio && !isNaN(audio.currentTime)) {
      const x = xOf(audio.currentTime);
      if (x >= 0 && x <= w) {
        ctx.strokeStyle = "#e8554d";
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, h);
        ctx.stroke();
      }
    }

    // --- minimapa: música inteira, notas como riscos, retângulo = viewport ---
    const mini = minimapRef.current;
    if (mini) {
      const mw = mini.clientWidth;
      const mh = mini.clientHeight;
      if (mini.width !== mw * dpr || mini.height !== mh * dpr) {
        mini.width = mw * dpr;
        mini.height = mh * dpr;
      }
      const mctx = mini.getContext("2d");
      if (mctx) {
        mctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        mctx.clearRect(0, 0, mw, mh);
        mctx.fillStyle = "#17171f";
        mctx.fillRect(0, 0, mw, mh);

        const lastNote = s.notes[s.notes.length - 1];
        const songEnd = Math.max(
          peaksRef.current?.duration ?? 0,
          lastNote ? beatToSec(s, lastNote.start_beat + lastNote.duration_beats) : 0,
          1
        );
        const mxOf = (t: number) => (t / songEnd) * mw;

        for (const n of s.notes) {
          const nx = mxOf(beatToSec(s, n.start_beat));
          if (n.source === "interpolated" || isLowConfidenceAnchor(n)) {
            // notas estimadas ou suspeitas saltam aos olhos até no minimapa
            mctx.fillStyle = n.source === "interpolated" ? SOURCE_COLORS.interpolated : LOW_CONFIDENCE_COLOR;
            mctx.fillRect(nx, 2, 2, mh - 4);
          } else {
            mctx.fillStyle = "#3d6fd6";
            mctx.fillRect(nx, mh * 0.3, 1, mh * 0.4);
          }
        }

        // viewport atual
        const vx0 = mxOf(start);
        const vx1 = mxOf(visibleEnd);
        mctx.strokeStyle = "#9a9aa8";
        mctx.strokeRect(Math.max(0, vx0) + 0.5, 0.5, Math.max(4, vx1 - vx0), mh - 1);

        // playhead no minimapa
        if (audio && !isNaN(audio.currentTime)) {
          mctx.fillStyle = "#e8554d";
          mctx.fillRect(mxOf(audio.currentTime), 0, 1, mh);
        }
      }
    }
  }, []);

  // versos derivados (painel lateral de navegação)
  const verses = useMemo(() => (song ? deriveVerses(song, t("revNoText")) : []), [song, t]);
  const versesRef = useRef<Verse[]>([]);
  versesRef.current = verses;

  const jumpToVerse = useCallback(
    (i: number) => {
      const v = versesRef.current[i];
      if (!v) return;
      setActiveVerse(i);
      activeVerseRef.current = i;
      setSelected(v.firstNote);
      selectedRef.current = v.firstNote;
      viewRef.current.start = Math.max(0, v.time - 1);
      draw();
    },
    [draw]
  );

  const onMinimapSeek = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>, requireButton: boolean) => {
      if (requireButton && e.buttons !== 1) return;
      const mini = minimapRef.current;
      const s = songRef.current;
      if (!mini || !s || s.notes.length === 0) return;
      const rect = mini.getBoundingClientRect();
      const frac = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
      const last = s.notes[s.notes.length - 1];
      const songEnd = Math.max(
        peaksRef.current?.duration ?? 0,
        beatToSec(s, last.start_beat + last.duration_beats),
        1
      );
      const w = canvasRef.current?.clientWidth ?? 800;
      const span = w / viewRef.current.pxPerSec;
      viewRef.current.start = Math.max(-1, frac * songEnd - span / 2);
      draw();
    },
    [draw]
  );

  // redesenha quando o React muda algo relevante
  useEffect(() => {
    draw();
  }, [song, selected, draw]);

  // loop de animação: acompanha o playhead durante o playback
  useEffect(() => {
    const tick = () => {
      const audio = audioRef.current;
      if (audio && !audio.paused) {
        // parada automática no "tocar só esta nota"
        if (playUntilRef.current !== null && audio.currentTime >= playUntilRef.current) {
          audio.pause();
          playUntilRef.current = null;
        }
        // acompanha o verso atual no painel lateral durante o playback
        const vs = versesRef.current;
        if (vs.length > 0) {
          let idx = 0;
          for (let i = 0; i < vs.length; i++) {
            if (vs[i].time <= audio.currentTime + 0.05) idx = i;
            else break;
          }
          if (idx !== activeVerseRef.current) {
            activeVerseRef.current = idx;
            setActiveVerse(idx);
            document
              .getElementById(`verse-item-${idx}`)
              ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
          }
        }
        // auto-scroll: mantém o playhead visível
        const { start, pxPerSec } = viewRef.current;
        const w = canvasRef.current?.clientWidth ?? 800;
        const visibleEnd = start + w / pxPerSec;
        if (audio.currentTime > visibleEnd - 1 || audio.currentTime < start) {
          viewRef.current.start = Math.max(0, audio.currentTime - 1);
        }
        draw();
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [draw]);

  // redesenho em resize da janela
  useEffect(() => {
    const onResize = () => draw();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [draw]);

  // ------------------------------------------------------------ playback
  const togglePlay = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    playUntilRef.current = null;
    if (audio.paused) {
      audio.play();
    } else {
      audio.pause();
    }
  }, []);

  const seekTo = useCallback(
    (t: number) => {
      const audio = audioRef.current;
      if (!audio) return;
      audio.currentTime = Math.max(0, t);
      draw();
    },
    [draw]
  );

  const playNote = useCallback(
    (idx: number) => {
      const s = songRef.current;
      const audio = audioRef.current;
      if (!s || !audio) return;
      const n = s.notes[idx];
      if (!n) return;
      audio.currentTime = Math.max(0, beatToSec(s, n.start_beat) - 0.15);
      playUntilRef.current = beatToSec(s, n.start_beat + n.duration_beats) + 0.15;
      audio.play();
    },
    []
  );

  // -------------------------------------------------------- mouse/canvas
  const noteAt = useCallback((mx: number, my: number): { idx: number; onEdge: boolean } | null => {
    const canvas = canvasRef.current;
    const s = songRef.current;
    if (!canvas || !s) return null;
    const h = canvas.clientHeight;
    const laneTop = RULER_H + WAVE_H + 6;
    const laneH = h - laneTop - 4;
    let pMin = Infinity;
    let pMax = -Infinity;
    for (const n of s.notes) {
      if (n.pitch < pMin) pMin = n.pitch;
      if (n.pitch > pMax) pMax = n.pitch;
    }
    if (!isFinite(pMin)) return null;
    pMin -= 2;
    pMax += 2;
    if (pMax - pMin < 12) pMax = pMin + 12;
    const semitoneH = laneH / (pMax - pMin + 1);
    const { start, pxPerSec } = viewRef.current;

    // percorre de trás pra frente: nota desenhada por cima ganha o clique
    for (let i = s.notes.length - 1; i >= 0; i--) {
      const n = s.notes[i];
      const t0 = beatToSec(s, n.start_beat);
      const t1 = beatToSec(s, n.start_beat + n.duration_beats);
      const x = (t0 - start) * pxPerSec;
      const nw = Math.max(3, (t1 - t0) * pxPerSec);
      const y = laneTop + (pMax - n.pitch) * semitoneH;
      const nh = Math.max(8, semitoneH - 2);
      if (mx >= x && mx <= x + nw && my >= y && my <= y + nh) {
        return { idx: i, onEdge: mx > x + nw - NOTE_EDGE_PX && nw > NOTE_EDGE_PX * 2 };
      }
    }
    return null;
  }, []);

  const onMouseDown = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      const s = songRef.current;
      if (!canvas || !s) return;
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      dragMovedRef.current = false;

      if (my <= RULER_H + WAVE_H) {
        // régua/waveform: clique posiciona o playhead, arrastar "esfrega"
        const { start, pxPerSec } = viewRef.current;
        seekTo(start + mx / pxPerSec);
        dragRef.current = { kind: "seek" };
        return;
      }

      const hit = noteAt(mx, my);
      if (hit) {
        setSelected(hit.idx);
        selectedRef.current = hit.idx;
        const n = s.notes[hit.idx];
        pushHistory(); // 1 snapshot por gesto de drag
        dragRef.current = hit.onEdge
          ? { kind: "resize", noteIdx: hit.idx, startX: mx, dur0: n.duration_beats }
          : {
              kind: "move",
              noteIdx: hit.idx,
              startX: mx,
              startY: my,
              beat0: n.start_beat,
              pitch0: n.pitch,
            };
        draw();
      } else {
        setSelected(null);
        selectedRef.current = null;
        dragRef.current = { kind: "pan", startX: mx, viewStart0: viewRef.current.start };
        draw();
      }
    },
    [noteAt, seekTo, pushHistory, draw]
  );

  const onMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      const s = songRef.current;
      const drag = dragRef.current;
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;

      // cursor de feedback fora de drag
      if (drag.kind === "none") {
        const hit = noteAt(mx, my);
        canvas.style.cursor =
          my <= RULER_H + WAVE_H ? "text" : hit ? (hit.onEdge ? "ew-resize" : "grab") : "default";
        return;
      }
      if (!s) return;
      dragMovedRef.current = true;

      const { pxPerSec } = viewRef.current;
      const beatDur = beatDuration(s);

      if (drag.kind === "seek") {
        seekTo(viewRef.current.start + mx / pxPerSec);
      } else if (drag.kind === "pan") {
        viewRef.current.start = Math.max(-1, drag.viewStart0 - (mx - drag.startX) / pxPerSec);
        draw();
      } else if (drag.kind === "move") {
        const dBeats = Math.round((mx - drag.startX) / pxPerSec / beatDur);
        const dPitch = -Math.round((my - drag.startY) / 12);
        mutate((d) => {
          const n = d.notes[drag.noteIdx];
          n.start_beat = drag.beat0 + dBeats;
          n.pitch = drag.pitch0 + dPitch;
        }, false); // snapshot já foi feito no mousedown
      } else if (drag.kind === "resize") {
        const dBeats = Math.round((mx - drag.startX) / pxPerSec / beatDur);
        mutate((d) => {
          const n = d.notes[drag.noteIdx];
          n.duration_beats = Math.max(1, drag.dur0 + dBeats);
        }, false);
      }
    },
    [noteAt, seekTo, mutate, draw]
  );

  const onMouseUp = useCallback(() => {
    const drag = dragRef.current;
    // clique simples numa nota (sem arrastar): o snapshot de história feito
    // no mousedown não corresponde a mudança nenhuma - descarta
    if ((drag.kind === "move" || drag.kind === "resize") && !dragMovedRef.current) {
      historyRef.current.pop();
    }
    dragRef.current = { kind: "none" };
  }, []);

  const onDoubleClick = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      const hit = noteAt(e.clientX - rect.left, e.clientY - rect.top);
      if (hit) playNote(hit.idx);
    },
    [noteAt, playNote]
  );

  const onWheel = useCallback(
    (e: React.WheelEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const view = viewRef.current;
      if (e.ctrlKey) {
        // zoom ancorado no cursor
        const tAtCursor = view.start + mx / view.pxPerSec;
        const factor = Math.exp(-e.deltaY * 0.0015);
        view.pxPerSec = Math.min(MAX_PX_PER_SEC, Math.max(MIN_PX_PER_SEC, view.pxPerSec * factor));
        view.start = Math.max(-1, tAtCursor - mx / view.pxPerSec);
      } else {
        view.start = Math.max(-1, view.start + e.deltaY / view.pxPerSec);
      }
      draw();
    },
    [draw]
  );

  // ------------------------------------------------------------- teclado
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;

      if (e.code === "Space") {
        e.preventDefault();
        togglePlay();
        return;
      }
      if (e.ctrlKey && e.key.toLowerCase() === "z") {
        e.preventDefault();
        undo();
        return;
      }
      if (e.ctrlKey && e.key.toLowerCase() === "y") {
        e.preventDefault();
        redo();
        return;
      }

      const sel = selectedRef.current;
      const s = songRef.current;
      if (sel === null || !s) return;

      if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && e.altKey) {
        // Alt+setas: move a FRASE inteira que contém a nota selecionada -
        // o erro típico de alinhamento desloca o verso todo, não uma sílaba
        e.preventDefault();
        const delta = e.key === "ArrowLeft" ? -1 : 1;
        let lineStart = 0;
        let lineEnd = s.notes.length - 1;
        for (const b of s.phrase_breaks_after_index) {
          if (b < sel) lineStart = b + 1;
          if (b >= sel) {
            lineEnd = b;
            break;
          }
        }
        mutate((d) => {
          for (let k = lineStart; k <= lineEnd; k++) {
            d.notes[k].start_beat += delta;
          }
        });
        return;
      }

      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        const delta = e.key === "ArrowLeft" ? -1 : 1;
        if (e.shiftKey) {
          mutate((d) => {
            const n = d.notes[sel];
            n.duration_beats = Math.max(1, n.duration_beats + delta);
          });
        } else {
          mutate((d) => {
            d.notes[sel].start_beat += delta;
          });
        }
      } else if (e.key === "ArrowUp" || e.key === "ArrowDown") {
        e.preventDefault();
        const delta = e.key === "ArrowUp" ? 1 : -1;
        mutate((d) => {
          d.notes[sel].pitch += delta;
        });
      } else if (e.key === "Enter") {
        e.preventDefault();
        playNote(sel);
      } else if (e.key === "Delete") {
        e.preventDefault();
        deleteNote(sel);
      } else if (e.key === "Tab") {
        e.preventDefault();
        const next = Math.min(s.notes.length - 1, sel + 1);
        setSelected(next);
        selectedRef.current = next;
        draw();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [togglePlay, undo, redo, mutate, playNote, draw]);

  // ------------------------------------------------------ ações pontuais
  function deleteNote(idx: number) {
    mutate((d) => {
      d.notes.splice(idx, 1);
      // os índices de quebra de frase apontam para posições em `notes` -
      // remover uma nota desloca tudo que vem depois
      d.phrase_breaks_after_index = d.phrase_breaks_after_index
        .filter((b) => b !== idx)
        .map((b) => (b > idx ? b - 1 : b));
    });
    setSelected(null);
  }

  function togglePhraseBreak(idx: number) {
    mutate((d) => {
      const set = new Set(d.phrase_breaks_after_index);
      if (set.has(idx)) set.delete(idx);
      else set.add(idx);
      d.phrase_breaks_after_index = Array.from(set).sort((a, b) => a - b);
    });
  }

  async function handleSave() {
    const s = songRef.current;
    if (!s) return;
    setSaving(true);
    setStatusMsg(null);
    try {
      const result = await invoke<SaveResult>("save_song", { outDir, song: s, lang });
      setWarnings(result.warnings);
      setDirty(false);
      setStatusMsg(t("revSaved", { path: result.txtPath }));
    } catch (err) {
      setError(typeof err === "string" ? err : t("revSaveError"));
    } finally {
      setSaving(false);
    }
  }

  async function handleClose() {
    if (dirty) {
      const leave = await ask(t("revConfirmDiscard"), { title: "USKMaker", type: "warning" });
      if (!leave) return;
    }
    audioRef.current?.pause();
    onClose();
  }

  // ------------------------------------------------------------- render
  if (error) {
    return (
      <div className="review-screen">
        <div className="error-box">
          <strong>{t("errorPrefix")}</strong> {error}
        </div>
        <button className="secondary" onClick={onClose}>
          {t("revBack")}
        </button>
      </div>
    );
  }

  if (!song) {
    return (
      <div className="review-screen">
        <p className="subtitle">{t("revLoading")}</p>
      </div>
    );
  }

  const sel = selected !== null ? song.notes[selected] : null;
  // Pacotes antigos não têm o campo source - nesse caso a legenda e o botão
  // de "pular pra flagrada" não fazem sentido e ficam ocultos.
  const hasSourceInfo = song.notes.some((n) => n.source != null);
  const needsReview = (n: USNote) => n.source === "interpolated" || isLowConfidenceAnchor(n);
  const flaggedCount = song.notes.filter(needsReview).length;

  function jumpToNextFlagged() {
    const s = songRef.current;
    if (!s) return;
    const from = selectedRef.current !== null ? selectedRef.current : -1;
    const order = [...Array(s.notes.length).keys()];
    // procura a partir da seleção atual, dando a volta no fim
    const next = [...order.slice(from + 1), ...order.slice(0, from + 1)].find((i) => needsReview(s.notes[i]));
    if (next === undefined) return;
    setSelected(next);
    selectedRef.current = next;
    // centraliza a nota na viewport
    const t = beatToSec(s, s.notes[next].start_beat);
    const w = canvasRef.current?.clientWidth ?? 800;
    viewRef.current.start = Math.max(0, t - w / viewRef.current.pxPerSec / 2);
    draw();
  }

  const sourceLabels: Record<string, string> = {
    anchor: t("revSourceAnchor"),
    fuzzy: t("revSourceFuzzy"),
    realign: t("revSourceRealign"),
    lrc: t("revSourceLrc"),
    interpolated: t("revSourceInterp"),
  };

  return (
    <div className="review-screen">
      <div className="review-header">
        <h2>
          {t("revTitle")}: {song.artist} — {song.title}
          {dirty ? " *" : ""}
        </h2>
        <div className="review-header-actions">
          <button className="secondary" onClick={handleClose}>
            {t("revClose")}
          </button>
          <button className="submit-button compact" onClick={handleSave} disabled={saving || !dirty}>
            {saving ? t("revSaving") : t("revSave")}
          </button>
        </div>
      </div>

      <div className="review-toolbar">
        <button onClick={togglePlay} title="Space">
          {playing ? t("revPause") : t("revPlay")}
        </button>
        <button onClick={() => seekTo(0)} title={t("revToStart")}>
          ⏮
        </button>
        {vocalsPath && audioPath && (
          <select
            value={audioChoice}
            onChange={(e) => setAudioChoice(e.target.value as "mix" | "vocals")}
            title={t("revListenTitle")}
          >
            <option value="mix">{t("revListenMix")}</option>
            <option value="vocals">{t("revListenVocals")}</option>
          </select>
        )}
        <span className="toolbar-sep" />
        <label className="inline-label">
          {t("revGap")}
          <input
            type="number"
            className="gap-input"
            value={song.gap_ms}
            onChange={(e) => {
              const v = parseInt(e.target.value, 10);
              if (!isNaN(v)) mutate((d) => void (d.gap_ms = v));
            }}
          />
        </label>
        {[-100, -10, +10, +100].map((step) => (
          <button
            key={step}
            className="gap-step"
            title={t("revGapStepTitle")}
            onClick={() => mutate((d) => void (d.gap_ms += step))}
          >
            {step > 0 ? `+${step}` : step}
          </button>
        ))}
        <span className="toolbar-sep" />
        <button onClick={undo} title="Ctrl+Z">
          {t("revUndo")}
        </button>
        <button onClick={redo} title="Ctrl+Y">
          {t("revRedo")}
        </button>
        {hasSourceInfo && flaggedCount > 0 && (
          <>
            <span className="toolbar-sep" />
            <button className="jump-interpolated" onClick={jumpToNextFlagged} title={t("revNextFlaggedTitle")}>
              {t("revNextFlagged", { n: flaggedCount })}
            </button>
          </>
        )}
      </div>

      <canvas
        ref={minimapRef}
        className="review-minimap"
        title={t("revMinimapTitle")}
        onMouseDown={(e) => onMinimapSeek(e, false)}
        onMouseMove={(e) => onMinimapSeek(e, true)}
      />

      <div className="review-main">
        <div className="verse-list">
          {verses.map((v, i) => (
            <button
              key={i}
              id={`verse-item-${i}`}
              className={`verse-item ${i === activeVerse ? "active" : ""}`}
              onClick={() => jumpToVerse(i)}
            >
              <span className="verse-time">
                {Math.floor(v.time / 60)}:{String(Math.floor(v.time % 60)).padStart(2, "0")}
              </span>
              <span className="verse-text">{v.text}</span>
            </button>
          ))}
        </div>
        <canvas
          ref={canvasRef}
          className="review-canvas"
          onMouseDown={onMouseDown}
          onMouseMove={onMouseMove}
          onMouseUp={onMouseUp}
          onMouseLeave={onMouseUp}
          onDoubleClick={onDoubleClick}
          onWheel={onWheel}
        />
      </div>

      <p className="review-hints">{t("revHints")}</p>

      {hasSourceInfo && (
        <p className="review-legend">
          {t("revLegendTiming")}{" "}
          <span className="legend-chip" style={{ background: SOURCE_COLORS.anchor }} />{" "}
          {t("revLegendAnchor")}{" "}
          <span className="legend-chip" style={{ background: SOURCE_COLORS.fuzzy }} />{" "}
          {t("revLegendFuzzy")}{" "}
          <span className="legend-chip" style={{ background: SOURCE_COLORS.realign }} />{" "}
          {t("revLegendRealign")}{" "}
          <span className="legend-chip" style={{ background: SOURCE_COLORS.lrc }} />{" "}
          {t("revLegendLrc")}{" "}
          <span className="legend-chip" style={{ background: SOURCE_COLORS.interpolated }} />{" "}
          {t("revLegendInterp")} · <span className="legend-chip" style={{ background: LOW_CONFIDENCE_COLOR }} />{" "}
          {t("revLegendLowScore")} · <span className="legend-chip" style={{ background: "#c9a227" }} />{" "}
          {t("revLegendGolden")} · <span className="legend-chip" style={{ background: "#4a4a58" }} />{" "}
          {t("revLegendFreestyle")}
        </p>
      )}

      {sel !== null && selected !== null && (
        <div className="note-inspector">
          <div className="field-group">
            <label>{t("revSyllable")}</label>
            <input
              type="text"
              value={sel.text}
              onChange={(e) => mutate((d) => void (d.notes[selected].text = e.target.value))}
            />
          </div>
          <div className="field-group">
            <label>{t("revStartBeat")}</label>
            <input
              type="number"
              value={sel.start_beat}
              onChange={(e) => {
                const v = parseInt(e.target.value, 10);
                if (!isNaN(v)) mutate((d) => void (d.notes[selected].start_beat = v));
              }}
            />
          </div>
          <div className="field-group">
            <label>{t("revDuration")}</label>
            <input
              type="number"
              min={1}
              value={sel.duration_beats}
              onChange={(e) => {
                const v = parseInt(e.target.value, 10);
                if (!isNaN(v) && v >= 1)
                  mutate((d) => void (d.notes[selected].duration_beats = v));
              }}
            />
          </div>
          <div className="field-group">
            <label>{t("revPitch")}</label>
            <input
              type="number"
              value={sel.pitch}
              onChange={(e) => {
                const v = parseInt(e.target.value, 10);
                if (!isNaN(v)) mutate((d) => void (d.notes[selected].pitch = v));
              }}
            />
          </div>
          <div className="field-group">
            <label>{t("revType")}</label>
            <select
              value={sel.note_type}
              onChange={(e) => mutate((d) => void (d.notes[selected].note_type = e.target.value))}
            >
              <option value=":">{t("revTypeNormal")}</option>
              <option value="*">{t("revTypeGolden")}</option>
              <option value="F">{t("revTypeFreestyle")}</option>
            </select>
          </div>
          <div className="field-group inspector-side">
            <label className="checkbox-line">
              <input
                type="checkbox"
                checked={song.phrase_breaks_after_index.includes(selected)}
                onChange={() => togglePhraseBreak(selected)}
              />
              {t("revPhraseBreak")}
            </label>
            <span className="note-time">
              {t("revNoteTime", {
                start: beatToSec(song, sel.start_beat).toFixed(2),
                dur: (sel.duration_beats * beatDuration(song)).toFixed(2),
              })}
            </span>
            {sel.source != null && (
              <span
                className="note-source"
                style={{ color: isLowConfidenceAnchor(sel) ? LOW_CONFIDENCE_COLOR : SOURCE_COLORS[sel.source] ?? "#9a9aa8" }}
              >
                {sourceLabels[sel.source] ?? sel.source}
                {/* score cru visível pra não fazer o revisor confiar cegamente num threshold arbitrário */}
                {typeof sel.score === "number" && ` (${sel.score.toFixed(2)})`}
              </span>
            )}
            <button className="danger" onClick={() => deleteNote(selected)}>
              {t("revDeleteNote")}
            </button>
          </div>
        </div>
      )}

      {statusMsg && <div className="result-box slim">{statusMsg}</div>}
      {warnings.length > 0 && (
        <div className="error-box">
          <strong>{t("revWarnings")}</strong>
          <ul>
            {warnings.map((wr, i) => (
              <li key={i}>{wr}</li>
            ))}
          </ul>
        </div>
      )}
      {!currentAudioFile && <div className="error-box">{t("revNoAudio")}</div>}

      <audio
        ref={audioRef}
        style={{ display: "none" }}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
      />
    </div>
  );
}

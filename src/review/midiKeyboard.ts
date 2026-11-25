// Teclado MIDI na tela de revisão: tocar as notas certas num teclado MIDI por
// cima do playback (estilo "mini DAW") e ouvir um clique de metrônomo.
//
// - Entrada pela Web MIDI API (WebView2 no Windows; o webkit2gtk do Linux não
//   tem Web MIDI, e aí o botão some, como o do microfone).
// - Gravação: enquanto a música toca, a nota sob o playhead recebe o pitch da
//   tecla apertada. O timing das notas NÃO muda - só o pitch.
// - Clique: andamento derivado do #BPM do chart; a fase vem dos ataques do
//   próprio áudio (o GAP é o início da 1ª nota, não um tempo forte).
//
// A lógica pura (sem Web Audio/Web MIDI) fica no topo e é testada em
// test/midiKeyboard.test.ts; as classes que tocam som ficam no fim.

// ------------------------------------------------------------ MIDI cru

export interface MidiEvent {
  kind: "on" | "off";
  note: number;
  velocity: number;
}

/** Decodifica note on/off de qualquer canal. Note on com velocity 0 = note off (padrão MIDI). */
export function parseMidiMessage(data: ArrayLike<number> | null | undefined): MidiEvent | null {
  if (!data || data.length < 3) return null;
  const status = data[0] & 0xf0;
  const note = data[1] & 0x7f;
  const velocity = data[2] & 0x7f;
  if (status === 0x90 && velocity > 0) return { kind: "on", note, velocity };
  if (status === 0x80 || (status === 0x90 && velocity === 0)) return { kind: "off", note, velocity: 0 };
  return null;
}

/** Pitch do UltraStar é relativo ao C4: pitch 0 = C4 = MIDI 60. */
export function midiToPitch(note: number): number {
  return note - 60;
}

/**
 * Teclas seguradas, na ordem em que foram apertadas. A melodia de karaokê é
 * uma voz só, então vale a ÚLTIMA apertada ("last note priority", como num
 * sintetizador monofônico): num legato a nova tecla entra antes de a anterior
 * sair, e é a nova que o usuário quer.
 */
export class HeldKeys {
  private order: number[] = [];

  press(note: number): void {
    this.release(note);
    this.order.push(note);
  }

  release(note: number): void {
    const i = this.order.indexOf(note);
    if (i >= 0) this.order.splice(i, 1);
  }

  clear(): void {
    this.order = [];
  }

  /** Tecla que vale agora (a última apertada ainda segurada), ou null. */
  get active(): number | null {
    return this.order.length > 0 ? this.order[this.order.length - 1] : null;
  }

  get all(): readonly number[] {
    return this.order;
  }
}

// ------------------------------------------------------------ gravação

export interface TimedNote {
  start_beat: number;
  duration_beats: number;
  note_type: string;
  pitch: number;
}

/** Índice da nota que toca em `t` segundos, ou -1. Notas em ordem de início. */
export function noteIndexAt(notes: readonly TimedNote[], t: number, toSec: (beat: number) => number): number {
  for (let i = 0; i < notes.length; i++) {
    const n = notes[i];
    const t0 = toSec(n.start_beat);
    if (t0 > t) break;
    if (t < toSec(n.start_beat + n.duration_beats)) return i;
  }
  return -1;
}

/**
 * O playhead já desconta a latência de saída (BufferPlayer.currentTime), mas
 * a mão chega depois do ouvido: avaliar um pouco ATRÁS do playhead põe a
 * tecla apertada logo depois do início de uma nota curta na nota certa, e não
 * na seguinte.
 */
export const RECORD_REACTION_S = 0.05;

/** Salto maior que isto entre dois quadros = o usuário pulou (seek), não tempo tocado. */
const MAX_FRAME_DT_S = 0.25;

/**
 * Gravação por cima do playback. Para cada nota, acumula quanto tempo cada
 * tecla ficou apertada enquanto ela tocava, e a nota fica com a tecla que
 * mais durou nela. Assim um legato desleixado (a tecla anterior ainda presa
 * no começo da nota seguinte, ou a próxima entrando antes da hora) não troca
 * o pitch de uma nota pelo da vizinha: quem ganha é a tecla que ocupou a nota.
 *
 * Notas freestyle ("F") não têm pitch significativo e ficam de fora.
 */
export class PitchRecorder {
  private acc = new Map<number, Map<number, number>>();
  private lastT: number | null = null;

  /** Esquece o passe atual (pausa, parada, nova gravação). */
  reset(): void {
    this.acc.clear();
    this.lastT = null;
  }

  /**
   * Um quadro do playback: `t` = posição (s), `pitch` = pitch UltraStar da
   * tecla que vale agora (null = nenhuma). Devolve a nota que deve mudar de
   * pitch neste quadro, se alguma.
   */
  step(
    notes: readonly TimedNote[],
    t: number,
    pitch: number | null,
    toSec: (beat: number) => number
  ): { index: number; pitch: number } | null {
    const last = this.lastT;
    this.lastT = t;
    if (last === null || pitch === null) return null;
    const dt = t - last;
    if (dt <= 0 || dt > MAX_FRAME_DT_S) return null;

    const i = noteIndexAt(notes, t - RECORD_REACTION_S, toSec);
    if (i < 0 || notes[i].note_type === "F") return null;

    let perKey = this.acc.get(i);
    if (!perKey) {
      perKey = new Map();
      this.acc.set(i, perKey);
    }
    perKey.set(pitch, (perKey.get(pitch) ?? 0) + dt);

    let best = pitch;
    let bestT = -1;
    for (const [p, secs] of perKey) {
      if (secs > bestT) {
        best = p;
        bestT = secs;
      }
    }
    return notes[i].pitch !== best ? { index: i, pitch: best } : null;
  }
}

// ------------------------------------------------------------ metrônomo

/**
 * Período do clique (s) a partir do #BPM do chart. No UltraStar o #BPM vale
 * 4x o andamento (beat = 60 / (BPM * 4)), e o #BPM automático é levado por
 * oitavas para [200, 400) - então BPM/4 já é o andamento ou metade/dobro dele.
 * Dobra/divide até cair numa faixa de clique confortável, [70, 180) por min.
 */
export function clickPeriodSec(bpm: number): number {
  if (!(bpm > 0) || !isFinite(bpm)) return NaN;
  let perMin = bpm / 4;
  while (perMin < 70) perMin *= 2;
  while (perMin >= 180) perMin /= 2;
  return 60 / perMin;
}

/**
 * Curva de ataques do áudio: energia RMS em janelas de `hopSec` e, dela, só a
 * subida de um quadro para o seguinte (bumbo, caixa e ataques de acorde viram
 * picos; nota sustentada não). Taxa de saída = 1 / hopSec.
 */
export function onsetEnvelope(samples: Float32Array, sampleRate: number, hopSec = 0.01): Float32Array {
  const hop = Math.max(1, Math.round(sampleRate * hopSec));
  const frames = Math.floor(samples.length / hop);
  const env = new Float32Array(frames);
  let prev = 0;
  for (let f = 0; f < frames; f++) {
    let sum = 0;
    const base = f * hop;
    for (let i = 0; i < hop; i++) {
      const v = samples[base + i];
      sum += v * v;
    }
    const rms = Math.sqrt(sum / hop);
    env[f] = Math.max(0, rms - prev);
    prev = rms;
  }
  return env;
}

/**
 * Fase (s, em [0, período)) que põe o clique em cima dos ataques: testa cada
 * deslocamento na resolução da curva e fica com o que soma mais energia nos
 * instantes fase + k·período. Pega o tempo forte em música com bateria; em
 * música sem ataques claros devolve algo arbitrário (o clique continua no
 * andamento certo, só deslocado).
 */
export function estimateBeatPhase(env: Float32Array, rate: number, period: number): number {
  const step = Math.max(1, Math.round(period * rate));
  if (!(period > 0) || env.length < step) return 0;
  let bestPhase = 0;
  let bestScore = -1;
  for (let ph = 0; ph < step; ph++) {
    let score = 0;
    for (let k = 0; ; k++) {
      const idx = Math.round(ph + k * period * rate);
      if (idx >= env.length) break;
      score += env[idx];
    }
    if (score > bestScore) {
      bestScore = score;
      bestPhase = ph;
    }
  }
  return bestPhase / rate;
}

/** Instantes de clique em [t0, t1), para um período e uma fase. */
export function clickTimesBetween(t0: number, t1: number, period: number, phase: number): number[] {
  if (!(period > 0) || !(t1 > t0)) return [];
  const out: number[] = [];
  let k = Math.ceil((t0 - phase) / period - 1e-9);
  for (let c = phase + k * period; c < t1; c = phase + ++k * period) {
    if (c >= t0) out.push(c);
  }
  return out;
}

// ------------------------------------------------------------ som (Web Audio)

/** Sintetizador polifônico simples para ouvir as teclas (mesmo timbre triangular da prévia de nota). */
export class KeySynth {
  private voices = new Map<number, { osc: OscillatorNode; gain: GainNode }>();
  // campo explícito, não "parameter property": o `npm test` roda com
  // --experimental-strip-types, que não aceita essa sintaxe
  private readonly getContext: () => AudioContext | null;

  constructor(getContext: () => AudioContext | null) {
    this.getContext = getContext;
  }

  noteOn(note: number, velocity: number): void {
    const ctx = this.getContext();
    if (!ctx) return;
    if (ctx.state === "suspended") void ctx.resume();
    this.noteOff(note);
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "triangle";
    osc.frequency.value = 440 * Math.pow(2, (note - 69) / 12);
    const peak = 0.08 + 0.27 * (velocity / 127);
    gain.gain.setValueAtTime(0.0001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(peak, ctx.currentTime + 0.008);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    this.voices.set(note, { osc, gain });
  }

  noteOff(note: number): void {
    const v = this.voices.get(note);
    if (!v) return;
    this.voices.delete(note);
    const now = v.gain.context.currentTime;
    v.gain.gain.cancelScheduledValues(now);
    v.gain.gain.setTargetAtTime(0, now, 0.04);
    v.osc.stop(now + 0.25);
  }

  allOff(): void {
    for (const note of [...this.voices.keys()]) this.noteOff(note);
  }
}

/** Um clique curto (seno de 1,5 kHz, 25 ms) no instante `when` do contexto. */
export function scheduleClick(ctx: AudioContext, when: number): OscillatorNode {
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.type = "sine";
  osc.frequency.value = 1500;
  gain.gain.setValueAtTime(0.0001, when);
  gain.gain.exponentialRampToValueAtTime(0.35, when + 0.002);
  gain.gain.exponentialRampToValueAtTime(0.0001, when + 0.025);
  osc.connect(gain);
  gain.connect(ctx.destination);
  osc.start(when);
  osc.stop(when + 0.03);
  return osc;
}

// ------------------------------------------------------------ Web MIDI

export function midiSupported(): boolean {
  return typeof navigator !== "undefined" && typeof navigator.requestMIDIAccess === "function";
}

/**
 * Abre a Web MIDI e escuta TODAS as entradas (inclusive as plugadas depois).
 * Devolve uma função que desliga tudo. `onDevices` recebe os nomes das
 * entradas conectadas sempre que a lista muda.
 */
export async function openMidiInputs(
  onEvent: (e: MidiEvent) => void,
  onDevices: (names: string[]) => void
): Promise<() => void> {
  const access = await navigator.requestMIDIAccess({ sysex: false });
  const handler = (msg: MIDIMessageEvent) => {
    const ev = parseMidiMessage(msg.data);
    if (ev) onEvent(ev);
  };
  const attach = () => {
    const names: string[] = [];
    access.inputs.forEach((input) => {
      input.onmidimessage = handler;
      if (input.state === "connected") names.push(input.name ?? "MIDI");
    });
    onDevices(names);
  };
  attach();
  access.onstatechange = attach;
  return () => {
    access.onstatechange = null;
    access.inputs.forEach((input) => {
      input.onmidimessage = null;
    });
  };
}

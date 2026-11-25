// Testes do src/review/midiKeyboard.ts (teclado MIDI na revisão) - rodar com
// `npm test`. Sem Web MIDI nem Web Audio: só a lógica pura.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  HeldKeys,
  PitchRecorder,
  RECORD_REACTION_S,
  clickPeriodSec,
  clickTimesBetween,
  estimateBeatPhase,
  midiToPitch,
  noteIndexAt,
  onsetEnvelope,
  parseMidiMessage,
} from "../src/review/midiKeyboard.ts";

// 1 beat = 0,1 s, sem GAP: deixa as contas de tempo legíveis
const toSec = (beat: number) => beat * 0.1;
const note = (start: number, dur: number, pitch = 0, type = ":") => ({
  start_beat: start,
  duration_beats: dur,
  pitch,
  note_type: type,
});

test("parseMidiMessage: note on/off de qualquer canal", () => {
  assert.deepEqual(parseMidiMessage([0x90, 60, 100]), { kind: "on", note: 60, velocity: 100 });
  assert.deepEqual(parseMidiMessage([0x93, 64, 1]), { kind: "on", note: 64, velocity: 1 });
  assert.deepEqual(parseMidiMessage([0x80, 60, 40]), { kind: "off", note: 60, velocity: 0 });
  // note on com velocity 0 é note off (muitos teclados mandam assim)
  assert.deepEqual(parseMidiMessage([0x90, 60, 0]), { kind: "off", note: 60, velocity: 0 });
});

test("parseMidiMessage ignora o que não é nota", () => {
  assert.equal(parseMidiMessage([0xb0, 64, 127]), null); // pedal de sustain
  assert.equal(parseMidiMessage([0xe0, 0, 64]), null); // pitch bend
  assert.equal(parseMidiMessage([0xf8]), null); // clock
  assert.equal(parseMidiMessage(null), null);
});

test("midiToPitch: C4 (MIDI 60) é o pitch 0 do UltraStar", () => {
  assert.equal(midiToPitch(60), 0);
  assert.equal(midiToPitch(51), -9); // D#3, como no piano da revisão
  assert.equal(midiToPitch(72), 12);
});

test("HeldKeys: vale a última tecla apertada que ainda está segurada", () => {
  const k = new HeldKeys();
  assert.equal(k.active, null);
  k.press(60);
  k.press(64); // legato: 64 entra antes de 60 sair
  assert.equal(k.active, 64);
  k.release(64);
  assert.equal(k.active, 60);
  k.release(60);
  assert.equal(k.active, null);
  k.press(60);
  k.press(60); // repetido não duplica
  k.release(60);
  assert.equal(k.active, null);
});

test("noteIndexAt acha a nota sob o tempo, ou -1 no silêncio", () => {
  const notes = [note(0, 5), note(10, 5)];
  assert.equal(noteIndexAt(notes, 0.2, toSec), 0);
  assert.equal(noteIndexAt(notes, 0.7, toSec), -1); // entre as notas
  assert.equal(noteIndexAt(notes, 1.0, toSec), 1);
  assert.equal(noteIndexAt(notes, 1.5, toSec), -1); // fim exclusivo
});

/** Simula o playback a 60 quadros/s de t0 a t1 com a tecla `pitchAt(t)`. */
function play(rec: PitchRecorder, notes: ReturnType<typeof note>[], t0: number, t1: number, pitchAt: (t: number) => number | null) {
  for (let t = t0; t < t1; t += 1 / 60) {
    const ch = rec.step(notes, t, pitchAt(t), toSec);
    if (ch) notes[ch.index].pitch = ch.pitch;
  }
}

test("gravação: a nota sob o playhead fica com a tecla tocada", () => {
  const notes = [note(0, 5, 0), note(10, 5, 0)];
  const rec = new PitchRecorder();
  play(rec, notes, 0, 1.6, (t) => (t < 0.7 ? 4 : 7));
  assert.deepEqual(notes.map((n) => n.pitch), [4, 7]);
});

test("gravação: legato desleixado não contamina a nota vizinha", () => {
  // nota 0 em [0, 0,5) s, nota 1 em [0,5, 1,0) s. A tecla da nota 0 (pitch 2)
  // fica presa 0,1 s dentro da nota 1, que é tocada com o pitch 9.
  const notes = [note(0, 5, 0), note(5, 5, 0)];
  const rec = new PitchRecorder();
  const lag = 0.1 + RECORD_REACTION_S;
  play(rec, notes, 0, 1.0 + RECORD_REACTION_S, (t) => (t < 0.5 + lag ? 2 : 9));
  assert.deepEqual(notes.map((n) => n.pitch), [2, 9]);
});

test("gravação: sem tecla nada muda, e freestyle é ignorada", () => {
  const notes = [note(0, 5, 3), note(10, 5, 3, "F")];
  const rec = new PitchRecorder();
  play(rec, notes, 0, 0.6, () => null);
  play(rec, notes, 0.6, 1.6, () => 12);
  assert.deepEqual(notes.map((n) => n.pitch), [3, 3]);
});

test("gravação: um salto de playhead (seek) não conta como tempo tocado", () => {
  const notes = [note(0, 50, 0)];
  const rec = new PitchRecorder();
  assert.equal(rec.step(notes, 0.10, 5, toSec), null); // 1º quadro só marca o tempo
  assert.equal(rec.step(notes, 3.00, 5, toSec), null); // pulou 2,9 s
  assert.deepEqual(rec.step(notes, 3.02, 5, toSec), { index: 0, pitch: 5 });
});

test("clickPeriodSec: #BPM do UltraStar é 4x o andamento", () => {
  // caso real (Ocean Grove): andamento 97,51 -> #BPM 390,04
  assert.ok(Math.abs(clickPeriodSec(390.04) - 60 / 97.51) < 1e-3);
  // #BPM 240 = andamento 60 -> dobra para 120 (faixa confortável)
  assert.ok(Math.abs(clickPeriodSec(240) - 0.5) < 1e-9);
  // #BPM manual baixo (ex.: 100) = 25 -> 100
  assert.ok(Math.abs(clickPeriodSec(100) - 0.6) < 1e-9);
  assert.ok(Number.isNaN(clickPeriodSec(0)));
});

test("estimateBeatPhase acha a fase dos ataques", () => {
  // 20 s de "bateria": impulso a cada 0,5 s começando em 0,23 s, mais ruído
  const sr = 8000;
  const samples = new Float32Array(sr * 20);
  let seed = 1;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647 - 0.5) * 0.02;
  for (let i = 0; i < samples.length; i++) samples[i] = rnd();
  for (let t = 0.23; t < 20; t += 0.5) {
    const i0 = Math.round(t * sr);
    for (let i = 0; i < 200; i++) samples[i0 + i] += Math.exp(-i / 40) * (i % 2 ? 0.8 : -0.8);
  }
  const env = onsetEnvelope(samples, sr, 0.01);
  const phase = estimateBeatPhase(env, 100, 0.5);
  assert.ok(Math.abs(phase - 0.23) <= 0.02, `fase ${phase}`);
});

test("clickTimesBetween lista os cliques da janela", () => {
  const c = clickTimesBetween(1.0, 2.1, 0.5, 0.2);
  assert.deepEqual(c.map((x) => Math.round(x * 100) / 100), [1.2, 1.7]);
  assert.deepEqual(clickTimesBetween(0, 0.3, 0.5, 0.2), [0.2]);
  assert.deepEqual(clickTimesBetween(2, 1, 0.5, 0), []);
});

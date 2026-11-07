// Testes do src/review/micPitch.ts (sing-along) - rodar com `npm test`.
// Sinais sintéticos: sem microfone, sem Tauri. Cobre a conversão Hz->semitom
// (mesma do pitch.py), o pitchy em cima de senoides e as regras do rastro.
import { test } from "node:test";
import assert from "node:assert/strict";
import { PitchDetector } from "pitchy";
import {
  MIC_GAP_S,
  MIC_TRAIL_S,
  hzToUltrastarPitch,
  pushMicSample,
  type MicSample,
} from "../src/review/micPitch.ts";

const SR = 48000;
const FFT = 2048;

function sine(hz: number): Float32Array {
  const buf = new Float32Array(FFT);
  for (let i = 0; i < FFT; i++) buf[i] = Math.sin((2 * Math.PI * hz * i) / SR);
  return buf;
}

test("Hz -> semitom UltraStar bate em 4 oitavas", () => {
  const cases: [number, number][] = [
    [440, 9],
    [261.63, 0],
    [523.25, 12],
    [196, -5],
  ];
  for (const [hz, expected] of cases) {
    assert.ok(Math.abs(hzToUltrastarPitch(hz) - expected) < 0.01, `${hz} Hz`);
  }
});

test("pitchy + conversão acertam o semitom de tons puros", () => {
  const detector = PitchDetector.forFloat32Array(FFT);
  for (const [hz, expected] of [[440, 9], [261.63, 0], [196, -5]] as const) {
    const [detected, clarity] = detector.findPitch(sine(hz), SR);
    assert.ok(clarity >= 0.9, `clareza ${hz} Hz`);
    assert.ok(Math.abs(hzToUltrastarPitch(detected) - expected) < 0.1, `${hz} Hz`);
  }
});

test("leitura fraca ou fora da voz não entra no rastro", () => {
  const trail: MicSample[] = [];
  pushMicSample(trail, 440, 0.5, 1); // clareza baixa
  pushMicSample(trail, 30, 0.99, 1.1); // grave demais
  pushMicSample(trail, 3000, 0.99, 1.2); // agudo demais
  assert.equal(trail.length, 0);
  pushMicSample(trail, 440, 0.99, 1.3);
  assert.equal(trail.length, 1);
});

test("descarta o que passou da janela de 5s", () => {
  const trail: MicSample[] = [];
  pushMicSample(trail, 440, 0.99, 1);
  pushMicSample(trail, 440, 0.99, 2);
  pushMicSample(trail, 440, 0.99, 1 + MIC_TRAIL_S + 0.5);
  assert.deepEqual(trail.map((s) => s.t), [2, 1 + MIC_TRAIL_S + 0.5]);
});

test("a limpeza roda mesmo quando a leitura nova é descartada", () => {
  const trail: MicSample[] = [];
  pushMicSample(trail, 440, 0.99, 1);
  pushMicSample(trail, 440, 0.1, 1 + MIC_TRAIL_S + 1); // silêncio, mas o tempo andou
  assert.equal(trail.length, 0);
});

test("voltar a música no tempo zera o rastro (sem reta pro futuro)", () => {
  const trail: MicSample[] = [];
  pushMicSample(trail, 440, 0.99, 10);
  pushMicSample(trail, 440, 0.99, 10.1);
  pushMicSample(trail, 440, 0.99, 3); // seek pra trás
  assert.deepEqual(trail.map((s) => s.t), [3]);
});

test("o intervalo de quebra do traçado é maior que um frame e menor que uma sílaba", () => {
  assert.ok(MIC_GAP_S > 1 / 30);
  assert.ok(MIC_GAP_S < 0.5);
});

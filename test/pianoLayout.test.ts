// Testes do src/review/pianoLayout.ts (teclado horizontal da Revisão) - rodar
// com `npm test`.
import { test } from "node:test";
import assert from "node:assert/strict";
import { isBlackKey, keyAt, midiName, pianoLayout } from "../src/review/pianoLayout.ts";

test("nomes no mesmo padrão do piano lateral (C4 = MIDI 60)", () => {
  assert.equal(midiName(60), "C4");
  assert.equal(midiName(61), "C#4");
  assert.equal(midiName(51), "D#3");
  assert.equal(midiName(36), "C2");
  assert.equal(midiName(24), "C1");
});

test("teclado de 61 teclas (C2-C7): 36 brancas, 25 pretas, largura total 1", () => {
  const keys = pianoLayout(36, 96);
  assert.equal(keys.length, 61);
  const whites = keys.filter((k) => !k.black);
  assert.equal(whites.length, 36);
  assert.equal(keys.filter((k) => k.black).length, 25);
  assert.ok(Math.abs(whites[0].left) < 1e-9);
  const last = whites[whites.length - 1];
  assert.ok(Math.abs(last.left + last.width - 1) < 1e-9);
});

test("tecla preta fica centrada na divisa entre as brancas vizinhas", () => {
  const keys = pianoLayout(60, 64); // C4 C#4 D4 D#4 E4
  const c = keys.find((k) => k.name === "C4")!;
  const cs = keys.find((k) => k.name === "C#4")!;
  assert.ok(isBlackKey(cs.midi) && !isBlackKey(c.midi));
  const edge = c.left + c.width;
  assert.ok(Math.abs(cs.left + cs.width / 2 - edge) < 1e-9);
});

test("pontas em tecla preta são puxadas para a branca de fora", () => {
  const keys = pianoLayout(61, 63); // C#4..D#4 -> C4..E4
  assert.equal(keys[0].name, "C4");
  assert.equal(keys[keys.length - 1].name, "E4");
});

test("keyAt: preta tem prioridade em cima, branca embaixo", () => {
  const keys = pianoLayout(60, 64);
  const c = keys.find((k) => k.name === "C4")!;
  const edge = c.left + c.width;
  assert.equal(keyAt(keys, edge, 0.3)!.name, "C#4"); // em cima da divisa: a preta
  assert.equal(keyAt(keys, edge - 0.001, 0.9)!.name, "C4"); // embaixo: a branca
  assert.equal(keyAt(keys, 1.5, 0.9), null);
});

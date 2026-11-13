// Testes do src/review/suspectLines.ts (linhas suspeitas da revisão) - rodar
// com `npm test`. Notas são booleanos: true = suspeita.
import { test } from "node:test";
import assert from "node:assert/strict";
import { countLines, nextSuspectLine, suspectLines } from "../src/review/suspectLines.ts";

const isSuspect = (n: boolean) => n;
const T = true;
const F = false;

test("sem quebras: a música inteira é uma linha", () => {
  assert.equal(countLines(3, []), 1);
  assert.deepEqual(suspectLines([F, T, F], [], isSuspect), [{ start: 0, end: 2 }]);
});

test("várias linhas: só entram as que têm nota suspeita", () => {
  // linhas: 0-1 | 2-4 | 5-6
  const notes = [F, F, F, T, F, F, T];
  assert.equal(countLines(notes.length, [1, 4]), 3);
  assert.deepEqual(suspectLines(notes, [1, 4], isSuspect), [
    { start: 2, end: 4 },
    { start: 5, end: 6 },
  ]);
});

test("quebras fora de ordem dão o mesmo resultado", () => {
  const notes = [T, F, F, F, F, T];
  assert.deepEqual(
    suspectLines(notes, [3, 1], isSuspect),
    suspectLines(notes, [1, 3], isSuspect)
  );
  assert.equal(countLines(notes.length, [3, 1]), 3);
});

test("notas depois da última quebra formam a linha final", () => {
  assert.deepEqual(suspectLines([F, F, F, T], [1], isSuspect), [{ start: 2, end: 3 }]);
});

test("quebra na última nota, repetida ou fora da faixa não cria linha vazia", () => {
  assert.equal(countLines(4, [1, 1, 3, 9, -1]), 2);
});

test("próxima linha suspeita: depois da nota dada, com volta no fim", () => {
  const lines = suspectLines([T, F, F, T, F, T], [1, 3], isSuspect);
  assert.deepEqual(lines.map((l) => l.start), [0, 2, 4]);
  assert.equal(nextSuspectLine(lines, -1), 0);
  assert.equal(nextSuspectLine(lines, 0), 1); // dentro da linha 0 -> vai pra seguinte
  assert.equal(nextSuspectLine(lines, 3), 2);
  assert.equal(nextSuspectLine(lines, 5), 0); // passou da última: volta
});

test("nenhuma suspeita", () => {
  const lines = suspectLines([F, F, F], [0], isSuspect);
  assert.deepEqual(lines, []);
  assert.equal(nextSuspectLine(lines, 0), null);
});

test("vazio", () => {
  assert.deepEqual(suspectLines([], [], isSuspect), []);
  assert.deepEqual(suspectLines([], [2], isSuspect), []);
  assert.equal(countLines(0, []), 0);
});

// Testes do src/review/noteEdit.ts (cortar, copiar/colar e duplicar notas na
// Revisão) - rodar com `npm test`. Letras inventadas.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  continuationTexts,
  copyNotes,
  duplicateNotes,
  extendNote,
  insertClip,
  sliceBeat,
  splitNote,
} from "../src/review/noteEdit.ts";

interface N {
  start_beat: number;
  duration_beats: number;
  text: string;
  pitch: number;
  note_type: string;
}
const n = (start_beat: number, duration_beats: number, text: string, pitch = 0): N => ({
  start_beat,
  duration_beats,
  text,
  pitch,
  note_type: ":",
});
const song = (notes: N[], breaks: number[] = []) => ({ notes, phrase_breaks_after_index: breaks });
const texts = (s: { notes: N[] }) => s.notes.map((x) => x.text);
const spans = (s: { notes: N[] }) => s.notes.map((x) => [x.start_beat, x.duration_beats]);

test("continuação: a sílaba fica na 1ª, o espaço de fim de palavra vai para o ~", () => {
  assert.deepEqual(continuationTexts("lua "), ["lua", "~ "]);
  assert.deepEqual(continuationTexts("lu"), ["lu", "~"]);
  assert.deepEqual(continuationTexts("~ "), ["~", "~ "]);
  assert.deepEqual(continuationTexts(""), ["", "~"]);
});

test("sliceBeat arredonda e deixa as duas partes com 1 beat ou mais", () => {
  assert.equal(sliceBeat(n(10, 8, "x"), 13.4), 13);
  assert.equal(sliceBeat(n(10, 8, "x"), 10.2), 11); // grudado no início
  assert.equal(sliceBeat(n(10, 8, "x"), 17.9), 17); // grudado no fim
  assert.equal(sliceBeat(n(10, 1, "x"), 10.5), null); // 1 beat não corta
});

test("splitNote: 2ª parte é ~ no mesmo pitch, e a quebra de frase vai junto para o fim", () => {
  const s = song([n(0, 4, "so "), n(4, 8, "lar ", 5), n(16, 4, "mar ")], [1]);
  const tail = splitNote(s, 1, 7);
  assert.equal(tail, 2);
  assert.deepEqual(texts(s), ["so ", "lar", "~ ", "mar "]);
  assert.deepEqual(spans(s), [[0, 4], [4, 3], [7, 5], [16, 4]]);
  assert.equal(s.notes[2].pitch, 5);
  assert.deepEqual(s.phrase_breaks_after_index, [2]); // depois do ~, não no meio da palavra
});

test("splitNote em nota de 1 beat não muda nada", () => {
  const s = song([n(0, 1, "a ")], []);
  assert.equal(splitNote(s, 0, 0.5), null);
  assert.deepEqual(texts(s), ["a "]);
});

test("extendNote (Ctrl+D de uma nota): continuação do mesmo tamanho logo depois", () => {
  const s = song([n(0, 4, "ven "), n(10, 2, "to ")], [0]);
  assert.equal(extendNote(s, 0), 1);
  assert.deepEqual(texts(s), ["ven", "~ ", "to "]);
  assert.deepEqual(spans(s), [[0, 4], [4, 4], [10, 2]]);
  assert.deepEqual(s.phrase_breaks_after_index, [1]);
});

test("extendNote para no início da nota seguinte; sem espaço não estende", () => {
  const s = song([n(0, 8, "mar "), n(10, 2, "e ")]);
  assert.equal(extendNote(s, 0), 1);
  assert.deepEqual(spans(s), [[0, 8], [8, 2], [10, 2]]);
  const cheia = song([n(0, 4, "sol "), n(4, 2, "e ")]);
  assert.equal(extendNote(cheia, 0), null);
  assert.deepEqual(texts(cheia), ["sol ", "e "]);
});

test("copyNotes guarda posição relativa, as quebras entre as notas e o tamanho do trecho", () => {
  const s = song([n(0, 2, "a "), n(8, 2, "be "), n(12, 3, "ce "), n(20, 2, "de ")], [2]);
  const clip = copyNotes(s, [2, 1, 1])!; // ordem e repetição não importam
  assert.deepEqual(clip.notes.map((x) => [x.start_beat, x.text]), [[0, "be "], [4, "ce "]]);
  assert.deepEqual(clip.breaksAfter, [1]);
  assert.equal(clip.span, 7);
  assert.equal(copyNotes(s, []), null);
});

test("insertClip cola no beat pedido, em ordem de tempo, e leva a quebra de frase junto", () => {
  const s = song([n(0, 2, "a "), n(8, 2, "be "), n(12, 3, "ce "), n(40, 2, "de ")], [2]);
  const clip = copyNotes(s, [1, 2])!;
  const placed = insertClip(s, clip, 30);
  assert.deepEqual(placed, [3, 4]);
  assert.deepEqual(texts(s), ["a ", "be ", "ce ", "be ", "ce ", "de "]);
  assert.deepEqual(spans(s).slice(3, 5), [[30, 2], [34, 3]]);
  assert.deepEqual(s.phrase_breaks_after_index, [2, 4]);
});

test("insertClip não reordena notas existentes fora de ordem", () => {
  // nota 1 foi arrastada para antes da 0 (o editor não reordena ao arrastar)
  const s = song([n(10, 2, "a "), n(4, 2, "b "), n(20, 2, "c ")], []);
  const clip = copyNotes(s, [2])!;
  insertClip(s, clip, 15);
  assert.deepEqual(texts(s), ["a ", "b ", "c ", "c "]);
  assert.deepEqual(s.notes.map((x) => x.start_beat), [10, 4, 15, 20]);
});

test("duplicateNotes (Ctrl+D com várias notas): cópia exata logo depois do fim da seleção", () => {
  const s = song([n(0, 2, "na "), n(4, 2, "na "), n(16, 2, "fim ")], [1]);
  const placed = duplicateNotes(s, [0, 1]);
  assert.deepEqual(placed, [2, 3]);
  assert.deepEqual(spans(s), [[0, 2], [4, 2], [6, 2], [10, 2], [16, 2]]);
  assert.deepEqual(texts(s), ["na ", "na ", "na ", "na ", "fim "]);
  assert.deepEqual(s.phrase_breaks_after_index, [1, 3]);
});

// Edição de notas no estilo de DAW na Revisão: cortar uma nota em duas,
// copiar/recortar/colar e duplicar. Lógica pura, testada em
// test/noteEdit.test.ts. As funções mudam o rascunho que o `mutate` da
// ReviewScreen entrega (um gesto = um Ctrl+Z).
//
// Convenção de texto (a mesma do pipeline e do editor oficial, que grava a
// continuação como "~", TScreenEditSub.DivideNote): a sílaba fica na 1ª
// nota e as seguintes viram "~". O espaço de fim de palavra fica na ÚLTIMA
// nota da palavra, então ele passa para a continuação - `build_song.py`
// faz o inverso ao fundir um "~" ("herda o espaço final").
//
// As quebras de frase são índices de nota ("quebra depois da nota i"), por
// isso toda inserção remapeia `phrase_breaks_after_index`.

export interface NoteLike {
  start_beat: number;
  duration_beats: number;
  text: string;
}

export interface SongLike<T extends NoteLike> {
  notes: T[];
  phrase_breaks_after_index: number[];
}

/** Notas copiadas: `start_beat` relativo à 1ª nota; `breaksAfter` são índices dentro de `notes`. */
export interface NoteClip<T extends NoteLike> {
  notes: T[];
  breaksAfter: number[];
  /** do início da 1ª ao fim da última nota, em beats */
  span: number;
}

function clone<T>(n: T): T {
  return JSON.parse(JSON.stringify(n)) as T;
}

/** Textos das duas partes: a sílaba sem o espaço final, e "~" com o espaço final (se havia). */
export function continuationTexts(text: string): [string, string] {
  const core = text.trimEnd();
  return [core, "~" + text.slice(core.length)];
}

/**
 * Beat inteiro onde cortar a nota perto de `beat`: arredonda e mantém as duas
 * partes com pelo menos 1 beat. `null` quando a nota tem 1 beat só.
 */
export function sliceBeat(note: NoteLike, beat: number): number | null {
  if (note.duration_beats < 2) return null;
  const end = note.start_beat + note.duration_beats;
  return Math.min(end - 1, Math.max(note.start_beat + 1, Math.round(beat)));
}

/** Quebras depois de `idx` ou adiante andam uma casa: a nota nova entra em idx+1. */
function shiftBreaksAfterInsertAt(song: SongLike<NoteLike>, idx: number): void {
  song.phrase_breaks_after_index = song.phrase_breaks_after_index.map((b) => (b >= idx ? b + 1 : b));
}

/**
 * Corta a nota `idx` no beat mais perto de `atBeat`. A 2ª parte vira "~" com
 * o mesmo pitch e tipo, e a quebra de frase que vinha depois da nota passa
 * para depois da 2ª parte. Devolve o índice da 2ª parte, ou `null` se a nota
 * tem 1 beat.
 */
export function splitNote<T extends NoteLike>(song: SongLike<T>, idx: number, atBeat: number): number | null {
  const n = song.notes[idx];
  if (!n) return null;
  const cut = sliceBeat(n, atBeat);
  if (cut === null) return null;
  const [first, second] = continuationTexts(n.text);
  const tail = clone(n);
  tail.start_beat = cut;
  tail.duration_beats = n.start_beat + n.duration_beats - cut;
  tail.text = second;
  n.duration_beats = cut - n.start_beat;
  n.text = first;
  song.notes.splice(idx + 1, 0, tail);
  shiftBreaksAfterInsertAt(song, idx);
  return idx + 1;
}

/**
 * Estende a palavra: uma continuação "~" logo depois da nota (o Ctrl+D de uma
 * nota só), do mesmo tamanho dela mas sem passar do início da nota seguinte -
 * a palavra que se arrasta para onde a próxima começa. Como no corte, a quebra
 * de frase passa para depois da continuação. Devolve o índice dela, ou `null`
 * se a nota seguinte começa colada (não há espaço).
 */
export function extendNote<T extends NoteLike>(song: SongLike<T>, idx: number): number | null {
  const n = song.notes[idx];
  if (!n) return null;
  const at = n.start_beat + n.duration_beats;
  const nextStart = Math.min(
    ...song.notes.filter((x, i) => i !== idx && x.start_beat >= at).map((x) => x.start_beat)
  );
  const room = nextStart - at; // Infinity sem nota depois
  if (room < 1) return null;
  const [first, second] = continuationTexts(n.text);
  const next = clone(n);
  next.start_beat = at;
  next.duration_beats = Math.min(n.duration_beats, room);
  next.text = second;
  n.text = first;
  song.notes.splice(idx + 1, 0, next);
  shiftBreaksAfterInsertAt(song, idx);
  return idx + 1;
}

/** Copia as notas `idxs` (em qualquer ordem, repetidas ignoradas), com as quebras de frase entre elas. */
export function copyNotes<T extends NoteLike>(song: SongLike<T>, idxs: Iterable<number>): NoteClip<T> | null {
  const sorted = [...new Set(idxs)].filter((i) => song.notes[i] !== undefined).sort((a, b) => a - b);
  if (sorted.length === 0) return null;
  const t0 = Math.min(...sorted.map((i) => song.notes[i].start_beat));
  const end = Math.max(...sorted.map((i) => song.notes[i].start_beat + song.notes[i].duration_beats));
  const breaks = new Set(song.phrase_breaks_after_index);
  return {
    notes: sorted.map((i) => {
      const c = clone(song.notes[i]);
      c.start_beat -= t0;
      return c;
    }),
    breaksAfter: sorted.flatMap((i, k) => (breaks.has(i) ? [k] : [])),
    span: end - t0,
  };
}

/**
 * Cola o clip com a 1ª nota em `atBeat`. Cada nota entra antes da primeira
 * nota que começa depois dela (como o "+ Nota"); as notas que já existiam não
 * mudam de ordem. Devolve os índices das notas coladas, em ordem.
 */
export function insertClip<T extends NoteLike>(song: SongLike<T>, clip: NoteClip<T>, atBeat: number): number[] {
  const placed: number[] = [];
  for (const src of clip.notes) {
    const note = clone(src);
    note.start_beat = src.start_beat + atBeat;
    let at = song.notes.findIndex((x) => x.start_beat > note.start_beat);
    if (at === -1) at = song.notes.length;
    // a ordem do clip vale mesmo se uma nota existente se intrometer
    if (placed.length > 0) at = Math.max(at, placed[placed.length - 1] + 1);
    song.notes.splice(at, 0, note);
    // como no "+ Nota": a quebra depois da nota anterior fica onde está, e a
    // nota colada abre a frase seguinte
    song.phrase_breaks_after_index = song.phrase_breaks_after_index.map((b) => (b >= at ? b + 1 : b));
    placed.push(at);
  }
  const breaks = new Set(song.phrase_breaks_after_index);
  for (const k of clip.breaksAfter) breaks.add(placed[k]);
  song.phrase_breaks_after_index = [...breaks].sort((a, b) => a - b);
  return placed;
}

/** Duplica as notas logo depois do fim da seleção (Ctrl+D com várias notas). */
export function duplicateNotes<T extends NoteLike>(song: SongLike<T>, idxs: Iterable<number>): number[] {
  const clip = copyNotes(song, idxs);
  if (!clip) return [];
  const first = Math.min(...[...new Set(idxs)].filter((i) => song.notes[i]).map((i) => song.notes[i].start_beat));
  return insertClip(song, clip, first + clip.span);
}

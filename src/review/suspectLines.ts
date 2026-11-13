// Lógica pura das "linhas suspeitas" da revisão: quais linhas (frases) têm
// ao menos uma nota incerta e qual é a próxima a visitar. Separada do
// ReviewScreen pra ser testável com `npm test`, sem React nem DOM - por isso
// o critério de nota suspeita entra como predicado.

// Faixa de índices de nota de uma linha, inclusiva nas duas pontas.
export interface LineRange {
  start: number;
  end: number;
}

// Linhas delimitadas por `phraseBreaksAfterIndex` (índice da ÚLTIMA nota de
// cada linha, em qualquer ordem). O que sobra depois da última quebra é a
// linha final; quebra repetida, fora da faixa ou na última nota não cria
// linha vazia.
function lineRanges(notesLength: number, phraseBreaksAfterIndex: number[]): LineRange[] {
  const breaks = [...new Set(phraseBreaksAfterIndex)]
    .filter((b) => b >= 0 && b < notesLength - 1)
    .sort((a, b) => a - b);
  const lines: LineRange[] = [];
  let start = 0;
  for (const b of breaks) {
    lines.push({ start, end: b });
    start = b + 1;
  }
  if (start < notesLength) lines.push({ start, end: notesLength - 1 });
  return lines;
}

export function countLines(notesLength: number, phraseBreaksAfterIndex: number[]): number {
  return lineRanges(notesLength, phraseBreaksAfterIndex).length;
}

// Linhas com pelo menos uma nota suspeita, em ordem de posição na música.
export function suspectLines<T>(
  notes: T[],
  phraseBreaksAfterIndex: number[],
  isSuspectNote: (n: T) => boolean
): LineRange[] {
  return lineRanges(notes.length, phraseBreaksAfterIndex).filter((l) =>
    notes.slice(l.start, l.end + 1).some(isSuspectNote)
  );
}

// Índice (em `lines`) da primeira linha suspeita que começa DEPOIS da nota
// `afterNoteIndex`, dando a volta pra primeira no fim. null = não há nenhuma.
export function nextSuspectLine(lines: LineRange[], afterNoteIndex: number): number | null {
  if (lines.length === 0) return null;
  const i = lines.findIndex((l) => l.start > afterNoteIndex);
  return i === -1 ? 0 : i;
}

// Geometria do teclado horizontal da Revisão (PianoKeyboard.tsx). Lógica
// pura, testada em test/pianoLayout.test.ts.
//
// Posições em fração da largura total (0..1): o teclado acompanha a largura
// da tela sem medir pixels. Teclas pretas ficam centradas na divisa entre as
// brancas vizinhas, com 60% da largura de uma branca (proporção de um piano).

const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const BLACK_PCS = new Set([1, 3, 6, 8, 10]);
export const BLACK_KEY_WIDTH = 0.6; // em larguras de tecla branca

export interface PianoKey {
  midi: number;
  /** "C4", "F#3"... - mesma notação do piano lateral (C4 = MIDI 60 = pitch 0 do UltraStar) */
  name: string;
  black: boolean;
  /** borda esquerda, em fração da largura total */
  left: number;
  /** largura, em fração da largura total */
  width: number;
}

export function isBlackKey(midi: number): boolean {
  return BLACK_PCS.has(((midi % 12) + 12) % 12);
}

export function midiName(midi: number): string {
  return `${NOTE_NAMES[((midi % 12) + 12) % 12]}${Math.floor(midi / 12) - 1}`;
}

/**
 * Teclas de `low` a `high` (MIDI, inclusive). As pontas são puxadas para a
 * tecla branca mais próxima por fora, para o teclado nunca começar ou
 * terminar numa preta cortada ao meio.
 */
export function pianoLayout(low: number, high: number): PianoKey[] {
  while (isBlackKey(low)) low--;
  while (isBlackKey(high)) high++;
  let whites = 0;
  for (let m = low; m <= high; m++) if (!isBlackKey(m)) whites++;
  const ww = 1 / whites;
  const keys: PianoKey[] = [];
  let whiteIndex = 0;
  for (let m = low; m <= high; m++) {
    if (isBlackKey(m)) {
      // divisa entre a branca anterior (whiteIndex - 1) e a próxima
      const edge = whiteIndex * ww;
      keys.push({ midi: m, name: midiName(m), black: true, left: edge - (BLACK_KEY_WIDTH * ww) / 2, width: BLACK_KEY_WIDTH * ww });
    } else {
      keys.push({ midi: m, name: midiName(m), black: false, left: whiteIndex * ww, width: ww });
      whiteIndex++;
    }
  }
  return keys;
}

/** Tecla sob a posição `x` (fração 0..1) e `y` (fração 0..1 da altura): pretas têm prioridade na parte de cima. */
export function keyAt(keys: readonly PianoKey[], x: number, y: number, blackHeight = 0.62): PianoKey | null {
  if (y < blackHeight) {
    for (const k of keys) if (k.black && x >= k.left && x < k.left + k.width) return k;
  }
  for (const k of keys) if (!k.black && x >= k.left && x < k.left + k.width) return k;
  return null;
}

// Pure helpers for the Lyric timing table.
//
// Everything here is a plain function - no React, no Tauri - so it can be
// tested from a Node script before shipping. LyricTimingPanel only draws the
// result.
//
// The idea: a LRCLIB .lrc carries ONE time per LINE. The generated package
// carries what the AI actually MEASURED (notes with source anchor/fuzzy/
// realign). Comparing the two line by line points at the lines worth
// listening to - that is what saves the user's time, instead of checking the
// whole song by ear.

export interface LrcLine {
  time: number;
  text: string;
}

/** A verse from the review screen (same shape deriveVerses produces). */
export interface TimingVerse {
  firstNote: number;
  text: string;
  time: number;
}

/** A note from song_data.json - only the fields the table needs. */
export interface TimingNote {
  start_beat: number;
  text: string;
  source?: string | null;
}

export interface TimingRow {
  /** Index of the line inside the .lrc (0-based). */
  lrcIndex: number;
  /** Time the .lrc declares, in seconds. */
  lrcTime: number;
  lrcText: string;
  /** Matching verse in the package, or null when it did not match. */
  verseIndex: number | null;
  /** First MEASURED time in that verse (anchor/fuzzy/realign), or null. */
  heardTime: number | null;
  heardSource: string | null;
  /** heardTime - lrcTime (positive = the AI heard it after the .lrc). */
  gap: number | null;
  /**
   * true when the .lrc and the measurement disagree. NOT the same as "needs
   * your attention": a line you have already ruled on is settled, and the
   * caller filters those out.
   */
  suspect: boolean;
  /**
   * true when this line's FIRST note came from the .lrc rather than from the
   * audio - which is what happens to every line once an approved file is in
   * use. The AI then has no independent opinion of where the line starts, and
   * `heardTime` is the first word it measured INSIDE the line, not a rival
   * reading of the start. Shown so the number is not mistaken for the AI
   * contradicting a time the user set.
   */
  lineStartSeeded: boolean;
}

/**
 * Difference (in seconds) above which a line is flagged for checking.
 * A good .lrc usually agrees with the measurement within ~0.5 s; the wrong
 * lines in Effigy were ~4 s out. 1.5 s separates the two cases with room to
 * spare.
 */
export const SUSPECT_GAP_S = 1.5;

/** Sources that mean a real measurement of the audio - not a guess, not .lrc. */
const MEASURED_SOURCES = new Set(["anchor", "fuzzy", "realign"]);

/** The source a note carries when its time came from the synced lyrics. */
const SEEDED_SOURCE = "lrc";

const LRC_TS_RE = /\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]/g;

/**
 * Parses a .lrc the same way the sidecar's parse_lrc does: metadata lines
 * ([ar:], [ti:], [length:] - the tag there is alphabetic, not a timestamp)
 * and lines with no text are ignored. One line may carry several timestamps
 * (a repeated chorus); each one becomes its own entry.
 */
export function parseLrc(text: string): LrcLine[] {
  const out: LrcLine[] = [];
  for (const raw of text.split(/\r?\n/)) {
    LRC_TS_RE.lastIndex = 0;
    const stamps = [...raw.matchAll(LRC_TS_RE)];
    if (stamps.length === 0) continue;
    const last = stamps[stamps.length - 1];
    const content = raw.slice((last.index ?? 0) + last[0].length).trim();
    if (!content) continue;
    for (const m of stamps) {
      const minutes = parseInt(m[1], 10);
      const seconds = parseInt(m[2], 10);
      const frac = m[3] ? parseFloat(`0.${m[3]}`) : 0;
      out.push({ time: minutes * 60 + seconds + frac, text: content });
    }
  }
  out.sort((a, b) => a.time - b.time);
  return out;
}

/** Same normalisation as the sidecar's _normalize_line. */
export function normalizeLine(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

/**
 * Matches two lists of lines IN ORDER and returns, for each item of `b`, the
 * index of the matching item of `a` (or null).
 *
 * Uses the longest common subsequence over the normalised text and keeps only
 * identical pairs - the same stance as the sidecar's match_lrc_to_lines: a
 * doubtful line is left UNMATCHED rather than matched to the wrong place.
 */
export function matchInOrder(a: string[], b: string[]): (number | null)[] {
  const n = a.length;
  const m = b.length;
  const result: (number | null)[] = new Array(m).fill(null);
  if (n === 0 || m === 0) return result;

  // Textbook LCS: dp[i][j] = length of the longest common subsequence of
  // a[i..] and b[j..]. n and m are the line count of one song (dozens), so
  // the cost does not matter.
  const dp: number[][] = Array.from({ length: n + 1 }, () =>
    new Array<number>(m + 1).fill(0)
  );
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] =
        a[i] === b[j]
          ? dp[i + 1][j + 1] + 1
          : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      result[j] = i;
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      i++;
    } else {
      j++;
    }
  }
  return result;
}

/** Note range [start, end) of each verse. */
function verseRanges(verses: TimingVerse[], noteCount: number): [number, number][] {
  return verses.map((v, i) => [
    v.firstNote,
    i + 1 < verses.length ? verses[i + 1].firstNote : noteCount,
  ]);
}

/**
 * Builds the table rows: each .lrc line next to what the AI measured in the
 * matching verse.
 *
 * Important: verse.time is NOT used as "what the AI heard". When the .lrc
 * seeded the start of that line (source "lrc"), verse.time IS the .lrc time
 * and the comparison would always be zero. Only genuinely measured notes
 * count.
 */
export function buildTimingRows(
  lrcText: string,
  verses: TimingVerse[],
  notes: TimingNote[],
  beatToSec: (beat: number) => number,
  suspectGap: number = SUSPECT_GAP_S
): TimingRow[] {
  const lrcLines = parseLrc(lrcText);
  if (lrcLines.length === 0) return [];

  const matched = matchInOrder(
    verses.map((v) => normalizeLine(v.text)),
    lrcLines.map((l) => normalizeLine(l.text))
  );
  const ranges = verseRanges(verses, notes.length);

  return lrcLines.map((line, k) => {
    const verseIndex = matched[k];
    let heardTime: number | null = null;
    let heardSource: string | null = null;
    let lineStartSeeded = false;
    if (verseIndex !== null && ranges[verseIndex]) {
      const [from, to] = ranges[verseIndex];
      lineStartSeeded = notes[from]?.source === SEEDED_SOURCE;
      for (let n = from; n < to; n++) {
        const note = notes[n];
        if (!note) continue;
        if (note.source && MEASURED_SOURCES.has(note.source)) {
          heardTime = beatToSec(note.start_beat);
          heardSource = note.source;
          break;
        }
      }
    }
    const gap = heardTime === null ? null : heardTime - line.time;
    const suspect =
      verseIndex === null || gap === null || Math.abs(gap) > suspectGap;
    return {
      lrcIndex: k,
      lrcTime: line.time,
      lrcText: line.text,
      verseIndex,
      heardTime,
      heardSource,
      gap,
      suspect,
      lineStartSeeded,
    };
  });
}

/**
 * Reads a time typed by the user. Accepts "34.5", "34,5", "0:34.5", "1:23",
 * "1:23,45". Returns seconds, or null when it cannot be understood.
 */
export function parseTimeInput(raw: string): number | null {
  const s = raw.trim().replace(",", ".");
  if (!s) return null;
  let m = /^(\d{1,3}):([0-5]?\d(?:\.\d{1,3})?)$/.exec(s);
  if (m) {
    return parseInt(m[1], 10) * 60 + parseFloat(m[2]);
  }
  m = /^(\d{1,5}(?:\.\d{1,3})?)$/.exec(s);
  if (m) {
    return parseFloat(m[1]);
  }
  return null;
}

/** Formats seconds as m:ss.d - the same shape the user types. */
export function formatTime(sec: number): string {
  if (!isFinite(sec)) return "-";
  const sign = sec < 0 ? "-" : "";
  const abs = Math.abs(sec);
  const minutes = Math.floor(abs / 60);
  const seconds = abs - minutes * 60;
  const ss = seconds < 10 ? `0${seconds.toFixed(1)}` : seconds.toFixed(1);
  return `${sign}${minutes}:${ss}`;
}

/**
 * True when this .lrc carries the marker USKMaker writes on a set of line
 * times a person checked by ear and approved. The sidecar looks for the same
 * tag (pipeline/align.py, lrc_is_approved) - if you change it here, change it
 * there too.
 */
export function isApprovedLrc(text: string): boolean {
  return /\[uskmapproved:\s*1\s*\]/i.test(text);
}

/**
 * Reads the metadata tags USKMaker writes at the top of an approved .lrc.
 * `audioSeconds` is the length of the recording the times were checked
 * against - if the user later downloads a different version of the track, the
 * approved times no longer describe it, and the panel says so.
 */
export function parseApprovedMeta(text: string): {
  audioSeconds: number | null;
  settled: number[];
} {
  const m = /\[uskmaudio:([0-9]+(?:\.[0-9]+)?)\]/i.exec(text);
  const st = /\[uskmsettled:([0-9,\s]*)\]/i.exec(text);
  const settled = st
    ? st[1]
        .split(",")
        .map((piece) => parseInt(piece.trim(), 10))
        .filter((n) => Number.isInteger(n) && n >= 0)
    : [];
  return { audioSeconds: m ? parseFloat(m[1]) : null, settled };
}

/**
 * Which table rows the user has already ruled on, read back from an approved
 * file. Matched by TEXT, exactly like approvedTimesForRows - the settled marks
 * must travel with their line, not with a row number.
 */
export function approvedSettledForRows(
  approvedText: string,
  rows: TimingRow[]
): Set<number> {
  const out = new Set<number>();
  const { settled } = parseApprovedMeta(approvedText);
  if (settled.length === 0 || rows.length === 0) return out;
  const approved = parseLrc(approvedText);
  if (approved.length === 0) return out;
  const matched = matchInOrder(
    rows.map((r) => normalizeLine(r.lrcText)),
    approved.map((l) => normalizeLine(l.text))
  );
  const settledSet = new Set(settled);
  approved.forEach((_, k) => {
    if (!settledSet.has(k)) return;
    const rowPos = matched[k];
    if (rowPos === null) return;
    out.add(rows[rowPos].lrcIndex);
  });
  return out;
}

/**
 * Maps the lines of an approved .lrc back onto the table rows, so reopening
 * the panel shows the times the user already approved.
 *
 * Matched by TEXT, not by position: the package's .lrc could have been
 * refetched in the meantime, and lining the two up by row number would then
 * silently move every correction onto the wrong line.
 */
export function approvedTimesForRows(
  approvedText: string,
  rows: TimingRow[]
): Record<number, number> {
  const approved = parseLrc(approvedText);
  if (approved.length === 0 || rows.length === 0) return {};
  const matched = matchInOrder(
    rows.map((r) => normalizeLine(r.lrcText)),
    approved.map((l) => normalizeLine(l.text))
  );
  const out: Record<number, number> = {};
  approved.forEach((line, k) => {
    const rowPos = matched[k];
    if (rowPos === null) return;
    out[rows[rowPos].lrcIndex] = line.time;
  });
  return out;
}

/**
 * Formats seconds as m:ss.cc - two decimals, so a time read back from an
 * approved file survives the round trip into the input box without being
 * rounded to a tenth.
 */
export function formatTimeExact(sec: number): string {
  if (!isFinite(sec) || sec < 0) return "0:00.00";
  const cs = Math.round(sec * 100);
  const minutes = Math.floor(cs / 6000);
  const rest = cs % 6000;
  const ss = String(Math.floor(rest / 100)).padStart(2, "0");
  const hundredths = String(rest % 100).padStart(2, "0");
  return `${minutes}:${ss}.${hundredths}`;
}

/** Formats a difference in seconds, always signed ("+2.5"/"-1.0"). */
export function formatGap(gap: number, decimalComma: boolean): string {
  const v = gap.toFixed(1);
  const withSign = gap > 0 ? `+${v}` : v;
  return decimalComma ? withSign.replace(".", ",") : withSign;
}

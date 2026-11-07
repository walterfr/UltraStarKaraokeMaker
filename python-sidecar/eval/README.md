# eval — accuracy harness against gold hand-charted songs

Dev tooling only (nothing here is imported by the app runtime). Ported from
[usdx-autochart](https://github.com/Alejololer/usdx-autochart) (MIT) and
adapted to USKMaker's artifacts and pipeline stages. Discussed on upstream
issue #2.

## What's here

| file | purpose |
|---|---|
| `usdx_parse.py` | UltraStar `.txt` reader (headers, notes, breaks, cp1252 fallback). P1/P2 duet blocks are flattened in time order. Time model: `time_s = GAP/1000 + beat*60/(BPM*4)`. Note lyrics keep their spaces — they mark word boundaries. |
| `evaluate.py` | Time-domain scoring of a generated chart (`.txt` **or** `song_data.json`) against a gold `.txt`: note-count ratio, onset error, relative-pitch contour, lyric similarity. |
| `library_replay.py` | Stage-level replay of USKMaker's own stages against a local gold library: global CTC alignment via `MMS_FA` (`--aligner ctc`, default, with 4b lead-vocal rescue at `> 0.20` and Whisper fallback at `> 0.35`, cached in `align_ctc.json`) or WhisperX (`--aligner whisper`, cached in `align.json`), SwiftF0 pitch inside gold note bounds, and BPM vs gold `#BPM` (mod octave). Resumable, per-song caching, stratified sampling. |
| `ab_align.py` | A/B of aligner variants (`ctc`, `whisper`, `hybrid`, `ctc@lead`, `...~dedup`, `...+snap`) on the **cached stems** of a finished `library_replay` run, printed next to that run's baseline. |
| `seed_set.json` | The 7-song seed set agreed on issue #2, referenced **by name only**. |

## Copyright

Nothing copyrighted lives in the repo. Gold charts and audio are referenced by
library folder name (`Artist - Title/` with audio + gold `.txt`); each dev
supplies their own local library (`--lib`, default `D:\Canciones Karaoke`).

## Usage

```bash
# score one generated song against its gold chart
python eval/evaluate.py "New Output/Song/song_data.json" "D:/Canciones Karaoke/Artist - Title/Artist - Title.txt"

# stage-level replay: stratified sample (lang x words-per-minute tercile)
python eval/library_replay.py --n 20 --seed 0 --aligner ctc

# stage-level replay: curated seed set
python eval/library_replay.py --seed-set eval/seed_set.json --aligner ctc

# rebuild results.csv + summary from existing per-song JSONs
python eval/library_replay.py --n 20 --seed 0 --aggregate-only
```

Run from `python-sidecar/` with its venv. Outputs land in
`python-sidecar/eval_runs/<run>/` (`results/*.json`, `results.csv`,
`cache/<slug>/` with stems/alignment/pitch).

## Reading the numbers

- Gold onsets are themselves ~50 ms-grid quantized and stylistic —
  differences below ~25–50 ms are noise, not signal.
- **Demucs is nondeterministic** (randomized shifts). On repetitive songs the
  same code can score wildly differently on two separation rolls. The replay
  caches stems per song precisely so that A/B comparisons between code
  versions run on **fixed stems** — never compare runs that re-separated.
- `interp_frac` is the pipeline's internal quality signal (`low_confidence_frac`
  on CTC or interpolated word fraction on Whisper); `rescue_tried/won` shows
  when the lead-vocal rescue (`main.py` Etapa 4b) fired and whether it improved
  the internal quality score.
- The replay excludes `[MULTI]` golds so interleaved voices do not poison
  single-track word matching; `evaluate.py` can still score against `[MULTI]`
  by flattening both parts in time order.

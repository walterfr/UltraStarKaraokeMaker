# Changelog

All notable changes to USKMaker. *(Português: [CHANGELOG.md](CHANGELOG.md))*

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/).

Every version has a ready-to-use installer on **[Releases](https://github.com/walterfr/UltraStarKaraokeMaker/releases)** — each release's notes also carry the install instructions.

## [Unreleased]

### Fixed

- **A YouTube link downloaded the whole playlist.** When the link carried `&list=...` (the "Mix"/auto-radio YouTube adds by itself, or an actual playlist), the app downloaded the entire list — you pasted one clip and got a dozen songs. It now downloads only the video you picked.
- **A crash at the alignment step (Step 4) for anyone without ffmpeg on their system PATH.** Generation reached Step 4 and died with a huge error (`WinError 2`, "the system cannot find the file specified"). Cause: the alignment library called `ffmpeg` by name, without using the ffmpeg the app already bundles. The bundled ffmpeg now goes on the process path before alignment — a separate ffmpeg install is no longer needed. (The noisy "torchcodec" warning shown alongside was harmless, not the cause.)

## [0.4.0] — 2026-07-17

### Added

- **Duet mode (two voices).** Tick the **Duet** box and say who sings each part in the lyrics with a tag at the start of the line — `P1:`, `P2:`, or `P1&P2:` when they sing together (a line with no tag stays with the previous singer). The package comes out in the community duet format: `#P1`/`#P2` headers (names taken from the artist, e.g. "Elton John & Kiki Dee"), the body split into two `P1`/`P2` blocks, and a `[DUET]` filename suffix. Both voices are already in the vocal the app isolates — the alignment doesn't change; the tag just says whose each line is. In duet mode, the lead-vocal rescue is skipped (it would drop the second singer).

## [0.3.8] — 2026-07-17

### Added

- **A warning when the app can't make out the lyrics well.** There was a way for a package to come out out-of-sync with no warning at all: when the app "heard" something else and placed the notes with false confidence, in the wrong spots. The previous warning only caught the case where the app *couldn't* place the notes — not the case where it placed them wrongly. Now, when lyric recognition comes out low, the result screen tells you to check the sync (and, if it's off, generate again). Found by measuring 60 songs against hand-made charts.

## [0.3.7] — 2026-07-17

Two note-accuracy improvements, both measured against 1444 hand-made charts.

### Changed

- **Fewer stray tildes (`~`).** The `~` marks a note that holds and changes pitch within the same syllable — but the app was overdoing it: putting `~` on three times as many notes as hand-made charts do. The cause was mistaking a note that *slides* in pitch (common when singing) for an actual note change. The `~` proportion now matches what humans do.

### Fixed

- **A number in the lyrics could send a note to the wrong place.** When the app "heard" a number in the song (e.g. "17") and your lyrics also had it written as a digit, it could pin a note at an invented time with false confidence. That case is now detected and the note is measured correctly. (Writing the number out — "seventeen" — was never affected.)

## [0.3.6] — 2026-07-17

### Fixed

- **If you installed in the last few weeks, you're probably running without your GPU — and don't know it.** Setup downloaded ~2.5 GB of the CUDA build of PyTorch and then, on the very next step, **silently replaced it with a build that has no CUDA**. The result: processing on the CPU (~10 min per song instead of ~2), while the app still showed "✓ GPU". Worse, when it was noticeable at all, the message blamed your **graphics driver** — which never had anything to do with it. **If you have an NVIDIA GPU, re-run "Set up AI environment"** and check the final line: it should say `CUDA disponivel: True`.
  *(The bug appeared on its own, with nobody touching anything: the library we download started serving a version newer than the one the app needs.)*

- **Songs that came out completely out of sync now fix themselves.** Vocal separation varies between attempts, and once in a while a bad one comes out — when it does, the app can't make out the singing and the whole package is wrong. It now detects that and **redoes the separation automatically**, keeping the better result. Costs 1–3 minutes, and only when the first attempt failed.

- **If it still fails, the app says so** instead of delivering silently. Before, a package with 89% guessed notes carried the same discreet notice as one with 5%.

- **Notes past the end of the song.** When the alignment got lost, notes could be written beyond the end of the audio — the game would show notes with nothing to sing.

### Changed

- **`#GAP` rounded to 10 ms** (`1927` → `1930`). The value came from the start of the first detected word, whose real precision is tens of milliseconds — the millisecond there was noise dressed up as exactness. It's the community convention, and 10 ms is well below what the ear notices.

## [0.3.5] — 2026-07-16

### Added

- **Separate vocal and instrumental tracks in the package** (optional). Tick the box and the package also carries the isolated vocal and the backing track, letting the game **control the guide vocal's volume separately from the instrumental** — turn it up to learn a song, off to sing solo. The separation already happened anyway (it's how the app understands the singing); the tracks were simply thrown away at the end. It makes the package almost 3× bigger, so the box starts unticked.

### Fixed

- **Manual BPM is literal again.** In v0.3.4 the value you typed was adjusted along with the automatic one. The field exists for you to override the detection when it gets it wrong — so now exactly what you type is what gets written. If the value falls outside the range that yields the most precise notes, the log just says so, without touching your number.

## [0.3.4] — 2026-07-16

Chart-quality improvements and a bug that broke packages silently. Much of this came from reviewing the neighbouring projects ([UltraSinger](https://github.com/rakuri255/UltraSinger), [UltraStar-Creator](https://github.com/UltraStar-Deluxe/UltraStar-Creator), [usdb_syncer](https://github.com/bohning/usdb_syncer)) and the [official spec](https://github.com/UltraStar-Deluxe/format).

### Fixed

- **A title with `?`, `/` or `:` broke the package.** We sanitized the folder name but not the files inside it, and one ordinary character was enough to break things in three ways: "AC/DC" sent the audio into a different folder (a package with no sound, and no error at all), "Quem?" made generation fail outright, and "Song 2: Live" created a **0-byte** file with the audio hidden in an NTFS stream — silently. Names now follow the same convention USDB uses ("AC/DC" becomes "AC-DC"). Your title and artist stay untouched inside the file and in the cover/year/genre lookups.
- **Much more accurate notes: `#BPM` now uses the fine grid that hand-made charts use.** UltraStar's `#BPM` isn't the song's tempo — it's the unit of the timing grid. We were writing the real tempo, which made the grid too coarse: **59% of notes were stuck at the minimum duration**, because their real length simply didn't fit. Note lengths now reflect what's actually sung, and the per-note timing error dropped by half.
- **Numbers in the lyrics ("20", "1985") got the wrong note.** Nobody sings "two-zero", they sing "twenty" — and the aligner doesn't understand digits. The number's note came out up to 6× too short and too early. It now follows what's actually sung, while your lyrics keep the number as you wrote it.

### Added

- **`#AUDIO` tag** in the package, alongside `#MP3` and pointing at the same file. It's where the format is heading: the spec already tells players to prefer `#AUDIO` when present, and the next format version makes it the required one. Writing both serves new and old players.

### Note

- The AI environment gained one new library (for spelling numbers out). If you **don't** re-run **Set up AI environment**, everything keeps working — you just won't get the number fix.

## [0.3.3] — 2026-07-16

### Changed

- **Git is no longer required to install.** `whisperx` (the alignment library) was the only dependency installed straight from its GitHub repo (`git+https://...`), and it alone forced **Set up AI environment** to require Git on the machine. Without it, setup died halfway and generation later failed with *"the sidecar exited unexpectedly"* and no log at all. It now comes from PyPI, pinned (`whisperx==3.8.7rc1`) — which also makes installs reproducible, since `git+` tracked the repo's latest commit, a moving target. It's the exact same version as before: the PyPI package was verified to be the same code file-by-file, and confirmed with a full end-to-end generation. Generated packages are unchanged.

## [0.3.2] — 2026-07-16

### Fixed

- **The app reported "environment OK" when it wasn't.** If the AI-environment setup failed halfway, the app still showed the green ✓ and hid the setup button; generation then failed with *"the sidecar exited unexpectedly"* and **no log** (the process died before creating it). The app now actually probes the libraries and reports which ones are missing.
- **Setup now fails loudly** when something goes wrong, instead of ending with a success message.

### Added

- **Automatic golden notes** (`*`) on sustained parts, like hand-made charts (~5% of notes, a ratio calibrated by measuring community charts). Packages previously had none.
- **Octave consistency** for pitch — fixes isolated notes where the detector picked the wrong octave.

### Changed

- **Much more precise timing** — syllable splits follow the actual voice (instead of dividing time evenly), with real **melisma (`~`)** on sustained syllables and sturdier alignment anchors. Contributed by [@Alejololer](https://github.com/Alejololer).
- **Lead-vocal rescue** — when backing vocals break the alignment, the app isolates the lead vocal and retries, accepting the result only if it improves. Contributed by [@Alejololer](https://github.com/Alejololer).
- The review screen now also flags notes measured with **low confidence**, not just estimated ones.
- New `eval/` module: a quality evaluation harness (time-domain scoring). Contributed by [@Alejololer](https://github.com/Alejololer).

## [0.3.1] — 2026-07-15

### Fixed

- **Setup wouldn't start on some machines** — the "Set up AI environment" button failed with a path error (`Join-Path ... the argument "drive" is null`) on Windows PowerShell 5.1.
- **Crash on accents/emoji** — titles or tags with special characters (CJK, emoji) took down processing on Windows. Everything is UTF-8 now.

### Added

- **Auto-fills title and artist** from the audio file's tags (only fields you haven't filled in).
- **`#BACKGROUND` image** in the package: a real 16:9 background via [fanart.tv](https://fanart.tv/get-an-api-key/) (optional, with `FANARTTV_API_KEY`); without the key it reuses the cover, so every package with a cover gets a background.
- **Automatic BPM correction** — fixes the common half/double error in detected tempo.
- **"Keep only the essentials" checkbox** — at the end of the queue, deletes the auxiliary files (`.lrc`/`.log`/`.json`) from each folder (optional; removes that package's review screen).
- A discreet project support link on the About page.

### Changed

- **Title/artist fields moved above the lyric search** — the search depends on them.

## [0.3.0] — 2026-07-12

### Added

- **One-button AI environment setup.** "Set up AI environment" downloads `uv` (which installs Python 3.12 for you if missing), a **bundled ffmpeg** (with libvorbis) and the AI libraries, with live progress in the app. No more installing Python by hand, putting ffmpeg on PATH, or running `setup-sidecar.ps1` (still available as an alternative).

## [0.2.2] — 2026-07-12

### Fixed

- **Machines without an NVIDIA GPU** (e.g. Intel Iris Xe) crashed with `AssertionError: Torch not compiled with CUDA enabled`, even though the UI showed CPU mode. The app now detects the absence of CUDA and runs everything on the CPU automatically.

## [0.2.1] — 2026-07-12

Fixes from community feedback, validated against the [official format spec](https://github.com/UltraStar-Deluxe/format/blob/main/The%20UltraStar%20File%20Format%20(v1).md).

### Fixed

- **Tilde (`~`) on syllables** — a `~` was prefixed to every continuation syllable, and the game displayed the literal tilde on screen ("Ju~rei").
- **GAP / first note** — the first note now starts at beat 0 and the real vocal lead-in moves to the `#GAP` tag, so re-syncing to a different audio source is just a GAP tweak.
- **Translated error messages** — errors coming from the Rust core now follow the UI language.

## [0.2.0] — 2026-07-12

### Added

- **Song queue + warm models** — a persistent Python sidecar keeps the AI models loaded between songs; from the 2nd song on, alignment is much faster.
- **Lyric fetching (LRCLIB)** by artist + title. When a synced version exists, each line's timing feeds the alignment as anchors.
- **Bilingual PT/EN interface**, detecting the system language.
- **Organized output** into an `Artist - Title` subfolder (the UltraStar collection convention).
- Splash screen, About page and a crisp taskbar icon.

### Changed

- **UX rework** — environment check on startup, real-time lyric validation, a step list with status and duration, real cancellation, and a result view with cover, metadata and a measured-vs-estimated note count.

## [0.1.0] — 2026-07-09

First public release: the complete pipeline (synced lyrics, pitch, BPM, metadata, video), a Windows installer and assisted AI-environment setup.

[0.4.0]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.4.0
[0.3.8]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.8
[0.3.7]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.7
[0.3.6]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.6
[0.3.5]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.5
[0.3.4]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.4
[0.3.3]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.3
[0.3.2]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.2
[0.3.1]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.1
[0.3.0]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.0
[0.2.2]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.2.2
[0.2.1]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.2.1
[0.2.0]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.2.0
[0.1.0]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.1.0

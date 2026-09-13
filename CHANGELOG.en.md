# Changelog

All notable changes to USKMaker. *(Português: [CHANGELOG.md](CHANGELOG.md))*

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/).

Every version has a ready-to-use installer on **[Releases](https://github.com/walterfr/UltraStarKaraokeMaker/releases)** — each release's notes also carry the install instructions.

## [Unreleased]

### Added

- **Karaoke video export (.mp4).** A new option renders a karaoke video from the finished package: the lyrics on screen with each syllable filling in time with the music, over the cover or a background image. Also adds a GitHub Actions workflow that builds the Windows installer, so a change can be tested without a full Rust + Node + Python toolchain on the tester's machine.
- **Rebuild the video after correcting the alignment, without reprocessing the song.** The review screen saved the corrected timings and rewrote the `.txt`, but left the `.mp4` on the OLD timings with nothing to say so. Applying a half-second nudge meant running Demucs and WhisperX again - minutes of AI work to redo a step that needs no AI at all. Everything the video needs is already in the folder after a generation, so it now re-renders from `song_data.json` in seconds. Also available as `scripts/rebuild-karaoke-video.ps1`.
- **"Fetch info" reads artist, title and duration from a YouTube link**, before generating, so the fields can be checked rather than typed. The song's real length now also decides WHICH set of synced lyrics to use, instead of trusting LRCLIB's best guess. Adds `update_ytdlp.py`, which keeps yt-dlp current on its own - it ages fast, and a stale copy is the usual reason a download suddenly starts failing.
- **A capable graphics card now gets the bigger recognition model.** "auto" reads the available VRAM and picks `large-v3` when there is room (6 GB or more), staying on `medium` otherwise. Better accuracy for anyone with a good GPU without asking for it, and no risk of running a modest card out of memory - a fix must not make things worse for anyone who was already working.
- **Synced lyrics are now found automatically when the first lookup comes back without them.** LRCLIB's "best guess" endpoint returns a single record, which sometimes carries no synced lyrics at all; the app now falls back to a proper search and picks a result whose duration matches the song.
- **"Update AI tools" button in the app header.** Updating the AI libraries previously meant finding and re-running `setup-sidecar.ps1` by hand. The button reuses the same setup command (the script is idempotent), streams the live progress log, and only appears once the environment is healthy — while the environment is incomplete, the original "Set up AI environment" button still covers it. It is disabled while a song is being generated.

- **Check the lyric timings by ear, and approve them as the master.** LRCLIB's synced lyrics are a stranger's guess: they may belong to another recording, and a single line inside an otherwise correct file can simply be wrong - proven on the user's own "Ministry - Effigy (Im Not An)", where lines 1-3 and 7-34 were right while lines 4-6 sat about four seconds late, so no global offset could have repaired it. The review screen now has a **Lyric timing** table: every line of the package's `.lrc` beside the time the AI actually MEASURED for that line, with the disagreements flagged - so the lines worth listening to are pointed at instead of hunted for. On Effigy it flagged exactly the three lines the user had already found by ear, out of 34. Each time plays from a second before its line, and the same button stops playback. Corrected times are written with **Save as approved** to `%LOCALAPPDATA%\USKMaker\approved-lyrics`, outside the song folder on purpose: deleting or regenerating a song must not throw away work someone did with their ears. Reopening the table fills them back in, matched by the line's TEXT rather than its position, so a refetched `.lrc` cannot shift corrections onto the wrong lines. The file also records the length of the audio it was checked against, and warns when a different recording is loaded later.
- **An approved lyric file overrules everything else in the pipeline.** From then on "Search lyrics" uses the approved version without consulting LRCLIB, the pre-generate warning about lyrics not fitting the audio is skipped, and the sidecar recognises the approval marker and stands down: no duration check, no recognition floor, the approved line starts entering as fixed anchors over whatever Whisper heard. Every defence in `align.py` exists because a third party's guess might be about another recording; a line start a person checked against THIS recording is not a guess, and doubting it would trade a human measurement for a heuristic. Because each line's start and the next line's start are then both fixed, the realignment pass can only search between them - it can no longer drop a phrase nine seconds from where it is sung, which is exactly what it did before. Measured on the user's Effigy after approving: all 34 line starts theirs, and one word in 349 still a guess.
- **"Generate again" sends a finished song back to the main form.** The form is cleared after a generation, so re-running one song meant finding the YouTube link again and retyping the name - the first thing anyone needs after approving corrected lyric timings. A button on the review screen now fills the form back in. The link is deliberately not stored anywhere, but yt-dlp prints it into the process log, which stays in the package folder, so it is recovered from there; when it cannot be (the source was a local file, or the helper files were cleaned) the name is filled in and the message says to paste the link.

- **Keep the backing vocals and harmonies in the karaoke track.** Demucs strips every voice out of the instrumental, harmonies included - and in a lot of music, the 80s synth-pop this gets used for especially, the vocal arrangement is half of what makes the song sound like itself. The app already downloads a second model that tells a LEAD voice from backing voices, but it was only used to help the aligner, and the backing stem it produced was thrown away. A new **Keep the backing vocals** option keeps that stem and mixes it back into the instrumental, so only the lead voice is removed. Tried on a real song before any of it was built: the harmonies came back with no trace of the lead singer, and at their natural level rather than pushed back. Opt-in, because it costs one extra separation pass, and it needs Backtrack switched on - that is the option that makes the instrumental the package's audio. Non-fatal throughout: if the second separation fails for any reason, the package comes out with the ordinary instrumental and says so. The mix passes `normalize=0` deliberately - ffmpeg's mixer divides every input by the number of inputs by default, which would have quietly turned every song down about 6 dB; checked by mixing in a SILENT stem and measuring the result at exactly the original level. User request.

### Fixed

- **Synced lyrics were chosen by a metadata field that LRCLIB often gets wrong, then thrown away later.** The app picked a record by comparing its declared `duration` against the song, but that field is contributor-supplied and can simply be false. Real case (2026-09-06, "Peter Murphy - Cuts You Up"): record 19409675 declares 254.8 s — matching the recording almost exactly — while carrying lyrics that run to 5:12. The sidecar then correctly refused them (`lrc_duration_mismatch`) and alignment fell back to the AI alone; the result put 17 lines of lyrics into eight seconds and left a 63-second hole in the middle of the song. Candidates are now judged by the timestamps INSIDE the file — the last line that actually has words — using the same rule and the same margins as the sidecar, and one that fits the recording is preferred over one whose metadata merely looks right. The timings in the file cannot lie; the number printed beside it can.
- **You only found out that the lyrics did not fit after three minutes of processing.** The check that rejects them lived solely in the sidecar, so it ran during alignment — long after there was anything useful to do about it. The same check now also runs when you press Generate, naming both times ("the synced lyrics run to 5:07, but this recording is 4:14") and letting you stop and pick different lyrics. The sidecar check stays exactly as it was, as the final net.
- **Lyrics ran about three seconds early in the karaoke video, on every line, all the way through.** In the ASS subtitle format karaoke durations are relative to when the line APPEARS, not to the music's clock. Because each line appears early to give you time to read it, the whole fill started early by exactly that lead-in - a constant offset on every line. Fixed with the idiomatic empty `{\k}` pause, which consumes the reading time without painting anything. The `.txt` for the game was correct all along; only the video was wrong.
- **RTX 50-series cards downloaded 2.5 GB of CUDA and then ran on the CPU anyway.** Blackwell (sm_120) only gained kernels in CUDA 12.8, and the setup installed a fixed cu126 build. The pipeline correctly fell back to the CPU rather than crashing, so nothing looked broken - it was just inexplicably slow. The setup now reads the card's real compute capability from `nvidia-smi` and picks cu128 for 12.0 and above, leaving every older card on exactly the path it had before.
- **Words ran together in the video - "missyou", "beenlonelysince", "Oh,and".** By the package format's convention the space separating two words is attached to the LAST note of that word, and that note can be a melisma continuation whose text is a tilde plus a space. Dropping the continuation note took the space with it. The tilde itself is pitch notation and is never displayed; the space beside it is real text.
- **A failed YouTube download showed the raw command line instead of the reason.** yt-dlp writes the real cause on an `ERROR:` line buried among dozens of others, and the user was handed a `CalledProcessError` containing the entire command while "HTTP Error 403: Forbidden" sat hidden in the output. The actual message is now extracted and turned into something actionable - including that a 403 is usually temporary and worth retrying.
- **The setup could stop dead for anyone whose Windows account name is two words.** The torch-protection step hands uv a constraints file kept in `%TEMP%`, and uv splits the value of `--constraints` on whitespace — so `C:\Users\John Smith\AppData\Local\Temp\...` reached it as `C:\Users\John` and the run ended with "File not found", taking the whole setup with it. Measured on 2026-09-05: `-c`, `--constraints`, `--constraints=VALUE` and the `UV_CONSTRAINT` environment variable all split the value; only `-r` survives a path containing a space. The setup now passes the path's 8.3 short name (`C:\Users\JOHNSM~1\...`), which never contains a space. Where 8.3 names are disabled on the volume it skips the update entirely instead of guessing — the same safe fallback already used when the installed torch version cannot be read, on the principle that being out of date beats losing the GPU, and both beat a setup that dies.
- **torchcodec could never load, on any machine.** It ships with torch 2.8 and is what torchaudio and pyannote reach for when decoding audio, but it needs FFmpeg's *shared* libraries — and the bundled ffmpeg is a single self-contained executable with none beside it. Every run failed on all four FFmpeg versions it tries and left a noisy warning in the log. Two things were needed. The setup now installs the seven FFmpeg 7.1.1 shared libraries next to the bundled ffmpeg (version 7 deliberately: torchcodec 0.7.0 ships loaders for FFmpeg 4-7 only, and even 0.10.0 stops at 8, so a "latest" FFmpeg 9 build is unusable). And the sidecar now registers that folder with `os.add_dll_directory`, because since Python 3.8 Windows does not search the PATH for a DLL's dependencies and torchcodec only learned to handle that itself in 0.10.0 — so the libraries could sit in the right folder and still be invisible. Seven files, not six: `avfilter-10` pulls in `postproc-58`, which the "or one of its dependencies" error never names. Harmless while the older decoders still exist; it stops being harmless when whisperx moves to torch 2.9+ and they are removed.
- **Re-running the setup never actually updated anything.** Dependencies are declared with a floor (`>=`), and `uv pip install` without `--upgrade` only checks that what is already installed satisfies the request, then stops — so re-running the setup printed "Audited N packages" and left the user frozen on the versions from the day they first installed, forever, with no warning that the command they ran to "update" does not update. The setup now upgrades, but freezes the installed torch into a constraints file first: `--upgrade` on its own would let whisperx's `torch~=2.8.0` accept a future CPU-only 2.8.1 from PyPI and silently cost the user their GPU — the same failure as the RTX 5080 report. If the installed versions cannot be read, nothing is updated: the previous behaviour is the safe fallback.
- **The torch install message always said "CUDA cu126", even when installing cu128.** The label was hard-coded and never looked at the index actually chosen a few lines earlier, which made the RTX 50 fix look as though it had not taken effect. The label is now derived from the chosen index, so the message and the download cannot disagree.

- **"Fetch info" cut the closing bracket off any song title that ended with one.** The title cleaner strips leftover punctuation from both ends, and its list of characters included brackets - so `Ministry - Effigy (Im Not An)` reached the form as `Effigy (Im Not An`, and went on into the LRCLIB query, the folder name and the generated `.txt`. A bracket at either end is now dropped only when it has no partner in the title, which is what a leftover shell actually looks like; `(Official Video)` and `[HD]` are still stripped as before. The test meant to cover this ("Until Death (Us Do Part)") only checked that the middle survived, so it passed green throughout - it now compares the whole string, and twelve cases were added around it: with the old code nine of them fail. Reported by the user. Also adds the British spelling "Visualiser" to the noise list.

- **The alignment validation warnings came out in Portuguese with the app set to English.** "Sobreposição entre nota 240 (fim=3024)..." - the sentence was built inside `rust-core`, a crate that has no notion of the interface language and should not have one. It now reports overlaps as data (which notes, at which beats) and the app writes the sentence in the language in use, so the Portuguese wording is byte-for-byte what it always was and English speakers finally get English. Reported by the user.

- **Approving a song's timings did not stop the table flagging those same lines.** Five corrections typed, saved and used - and the next package flagged four of the same rows. The times were applied correctly; the table was reading them wrong. "AI heard at" is meant to be the AI's own reading of where a line starts, but once an approved time is in use the AI is TOLD where the line starts, so it has no reading of its own - and the column quietly fell through to the NEXT word in the line. On the user's "Nick Heyward - Tell Me Why (Extended Remix)", 63 of the 65 line starts came from the approved file, so almost every row could report a difference that was never a disagreement: "Blue eyes" showed "+2.5" because that is where the AI measured the word *eyes*, 2.5 s after the start the user had set. Two other rows could never clear at all - the .lrc has 65 lines and the chart 63, because the bracketed backing-vocal lines never make it into the lyrics, so they read "no match" on every future run. A line the user has ruled on - a time typed, or listened to and ticked as already right - is now settled and stops being flagged, and the settled marks travel inside the approved file, matched by the line's text rather than its row number. The difference is still shown, and now says when a line's start came from the approved file rather than from the audio, because a long gap there can still mean the start is early. Reported by the user.

- **Generating the same song a second time into the same folder died, once the helper files were being kept.** "Failed to generate the package: Command '[...ffmpeg.exe, -y, -i, ...video.wav, -vn, ...video.wav]'" - the same path as input and output, which ffmpeg refuses outright ("cannot edit existing files in-place"). The video download saves its file as `video.<ext>` and then extracts the audio beside it as `video.wav`. On a second run yt-dlp finds the video already downloaded and leaves it untouched, so `video.wav` - written by the PREVIOUS run - is the newest `video.*` in the folder, and was chosen as the video to extract audio from. It only bites when intermediate files are kept, which is why it stayed hidden until the new "Generate again" button made re-running a song into the same folder an ordinary thing to do. The `.wav` is now left out of the candidates: it is the file the app writes, not one yt-dlp produced. Reported by the user.

### Changed

- **The "recognition was low" alarm stopped crying wolf.** That warning counts only what Whisper recognised on its own, so it cannot see the realignment pass or the synced lyrics — a limitation the code already noted ("the realignment saves it, but word-recall doesn't know that"). Measured on 2026-09-06 across three of the user's own songs, all with near-identical recognition: Peter Murphy 55% with the `.lrc` REJECTED gave 38% guessed words; Killing Joke 53% with the `.lrc` accepted gave **0%**; Ministry 59% with the `.lrc` accepted gave **0.3%**. The recognition figure barely predicted quality — whether the synced lyrics fit the recording predicted all of it — yet all three got the same red alarm. When the `.lrc` was accepted, actually seeded line starts, and under 5% of words ended up estimated, the message is now a calm note saying so. The red warning is unchanged everywhere else, which is the point: a warning that fires on good packages teaches people to ignore it, and then it is worth nothing on the broken one.
- **When recognition is poor, the synced lyrics now outrank the AI at line starts.** Below 60% measured recall - the share of the lyric WhisperX actually recognised, counted before any realignment - a `.lrc` stops merely filling gaps and takes charge of where lines begin. Above that floor the measured anchors still win, because when recognition is good they are more accurate than any external file.
- **`scripts/setup-sidecar.ps1` is now written in English** (comments and on-screen messages), and its historical notes use unambiguous `YYYY-MM-DD` dates. No code changed — verified by comparing the parsed token stream of both versions.

## [0.20.0] — 2026-08-12

### Added

- **Configurable output audio format (OGG/MP3) and a max resolution cap for the downloaded video.** Previously every package's audio was always OGG, and the video (when included) downloaded at the best available resolution, uncapped (could come in at 4K). You can now choose MP3 — applied to every audio file the package generates (main audio, separated stems, and YARG export) — and cap the video resolution, with **1080p as the new default** (anyone who doesn't touch the setting now downloads a lighter video; audio format still defaults to OGG). User request.
- **Rap/GoldenRap note types in the review screen**, distinct from Freestyle (square corners in the visualization to tell them apart). **"+ Note" button (shortcut `N`)** to manually create a note at the time-marker position, keeping notes chronologically ordered. **Playable piano roll sidebar**, synced with the selected note — a handy pitch reference while reviewing. **Fixed:** moving/resizing notes with the keyboard (arrows/Shift+arrows) while a group was multi-selected only affected one note — it now moves the whole group, matching how dragging already worked. Contributed by [@mur1nu](https://github.com/mur1nu) ([PR #14](https://github.com/walterfr/UltraStarKaraokeMaker/pull/14)).

## [0.19.0] — 2026-08-08

### Added

- **Bulk change note type (Normal/Golden/Freestyle) for the selected group.** Previously only doable note by note. Contributed by [@angelrdgzrivero](https://github.com/angelrdgzrivero) ([PR #13](https://github.com/walterfr/UltraStarKaraokeMaker/pull/13)).

## [0.18.5] — 2026-08-05

### Fixed

- **A detected-but-incompatible GPU stalled the pipeline instead of falling back to CPU.** `resolve_device` only checked whether an NVIDIA GPU with a driver was present (`torch.cuda.is_available()`), not whether the installed torch build actually had compiled KERNELS for it. Older cards (e.g. GTX 750 Ti, Maxwell architecture) passed that check and only failed later, inside Demucs, with "CUDA error: no kernel image is available for execution on the device" — no fallback, no clear warning. The GPU's real capability is now compared against the kernels torch actually ships before picking CUDA; if it doesn't match, it falls back to CPU (slower, but it works) with a log warning. User report (Vitor).

## [0.18.4] — 2026-08-04

### Fixed

- **YouTube download could silently pick up the audio/video from a DIFFERENT song.** `download_from_youtube` picked "the most recently modified `.wav`" in the working folder — if that folder already had any other `.wav` (from an earlier test, for instance), the heuristic could return the wrong file, with no error at all. Real-world result (user report): one song's lyrics aligned against a completely different song's audio, alignment collapsing (0 exact anchors, 61% interpolated). Same pattern fixed in the video download path. The downloaded filename is now fixed (`audio.wav`/`video.*`), removing the ambiguity entirely.

## [0.18.3] — 2026-07-31

### Fixed

- **AI environment setup was failing for everyone since v0.18.0.** `requirements.txt` required `korean-romanizer>=1.4` — a version that never existed (the real package hasn't even reached 1.0; the latest is 0.28.0). Pin corrected. User report (Sethid777).

## [0.18.2] — 2026-07-31

### Fixed

- **Setup didn't test pitch extraction (`swift_f0`), only surfacing the crash when actually generating.** `swift_f0` imports `onnxruntime` just like the lead-vocal-rescue (audio-separator), but without try/except protection — if its onnxruntime fails to load (common cause: missing Microsoft Visual C++ Redistributable), the whole sidecar dies on import, generating nothing. Setup validated other essential libraries but not this one, so it reported "all good" and the user only discovered the problem mid-generation (reported by a real user). `swift_f0` is now also validated during setup, with the same VC++ Redistributable hint if it fails.

## [0.18.1] — 2026-07-31

### Fixed

- **Sidecar diagnostic log could silently disappear.** The Python server's session log was written inside the app's install folder — under the default `perMachine` installer (Program Files), that folder is read-only for regular users, so the write failed and the error was swallowed, falling back to `/dev/null`. If the sidecar died before opening the job's own log (e.g. a crash on torch/CUDA import, a real case with an old GPU), no log survived at all, for the user or for us. This log now lives in `%LOCALAPPDATA%\USKMaker\`, always writable.

## [0.18.0] — 2026-07-31

### Added

- **Extended romanization to Chinese, Korean, Russian, Ukrainian, Hindi, and Greek.** The "Romanize" option (previously Japanese/Hepburn only) now covers more languages, each using its standard system: Chinese → Pinyin with tone marks, Korean → Revised Romanization, Russian/Ukrainian → Cyrillic-to-Latin transliteration, Hindi → IAST, Greek → generic transliteration. The checkbox only appears for languages with an available converter. User request.

## [0.17.0] — 2026-07-30

### Added

- **Visual warning for isolated pitch jumps in the review screen.** In layered productions (e.g. a backing harmony a fifth above the lead vocal), the pitch-recognition AI can sometimes lock onto the wrong voice for an isolated note — confidently, without giving itself away. With no cheap way to auto-correct this without reprocessing the whole song, the review screen now flags these notes (same visual highlight and "jump to next" button already used for other suspicious notes), for a quick manual fix.

## [0.16.0] — 2026-07-30

### Added

- **Paste synced lyrics (.lrc) manually.** The automatic search (LRCLIB) doesn't find everything — under-indexed genres (e.g. EBM, industrial, darkwave) often come up empty. You can now paste the contents of an `.lrc` file found manually on the site; the app extracts the lyrics and uses the line timestamps as alignment anchors, same as the automatic search. User request.
- **New automatic rescue: more sensitive voice detection (VAD).** When alignment comes out poorly, the app now also tries to unlock recognition of quiet/atmospheric vocals (common in soundtracks and certain electronic styles) that the default voice detector simply doesn't register as singing. It only kicks in when the result is already poor, and only keeps the change if it actually helps — measured on 51 third-party songs from the test library to make sure it doesn't hurt songs that already work well. User report (issue #9).

## [0.15.0] — 2026-07-30

### Fixed

- **Synced lyrics (LRCLIB) from the wrong recording are now detected and ignored.** The app searches for synced lyrics by artist/title only, without confirming duration — LRCLIB is a crowdsourced database and can return someone else's live version, remix, or extended edit. Measured on the test library: 66% of the synced lyrics found had a duration inconsistent with the downloaded audio. Now, before using it, the app checks whether the duration matches; if it doesn't, the synced lyrics are ignored (alignment proceeds normally with just the AI) instead of risking wrong note placement.
- **Confusing "no language specified" log removed.** In some cases the log showed a warning that no language had been set, even when the user had picked one on screen — the chosen language was always correctly used for transcription, only the warning was wrong. User report (issue #9).

## [0.14.0] — 2026-07-30

### Added

- **Multi-select notes in the review screen.** `Shift+click` toggles a note in/out of the selected group; `Shift+drag` on the piano roll background opens a selection rectangle that adds the notes inside it to the group. Dragging any note in the group moves the **whole block** (same time and pitch shift applied to all), with a single undo for the gesture. `Del` with a group selected removes all of them at once. Fixes the case where a whole section of the song comes out shifted from automatic alignment and needs a bulk correction instead of adjusting note by note. User request (issue #11).

## [0.13.0] — 2026-07-29

### Fixed

- **The low-confidence alignment warning is now much more visible.** When the app recognizes little of the lyrics in a song (e.g. heavily processed/electronic vocals), the package still comes out, but with a real risk of being out of sync — and the warning about that was small text, easy to miss on an otherwise "success" screen. It's now a proper banner (background and border), matching the rest of the app's style. Found from a real user report (electronic music with processed vocals, only 18% of the lyrics recognized).

## [0.12.0] — 2026-07-26

### Added

- **Romanize (romaji).** New option under **Options**, for Japanese songs: rewrites the package lyrics in **romaji** (Latin alphabet, Hepburn), so people who can't read kana/kanji can sing along. Alignment still runs on the original Japanese — only the final text becomes romaji. For lyrics that are already Latin, nothing changes.

### Fixed

- **The AI environment install no longer fails because of the optional vocal-rescue component.** Before, if `audio-separator` (a 2nd separation pass that improves vocals on some songs) failed to import — common when the Microsoft Visual C++ Redistributable is missing — the setup rejected the **whole** environment and the app wouldn't open, even with everything essential working. That component is now treated as **optional**: the setup only warns, and the app works normally (the pipeline uses the Demucs separation). To re-enable the rescue, install the VC++ Redistributable and run the setup again.
- **The GPU indicator now tells the truth.** Before, the app showed "✓ GPU" whenever an NVIDIA card was present — even when PyTorch had fallen back to CPU and generation would run slow. It now checks whether PyTorch actually sees CUDA and, when it doesn't, shows a clear warning ("⚠ GPU … — torch without CUDA, running on CPU") instead of a false positive.

## [0.11.0] — 2026-07-25

### Added

- **Export for YARG.** New option under **Options**: alongside the UltraStar package, the app assembles a **"(YARG)"** subfolder ready for [YARG](https://yarg.in). YARG reads the UltraStar `.txt` format natively — so there's no format conversion, just packaging into the layout it expects: `notes.txt` (the same chart), `song.ini` (metadata), and the audio files `song.ogg` (instrumental) and `vocals.ogg` (isolated vocal), built from the separation the app already does. Cover (`album.jpg`) and video are included when present. Respects the chosen transpose. Reuses everything the pipeline already produces, at no meaningful extra processing cost.

## [0.10.0] — 2026-07-24

### Added

- **Key change (transpose).** New **Transpose (semitones)** field next to BPM, from −6 to +6. The package comes out in a different key from the original: the app shifts the **audio** (tempo preserved) **and the notes** together, by the same number of semitones — everything stays in sync in the new key. Handy to share or play outside the game already in the right key, or in players without live transpose. Large steps (beyond ±4) degrade the audio; combined with Backtrack, the separation residue becomes more audible. The key is per-song: it resets to the original on each new generation.

## [0.9.0] — 2026-07-23

### Added

- **Backtrack mode (instrumental only).** In the options, tick **Backtrack** and the package audio comes out **without the guide vocal** — just the instrumental, to sing over (real karaoke). It uses the vocal separation the app already does during generation, so it costs no extra time. Quality is that of the separation: some vocal residue may remain here and there. Alignment and notes are unchanged — only the packaged audio.

## [0.8.0] — 2026-07-23

### Added

- **A "Generate again" button.** On the result screen, generates the same song again without retyping anything. Handy when the vocal separation comes out bad on one attempt — it varies each run, and the next one usually improves.
- **The result screen now explains when to use "Review".** Many people didn't realize Review fixes a broken section **without generating again** — so tweaking the lyrics and regenerating kept ruining parts that were already good. A hint on the button now makes it clear: to fix specific bits, use Review (adjusts the notes without re-separating the vocal); regenerating is for when the whole separation came out bad.

## [0.7.1] — 2026-07-22

### Fixed

- **Downloading cover/background/video in review always failed** with "asset download failed". The part that fetches the files mixed warning messages into the response the app reads, corrupting it — it had nothing to do with your AI environment. Fixed; the download works.

## [0.7.0] — 2026-07-22

### Added

- **A notification when a song (or the queue) finishes.** If you left USKMaker generating and walked away, Windows tells you when it's done — `✓ Done: Artist - Title`, or a queue summary. It only shows when the app window is **not** focused (if you're watching the screen, it stays quiet).
- **Review suggests downloading the missing cover, background and video.** When you pick a package to review, the app analyzes the folder and shows what's missing — with a button to **download at once** whatever it lacks (cover via MusicBrainz, background via fanart.tv, clip via YouTube). It also works with **packages not generated here**: in that case the app reads the `.txt` to get artist/title and what already exists. *(Editing the notes remains only for packages generated by USKMaker.)*

## [0.6.0] — 2026-07-20

### Added

- **41 song languages, no longer just 3.** The "Song language" selector offered only Portuguese, English and Spanish — anyone with a song in Croatian, Korean, German, Japanese, etc. had no option (forcing English gave poor results). It now lists all 41 languages the app can align word-by-word. For non-Latin-script languages (Korean, Japanese, Russian, Arabic…), type the lyrics in the native script (한국어, not romanized) — a hint shows when you pick one. *(The engine already supported them all; the screen was just missing the option.)*

## [0.5.1] — 2026-07-19

### Fixed

- **Some songs failed to generate with the error `cannot access local variable 'pct'`.** It happened precisely with the songs the app aligned **perfectly** (no guessed words) — clean recordings. A programming mistake crashed the app right after alignment, while assembling the quality warnings. Fixed; those songs generate normally now. (Bug present since v0.3.8.)

## [0.5.0] — 2026-07-18

### Fixed

- **When "Set up AI environment" failed, it hid the reason.** The screen showed only `Traceback (most recent call last):` and stopped there — without saying which library failed or what the error was, leaving "run it again" as the only option. The cause was in the script itself: on Windows PowerShell, the first line of Python's error became a fatal failure and the rest of the diagnosis was thrown away. Now each library is tested separately and, when one fails, setup says **which** one and shows the **end of the traceback** (where the real error lives). As a bonus, a mere warning (like the "torchcodec" one) no longer fails a library that loaded fine.

### Changed

- **New interface: the window is now a two-column workspace that no longer scrolls.** The song and lyrics are on the left (the lyrics now fill all the available height); the package (language, BPM, folder and options) sits in cards on the right. The **Generate** button is always visible in a fixed bottom bar — you no longer scroll the whole page to reach it. While generating, the right column shows only the progress; when done, only the result. On narrow windows the columns stack automatically. Options now use short labels with the explanation in a tooltip, so each fits on one line.

## [0.4.1] — 2026-07-17

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

[0.9.0]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.9.0
[0.8.0]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.8.0
[0.7.1]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.7.1
[0.7.0]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.7.0
[0.6.0]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.6.0
[0.5.1]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.5.1
[0.5.0]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.5.0
[0.4.1]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.4.1
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

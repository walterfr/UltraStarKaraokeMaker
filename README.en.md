# USKMaker — UltraStar Karaoke Maker

**🇧🇷 [Versão em português](README.md)**

**UltraStar** karaoke package maker from a YouTube link or a local audio file, with automatic lyric syncing, pitch extraction, BPM detection and metadata (cover, year, genre).

What sets it apart from tools like UltraSinger is that USKMaker starts from the **lyrics the user already provides**. The problem becomes *forced alignment* (aligning known lyrics to the audio) rather than transcription from scratch — which yields far more accurate syncing, especially in Portuguese.

All processing is **local**: no paid APIs, and your audio is never sent to external services. The only network calls are to free, open databases (MusicBrainz/Cover Art Archive, iTunes, Deezer and — optionally, with a personal token — Discogs) to enrich metadata, plus the YouTube download when requested.

## How it works

The pipeline has six steps:

1. **Get audio** — downloads from YouTube (via `yt-dlp`) or normalizes a local file to WAV. Optionally downloads the video too, for an animated background in game.
2. **Vocal separation** — isolates vocals and instrumental with Demucs (`htdemucs`).
3. **BPM detection** — estimates the tempo with librosa.
4. **Lyrics-to-audio alignment** — in four passes: WhisperX freely transcribes the audio and measures real acoustic timestamps; the transcription is matched against the provided lyrics (`difflib.SequenceMatcher`), producing *exact anchors*; words Whisper spelled differently are recovered by *fuzzy anchors* (character similarity with monotonic pairing); stretches still without an anchor go through a *second forced alignment* (wav2vec2) restricted to the audio window between neighboring anchors, using the missing text; whatever remains is interpolated with weights proportional to syllable count. When the lyrics come synced from **LRCLIB** (`.lrc`), each line's start time is added as an extra anchor in the gaps Whisper didn't measure, shortening interpolation.
5. **Metadata** — fetches cover, year and genre in a cascade, each source filling only what is still missing: tags embedded in the file → MusicBrainz + Cover Art Archive → iTunes (600x600 cover, year and genre) → Deezer (1000px cover) → Last.fm (cover and genre; optional: set `LASTFM_API_KEY` with a [free key](https://www.last.fm/api/account/create)) → Discogs (optional: set `DISCOGS_TOKEN` with a [free personal token](https://www.discogs.com/settings/developers)). Optional sources are skipped when the corresponding variable is not set.
6. **Assembly** — extracts per-syllable pitch (SwiftF0), splits syllables (pyphen) and builds the UltraStar `.txt` file, with audio converted to `.ogg`.

## Stack

- **Interface**: Tauri v1 + React 18 + TypeScript + Vite — bilingual (PT-BR/EN, detects the system language and can be switched anytime from the header)
- **Format-writing core**: Rust (`rust-core`, crate `uskmaker_core`)
- **AI pipeline**: Python (sidecar), with WhisperX, Demucs, librosa, SwiftF0, pyphen
- **Architecture**: the frontend calls Rust (Tauri), which invokes the Python sidecar; Python exports an intermediate JSON (`song_data.json`) and Rust is the one that writes the final `.txt` from it.

## Requirements

- **Python 3.12** (tested with 3.12.10)
- **NVIDIA GPU with CUDA** — developed and tested on an RTX 4060 (8 GB VRAM). It runs on CPU, but vocal separation and alignment get much slower.
- **Node.js** and **Rust** (stable toolchain), for the Tauri part.
- **ffmpeg** with `libvorbis` support (to produce `.ogg`). With the installer (Option A) it is **downloaded automatically** by `setup-sidecar.ps1`; in development mode, have it on your PATH.

## Installation

### Option A — Installer (recommended for regular use)

1. Download the installer (`USKMaker_x.y.z_x64-setup.exe`) from the [Releases](https://github.com/walterfr/UltraStarKaraokeMaker/releases) page and install it normally.
2. Open USKMaker and click **"Set up AI environment"**. It downloads Python 3.12 (via `uv`), a bundled ffmpeg (with libvorbis) and the AI libraries automatically, with a live progress bar (≈ 10–15 min the first time, ~2 GB, requires internet).
3. That's it. On the first song, the AI models are downloaded automatically (~2 GB, first time only).

Requirements: Windows 10/11 and (optional but highly recommended) an NVIDIA GPU — without one, processing runs on CPU, ~10 min per song. **Python and ffmpeg don't need to be installed by hand** — the button handles it.

> **Advanced users (manual setup):** the button is optional. You can set up the environment yourself in two ways: (a) run the `setup-sidecar.ps1` script from the install folder directly (right-click → "Run with PowerShell" — same as the button, from the terminal); or (b) build everything by hand with your own Python, as in **Option B** below (create the venv at `%LOCALAPPDATA%\USKMaker\venv`). The app also honors an `ffmpeg` already on your PATH and a venv you created manually.

### Option B — Development environment

#### 1. Python sidecar

```powershell
cd python-sidecar
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install torch torchaudio torchvision --index-url https://download.pytorch.org/whl/cu126
pip install -r requirements.txt
python -c "import torch; print('CUDA:', torch.cuda.is_available())"
```

If `CUDA` returns `False`, review your driver/CUDA version before continuing (the pipeline was designed to run on GPU).

> **Note:** WhisperX downloads models on first run and may ask for a Hugging Face token. Set it via the `HF_TOKEN` environment variable or through `huggingface-cli` login. **Never** put the token in the code.

#### 2. Tauri app

```powershell
npm install
npm run tauri dev
```

## Usage

1. Choose the source: YouTube link or local audio file. In local-file mode, you can optionally download a YouTube music video **just for the background** (`#VIDEO`) — the package audio remains your file (great for CD-ripped collections, with better quality than YouTube). Provide the video link or leave it blank for an automatic search by artist + title; if no video is found, the package ships with the cover only.
2. Paste the lyrics — **one line per sung phrase**. Write repeated choruses out in full, as many times as they are sung (don't use "(2x)"); otherwise the repetitions get no notes. Or click **Search lyrics (LRCLIB)** to fill them automatically by artist + title (a free, open database); when a synced version exists, the line timings also help the alignment.
3. Fill in title, artist and language. BPM is optional (detected automatically if left blank).
4. Choose the output folder and generate — the package is created in an `Artist - Title` subfolder (the UltraStar collection convention; point it at the game's `Songs` folder and you're done). To process several songs at once, use **+ Add to queue** and then **Generate queue**: they run one after another without reopening the app, with the AI models already loaded (from the second song on, alignment is much faster).

The resulting package contains the UltraStar `.txt`, the `.ogg` audio, the `[CO].jpg` cover (when found) and, if requested, the `.mp4` video. It can be loaded in UltraStar Deluxe or UltraStar Play.

5. (Optional) Click **Review alignment** at the end — or "Review an existing package..." on the home screen — to open the review editor: listen to the song (full mix or isolated vocals, if intermediates were kept), drag notes in time/pitch, adjust durations, syllables and phrase breaks, shift the global GAP and save to regenerate the `.txt`.

## Project status

Fully functional end to end through the GUI. All scoped milestones are complete:

- **Python pipeline** — playable package generation validated with real songs.
- **Rust core** — `.txt` writing with output identical to the Python prototype, covered by tests.
- **Tauri + UI integration** — complete flow through the interface: environment check on startup (AI/ffmpeg/GPU), real-time lyric validation (catches "(2x)", "[Chorus]", .lrc timestamps before burning GPU time), step list with state and typical duration, a cancel button that kills the process tree, collapsed technical log and a result with cover, metadata and per-confidence note counts. Preferences and window state persist across sessions.
- **Metadata and video** — automatic cover/year/genre (local and network sources) and optional YouTube video in the package.
- **Distribution** — NSIS installer + assisted AI environment setup (`setup-sidecar.ps1`).
- **Manual review** — integrated Yass-style editor: waveform timeline, playback (mix or vocals only), note editing by drag/keyboard, phrase breaks, global GAP and undo/redo; saving rewrites `song_data.json` and regenerates the `.txt` through the Rust core.

## Support the project

USKMaker is free and open source. If it helped you, consider supporting development — every bit helps keep the project maintained and improving:

- ❤️ [GitHub Sponsors](https://github.com/sponsors/walterfr)
- ☕ [Ko-fi](https://ko-fi.com/walterfr)
- ☕ [Buy Me a Coffee](https://buymeacoffee.com/walterfr)

### Pix (Brazil)

Brazilian users can scan the QR code in their bank app, or use the **copy-and-paste** key below:

<img src="docs/pix-qr.png" alt="Pix QR Code" width="200" />

```
00020101021126400014br.gov.bcb.pix0118walterfr@gmail.com5204000053039865802BR5915WALTER REBOUCAS6009FORTALEZA62070503***63045603
```

## License

MIT. See the [LICENSE](LICENSE) file.

## Credits

Built on top of: [WhisperX](https://github.com/m-bain/whisperx), [Demucs](https://github.com/facebookresearch/demucs), [librosa](https://librosa.org/), [SwiftF0](https://github.com/lars76/swift-f0), [yt-dlp](https://github.com/yt-dlp/yt-dlp), [Tauri](https://tauri.app/), [MusicBrainz](https://musicbrainz.org/), [Cover Art Archive](https://coverartarchive.org/), [iTunes Search API](https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/), [Deezer API](https://developers.deezer.com/api), [Last.fm](https://www.last.fm/api) and [Discogs](https://www.discogs.com/developers). Flow inspiration: [UltraSinger](https://github.com/rakuri255/UltraSinger).

---

Made with ♥ in Fortaleza-CE, Brazil by [@prof.walterfr](https://www.instagram.com/prof.walterfr)

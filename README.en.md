# USKMaker — UltraStar Karaoke Maker

[![Release](https://img.shields.io/github/v/release/walterfr/UltraStarKaraokeMaker?color=blue)](https://github.com/walterfr/UltraStarKaraokeMaker/releases)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-brightgreen)](https://github.com/walterfr/UltraStarKaraokeMaker/releases)
[![WinGet](https://img.shields.io/badge/winget-walterfr.USKMaker-blue)](https://github.com/microsoft/winget-pkgs/tree/master/manifests/w/walterfr/USKMaker)
[![Build Windows](https://github.com/walterfr/UltraStarKaraokeMaker/actions/workflows/build-windows.yml/badge.svg)](https://github.com/walterfr/UltraStarKaraokeMaker/actions/workflows/build-windows.yml)
[![Build Linux](https://github.com/walterfr/UltraStarKaraokeMaker/actions/workflows/build-linux.yml/badge.svg)](https://github.com/walterfr/UltraStarKaraokeMaker/actions/workflows/build-linux.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**🇧🇷 [Versão em português](README.md)**

**UltraStar** karaoke package maker from a YouTube link or a local audio file, with automatic lyric syncing, pitch extraction, BPM detection and metadata (cover, year, genre).

What sets it apart from tools like UltraSinger is that USKMaker starts from the **lyrics the user already provides**. The problem becomes *forced alignment* (aligning known lyrics to the audio) rather than transcription from scratch — which yields far more accurate syncing, especially in Portuguese.

All processing is **local**: no paid APIs, and your audio is never sent to external services. The only network calls are to free, open databases (MusicBrainz/Cover Art Archive, iTunes, Deezer and — optionally, with a personal token — Discogs) to enrich metadata, plus the YouTube download when requested.

## How it works

The pipeline has six steps:

1. **Get audio** — downloads from YouTube (via `yt-dlp`) or normalizes a local file to WAV. Optionally downloads the video too, for an animated background in game.
2. **Vocal separation** — isolates vocals and instrumental with Demucs (`htdemucs`).
3. **BPM detection** — estimates the tempo with librosa.
4. **Lyrics-to-audio alignment** — direct global acoustic alignment (CTC / MMS / wav2vec2): the entire provided lyrics are aligned against the vocal track in a single fast pass, guaranteeing lyric order in seconds (with dedicated acoustic models per language, such as Swedish wav2vec2). Lines with lower confidence are flagged for review, and the classic WhisperX transcription + acoustic/fuzzy anchor alignment automatically acts as a fallback when overall confidence is low. When lyrics come synced from **LRCLIB** (`.lrc`) or an approved file, line start timings serve as fixed anchors. Non-Latin alphabets automatically keep WhisperX alignment.
5. **Metadata** — fetches cover, year and genre in a cascade, each source filling only what is still missing: tags embedded in the file → MusicBrainz + Cover Art Archive (prioritizing original studio albums over compilations) → iTunes (600x600 cover, year and genre) → Deezer (1000px cover) → Last.fm (cover and genre; optional: set `LASTFM_API_KEY` with a [free key](https://www.last.fm/api/account/create)) → Discogs (optional: set `DISCOGS_TOKEN` with a [free personal token](https://www.discogs.com/settings/developers)). Optional sources are skipped when the corresponding variable is not set. For the **background image** (`#BACKGROUND`, 16:9): if `FANARTTV_API_KEY` is set (free personal key at [fanart.tv](https://fanart.tv/get-an-api-key/)), it fetches a real *artist background*; without a key or artwork, the background reuses the cover as `[BG].jpg` — so every package with a cover gets a `#BACKGROUND`.
6. **Assembly** — extracts per-syllable pitch (SwiftF0 in optimized window slices), splits syllables with language-specific rules (Portuguese, English, Swedish via pyphen), places syllables exactly where phonemes are sung, calibrates held notes to follow voice duration, automatically marks the longest notes as **golden** (`*`, scoring bonus, ~5% of notes — a pattern calibrated on hand-made charts) and builds the UltraStar `.txt` file, with audio converted to `.ogg` or `.mp3`.

## Stack

- **Interface**: Tauri v2 + React 18 + TypeScript + Vite — bilingual (PT-BR/EN, detects the system language and can be switched anytime from the header)
- **Format-writing core**: Rust (`rust-core`, crate `uskmaker_core`)
- **AI pipeline**: Python (sidecar), with WhisperX, Demucs, librosa, SwiftF0, pyphen
- **Architecture**: the frontend calls Rust (Tauri), which invokes the Python sidecar; Python exports an intermediate JSON (`song_data.json`) and Rust is the one that writes the final `.txt` from it.

## Requirements

- **Python 3.12** (tested with 3.12.10)
- **NVIDIA GPU with CUDA** — developed and tested on an RTX 4060 (8 GB VRAM). On Linux, AMD GPUs work too, through ROCm (tested on an RX 7800 XT). It runs on CPU, but vocal separation and alignment get much slower.
- **Node.js** and **Rust** (stable toolchain), for the Tauri part.
- **ffmpeg** with `libvorbis` support (to produce `.ogg`). With the Windows installer (Option A) it is **downloaded automatically** by `setup-sidecar.ps1`; on Linux it comes from your distribution (the `.deb`/`.rpm` install it); in development mode, have it on your PATH.

## Installation

### Option A (Windows) — WinGet or Installer (recommended for regular use)

Install directly from your terminal using **Windows Package Manager (WinGet)**:

```powershell
winget install walterfr.USKMaker
```

Or download the installer manually:

1. Download the installer (`USKMaker_x.y.z_x64-setup.exe`) from the [Releases](https://github.com/walterfr/UltraStarKaraokeMaker/releases) page and install it normally.
2. Open USKMaker and click **"Set up AI environment"**. It downloads Python 3.12 (via `uv`), a bundled ffmpeg (with libvorbis) and the AI libraries automatically, with a live progress bar (≈ 10–15 min the first time, ~2 GB, requires internet).
3. That's it. On the first song, the AI models are downloaded automatically (~2 GB, first time only).

Requirements: Windows 10/11 and (optional but highly recommended) an NVIDIA GPU — without one, processing runs on CPU, ~10 min per song. **Python and ffmpeg don't need to be installed by hand** — the button handles it.

> **Advanced users (manual setup):** the button is optional. You can set up the environment yourself in two ways: (a) run the `setup-sidecar.ps1` script from the install folder directly (right-click → "Run with PowerShell" — same as the button, from the terminal); or (b) build everything by hand with your own Python, as in **Option B** below (create the venv at `%LOCALAPPDATA%\USKMaker\venv`). The app also honors an `ffmpeg` already on your PATH and a venv you created manually.

### Option A (Linux) — .deb, .rpm or AppImage

1. Download the package for your distribution from the [Releases](https://github.com/walterfr/UltraStarKaraokeMaker/releases) page:
   - **Debian / Ubuntu / Mint:** `sudo apt install ./USKMaker_x.y.z_amd64.deb`
   - **Fedora / openSUSE:** `sudo dnf install ./USKMaker-x.y.z-1.x86_64.rpm`
   - **Any distribution:** the `.AppImage` — `chmod +x USKMaker_x.y.z_amd64.AppImage` and run it.
2. Install a C compiler and ffmpeg if you don't have them (the `.deb`/`.rpm` already pull in ffmpeg). The compiler builds one of the AI libraries during setup.
   - Fedora: `sudo dnf install gcc ffmpeg-free` (Fedora's own `ffmpeg-free` is enough — it has libvorbis)
   - Debian/Ubuntu: `sudo apt install build-essential ffmpeg`
   - Arch: `sudo pacman -S base-devel ffmpeg`
3. Open USKMaker and click **"Set up AI environment"**, as on Windows. It runs `setup-sidecar.sh`, which downloads Python 3.12 (via `uv`) and the AI libraries into `~/.local/share/USKMaker` — nothing is installed system-wide and it never asks for `sudo`. It picks the PyTorch build for your GPU: CUDA on NVIDIA, ROCm on AMD (needs `/dev/kfd`, i.e. the amdgpu driver), CPU otherwise.

The script checks for the compiler and ffmpeg first and tells you the install command for your distribution if one is missing. To run it from a terminal instead of the button: `bash /usr/lib/USKMaker/_up_/scripts/setup-sidecar.sh` (`.deb`/`.rpm`), or `bash scripts/setup-sidecar.sh` from the repository.

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

On Linux the steps are the same, with `python3.12 -m venv venv` and `source venv/bin/activate`; pick the PyTorch index for your GPU — `cu126` for NVIDIA, `rocm6.4` for AMD, `cpu` without a GPU.

#### 2. Tauri app

```powershell
npm install
npm run tauri dev
```

## Usage

1. Choose the source: YouTube link or local audio file. In local-file mode, you can optionally download a YouTube music video **just for the background** (`#VIDEO`) — the package audio remains your file (great for CD-ripped collections, with better quality than YouTube). Provide the video link or leave it blank for an automatic search by artist + title; if no video is found, the package ships with the cover only.
2. Fill in **title, artist and language** (the app checks the lyrics offline and warns if the language seems different from the one selected, with a 1-click button to switch; in local-file mode, title and artist are **auto-filled from the file's tags** — only fields you haven't typed yet; double-check before generating). BPM is optional (detected automatically if left blank; the detector fixes the common "half/double" tempo error).
3. Paste the lyrics — **one line per sung phrase**. Write repeated choruses out in full, as many times as they are sung (don't use "(2x)"); otherwise the repetitions get no notes. Or click **Search lyrics (LRCLIB)** to fill them automatically from the title + artist entered above (a free, open database); when a synced version exists, the line timings also help the alignment.
   - **Duet:** tick **Duet (two voices)** and, in the lyrics, start each singer's lines with a tag — `P1:`, `P2:`, or `P1&P2:` (when they sing together). A line with no tag stays with the previous singer. The package comes out in the community duet format: `#P1`/`#P2` headers (names derived from the artist, e.g. "Elton John & Kiki Dee"), a body split into two `P1`/`P2` blocks, and a `[DUET]` filename suffix.
4. Customize options as needed:
   - **Audio format:** choose between **OGG** (default) and **MP3**.
   - **Video resolution:** cap the downloaded video (defaults to **1080p** to avoid oversized 4K downloads).
   - **Keep backing vocals:** isolates and mutes only the lead singer, keeping background harmonies in the instrumental track (requires *Backtrack* enabled).
   - **YouTube cookies:** for restricted videos that prompt for sign-in ("Sign in to confirm you're not a bot"), enable the option and select your browser.
5. Choose the output folder and generate — the package is created in an `Artist - Title` subfolder (the UltraStar collection convention; point it at the game's `Songs` folder and you're done). To process several songs at once, use **+ Add to queue** and then **Generate queue**: they run one after another without reopening the app, with the AI models already loaded (from the second song on, alignment is much faster). Check **"Keep only the essentials"** to have the helper files (`.lrc`, `.log`, `.json`) deleted from each folder at the end of the queue — the package stays lean, but **without the review screen** (the `song_data.json` it reads is removed).

The resulting package contains the UltraStar `.txt`, the `.ogg`/`.mp3` audio, the `[CO].jpg` cover (when found) and, if requested, the `.mp4` video. It can be loaded in UltraStar Deluxe, UltraStar Play, or Vocaluxe.

   **Karaoke video (optional):** tick **Make karaoke video (.mp4)** to also get an `Artist - Title (Karaoke).mp4` — the lyrics filling in syllable by syllable over the background, on exactly the timing the alignment already measured. It plays on any TV, phone or USB stick, with no game installed. The background is the package video when there is one, otherwise the background art or the cover; the audio is whatever the package uses, so **Backtrack** (instrumental) and transpose carry over automatically. Rendering happens last and is non-fatal: if it fails, the UltraStar package is still complete. The subtitle file it renders from is left in the folder as `_karaoke_subs.ass`, so the look can be tweaked and re-rendered in seconds from the review screen without running the AI again.

6. (Optional) Click **Review alignment** at the end — or "Review an existing package..." on the home screen — to open the integrated review editor:
   - Listen to the song (full mix or vocals only).
   - Drag notes across time and pitch, split syllables, adjust phrase breaks and shift global GAP.
   - Handy pitch reference via the interactive **piano roll** and bulk note-type changes (Normal, Golden, Freestyle, Rap).
   - **🎤 Sing along:** turn on your microphone (shortcut `M`) to draw your live vocal pitch over the notes in real time.
   - Safe saving: edits are never lost on error, and generating again keeps automatic `.bak` backups.

## Project status

Fully functional end to end through the GUI. All scoped milestones are complete:

- **Python pipeline** — playable package generation validated with real songs.
- **Rust core** — `.txt` writing with output identical to the Python prototype, covered by tests.
- **Tauri + UI integration** — complete flow through the interface: environment check on startup (AI/ffmpeg/GPU), real-time lyric validation (catches "(2x)", "[Chorus]", .lrc timestamps before burning GPU time), step list with state and typical duration, a cancel button that kills the process tree, collapsed technical log and a result with cover, metadata and per-confidence note counts. Preferences and window state persist across sessions.
- **Metadata and video** — title/artist auto-filled from the file's tags; automatic cover/year/genre (local and network sources); `#BACKGROUND` image (optional fanart.tv, with cover fallback) and optional YouTube video in the package.
- **Distribution** — NSIS installer on Windows, `.deb`/`.rpm`/AppImage on Linux, plus assisted AI environment setup (`setup-sidecar.ps1` / `setup-sidecar.sh`).
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

## Version history

What changed in each version is in the [CHANGELOG](CHANGELOG.en.md). Installers live on [Releases](https://github.com/walterfr/UltraStarKaraokeMaker/releases).

## License

MIT. See the [LICENSE](LICENSE) file.

## Credits

Built on top of: [WhisperX](https://github.com/m-bain/whisperx), [Demucs](https://github.com/facebookresearch/demucs), [librosa](https://librosa.org/), [SwiftF0](https://github.com/lars76/swift-f0), [yt-dlp](https://github.com/yt-dlp/yt-dlp), [Tauri](https://tauri.app/), [MusicBrainz](https://musicbrainz.org/), [Cover Art Archive](https://coverartarchive.org/), [iTunes Search API](https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/), [Deezer API](https://developers.deezer.com/api), [Last.fm](https://www.last.fm/api) and [Discogs](https://www.discogs.com/developers). Flow inspiration: [UltraSinger](https://github.com/rakuri255/UltraSinger).

---

Made with ♥ in Fortaleza-CE, Brazil by [@prof.walterfr](https://www.instagram.com/prof.walterfr)

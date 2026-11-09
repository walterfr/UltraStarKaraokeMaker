# Privacy Policy for USKMaker

**Last updated:** November 9, 2026

**USKMaker** ("we", "our", or "the application") is a free, open-source desktop application designed to create UltraStar-compatible karaoke packages with AI-assisted lyrics alignment, pitch detection, and beat tracking.

We are committed to protecting your privacy. This Privacy Policy explains how information is handled when you use the application.

---

## 1. Information We Do Not Collect

- **No Personal Data:** USKMaker does not require registration, user accounts, names, email addresses, or phone numbers.
- **No Telemetry or Tracking:** The application does not collect analytics, telemetry, crash dumps, or usage tracking data.
- **No Microphone Audio Recording:** When using the real-time sing-along feature ("Cantar junto"), your microphone input is processed purely in-memory in real time to estimate fundamental frequency (pitch). No voice recordings or audio streams are ever saved to disk or transmitted over the internet.

---

## 2. Local Processing & On-Device Operations

- All audio processing (vocal isolation, silence trimming, pitch extraction, alignment, and video rendering) runs **locally on your computer**.
- Model weights (e.g., Torch, Demucs, WhisperX, CTC models) downloaded by the environment are stored locally in your operating system's application directory (`%LOCALAPPDATA%\USKMaker` on Windows or `~/.local/share/USKMaker` on Linux).

---

## 3. Third-Party Network Services (User-Initiated)

The application makes outbound network requests only when explicitly directed by user actions:
- **Audio/Video Download (yt-dlp):** If you provide a YouTube URL, media is fetched directly from YouTube servers to your computer. YouTube's privacy policy applies to those interactions.
- **Lyrics Search (LRCLIB, NetEase):** If you click "Search lyrics", requests containing song title and artist name are sent to public lyrics databases to retrieve text and timestamps.
- **Metadata & Cover Art (MusicBrainz, Cover Art Archive, Fanart.tv):** Song titles and artist names are queried against public metadata databases to fetch release year, genre, and album artwork.
- **Hugging Face Model Downloads:** On first run for specific acoustic models, weights are downloaded directly from Hugging Face repositories.
- **Application Updates:** The application checks the official GitHub repository (`github.com/walterfr/UltraStarKaraokeMaker`) for new releases.

None of these requests transmit personal information, device identifiers, or tracking IDs.

---

## 4. Open Source Transparency

USKMaker is open-source software distributed under the MIT License. The complete source code is publicly inspectable and verifiable at:
[https://github.com/walterfr/UltraStarKaraokeMaker](https://github.com/walterfr/UltraStarKaraokeMaker)

---

## 5. Children's Privacy

USKMaker does not collect any personal data from anyone, including children under the age of 13.

---

## 6. Contact

If you have any questions or feedback regarding this Privacy Policy, please open an issue or reach out via:
- **GitHub:** [https://github.com/walterfr/UltraStarKaraokeMaker/issues](https://github.com/walterfr/UltraStarKaraokeMaker/issues)
- **Developer:** Walter Rebouças (walterfr@gmail.com)

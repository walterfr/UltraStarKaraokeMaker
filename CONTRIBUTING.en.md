# Contributing to USKMaker

*(Português: [CONTRIBUTING.md](CONTRIBUTING.md))*

Thanks for your interest! This document explains how to propose changes,
report issues, and what to expect from the review process.

## Before you start

- **Bugs and ideas go in [Issues](https://github.com/walterfr/UltraStarKaraokeMaker/issues).**
  For a bug, include: what you expected, what happened, and if possible the
  `pipeline_debug.log` from the package's output folder.
- **Large changes or anything that shifts the project's scope**, open an
  issue before coding — avoids rework if the direction doesn't fit the
  project.
- **Project scope:** USKMaker starts from the **lyrics the user already
  has** and aligns AI to them (forced alignment). It **does not transcribe
  the song from scratch** — that's the deliberate differentiator (other
  tools already do that). PRs that would change this core premise should
  discuss the reasoning in an issue first.

## Development environment

See **[README.en.md](README.en.md)**, section "Option B — Development
environment", to set up the Python sidecar and the Tauri app locally.

Repository layout:

| Folder | What |
|---|---|
| `python-sidecar/` | AI pipeline (WhisperX, Demucs, SwiftF0, librosa) |
| `src-tauri/` | Rust/Tauri backend (orchestrates the sidecar, UI commands) |
| `rust-core/` | `uskmaker-core` crate — shared logic (UltraStar `.txt` writer) |
| `src/` | React/TypeScript frontend |
| `eval/` | Evaluation harness against a gold library (`library_replay.py`) |
| `scripts/` | `setup-sidecar.ps1` — sets up the end user's AI environment |

## Running tests

**Python** (`python-sidecar/tests/`): standalone `assert`-based scripts, no
framework (pytest, etc.) — deliberately, to keep the test as simple as the
code it checks. Each file runs on its own:

```bash
cd python-sidecar
python tests/test_build_song_logic.py
python tests/test_align_logic.py
# ... (one per file in tests/)
```

**Rust:**

```bash
cd src-tauri && cargo test
cd rust-core && cargo test
```

No test hits the network or needs a GPU — it's all pure logic (parsing,
formatting, business rules). If your change has non-trivial logic (a
branch, a parser, a rule), include a test in the same style.

## Commit style

The project uses **[Conventional Commits](https://www.conventionalcommits.org/)**
with its own convention: **type in English, description in Portuguese**
(the maintainer and most current contributors are Brazilian).

```
feat(pipeline): mudança de tom (transposição do pacote)
fix(review): download de assets falhava - stdout poluido por avisos
chore(release): v0.9.0
docs: atualiza instruções de instalação
```

Common types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`. The scope
in parentheses is optional but helps (`pipeline`, `review`, `ui`, `export`).

## Pull Requests

1. Branch off `main`.
2. Relevant tests passing (Python + Rust, depending on what you touched).
3. If the change is **user-visible** (feature, behavior fix): update
   **both `CHANGELOG.md` and `CHANGELOG.en.md`**, in the same `[Unreleased]`
   or upcoming version section — both files must say the same thing in both
   languages.
4. Small, focused PRs are easier to review than one PR mixing unrelated
   features.
5. Describe the *why* of the change, not just the *what* — the diff already
   shows the what.

## Security

- **Never** commit tokens/keys (`HF_TOKEN`, `DISCOGS_TOKEN`,
  `LASTFM_API_KEY`, `FANARTTV_API_KEY`, or any other). Always environment
  variables.
- If you find a vulnerability, please report it privately to the maintainer
  before opening a public issue.

## License

By contributing, you agree that your contribution will be licensed under
the project's [MIT License](LICENSE).

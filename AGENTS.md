# AGENTS.md - Diretrizes do Projeto USKMaker

## Regras Críticas de Release e CI (Importante)

- **Cota do GitHub Actions esgotada**: NUNCA depender de GitHub Actions para builds, CI ou releases.
- **Triggers automáticos desativados**: Os workflows em `.github/workflows/` (`build-windows.yml`, `build-linux.yml`, `winget.yml`) têm triggers `push` e `pull_request` comentados para evitar falhas de cota.
- **Releases sempre locais**: Todos os lançamentos devem ser compilados na máquina local e enviados diretamente ao GitHub Releases via GitHub CLI (`gh`).
- **Comando de Release**:
  ```powershell
  npm run release
  # ou com parâmetros específicos:
  powershell -ExecutionPolicy Bypass -File scripts/release.ps1 -Version 0.24.1 [-SkipTests] [-Draft] [-Prerelease]
  ```
  O script executa os testes, compila o instalador NSIS via `npm run tauri build`, gera checksums SHA256, extrai o changelog correspondente de `CHANGELOG.md` e publica no GitHub via `gh release`.

## Convenções de Formato UltraStar

- **Tag #CREATOR (Issue #35)**:
  - Os arquivos `.txt` gerados pelo USKMaker DEVEM incluir a versão do app no cabeçalho `#CREATOR`:
    `#CREATOR:USKMaker v<versao>` (ex.: `#CREATOR:USKMaker v0.24.1`).
  - Tanto a exportação direta do pipeline (`src-tauri/src/main.rs`), a tela de revisão/salvamento (`save_song`) quanto o sidecar Python mantêm e gravam este formato.

## Comandos do Projeto

### Frontend (React + Vite + TypeScript)
- `npm run dev`: Inicia dev server do Vite.
- `npm run build`: Compila TypeScript e bundle Vite (`tsc && vite build`).
- `npm test`: Roda testes do frontend (`test/**/*.test.ts`).

### Desktop / Tauri (Rust)
- `npm run tauri dev`: Inicia aplicação em modo desenvolvimento.
- `npm run tauri build`: Compila instalador de produção (NSIS no Windows).
- `cargo test --manifest-path rust-core/Cargo.toml`: Executa testes unitários do núcleo em Rust (`uskmaker-core`).
- `cargo check --manifest-path src-tauri/Cargo.toml`: Valida compilação do app Tauri.

### Sidecar Python (IA / Demucs / WhisperX / Pitch)
- `python-sidecar\venv\Scripts\pytest.exe python-sidecar\tests`: Executa testes do sidecar Python (1000+ testes).
- `python python-sidecar/server.py`: Servidor persistente de jobs via stdin.
- `python python-sidecar/main.py --help`: CLI direta do pipeline.

# AGENTS.md - Diretrizes do Projeto USKMaker

## Regras de Release e CI
 
- **Esquema de Versionamento — [Pride Versioning 0.3.0](https://pridever.org/) (`PROUD.DEFAULT.SHAME`)**:
  - `PROUD` (1º segmento): incrementar em releases que tragam grande orgulho (zerando `DEFAULT` e `SHAME`).
  - `DEFAULT` (2º segmento): incrementar em releases normais do dia a dia / novas funcionalidades regulares (zerando `SHAME`).
  - `SHAME` (3º segmento): incrementar ao corrigir bugs embaraçosos, hotfixes rápidos ou descuidos.
- **Repositório Público**: GitHub Actions é gratuito e ilimitado.
- **Triggers automáticos ativos**: Os workflows em `.github/workflows/` (`build-windows.yml`, `build-linux.yml`, `winget.yml`) rodam em push de tags `v*`.
- **Releases via Git**: Ao dar push de uma tag `vX.Y.Z`, os workflows compilam os pacotes de Windows (.exe) e Linux (.deb, .rpm, .AppImage) e anexam ao Release no GitHub.
- **Release local opcional**: O script `scripts/release.ps1` pode ser usado caso deseje compilar ou testar localmente.

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

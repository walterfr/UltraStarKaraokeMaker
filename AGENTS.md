# AGENTS.md - Diretrizes do Projeto USKMaker

## Regras de Release e CI
 
- **Esquema de Versionamento — [Pride Versioning 0.3.0](https://pridever.org/) (`PROUD.DEFAULT.SHAME`)**:
  - `PROUD` (1º segmento): incrementar em releases que tragam grande orgulho (zerando `DEFAULT` e `SHAME`).
  - `DEFAULT` (2º segmento): incrementar em releases normais do dia a dia / novas funcionalidades regulares (zerando `SHAME`).
  - `SHAME` (3º segmento): incrementar ao corrigir bugs embaraçosos, hotfixes rápidos ou descuidos.
- **Repositório Público**: GitHub Actions é gratuito e ilimitado.
- **Triggers automáticos ativos**: Os workflows em `.github/workflows/` (`build-windows.yml`, `build-linux.yml`, `winget.yml`) rodam em push de tags `v*`.
- **Releases via Git**: Ao dar push de uma tag `vX.Y.Z`, os workflows compilam os pacotes de Windows (.exe) e Linux (.deb, .rpm, .AppImage) e anexam ao Release no GitHub.
- **Notas na aba Releases do GitHub (Obrigatório)**: Toda nova versão DEVE ter o log da versão preenchido na aba Releases do GitHub (extraído do `CHANGELOG.md` / `CHANGELOG.en.md`), tanto automaticamente via CI (`body_path` no `action-gh-release`) quanto garantindo via `gh release create <tag> --title "USKMaker <tag>" --notes-file ...` (ou `gh release edit <tag> --notes-file ...`) ao publicar a tag.
- **Release local opcional**: O script `scripts/release.ps1` pode ser usado caso deseje compilar ou testar localmente.
- **Pendências de Lojas Linux (em `packaging/linux/` e `.github/workflows/publish-linux-repos.yml`)**:
  - **AUR (`uskmaker-bin`) — Pendente (cadastro no AUR temporariamente suspenso)**: Assim que o cadastro reabrir em `https://aur.archlinux.org`, criar conta, registrar chave pública SSH (`ssh-keygen -t ed25519 -f ~/.ssh/aur`) e salvar a chave privada em `AUR_SSH_PRIVATE_KEY` nos Secrets do GitHub (`gh secret set AUR_SSH_PRIVATE_KEY < ~/.ssh/aur`). O workflow `.github/workflows/publish-linux-repos.yml` e o `packaging/linux/aur/PKGBUILD` já estão prontos e publicarão automaticamente.
  - **Snap Store (`uskmaker`) — Pendente (instabilidade no servidor Snapcraft)**: Assim que normalizar em `https://snapcraft.io`, registrar o nome `uskmaker`, exportar credencial (`snapcraft export-login snap.login`) e salvar em `SNAPCRAFT_STORE_CREDENTIALS` nos Secrets do GitHub (`gh secret set SNAPCRAFT_STORE_CREDENTIALS < snap.login`). O manifesto `packaging/linux/snap/snapcraft.yaml` e o workflow já estão prontos.

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

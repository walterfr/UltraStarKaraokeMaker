# AGENTS.md - Diretrizes do Projeto USKMaker

## Regras de Release e CI

- **Esquema de Versionamento — [Pride Versioning 0.3.0](https://pridever.org/) (`PROUD.DEFAULT.SHAME`)**:
  - `PROUD` (1º segmento): incrementar em releases que tragam grande orgulho (zerando `DEFAULT` e `SHAME`).
  - `DEFAULT` (2º segmento): incrementar em releases normais do dia a dia / novas funcionalidades regulares (zerando `SHAME`).
  - `SHAME` (3º segmento): incrementar ao corrigir bugs embaraçosos, hotfixes rápidos ou descuidos.
- **Repositório Público**: GitHub Actions é gratuito e ilimitado.
- **Triggers automáticos ativos**: Os workflows em `.github/workflows/` (`build-windows.yml`, `build-linux.yml`) rodam em push na `main` (validação de build) e em tags `v*` (geração de release + `winget.yml`).
- **Releases via Git**: Ao dar push de uma tag `vX.Y.Z`, os workflows compilam os pacotes de Windows (.exe) e Linux (.deb, .rpm, .AppImage) e anexam ao Release no GitHub.
- **Notas na aba Releases do GitHub (Obrigatório)**: Toda nova versão DEVE ter o log da versão preenchido na aba Releases do GitHub (extraído do `CHANGELOG.md` / `CHANGELOG.en.md`), tanto automaticamente via CI (`body_path` no `action-gh-release`) quanto garantindo via `gh release create <tag> --title "USKMaker <tag>" --notes-file ...` (ou `gh release edit <tag> --notes-file ...`) ao publicar a tag.
- **Release local opcional**: O script `scripts/release.ps1` pode ser usado caso deseje compilar ou testar localmente.
- **Pendências de Lojas Linux (em `packaging/linux/` e `.github/workflows/publish-linux-repos.yml`)**:
  - **AUR (`uskmaker-bin`) — Pendente (cadastro no AUR temporariamente suspenso)**: Assim que o cadastro reabrir em `https://aur.archlinux.org`, criar conta, registrar chave pública SSH (`ssh-keygen -t ed25519 -f ~/.ssh/aur`) e salvar a chave privada em `AUR_SSH_PRIVATE_KEY` nos Secrets do GitHub (`gh secret set AUR_SSH_PRIVATE_KEY < ~/.ssh/aur`). O workflow `.github/workflows/publish-linux-repos.yml` e o `packaging/linux/aur/PKGBUILD` já estão prontos e publicarão automaticamente.
  - **Snap Store (`uskmaker`) — Pendente (instabilidade no servidor Snapcraft)**: Assim que normalizar em `https://snapcraft.io`, registrar o nome `uskmaker`, exportar credencial (`snapcraft export-login snap.login`) e salvar em `SNAPCRAFT_STORE_CREDENTIALS` nos Secrets do GitHub (`gh secret set SNAPCRAFT_STORE_CREDENTIALS < snap.login`). O manifesto `packaging/linux/snap/snapcraft.yaml` e o workflow já estão prontos.
  - **Badges/Tags no `README.md` e `README.en.md` (Obrigatório após aprovação)**: À medida que os PRs/cadastros das lojas Linux forem aprovados (`deb-get` [#2083](https://github.com/wimpysworld/deb-get/pull/2083), `Pacstall` [#9562](https://github.com/pacstall/pacstall-programs/pull/9562), `AppImageHub` [#11148](https://github.com/AppImage/appimage.github.io/pull/11148), `AUR` e `Snap`), adicionar as respectivas badges (shields.io) no cabeçalho do `README.md` e `README.en.md` ao lado da badge do `winget`.

## Regras de Trabalho

- **Conventional Commits**: tipo em inglês, descrição em português.
- **Documentação espelhada**: `CHANGELOG.md`/`CHANGELOG.en.md` e `README.md`/`README.en.md` sempre espelhados no mesmo commit.
- **Ações públicas**: push, release, comentário público e fechamento de PR ou issue só com aprovação explícita do mantenedor.
- **Segredos e Tokens**: nunca gravar tokens (`HF_TOKEN`, `DISCOGS_TOKEN`, `LASTFM_API_KEY`, `FANARTTV_API_KEY`) em código ou notas — usar apenas variáveis de ambiente.
- **Testes sem letras reais**: nunca reproduzir letras de músicas comerciais em testes ou saídas versionadas; usar texto inventado.
- **Medição empírica**: medir antes de mudar limiares do pipeline com lote completo (`eval/library_replay.py --seed-set ... --aligner ctc`) e registrar resultados (inclusive negativos).

## Convenções de Formato UltraStar

- **Tag #CREATOR (Issue #35)**:
  - Os arquivos `.txt` gerados pelo USKMaker DEVEM incluir a versão do app no cabeçalho `#CREATOR`:
    `#CREATOR:USKMaker v<versao>` (ex.: `#CREATOR:USKMaker v2.0.2`).
  - Tanto a exportação direta do pipeline (`src-tauri/src/main.rs`), a tela de revisão/salvamento (`save_song`) quanto o sidecar Python mantêm e gravam este formato.
- **Decisões medidas do pipeline**:
  - `#BPM` automático fica na faixa `[200, 400)` (unidade de resolução da grade); BPM manual informado pelo usuário é literal.
  - Notas de continuação com texto `~` seguem o padrão do editor oficial.
  - O alinhador padrão de produção é o CTC global com `MMS_FA` (`DEFAULT_ALIGNER = "ctc"` em `python-sidecar/main.py`, resgate 4b em `> 0.20` e fallback para Whisper em `> 0.35`). Confirmado em escala (`n=55`, mesmos stems do baseline): reduz colapsos catastróficos (`w_1s < 0,50`) de 7 para 3 e corta o erro médio de início em 75% (`2315 ms -> 576 ms`; mediana `84,0 -> 79,2 ms`), acionando fallback Whisper em apenas 4/55 músicas.

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

### Sidecar Python (IA / MMS_FA / Demucs / WhisperX / Pitch)
- `python-sidecar\venv\Scripts\pytest.exe python-sidecar\tests`: Executa testes do sidecar Python (1000+ testes).
- `python python-sidecar/server.py`: Servidor persistente de jobs via stdin.
- `python python-sidecar/main.py --help`: CLI direta do pipeline.

## Ideias Futuras (Backlog)

- **Pré-filtro de Redução de Ruído FFT na Voz (`afftdn`) antes do Pitch/Silence**:
  - Passar a faixa vocal isolada (`vocals.wav` do Demucs) por `ffmpeg -af "afftdn=nr=70:nf=-80:tn=1"` (FFT denoise com *noise floor tracking*) antes da extração de pitch e detecção de silêncio, caso vazamentos residuais de pratos/bateria no Demucs alonguem indevidamente finais de notas sustentadas.
- **Descartado**: Exportação de partitura PDF/MusicXML via MuseScore (desnecessário pois o USKMaker já possui exportação nativa de MIDI com sílabas/letras embutidas compatível com MuseScore e DAWs).

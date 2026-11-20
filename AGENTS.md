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
- **Bump de versão (o `release.ps1` NÃO faz isso)**: alterar à mão `package.json`, `src-tauri/Cargo.toml` e `src-tauri/tauri.conf.json`; o `Cargo.lock` se atualiza sozinho com `cargo check --manifest-path src-tauri/Cargo.toml`. **Nunca fazer substituição global da versão antiga no `Cargo.lock`**: na v2.1.0 isso trocou também `webkit2gtk`, `webkit2gtk-sys` e `proc-macro-crate` (que estavam na 2.0.2), quebrou o CI do Windows (`failed to select a version for the requirement webkit2gtk = "^2" (locked to 2.1.0)`) e obrigou a reescrever o commit da release com push forçado na `main`. Antes de commitar, conferir com `git diff src-tauri/Cargo.lock`: só o bloco `name = "uskmaker"` pode mudar.
- **Microsoft Store (`UltraStar Karaoke Maker` / `USKMaker`)**:
  - **Status**: Aprovado e publicado na loja (10/11/2026).
  - **Store ID**: `9PM26VDJM55R`
  - **URL**: `https://apps.microsoft.com/detail/9PM26VDJM55R`
  - **Package Family Name (PFN)**: `walterfr.UltraStarKaraokeMaker_13vxnhy6xyrz2`
  - **Package Name**: `walterfr.UltraStarKaraokeMaker`
  - **Publisher**: `CN=2D8170EA-4E46-4D87-AB01-FA235CAE3F0D` (`walterfr`)
  - **Formato**: MSIX nativo (`scripts/build-msix.ps1`, MakeAppx do Windows SDK, assinado pela Microsoft Store).
  - **Submissão Inicial**: enviada em 09/11/2026, aprovada em 10/11/2026.
  - **Badge ativa**: presente nos cabeçalhos de `README.md` e `README.en.md`.
- **itch.io (`walterfr/uskmaker`)**:
  - **URL**: `https://walterfr.itch.io/uskmaker`
  - **Automação**: `.github/workflows/publish-itch.yml` via Butler CLI oficial.
  - **Secret necessário**: `BUTLER_API_KEY` (gerar chave em `https://itch.io/user/settings/api-keys` e salvar nos Secrets do GitHub via `gh secret set BUTLER_API_KEY`).
  - **Canais**: `walterfr/uskmaker:windows` (instalador `.exe`) e `walterfr/uskmaker:linux` (pacote `.AppImage`).
  - **Badge ativa**: presente nos cabeçalhos de `README.md` e `README.en.md`.
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
    - **Mas não domina o Whisper música a música**: em 54 pares, 11 melhoram e 13 pioram mais de 0,05 em `w_1s` (delta mediano 0). Ganha nas catástrofes e perde em músicas que já iam bem (Coldplay "The Hardest Part" 0,975→0,736; RHCP "Under The Bridge" 0,807→0,596; Florence "You've Got The Love" 0,940→0,777). Ver "Próximos passos", item 1.

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

## Conhecimento acumulado (migrado das notas do agente em 20/11/2026)

Esta seção junta o que estava só na memória privada do Claude Code, para qualquer agente (Claude Code, Antigravity, Codex...) continuar daqui. O `CLAUDE.md` só importa este arquivo; **o AGENTS.md é a fonte única**.

### Como trabalhar com o mantenedor (Walter)

- **Idioma**: responder em português, direto e curto; código, commits e termos técnicos como são.
- **Registrar tudo**: achado, medição, decisão e beco sem saída viram commit, issue ou este arquivo, nunca só o chat. Medição vai com número ("35,1 ms → 16,7 ms", não "melhorou"). Decisão contraintuitiva ganha teste que a trava, com o porquê no texto do teste. Hipótese refutada também se registra (evita refazer). Achado do tipo "não mexa nisto" vira issue (a #5 é o modelo).
- **Commits**: Conventional Commits v1.0.0, tipo em inglês e descrição em português (`fix(sidecar): detecta CPU quando não há GPU NVIDIA`). Escopos comuns: `sidecar`, `review`, `align`, `eval`, `tauri`, `ui`, `release`, `ci`. O corpo explica o PORQUÊ e traz a evidência. Não reescrever histórico antigo.
- **Pedir antes**: push, tag, release, comentário público, fechar PR/issue, baixar arquivo (dizer nome, origem e tamanho) e instalar pacote no venv. Commit local pode.
- **GPU (RTX 4060, 8 GB)**: não rodar medição pesada (lote do harness, separação) enquanto o Walter usa o app. Em 14/11 uma medição minha ocupou a VRAM e derrubou uma geração dele no resgate 4b. Perguntar antes ou checar `nvidia-smi`.
- **Dados pessoais**: não colocar e-mail ou dado pessoal de ninguém em código, notas ou requisições externas. Tokens só em variável de ambiente (o Walter tem `DISCOGS_TOKEN` e `FANARTTV_API_KEY` definidos; Last.fm em standby por escolha dele).
- **Medir antes de mudar o pipeline**, sempre no lote inteiro (`--seed-set`, 55 músicas). **Nunca concluir com n=3**: em 27/07 o `initial_prompt` deu +12,8 pp em 3 músicas e +0,1 pp em 51; o `large-v3` pareceu muito pior em 3 e empatou em 51.

### Arquitetura em uma tela

- **Tauri v2 + React 19/TS 7** (frontend em `src/`, tela de revisão em `src/review/ReviewScreen.tsx`, canvas imperativo com estado em refs) **+ Rust** (`src-tauri/src/main.rs`; núcleo `.txt`/MIDI em `rust-core/`, crate `uskmaker-core`) **+ sidecar Python** (`python-sidecar/`).
- `server.py` fica vivo lendo jobs JSON por stdin (Whisper/MMS em cache de módulo; 2º job pula ~85 s de carga). Conclusão sinalizada por `_job_status.json`; log por job lido por tail. Cancelar mata a árvore e respawna frio; fechar o app mata o servidor.
- **Pipeline** (`main.py`): download/conversão → separação Demucs (subprocesso) → alinhamento CTC global MMS_FA com curinga (`STAR_LOGP = 0.0`) → resgates (4b voz principal via MelBand Roformer karaoke, 4d, 4c) e arbitragem com Whisper (`prefer_whisper_over_ctc`) → re-flag de linhas (B1/B2) → pitch SwiftF0 → grade de BPM → `.txt` UltraStar. Modo verificação (C7, `--verify-alignment`, desligado por padrão) roda um Whisper simples quando o CTC fica sem arbitragem.
- `WordTiming.source` (anchor/fuzzy/realign/interpolated/lrc/ctc/ctc_low) atravessa Note → `song_data.json` → cores na revisão.
- Metadados em cascata: tags → MusicBrainz/CAA → iTunes → Deezer → Last.fm (`LASTFM_API_KEY`) → Discogs (`DISCOGS_TOKEN`), com validação de artista/título (D2). Letra: LRCLIB (allowlist só `lrclib.net/api`), `.lrc` vira âncora de linha.
- Auto-setup: `setup-sidecar.ps1 -Unattended` com **uv** (baixa uv + ffmpeg para `%LOCALAPPDATA%\USKMaker\bin`, `uv venv --python 3.12`, torch cu126/cpu por `nvidia-smi`). Manutenção do venv: `& "$env:LOCALAPPDATA\USKMaker\bin\uv.exe" pip install --python <python do venv> <pacote>`.

### Gotchas (cada um já custou um bug)

- **Caminho `\\?\` + PowerShell 5.1**: `resource_dir()` do Tauri devolve `\\?\C:\...`; o app chama `powershell.exe` (5.1), onde `Split-Path`/`Join-Path` perdem o drive. PS7 tolera, então só quebra no app instalado. Todo `.ps1` disparado pelo app normaliza o prefixo no topo (ver `setup-sidecar.ps1`, commit d5c4a9b).
- **Todo `.py` novo do sidecar entra em `tauri.conf.json > bundle.resources`**, senão some no app instalado.
- **Pins do torch em DOIS lugares** (`setup-sidecar.ps1` e comentário do `requirements.txt`), alinhados ao `requires_dist` do whisperx. Divergiu uma vez e o usuário perdeu a GPU em silêncio (`d508650`). A UI tem chip âmbar quando o torch caiu para CPU.
- **`audio-separator` precisa do extra `[gpu]` ou `[cpu]`**: sem ele falta `onnxruntime`, o try/except engole e o resgate de voz nunca roda. Puxa `onnx-weekly` (alvo móvel).
- **`numpy<2.5`** por causa do `numba`. Reinstalar `ctc-segmentation` (só dev) exige `pip install ctc-segmentation "numpy<2.5" --no-build-isolation` de dentro do `vcvarsall.bat`.
- **Log do Python em cp1252** quebrava o tail UTF-8 do Rust: spawn com `PYTHONUTF8=1` e leitura com `from_utf8_lossy`.
- **CSP do Tauri só vale no app compilado**, não no `tauri dev`. Conferir à mão no build (capa, áudio da revisão, LRCLIB, Sobre).
- **Build local (`target/release`) usa o venv do repo** (`python-sidecar/venv`, via `CARGO_MANIFEST_DIR`), não o do usuário. Esse venv não tem `yt_dlp` (link do YouTube falha só no teste local); `certifi` foi instalado em 14/11.
- **GitHub Actions**: evento criado com `GITHUB_TOKEN` (ex.: release publicado pelo `action-gh-release`) não dispara outro workflow. Por isso itch.io, winget e AUR/Snap são `workflow_call` chamados pelos jobs de build. Actions fixadas por SHA.
- **Computer use nesta máquina**: `screenshot` pode falhar (`empty capture (0x0)`); o processo do app chama-se `uskmaker.exe` (nome exato no pedido de acesso). Alternativa: `npm run tauri dev` e abrir `http://localhost:1423` no navegador (o `invoke` não funciona lá).
- **Máquina limpa sem VM**: `uv venv --python 3.12 --python-preference only-managed <dir>` ignora o Python do sistema. Foi assim que o bug do torch apareceu. Não cobre NSIS, VC++ redist nem máquina sem GPU.

### Harness de avaliação (`python-sidecar/eval/`)

- **Gold**: `K:\Ultrastar Songs` (~1900 charts; mantida pelo `usdb_syncer`, banco em `%LOCALAPPDATA%\bohning\usdb_syncer\usdb_syncer.db`). Seed set do @Alejololer em `K:\Ultrastar Seed` (issue #2).
- **Lote padrão**: `--seed-set python-sidecar\eval_runs\seed_jul59.json` (55 músicas medíveis). Comando base em "Dados locais de avaliação" abaixo.
- **Scripts**: `library_replay.py` (lote; `--aligner ctc`, `--separator {demucs,roformer}`, `--roformer-model`, `--tag` muda a pasta do run), `prep_stems.py` (separa cada música num processo novo, antes do alinhamento; necessário para o Roformer, que dentro do lote disputava VRAM e morria), `error_anatomy.py` (relatório das flags de linha, sem GPU, ~22 s; `--whisper-json`), `verify_whisper.py` (gera `align_verify.json` para medir o C7), `ab_align.py`, `evaluate.py`, `usdx_parse.py`.
- **Run dirs atuais em `eval_runs/`**: `replay-seedset-2_6_1` (baseline do código atual, Demucs, Whisper large-v3), `replay-seedset-roformer-karaoke`, `replay-seedset-roformer-vocals_mel_band_roformer` (G2).
- **O Whisper do harness tem de ser o do app** (`main.resolve_whisper_model("auto")` → large-v3 na RTX 4060). Até 14/11 o harness usava `medium`; todas as comparações CTC × Whisper antigas (julho, B2) eram com medium e foram remedidas.
- **Métricas**: `w_1s` (fração de palavras com onset a menos de 1 s do gold) super-reporta falha: cruzar com `onset_med_ms` separa erro localizado de música quebrada. `offset_data_mismatch` marca como `UnmeasurableSong` o áudio deslocado em relação ao gold (reta `h ≈ a·g + b`), para não contar como falha nossa.
- Letra usada no harness é a do próprio gold (caso otimista; o usuário real cola letra da web).

### Decisões travadas por medida — NÃO refazer sem dado novo

- **`STAR_LOGP = 0.0` (curinga grátis) fica** (20/11, C2): custo constante, sem curinga ou custo só onde há voz pioram o CTC cru (0,831 → 0,793–0,806 em `w_1s`, nenhuma música melhora). O curinga grátis não atrasa a letra.
- **Roformer como separador principal: não** (19/11, G1/G2 acima). Karaoke piora a sincronia; o de vocais ganha +0,011 em `w_1s`, que não paga 913 MB e o tempo.
- **`#BPM` na faixa `[200, 400)`**: o `#BPM` é a unidade da grade (`beat = 60/(BPM·4)`), não o andamento. Andamento real dava 35,1 ms/nota de erro e 59% das notas no piso de 1 beat; hoje 16,7 ms e 17%. **BPM manual é literal** (decisão do Walter).
- **Não expandir número em `compute_anchors`**: derruba âncoras exatas de 166 para 100 e joga 109/181 palavras +43,8 s. Números só no realinhamento (`f8c40a1`).
- **Notas com `~` estão corretas** (o editor oficial grava assim, `TScreenEditSub.DivideNote`; issue #5). **`#VERSION:1.0.0` fica** (a v2 da spec não foi publicada).
- **Melisma calibrado** contra 1444 charts: `MELISMA_PITCH_TOLERANCE_ST=2.0`, `MIN_SYLLABLE_S=0.45`, `MIN_EXTENSION_S=0.25` (6,5% contra 5,0% dos charts humanos, p90 casando). A causa era deriva de pitch, não vibrato.
- **Separar ajuda o pitch só quando o lead não domina** (Maneater: 32× melhor com lead isolado; Sangue Latino/Dancing Queen: 0 st). Produção em camadas é rara (2% no n=60): não vale pitch por nota agora (issue #7).
- **`suppress_silence` (stable-ts) no onset: NO-GO** (melhor caso −3,3 ms, `w_1s` não muda). O erro de onset é variância, não viés (viés mediano −15,6 ms): não há conserto global barato.
- **PT alinha ~2× melhor que EN** (onset 45,9 × 84,5 ms, julho, caminho Whisper). Refutadas: redução vocálica, tamanho do wav2vec2 (LARGE piorou), WPM. Pista não provada: fidelidade da transcrição do Whisper.
- **Levers de transcrição (27/07), todos NO-GO no lote**: anchoring fonético (38% das âncoras novas erradas), `initial_prompt` com a letra (só condiciona os primeiros ~30 s), `large-v3` na transcrição (empate). 79% das palavras não ancoradas eram falha de transcrição.
- **Forced alignment global alternativo**: bloco único, blocos por palavra/voicing e `ctc-segmentation` (196 ms mediano contra 77 ms) perderam. MFA, NeMo, gentle, aeneas bloqueados (sem wheel Windows ou AGPL). Depois disso veio o CTC global com curinga, que é o de produção.
- **Downbeat/`allin1`: NO-GO** (grade uniforme não tem onde usar downbeat; `corr(bpm_dev, onset) ≈ 0`; `natten` sem wheel Windows).
- **Loudness normalization (EBU R128) antes do Whisper: não muda a transcrição** (caso Supergrass, 17/07).
- **Seletor CTC × Whisper por música bateu no teto** (+0,036 do oráculo). O ganho que sobra está no nível de linha e em avisar a linha certa (B1/B2/C7).
- **Auditoria de 13/11 (anatomia do erro, n=51)**: 14% das palavras erram mais de 1 s, em rajadas (52% em sequências de 20+ palavras, mediana 8,6 s, 76% atrasadas: deslocamento de seção, não jitter). Refrão repetido erra 19,7% contra 8,2%. Viés nas palavras certas −32 ms: não mexer.

### Colaborador externo

- **@Alejololer**: PR #3 (timing por energia vozeada, melisma, resgate de voz principal "tenta e fica com o melhor") e PR #4 (o harness `eval/`). Tratar como par; canal ativo é a issue #2.
- O projeto paralelo dele, `usdx-autochart`, **não tem licença**: só ideias, nunca código. O que veio de lá veio por PR dele, sob MIT.
- Ideias dele não feitas: split de dueto P1/P2 por diarização e aviso de poucas palavras/min.

### Repositórios vizinhos já analisados (não reanalisar)

- **Renderam**: `rakuri255/UltraSinger` (números da letra, `#GAP` em 10 ms, motivação do melisma), `UltraStar-Deluxe/format` (`#AUDIO`, `#VOCALS`/`#INSTRUMENTAL`, pitch módulo 12), `UltraStar-Deluxe/USDX` (prova do `~`), `bohning/usdb_syncer` (sanitização de nome, `[VOC]`/`[INSTR]`, `BPM_THRESHOLD=200`), `linto-ai/whisper-timestamped` (issue #8, dígito virando âncora falsa), `vicsaizo/Karaokiza` (emoji, avc1, itch.io, títulos PT/ES, validação de metadados; falta `detect_language_by_vote` = item D3).
- **Positivos guardados**: `stemdeckapp/stemdeck` (Apache-2.0, mesma stack; referência de empacotamento macOS arm64), `retotito/UltrastarCreatorTool` (sem licença; mesma premissa de letra fornecida; tem curva de pitch atrás das notas e sing-along), `thewh1teagle/vibe` e `cjpais/Handy` (Tauri + whisper.cpp sem Python: direção de longo prazo, não tarefa; Handy sugere download manual de modelo como plano B para rede que bloqueia o Hugging Face).
- **Descartados**: `nomadkaraoke/karaoke-gen` (API paga; mas a issue #792 deles pede exatamente a nossa premissa), `zh-plus/openlrc`, `BBleae/whisper-lrc`, `dotslashgabut/lyricflow`, `AIXerum/faster-whisper`, Nightingale, UVR, pikaraoke, cog-musicgen-remixer, OmniVoice (AGPL), `nschmidtdev/USDB-Importer` (GPL), `sc0ty/subsync`, Voxtral, `marl/crepe` (SwiftF0 é mais leve e já em PyTorch), stable-ts (arquivado), aeneas, MFA, NeMo, gentle, karlyriceditor (GPL; ideia de tap-to-time).
- **Padrão**: todo vizinho transcreve do zero; nenhum parte da letra fornecida. Esse é o diferencial do USKMaker.

### Modernização da UI (parada por escolha do Walter)

Proposta de redesign WinUI 3 recusada (reescrita de stack; o app é gerador batch + revisão, e a revisão já é ~80% do "editor" proposto). Se retomar, nesta ordem: (1) trocar as cores hex de `src/index.css` por variáveis CSS (hoje zero variáveis); (2) polish (raio 8, `:focus-visible`, tooltips com atalho); (3) curva de pitch de referência atrás das notas na revisão; (4) tap-sync com `Espaço`; tecla `G` para golden.

## Próximos passos (atualizado em 20/11/2026, após a v2.9.0)

Estado: **v2.9.0** (v2.6.1: lote 1, bloco A + D1 + D4; v2.7.0: B1+B2 e parte do B3; v2.8.0: C7, D2, E1-E3; v2.9.0: A8, resto do B3, E4; G1/G2 e C2 medidos e descartados; CSP conferida à mão no app compilado em 14/11). O resto está em aberto. A lista junta a auditoria de 13/11, a verificação da v2.6.0 e a análise do `vicsaizo/Karaokiza`.

Legenda: esforço **P** (até 1 h), **M** (meio dia), **G** (mais de um dia). **[medir]** = mexe no alinhamento, só entra depois de medir no lote inteiro (`--seed-set`).

### A. Correções rápidas (bugs confirmados)

**Lote 1 feito em 13/11 e lançado na v2.6.1:** A1 itch.io encadeado ao build (`publish-itch` em `build-windows.yml`, `publish-itch.yml` virou `workflow_call`); A2 MSIX 2.2.0 fora do git e glob `USKMaker_v*.msix`; A3 limpeza de emoji sem sobras invisíveis; A4 `strict_lrc` repassado nos resgates 4b/4d/4c; A5 docstrings de `lrc_blocks`; A6 H.264 só até 1080p (`download._video_format`), 1440/2160/sem limite voltam a valer e a dica avisa do AV1/VP9; A7 `package-lock.json` em 2.6.0 e PR #478670 do winget fechado; D1 ruído de título PT/ES; D4 crédito ao Karaokiza. Verificado: pytest 1137, `npm test` 16, `tsc` limpo. O job `publish-itch` só será exercitado de verdade na próxima tag.

| ID | Item | Onde | Esforço |
|---|---|---|---|
| A8 | **Feito em 18/11, lançado na v2.9.0:** `publish-linux-repos.yml` virou `workflow_call`, chamado pelo job `publish-linux-repos` do `build-linux.yml` depois de anexar o .deb. Só será exercitado quando o AUR/Snap tiverem os secrets. Mesmo gatilho morto (`release: published` não dispara com `GITHUB_TOKEN`) em `publish-linux-repos.yml` (AUR/Snap) e no `winget.yml` avulso. O winget já está coberto pelo job encadeado; AUR/Snap não vão disparar sozinhos quando as lojas reabrirem. Encadear como o itch | `.github/workflows/` | P |

### B. Sincronia: avisar melhor o que está errado (revisão)

Base medida em 13/11 (51 músicas, 2.880 linhas, caches de 07/11): a flag atual de linha (`LOW_LINE_SCORE = 0.10`) tem precisão 0,42 e recall 0,61.

| ID | Item | Medido | Esforço |
|---|---|---|---|
| B1+B2 | **Feito em 13/11, lançado na v2.7.0:** `ctc_align.words_on_silence`, `line_start_disagreement` e `reflag_lines`, ligados em `main._reflag_ctc_lines` depois do resgate e da arbitragem (que seguem pelo score). Palavra interpolada do Whisper não conta como discordância (sem essa guarda, Whisper colapsado pintava a música inteira) | Medido com Whisper **medium** (julho): 23,1% / 0,42 / 0,61 → 21,8% / 0,55 / 0,74. **Remedido em 14/11 com o código atual e o large-v3 do app** (33 músicas em que o CTC fica): 19,4% / 0,45 / 0,58 → 22,3% / 0,44 / 0,66 | feito |
| B3 | **Feito em 13/11 (parcial), lançado na v2.7.0:** contador "Linhas suspeitas: N de M" e botão/atalho `L` "Próxima suspeita" na Revisão (`src/review/suspectLines.ts`). **Resto feito em 20/11, lançado na v2.9.0:** índice de linhas suspeitas no resultado da geração (Rust `suspect_lines`, mesmo critério do `isSuspectNote`; até 8 com minuto) e botão/atalho `K` "Confirmar linha" (`source = "confirmed"`, verde, sai das suspeitas) | resultado conferido no navegador (`?uiState=result`); o botão da Revisão só no app, falta exercitar | P |

### C. Sincronia: errar menos

O erro vem em rajada (52% das palavras erradas em sequências de 20+, mediana 8,6 s, 76% atrasadas) e em linha repetida (19,7% contra 8,2%). O seletor por música já bateu no teto; o ganho que sobra é por linha (CTC 0,839 das linhas certas, oráculo 0,909).

| ID | Item | Medido | Esforço |
|---|---|---|---|
| C1 | Fusão segura por linha: discorda em mais de 1 s **e** CTC em silêncio, usa a linha do Whisper (respeitando monotonicidade) | 48 trocas boas, 2 ruins; 0,839 para 0,855 | M **[medir]** |
| C2 | **Medido em 20/11: NO-GO, `STAR_LOGP = 0.0` fica.** `eval/star_sweep.py` (CTC cru, bloco global, emissões em `cache/<música>/emissions_ctc.pt`): curinga grátis 0,831/0,888 (média/mediana `w_1s`), 3 colapsos; custo constante −1 a −5 ou sem curinga 0,793/0,855, 5 colapsos, 0 melhoram × 9 pioram; grátis só no silêncio e com custo onde há voz (e1–e3) 0,806, 4 colapsos, 0 × 6. Viés igual (−22 × −21 ms): a hipótese "curinga grátis engole voz e atrasa a letra" está refutada; o curinga é o que segura o alinhamento (Weezer: 0,82 → 0,36 sem ele) | 55 músicas, `replay-seedset-2_6_1` | M |
| C3 | `lrc_blocks` com pad e restrição sequencial em vez de partição dura no timestamp do `.lrc` | não medido (o harness não passa `.lrc`) | M **[medir]** |
| C4 | Harness chamar a orquestração do `main.py` (hoje reimplementa) e ganhar modo com `.lrc`. | **parte feita em 13/11:** `eval/error_anatomy.py` mede os detectores no cache, sem GPU, chamando as funções de produção. Falta o harness fiel + `.lrc`, pré-requisito de C2/C3 | M |
| C5 | Checagem de refrão: avisar antes de alinhar quando a transcrição mostra repetição cantada que falta na letra | ataca a causa das rajadas; não medido | G |
| C6 | Âncora manual: usuário marca 2 ou 3 inícios de linha e o CTC realinha em blocos (reusa `lrc_blocks`) | não medido | G |
| C7 | **Feito em 14/11, lançado na v2.8.0:** modo verificação opcional, **desligado por padrão** (caixa na interface, `--verify-alignment` na CLI, `verify_alignment` no job do servidor). Com o CTC mantido sem arbitragem, `main._verify_with_whisper` roda UM `align_lyrics_to_audio` simples (sem 4b/4d/4c) só para dar o sinal de discordância ao `_reflag_ctc_lines`; não troca alinhador nem tempo de nota, e falha do Whisper é não-fatal. Orquestração extraída para `main._align_stage_ctc` (testes em `tests/test_verify_alignment_logic.py`) | Remedido em 14/11 (código atual, large-v3, 33 músicas): marca 24,2% / precisão 0,50 / recall 0,80, contra 22,3% / 0,44 / 0,66 sem o modo; ~20 s por música | feito |

Já feito e fora da lista: arbitragem por música com Whisper guardado (`prefer_whisper_over_ctc`) e correção de melisma. Não reabrir: snap/ajuste acústico de onset e correção constante de viés (NO-GO medidos em 18/07).

### D. Entrada e metadados (do `vicsaizo/Karaokiza`, MIT)

| ID | Item | Evidência | Esforço |
|---|---|---|---|
| D2 | **Feito em 14/11, lançado na v2.8.0.** Aceitar resultado de metadados só se artista **e** título parecem com a busca (`difflib`, sem dependência nova) | `_pick_itunes_result` e `_mb_find_artist_mbid` pegam o 1º resultado | M |
| D3 | Idioma por votação nas 5 janelas de 30 s com mais voz, só no caminho sem letra | `transcribe_lyrics` usa o idioma da interface | M |

### E. Robustez, segurança e CI

| ID | Item | Esforço |
|---|---|---|
| E1 | **Feito em 14/11, lançado na v2.8.0** (CSP + fila só `.json`; `assetProtocol.scope` segue `**`, a Revisão abre pacote de qualquer pasta). Definir CSP e restringir `assetProtocol.scope` (hoje `csp: null` e `**`); validar caminho em `save_queue_file` / `load_queue_file` | M |
| E2 | **Feito em 14/11, lançado na v2.8.0.** Fixar as actions de terceiros por SHA (0 de 22 hoje; o release assina o updater) | P |
| E3 | **Feito em 14/11, lançado na v2.8.0** (`npm test` no build do Windows, Node 22; pytest já rodava em ubuntu). Rodar `npm test` no CI e pytest também no Linux | P |
| E4 | **Feito em 20/11, lançado na v2.9.0:** `hard_anchor_runs`, `plan_blocks`, `align_lyrics_ctc` e `snap_line_starts` foram para `eval/ab_align.py` (testes seguem em `test_ctc_align_logic.py`); `align_file` apagado (sem chamador). Pedido original: tirar de `ctc_align.py` o código só usado por `eval/ab_align.py` (`hard_anchor_runs`, `plan_blocks`, `align_lyrics_ctc`, `snap_line_starts`, `align_file`) | P |

### F. Pendências antigas

| ID | Item | Esforço |
|---|---|---|
| F1 | Validar o sing-along com microfone real (detalhe no item 2 abaixo) | P (manual) |
| F2 | Arquivos grandes: `App.tsx` (~2830 linhas), `ReviewScreen.tsx` (~2740), `main.rs` (~2310) | G |
| F3 | macOS (issue #36) | G |
| F4 | Lojas Linux pendentes (AUR, Snap), ver "Regras de Release e CI" | P cada, quando reabrirem |

### G. Separação de voz (motores)

| ID | Item | Evidência | Esforço |
|---|---|---|---|
| G1 | **Descartado em 19/11 (medido no G2).** Hipótese original: Mel-Band Roformer como separador principal ("Qualidade") ao lado do Demucs ("Velocidade"). O código já existe (`separate_vocals(..., backend="roformer")` em `pipeline/separate.py`), mas nada em `main.py`/`server.py`/UI passa o parâmetro | Ensaio de 13/11 (`eval/benchmark_roformer.py`, 1 trecho de 30 s) **não é comparável**: o tempo do Demucs inclui abrir o processo e carregar o modelo, o do Roformer não; VRAM do Demucs fica fora do processo medido; o script não calcula vazamento. **Atenção:** o modelo testado (`mel_band_roformer_karaoke_aufr33_viperx`) é o do resgate 4b: separa voz PRINCIPAL × resto e joga coro/harmonia no instrumental, então letra cantada pelo coro some do stem que o alinhador ouve (em 13/11 o lead isolado melhorou o CTC numa música, 21,6% → 18,8% de baixa confiança, e piorou noutra, 26,7% → 43,0%). Medido no G2: **descartado** (19/11) | M |
| G2 | **Feito em 19/11, encerrado.** Medir separadores pelo que importa (alinhamento e pitch), não tempo/dB: `eval/library_replay.py --separator {demucs,roformer} --roformer-model <ckpt>` nas 55 músicas do seed-set, comparando `w_1s`, onset e pitch contra o Demucs. Candidatos: o karaoke atual e um modelo de vocais completos (`vocals_mel_band_roformer`). Conferir licença dos pesos antes de expor na UI. **Karaoke medido 18/11 (53 comuns, CTC, whisper large-v3, `replay-seedset-roformer-karaoke` × `replay-seedset-2_6_1`): sincronia PIORA** — w_1s média 0,877 → 0,831 (mediana 0,923 → 0,917), colapsos (w_1s < 0,5) 1 → 4, 9 melhoram × 13 pioram (>0,05; pior: Manu Chao - Clandestino −0,92); onset mediano igual (73 → 71 ms). **Pitch melhora**: corr 0,683 → 0,722, ±2 st mod 12 0,811 → 0,831. Karaoke como separador principal descartado para alinhar; pitch sobre o lead fica como ideia. Modelo vocais: 1ª rodada falhou nas 58 (stem chama `Other`, e o fallback de nomes casava `(other)_vocals_...` como vocal) — corrigido em `_separate_with_roformer`. **Vocais medido 19/11 (55 comuns, `replay-seedset-roformer-vocals_mel_band_roformer`): sincronia melhora pouco** — w_1s média 0,878 → 0,889 (mediana 0,923 → 0,931), 12 melhoram × 5 pioram (>0,05), onset MAE mediano 537 → 411 ms, onset mediano igual (72 → 70 ms); pitch empata (corr 0,685 → 0,698, ±2 st mod 12 0,815 → 0,808). Colapsos 1 → 2: Michael Jackson - Blood On The Dance Floor cai 0,74 → 0,02 com o resgate VENCENDO e a música inteira deslocada ~25 s (bias −24,8 s) — a arbitragem aceitou um deslocamento global; no karaoke a mesma música também colapsa (0,23, bias −9,7 s). Sem piso de ruído medido (rodar o Demucs 2× para saber quanto de 0,011 é ruído). Próximo: piso de ruído + investigar a arbitragem que aceitou o deslocamento; só depois decidir se o vocais vira opção "Qualidade" (pesos MIT, 913 MB). **Encerrado 19/11 (decisão do Walter): ganho não paga o custo; Demucs segue único separador de alinhamento** | — | M |

### Detalhes dos itens antigos (07/11/2026)

1. **Seletor CTC × Whisper (investigação de 07/11; a arbitragem guardada entrou depois em `prefer_whisper_over_ctc`).** O CTC perde em 13 de 54 músicas (ver "Decisões medidas"). Simulação offline com os dados em cache:

   | Fallback para Whisper quando `low_frac` > | média `w_1s` | mediana | colapsos (`w_1s` < 0,5) |
   |---|---|---|---|
   | nunca (só CTC) | 0,837 | 0,879 | 3 |
   | 0,35 (limiar atual) | 0,837 | 0,879 | 3 |
   | 0,25 | 0,844 | 0,897 | 4 |
   | 0,20 | 0,837 | 0,909 | 5 |
   | oráculo (sempre o melhor dos dois) | 0,873 | 0,931 | 3 |
   | só Whisper (julho) | 0,808 | 0,899 | 7 |

   - `low_frac` = fração de palavras `ctc_low`/`interpolated` (`ctc_align.low_confidence_frac`). Prevê pouco: mediana 0,231 nas que pioraram contra 0,177 no resto, com muita sobreposição (Coldplay 0,135, Bob Marley 0,115, Manu Chao 0,039 pioram mesmo com confiança alta).
   - Baixar o limiar sobe a mediana mas traz colapsos de volta. O teto de um seletor perfeito é +0,036 na média e +0,05 na mediana.
   - **Achados da análise offline nos caches (`n=54`, sem GPU)**:
     - **Sinais só do CTC** (`wpm`, `lang`, voicing em `pitch.npz`, `low_frac`) não separam `CTC perdeu` (`low_frac` mediano `0,231`) de `Whisper colapsou` (`low_frac` mediano `0,222`). O melhor sinal puro do CTC é o `score` médio por palavra (`c_sc_mean < 0,25`): troca só 11/54 músicas, sobe média `0,837 -> 0,848` e mediana `0,879 -> 0,909` **sem trazer colapsos de volta (`col = 3`)** (`+10 / -8` vs Whisper).
     - **Por que baixar `low_frac` trazia colapsos de volta**: porque `_align_with_ctc` descarta o CTC (`return None`) ao chamar o Whisper, trocando mesmo quando o próprio Whisper colapsa (`w_interp` alto: 4 Non Blondes `0,432`, Beatles `0,403`, Weezer `0,268`, RHCP By The Way `0,233`). Nas 13 músicas em que o CTC perdeu, o Whisper teve `w_interp <= 0,072` (mediana `0,017`).
     - **Fallback guardado + arbitragem por palavra discordante**: mantendo o CTC se o Whisper vier com `w_interp >= 0,08` e comparando o `score` médio especificamente nas palavras em que `|t_ctc - t_whi| > 1,0s` (`dis_sc_gap = dis_w_sc - dis_c_sc > 0,35`), chega-se a **média `0,868`, mediana `0,922`, `col = 3`, onset mediano `69,9 ms` e saldo `+11 / -1` contra o Whisper** (captura 86% do teto do oráculo; com gatilho `c_sc_mean < 0,35` roda Whisper em 37/54 e entrega `0,862` / mediana `0,917` / `+11 / -3`).
     - **Correção de melisma em `ctc_align.py` (implementada e medida em `n=55`)**: em músicas com melisma longo (ex.: Coldplay `"pa~rt"`, `"ri~ng"`; Simply Red `"keep"` 6x no refrão; Céline Dion `"far,"`; Legião Urbana `"amar"`), o CTC alinha a sílaba inicial no tempo certo, emite blank (`-`) durante ~1,2s de vogal sustentada e alinha a consoante final na cauda; `_trim_premature_word_prefix` (`gap_s > 0,8s` e `prefix_dur_s <= 0,4s`) descartava o início real, encolhendo 44 palavras em 20 músicas para 1–4 quadros (`0,02–0,08s`) no fim da nota (`+1,4s` atrasadas). Adicionada a guarda `MIN_TRIMMED_SUFFIX_S = 0.10` (preserva o início quando a cauda pós-gap tem `<= 0,10s`). **Medido nas 55 músicas do seed-set**: 31 músicas melhoram (Céline Dion `+0,068`, Simply Red `+0,059`, Coldplay `+0,031`, Beatles I Should Have Known Better `+0,029`, The Smiths `+0,024`, Legião Urbana e Beatles Help! chegam a `1,000`), média `w_1s` sobe `0,838 -> 0,846` (`0,837 -> 0,844` nas 54 pareadas) e mediana sobe `0,881 -> 0,892` (`0,879 -> 0,891` nas 54 pareadas), a custo zero de GPU.
   - Ressalvas: o lado Whisper da simulação é o pipeline de julho (o fallback real roda o código atual), e a simulação usa `w_1s` do harness, não o app. Só mexer em limiar de produção depois de medir no lote inteiro.

2. **Validar o sing-along com microfone real.** Saiu na v2.1.0 sem teste com microfone (só sinais sintéticos em `test/micPitch.test.ts`). Abrir a Revisão no app, apertar `M`, cantar **de fones**. Conferir: o rastro rosa acompanha a voz, some ao desligar, o indicador de gravação do Windows apaga. Hipóteses não verificadas: Linux/webkit2gtk sem `getUserMedia` (o botão some) e macOS exigindo `NSMicrophoneUsageDescription`.

3. **Arquivos grandes** (refatorar quando houver motivo): `src/App.tsx` (~2670 linhas), `src/review/ReviewScreen.tsx` (~2410), `src-tauri/src/main.rs` (~2140). *(Conversão de escala de pitch em `ReviewScreen.tsx` já extraída e deduplicada em `computePitchScale`.)*

4. **macOS** (issue #36, procurando quem tenha Mac Apple Silicon). Referência de empacotamento arm64 com licença permissiva: `stemdeckapp/stemdeck` (Apache-2.0).

5. **Dependências**: Vite 8, React 19 (`19.3.1`) e TypeScript 7 (`7.0.2`) atualizados e validados (`tsc`, `vite build`, `npm test` 16/16, `npm audit` 0).

### Dados locais de avaliação (fora do git)

Tudo em `python-sidecar/eval_runs/` (ignorado pelo git; só existe nesta máquina, que tem a biblioteca gold em `K:\Ultrastar Songs`):

- `seed_jul59.json`: as 59 músicas de julho (57 ainda na biblioteca). Usar sempre `--seed-set` para comparar; `--n 60 --seed 1` hoje sorteia outras músicas, porque o manifesto foi reconstruído com 1897 charts.
- `replay-n60-seed1-jul/`: baseline de julho, caminho Whisper (`results.csv`).
- `replay-seedset/`: medição do CTC de 07/11 (`results.csv`). Em `cache/<música>/` ficam `align_ctc.json` (CTC atual, palavras com `source` e `score`) e `align.json` (Whisper de julho), mais os stems fixos.
- Medir de novo: `python-sidecar\venv\Scripts\python.exe python-sidecar\eval\library_replay.py --lib "K:\Ultrastar Songs" --seed-set python-sidecar\eval_runs\seed_jul59.json --aligner ctc --device cuda`
  - Com `--seed-set` o harness grava em `replay-seedset/` (ou `replay-seedset-<separador>-<modelo>`/`-<tag>` com `--separator`/`--tag`) e **pula** música que já tem resultado. Para medir uma mudança de código, renomeie antes a pasta atual (ex.: `replay-seedset-2.1.0`) e recrie `replay-seedset/` com os stems em hard link (`vocals.wav`, `no_vocals.wav`, `lead_vocals.wav` de cada `cache/<música>/`). Assim a separação do Demucs, que não é determinística, fica fixa e a comparação vale.
  - O cache também é reaproveitado só pela existência do arquivo (`align_ctc.json`/`align.json`): se não apagar esses arquivos, a mudança no alinhador nem roda.

## Ideias Futuras (Backlog)

- **Suporte nativo a escritas sem espaços (Japonês/Chinês) (Implementado)**:
  - Detecta caracteres CJK na letra e aplica segmentador morfológico (*wakachigaki* via `pykakasi` para japonês e por ideograma para chinês) em `align.py` (`segment_line_words`), evitando colapso de âncoras e geração de nota única por linha.
  - Divisão silábica precisa em moras e ideogramas individuais em `syllabify.py` (`is_cjk_char`, `_SMALL_KANA`).
  - *Pendente futuro*: Exibir aviso/progresso visual de download na UI quando o WhisperX estiver baixando modelos acústicos pesados (como `wav2vec2-large-xlsr-53-japanese` de 1,26 GB).
- **Pré-filtro de Redução de Ruído FFT na Voz (`afftdn`) antes do Pitch/Silence**:
  - Passar a faixa vocal isolada (`vocals.wav` do Demucs) por `ffmpeg -af "afftdn=nr=70:nf=-80:tn=1"` (FFT denoise com *noise floor tracking*) antes da extração de pitch e detecção de silêncio, caso vazamentos residuais de pratos/bateria no Demucs alonguem indevidamente finais de notas sustentadas.
- **Oportunidades inspiradas no `lrcget` (LRCLIB client)**:
  - **Parser nativo de tags de áudio em Rust (`lofty` / `symphonia`)**: Substituir ou acelerar a leitura de metadados em lote (`read_tags.py`) diretamente pelo Rust no `rust-core`/Tauri, permitindo varreduras instantâneas de pastas de áudio locais sem overhead de subprocesso Python.
  - **Enhanced LRC (Karaokê por palavra / sílaba `<mm:ss.xx>`)**: O LRCLIB suporta timestamps no nível de palavra em faixas enriquecidas pela comunidade. Extrair e converter essas âncoras finas para guiar o alinhamento de sílabas quando o `.lrc` contiver marcação intra-linha.
  - **Identificação do Client na API LRCLIB**: Mantido atualizado com a versão corrente em `src/App.tsx` (`USKMaker/vX.Y.Z`).
- **Descartado**: Exportação de partitura PDF/MusicXML via MuseScore (desnecessário pois o USKMaker já possui exportação nativa de MIDI com sílabas/letras embutidas compatível com MuseScore e DAWs).

# Contribuindo com o USKMaker

*(English: [CONTRIBUTING.en.md](CONTRIBUTING.en.md))*

Obrigado pelo interesse! Este documento explica como propor mudanças, relatar
problemas e o que esperar do processo de revisão.

## Antes de começar

- **Bugs e ideias vão em [Issues](https://github.com/walterfr/UltraStarKaraokeMaker/issues).**
  Para bug, inclua: o que você esperava, o que aconteceu, e se possível o
  `pipeline_debug.log` da pasta de saída do pacote.
- **Mudanças grandes ou que alteram o escopo do projeto**, abra uma issue
  antes de codar — evita retrabalho se a direção não fizer sentido para o
  projeto.
- **Escopo do projeto:** o USKMaker parte da **letra que o usuário já tem** e
  alinha a IA a ela (forced alignment). Ele **não transcreve a música do
  zero** — esse é o diferencial deliberado (existem outras ferramentas que
  fazem isso). PRs que mudem essa premissa central devem discutir o motivo na
  issue primeiro.

## Ambiente de desenvolvimento

Veja **[README.md](README.md)**, seção "Opção B — Ambiente de desenvolvimento",
para configurar o sidecar Python e o app Tauri localmente.

Estrutura do repositório:

| Pasta | O quê |
|---|---|
| `python-sidecar/` | Pipeline de IA (WhisperX, Demucs, SwiftF0, librosa) |
| `src-tauri/` | Backend Rust/Tauri (orquestra o sidecar, comandos da UI) |
| `rust-core/` | Crate `uskmaker-core` — lógica compartilhada (escritor do `.txt` UltraStar) |
| `src/` | Frontend React/TypeScript |
| `eval/` | Harness de avaliação contra biblioteca gold (`library_replay.py`) |
| `scripts/` | `setup-sidecar.ps1` — configura o ambiente de IA do usuário final |

## Rodando os testes

**Python** (`python-sidecar/tests/`): scripts independentes baseados em
`assert`, sem framework (pytest, etc.) — de propósito, para manter o teste
tão simples quanto o código que ele verifica. Cada arquivo roda sozinho:

```bash
cd python-sidecar
python tests/test_build_song_logic.py
python tests/test_align_logic.py
# ... (um por arquivo em tests/)
```

**Rust:**

```bash
cd src-tauri && cargo test
cd rust-core && cargo test
```

Nenhum teste sobe rede nem precisa de GPU — são lógica pura (parsing,
formatação, regras de negócio). Se sua mudança tem lógica não-trivial (um
branch, um parser, uma regra), inclua um teste no mesmo estilo.

## Estilo de commit

O projeto usa **[Conventional Commits](https://www.conventionalcommits.org/)**
com uma convenção própria: **tipo em inglês, descrição em português**.

```
feat(pipeline): mudança de tom (transposição do pacote)
fix(review): download de assets falhava - stdout poluido por avisos
chore(release): v0.9.0
docs: atualiza instruções de instalação
```

Tipos comuns: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`. O escopo
entre parênteses é opcional, mas ajuda (`pipeline`, `review`, `ui`, `export`).

## Pull Requests

1. Branch a partir de `main`.
2. Testes relevantes passando (Python + Rust, conforme o que você tocou).
3. Se a mudança é **visível pro usuário** (feature, correção de comportamento):
   atualize **`CHANGELOG.md` e `CHANGELOG.en.md` juntos**, na mesma seção
   `[Unreleased]` ou próxima versão — os dois arquivos têm que dizer a mesma
   coisa nos dois idiomas.
4. PRs pequenos e focados em uma coisa são mais fáceis de revisar do que um
   PR que mistura features não relacionadas.
5. Descreva o *porquê* da mudança, não só o *o quê* — o diff já mostra o quê.

## Segurança

- **Nunca** commite tokens/chaves (`HF_TOKEN`, `DISCOGS_TOKEN`,
  `LASTFM_API_KEY`, `FANARTTV_API_KEY` ou qualquer outro). Sempre variável de
  ambiente.
- Se encontrar uma vulnerabilidade, prefira reportar de forma privada ao
  mantenedor antes de abrir uma issue pública.

## Licença

Ao contribuir, você concorda que sua contribuição será licenciada sob a
mesma licença do projeto ([MIT](LICENSE)).

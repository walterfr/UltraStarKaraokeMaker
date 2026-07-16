# Changelog

Todas as mudanças relevantes do USKMaker. *(English: [CHANGELOG.en.md](CHANGELOG.en.md))*

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o projeto usa [Versionamento Semântico](https://semver.org/lang/pt-BR/).

Cada versão tem um instalador pronto em **[Releases](https://github.com/walterfr/UltraStarKaraokeMaker/releases)** — as notas de cada release trazem também as instruções de instalação.

## [0.3.3] — 2026-07-16

### Alterado

- **O Git não é mais necessário para instalar.** O `whisperx` (a biblioteca de alinhamento) era a única dependência instalada direto do repositório do GitHub (`git+https://...`), e só por causa dela o **Configurar ambiente de IA** exigia Git na máquina. Quem não tinha via o setup morrer no meio e a geração falhar depois com *"o sidecar encerrou inesperadamente"*, sem nem gerar log. Agora ele vem do PyPI, com a versão fixa (`whisperx==3.8.7rc1`) — o que também torna a instalação reproduzível, já que o `git+` seguia o último commit do repositório, um alvo móvel. É exatamente a mesma versão de antes: o pacote do PyPI foi verificado como o mesmo código, arquivo por arquivo, e confirmado com uma geração completa. Pacotes gerados não mudam.

## [0.3.2] — 2026-07-16

### Corrigido

- **O app dizia "ambiente OK" quando não estava.** Se a configuração do ambiente de IA falhasse no meio, o app mostrava o ✓ verde mesmo assim e escondia o botão de configurar; a geração então falhava com *"o sidecar encerrou inesperadamente"* e **sem gerar log** (o processo morria antes de criá-lo). Agora o app confere as bibliotecas de verdade e avisa quais faltam.
- **O setup falha de verdade quando dá errado**, em vez de terminar com mensagem de sucesso.

### Adicionado

- **Notas douradas automáticas** (`*`) nas partes sustentadas, como nos charts feitos à mão (~5% das notas, proporção calibrada medindo charts da comunidade). Antes os pacotes saíam sem nenhuma.
- **Consistência de oitava** no pitch — corrige notas isoladas em que o detector errava a oitava.

### Alterado

- **Timing bem mais preciso** — a divisão das sílabas segue a voz de verdade (em vez de dividir o tempo em partes iguais), com **melisma (`~`) real** nas sílabas sustentadas e âncoras de alinhamento mais robustas. Contribuição de [@Alejololer](https://github.com/Alejololer).
- **Resgate de voz principal** — quando o coro atrapalha o alinhamento, o app isola a voz principal e tenta de novo, só aceitando se melhorar. Contribuição de [@Alejololer](https://github.com/Alejololer).
- A tela de revisão passa a sinalizar também as notas medidas com **baixa confiança**, não só as estimadas.
- Novo módulo `eval/`: harness de avaliação de qualidade (pontuação no domínio do tempo). Contribuição de [@Alejololer](https://github.com/Alejololer).

## [0.3.1] — 2026-07-15

### Corrigido

- **O setup não abria em algumas máquinas** — o botão "Configurar ambiente de IA" falhava com um erro de caminho (`Join-Path ... o valor do argumento "drive" é nulo`) no Windows PowerShell 5.1.
- **Crash com acentos/emoji** — títulos ou tags com caracteres especiais (CJK, emoji) derrubavam o processamento no Windows. Tudo em UTF-8 agora.

### Adicionado

- **Preenchimento automático de título e artista** a partir das tags do arquivo de áudio (só os campos ainda vazios).
- **Imagem de fundo `#BACKGROUND`** no pacote: fundo 16:9 real via [fanart.tv](https://fanart.tv/get-an-api-key/) (opcional, com `FANARTTV_API_KEY`); sem a chave, reaproveita a capa — assim todo pacote com capa passa a ter fundo.
- **Correção automática de BPM** — conserta o erro comum de "meio/dobro" no andamento detectado.
- **Caixa "deixar só o essencial"** — ao fim da fila, apaga os auxiliares (`.lrc`/`.log`/`.json`) de cada pasta (opcional; remove a tela de revisão daquele pacote).
- Link discreto de apoio ao projeto na página "Sobre".

### Alterado

- Campos de **título/artista movidos para acima da busca de letra** — a busca depende deles.

## [0.3.0] — 2026-07-12

### Adicionado

- **Auto-setup do ambiente de IA por um botão.** "Configurar ambiente de IA" baixa o `uv` (que instala o Python 3.12 se você não tiver), um **ffmpeg embutido** (com libvorbis) e as bibliotecas de IA, com progresso ao vivo no app. Acabou a necessidade de instalar Python à mão, pôr o ffmpeg no PATH ou rodar o `setup-sidecar.ps1` (que segue disponível como alternativa).

## [0.2.2] — 2026-07-12

### Corrigido

- **Máquinas sem GPU NVIDIA** (ex.: Intel Iris Xe) falhavam com `AssertionError: Torch not compiled with CUDA enabled`, mesmo com a interface indicando modo CPU. O app agora detecta a ausência de CUDA e roda tudo na CPU automaticamente.

## [0.2.1] — 2026-07-12

Correções a partir de feedback da comunidade, validadas contra a [spec oficial do formato](https://github.com/UltraStar-Deluxe/format/blob/main/The%20UltraStar%20File%20Format%20(v1).md).

### Corrigido

- **Til (`~`) nas sílabas** — o `~` era prefixado em toda sílaba de continuação, e o jogo exibia o til literal na tela ("Ju~rei").
- **GAP / primeira nota** — a primeira nota agora começa no beat 0 e o atraso real do canto vai para a tag `#GAP`, então re-sincronizar com outro áudio é só ajustar o `#GAP`.
- **Mensagens de erro traduzidas** — os erros vindos do núcleo Rust passam a respeitar o idioma da interface.

## [0.2.0] — 2026-07-12

### Adicionado

- **Fila de músicas + modelos quentes** — um sidecar Python persistente mantém os modelos carregados entre músicas; da 2ª em diante o alinhamento fica bem mais rápido.
- **Buscar letra (LRCLIB)** por artista + título. Havendo versão sincronizada, os tempos de cada linha entram como âncoras no alinhamento.
- **Interface bilíngue PT/EN**, detectando o idioma do sistema.
- **Saída organizada** numa subpasta `Artista - Título` (padrão das coleções UltraStar).
- Splash, página "Sobre" e ícone nítido na barra de tarefas.

### Alterado

- **Reformulação de UX** — checagem de ambiente na abertura, validação da letra em tempo real, lista de etapas com estado e duração, cancelamento de verdade, e resultado com capa, metadados e contagem de notas medidas vs. estimadas.

## [0.1.0] — 2026-07-09

Primeira release pública: pipeline completo (letra sincronizada, pitch, BPM, metadados, vídeo), instalador Windows e setup assistido do ambiente de IA.

[0.3.3]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.3
[0.3.2]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.2
[0.3.1]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.1
[0.3.0]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.0
[0.2.2]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.2.2
[0.2.1]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.2.1
[0.2.0]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.2.0
[0.1.0]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.1.0

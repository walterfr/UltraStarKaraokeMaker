# Changelog

Todas as mudanças relevantes do USKMaker. *(English: [CHANGELOG.en.md](CHANGELOG.en.md))*

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o projeto usa [Versionamento Semântico](https://semver.org/lang/pt-BR/).

Cada versão tem um instalador pronto em **[Releases](https://github.com/walterfr/UltraStarKaraokeMaker/releases)** — as notas de cada release trazem também as instruções de instalação.

## [Não lançado]

### Adicionado

- **Modo dueto (duas vozes).** Marque a caixa **Dueto** e diga na letra quem canta cada trecho com uma tag no início da linha — `P1:`, `P2:` ou `P1&P2:` quando cantam juntos (linha sem tag continua com o cantor da anterior). O pacote sai no formato de dueto que a comunidade usa: headers `#P1`/`#P2` (os nomes vêm do artista, ex.: "Elton John & Kiki Dee"), o corpo em dois blocos `P1`/`P2` e o sufixo `[DUET]` no arquivo. As duas vozes já estão no vocal que o app isola — o alinhamento não muda, a tag só diz de quem é cada linha. Em dueto, o resgate por voz principal isolada é pulado (ele descartaria o segundo cantor).

## [0.3.8] — 2026-07-17

### Adicionado

- **Aviso quando o app não reconhece bem a letra na música.** Havia um jeito de o pacote sair fora de sincronia sem nenhum aviso: quando o app "ouvia" outra coisa e encaixava as notas com falsa confiança, nos lugares errados. O aviso anterior só pegava o caso em que o app *não conseguia* encaixar — não o caso em que ele encaixava errado. Agora, quando o reconhecimento da letra fica baixo, a tela de resultado avisa para você conferir a sincronia (e, se estiver ruim, gerar de novo). Descoberto medindo 60 músicas contra charts feitos à mão.

## [0.3.7] — 2026-07-17

Duas melhorias na precisão das notas, as duas medidas contra 1444 charts feitos à mão.

### Alterado

- **Menos til (`~`) sobrando.** O `~` marca uma nota que sustenta e muda de altura dentro da mesma sílaba — mas o app estava exagerando: colocava `~` em três vezes mais notas que os charts feitos à mão. A causa era confundir uma nota que *escorrega* de altura (algo comum ao cantar) com uma mudança de nota de verdade. Agora a proporção de `~` está alinhada com o que os humanos fazem.

### Corrigido

- **Número na letra podia levar uma nota para o lugar errado.** Quando o app "ouvia" um número na música (ex.: "17") e a sua letra também trazia o número escrito como dígito, ele podia fixar uma nota num tempo inventado, com falsa confiança. Agora esse caso é detectado e a nota é medida do jeito certo. (Escrever o número por extenso na letra — "dezessete" — nunca foi afetado.)

## [0.3.6] — 2026-07-17

### Corrigido

- **Quem instalou nas últimas semanas provavelmente está rodando sem a GPU — e nem sabe.** A instalação baixava ~2,5 GB da versão do PyTorch com CUDA e, no passo seguinte, **trocava tudo por uma versão sem CUDA** sem avisar. O resultado: processamento na CPU (~10 min por música em vez de ~2), com o app ainda mostrando "✓ GPU". Pior: quando dava para perceber, a mensagem culpava o **driver de vídeo** — que nunca teve nada a ver. **Se você tem GPU NVIDIA, rode o Configurar ambiente de IA de novo** e confira a linha final: deve dizer `CUDA disponivel: True`.
  *(O bug apareceu sozinho, sem ninguém mexer em nada: a biblioteca que fazíamos o download passou a servir uma versão mais nova do que a que o app precisa.)*

- **Músicas que saíam completamente fora de sincronia agora se resolvem sozinhas.** A separação da voz varia a cada tentativa, e de vez em quando sai uma ruim — quando isso acontece, o app não reconhece o canto e o pacote inteiro sai errado. Agora ele detecta e **refaz a separação automaticamente**, ficando com o melhor resultado. Custa 1–3 minutos, e só nos casos em que a primeira tentativa falhou.

- **Se mesmo assim falhar, o app avisa** em vez de entregar calado. Antes, um pacote com 89% das notas estimadas trazia o mesmo aviso discreto de um com 5%.

- **Notas depois do fim da música.** Quando o alinhamento se perdia, as notas podiam ser escritas além do fim do áudio — o jogo mostrava nota sem ter o que cantar.

### Alterado

- **`#GAP` arredondado para 10 ms** (`1927` → `1930`). O valor vinha do início da primeira palavra detectada, cuja precisão real é de dezenas de milissegundos — o milissegundo ali era ruído com cara de exatidão. É a convenção da comunidade, e 10 ms está bem abaixo do que o ouvido percebe.

## [0.3.5] — 2026-07-16

### Adicionado

- **Faixas separadas de voz e instrumental no pacote** (opcional). Marcando a caixa, o pacote leva também a voz isolada e o playback, e o jogo passa a poder **controlar o volume da voz-guia separado do instrumental** — subir para aprender a música, zerar para cantar sozinho. A separação já acontecia de qualquer jeito (é como o app entende o canto); antes as faixas eram descartadas no fim. O pacote fica quase 3× maior, por isso a caixa vem desmarcada.

### Corrigido

- **O BPM manual voltou a ser literal.** Na v0.3.4 o valor digitado era ajustado junto com o automático. O campo existe para você mandar quando a detecção erra — então agora vai exatamente o que você digitou. Se o valor ficar fora da faixa que dá as notas mais precisas, o log só avisa, sem mexer no número.

## [0.3.4] — 2026-07-16

Melhorias de qualidade do chart e um bug que quebrava pacotes em silêncio. Boa parte veio de revisar os projetos vizinhos ([UltraSinger](https://github.com/rakuri255/UltraSinger), [UltraStar-Creator](https://github.com/UltraStar-Deluxe/UltraStar-Creator), [usdb_syncer](https://github.com/bohning/usdb_syncer) e a [spec oficial](https://github.com/UltraStar-Deluxe/format)).

### Corrigido

- **Título com `?`, `/` ou `:` quebrava o pacote.** Sanitizávamos o nome da pasta, mas não o dos arquivos dentro dela — e bastava um caractere comum para dar errado de três jeitos: "AC/DC" fazia o áudio ir parar em outra pasta (pacote sem som, sem erro nenhum), "Quem?" fazia a geração falhar, e "Song 2: Live" criava um arquivo de **0 byte** com o áudio escondido num *stream* do NTFS — sem reclamar. Agora os nomes seguem a mesma convenção que o USDB usa ("AC/DC" vira "AC-DC"). O título e o artista continuam intactos dentro do arquivo e nas buscas de capa/ano/gênero.
- **Notas muito mais precisas: o `#BPM` agora usa a grade fina dos charts feitos à mão.** O `#BPM` do UltraStar não é o andamento da música — é a unidade da grade de tempo. Gravávamos o andamento real, o que dava uma grade grossa demais: **59% das notas ficavam presas na duração mínima**, porque a duração real delas simplesmente não cabia. Agora a duração das notas reflete o que é cantado de verdade, e o erro de tempo por nota caiu pela metade.
- **Números na letra ("20", "1985") saíam com a nota errada.** Ninguém canta "dois-zero", canta "vinte" — e o alinhador não entende dígitos. A nota do número saía até 6× curta demais e adiantada. Agora ela acompanha o que é cantado. A letra continua escrita do seu jeito, com o número.

### Adicionado

- **Tag `#AUDIO`** no pacote, junto do `#MP3` e apontando para o mesmo arquivo. É para onde o formato está migrando: a spec já manda os players preferirem o `#AUDIO` quando ele existe, e a próxima versão do formato o torna obrigatório. Escrever os dois atende player novo e antigo.

### Nota

- O ambiente de IA ganhou uma biblioteca nova (para os números por extenso). Se você **não** rodar o **Configurar ambiente de IA** de novo, tudo continua funcionando — só a correção dos números não entra em ação.

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

[0.3.8]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.8
[0.3.7]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.7
[0.3.6]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.6
[0.3.5]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.5
[0.3.4]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.4
[0.3.3]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.3
[0.3.2]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.2
[0.3.1]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.1
[0.3.0]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.3.0
[0.2.2]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.2.2
[0.2.1]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.2.1
[0.2.0]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.2.0
[0.1.0]: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/v0.1.0

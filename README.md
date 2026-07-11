# USKMaker — UltraStar Karaoke Maker

Gerador de pacotes de karaokê **UltraStar** a partir de um link do YouTube ou de um arquivo de áudio local, com sincronização de letra, extração de pitch, detecção de BPM e metadados (capa, ano, gênero) automáticos.

O diferencial em relação a ferramentas como o UltraSinger é que o USKMaker parte da **letra que o usuário já fornece**. O problema passa a ser de *forced alignment* (alinhar uma letra conhecida ao áudio), não de transcrição do zero — o que resulta em sincronização bem mais precisa, especialmente em português.

Todo o processamento é **local**: não depende de APIs pagas nem envia áudio para serviços externos. As únicas consultas de rede são a bancos abertos e gratuitos (MusicBrainz/Cover Art Archive, iTunes, Deezer e — opcionalmente, com token pessoal — Discogs) para enriquecer metadados, e o download do YouTube quando solicitado.

## Como funciona

O pipeline tem seis etapas:

1. **Obter áudio** — baixa do YouTube (via `yt-dlp`) ou normaliza um arquivo local para WAV. Opcionalmente baixa também o vídeo, para fundo animado no jogo.
2. **Separação vocal** — isola voz e instrumental com Demucs (`htdemucs`).
3. **Detecção de BPM** — estima o andamento com librosa.
4. **Alinhamento letra-áudio** — em quatro passes: WhisperX transcreve livremente o áudio e mede timestamps acústicos reais; a transcrição é casada com a letra fornecida (`difflib.SequenceMatcher`) gerando *âncoras exatas*; palavras que o Whisper grafou diferente ("tá"/"está", "pra"/"para") são recuperadas por *âncoras fuzzy* (similaridade de caracteres com pareamento monotônico); trechos ainda sem âncora passam por um *segundo forced alignment* (wav2vec2) restrito à janela de áudio entre as âncoras vizinhas, com o texto que falta; o que restar é interpolado com peso proporcional ao número de sílabas.
5. **Metadados** — busca capa, ano e gênero em cascata, cada fonte preenchendo só o que ainda falta: tags embutidas no arquivo → MusicBrainz + Cover Art Archive → iTunes (capa 600x600, ano e gênero) → Deezer (capa 1000px) → Last.fm (capa e gênero; opcional: defina `LASTFM_API_KEY` com uma [chave gratuita](https://www.last.fm/api/account/create)) → Discogs (opcional: defina `DISCOGS_TOKEN` com um [token pessoal gratuito](https://www.discogs.com/settings/developers)). As fontes opcionais são puladas quando a variável correspondente não existe.
6. **Montagem** — extrai o pitch por sílaba (SwiftF0), separa sílabas (pyphen) e monta o arquivo `.txt` no formato UltraStar, com áudio convertido para `.ogg`.

## Stack

- **Interface**: Tauri v1 + React 18 + TypeScript + Vite — bilíngue (PT-BR/EN, detecta o idioma do sistema e pode ser trocada a qualquer momento no cabeçalho)
- **Núcleo de escrita do formato**: Rust (`rust-core`, crate `uskmaker_core`)
- **Pipeline de IA**: Python (sidecar), com WhisperX, Demucs, librosa, SwiftF0, pyphen
- **Arquitetura**: o frontend chama o Rust (Tauri), que invoca o sidecar Python; o Python exporta um JSON intermediário (`song_data.json`) e o Rust é quem escreve o `.txt` final a partir dele.

## Requisitos

- **Python 3.12** (testado com 3.12.10)
- **GPU NVIDIA com CUDA** — desenvolvido e testado numa RTX 4060 (8 GB VRAM). Roda em CPU, mas a separação vocal e o alinhamento ficam bem mais lentos.
- **Node.js** e **Rust** (toolchain estável), para a parte Tauri.
- **ffmpeg** no PATH do sistema, com suporte a `libvorbis` (para gerar `.ogg`).

## Instalação

### Opção A — Instalador (recomendado para uso)

1. Baixe o instalador (`USKMaker_x.y.z_x64-setup.exe`) na página de [Releases](https://github.com/walterfr/UltraStarKaraokeMaker/releases) e instale normalmente.
2. Instale o [Python 3.12](https://www.python.org/downloads/) (marque "Add python.exe to PATH").
3. Na pasta de instalação do USKMaker, execute **uma única vez** o script `setup-sidecar.ps1` (clique-direito → "Executar com PowerShell"). Ele detecta sua GPU, cria o ambiente de IA em `%LOCALAPPDATA%\USKMaker` e instala as dependências (≈ 10 min, requer internet).
4. Abra o USKMaker e use. Na primeira música, os modelos de IA são baixados automaticamente (~2 GB, só na primeira vez).

Requisitos: Windows 10/11, [ffmpeg](https://www.gyan.dev/ffmpeg/builds/) no PATH com `libvorbis`, e (opcional, mas muito recomendado) GPU NVIDIA — sem ela o processamento roda em CPU, ~10 min por música.

### Opção B — Ambiente de desenvolvimento

#### 1. Sidecar Python

```powershell
cd python-sidecar
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install torch torchaudio torchvision --index-url https://download.pytorch.org/whl/cu126
pip install -r requirements.txt
python -c "import torch; print('CUDA:', torch.cuda.is_available())"
```

Se `CUDA` retornar `False`, revise o driver/versão CUDA antes de continuar (o pipeline foi pensado para rodar em GPU).

> **Nota:** o WhisperX baixa modelos na primeira execução e pode pedir um token do Hugging Face. Configure-o via variável de ambiente `HF_TOKEN` ou pelo login do `huggingface-cli`. **Nunca** coloque o token dentro do código.

#### 2. App Tauri

```powershell
npm install
npm run tauri dev
```

## Uso

1. Escolha a fonte: link do YouTube ou arquivo de áudio local. No modo arquivo local, você pode opcionalmente baixar um videoclipe do YouTube **só para o fundo** (`#VIDEO`) — o áudio do pacote continua sendo o seu arquivo (útil para coleções ripadas de CD, com qualidade melhor que a do YouTube). Informe o link do clipe ou deixe em branco para busca automática por artista + título; se nenhum vídeo for encontrado, o pacote sai só com a capa.
2. Cole a letra — **uma linha por frase cantada**. Repita refrões por extenso, tantas vezes quantas forem cantados (não use "(2x)"); caso contrário, as repetições ficam sem notas.
3. Preencha título, artista e idioma. O BPM é opcional (detectado automaticamente se em branco).
4. Escolha a pasta de saída e gere — o pacote é criado numa subpasta `Artista - Título` (padrão das coleções UltraStar; aponte para a pasta `Songs` do jogo e pronto).

O pacote resultante contém o `.txt` UltraStar, o áudio `.ogg`, a capa `[CO].jpg` (quando encontrada) e, se solicitado, o vídeo `.mp4`. Pode ser carregado no UltraStar Deluxe ou no UltraStar Play.

5. (Opcional) Clique em **Revisar alinhamento** ao final — ou em "Revisar um pacote já gerado..." na tela inicial — para abrir o editor de revisão: ouça a música (mix completo ou só o vocal isolado, se os intermediários foram mantidos), arraste notas no tempo/pitch, ajuste durações, sílabas e quebras de frase, desloque o GAP global e salve para regenerar o `.txt`.

## Estado do projeto

Funcional de ponta a ponta pela interface gráfica. Todas as etapas de escopo estão concluídas:

- **Pipeline Python** — geração de pacotes jogáveis validada com músicas reais.
- **Núcleo em Rust** — escrita do `.txt` com saída idêntica à do protótipo Python, coberta por testes.
- **Integração Tauri + UI** — fluxo completo pela interface: checagem de ambiente na abertura (IA/ffmpeg/GPU), validação da letra em tempo real (detecta "(2x)", "[Refrão]", timestamps .lrc antes de gastar GPU), lista de etapas com estado e duração típica, botão de cancelar que encerra a árvore de processos, log técnico colapsado e resultado com capa, metadados e contagem de notas por confiança. Preferências e janela persistem entre sessões.
- **Metadados e vídeo** — capa/ano/gênero automáticos (fonte local e rede) e vídeo do YouTube opcional no pacote.
- **Distribuição** — instalador NSIS + setup assistido do ambiente de IA (`setup-sidecar.ps1`).
- **Revisão manual** — editor estilo Yass integrado: timeline com waveform, playback (mix ou só vocal), ajuste de notas por arrastar/teclado, quebras de frase, GAP global e undo/redo; salvar regrava o `song_data.json` e regenera o `.txt` pelo núcleo Rust.

## Licença

MIT. Veja o arquivo [LICENSE](LICENSE).

## Créditos

Apoia-se em: [WhisperX](https://github.com/m-bain/whisperx), [Demucs](https://github.com/facebookresearch/demucs), [librosa](https://librosa.org/), [SwiftF0](https://github.com/lars76/swift-f0), [yt-dlp](https://github.com/yt-dlp/yt-dlp), [Tauri](https://tauri.app/), [MusicBrainz](https://musicbrainz.org/), [Cover Art Archive](https://coverartarchive.org/), [iTunes Search API](https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/), [Deezer API](https://developers.deezer.com/api), [Last.fm](https://www.last.fm/api) e [Discogs](https://www.discogs.com/developers). Inspiração de fluxo: [UltraSinger](https://github.com/rakuri255/UltraSinger).

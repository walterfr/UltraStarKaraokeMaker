# USKMaker — UltraStar Karaoke Maker

Gerador de pacotes de karaokê **UltraStar** a partir de um link do YouTube ou de um arquivo de áudio local, com sincronização de letra, extração de pitch, detecção de BPM e metadados (capa, ano, gênero) automáticos.

O diferencial em relação a ferramentas como o UltraSinger é que o USKMaker parte da **letra que o usuário já fornece**. O problema passa a ser de *forced alignment* (alinhar uma letra conhecida ao áudio), não de transcrição do zero — o que resulta em sincronização bem mais precisa, especialmente em português.

Todo o processamento é **local**: não depende de APIs pagas nem envia áudio para serviços externos. As únicas consultas de rede são a bancos abertos e gratuitos (MusicBrainz e Cover Art Archive) para enriquecer metadados, e o download do YouTube quando essa é a fonte escolhida.

## Como funciona

O pipeline tem seis etapas:

1. **Obter áudio** — baixa do YouTube (via `yt-dlp`) ou normaliza um arquivo local para WAV. Opcionalmente baixa também o vídeo, para fundo animado no jogo.
2. **Separação vocal** — isola voz e instrumental com Demucs (`htdemucs`).
3. **Detecção de BPM** — estima o andamento com librosa.
4. **Alinhamento letra-áudio** — em quatro passes: WhisperX transcreve livremente o áudio e mede timestamps acústicos reais; a transcrição é casada com a letra fornecida (`difflib.SequenceMatcher`) gerando *âncoras exatas*; palavras que o Whisper grafou diferente ("tá"/"está", "pra"/"para") são recuperadas por *âncoras fuzzy* (similaridade de caracteres com pareamento monotônico); trechos ainda sem âncora passam por um *segundo forced alignment* (wav2vec2) restrito à janela de áudio entre as âncoras vizinhas, com o texto que falta; o que restar é interpolado com peso proporcional ao número de sílabas.
5. **Metadados** — busca capa, ano e gênero em cascata: primeiro as tags embutidas no arquivo, depois MusicBrainz + Cover Art Archive para o que faltar.
6. **Montagem** — extrai o pitch por sílaba (SwiftF0), separa sílabas (pyphen) e monta o arquivo `.txt` no formato UltraStar, com áudio convertido para `.ogg`.

## Stack

- **Interface**: Tauri v1 + React 18 + TypeScript + Vite
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

1. Escolha a fonte: link do YouTube ou arquivo de áudio local.
2. Cole a letra — **uma linha por frase cantada**. Repita refrões por extenso, tantas vezes quantas forem cantados (não use "(2x)"); caso contrário, as repetições ficam sem notas.
3. Preencha título, artista e idioma. O BPM é opcional (detectado automaticamente se em branco).
4. Escolha a pasta de saída e gere.

O pacote resultante contém o `.txt` UltraStar, o áudio `.ogg`, a capa `[CO].jpg` (quando encontrada) e, se solicitado, o vídeo `.mp4`. Pode ser carregado no UltraStar Deluxe ou no UltraStar Play.

## Estado do projeto

Funcional de ponta a ponta pela interface gráfica. As quatro etapas de escopo estão concluídas:

- **Pipeline Python** — geração de pacotes jogáveis validada com músicas reais.
- **Núcleo em Rust** — escrita do `.txt` com saída idêntica à do protótipo Python, coberta por testes.
- **Integração Tauri + UI** — fluxo completo pela interface, com log ao vivo e barra de progresso.
- **Metadados e vídeo** — capa/ano/gênero automáticos (fonte local e rede) e vídeo do YouTube opcional no pacote.

### Próximos passos possíveis

- Empacotamento para distribuição (PyInstaller + `externalBin` do Tauri).
- Tela de revisão manual do alinhamento (estilo Yass).

## Licença

MIT. Veja o arquivo [LICENSE](LICENSE).

## Créditos

Apoia-se em: [WhisperX](https://github.com/m-bain/whisperx), [Demucs](https://github.com/facebookresearch/demucs), [librosa](https://librosa.org/), [SwiftF0](https://github.com/lars76/swift-f0), [yt-dlp](https://github.com/yt-dlp/yt-dlp), [Tauri](https://tauri.app/), [MusicBrainz](https://musicbrainz.org/) e [Cover Art Archive](https://coverartarchive.org/). Inspiração de fluxo: [UltraSinger](https://github.com/rakuri255/UltraSinger).

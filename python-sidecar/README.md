# USKMaker — `python-sidecar`

Pipeline local de IA para geração e revisão de pacotes UltraStar, invocada pelo aplicativo Tauri (via `server.py` persistente em lote ou `main.py` via CLI).

## Arquitetura do Pipeline (`pipeline/`)

| Módulo | Função |
|---|---|
| `download.py` | Download de áudio/vídeo do YouTube (`yt-dlp`) e normalização de arquivos locais para WAV via `ffmpeg`. |
| `separate.py` | Separação vocal com Demucs (`htdemucs`) ou Mel-Band RoFormer (`audio-separator`), mais isolamento de voz principal (resgate 4b) e backing vocals. |
| `beatgrid.py` | Estimativa de BPM (`librosa`, normalizado na grade `[200, 400)`) e conversão tempo ↔ beats UltraStar. |
| `key_detect.py` | Detecção de tom musical (`C major`, `A minor`, etc.) por correlação de croma CQT contra os 24 perfis de Krumhansl-Kessler. |
| `ctc_align.py` | Alinhador padrão de produção (`--aligner ctc`): forced alignment global com `torchaudio.pipelines.MMS_FA` (ou `wav2vec2` dedicado por idioma) + âncoras `.lrc`. |
| `align.py` | Alinhador alternativo e fallback automático (`--aligner whisper`): transcrição WhisperX + ancoragem exata/fuzzy + realinhamento por linha. |
| `pitch.py` | Extração de F0 por sílaba via `SwiftF0` com gate acústico RMS de silêncio e dobra de oitava. |
| `repitch.py` | Re-cálculo isolado de pitches na tela de Revisão preservando tempos e sílabas existentes. |
| `syllabify.py` | Separação silábica (`pyphen` + regras fonéticas para português, inglês, espanhol, sueco e outros idiomas). |
| `build_song.py` | Montagem das notas, divisão de melismas e silêncios internos (`~`), detecção de Rap (`R`/`G`), marcação de notas douradas (`*`) e exportação do `song_data.json`. |
| `metadata.py` | Busca em cascata de capa, ano, gênero e fundo (`#BACKGROUND`): tags locais → MusicBrainz/CAA → iTunes → Deezer → Last.fm → Discogs / fanart.tv. |
| `video_export.py` | Renderização de vídeo MP4 com letra karaokê ASS (`libass`) sincronizada por sílaba. |

## Setup Manual (Desenvolvimento)

```powershell
cd python-sidecar
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install torch torchaudio torchvision --index-url https://download.pytorch.org/whl/cu126
pip install -r requirements.txt
```

## Comandos Principais

```powershell
# CLI direta do pipeline
python main.py --help

# Servidor persistente de jobs (usado pelo Tauri)
python server.py

# Suite de testes unitários (sem rede e sem GPU)
.\venv\Scripts\pytest.exe tests
```

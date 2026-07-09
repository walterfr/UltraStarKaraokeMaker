# USKMaker — Fase 0 (python-sidecar)

Esqueleto de prova de conceito da pipeline completa, **sem Tauri ainda**.
Objetivo: validar com 2-3 músicas de teste (de preferência letras que você
já conhece de cor) se o pipeline `download → separação vocal → alinhamento
→ pitch → .txt UltraStar` produz um resultado utilizável antes de investir
tempo construindo a UI em Rust/React.

## Setup (Windows, RTX 4060)

```powershell
cd "X:\Android Projetos\USKMaker\python-sidecar"
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install --upgrade pip

# Torch com CUDA 12.1 (compatível com RTX 4060)
pip install torch==2.1.2 torchaudio==2.1.2 --index-url https://download.pytorch.org/whl/cu121

pip install -r requirements.txt
```

Confirme que a GPU foi reconhecida antes de seguir:

```powershell
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

Se retornar `False`, revise a versão do driver NVIDIA e do CUDA Toolkit
antes de continuar — nenhuma etapa da pipeline vai funcionar bem em CPU
para testes iterativos (Demucs + WhisperX ficam **muito** lentos sem GPU).

Você também vai precisar do **ffmpeg** instalado e no PATH do sistema
(usado pelo yt-dlp e pelo download.py).

## Testando módulo por módulo (recomendado antes do pipeline completo)

Cada arquivo em `pipeline/` roda isolado via `python -m pipeline.<nome>`.
Teste nessa ordem, revisando a saída de cada etapa manualmente antes de ir
para a próxima:

```powershell
# 1. Baixar áudio de teste
python -m pipeline.download --url "https://youtu.be/XXXXX" --out ./work/raw

# 2. Separar vocal
python -m pipeline.separate --input ./work/raw/NOME.wav --out ./work/stems

# 3. Detectar BPM (ouça a música com metrônomo pra conferir)
python -m pipeline.beatgrid --input ./work/stems/htdemucs/NOME/no_vocals.wav

# 4. Alinhar a letra (crie um .txt simples com a letra, uma linha por frase)
python -m pipeline.align --vocals ./work/stems/htdemucs/NOME/vocals.wav \
    --lyrics ./minha_letra.txt --language pt --out ./work/align.json

# 5. Teste de pitch num trecho específico (use os timestamps do align.json)
python -m pipeline.pitch --vocals ./work/stems/htdemucs/NOME/vocals.wav \
    --start 12.5 --end 13.1
```

## Rodando o pipeline completo

```powershell
python main.py `
    --url "https://youtu.be/XXXXX" `
    --lyrics "./minha_letra.txt" `
    --title "Nome da Música" `
    --artist "Nome do Artista" `
    --language pt `
    --out "./output_test"
```

Isso gera, dentro de `./output_test/`:
- `Artista - Título.txt` (formato UltraStar)
- `Artista - Título.wav` (áudio — ainda não convertido pra mp3 nesta fase)
- `_work/` com todos os arquivos intermediários (stems, alinhamento etc.) —
  útil para debugar quando algo sair errado.

## O que ainda é propositalmente simplificado nesta Fase 0

Estes pontos estão marcados com `TODO` nos arquivos correspondentes:

1. **Mapeamento letra↔segmento no `align.py`**: a distribuição proporcional
   de palavras entre segmentos do Whisper é ingênua. Funciona bem quando a
   letra fornecida é fiel ao que é cantado; quebra em refrões muito
   repetidos ou intros longas sem letra. É o primeiro candidato a melhorar
   depois de rodar os primeiros testes reais.
2. **Marcação de quebra de frase (`phrase_breaks_after_index`)**: ainda não
   está sendo propagada do `align.py` até o `build_song.py`. Sem isso, o
   `.txt` gerado sai sem os marcadores `-` de fim de linha — o UltraStar
   ainda carrega, mas a letra aparece tudo "grudado" na tela.
3. **Elisões e sílabas estendidas**: o `syllabify.py` faz hifenização
   ortográfica simples, não separação silábica cantada. Vogais estendidas
   (`"amoooor"`) e elisões (`"d'eu"`) vão precisar de ajuste manual até
   existir a tela de revisão (Fase 4 do roadmap).
4. **Empacotamento final**: não busca capa automaticamente, não converte
   pra mp3, não copia vídeo do YouTube. Isso é a Fase 3.
5. **API real do `swift-f0`**: o import em `pitch.py` é ilustrativo —
   confirme o nome exato do pacote/classe na documentação da lib antes de
   rodar (pode ter mudado desde a escrita deste esqueleto).

## Depois de validar a Fase 0

Se os testes com 2-3 músicas mostrarem que a qualidade é aceitável (letra
sincronizada de forma razoável, pitch coerente com a melodia), o próximo
passo é a Fase 1 do roadmap: reescrever `ultrastar_writer.py` em Rust
(`ultrastar_writer.rs`) e criar o `sidecar.rs` que chama este script Python
como subprocesso a partir do Tauri.

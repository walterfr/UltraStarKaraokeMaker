"""
main.py
USKMaker - pipeline completa: download/áudio local -> separação vocal ->
BPM -> alinhamento letra<->áudio -> pitch -> metadados -> .txt UltraStar.

USO:
    python main.py \
        --url "https://youtu.be/XXXXX" \
        --lyrics "./minha_letra.txt" \
        --title "Nome da Música" \
        --artist "Nome do Artista" \
        --language pt \
        --out "./output_test"

    (ou --file "C:/caminho/musica.mp3" no lugar de --url)
    (adicione --with-video para baixar e incluir o vídeo do YouTube no pacote)

REQUISITOS: rodar `pip install -r requirements.txt` num venv antes,
com torch+CUDA instalado.

HISTÓRICO DE DECISÕES E BUGS (resumo - detalhes nos módulos de cada etapa):
- FASE 1: exporta song_data.json (intermediário) que o rust-core consome.
- FASE 2: bug de sincronia via Tauri (conflito de I/O no pipe do Windows)
  corrigido no lado Rust; log em disco (pipeline_debug.log) + line_buffering
  mantidos como diagnóstico permanente; align.py reescrito para
  âncora+interpolação.
- Checagem de cobertura da letra: avisa quando um refrão repetido foi
  escrito só uma vez (erro comum de letras com "(2x)"/"(4x)").
- FASE 3: metadados (capa/ano/gênero) em cascata (arquivo -> MusicBrainz/CAA);
  e (complemento) suporte opcional a baixar o VÍDEO do YouTube para o pacote.
- Etapa 4 (30/09/2026): alinhador padrão passa a ser o CTC global da letra
  inteira (pipeline/ctc_align.py); o caminho do Whisper vira fallback.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path

import soundfile as sf
from rich.console import Console

from pipeline.align import (
    align_lyrics_to_audio,
    alignment_stats,
    count_singer_tagged_lines,
)
from pipeline.beatgrid import detect_bpm
from pipeline.build_song import build_song
from pipeline.download import download_background_video, get_source_audio
from pipeline.filenames import sanitize_filename
from pipeline.i18n import SUPPORTED_LANGS, set_ui_lang, t
from pipeline.metadata import fetch_metadata
from pipeline.proc_utils import YT_COOKIE_BROWSERS, ensure_ffmpeg_on_path, ffmpeg_exe, run_subprocess
from pipeline.separate import isolate_backing_vocals, isolate_lead_vocal, separate_vocals
from pipeline.video_export import export_karaoke_video, ffmpeg_has_libass

# Quando o stdout/stderr do Python não está conectado a um terminal real (é
# o caso ao rodar via Tauri), o Python usa buffer em bloco por padrão.
# Forçar line_buffering garante que cada linha seja enviada imediatamente.
#
# encoding="utf-8": sem isso, o stdout de um pipe no Windows fica em cp1252 e
# um print() de saída ecoada de subprocesso (yt-dlp/ffmpeg com título/tag
# CJK/emoji) estoura UnicodeEncodeError. O caminho do app (server.py) já
# redireciona para um arquivo utf-8; isto cobre o caminho standalone (CLI/dev).
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)

console = Console()

# Acima desta fração de palavras ESTIMADAS, o alinhamento não achou onde
# ancorar e o pacote sai fora de sincronia - deixa de ser "vale revisar" e
# vira "provavelmente não presta".
#
# O corte NÃO é chute. Medido na biblioteca gold (19 músicas, harness):
#     mediana de interpoladas ........  1,9%
#     pior caso LEGÍTIMO ............. 16,8%  (Joan Jett - I Love Rock-n-Roll)
#     caso patológico ................ 89,1%  (Supergrass - Alright, issue #6)
#     entre 20% e 50% ................ NADA
# O vão é vazio: música difícil e alinhamento quebrado não se misturam. 50%
# fica no meio do vazio, longe dos dois lados - então não há falso positivo
# plausível, e mesmo assim há folga de sobra pro caso patológico.
#
# A UI usa o mesmo corte sobre notes_estimated/notes_total (App.tsx).
ALIGNMENT_FAILED_PCT = 50.0

# Alinhador da Etapa 4: "ctc" (CTC global da letra inteira, pipeline/ctc_align.py)
# ou "whisper" (transcrição livre + âncoras, pipeline/align.py - o de antes).
# O "ctc" cai sozinho no "whisper" quando a letra não cabe no vocabulário dele.
# MEDIDO (30/09/2026, mesmas 8 músicas e stems, 5 en + 3 sv): palavras a <= 1 s
# do chart feito à mão 0,867 -> 0,966; erro mediano de início 95 -> 49 ms.
DEFAULT_ALIGNER = "ctc"
ALIGNERS = ("ctc", "whisper")

# Limiares do caminho CTC, sobre a fração de palavras em linha de confiança
# baixa (ctc_align.low_confidence_frac) - o análogo do interp_frac do Whisper.
# Acima disto tenta a voz principal isolada (4b). MEDIDO (30/09/2026, 16
# músicas, 2 amostras): o stem isolado é ARRISCADO no CTC - numa música
# "Skönheten Och Odjuret" ele derrubou o acerto de 1,00 pra 0,00 - mas a regra
# "ganha quem tiver menos palavras em linha de confiança baixa" rejeitou todos
# os stems catastróficos; saldo levemente positivo (+0,11 Scar Tissue, +0,04
# Jag Ljuger Så Bra, -0,11 Kylie In Your Eyes). Com 0,10 o resgate (~3 min de
# GPU) disparava em 11/16 músicas; com 0,20 em 7/16, com os mesmos ganhos.
CTC_RESCUE_LOW_FRAC = 0.20
CTC_WARN_PCT = 10.0          # acima disto avisa pra conferir as linhas marcadas

# Acima disto o CTC é descartado e a Etapa 4 segue pelo caminho do Whisper
# (com os resgates dele). MEDIDO (01/10/2026, 24 músicas, 3 amostras): ordenadas
# por esta fração, há um vão VAZIO entre 0,24 e 0,43. Acima dele (7 músicas) o
# CTC perdeu feio em 5 (Heart of Glass 0,67 -> 0,45 com erro mediano de 20 s,
# Super Bass 0,68 -> 0,44) e empatou em 2; abaixo (17) empatou ou ganhou, às
# vezes muito (Dansa I Neon 0,41 -> 1,00). Palavras a <= 1 s do chart feito à
# mão, mediana das 24: Whisper 0,867, CTC sempre 0,919, CTC + este fallback
# 0,936, e a pior música sobe de 0,44 pra 0,49. Qualquer valor dentro do vão dá
# as mesmas escolhas - 0,35 fica no meio dele. (O limiar foi escolhido depois
# de ver a 3ª amostra; as duas primeiras mostram o mesmo vão sozinhas.)
CTC_FALLBACK_LOW_FRAC = 0.35

# Piso de "word-recall" do Whisper: a fração da letra que o Whisper reconheceu
# de verdade (âncoras exatas + fuzzy, ANTES do realinhamento). Abaixo disto, o
# Whisper não entendeu o suficiente da música, e as âncoras que ele COLOCOU têm
# boa chance de estar nas palavras erradas.
#
# Por que precisa existir SEPARADO do interp_frac (medido no lote n=60, 17/07):
# há um modo de falha "ancorado com CONFIANÇA mas ERRADO" que o interp_frac não
# vê. Ex.: "Paul McCartney - No More Lonely Nights" alinhou com interp=0,01
# (quase tudo ancorado) mas 67 s fora do lugar - o Whisper ouviu outra coisa e
# ancorou nela. O interp_frac mede "quanto NÃO ancorou"; o word-recall mede
# "quão pouco do que ancorou veio da letra de verdade". São buracos diferentes.
#
# Corte 0,60, escolhido pela CURVA medida (n=60), não arredondando no olho.
# As 5 falhas reais têm wrecall 0,16-0,589; as 51 boas, mediana 0,89. A curva:
#     <0,58: pega 3/5 reais, 1 falso-positivo
#     <0,60: pega 5/5 reais, 2 falsos-positivos   <- patamar: 0,60 fica logo
#     <0,65: pega 5/5 reais, 3 falsos-positivos       acima do pior real (0,589)
#     <0,70: pega 5/5 reais, 5 falsos-positivos
# 0,60 é o ponto onde pega TODAS as falhas com o mínimo de falso positivo.
# O viés é DE PROPÓSITO pra capturar: o aviso é suave ("vale conferir"), então
# um falso positivo custa um olhar do usuário, mas um falso negativo deixa um
# pacote quebrado passar calado. Os 2 falsos positivos são vocais gritados/
# rápidos (ex.: System of a Down - "Chop Suey!", wrecall 0,48 mas alinhamento
# ótimo) - o realinhamento salva, mas o word-recall não sabe disso.
# (Os 3 casos de wrecall ALTO que pareciam falha eram mismatch de GAP
# gold/áudio, não erro do pipeline - não disparam, corretamente.)
WHISPER_RECALL_FLOOR = 0.60

# Teto de interpolação abaixo do qual um word-recall baixo deixa de ser alarme
# e vira informação - DESDE QUE a letra sincronizada tenha entrado de verdade.
#
# POR QUE: o aviso de recall mede só o que o Whisper reconheceu SOZINHO
# (anchor + fuzzy). Ele não enxerga o realinhamento nem o .lrc - a limitação
# que o comentário do WHISPER_RECALL_FLOOR acima já registra ("o realinhamento
# salva, mas o word-recall não sabe disso", caso Chop Suey).
#
# MEDIDO (2026-09-06, três músicas reais do usuário, todas com recall parecido):
#   Peter Murphy - Cuts You Up   recall 55%, .lrc RECUSADO  -> 38% interpoladas
#   Killing Joke - Sanity        recall 53%, .lrc aceito    ->  0% interpoladas
#   Ministry - Revenge           recall 59%, .lrc aceito    ->  0,3% interpoladas
#
# Ou seja: o recall quase não previu a qualidade; o .lrc caber na gravação
# previu tudo. As duas boas levaram o mesmo susto vermelho da quebrada, o que
# treina o usuário a ignorar o aviso - e aí ele não serve pra nada quando
# importa. `by_source["lrc"] > 0` só acontece quando a letra sincronizada
# passou na checagem de duração E semeou inícios de linha de fato.
LRC_RESCUE_INTERP_PCT = 5.0

_debug_log_path: Path | None = None


def debug_log(message: str) -> None:
    """Grava uma linha de log em disco, com timestamp e flush imediato."""
    if _debug_log_path is None:
        return
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    with open(_debug_log_path, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")
        f.flush()


def resolve_device(requested: str) -> str:
    """
    Decide o device REAL de processamento. "cpu" é sempre respeitado; "cuda"
    ou "auto" só viram "cuda" se o torch tiver CUDA de fato disponível - caso
    contrário caem para "cpu".

    Corrige o erro reportado em máquinas sem GPU NVIDIA (ex.: Intel Iris Xe):
    o Demucs/whisperx eram chamados com "cuda" mesmo sem CUDA, estourando
    "AssertionError: Torch not compiled with CUDA enabled". A interface já
    avisa que o processamento roda na CPU; aqui garantimos que o pipeline
    concorde com isso, em vez de assumir GPU cegamente.

    SEGUNDO CASO (achado por relato de usuário, GTX 750 Ti, 05/08/2026):
    `torch.cuda.is_available()` só confirma que HÁ uma GPU NVIDIA com driver
    - não que os KERNELS compilados no torch instalado cobrem a capacidade de
    computação dela. GPU antiga (ex.: Maxwell, sm_50) passa nesse teste e só
    quebra depois, dentro do subprocess do Demucs, com "CUDA error: no kernel
    image is available for execution on the device" - sem fallback, sem
    log claro pro usuário. `torch.cuda.get_arch_list()` é a mesma lista que o
    próprio torch usa pra emitir o aviso "supports CUDA capabilities sm_XX...";
    comparamos a capacidade REAL da placa contra ela antes de decidir "cuda".
    """
    if requested == "cpu":
        return "cpu"
    try:
        import torch
        if torch.cuda.is_available():
            major, minor = torch.cuda.get_device_capability(0)
            # Pega a menor arquitetura que este torch suporta (ex: 61 de 'sm_61')
            archs = [int(a.replace("sm_", "")) for a in torch.cuda.get_arch_list() if a.startswith("sm_")]
            min_arch = min(archs) if archs else 0
            sm_val = int(f"{major}{minor}")

            # Se a placa é mais nova ou igual à mais antiga suportada (sm_val >= min_arch),
            # o torch consegue rodar (usando PTX JIT se a placa não estiver explícita na lista, ex: sm_89).
            # O erro "no kernel image" só ocorre em placas MAIS ANTIGAS que o min_arch (ex: sm_50 < sm_61).
            if sm_val >= min_arch:
                return "cuda"
            
            print(t("main.gpu_too_old", cap=f"{major}{minor}", min_arch=min_arch,
                    archs=torch.cuda.get_arch_list()))
    except Exception:
        pass
    return "cpu"


def resolve_whisper_device(device: str) -> str:
    """
    Device da TRANSCRIÇÃO (Whisper), que pode ser diferente do resto.

    O Whisper do whisperx roda no faster-whisper, que usa o CTranslate2 - e não
    o torch. Com GPU AMD (torch ROCm), `torch.cuda.is_available()` é True e o
    resolve_device devolve "cuda" (Demucs e o alinhamento wav2vec2 rodam na GPU
    via HIP), mas o CTranslate2 do PyPI só conhece CUDA de verdade: carregar o
    Whisper com "cuda" quebraria. Quem decide é o próprio CTranslate2: se ele
    enxerga GPU, usa; senão, a transcrição vai para a CPU e o resto continua na
    GPU. NVIDIA: nada muda (o CTranslate2 vê a placa). Um build ROCm do
    CTranslate2 também passa a ser usado sozinho, sem código específico de AMD.
    """
    if device != "cuda":
        return "cpu"
    _prefer_safe_ct2_allocator_on_hip()
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _prefer_safe_ct2_allocator_on_hip() -> None:
    """
    Com build ROCm do CTranslate2 (GPU AMD), usa o alocador "cub_caching".

    O alocador padrão dele na GPU usa hipMallocAsync, que em placas AMD de
    consumo CORROMPE buffers em silêncio: o Whisper roda, mas perde de 30% a
    95% do texto e cada execução do mesmo áudio sai diferente (às vezes com
    "Memory access fault"). Relatado em CTranslate2 #2090 (RDNA2 e RDNA3.5) e
    #2012; medido aqui numa RX 7800 XT (RDNA3, 29/09/2026): WER 15-95% e
    falhas com o padrão, 11-13% estável com cub_caching (CPU: 10%), 13 s em
    vez de 60-80 s na CPU. Só vale com torch ROCm (HIP); NVIDIA não muda, e
    quem definiu CT2_CUDA_ALLOCATOR por conta própria é respeitado. Precisa
    rodar ANTES do primeiro modelo carregado na GPU.
    """
    try:
        import torch
        if getattr(torch.version, "hip", None):
            os.environ.setdefault("CT2_CUDA_ALLOCATOR", "cub_caching")
    except Exception:
        pass


# Modelo do Whisper usado no alinhamento.
#
# POR QUE ISTO VIROU UMA OPÇÃO (relato real, 02/09/2026 - "Camouflage - The
# Great Commandment"): o tamanho estava FIXO em "medium", como default de
# parâmetro do align_lyrics_to_audio, e não era exposto em lugar nenhum -
# nem CLI, nem servidor, nem interface. Toda música do mundo usava "medium".
#
# Naquele caso o Whisper reconheceu 50% das palavras; abaixo disso as âncoras
# começam a cair na sílaba errada e o que está entre elas é esticado pra caber.
# O log AVISOU ("reconhecimento da letra ficou baixo"), a pipeline tentou dois
# resgates e os dois pioraram - mas não havia nenhuma alavanca pra puxar.
# Música densa, voz processada, banda alemã cantando em inglês: é exatamente o
# terreno onde um modelo maior ouve mais palavras.
#
# O "large-v3" pede ~3 GB de VRAM em float16 contra ~1,6 GB do "medium" - o
# projeto nasceu numa RTX 4060 de 8 GB, onde "medium" era a escolha prudente,
# mas a folga existe em qualquer placa moderna.
WHISPER_MODEL_DEFAULT = "medium"
WHISPER_MODEL_BEST = "large-v3"

# VRAM (em GB) a partir da qual o "auto" escolhe o modelo grande. 6 GB é
# deliberadamente folgado: o large-v3 usa ~3 GB, e a margem cobre o
# fragmento que o torch já mantém reservado. Abaixo disso, "medium" - melhor
# um alinhamento razoável que um estouro de memória no meio da música.
WHISPER_LARGE_MIN_VRAM_GB = 6.0


def resolve_whisper_model(requested: str, device: str) -> str:
    """
    Traduz a escolha do usuário no nome real do modelo.

    "auto" (padrão) olha a VRAM: placa com folga usa o modelo grande, o resto
    segue no "medium" de antes. Assim quem tem GPU boa ganha precisão sem
    pedir nada, e nenhuma máquina modesta passa a estourar memória - a
    correção não pode piorar quem já estava funcionando.

    Na CPU é SEMPRE "medium": o large-v3 na CPU levaria dezenas de minutos por
    música, o que na prática é o mesmo que travar.
    """
    if requested and requested not in ("auto", ""):
        return requested
    if device != "cuda":
        return WHISPER_MODEL_DEFAULT
    try:
        import torch
        # GPU AMD (torch ROCm/HIP): "auto" fica no medium. MEDIDO (29/09/2026,
        # RX 7800 XT, CTranslate2 ROCm + cub_caching), 3 músicas:
        #   - Arvingarna "Eloise" (sueco), contra o chart do SingStar: large-v3
        #     deixou 17 âncoras exatas e 54% das palavras a <=0,3 s; medium
        #     deu 140 âncoras e 78% (notas casadas 58% -> 78%, contorno de
        #     pitch 0,67 -> 0,87).
        #   - Mauro Scocco "Till dom ensamma" (sueco): large-v3 alucinou um
        #     crédito de legenda de TV ("textning stina hedin ...") e variou
        #     entre execuções (WER 35-44%); medium 22%.
        #   - Rick Astley (inglês): medium mais rápido e melhor (2,4% x 5,0%
        #     de palavras interpoladas).
        # NVIDIA continua na regra de VRAM abaixo (medida lá, noutro backend).
        if getattr(getattr(torch, "version", None), "hip", None):
            return WHISPER_MODEL_DEFAULT
        vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        if vram_gb >= WHISPER_LARGE_MIN_VRAM_GB:
            return WHISPER_MODEL_BEST
    except Exception:
        pass
    return WHISPER_MODEL_DEFAULT


def get_audio_duration_seconds(path: Path) -> float:
    """Lê só o cabeçalho do áudio (rápido, não carrega o arquivo inteiro)."""
    info = sf.info(str(path))
    return info.frames / info.samplerate


# Vorbis -q:a (0-10, maior=melhor) -> libmp3lame -q:a (0-9, MENOR=melhor,
# escala invertida). Só 2 níveis de qualidade existem hoje na pipeline
# (6=pacote principal/stems ~192kbps, 8=export YARG ~256kbps) - mapeados
# pela tabela de bitrate VBR do LAME, sem inventar fórmula pra caso que não
# existe: q6->V2 (~190kbps), q8->V0 (~245kbps, teto do VBR do mp3).
_VORBIS_TO_MP3_QUALITY = {6: 2, 8: 0}
_MP3_QUALITY_FALLBACK = 2  # V2, se algum dia surgir um 3º nível não mapeado


def convert_audio(source_wav: Path, dest: Path, audio_format: str = "ogg",
                   quality: int = 6, pitch_semitones: int = 0) -> None:
    """
    Converte um .wav para .ogg (Vorbis) ou .mp3 (LAME) via ffmpeg, conforme
    audio_format. quality é a escala do VORBIS (0-10, maior=melhor); quando
    audio_format="mp3" ela é convertida via _VORBIS_TO_MP3_QUALITY. Ambos
    UltraStar Deluxe e Play leem os dois formatos nativamente.

    pitch_semitones != 0 transpõe o áudio N semitons PRESERVANDO o tempo, via
    filtro rubberband (phase-vocoder de boa qualidade). Usado no "tom fixo":
    o pacote sai num tom diferente do original. Shift grande (>±4) degrada.
    """
    cmd = [ffmpeg_exe(), "-y", "-i", str(source_wav)]
    if pitch_semitones:
        # pitch é fator de escala; 2^(N/12) = N semitons na escala temperada.
        ratio = 2 ** (pitch_semitones / 12.0)
        cmd += ["-af", f"rubberband=pitch={ratio:.6f}"]
    if audio_format == "mp3":
        mp3_q = _VORBIS_TO_MP3_QUALITY.get(quality, _MP3_QUALITY_FALLBACK)
        cmd += ["-c:a", "libmp3lame", "-q:a", str(mp3_q)]
    else:
        cmd += ["-c:a", "libvorbis", "-q:a", str(quality)]
    cmd += [str(dest)]
    run_subprocess(cmd)


def mix_backing_into_instrumental(instrumental: Path, backing: Path, dest: Path) -> None:
    """
    Soma as vozes de apoio de volta ao instrumental, no nível natural delas.

    `normalize=0` é o detalhe que importa: por padrão o filtro amix divide
    cada entrada pelo número de entradas, o que baixaria a música inteira
    ~6 dB sem ninguém pedir. Medido em teste antes de entrar aqui: com um
    stem de apoio SILENCIOSO, o volume médio da saída fica idêntico ao do
    instrumental sozinho - prova de que nada foi atenuado no caminho.
    """
    cmd = [
        ffmpeg_exe(), "-y",
        "-i", str(instrumental),
        "-i", str(backing),
        "-filter_complex",
        "[0:a][1:a]amix=inputs=2:duration=longest:normalize=0[out]",
        "-map", "[out]",
        str(dest),
    ]
    run_subprocess(cmd)


def _make_romanize_converter(language: str):
    """
    Devolve uma função texto->texto pro idioma, ou None se não suportado.
    Cria qualquer instância COM ESTADO (ex.: kakasi carrega dicionário) UMA
    VEZ aqui fora, não a cada nota - recriar por nota seria caro à toa.

    Idiomas de fora (hebraico/persa): script sem vogal marcada no uso comum -
    romanizar sem elas dá só um esqueleto de consoantes, não a pronúncia real.
    Baixa demanda medida (3-4 charts na comunidade) não justifica o risco de
    qualidade. Ver issue de romanização (30/07/2026).
    """
    if language == "ja":
        from pykakasi import kakasi
        kks = kakasi()
        return lambda t: "".join(item["hepburn"] for item in kks.convert(t))
    if language == "zh":
        from pypinyin import pinyin, Style
        return lambda t: " ".join(p[0] for p in pinyin(t, style=Style.TONE))
    if language == "ko":
        from korean_romanizer.romanizer import Romanizer
        return lambda t: Romanizer(t).romanize()
    if language in ("ru", "uk"):
        from transliterate import translit
        return lambda t: translit(t, language, reversed=True)
    if language == "hi":
        from indic_transliteration import sanscript
        return lambda t: sanscript.transliterate(t, sanscript.DEVANAGARI, sanscript.IAST)
    if language == "el":
        from unidecode import unidecode
        return unidecode
    return None


def romanize_notes(notes, language: str) -> None:
    """
    Reescreve o texto de cada nota em alfabeto latino, no sistema padrão do
    idioma: japonês (Hepburn), chinês (Pinyin com tom), coreano (Revised
    Romanization), russo/ucraniano (transliteração cirílico->latino), hindi
    (IAST). Deixa quem não lê o script original cantar. Texto já latino
    passa direto; idioma sem conversor (ver _make_romanize_converter) não
    faz nada. Import LAZY por idioma - só paga o custo de quem usar.
    Preserva o espaço à direita, que no UltraStar marca fim de palavra.
    """
    converter = _make_romanize_converter(language)
    if converter is None:
        return
    for n in notes:
        raw = n.text
        core = raw.strip()
        if not core:
            continue
        romanized = converter(core)
        if romanized:
            n.text = romanized + (" " if raw.endswith(" ") else "")


def write_song_ini(dest: Path, name: str, artist: str,
                   length_ms: int | None = None, year: int | None = None,
                   genre: str | None = None,
                   video_start_time: int | None = None) -> None:
    """
    Escreve o song.ini que o YARG lê (seção [song]). Todos os campos são
    opcionais na spec (GuitarGame_ChartFormats), então só emitimos os que
    temos. charter=USKMaker identifica a origem. song_length é em ms e é
    "metadata only" para o YARG (ele mede a duração do áudio de verdade).
    """
    lines = ["[song]", f"name={name}", f"artist={artist}", "charter=USKMaker"]
    if length_ms is not None:
        lines.append(f"song_length={length_ms}")
    if year:
        lines.append(f"year={year}")
    if genre:
        lines.append(f"genre={genre}")
    if video_start_time is not None:
        lines.append(f"video_start_time={video_start_time}")
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_yarg(yarg_dir: Path, txt_path: Path, stems, source_audio: Path,
                cover_path: Path | None, video_path: Path | None,
                name: str, artist: str, year: int | None, genre: str | None,
                transpose: int = 0, audio_format: str = "ogg",
                video_gap: float | None = None) -> None:
    """
    Monta a pasta no layout do YARG. O YARG lê o UltraStar .txt NATIVAMENTE
    (ChartFormat.UltraStar) - não há conversão de formato, só empacotamento.
    O áudio vem dos STEMS (nomes reservados song/vocals), não da tag #MP3 do
    .txt: song.<ext> = instrumental (Demucs), vocals.<ext> = vocal. Ambos
    respeitam a transposição, para casar com as notas transpostas do
    notes.txt. Quality 8 (~256kbps/V0) é o recomendado pela spec (o pacote
    UltraStar principal usa quality 6).
    """
    yarg_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(txt_path, yarg_dir / "notes.txt")
    convert_audio(stems.instrumental, yarg_dir / f"song.{audio_format}",
                  audio_format=audio_format, quality=8, pitch_semitones=transpose)
    convert_audio(stems.vocals, yarg_dir / f"vocals.{audio_format}",
                  audio_format=audio_format, quality=8, pitch_semitones=transpose)
    if cover_path and cover_path.exists():
        shutil.copy(cover_path, yarg_dir / "album.jpg")
    if video_path and video_path.exists():
        shutil.copy(video_path, yarg_dir / f"video{video_path.suffix.lower() or '.mp4'}")
    try:
        length_ms = int(sf.info(str(source_audio)).duration * 1000)
    except Exception:
        length_ms = None
    video_start_time = round(-video_gap * 1000) if video_gap is not None else None
    write_song_ini(yarg_dir / "song.ini", name, artist, length_ms, year, genre,
                   video_start_time=video_start_time)


def _meta_source_label(source: str) -> str:
    """
    metadata.source ("arquivo+MusicBrainz+iTunes", "nenhuma"...) pronto para o
    log no idioma da interface. "arquivo" e "nenhuma" são VALORES internos
    (o próprio metadata.py compara com eles) - por isso a tradução acontece só
    aqui, na hora de mostrar, sem mexer no dado. Nomes de serviço passam
    direto (29/09/2026).
    """
    words = {"arquivo": t("main.meta_source_file"), "nenhuma": t("main.meta_source_none")}
    return "+".join(words.get(part, part) for part in (source or "").split("+"))


def split_duet_artists(artist: str) -> tuple[str | None, str | None]:
    """
    Tenta separar o campo #ARTIST em dois nomes para os headers #P1/#P2 do
    dueto (ex.: "Elton John & Kiki Dee" -> ("Elton John", "Kiki Dee")). Cobre
    os separadores comuns dos duetos reais: "&", "feat.", "ft.", "x", ",", "/".
    Se não achar dois nomes, devolve (None, None) e o writer usa "P1"/"P2".
    """
    for sep in (" & ", " feat. ", " feat ", " ft. ", " ft ", " x ", " X ",
                " vs. ", " vs ", " and ", " And ", " e ", ", ", " / ", "/"):
        if sep in artist:
            a, _, b = artist.partition(sep)
            a, b = a.strip(), b.strip()
            if a and b:
                return a, b
    return None, None


def _align_with_ctc(stems, work_path: Path, lyrics_path: str, language: str,
                    device: str, duet: bool, synced_lyrics_path: str | None):
    """
    Etapa 4 pelo CTC global (pipeline/ctc_align.py): a letra inteira alinhada
    de uma vez, sem Whisper. Devolve (word_timings, stems), ou (None, stems)
    quando a letra não cabe no vocabulário do modelo, algo falha ou a
    confiança ficou baixa demais - aí o chamador segue pelo caminho do
    Whisper, como antes.

    Com o sinal interno do CTC (fração de palavras em linha de confiança
    baixa, ctc_align.low_confidence_frac) no lugar das interpoladas:
      > CTC_FALLBACK_LOW_FRAC - devolve (None, stems): o chamador segue pelo
          caminho do Whisper, que é melhor nesse regime (ver a constante);
      > CTC_RESCUE_LOW_FRAC - 4b, voz principal isolada (ganha quem tiver MENOS
          palavras em linha de confiança baixa; falha NÃO-FATAL).
    Não há 4c (2ª separação) nem 4d (VAD) aqui: acima do ponto em que o 4c
    faria sentido o fallback já leva pro Whisper, que tem os dele.
    """
    from pipeline.ctc_align import align_lyrics_ctc_to_audio, low_confidence_frac

    synced = Path(synced_lyrics_path) if synced_lyrics_path else None
    debug_log("ETAPA 4 - iniciando alinhamento CTC global")
    console.print(t("main.aligner_ctc"))
    try:
        word_timings = align_lyrics_ctc_to_audio(
            stems.vocals, Path(lyrics_path), language, device, synced_lyrics_path=synced,
        )
    except Exception as e:
        debug_log(f"ETAPA 4 - CTC falhou, caindo pro Whisper: {e!r}")
        console.print(t("main.ctc_failed", err=e))
        return None, stems
    if word_timings is None:
        debug_log("ETAPA 4 - letra fora do vocabulário do CTC, caindo pro Whisper")
        console.print(t("main.ctc_unsupported"))
        return None, stems

    low = low_confidence_frac(word_timings)
    debug_log(f"ETAPA 4 - CTC concluído. {len(word_timings)} palavras, {100 * low:.1f}% em linha de confiança baixa")

    if low > CTC_FALLBACK_LOW_FRAC:
        debug_log(f"ETAPA 4 - CTC com {100 * low:.1f}% em linha de confiança baixa, caindo pro Whisper")
        console.print(t("main.ctc_fallback", pct=100 * low))
        return None, stems

    if low > CTC_RESCUE_LOW_FRAC and not duet:
        console.print(t("main.ctc_rescue4b_try", pct=100 * low))
        debug_log(f"ETAPA 4b (CTC) - resgate: low={low:.2f}, iniciando isolate_lead_vocal")
        try:
            lead_vocals = isolate_lead_vocal(stems.vocals, work_path / "lead_vocal")
            retry = align_lyrics_ctc_to_audio(
                lead_vocals, Path(lyrics_path), language, device, synced_lyrics_path=synced,
            )
            retry_low = low_confidence_frac(retry) if retry else 1.0
            debug_log(f"ETAPA 4b (CTC) - baixa confiança: demucs={low:.3f} lead={retry_low:.3f}")
            if retry and retry_low < low:
                console.print(t("main.ctc_rescue_ok", before=100 * low, after=100 * retry_low))
                word_timings, low = retry, retry_low
            else:
                console.print(t("main.ctc_rescue_no", before=100 * low, after=100 * retry_low))
        except Exception as e:
            debug_log(f"ETAPA 4b (CTC) - falhou (não-fatal): {e}")
            console.print(t("main.rescue4b_fail", err=e))

    return word_timings, stems


def _report_ctc_alignment(word_timings) -> None:
    """Resumo + aviso do caminho do CTC: quantas palavras em linha de confiança baixa."""
    from pipeline.ctc_align import low_confidence_frac

    by_source = alignment_stats(word_timings)["by_source"]
    console.print(t("main.words_done", n=len(word_timings)))
    console.print(t("main.ctc_breakdown", ctc=by_source["ctc"], low=by_source["ctc_low"],
                    interp=by_source["interpolated"]))
    pct = 100 * low_confidence_frac(word_timings)
    if pct > CTC_WARN_PCT:
        console.print(t("main.ctc_low_warn", pct=pct))


def _align_with_whisper(stems, source, work_path: Path, lyrics_path: str, language: str,
                        device: str, duet: bool, whisper_model: str,
                        synced_lyrics_path: str | None):
    """
    Etapa 4 pelo caminho do Whisper (align.align_lyrics_to_audio) + os resgates
    4b/4d/4c. É o alinhador de antes do CTC global, e o fallback dele quando a
    letra não cabe no vocabulário do MMS_FA (outro alfabeto) ou com
    --aligner whisper. Devolve (word_timings, stems) - o 4c pode trocar os stems.
    """
    debug_log("ETAPA 4 - iniciando align_lyrics_to_audio")
    # Transcrição pode ir para a CPU mesmo com o resto na GPU (GPU AMD/ROCm:
    # ver resolve_whisper_device). O tamanho do modelo segue o device REAL dela.
    whisper_device = resolve_whisper_device(device)
    if whisper_device != device:
        debug_log(f"ETAPA 4 - Whisper na CPU (CTranslate2 sem GPU); alinhamento em {device}")
        console.print(t("main.whisper_on_cpu"))
    whisper_model_size = resolve_whisper_model(whisper_model, whisper_device)
    debug_log(f"ETAPA 4 - modelo Whisper: {whisper_model_size} (pedido: {whisper_model})")
    console.print(t("main.whisper_model", model=whisper_model_size))
    word_timings = align_lyrics_to_audio(
        stems.vocals, Path(lyrics_path), language=language, device=device, whisper_device=whisper_device,
        whisper_model_size=whisper_model_size,
        synced_lyrics_path=Path(synced_lyrics_path) if synced_lyrics_path else None,
    )
    debug_log(f"ETAPA 4 - concluída. {len(word_timings)} palavras")

    # RESGATE com voz principal isolada (validado em 13/07/2026 contra 5
    # charts feitos à mão de D:\Canciones Karaoke): alinhar SEMPRE no stem
    # isolado pelo modelo de karaoke PIORA músicas pop normais (no pior
    # caso, 59%->15% das palavras dentro de 1s do chart de referência),
    # mas SALVA músicas onde coro/apoio sobrepõe a voz principal (caso
    # "Ama De Mi Sol": cauda do coro saiu de 100% interpolada para
    # ancorada). Então o stem combinado do Demucs é o padrão, e o stem
    # isolado é só tentativa de resgate quando a âncora ficou fraca -
    # ganha quem tiver MENOS palavras interpoladas (sinal interno de
    # qualidade, não precisa de ground truth). NÃO-FATAL: qualquer falha
    # (download do modelo ~900MB, etc.) mantém o resultado que já temos.
    interp_frac = alignment_stats(word_timings)["by_source"]["interpolated"] / max(len(word_timings), 1)
    if interp_frac > 0.10 and duet:
        # Em dueto, o resgate 4b é CONTRAPRODUCENTE: isolate_lead_vocal isola a
        # voz PRINCIPAL, o que descartaria o 2º cantor - exatamente o que o
        # dueto precisa manter. O 4c (2ª separação Demucs completa, abaixo)
        # preserva as duas vozes e segue valendo.
        debug_log(f"ETAPA 4b - PULADA (modo dueto): interp_frac={interp_frac:.2f}")
        console.print(t("main.rescue4b_skip_duet", pct=100 * interp_frac))
    elif interp_frac > 0.10:
        console.print(t("main.rescue4b_try", pct=100 * interp_frac))
        debug_log(f"ETAPA 4b - resgate: interp_frac={interp_frac:.2f}, iniciando isolate_lead_vocal")
        try:
            lead_vocals = isolate_lead_vocal(stems.vocals, work_path / "lead_vocal")
            retry_timings = align_lyrics_to_audio(
                lead_vocals, Path(lyrics_path), language=language, device=device, whisper_device=whisper_device,
                whisper_model_size=whisper_model_size,
                synced_lyrics_path=Path(synced_lyrics_path) if synced_lyrics_path else None,
            )
            retry_interp = alignment_stats(retry_timings)["by_source"]["interpolated"]
            base_interp = alignment_stats(word_timings)["by_source"]["interpolated"]
            debug_log(f"ETAPA 4b - interpoladas: demucs={base_interp} lead={retry_interp}")
            if retry_interp < base_interp:
                word_timings = retry_timings
                console.print(t("main.rescue4b_ok", before=base_interp, after=retry_interp))
            else:
                console.print(t("main.rescue4b_no", before=base_interp, after=retry_interp))
        except Exception as e:
            debug_log(f"ETAPA 4b - falhou (não-fatal): {e}")
            console.print(t("main.rescue4b_fail", err=e))

    # ETAPA 4d - RESGATE com detecção de voz (VAD) mais sensível.
    #
    # Achado real (relato de usuário, issue #9, "Why Do I Have To Feel?" - The
    # Vampire Lestat): o VAD do whisperx (pyannote, onset=0.5/offset=0.363)
    # deixou ~70% da música sem NENHUM segmento de fala - vocal baixo/breathy
    # de trilha atmosférica não passa no limiar default. Baixando pra
    # onset=0.3/offset=0.2 a cobertura da transcrição livre subiu de 30% pra
    # 43%. É um sintoma DIFERENTE do resgate 4b (que mira harmonia/coro
    # sequestrando o lead) - aqui o Whisper nem CHEGA a tentar transcrever o
    # trecho, o VAD que descarta antes.
    #
    # MEDIDO (30/07/2026) contra 51 charts de TERCEIROS na biblioteca gold
    # (filtrado #CREATOR != USKMaker, pra não medir nosso pipeline contra ele
    # mesmo - 616/~1440 charts da biblioteca já foram gerados por nós em algum
    # momento). Resultado: baixar o VAD como DEFAULT GLOBAL não é seguro -
    # empate no agregado (onset 87,3→88,3ms, w_1s 0,747→0,757) mas com ALTA
    # variância: ajuda muito em alguns casos (Beatles - I'll Follow The Sun:
    # 26,65s→0,41s de erro) e PIORA música que já estava boa (P!nk, Irene
    # Cara, Chop Suey - o VAD mais permissivo pegou ruído/instrumental como
    # fala). Por isso é condicional aqui, mesmo contrato dos resgates acima:
    # só tenta quando já está ruim (interp_frac>0,10), ganha quem tiver MENOS
    # palavras interpoladas (sinal interno, sem ground truth). Roda ANTES do
    # 4c (que reseparara o Demucs, caro) porque é barato - reusa o mesmo stem.
    interp_frac = alignment_stats(word_timings)["by_source"]["interpolated"] / max(len(word_timings), 1)
    if interp_frac > 0.10:
        console.print(t("main.rescue4d_try", pct=100 * interp_frac))
        debug_log(f"ETAPA 4d - resgate VAD sensivel: interp_frac={interp_frac:.2f}")
        try:
            vad_retry_timings = align_lyrics_to_audio(
                stems.vocals, Path(lyrics_path), language=language, device=device, whisper_device=whisper_device,
                whisper_model_size=whisper_model_size,
                synced_lyrics_path=Path(synced_lyrics_path) if synced_lyrics_path else None,
                vad_options={"vad_onset": 0.3, "vad_offset": 0.2},
            )
            vad_retry_interp = alignment_stats(vad_retry_timings)["by_source"]["interpolated"]
            base_interp = alignment_stats(word_timings)["by_source"]["interpolated"]
            debug_log(f"ETAPA 4d - interpoladas: atual={base_interp} vad_sensivel={vad_retry_interp}")
            if vad_retry_interp < base_interp:
                word_timings = vad_retry_timings
                console.print(t("main.rescue4d_ok", before=base_interp, after=vad_retry_interp))
            else:
                console.print(t("main.rescue4d_no", before=base_interp, after=vad_retry_interp))
        except Exception as e:
            debug_log(f"ETAPA 4d - falhou (não-fatal): {e}")
            console.print(t("main.rescue4d_fail", err=e))

    # ETAPA 4c - 2ª SEPARAÇÃO ("outro sorteio do Demucs").
    #
    # O Demucs NÃO é determinístico: a MESMA entrada dá stems diferentes a cada
    # rodada (medido por sha256 - 3 rodadas do mesmo .ogg, 3 hashes distintos).
    # Quase sempre tanto faz, mas de vez em quando sai uma separação ruim, e o
    # estrago é desproporcional: em "Supergrass - Alright" o Whisper ouviu
    # "eat blond tea" no lugar de "keep our teeth", sobraram 20 âncoras de 183
    # palavras e o alinhamento desabou (89% interpoladas). A MESMA música, com
    # o Demucs rodado de novo, deu 0,5%. Ver issue #6.
    #
    # Não adianta tentar isso sempre: sorteio ruim é raro (1 em 19 na
    # biblioteca gold medida) e uma 2ª separação custa 1-3 min de GPU. Então só
    # rodamos quando o alinhamento claramente desabou - o mesmo corte do aviso
    # ao usuário (ALIGNMENT_FAILED_PCT), que fica num vão VAZIO dos dados:
    # música difícil chega a 16,8%, o caso patológico é 89%, e não há nada
    # entre 20% e 50%.
    #
    # Por que DEPOIS do resgate (4b) e não antes: o resgate isola a voz
    # principal A PARTIR do stem do Demucs. Se o stem está ruim, o isolado
    # herda o problema - foi o que aconteceu no Supergrass (resgate tentou e
    # deu exatamente os mesmos 89%). Ou seja, 4b não cobre este caso, e por
    # isso 4c existe.
    #
    # Mesmo contrato do resgate: ganha quem tiver MENOS palavras interpoladas
    # (sinal interno, sem ground truth) e qualquer falha é NÃO-FATAL.
    interp_frac = alignment_stats(word_timings)["by_source"]["interpolated"] / max(len(word_timings), 1)
    if interp_frac * 100 > ALIGNMENT_FAILED_PCT:
        console.print(t("main.rescue4c_try", pct=100 * interp_frac))
        debug_log(f"ETAPA 4c - 2a separacao: interp_frac={interp_frac:.2f}")
        try:
            stems2 = separate_vocals(source.audio_wav, work_path / "stems_retry", device=device)
            retry_timings = align_lyrics_to_audio(
                stems2.vocals, Path(lyrics_path), language=language, device=device, whisper_device=whisper_device,
                whisper_model_size=whisper_model_size,
                synced_lyrics_path=Path(synced_lyrics_path) if synced_lyrics_path else None,
            )
            retry_interp = alignment_stats(retry_timings)["by_source"]["interpolated"]
            base_interp = alignment_stats(word_timings)["by_source"]["interpolated"]
            debug_log(f"ETAPA 4c - interpoladas: 1a separacao={base_interp} 2a={retry_interp}")
            if retry_interp < base_interp:
                word_timings = retry_timings
                # o pitch tem que sair do MESMO stem que alinhou, senão as
                # notas medem uma separação e apontam pra outra
                stems = stems2
                console.print(t("main.rescue4c_ok", before=base_interp, after=retry_interp))
            else:
                console.print(t("main.rescue4c_no", before=base_interp, after=retry_interp))
        except Exception as e:
            debug_log(f"ETAPA 4c - falhou (não-fatal): {e}")
            console.print(t("main.rescue4c_fail", err=e))


    return word_timings, stems


def _report_whisper_alignment(word_timings) -> None:
    """Resumo por fonte + avisos (interpolação, reconhecimento baixo) do caminho do Whisper."""
    stats = alignment_stats(word_timings)
    by_source = stats["by_source"]
    interpolated_count = by_source["interpolated"]
    console.print(t("main.words_done", n=len(word_timings)))
    console.print(t(
        "main.words_breakdown",
        anchor=by_source["anchor"], fuzzy=by_source["fuzzy"],
        realign=by_source["realign"], lrc=by_source["lrc"], interp=interpolated_count,
    ))
    pct = 100 * interpolated_count / max(len(word_timings), 1)
    if interpolated_count:
        console.print(t("main.interp_warn", pct=pct, runs=stats["interpolated_runs"]))
        # Acima de metade estimada não é "vale revisar", é OUTRA COISA: o
        # alinhamento não achou onde ancorar e o pacote sai fora de sincronia.
        # Tratar isso com o mesmo aviso amarelo de 5% é entregar lixo calado.
        #
        # CAUSA (medida, issue #6): o Demucs NÃO é determinístico - a mesma
        # entrada dá stems diferentes (3 hashes distintos do mesmo .ogg). Uma
        # separação ruim faz o Whisper ouvir errado ("eat blond tea" no lugar
        # de "keep our teeth" em "Supergrass - Alright"), sobram 20 âncoras de
        # 183 palavras e o alinhamento desaba: 89% interpoladas. Rodando de
        # novo, a mesma música deu 0,5%. Por isso o conselho é REGERAR - não é
        # "esta música é difícil", é um dado ruim que a próxima tentativa
        # provavelmente não repete.
        if pct > ALIGNMENT_FAILED_PCT:
            console.print(t("main.align_failed", pct=pct))
            console.print(t("main.align_failed_hint"))
            debug_log(f"ALINHAMENTO FALHOU: {pct:.1f}% interpoladas")

    # Aviso "ancorado mas ERRADO" (issue nova, achado no n=60): independente do
    # interp. Quando o Whisper reconheceu POUCO da letra (word-recall baixo), as
    # âncoras que ele colocou podem estar nas palavras erradas - e isso passa
    # batido pelo aviso de interpolação (a música pode estar quase toda
    # "ancorada", só que no lugar errado).
    measured = by_source["anchor"] + by_source["fuzzy"]
    wrecall = measured / max(len(word_timings), 1)
    # A letra sincronizada segurou o alinhamento? Ver LRC_RESCUE_INTERP_PCT.
    lrc_carried = by_source["lrc"] > 0 and pct <= LRC_RESCUE_INTERP_PCT
    if wrecall < WHISPER_RECALL_FLOOR and pct <= ALIGNMENT_FAILED_PCT:
        # o "pct <= ..." evita avisar duas vezes a mesma música (se o interp já
        # disparou o alarme forte acima, não repete)
        if lrc_carried:
            # Recall baixo, mas quase nada foi estimado E o .lrc entrou: o risco
            # que este aviso descreve (ancorar no lugar errado) foi justamente o
            # que o .lrc corrigiu, demovendo âncoras implausíveis. Informa, sem
            # alarme - um vermelho aqui seria treinar o usuário a ignorá-lo.
            console.print(t("main.recall_lrc_ok", recall=100 * wrecall,
                            lrc=by_source["lrc"], pct=pct))
            debug_log(
                f"WORD-RECALL BAIXO: {100*wrecall:.0f}% - coberto pelo .lrc "
                f"({by_source['lrc']} inícios de linha, {pct:.1f}% interpoladas)"
            )
        else:
            console.print(t("main.recall_low", recall=100 * wrecall))
            console.print(t("main.recall_low_hint"))
            debug_log(f"WORD-RECALL BAIXO: {100*wrecall:.0f}% (âncoras podem estar erradas)")



def run_pipeline(
    url: str | None,
    file: str | None,
    lyrics_path: str,
    title: str,
    artist: str,
    language: str,
    out_dir: str,
    manual_bpm: float | None,
    manual_gap_ms: int,
    device: str,
    with_video: bool = False,
    bg_video: bool = False,
    bg_video_url: str | None = None,
    clean_work: bool = False,
    synced_lyrics_path: str | None = None,
    with_stems: bool = False,
    duet: bool = False,
    backtrack: bool = False,
    transpose: int = 0,
    yarg_export: bool = False,
    keep_harmonies: bool = False,
    mp4_export: bool = False,
    whisper_model: str = "auto",
    romanize: bool = False,
    audio_format: str = "ogg",
    max_video_resolution: int = 0,
    transcribe: bool = False,
    aligner: str = DEFAULT_ALIGNER,
    creator: str | None = None,
    app_version: str | None = None,
):
    global _debug_log_path

    out_path = Path(out_dir)
    work_path = out_path / "_work"
    out_path.mkdir(parents=True, exist_ok=True)

    _debug_log_path = out_path / "pipeline_debug.log"
    _debug_log_path.write_text("", encoding="utf-8")

    debug_log(f"Pipeline iniciada. PID={__import__('os').getpid()}")
    debug_log(f"Python: {sys.executable}")
    debug_log(
        f"Args: url={url!r} file={file!r} title={title!r} artist={artist!r} "
        f"out={out_dir!r} with_video={with_video}"
    )

    # Resolve o device de verdade (cai para CPU se não houver CUDA). Sem isso,
    # máquinas sem GPU NVIDIA quebravam com "Torch not compiled with CUDA".
    requested_device = device
    device = resolve_device(device)
    debug_log(f"Device solicitado={requested_device!r} -> efetivo={device!r}")

    # Põe o ffmpeg embutido no PATH ANTES da Etapa 4: o whisperx.load_audio e o
    # pyannote chamam "ffmpeg" cru por subprocess, sem passar pelo ffmpeg_exe().
    # Sem isto, quem não tem ffmpeg no PATH do sistema quebrava no alinhamento
    # com FileNotFoundError [WinError 2], mesmo com o embutido presente.
    ensure_ffmpeg_on_path()

    # Dueto: cruza a caixa com as tags P1:/P2: da letra e avisa se divergirem
    # (as tags são sempre removidas do texto cantado, marque a caixa ou não).
    tagged_lines = count_singer_tagged_lines(Path(lyrics_path))
    if duet and tagged_lines == 0:
        console.print(t("main.duet_no_tags"))
    elif tagged_lines > 0 and not duet:
        console.print(t("main.tags_no_duet"))
    if device == "cpu" and requested_device != "cpu":
        console.print(t("main.no_cuda"))

    console.rule(t("main.step1"))
    debug_log("ETAPA 1 - iniciando get_source_audio")
    source = get_source_audio(url, file, work_path / "raw", with_video=with_video,
                               max_video_resolution=max_video_resolution)
    debug_log(f"ETAPA 1 - concluída. audio={source.audio_wav} video={source.video_path}")
    console.print(t("main.audio_at", path=source.audio_wav))
    if source.video_path:
        console.print(t("main.video_downloaded", path=source.video_path))

    audio_url = url if url and (url.startswith("http://") or url.startswith("https://")) else None
    resolved_video_url = None
    if with_video and audio_url:
        resolved_video_url = audio_url
    elif bg_video_url:
        resolved_video_url = bg_video_url

    # Videoclipe de fundo para fonte LOCAL: o áudio do pacote continua sendo
    # o arquivo do usuário (ex.: rip de CD, qualidade melhor que YouTube);
    # o vídeo é só ilustração de fundo (#VIDEO). Com URL explícita usa ela;
    # sem URL, busca o 1º resultado do YouTube por artista + título
    # (geralmente o clipe oficial). NÃO-FATAL: sem vídeo, o pacote sai só
    # com a capa - que já é o fallback natural do jogo.
    if (bg_video or bg_video_url) and source.video_path is None:
        query = (bg_video_url or "").strip() or f"ytsearch1:{artist} {title}"
        console.print(t("main.bgvideo_downloading", query=query))
        debug_log(f"ETAPA 1b - baixando videoclipe de fundo: {query}")
        bg_path, bg_url = download_background_video(query, work_path / "bgvideo")
        if bg_path:
            source.video_path = bg_path
            resolved_video_url = bg_url or bg_video_url
            debug_log(f"ETAPA 1b - concluída. video={bg_path} url={resolved_video_url}")
            console.print(t("main.bgvideo_ok", path=bg_path))
        else:
            debug_log("ETAPA 1b - sem vídeo (falha não-fatal)")
            console.print(t("main.bgvideo_fail"))

    video_gap = None
    if source.video_path and source.video_path.exists() and (bg_video or bg_video_url or not url):
        debug_log("Estimando offset de sincronização de vídeo (#VIDEOGAP)...")
        try:
            from pipeline.video_sync import estimate_video_offset
            video_gap = estimate_video_offset(source.audio_wav, source.video_path, work_dir=work_path / "sync")
            if video_gap is not None:
                debug_log(f"#VIDEOGAP medido com sucesso: {video_gap} s")
                console.print(f"[green]Sincronia de vídeo (#VIDEOGAP): {video_gap:+.2f}s[/green]")
            else:
                debug_log("#VIDEOGAP: correlação inconclusiva ou vídeo sem áudio (usando 0)")
        except Exception as e:
            debug_log(f"Falha ao estimar #VIDEOGAP: {e}")

    console.rule(t("main.step2"))
    debug_log("ETAPA 2 - iniciando separate_vocals")
    stems = separate_vocals(source.audio_wav, work_path / "stems", device=device)
    debug_log(f"ETAPA 2 - concluída. vocals={stems.vocals} instrumental={stems.instrumental}")
    console.print(t("main.vocal_ok", path=stems.vocals))
    console.print(t("main.instrumental_ok", path=stems.instrumental))

    console.rule(t("main.step3"))
    debug_log("ETAPA 3 - iniciando detect_bpm")
    grid = detect_bpm(stems.instrumental, manual_bpm)
    debug_log(f"ETAPA 3 - concluída. bpm={grid.bpm}")
    console.print(t("main.bpm_ok", bpm=grid.bpm))
    if not manual_bpm:
        console.print(t("main.bpm_auto_warn"))

    console.rule(t("main.step4"))

    # Auto-transcrição se a letra estiver vazia ou transcribe=True
    lyrics_file = Path(lyrics_path) if lyrics_path else None
    has_lyrics = bool(lyrics_file and lyrics_file.exists() and lyrics_file.read_text(encoding="utf-8").strip())

    if transcribe or not has_lyrics:
        console.print("[yellow]Nenhuma letra fornecida: iniciando auto-transcrição pelo áudio com Whisper...[/yellow]")
        debug_log("Auto-transcrição ativada: transcrevendo vocais...")
        from pipeline.align import transcribe_lyrics
        transcribed_lines = transcribe_lyrics(
            stems.vocals,
            language=language,
            device=device,
            whisper_model_size=whisper_model,
        )
        if not transcribed_lines:
            raise RuntimeError("Auto-transcrição não detectou palavras no áudio.")

        transcribed_text = "\n".join(transcribed_lines)
        transcribed_file = out_path / "_lyrics_transcribed.txt"
        transcribed_file.write_text(transcribed_text, encoding="utf-8")
        lyrics_path = str(transcribed_file)
        debug_log(f"Auto-transcrição concluída ({len(transcribed_lines)} linhas gravadas em {transcribed_file})")
        console.print(f"[green]Auto-transcrição concluída: {len(transcribed_lines)} linhas geradas.[/green]")

    word_timings = None
    if aligner == "ctc":
        word_timings, stems = _align_with_ctc(
            stems, work_path, lyrics_path, language, device, duet, synced_lyrics_path,
        )
    if word_timings is None:
        word_timings, stems = _align_with_whisper(
            stems, source, work_path, lyrics_path, language, device, duet, whisper_model,
            synced_lyrics_path,
        )
        _report_whisper_alignment(word_timings)
    else:
        _report_ctc_alignment(word_timings)

    # Checagem de cobertura: avisa se a letra termina muito antes do áudio
    # (refrão repetido escrito só uma vez - erro comum de letras "(2x)").
    if word_timings:
        last_word_end = max(w.end for w in word_timings)
        audio_duration = get_audio_duration_seconds(stems.vocals)
        uncovered = audio_duration - last_word_end
        debug_log(f"Cobertura da letra: última palavra em {last_word_end:.1f}s de {audio_duration:.1f}s totais")
        if uncovered > 10.0:
            console.print(t("main.lyrics_short", last=last_word_end,
                            duration=audio_duration, uncovered=uncovered))

        # Detecção em 2 estágios de possíveis trechos faltantes na letra oficial
        if has_lyrics:
            debug_log("Verificando possíveis trechos faltantes na letra (2-stage gap detection)...")
            try:
                from pipeline.align import detect_missing_lyrics_gaps
                lead_vocal_path = work_path / "lead_vocal" / "vocals_lead.wav"
                gap_warnings = detect_missing_lyrics_gaps(
                    word_timings, stems.vocals, language, device=device,
                    whisper_model_size=whisper_model,
                    lead_vocals_wav=lead_vocal_path if lead_vocal_path.exists() else None,
                    work_dir=work_path,
                )
                for (start_str, end_str, snippet) in gap_warnings:
                    msg = f"Possível trecho de letra faltando em {start_str}-{end_str}: \"{snippet}\""
                    debug_log(msg)
                    console.print(f"[yellow]{msg}[/yellow]")
            except Exception as e:
                debug_log(f"Falha na detecção de gaps (ignorada): {e}")

    console.rule(t("main.step5"))
    debug_log("ETAPA 5 - iniciando fetch_metadata")
    # Base dos nomes de arquivo do pacote. SANITIZADA: o texto do usuário pode
    # trazer caractere que o Windows não aceita ("Quem?") ou que muda o caminho
    # ("AC/DC", "Song 2: Live") - ver pipeline/filenames.py. O título/artista
    # ORIGINAIS seguem intactos para os headers e as buscas de metadado.
    file_base = sanitize_filename(f"{artist} - {title}")
    # Sufixo " [DUET]" no padrão da comunidade (USDB) - o "[DUET]" é adicionado
    # DEPOIS do sanitize (que removeria os colchetes), igual a "[CO]"/"[BG]".
    if duet:
        file_base = f"{file_base} [DUET]"

    # Nomes no padrão UltraStar profissional: "[CO]" (capa) e "[BG]" (fundo).
    cover_path = out_path / f"{file_base} [CO].jpg"
    bg_path = out_path / f"{file_base} [BG].jpg"
    metadata = fetch_metadata(
        audio_path=source.audio_wav,
        artist=artist,
        title=title,
        out_cover_path=cover_path,
        use_network=True,
        out_bg_path=bg_path,
    )
    debug_log(
        f"ETAPA 5 - concluída. fonte={metadata.source} ano={metadata.year} "
        f"gênero={metadata.genre} capa={metadata.cover_path} fundo={metadata.background_path}"
    )
    console.print(t("main.meta_ok", source=_meta_source_label(metadata.source)))
    console.print(t(
        "main.meta_detail",
        year=metadata.year or "—",
        genre=metadata.genre or "—",
        cover=t("main.word_yes") if metadata.cover_path else t("main.word_no"),
        bg=("fanart.tv" if metadata.background_path
            else t("main.word_cover") if metadata.cover_path else t("main.word_no")),
    ))

    console.rule(t("main.step6"))
    debug_log("ETAPA 6 - iniciando build_song")
    final_audio_name = f"{file_base}.{audio_format}"
    cover_filename = metadata.cover_path.name if metadata.cover_path else None

    # Background (#BACKGROUND): em camadas. Se o fanart.tv devolveu um fundo
    # 16:9 (só com FANARTTV_API_KEY), usa ele. Senão, reaproveita a capa como
    # background ("[BG].jpg") para que TODO pacote com capa tenha #BACKGROUND -
    # é comum no padrão do formato. Sem capa nenhuma, fica sem background.
    background_filename = None
    if metadata.background_path and metadata.background_path.exists():
        background_filename = metadata.background_path.name
    elif metadata.cover_path and metadata.cover_path.exists():
        try:
            shutil.copy(metadata.cover_path, bg_path)
            background_filename = bg_path.name
            debug_log(f"Background (fallback) copiado da capa: {bg_path}")
        except Exception as e:
            debug_log(f"Falha ao copiar capa->background (ignorada): {e}")

    # Se um vídeo foi baixado, copia para o pacote com o nome padrão
    # UltraStar ("Artista - Título.mp4") e referencia na tag #VIDEO.
    video_filename = None
    if source.video_path and source.video_path.exists():
        video_ext = source.video_path.suffix.lower() or ".mp4"
        video_filename = f"{file_base}{video_ext}"
        video_dest = out_path / video_filename
        shutil.copy(source.video_path, video_dest)
        debug_log(f"Vídeo copiado para o pacote: {video_dest}")
        console.print(t("main.video_included", path=video_dest))

    # Faixas separadas (#VOCALS/#INSTRUMENTAL, spec v1 apêndice A.3): deixam o
    # player oferecer volume separado de voz-guia e instrumental. Os stems já
    # existem - o Demucs os produziu na Etapa 2 e a gente os jogava fora.
    # OPT-IN porque cada um vira um .ogg do tamanho da música: o pacote quase
    # triplica. Convenção de nome "[VOC]"/"[INSTR]" copiada do usdb_syncer,
    # que é como a comunidade nomeia (e casa com nosso "[CO]"/"[BG]").
    vocals_filename = None
    instrumental_filename = None
    if with_stems:
        debug_log("Convertendo stems separados para .ogg (with_stems=True)")
        console.print(t("main.stems_converting"))
        try:
            vocals_filename = f"{file_base} [VOC].{audio_format}"
            instrumental_filename = f"{file_base} [INSTR].{audio_format}"
            convert_audio(stems.vocals, out_path / vocals_filename, audio_format=audio_format)
            convert_audio(stems.instrumental, out_path / instrumental_filename, audio_format=audio_format)
            console.print(t("main.stems_ok", vocals=vocals_filename,
                            instrumental=instrumental_filename))
        except Exception as e:
            # Não-fatal: o pacote é perfeitamente válido sem estas faixas (são
            # opcionais na spec). Derrubar uma geração que já deu certo por
            # causa de um extra seria desproporcional.
            vocals_filename = None
            instrumental_filename = None
            debug_log(f"Falha ao converter stems: {e}")
            console.print(t("main.stems_fail", err=e))

    # Nomes dos cantores para os headers #P1/#P2, derivados do #ARTIST
    # ("Elton John & Kiki Dee" -> "Elton John" / "Kiki Dee"). Só em dueto.
    p1_name, p2_name = split_duet_artists(artist) if duet else (None, None)

    if creator:
        effective_creator = creator
    elif app_version:
        effective_creator = f"USKMaker v{app_version}"
    else:
        effective_creator = "USKMaker"

    song = build_song(
        title=title,
        artist=artist,
        mp3_filename=final_audio_name,
        word_timings=word_timings,
        vocals_wav_path=stems.vocals,
        grid=grid,
        gap_ms=manual_gap_ms,
        language=language,
        year=metadata.year,
        genre=metadata.genre,
        cover_filename=cover_filename,
        video_filename=video_filename,
        background_filename=background_filename,
        audio_url=audio_url,
        video_url=resolved_video_url,
        cover_url=metadata.cover_url,
        video_gap=video_gap,
        vocals_filename=vocals_filename,
        instrumental_filename=instrumental_filename,
        duet=duet,
        p1_name=p1_name,
        p2_name=p2_name,
        transpose=transpose,
        creator=effective_creator,
    )
    debug_log("ETAPA 6 - build_song concluído, escrevendo .txt")

    # Romanização (opt-in): reescreve o texto das notas em romaji. Depois do
    # build_song (o alinhamento roda sobre o japonês original) e antes de
    # escrever - o .txt e o song_data.json já saem romanizados. Não-fatal: se o
    # pykakasi não estiver instalado, o pacote em japonês continua válido.
    if romanize:
        debug_log("Romanizando texto das notas (romanize=True)")
        try:
            romanize_notes(song.notes, language)
            console.print(t("main.romanized"))
        except Exception as e:
            debug_log(f"Falha ao romanizar (ignorada): {e}")
            console.print(t("main.romanize_fail", err=e))

    txt_path = out_path / f"{file_base}.txt"
    song.write(str(txt_path))
    console.print(t("main.txt_ok", path=txt_path))

    json_path = out_path / "song_data.json"
    song.write_json(str(json_path))
    console.print(t("main.json_ok", path=json_path))

    # Backtrack: o áudio do pacote vira o INSTRUMENTAL (sem voz-guia) - karaokê
    # puro. O instrumental já foi separado na Etapa 2; aqui só escolhemos a
    # fonte. Alinhamento/pitch usam o VOCAL e não são afetados. A qualidade é a
    # da separação do Demucs (nunca perfeita - pode sobrar resíduo de voz).
    audio_src = stems.instrumental if backtrack else source.audio_wav

    # Harmonias de volta (opt-in): o Demucs tira TODA voz, inclusive o apoio.
    # Aqui um segundo modelo separa voz principal de apoio DENTRO do stem
    # vocal, e só o apoio volta pro instrumental. Não-fatal: se falhar, o
    # pacote sai com o instrumental puro de sempre, como antes.
    if backtrack and keep_harmonies:
        console.print(t("main.harmonies_try"))
        debug_log("HARMONIAS - iniciando isolate_backing_vocals")
        try:
            backing = isolate_backing_vocals(stems.vocals, work_path / "backing_vocals")
            mixed = work_path / "instrumental_com_harmonias.wav"
            mix_backing_into_instrumental(stems.instrumental, backing, mixed)
            audio_src = mixed
            debug_log(f"HARMONIAS - concluído. fonte do áudio final: {mixed}")
            console.print(t("main.harmonies_ok"))
        except Exception as e:
            debug_log(f"HARMONIAS - falhou (ignorado): {e}")
            console.print(t("main.harmonies_fail", err=e))

    debug_log(f"Convertendo áudio final para .ogg (backtrack={backtrack}, transpose={transpose}, fonte={audio_src})")
    final_audio_dest = out_path / final_audio_name
    convert_audio(audio_src, final_audio_dest, audio_format=audio_format, pitch_semitones=transpose)
    console.print(t(
        "main.audio_converted",
        instr=t("main.audio_tag_instrumental") if backtrack else "",
        tone=t("main.audio_tag_tone", n=transpose) if transpose else "",
        path=final_audio_dest,
    ))

    # Export YARG (opt-in): monta uma subpasta "<file_base> (YARG)" com o
    # layout do YARG. O YARG lê o .txt UltraStar nativo, então só empacotamos
    # (notes.txt + song.ini + stems song.ogg/vocals.ogg + capa/vídeo). Roda
    # ANTES do clean_work porque os stems vivem em _work. Não-fatal: um pacote
    # UltraStar válido não pode ser derrubado por causa de um extra.
    if yarg_export:
        yarg_dir = out_path / f"{file_base} (YARG)"
        debug_log(f"Exportando para YARG em {yarg_dir} (transpose={transpose})")
        console.print(t("main.yarg_try"))
        try:
            export_yarg(
                yarg_dir, txt_path, stems, source.audio_wav,
                metadata.cover_path, source.video_path,
                title, artist, metadata.year, metadata.genre,
                transpose=transpose, audio_format=audio_format,
                video_gap=video_gap,
            )
            console.print(t("main.yarg_ok", path=yarg_dir))
        except Exception as e:
            debug_log(f"Falha ao exportar YARG (ignorada): {e}")
            console.print(t("main.yarg_fail", err=e))

    # Vídeo de karaokê (opt-in): renderiza "<base> (Karaoke).mp4" - a letra
    # preenchendo sílaba a sílaba por cima do fundo, para tocar em qualquer
    # TV/telefone, sem precisar do jogo instalado.
    #
    # Roda por ÚLTIMO de propósito. É o passo mais demorado depois da IA
    # (minutos, dependendo do tamanho do fundo) e é o mais dispensável: quando
    # ele chega, o pacote UltraStar inteiro já está escrito e válido no disco.
    # Por isso o try/except só AVISA - a mesma regra do YARG acima: um extra
    # não derruba uma geração que já deu certo.
    #
    # Reusa `final_audio_dest` (o áudio que foi para o pacote), então backtrack
    # e transposição valem no vídeo sem nenhum código extra aqui. E ANTES do
    # clean_work, que não importa para este passo (nada vem de _work) mas
    # mantém a ordem "tudo que gera arquivo primeiro, limpeza depois".
    if mp4_export:
        debug_log("Exportando vídeo de karaokê (.mp4)")
        if not ffmpeg_has_libass():
            console.print(t("main.mp4_no_libass"))
        else:
            console.print(t("main.mp4_rendering"))
            try:
                mp4_path = export_karaoke_video(
                    song,
                    out_path,
                    file_base,
                    audio_path=final_audio_dest,
                    video_path=(out_path / video_filename) if video_filename else None,
                    background_path=(out_path / background_filename) if background_filename else None,
                    cover_path=metadata.cover_path,
                )
                console.print(t("main.mp4_ok", path=mp4_path))
            except Exception as e:
                debug_log(f"Falha ao renderizar o vídeo de karaokê (ignorada): {e}")
                console.print(t("main.mp4_fail", err=e))

    # Limpeza opcional da pasta _work (intermediários: áudio bruto, stems do
    # Demucs, vídeo bruto). Só roda se o usuário pediu, e nunca derruba um
    # pipeline que já deu certo - por isso o try/except que só avisa.
    # Mantida OPT-IN porque esses intermediários são úteis para reprocessar
    # uma música sem baixar/separar tudo de novo durante testes.
    if clean_work:
        debug_log("Limpando pasta _work (clean_work=True)")
        try:
            if work_path.exists():
                shutil.rmtree(work_path)
            console.print(t("main.clean_ok", path=work_path))
        except Exception as e:
            debug_log(f"Falha ao limpar _work (ignorada): {e}")
            console.print(t("main.clean_fail", path=work_path, err=e))

    debug_log("Pipeline concluída com sucesso.")
    console.rule(t("main.done"))
    console.print(t("main.out_ready", path=out_path))
    console.print(t("main.reminder"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="USKMaker - pipeline completa")
    parser.add_argument("--url", help="Link do YouTube")
    parser.add_argument("--file", help="Caminho de áudio local (mp3/wav/ogg/flac/m4a)")
    parser.add_argument("--lyrics", required=True, help="Arquivo .txt com a letra (uma linha por frase)")
    parser.add_argument("--title", required=True)
    parser.add_argument("--artist", required=True)
    parser.add_argument("--language", default="pt")
    parser.add_argument("--out", default="./output_test")
    parser.add_argument("--bpm", type=float, default=None, help="BPM manual (recomendado após 1a rodada automática)")
    parser.add_argument("--gap_ms", type=int, default=0, help="GAP manual em ms (ajustar após 1a rodada)")
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"],
                        help="auto = usa CUDA se disponível, senão CPU")
    parser.add_argument("--with-video", action="store_true", help="Baixar e incluir o vídeo do YouTube no pacote")
    parser.add_argument(
        "--bg-video",
        action="store_true",
        help="Fonte local: baixar do YouTube um videoclipe só para o fundo "
        "(busca automática por artista + título; o áudio continua sendo o arquivo local)",
    )
    parser.add_argument(
        "--bg-video-url",
        default=None,
        help="URL específica do videoclipe de fundo (implica --bg-video)",
    )
    parser.add_argument("--clean-work", action="store_true", help="Remover a pasta _work (intermediários) ao final")
    parser.add_argument("--with-stems", action="store_true", help="Incluir faixas separadas voz/instrumental no pacote (#VOCALS/#INSTRUMENTAL) - quase triplica o tamanho")
    parser.add_argument("--duet", action="store_true", help="Modo dueto: lê as tags P1:/P2:/P1&P2: da letra e escreve o formato de dueto (#P1/#P2, blocos P1/P2, [DUET])")
    parser.add_argument("--backtrack", action="store_true", help="Backtrack: o áudio do pacote é o INSTRUMENTAL (sem voz-guia), karaokê puro")
    parser.add_argument("--transpose", type=int, default=0, help="Transpõe o pacote N semitons (áudio via rubberband + pitches das notas). 0 = tom original")
    parser.add_argument("--yarg-export", action="store_true", help="Exporta também uma subpasta no layout do YARG (notes.txt + song.ini + stems song.ogg/vocals.ogg)")
    parser.add_argument("--keep-harmonies", action="store_true", help="Mantém as vozes de apoio/harmonias no áudio do pacote (só a voz principal é removida). Custa uma separação a mais.")
    parser.add_argument("--whisper-model", default="auto",
                        choices=["auto", "medium", "large-v3", "large-v2", "small"],
                        help="Modelo de reconhecimento do alinhamento. auto = large-v3 em GPU NVIDIA com VRAM sobrando, senão medium (GPU AMD: medium)")
    parser.add_argument("--yt-cookies-browser", default="", choices=["", *YT_COOKIE_BROWSERS],
                        help="Lê os cookies do YouTube deste navegador (para vídeo em que o YouTube pede "
                             "\"confirm you're not a bot\" ou login). Vazio = desligado")
    parser.add_argument("--aligner", default=DEFAULT_ALIGNER, choices=list(ALIGNERS),
                        help="Alinhador letra<->áudio: ctc = letra inteira de uma vez (padrão; cai no whisper "
                             "se a letra tiver outro alfabeto), whisper = transcrição livre + âncoras (o de antes)")
    parser.add_argument("--mp4-export", action="store_true", help="Renderiza também um vídeo de karaokê '<base> (Karaoke).mp4' (letra sincronizada gravada por cima do fundo)")
    parser.add_argument("--romanize", action="store_true", help="Reescreve o texto das notas em romaji (Hepburn) via pykakasi - para letras japonesas")
    parser.add_argument(
        "--synced-lyrics",
        default=None,
        help="Arquivo .lrc (letra sincronizada, ex.: LRCLIB) para semear âncoras de início de linha",
    )
    parser.add_argument("--audio-format", default="ogg", choices=["ogg", "mp3"],
                        help="Formato de saída de todos os áudios do pacote")
    parser.add_argument("--max-video-resolution", type=int, default=0,
                        help="Teto de altura (px) do vídeo baixado com --with-video. 0 = sem limite")
    parser.add_argument("--transcribe", action="store_true",
                        help="Transcrever automaticamente a letra pelo áudio com Whisper quando não fornecida")
    # Idioma das mensagens do log (não confundir com --language, que é o
    # idioma CANTADO da música). Default pt = o log de sempre. Ver pipeline/i18n.py.
    parser.add_argument("--ui-lang", default="pt", choices=list(SUPPORTED_LANGS),
                        help="Idioma das mensagens do log (pt/en)")
    parser.add_argument("--app-version", default=None,
                        help="Versão do USKMaker para o cabeçalho #CREATOR")
    parser.add_argument("--creator", default=None,
                        help="Sobrescreve o cabeçalho #CREATOR")
    args = parser.parse_args()
    if args.yt_cookies_browser:
        # mesmo caminho do servidor: o download lê a env (proc_utils.yt_cookies_browser)
        os.environ["USKMAKER_YT_COOKIES_BROWSER"] = args.yt_cookies_browser
    set_ui_lang(args.ui_lang)

    try:
        run_pipeline(
            url=args.url,
            file=args.file,
            lyrics_path=args.lyrics,
            title=args.title,
            artist=args.artist,
            language=args.language,
            out_dir=args.out,
            manual_bpm=args.bpm,
            manual_gap_ms=args.gap_ms,
            device=args.device,
            with_video=args.with_video,
            bg_video=args.bg_video,
            bg_video_url=args.bg_video_url,
            clean_work=args.clean_work,
            with_stems=args.with_stems,
            duet=args.duet,
            backtrack=args.backtrack,
            transpose=args.transpose,
            yarg_export=args.yarg_export,
            keep_harmonies=args.keep_harmonies,
            mp4_export=args.mp4_export,
            whisper_model=args.whisper_model,
            romanize=args.romanize,
            synced_lyrics_path=args.synced_lyrics,
            audio_format=args.audio_format,
            max_video_resolution=args.max_video_resolution,
            transcribe=args.transcribe,
            aligner=args.aligner,
            creator=args.creator,
            app_version=args.app_version,
        )
    except Exception:
        debug_log("EXCEÇÃO NÃO TRATADA:\n" + traceback.format_exc())
        raise

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
"""

from __future__ import annotations

import argparse
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path

import soundfile as sf
from rich.console import Console

from pipeline.align import align_lyrics_to_audio, alignment_stats
from pipeline.beatgrid import detect_bpm
from pipeline.build_song import build_song
from pipeline.download import download_background_video, get_source_audio
from pipeline.filenames import sanitize_filename
from pipeline.metadata import fetch_metadata
from pipeline.proc_utils import ffmpeg_exe, run_subprocess
from pipeline.separate import isolate_lead_vocal, separate_vocals

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
    """
    if requested == "cpu":
        return "cpu"
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def get_audio_duration_seconds(path: Path) -> float:
    """Lê só o cabeçalho do áudio (rápido, não carrega o arquivo inteiro)."""
    info = sf.info(str(path))
    return info.frames / info.samplerate


def convert_to_ogg(source_wav: Path, dest_ogg: Path, quality: int = 6) -> None:
    """
    Converte um .wav para .ogg (Vorbis) via ffmpeg. quality 0-10 (VBR
    libvorbis); 6 ~= 192kbps, bom equilíbrio qualidade/tamanho para karaoke.
    Ambos UltraStar Deluxe e Play leem Ogg Vorbis nativamente.
    """
    cmd = [
        ffmpeg_exe(), "-y",
        "-i", str(source_wav),
        "-c:a", "libvorbis",
        "-q:a", str(quality),
        str(dest_ogg),
    ]
    run_subprocess(cmd)


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
    if device == "cpu" and requested_device != "cpu":
        console.print(
            "[yellow]AVISO[/yellow] GPU NVIDIA/CUDA não disponível — o processamento "
            "vai rodar na CPU (funciona, mas é bem mais lento)."
        )

    console.rule("[bold cyan]Etapa 1/6 — Obtendo áudio fonte")
    debug_log("ETAPA 1 - iniciando get_source_audio")
    source = get_source_audio(url, file, work_path / "raw", with_video=with_video)
    debug_log(f"ETAPA 1 - concluída. audio={source.audio_wav} video={source.video_path}")
    console.print(f"[green]OK[/green] Áudio em: {source.audio_wav}")
    if source.video_path:
        console.print(f"[green]OK[/green] Vídeo baixado: {source.video_path}")

    # Videoclipe de fundo para fonte LOCAL: o áudio do pacote continua sendo
    # o arquivo do usuário (ex.: rip de CD, qualidade melhor que YouTube);
    # o vídeo é só ilustração de fundo (#VIDEO). Com URL explícita usa ela;
    # sem URL, busca o 1º resultado do YouTube por artista + título
    # (geralmente o clipe oficial). NÃO-FATAL: sem vídeo, o pacote sai só
    # com a capa - que já é o fallback natural do jogo.
    if (bg_video or bg_video_url) and source.video_path is None:
        query = (bg_video_url or "").strip() or f"ytsearch1:{artist} {title}"
        console.print(f"[cyan]—[/cyan] Baixando videoclipe de fundo ({query})...")
        debug_log(f"ETAPA 1b - baixando videoclipe de fundo: {query}")
        bg_path = download_background_video(query, work_path / "bgvideo")
        if bg_path:
            source.video_path = bg_path
            debug_log(f"ETAPA 1b - concluída. video={bg_path}")
            console.print(f"[green]OK[/green] Videoclipe de fundo: {bg_path}")
        else:
            debug_log("ETAPA 1b - sem vídeo (falha não-fatal)")
            console.print(
                "[yellow]AVISO[/yellow] Não consegui baixar um videoclipe de fundo - "
                "o pacote seguirá apenas com a imagem de capa."
            )

    console.rule("[bold cyan]Etapa 2/6 — Separando vocal/instrumental (Demucs)")
    debug_log("ETAPA 2 - iniciando separate_vocals")
    stems = separate_vocals(source.audio_wav, work_path / "stems", device=device)
    debug_log(f"ETAPA 2 - concluída. vocals={stems.vocals} instrumental={stems.instrumental}")
    console.print(f"[green]OK[/green] Vocal: {stems.vocals}")
    console.print(f"[green]OK[/green] Instrumental: {stems.instrumental}")

    console.rule("[bold cyan]Etapa 3/6 — Detectando BPM")
    debug_log("ETAPA 3 - iniciando detect_bpm")
    grid = detect_bpm(stems.instrumental, manual_bpm)
    debug_log(f"ETAPA 3 - concluída. bpm={grid.bpm}")
    console.print(f"[green]OK[/green] BPM: {grid.bpm:.2f} (este valor BRUTO vai direto para #BPM no .txt)")
    if not manual_bpm:
        console.print("[yellow]AVISO[/yellow] BPM detectado automaticamente - confira antes de confiar 100%.")

    console.rule("[bold cyan]Etapa 4/6 — Alinhando letra ao áudio (WhisperX, âncora+interpolação)")
    debug_log("ETAPA 4 - iniciando align_lyrics_to_audio")
    word_timings = align_lyrics_to_audio(
        stems.vocals, Path(lyrics_path), language=language, device=device,
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
    if interp_frac > 0.10:
        console.print(
            f"[yellow]—[/yellow] {100*interp_frac:.0f}% das palavras interpoladas - tentando resgate "
            "com a voz principal isolada do coro/apoio..."
        )
        debug_log(f"ETAPA 4b - resgate: interp_frac={interp_frac:.2f}, iniciando isolate_lead_vocal")
        try:
            lead_vocals = isolate_lead_vocal(stems.vocals, work_path / "lead_vocal")
            retry_timings = align_lyrics_to_audio(
                lead_vocals, Path(lyrics_path), language=language, device=device,
                synced_lyrics_path=Path(synced_lyrics_path) if synced_lyrics_path else None,
            )
            retry_interp = alignment_stats(retry_timings)["by_source"]["interpolated"]
            base_interp = alignment_stats(word_timings)["by_source"]["interpolated"]
            debug_log(f"ETAPA 4b - interpoladas: demucs={base_interp} lead={retry_interp}")
            if retry_interp < base_interp:
                word_timings = retry_timings
                console.print(
                    f"[green]OK[/green] Resgate melhorou: {base_interp} -> {retry_interp} "
                    "palavras interpoladas (usando voz principal isolada)."
                )
            else:
                console.print(
                    f"[dim]Resgate não melhorou ({base_interp} -> {retry_interp} interpoladas) - "
                    "mantendo o alinhamento no stem combinado.[/dim]"
                )
        except Exception as e:
            debug_log(f"ETAPA 4b - falhou (não-fatal): {e}")
            console.print(
                f"[yellow]AVISO[/yellow] Não consegui isolar a voz principal ({e}) - "
                "mantendo o alinhamento no stem combinado do Demucs."
            )

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
        console.print(
            f"[yellow]—[/yellow] {100*interp_frac:.0f}% das palavras interpoladas: o "
            "alinhamento desabou. Separando o vocal de novo (a separação varia a cada "
            "tentativa) e realinhando..."
        )
        debug_log(f"ETAPA 4c - 2a separacao: interp_frac={interp_frac:.2f}")
        try:
            stems2 = separate_vocals(source.audio_wav, work_path / "stems_retry", device=device)
            retry_timings = align_lyrics_to_audio(
                stems2.vocals, Path(lyrics_path), language=language, device=device,
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
                console.print(
                    f"[green]OK[/green] A 2ª separação salvou: {base_interp} -> {retry_interp} "
                    "palavras interpoladas."
                )
            else:
                console.print(
                    f"[dim]A 2ª separação não melhorou ({base_interp} -> {retry_interp} "
                    "interpoladas) - mantendo a primeira.[/dim]"
                )
        except Exception as e:
            debug_log(f"ETAPA 4c - falhou (não-fatal): {e}")
            console.print(
                f"[yellow]AVISO[/yellow] Não consegui separar o vocal de novo ({e}) - "
                "mantendo o alinhamento que já temos."
            )

    stats = alignment_stats(word_timings)
    by_source = stats["by_source"]
    interpolated_count = by_source["interpolated"]
    console.print(f"[green]OK[/green] {len(word_timings)} palavras processadas.")
    console.print(
        f"    [dim]{by_source['anchor']} âncora exata / {by_source['fuzzy']} fuzzy / "
        f"{by_source['realign']} realinhadas no 2º passe / "
        f"{by_source['lrc']} início de linha (.lrc) / "
        f"{interpolated_count} interpoladas (estimadas)[/dim]"
    )
    if interpolated_count:
        pct = 100 * interpolated_count / len(word_timings)
        console.print(
            f"[yellow]AVISO[/yellow] {pct:.1f}% das palavras ficaram interpoladas "
            "(não foi possível medi-las no áudio, nem no 2º passe) - "
            f"maiores sequências seguidas: {stats['interpolated_runs']}."
        )
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
            console.print(
                f"[bold red]ATENÇÃO[/bold red] A MAIORIA das palavras ({pct:.0f}%) é "
                "estimativa - o alinhamento não conseguiu reconhecer o canto nesta "
                "música. O pacote provavelmente sai fora de sincronia."
            )
            console.print(
                "    [yellow]VALE GERAR ESTA MÚSICA DE NOVO: a separação de voz do Demucs "
                "varia a cada tentativa (mesma entrada, saída diferente - verificado por "
                "hash), e uma separação ruim derruba o alinhamento inteiro. Normalmente a "
                "2ª tentativa funciona. Se repetir, confira se a letra bate com ESTA "
                "gravação (versão ao vivo, remix e refrão escrito uma vez só atrapalham)."
                "[/yellow]"
            )
            debug_log(f"ALINHAMENTO FALHOU: {pct:.1f}% interpoladas")

    # Aviso "ancorado mas ERRADO" (issue nova, achado no n=60): independente do
    # interp. Quando o Whisper reconheceu POUCO da letra (word-recall baixo), as
    # âncoras que ele colocou podem estar nas palavras erradas - e isso passa
    # batido pelo aviso de interpolação (a música pode estar quase toda
    # "ancorada", só que no lugar errado).
    measured = by_source["anchor"] + by_source["fuzzy"]
    wrecall = measured / max(len(word_timings), 1)
    if wrecall < WHISPER_RECALL_FLOOR and pct <= ALIGNMENT_FAILED_PCT:
        # o "pct <= ..." evita avisar duas vezes a mesma música (se o interp já
        # disparou o alarme forte acima, não repete)
        console.print(
            f"[bold red]ATENÇÃO[/bold red] O reconhecimento da letra ficou baixo "
            f"({100*wrecall:.0f}% das palavras) - o Whisper pode ter entendido outra "
            "coisa e ancorado no lugar errado. O pacote pode sair fora de sincronia."
        )
        console.print(
            "    [yellow]Vale conferir a sincronia e, se estiver ruim, GERAR DE NOVO "
            "(a separação de voz varia a cada tentativa). Confira também se a letra bate "
            "com ESTA gravação.[/yellow]"
        )
        debug_log(f"WORD-RECALL BAIXO: {100*wrecall:.0f}% (âncoras podem estar erradas)")

    # Checagem de cobertura: avisa se a letra termina muito antes do áudio
    # (refrão repetido escrito só uma vez - erro comum de letras "(2x)").
    if word_timings:
        last_word_end = max(w.end for w in word_timings)
        audio_duration = get_audio_duration_seconds(stems.vocals)
        uncovered = audio_duration - last_word_end
        debug_log(f"Cobertura da letra: última palavra em {last_word_end:.1f}s de {audio_duration:.1f}s totais")
        if uncovered > 10.0:
            console.print(
                f"[yellow]AVISO[/yellow] A letra fornecida termina em {last_word_end:.1f}s, mas o áudio "
                f"tem {audio_duration:.1f}s ({uncovered:.1f}s sem nenhuma palavra no final). "
                "Isso costuma acontecer quando um refrão/trecho repetido foi escrito só uma vez na letra "
                "(ex.: letras de sites que usam \"(2x)\"/\"(4x)\" em vez de repetir o texto por extenso). "
                "Se for o caso, reescreva a letra repetindo o trecho tantas vezes quanto ele é cantado."
            )

    console.rule("[bold cyan]Etapa 5/6 — Buscando metadados (capa, ano, gênero)")
    debug_log("ETAPA 5 - iniciando fetch_metadata")
    # Base dos nomes de arquivo do pacote. SANITIZADA: o texto do usuário pode
    # trazer caractere que o Windows não aceita ("Quem?") ou que muda o caminho
    # ("AC/DC", "Song 2: Live") - ver pipeline/filenames.py. O título/artista
    # ORIGINAIS seguem intactos para os headers e as buscas de metadado.
    file_base = sanitize_filename(f"{artist} - {title}")

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
    console.print(f"[green]OK[/green] Metadados (fonte: {metadata.source}):")
    console.print(
        f"    [dim]ano={metadata.year or '—'} / gênero={metadata.genre or '—'} / "
        f"capa={'sim' if metadata.cover_path else 'não'} / "
        f"fundo={'fanart.tv' if metadata.background_path else 'capa' if metadata.cover_path else 'não'}[/dim]"
    )

    console.rule("[bold cyan]Etapa 6/6 — Extraindo pitch e montando o .txt")
    debug_log("ETAPA 6 - iniciando build_song")
    final_audio_name = f"{file_base}.ogg"
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
        console.print(f"[green]OK[/green] Vídeo incluído no pacote: {video_dest}")

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
        console.print("[cyan]Convertendo faixas separadas (voz/instrumental)...[/cyan]")
        try:
            vocals_filename = f"{file_base} [VOC].ogg"
            instrumental_filename = f"{file_base} [INSTR].ogg"
            convert_to_ogg(stems.vocals, out_path / vocals_filename)
            convert_to_ogg(stems.instrumental, out_path / instrumental_filename)
            console.print(
                f"[green]OK[/green] Faixas separadas no pacote: "
                f"{vocals_filename} / {instrumental_filename}"
            )
        except Exception as e:
            # Não-fatal: o pacote é perfeitamente válido sem estas faixas (são
            # opcionais na spec). Derrubar uma geração que já deu certo por
            # causa de um extra seria desproporcional.
            vocals_filename = None
            instrumental_filename = None
            debug_log(f"Falha ao converter stems: {e}")
            console.print(f"[yellow]AVISO[/yellow] Não consegui incluir as faixas separadas: {e}")

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
        vocals_filename=vocals_filename,
        instrumental_filename=instrumental_filename,
    )
    debug_log("ETAPA 6 - build_song concluído, escrevendo .txt")

    txt_path = out_path / f"{file_base}.txt"
    song.write(str(txt_path))
    console.print(f"[green]OK[/green] Arquivo UltraStar gerado (Python): {txt_path}")

    json_path = out_path / "song_data.json"
    song.write_json(str(json_path))
    console.print(f"[green]OK[/green] JSON intermediário exportado: {json_path}")

    debug_log("Convertendo áudio final para .ogg")
    final_audio_dest = out_path / final_audio_name
    convert_to_ogg(source.audio_wav, final_audio_dest)
    console.print(f"[green]OK[/green] Áudio convertido para .ogg: {final_audio_dest}")

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
            console.print(f"[green]OK[/green] Intermediários removidos: {work_path}")
        except Exception as e:
            debug_log(f"Falha ao limpar _work (ignorada): {e}")
            console.print(
                f"[yellow]AVISO[/yellow] Não consegui remover a pasta de intermediários "
                f"({work_path}): {e}. O pacote final está OK; a pasta pode ser apagada à mão."
            )

    debug_log("Pipeline concluída com sucesso.")
    console.rule("[bold green]Pipeline concluída")
    console.print(f"Pasta pronta em: [bold]{out_path}[/bold]")
    console.print(
        "[yellow]Lembrete:[/yellow] confira o .txt manualmente contra a spec oficial e "
        "teste carregando no UltraStar Deluxe antes de considerar definitivo."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="USKMaker - pipeline completa")
    parser.add_argument("--url", help="Link do YouTube")
    parser.add_argument("--file", help="Caminho de mp3/wav local")
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
    parser.add_argument(
        "--synced-lyrics",
        default=None,
        help="Arquivo .lrc (letra sincronizada, ex.: LRCLIB) para semear âncoras de início de linha",
    )
    args = parser.parse_args()

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
            synced_lyrics_path=args.synced_lyrics,
        )
    except Exception:
        debug_log("EXCEÇÃO NÃO TRATADA:\n" + traceback.format_exc())
        raise

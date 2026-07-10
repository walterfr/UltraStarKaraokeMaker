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
from pipeline.metadata import fetch_metadata
from pipeline.proc_utils import run_subprocess
from pipeline.separate import separate_vocals

# Quando o stdout/stderr do Python não está conectado a um terminal real (é
# o caso ao rodar via Tauri), o Python usa buffer em bloco por padrão.
# Forçar line_buffering garante que cada linha seja enviada imediatamente.
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

console = Console()

_debug_log_path: Path | None = None


def debug_log(message: str) -> None:
    """Grava uma linha de log em disco, com timestamp e flush imediato."""
    if _debug_log_path is None:
        return
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    with open(_debug_log_path, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")
        f.flush()


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
        "ffmpeg", "-y",
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
        stems.vocals, Path(lyrics_path), language=language, device=device
    )
    debug_log(f"ETAPA 4 - concluída. {len(word_timings)} palavras")

    stats = alignment_stats(word_timings)
    by_source = stats["by_source"]
    interpolated_count = by_source["interpolated"]
    console.print(f"[green]OK[/green] {len(word_timings)} palavras processadas.")
    console.print(
        f"    [dim]{by_source['anchor']} âncora exata / {by_source['fuzzy']} fuzzy / "
        f"{by_source['realign']} realinhadas no 2º passe / "
        f"{interpolated_count} interpoladas (estimadas)[/dim]"
    )
    if interpolated_count:
        pct = 100 * interpolated_count / len(word_timings)
        console.print(
            f"[yellow]AVISO[/yellow] {pct:.1f}% das palavras ficaram interpoladas "
            "(não foi possível medi-las no áudio, nem no 2º passe) - "
            f"maiores sequências seguidas: {stats['interpolated_runs']}."
        )

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
    # Nome de capa no padrão UltraStar profissional: "Artista - Título [CO].jpg"
    cover_path = out_path / f"{artist} - {title} [CO].jpg"
    metadata = fetch_metadata(
        audio_path=source.audio_wav,
        artist=artist,
        title=title,
        out_cover_path=cover_path,
        use_network=True,
    )
    debug_log(
        f"ETAPA 5 - concluída. fonte={metadata.source} ano={metadata.year} "
        f"gênero={metadata.genre} capa={metadata.cover_path}"
    )
    console.print(f"[green]OK[/green] Metadados (fonte: {metadata.source}):")
    console.print(
        f"    [dim]ano={metadata.year or '—'} / gênero={metadata.genre or '—'} / "
        f"capa={'sim' if metadata.cover_path else 'não'}[/dim]"
    )

    console.rule("[bold cyan]Etapa 6/6 — Extraindo pitch e montando o .txt")
    debug_log("ETAPA 6 - iniciando build_song")
    final_audio_name = f"{artist} - {title}.ogg"
    cover_filename = metadata.cover_path.name if metadata.cover_path else None

    # Se um vídeo foi baixado, copia para o pacote com o nome padrão
    # UltraStar ("Artista - Título.mp4") e referencia na tag #VIDEO.
    video_filename = None
    if source.video_path and source.video_path.exists():
        video_ext = source.video_path.suffix.lower() or ".mp4"
        video_filename = f"{artist} - {title}{video_ext}"
        video_dest = out_path / video_filename
        shutil.copy(source.video_path, video_dest)
        debug_log(f"Vídeo copiado para o pacote: {video_dest}")
        console.print(f"[green]OK[/green] Vídeo incluído no pacote: {video_dest}")

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
    )
    debug_log("ETAPA 6 - build_song concluído, escrevendo .txt")

    txt_path = out_path / f"{artist} - {title}.txt"
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
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
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
        )
    except Exception:
        debug_log("EXCEÇÃO NÃO TRATADA:\n" + traceback.format_exc())
        raise

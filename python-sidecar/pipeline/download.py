"""
download.py
Etapa 1 da pipeline: obter um arquivo de áudio local a partir de um link do
YouTube, ou simplesmente validar/normalizar um mp3 já fornecido pelo usuário.

FASE 3 (complemento, 06/07/2026): agora suporta também baixar o VÍDEO do
YouTube (opcional, opt-in via flag), para incluir no pacote UltraStar e ter
fundo animado no jogo (tag #VIDEO). O download de vídeo é opcional porque é
custoso (arquivos grandes, mais banda/tempo) e a maioria dos pacotes quer só
letra+áudio - quem não pede vídeo não paga esse custo.

Uso isolado (teste manual):
    python -m pipeline.download --url "https://youtu.be/XXXXX" --out ./work/raw
    python -m pipeline.download --url "https://youtu.be/XXXXX" --out ./work/raw --with-video
    python -m pipeline.download --file "C:/musicas/minha_musica.mp3" --out ./work/raw
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from .proc_utils import run_subprocess


@dataclass
class SourceAudio:
    """
    Resultado da etapa 1. `audio_wav` é sempre preenchido; `video_path` só
    quando o vídeo foi baixado do YouTube (fonte local nunca traz vídeo,
    e download de vídeo é opt-in).
    """
    audio_wav: Path
    video_path: Path | None = None


def _yt_dlp_base_cmd() -> list[str]:
    # yt-dlp invocado como MÓDULO do interpretador atual (sys.executable -m
    # yt_dlp), não pelo nome "yt-dlp" no PATH. Ver histórico de bug detalhado
    # abaixo - resumindo: via Tauri o venv não está ativado, então o
    # executável "yt-dlp" não está no PATH, mas o módulo yt_dlp está
    # instalado no venv e é encontrado por sys.executable. Nome do módulo
    # usa underscore (yt_dlp), o comando usa hífen (yt-dlp).
    return [sys.executable, "-m", "yt_dlp"]


def download_from_youtube(url: str, out_dir: Path) -> Path:
    """
    Baixa SÓ o áudio (melhor qualidade) de um vídeo do YouTube e converte
    para .wav. Usado quando o usuário não pediu o vídeo no pacote - é o
    caminho mais leve.

    Retorna o caminho do arquivo .wav gerado.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(out_dir / "%(title)s.%(ext)s")

    # HISTÓRICO DE BUG (06/07/2026): antes chamava "yt-dlp" direto pelo nome,
    # dependendo de ele estar no PATH. Funcionava com o venv ATIVADO, mas
    # quebrava via Tauri com FileNotFoundError [WinError 2] - o Tauri chama o
    # python.exe do venv DIRETAMENTE, sem ativar o venv. Corrigido invocando
    # como módulo (ver _yt_dlp_base_cmd).
    cmd = _yt_dlp_base_cmd() + [
        "-x",  # extrair só o áudio
        "--audio-format", "wav",
        "--audio-quality", "0",  # melhor qualidade
        "-o", output_template,
        url,
    ]

    # NOTA: se o YouTube pedir autenticação (idade/região), gere um cookies.txt
    # e adicione "--cookies", "cookies.txt" na lista acima.

    run_subprocess(cmd)

    wav_files = sorted(out_dir.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not wav_files:
        raise RuntimeError("yt-dlp rodou mas nenhum .wav foi encontrado em " + str(out_dir))
    return wav_files[0]


def download_from_youtube_with_video(url: str, out_dir: Path) -> SourceAudio:
    """
    Baixa o VÍDEO do YouTube (preferindo mp4) UMA vez e extrai o áudio dele
    localmente via ffmpeg - assim há apenas UMA transferência de rede, em
    vez de baixar áudio e vídeo separadamente.

    Retorna SourceAudio com audio_wav E video_path preenchidos.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(out_dir / "%(title)s.%(ext)s")

    # Baixa o melhor vídeo mp4 + melhor áudio m4a e combina em mp4. O formato
    # mp4 é o que o UltraStar lê melhor; se o YouTube só tiver webm, o yt-dlp
    # ainda entrega webm e o UltraStar moderno também lê, mas mp4 é o alvo
    # preferencial por compatibilidade máxima.
    cmd = _yt_dlp_base_cmd() + [
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "-o", output_template,
        url,
    ]
    run_subprocess(cmd)

    # Descobre o arquivo de vídeo recém-baixado (mais recente na pasta, entre
    # as extensões de vídeo comuns que o yt-dlp pode ter entregue).
    video_candidates: list[Path] = []
    for ext in ("*.mp4", "*.webm", "*.mkv"):
        video_candidates.extend(out_dir.glob(ext))
    if not video_candidates:
        raise RuntimeError("yt-dlp rodou mas nenhum vídeo foi encontrado em " + str(out_dir))
    video_path = max(video_candidates, key=lambda p: p.stat().st_mtime)

    # Extrai o áudio do vídeo já baixado (sem nova transferência de rede),
    # para .wav, mantendo consistência com o resto da pipeline.
    audio_wav = out_dir / (video_path.stem + ".wav")
    cmd_extract = ["ffmpeg", "-y", "-i", str(video_path), "-vn", str(audio_wav)]
    run_subprocess(cmd_extract)

    if not audio_wav.exists():
        raise RuntimeError(f"Falha ao extrair áudio do vídeo baixado: {video_path}")

    return SourceAudio(audio_wav=audio_wav, video_path=video_path)


def normalize_local_file(file_path: Path, out_dir: Path) -> Path:
    """
    Para um mp3/wav local: copia para a pasta de trabalho e garante .wav
    (via ffmpeg) para manter consistência com o resto da pipeline.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    dest_wav = out_dir / (file_path.stem + ".wav")

    if file_path.suffix.lower() == ".wav":
        shutil.copy(file_path, dest_wav)
        return dest_wav

    # NOTA sobre o ffmpeg vs yt-dlp: o ffmpeg é um BINÁRIO de sistema (não um
    # módulo Python), instalado no PATH global do Windows - por isso ele
    # continua funcionando via Tauri mesmo sem o venv ativado, e não precisa
    # do mesmo tratamento "sys.executable -m ..." que aplicamos ao yt-dlp.
    cmd = ["ffmpeg", "-y", "-i", str(file_path), str(dest_wav)]
    run_subprocess(cmd)
    return dest_wav


def get_source_audio(
    url: str | None,
    file: str | None,
    out_dir: Path,
    with_video: bool = False,
) -> SourceAudio:
    """
    Ponto de entrada da etapa 1. Sempre retorna um SourceAudio.

    with_video: só tem efeito para fonte YouTube. Quando True, baixa o vídeo
    e o inclui no resultado (para virar #VIDEO no pacote). Para fonte local
    (--file), não há vídeo a incluir e o flag é ignorado.
    """
    if not url and not file:
        raise ValueError("Forneça --url (YouTube) ou --file (mp3/wav local).")

    if url:
        if with_video:
            return download_from_youtube_with_video(url, out_dir)
        return SourceAudio(audio_wav=download_from_youtube(url, out_dir))

    # fonte local: nunca há vídeo
    return SourceAudio(audio_wav=normalize_local_file(Path(file), out_dir))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Etapa 1: obter áudio fonte (Fase 0 - teste isolado)")
    parser.add_argument("--url", help="Link do YouTube")
    parser.add_argument("--file", help="Caminho de mp3/wav local")
    parser.add_argument("--out", default="./work/raw", help="Pasta de saída")
    parser.add_argument("--with-video", action="store_true", help="Baixar também o vídeo (só YouTube)")
    args = parser.parse_args()

    result = get_source_audio(args.url, args.file, Path(args.out), with_video=args.with_video)
    print(f"[OK] Áudio pronto em: {result.audio_wav}")
    if result.video_path:
        print(f"[OK] Vídeo baixado em: {result.video_path}")

"""
video_sync.py
Sincronização entre áudio e vídeo avulso de fundo via correlação cruzada de envelopes de transientes (onset strength).
Mede a diferença temporal (offset) entre a trilha de áudio da música e a trilha de áudio do vídeo,
produzindo a tag #VIDEOGAP no formato UltraStar.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import librosa
import numpy as np
import scipy.signal as signal

from .proc_utils import ffmpeg_exe


def estimate_video_offset(
    audio_path: Path,
    video_path: Path,
    work_dir: Path | None = None,
    sr: int = 16000,
    hop_length: int = 160,
    min_confidence_ratio: float = 3.5,
) -> float | None:
    """
    Estima a tag #VIDEOGAP (em segundos) comparando o áudio da música com o áudio do vídeo.
    Retorna o valor em segundos para a tag #VIDEOGAP, ou None se não houver áudio no vídeo
    ou a correlação não for estatisticamente confiável.

    Convenção UltraStar:
      - VIDEOGAP > 0: o vídeo começa X segundos APÓS o início da música.
      - VIDEOGAP < 0: o vídeo começa X segundos ANTES do início da música (ex: videoclipe com introdução).
    """
    if not audio_path.exists() or not video_path.exists():
        return None

    temp_audio: Path | None = None
    try:
        if work_dir is None:
            temp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            temp_audio = Path(temp_file.name)
            temp_file.close()
        else:
            work_dir.mkdir(parents=True, exist_ok=True)
            temp_audio = work_dir / f"_video_audio_{video_path.stem}.wav"

        # Extrai áudio mono 16kHz do vídeo via ffmpeg
        cmd = [
            ffmpeg_exe(),
            "-y",
            "-i", str(video_path),
            "-vn",
            "-ac", "1",
            "-ar", str(sr),
            str(temp_audio),
        ]
        res = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if res.returncode != 0 or not temp_audio.exists() or temp_audio.stat().st_size < 1000:
            return None

        # Carrega os áudios
        y_audio, _ = librosa.load(str(audio_path), sr=sr, mono=True)
        y_video, _ = librosa.load(str(temp_audio), sr=sr, mono=True)

        min_len_samples = sr * 5  # mínimo 5 segundos
        if len(y_audio) < min_len_samples or len(y_video) < min_len_samples:
            return None

        # Calcula envelope de onset strength
        env_audio = librosa.onset.onset_strength(y=y_audio, sr=sr, hop_length=hop_length)
        env_video = librosa.onset.onset_strength(y=y_video, sr=sr, hop_length=hop_length)

        if len(env_audio) == 0 or len(env_video) == 0:
            return None

        # Correlação cruzada
        corr = signal.correlate(env_video, env_audio, mode="full")
        lags = signal.correlation_lags(len(env_video), len(env_audio), mode="full")

        peak_idx = int(np.argmax(corr))
        peak_val = float(corr[peak_idx])
        mean_val = float(np.mean(np.abs(corr)))

        if mean_val <= 1e-9 or peak_val <= 0:
            return None

        ratio = peak_val / (mean_val + 1e-8)
        if ratio < min_confidence_ratio:
            return None

        best_lag = lags[peak_idx]
        delta_t = float(best_lag * (hop_length / sr))

        # video_time = audio_time + delta_t => VIDEOGAP = -delta_t
        videogap = -delta_t
        return round(videogap, 2)

    except Exception:
        return None
    finally:
        if temp_audio and temp_audio.exists():
            try:
                temp_audio.unlink()
            except Exception:
                pass

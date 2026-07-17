# -*- coding: utf-8 -*-
"""
Testes de dois bugs de ambiente/rede reportados por usuários (17/07/2026):

1. Link de YouTube com "&list=..." baixava a PLAYLIST INTEIRA (o usuário cola
   um clipe e recebe uma dúzia de músicas) -> --no-playlist no comando base.
2. `whisperx.load_audio`/`pyannote` chamam "ffmpeg" CRU por subprocess, sem
   passar pelo ffmpeg_exe(); quem não tinha ffmpeg no PATH do sistema quebrava
   no alinhamento com WinError 2 -> ensure_ffmpeg_on_path() põe a pasta do
   ffmpeg embutido no PATH.

Sem rede: só a montagem do comando e a manipulação de env.

Rodar:  python tests/test_download_env_logic.py
"""
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from pipeline import download, proc_utils


# --- bug 1: --no-playlist -----------------------------------------------------

def test_no_playlist_no_comando_base():
    # base sem USKMAKER_FFMPEG ainda tem que ter --no-playlist
    old = os.environ.pop("USKMAKER_FFMPEG", None)
    try:
        cmd = download._yt_dlp_base_cmd()
    finally:
        if old is not None:
            os.environ["USKMAKER_FFMPEG"] = old
    assert "--no-playlist" in cmd


def test_no_playlist_vale_para_audio_e_video():
    # os dois caminhos principais herdam do base -> os dois pegam a flag.
    # (verificamos via o base, que ambos concatenam)
    assert download._yt_dlp_base_cmd().count("--no-playlist") == 1


def test_ffmpeg_location_ainda_e_passado_quando_ha_embutido():
    os.environ["USKMAKER_FFMPEG"] = r"C:\fake\bin\ffmpeg.exe"
    try:
        cmd = download._yt_dlp_base_cmd()
    finally:
        os.environ.pop("USKMAKER_FFMPEG", None)
    assert "--ffmpeg-location" in cmd
    assert "--no-playlist" in cmd  # os dois convivem


# --- bug 2: ensure_ffmpeg_on_path --------------------------------------------

def _run_with_env(ffmpeg_val, path_val, fn):
    old_ff = os.environ.get("USKMAKER_FFMPEG")
    old_path = os.environ.get("PATH")
    try:
        if ffmpeg_val is None:
            os.environ.pop("USKMAKER_FFMPEG", None)
        else:
            os.environ["USKMAKER_FFMPEG"] = ffmpeg_val
        os.environ["PATH"] = path_val
        fn()
        return os.environ.get("PATH")
    finally:
        if old_ff is None:
            os.environ.pop("USKMAKER_FFMPEG", None)
        else:
            os.environ["USKMAKER_FFMPEG"] = old_ff
        if old_path is not None:
            os.environ["PATH"] = old_path


def test_prepende_a_pasta_do_ffmpeg_embutido():
    new_path = _run_with_env(r"C:\Users\x\AppData\Local\USKMaker\bin\ffmpeg.exe",
                             r"C:\Windows", proc_utils.ensure_ffmpeg_on_path)
    first = new_path.split(os.pathsep)[0]
    assert first == r"C:\Users\x\AppData\Local\USKMaker\bin"
    assert r"C:\Windows" in new_path  # o PATH antigo continua lá


def test_idempotente_nao_duplica():
    def twice():
        proc_utils.ensure_ffmpeg_on_path()
        proc_utils.ensure_ffmpeg_on_path()
    new_path = _run_with_env(r"C:\ff\bin\ffmpeg.exe", r"C:\Windows", twice)
    assert new_path.split(os.pathsep).count(r"C:\ff\bin") == 1


def test_sem_ffmpeg_embutido_nao_mexe_no_path():
    # dev com ffmpeg no PATH do sistema: sem USKMAKER_FFMPEG, PATH intacto
    new_path = _run_with_env(None, r"C:\Windows;C:\bin",
                             proc_utils.ensure_ffmpeg_on_path)
    assert new_path == r"C:\Windows;C:\bin"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"[OK]   {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"[FAIL] {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} testes passaram")
    sys.exit(1 if failed else 0)

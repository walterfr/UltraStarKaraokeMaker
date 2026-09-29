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

def _run_with_env(ffmpeg_val, path_val, fn, local_app_data=None):
    old_ff = os.environ.get("USKMAKER_FFMPEG")
    old_path = os.environ.get("PATH")
    old_local_app_data = os.environ.get("LOCALAPPDATA")
    old_xdg_data_home = os.environ.get("XDG_DATA_HOME")
    old_home = os.environ.get("HOME")
    try:
        if ffmpeg_val is None:
            os.environ.pop("USKMAKER_FFMPEG", None)
        else:
            os.environ["USKMAKER_FFMPEG"] = ffmpeg_val
        if local_app_data is None:
            os.environ.pop("LOCALAPPDATA", None)
            os.environ.pop("XDG_DATA_HOME", None)
            os.environ.pop("HOME", None)
        else:
            os.environ["LOCALAPPDATA"] = str(local_app_data)
            os.environ["XDG_DATA_HOME"] = str(local_app_data)
        os.environ["PATH"] = path_val
        fn()
        return os.environ.get("PATH")
    finally:
        if old_ff is None:
            os.environ.pop("USKMAKER_FFMPEG", None)
        else:
            os.environ["USKMAKER_FFMPEG"] = old_ff
        if old_local_app_data is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = old_local_app_data
        if old_xdg_data_home is None:
            os.environ.pop("XDG_DATA_HOME", None)
        else:
            os.environ["XDG_DATA_HOME"] = old_xdg_data_home
        if old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old_home
        if old_path is not None:
            os.environ["PATH"] = old_path


# Caminhos montados com os.path.join/os.pathsep: com barra invertida fixa
# ("C:\\ff\\bin\\ffmpeg.exe") o teste só passava no Windows - no Linux o
# dirname disso é "" e o ':' do "C:" ainda quebra o split do PATH.
_FF_DIR = os.path.join(os.sep, "ff", "bin")
_FF_EXE = os.path.join(_FF_DIR, "ffmpeg.exe")
_SYS_DIR = os.path.join(os.sep, "sys")
_BIN_DIR = os.path.join(os.sep, "bin")


def test_prepende_a_pasta_do_ffmpeg_embutido():
    new_path = _run_with_env(_FF_EXE, _SYS_DIR, proc_utils.ensure_ffmpeg_on_path)
    first = new_path.split(os.pathsep)[0]
    assert first == _FF_DIR
    assert _SYS_DIR in new_path.split(os.pathsep)  # o PATH antigo continua lá


def test_idempotente_nao_duplica():
    def twice():
        proc_utils.ensure_ffmpeg_on_path()
        proc_utils.ensure_ffmpeg_on_path()
    new_path = _run_with_env(_FF_EXE, _SYS_DIR, twice)
    assert new_path.split(os.pathsep).count(_FF_DIR) == 1


def test_sem_ffmpeg_embutido_nao_mexe_no_path():
    # dev com ffmpeg no PATH do sistema: sem USKMAKER_FFMPEG, PATH intacto
    original = os.pathsep.join([_SYS_DIR, _BIN_DIR])
    new_path = _run_with_env(None, original, proc_utils.ensure_ffmpeg_on_path)
    assert new_path == original


def test_pasta_de_ferramentas_entra_no_path_sem_ffmpeg_embutido(tmp_path):
    # Se o download do ffmpeg falhar, o Deno na mesma pasta ainda precisa ser
    # encontrado pelo yt-dlp para resolver os desafios JavaScript do YouTube.
    tools_dir = tmp_path / "USKMaker" / "bin"
    tools_dir.mkdir(parents=True)
    new_path = _run_with_env(
        None, _SYS_DIR, proc_utils.ensure_ffmpeg_on_path,
        local_app_data=tmp_path,
    )
    assert new_path.split(os.pathsep)[0] == str(tools_dir)
    assert _SYS_DIR in new_path.split(os.pathsep)


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

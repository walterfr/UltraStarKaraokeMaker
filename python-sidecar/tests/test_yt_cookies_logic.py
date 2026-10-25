# -*- coding: utf-8 -*-
"""
Cookies do YouTube (configuração "YouTube cookies") e a pasta bin do USKMaker
no PATH (Deno para o yt-dlp) - lógica pura, sem rede.

Rodar:  python -m pytest tests/ -v
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import proc_utils
from pipeline.download import _yt_dlp_base_cmd
from read_video_info import classify_error


def test_cookie_browser_off_by_default_and_validated(monkeypatch):
    monkeypatch.delenv("USKMAKER_YT_COOKIES_BROWSER", raising=False)
    assert proc_utils.yt_cookies_browser() is None
    monkeypatch.setenv("USKMAKER_YT_COOKIES_BROWSER", " Firefox ")
    assert proc_utils.yt_cookies_browser() == "firefox"
    monkeypatch.setenv("USKMAKER_YT_COOKIES_BROWSER", "firefox; rm -rf /")
    assert proc_utils.yt_cookies_browser() is None  # unknown value = off


def test_download_command_carries_the_cookie_browser(monkeypatch):
    monkeypatch.delenv("USKMAKER_YT_COOKIES_BROWSER", raising=False)
    assert "--cookies-from-browser" not in _yt_dlp_base_cmd()
    monkeypatch.setenv("USKMAKER_YT_COOKIES_BROWSER", "chrome")
    cmd = _yt_dlp_base_cmd()
    i = cmd.index("--cookies-from-browser")
    assert cmd[i + 1] == "chrome"


def test_data_bin_dir_goes_on_path_without_bundled_ffmpeg(monkeypatch, tmp_path):
    # Linux: ffmpeg from the distro (no USKMAKER_FFMPEG), Deno installed by the
    # setup in <data>/bin - that folder must still reach the PATH.
    (tmp_path / "USKMaker" / "bin").mkdir(parents=True)
    monkeypatch.delenv("USKMAKER_FFMPEG", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setattr(proc_utils, "data_dir", lambda: tmp_path / "USKMaker")
    proc_utils.ensure_ffmpeg_on_path()
    parts = os.environ["PATH"].split(os.pathsep)
    assert parts[0] == str(tmp_path / "USKMaker" / "bin")
    proc_utils.ensure_ffmpeg_on_path()  # idempotent
    assert os.environ["PATH"].split(os.pathsep).count(str(tmp_path / "USKMaker" / "bin")) == 1


def test_missing_bin_dir_leaves_path_alone(monkeypatch, tmp_path):
    monkeypatch.delenv("USKMAKER_FFMPEG", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setattr(proc_utils, "data_dir", lambda: tmp_path / "USKMaker")
    proc_utils.ensure_ffmpeg_on_path()
    assert os.environ["PATH"] == "/usr/bin"


def test_video_info_errors_are_classified():
    assert classify_error("[youtube] x: Sign in to confirm you’re not a bot. Use --cookies-from-browser") == "bot"
    assert classify_error("Sign in to confirm your age") == "age"
    assert classify_error("could not find firefox cookies database in /home/x") == "cookies"
    assert classify_error("Private video") == "private"
    assert classify_error("Video unavailable") == "unavailable"
    assert classify_error("timed out") == "other"

def test_cookie_database_locked_friendly_error():
    from pipeline.download import _friendly_download_error
    assert classify_error('Could not copy Chrome cookie database. See https://github.com/yt-dlp/yt-dlp/issues/7271') == 'cookies'
    msg = _friendly_download_error('Could not copy Chrome cookie database. See https://github.com/yt-dlp/yt-dlp/issues/7271')
    assert 'cookies' in msg.lower() or 'navegador' in msg.lower()

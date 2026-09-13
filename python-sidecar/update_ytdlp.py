#!/usr/bin/env python3
"""
update_ytdlp.py
Mantém o yt-dlp em dia. O app chama isto ao abrir, em segundo plano.

POR QUE ISTO EXISTE: o yt-dlp ENVELHECE RÁPIDO. O YouTube muda o site e o
download quebra até sair versão nova - e a versão instalada não se atualiza
sozinha depois do setup. Um usuário viu "HTTP Error 403: Forbidden" com uma
instalação que tinha só dois meses (02/09/2026).

A ARMADILHA DO CANAL (é o ponto principal deste arquivo):
o yt-dlp publica um canal ESTÁVEL e um canal de TESTE (nightly). Quando o
YouTube quebra, a correção aparece no de teste primeiro - então quem teve
problema costuma estar justamente nele, numa versão MAIS NOVA que qualquer
estável. Um "instale a última versão" ingênuo olha o estável, acha que é mais
recente e faz DOWNGRADE - devolvendo exatamente o erro que a pessoa já tinha
resolvido. Por isso detectamos o canal instalado e ficamos NELE.

Não comparamos versões na mão de propósito: o `uv pip install --upgrade`
resolve e instala só se houver algo mais novo. Se já estiver em dia, é uma
verificação rápida e nada acontece. Menos código nosso pra errar.

Uso:   python update_ytdlp.py [--check-only]
Saída: JSON {"before","after","changed","channel","ok","message"}
Nunca sai com traceback: falhar aqui não pode impedir ninguém de usar o app.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Marcadores de versão de PRÉ-LANÇAMENTO no esquema do yt-dlp
# (ex.: "2026.8.30.232658.dev0"). Se a instalada tem um destes, o usuário está
# no canal de teste e é lá que ele tem que continuar.
_PRERELEASE_MARKERS = ("dev", "a", "b", "rc")


def is_prerelease(version: str) -> bool:
    """
    True se `version` é do canal de teste.

    Cuidado com o "a" e o "b": eles só valem como marcador quando aparecem
    COLADOS num número (2026.1.1a1), não como letra solta em qualquer lugar.
    O teste ingênuo `"a" in version` daria True pra qualquer coisa.
    """
    if not version:
        return False
    v = version.strip().lower()
    if ".dev" in v or v.endswith("dev"):
        return True
    return bool(re.search(r"\d(?:a|b|rc)\d", v))


def installed_version(python_exe: str) -> str | None:
    """Versão do yt-dlp instalada no venv, ou None se não estiver instalado."""
    try:
        out = subprocess.run(
            [python_exe, "-c", "import yt_dlp,sys; sys.stdout.write(yt_dlp.version.__version__)"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, check=False,
        )
        v = (out.stdout or "").strip()
        return v or None
    except Exception:
        return None


def build_upgrade_command(uv_exe: str, python_exe: str, prerelease: bool) -> list[str]:
    """
    Comando de atualização, preservando o canal.

    "yt-dlp[default]" (e não "yt-dlp" puro) é o extra que o próprio projeto
    recomenda instalar no canal de teste - traz as dependências opcionais que
    as correções mais novas às vezes passam a exigir.
    """
    cmd = [uv_exe, "pip", "install", "--python", python_exe, "--upgrade"]
    if prerelease:
        cmd += ["--prerelease", "allow", "yt-dlp[default]"]
    else:
        cmd += ["yt-dlp"]
    return cmd


def find_uv() -> str | None:
    """O uv que o setup baixou (%LOCALAPPDATA%\\USKMaker\\bin\\uv.exe)."""
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidate = Path(local) / "USKMaker" / "bin" / "uv.exe"
        if candidate.exists():
            return str(candidate)
    from shutil import which
    return which("uv")


def update(python_exe: str, check_only: bool = False) -> dict:
    before = installed_version(python_exe)
    prerelease = is_prerelease(before or "")
    channel = "test" if prerelease else "stable"

    if before is None:
        return {"ok": False, "changed": False, "channel": channel,
                "before": None, "after": None,
                "message": "yt-dlp is not installed in this environment."}

    if check_only:
        return {"ok": True, "changed": False, "channel": channel,
                "before": before, "after": before, "message": "check only"}

    uv_exe = find_uv()
    if not uv_exe:
        return {"ok": False, "changed": False, "channel": channel,
                "before": before, "after": before,
                "message": "uv not found - cannot update yt-dlp."}

    try:
        subprocess.run(
            build_upgrade_command(uv_exe, python_exe, prerelease),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=600, check=False,
        )
    except Exception as e:
        return {"ok": False, "changed": False, "channel": channel,
                "before": before, "after": before, "message": str(e)}

    after = installed_version(python_exe) or before
    return {
        "ok": True,
        "changed": after != before,
        "channel": channel,
        "before": before,
        "after": after,
        "message": (f"yt-dlp {before} -> {after}" if after != before
                    else f"yt-dlp {after} is already current"),
    }


if __name__ == "__main__":
    result: dict = {"ok": False, "changed": False, "message": "not run"}
    try:
        result = update(sys.executable, check_only="--check-only" in sys.argv)
    except Exception as e:
        result = {"ok": False, "changed": False, "message": str(e)}
    sys.stdout.write(json.dumps(result))

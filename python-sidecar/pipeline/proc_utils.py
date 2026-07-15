"""
proc_utils.py
Helper compartilhado para rodar subprocessos (Demucs, ffmpeg, yt-dlp) de um
jeito seguro para ser chamado de dentro do Tauri.

HISTÓRICO DE BUGS (06/07/2026) - dois problemas diferentes encontrados na
mesma área de código, em sequência:

1. Primeira suspeita (parcialmente correta, mas não era a causa raiz do
   travamento investigado): subprocessos herdando o mesmo pipe do processo
   pai quando rodado via Tauri. Corrigido usando capture_output=True em vez
   de deixar o Demucs/ffmpeg escrever direto no stdout/stderr herdado.

2. CAUSA RAIZ REAL do travamento (só descoberta depois de adicionar log em
   disco + stdout/stderr com line_buffering=True para conseguir ver o
   traceback completo, que antes se perdia): `OSError: [Errno 22] Invalid
   argument` ao imprimir um bloco de texto MUITO GRANDE de uma vez via
   print(), quando o stdout está conectado a um pipe (não um terminal) no
   Windows. Isso é uma limitação conhecida do Python/Windows para escritas
   únicas muito grandes em pipes. Aconteceu especificamente com um arquivo
   FLAC que tinha uma tag LYRICS enorme embutida nos metadados, que o
   ffmpeg ecoa (duas vezes) no stderr - um bloco de texto grande o
   suficiente para estourar o limite.

CORREÇÃO: em vez de imprimir stdout/stderr como um bloco único, imprime
linha por linha - cada escrita individual fica pequena o suficiente para
nunca esbarrar nesse limite do Windows.
"""

from __future__ import annotations

import os
import subprocess


def ffmpeg_exe() -> str:
    """
    Caminho do ffmpeg a usar. Prefere o ffmpeg EMBUTIDO do USKMaker (env var
    USKMAKER_FFMPEG, apontando para o ffmpeg.exe em
    %LOCALAPPDATA%\\USKMaker\\bin, obtido pelo setup), e cai para "ffmpeg" do
    PATH quando a variável não está definida. Isso remove a exigência de ter
    o ffmpeg no PATH do sistema, mantendo compatibilidade com instalações
    antigas que dependiam dele.
    """
    return os.environ.get("USKMAKER_FFMPEG") or "ffmpeg"


def _print_captured(text: str) -> None:
    """
    Imprime um texto capturado de um subprocesso LINHA POR LINHA, nunca
    como um bloco único - ver nota do módulo sobre o OSError [Errno 22]
    que acontece no Windows ao escrever blocos grandes de uma vez num
    stdout conectado a um pipe (não um terminal).
    """
    if not text:
        return
    for line in text.splitlines():
        print(line)


def run_subprocess(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """
    Substituto seguro para `subprocess.run(cmd, check=True)` quando este
    código pode ser invocado de dentro de um processo pai que já está com
    seu próprio stdout/stderr conectado a um pipe (como o Tauri faz).

    Captura a saída do subprocesso e a imprime linha por linha via print()
    normal (que passa pelo stdout do processo Python principal, não por um
    canal compartilhado com o processo pai), evitando tanto o cenário de
    dois processos escrevendo no mesmo pipe do Windows simultaneamente
    quanto o OSError de escrita única grande demais (ver notas do módulo).

    text=True SEM encoding explícito usa o codec de locale (cp1252 no
    Windows), que estoura UnicodeDecodeError quando a saída do subprocesso
    tem bytes fora do cp1252 - ex.: yt-dlp/ffmpeg ecoando um título de vídeo
    ou uma tag de metadados com emoji/CJK. Fixar utf-8 + errors="replace"
    garante que a decodificação da saída nunca derrube o pipeline. Usamos
    setdefault para um eventual chamador ainda poder sobrescrever.
    """
    kwargs.setdefault("encoding", "utf-8")
    kwargs.setdefault("errors", "replace")
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)

    _print_captured(result.stdout)
    _print_captured(result.stderr)

    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, cmd, output=result.stdout, stderr=result.stderr
        )

    return result

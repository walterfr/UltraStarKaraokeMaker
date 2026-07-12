# -*- coding: utf-8 -*-
"""
server.py — sidecar PERSISTENTE do USKMaker.

Processa uma FILA de músicas mantendo os modelos de IA carregados entre elas.
Lê "jobs" (um JSON por linha) do stdin, roda a pipeline completa reusando os
modelos do WhisperX já carregados (ficam quentes em cache de módulo — ver
pipeline/align.py) e sinaliza a conclusão de cada job por um arquivo de status
na pasta de saída. O log humano de cada job vai para out_dir/_process_output.log
(o Rust faz tail dele), igual ao modo avulso (python main.py).

PROTOCOLO
  Entrada (stdin, uma linha JSON por job):
    {"url":..., "file":..., "lyrics_path":..., "title":..., "artist":...,
     "language":..., "out_dir":..., "bpm":..., "gap_ms":..., "device":...,
     "with_video":..., "bg_video":..., "bg_video_url":..., "clean_work":...,
     "synced_lyrics_path":...}
    {"cmd":"shutdown"}  -> encerra o servidor.

  Conclusão (out_dir/_job_status.json, escrito ao fim de cada job):
    {"status":"ok"}  ou  {"status":"error","message":"..."}

POR QUE stdin + arquivo de status (e não um pipe de stdout lido pelo Rust):
no Windows, ler o stdout de um Python por um pipe assíncrono do Tokio quebra a
escrita SÍNCRONA do Python (OSError 22 — ver a nota longa no src-tauri/src/
main.rs). Mandar jobs POR stdin (Rust escreve, Python lê — direção segura) e
sinalizar POR arquivo evita de vez esse pipe problemático. O stdout/stderr do
próprio servidor é redirecionado pelo Rust para um arquivo de sessão (só
diagnóstico); durante um job, toda a saída é capturada no log daquele job.

O primeiro job paga o custo de carregar os modelos (igual a hoje); do segundo
em diante eles já estão quentes.
"""
from __future__ import annotations

import json
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from rich.console import Console

import main as pipeline_main


def _run_one(job: dict) -> None:
    out_dir = Path(job["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "_process_output.log"
    status_path = out_dir / "_job_status.json"

    # remove status de uma execução anterior na mesma pasta (reprocessamento)
    try:
        status_path.unlink()
    except FileNotFoundError:
        pass

    # buffering=1 = line-buffered: o Rust vê cada linha do log assim que sai.
    with open(log_path, "w", encoding="utf-8", buffering=1) as f:
        # O main usa um Console global do rich; aponta ele para o arquivo deste
        # job (restaura no finally). redirect_stdout/err cobre prints normais e
        # a saída dos subprocessos (proc_utils re-imprime tudo linha por linha).
        prev_console = pipeline_main.console
        pipeline_main.console = Console(file=f, force_terminal=False)
        try:
            with redirect_stdout(f), redirect_stderr(f):
                pipeline_main.run_pipeline(
                    url=job.get("url"),
                    file=job.get("file"),
                    lyrics_path=job["lyrics_path"],
                    title=job["title"],
                    artist=job["artist"],
                    language=job.get("language", "pt"),
                    out_dir=job["out_dir"],
                    manual_bpm=job.get("bpm"),
                    manual_gap_ms=job.get("gap_ms", 0),
                    device=job.get("device", "auto"),
                    with_video=job.get("with_video", False),
                    bg_video=job.get("bg_video", False),
                    bg_video_url=job.get("bg_video_url"),
                    clean_work=job.get("clean_work", False),
                    synced_lyrics_path=job.get("synced_lyrics_path"),
                )
            status_path.write_text(json.dumps({"status": "ok"}), encoding="utf-8")
        except Exception as e:
            try:
                f.write("\n" + traceback.format_exc())
                f.flush()
            except Exception:
                pass
            status_path.write_text(
                json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False),
                encoding="utf-8",
            )
        finally:
            pipeline_main.console = prev_console


def main_loop() -> None:
    # Sinaliza prontidão no arquivo de sessão (diagnóstico); o Rust não depende
    # disso — ele só escreve o job e espera o _job_status.json aparecer.
    print("[server] USKMaker sidecar persistente pronto. Aguardando jobs...", flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            job = json.loads(line)
        except json.JSONDecodeError:
            print(f"[server] linha ignorada (JSON inválido): {line[:80]}", flush=True)
            continue
        if job.get("cmd") == "shutdown":
            print("[server] shutdown recebido. Encerrando.", flush=True)
            break
        _run_one(job)


if __name__ == "__main__":
    main_loop()

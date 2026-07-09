"""
separate.py
Etapa 2 da pipeline: separar vocal e instrumental usando Demucs.

Com uma RTX 4060 (8GB), o modelo padrão "htdemucs" roda tranquilo em GPU.
Evite "htdemucs_ft" (fine-tuned, mais pesado/lento) a menos que a qualidade
do "htdemucs" não seja suficiente - ele é ~4x mais lento.

Uso isolado (teste manual):
    python -m pipeline.separate --input ./work/raw/musica.wav --out ./work/stems
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from .proc_utils import run_subprocess


@dataclass
class Stems:
    vocals: Path
    instrumental: Path  # "no_vocals" - útil para oferecer versão instrumental


def separate_vocals(
    input_wav: Path,
    out_dir: Path,
    model: str = "htdemucs",
    device: str = "cuda",
) -> Stems:
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "demucs",  # sys.executable garante o Python do venv atual,
        # não um "python" genérico resolvido pelo PATH do sistema (que pode
        # apontar pro Python global em vez do venv, mesmo com o venv ativado -
        # foi exatamente isso que quebrou na primeira tentativa deste projeto).
        "-n", model,
        "--two-stems", "vocals",  # só separa vocal vs. resto (mais rápido que 4 stems)
        "-d", device,
        "-o", str(out_dir),
        str(input_wav),
    ]

    # DIAGNÓSTICO (06/07/2026): prints com flush=True explícito, bem antes
    # e depois do subprocess.run, para descobrir se o travamento (bug de
    # sincronia investigado hoje, aparece só via Tauri) acontece no
    # LANÇAMENTO do subprocesso do Demucs ou durante a execução dele.
    # Complementam o log em disco (pipeline_debug.log) que o main.py
    # escreve nas fronteiras de cada etapa - esses aqui dão granularidade
    # fina dentro da própria etapa 2.
    print(f"[DIAG] Prestes a chamar subprocess: {cmd}", flush=True)
    run_subprocess(cmd)
    print("[DIAG] subprocess do Demucs retornou com sucesso.", flush=True)

    # Demucs organiza a saída como: <out_dir>/<model>/<nome_do_arquivo>/vocals.wav e no_vocals.wav
    song_name = input_wav.stem
    result_dir = out_dir / model / song_name

    vocals = result_dir / "vocals.wav"
    instrumental = result_dir / "no_vocals.wav"

    if not vocals.exists() or not instrumental.exists():
        raise RuntimeError(
            f"Demucs rodou mas não encontrei os stems esperados em {result_dir}. "
            "Confira a versão do demucs instalada (a estrutura de pastas pode variar)."
        )

    return Stems(vocals=vocals, instrumental=instrumental)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Etapa 2: separação vocal (Fase 0 - teste isolado)")
    parser.add_argument("--input", required=True, help="Arquivo .wav de entrada")
    parser.add_argument("--out", default="./work/stems", help="Pasta de saída")
    parser.add_argument("--model", default="htdemucs")
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    args = parser.parse_args()

    stems = separate_vocals(Path(args.input), Path(args.out), args.model, args.device)
    print(f"[OK] Vocal isolado em: {stems.vocals}")
    print(f"[OK] Instrumental em:  {stems.instrumental}")

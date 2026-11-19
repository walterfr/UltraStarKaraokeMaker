"""
prep_stems.py
Separa os stems de um lote do harness ANTES do alinhamento, cada música num
processo novo - com a placa livre, como no app (lá a separação é a Etapa 2,
antes de qualquer modelo de alinhamento carregar). Dentro do library_replay o
MelBand Roformer rodava com o MMS/Whisper ainda na VRAM: ~50 s por pedaço de
áudio e o lote morreu sem traceback na 3ª música (14/11).

Grava vocals.wav, no_vocals.wav e lead_vocals.wav (o do resgate 4b) em
<run-dir>/cache/<música>/, onde o library_replay os reaproveita. Pula música
que já tem os três.

    python eval/prep_stems.py --lib "K:\\Ultrastar Songs" --seed-set eval_runs/seed_jul59.json \\
        --separator roformer --roformer-model vocals_mel_band_roformer.ckpt
Depois: o mesmo library_replay.py com os mesmos --separator/--roformer-model.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[0]))
sys.path.insert(0, str(_HERE))

import library_replay as lr  # noqa: E402

STEMS = ("vocals.wav", "no_vocals.wav", "lead_vocals.wav")


def one(audio: str, cache: Path, separator: str, model: str | None, device: str) -> None:
    """Filho: separa UMA música e sai (a VRAM volta inteira ao terminar)."""
    from pipeline.separate import LEAD_VOCAL_MODEL, isolate_lead_vocal, separate_vocals

    cache.mkdir(parents=True, exist_ok=True)
    tmp = cache / "demucs_tmp"
    if not ((cache / "vocals.wav").exists() and (cache / "no_vocals.wav").exists()):
        if separator == "roformer":
            stems = separate_vocals(Path(audio), tmp, device=device, backend="roformer",
                                    model=model or LEAD_VOCAL_MODEL)
        else:
            stems = separate_vocals(Path(audio), tmp, device=device)
        shutil.move(str(stems.vocals), str(cache / "vocals.wav"))
        shutil.move(str(stems.instrumental), str(cache / "no_vocals.wav"))
        shutil.rmtree(tmp, ignore_errors=True)
    if not (cache / "lead_vocals.wav").exists():
        lead = isolate_lead_vocal(cache / "vocals.wav", cache)
        if lead != cache / "lead_vocals.wav":
            shutil.move(str(lead), str(cache / "lead_vocals.wav"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--lib", default=r"K:\Ultrastar Songs")
    ap.add_argument("--seed-set", required=True)
    ap.add_argument("--separator", choices=("demucs", "roformer"), default="roformer")
    ap.add_argument("--roformer-model", default=None)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--one", nargs=2, metavar=("AUDIO", "CACHE"), help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.one:
        one(args.one[0], Path(args.one[1]), args.separator, args.roformer_model, args.device)
        return 0

    # Mesma pasta que o library_replay.main monta para estes argumentos.
    runs_root = str(_HERE.parents[0] / "eval_runs")
    run_dir = os.path.join(runs_root, "replay-seedset")
    if args.separator != "demucs":
        tag = lr.slugify(Path(args.roformer_model).stem)[:40] if args.roformer_model else "karaoke"
        run_dir += f"-{args.separator}-{tag}"
    if args.tag:
        run_dir += f"-{lr.slugify(args.tag)}"

    sample = lr.seed_set_sample(args.seed_set, lr.build_manifest(os.path.expanduser(args.lib), runs_root))
    lr.log(f"{len(sample)} músicas -> {run_dir}")
    for i, song in enumerate(sample, 1):
        cache = Path(run_dir) / "cache" / lr.slugify(song["name"])
        if all((cache / f).exists() for f in STEMS):
            continue
        t0 = time.monotonic()
        cmd = [sys.executable, __file__, "--seed-set", args.seed_set, "--separator", args.separator,
               "--device", args.device, "--one", song["mp3"], str(cache)]
        if args.roformer_model:
            cmd += ["--roformer-model", args.roformer_model]
        code = subprocess.run(cmd).returncode
        lr.log(f"[{i}/{len(sample)}] {song['name']}: {'ok' if code == 0 else f'FALHOU ({code})'} "
               f"em {time.monotonic() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

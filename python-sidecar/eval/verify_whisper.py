"""
verify_whisper.py
Gera `align_verify.json` em cada música de um lote do harness: UM alinhamento
Whisper simples (sem resgates), com o mesmo modelo do app - o que o modo
verificação (C7, main._verify_with_whisper) roda. Serve para medir o C7 com
eval/error_anatomy.py --whisper-json align_verify.json. Pula música que já tem
o arquivo. Usa GPU (~30 s por música).

    python eval/verify_whisper.py --run-dir eval_runs/replay-seedset-2_6_1
"""
import argparse
import json
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[0]))
sys.path.insert(0, str(_HERE))

import library_replay as lr  # noqa: E402
import usdx_parse  # noqa: E402


def main() -> None:
    root = _HERE.parents[0]
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--run-dir", type=Path, default=root / "eval_runs" / "replay-seedset")
    ap.add_argument("--manifest", type=Path, default=root / "eval_runs" / "library_manifest.json")
    ap.add_argument("--device", default="cuda")
    args = ap.parse_args()

    from pipeline.align import align_lyrics_to_audio

    man = {s["name"]: s for s in json.loads(args.manifest.read_text(encoding="utf-8"))["songs"]}
    kw = lr._whisper_kwargs(args.device)
    done = 0
    for p in sorted((args.run_dir / "results").glob("*.json")):
        if p.name.endswith(".error.json"):
            continue
        s = man.get(json.loads(p.read_text(encoding="utf-8"))["song"])
        cache = args.run_dir / "cache" / lr.slugify(s["name"]) if s else None
        out = cache / "align_verify.json" if cache else None
        if not cache or out.exists() or not (cache / "lyrics.txt").exists():
            continue
        language = lr.normalize_language(usdx_parse.read_file(s["gold"]).language)
        t0 = time.monotonic()
        timings = align_lyrics_to_audio(cache / "vocals.wav", cache / "lyrics.txt", language=language,
                                        device=args.device, **kw)
        out.write_text(json.dumps({"words": lr._timings_to_dicts(timings)}, ensure_ascii=False),
                       encoding="utf-8")
        done += 1
        lr.log(f"[{done}] {s['name']} ({time.monotonic() - t0:.0f} s)")


if __name__ == "__main__":
    main()

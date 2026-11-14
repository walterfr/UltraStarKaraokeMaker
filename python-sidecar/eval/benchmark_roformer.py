"""
benchmark_roformer.py
Compara Demucs (htdemucs) vs Mel-Band Roformer (UVR/audio-separator).
Mede:
- Tempo de carregamento do modelo
- Tempo de separação (wall clock)
- Consumo de VRAM de pico (GB)
- Verificação dos stems gerados (vocals / instrumental)
"""
import os
import sys
import time
from pathlib import Path
import torch

def reset_cuda():
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

def get_peak_vram_gb():
    if torch.cuda.is_available():
        return torch.cuda.max_memory_allocated() / (1024 ** 3)
    return 0.0

def run_demucs(sample_path: Path, out_dir: Path):
    print("--- [1/2] Testando Demucs v4 (htdemucs) ---")
    reset_cuda()
    t0 = time.perf_counter()

    import subprocess
    cmd = [
        sys.executable, "-m", "demucs",
        "-n", "htdemucs",
        "--two-stems", "vocals",
        "-d", "cuda",
        "-o", str(out_dir / "demucs"),
        str(sample_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    duration = time.perf_counter() - t0

    if res.returncode != 0:
        print("Demucs falhou:", res.stderr)
        return None

    # Demucs puts files in <out_dir>/demucs/htdemucs/<sample_stem>/
    stem_dir = out_dir / "demucs" / "htdemucs" / sample_path.stem
    vocals = stem_dir / "vocals.wav"
    no_vocals = stem_dir / "no_vocals.wav"
    
    print(f"Demucs concluído em {duration:.2f}s")
    print(f"Vocals: {vocals.exists()} ({vocals.stat().st_size / 1024:.1f} KB)")
    print(f"No-Vocals: {no_vocals.exists()} ({no_vocals.stat().st_size / 1024:.1f} KB)")
    return {
        "engine": "Demucs v4 (htdemucs)",
        "duration_s": duration,
        "vocals_path": vocals,
        "inst_path": no_vocals,
    }

def run_mel_band_roformer(sample_path: Path, out_dir: Path, model_filename: str):
    print(f"\n--- [2/2] Testando Mel-Band Roformer ({model_filename}) ---")
    reset_cuda()
    t0 = time.perf_counter()

    from audio_separator.separator import Separator

    target_dir = out_dir / "roformer" / sample_path.stem
    target_dir.mkdir(parents=True, exist_ok=True)

    sep = Separator(
        model_file_dir=r"C:\tmp\audio-separator-models",
        output_dir=str(target_dir),
        output_format="WAV",
    )
    t_load_start = time.perf_counter()
    sep.load_model(model_filename=model_filename)
    load_time = time.perf_counter() - t_load_start
    vram_after_load = get_peak_vram_gb()

    t_sep_start = time.perf_counter()
    output_files = sep.separate(str(sample_path))
    sep_time = time.perf_counter() - t_sep_start
    total_time = time.perf_counter() - t0
    peak_vram = get_peak_vram_gb()

    print(f"Roformer carregado em {load_time:.2f}s (VRAM: {vram_after_load:.2f} GB)")
    print(f"Separação concluída em {sep_time:.2f}s (Total: {total_time:.2f}s, Pico VRAM: {peak_vram:.2f} GB)")
    print(f"Arquivos gerados: {output_files}")
    for f in output_files:
        fp = target_dir / f
        print(f" - {f}: {fp.stat().st_size / 1024:.1f} KB")

    return {
        "engine": f"Mel-Band Roformer ({model_filename})",
        "load_time_s": load_time,
        "separation_time_s": sep_time,
        "total_time_s": total_time,
        "peak_vram_gb": peak_vram,
        "output_files": [target_dir / f for f in output_files],
    }

def main():
    sample_path = Path("python-sidecar/eval_runs/mel_roformer_benchmark/sample_30s.wav")
    out_dir = Path("python-sidecar/eval_runs/mel_roformer_benchmark")

    if not sample_path.exists():
        print(f"Amostra não encontrada: {sample_path}")
        return

    print(f"Arquivo de teste: {sample_path} (Duração: 30s)")
    if torch.cuda.is_available():
        print(f"GPU: {torch.cuda.get_device_name(0)} | VRAM Total: {torch.cuda.get_device_properties(0).total_memory / (1024**3):.2f} GB\n")

    res_demucs = run_demucs(sample_path, out_dir)
    res_roformer = run_mel_band_roformer(
        sample_path,
        out_dir,
        model_filename="mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt"
    )

    print("\n================== RESUMO DO BENCHMARK (Trecho de 30s) ==================")
    if res_demucs:
        print(f"Demucs v4 (htdemucs)        : {res_demucs['duration_s']:.2f}s")
    if res_roformer:
        print(f"Mel-Band Roformer (Karaoke) : {res_roformer['separation_time_s']:.2f}s (Pico VRAM: {res_roformer['peak_vram_gb']:.2f} GB)")
    print("=========================================================================")

if __name__ == "__main__":
    main()

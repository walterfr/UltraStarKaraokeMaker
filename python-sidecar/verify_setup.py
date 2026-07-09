"""
verify_setup.py
Checagem única de sanidade do ambiente, criada depois de uma instalação
cheia de percalços (Python 3.14 incompatível, numpy<2.0 conflitando com
whisperx, torch sendo rebaixado pra CPU pelo próprio whisperx/torchvision).

Roda isso sempre que:
  - Instalar algo novo no requirements.txt
  - Reinstalar/recriar o venv
  - Antes de rodar qualquer teste real de pipeline, se ficar muito tempo
    sem mexer no projeto e quiser confirmar que nada quebrou.

Uso:
    python verify_setup.py
"""

from __future__ import annotations

import sys

CHECKS_OK = []
CHECKS_FAIL = []


def check(name: str, fn):
    try:
        result = fn()
        CHECKS_OK.append((name, result))
        print(f"[OK] {name}: {result}")
    except Exception as e:
        CHECKS_FAIL.append((name, str(e)))
        print(f"[FALHOU] {name}: {e}")


def check_python():
    return sys.version.split()[0]


def check_torch_cuda():
    import torch
    assert torch.cuda.is_available(), "CUDA não disponível - torch caiu pra CPU de novo"
    return f"torch {torch.__version__} | GPU: {torch.cuda.get_device_name(0)}"


def check_torchaudio():
    import torchaudio
    return f"torchaudio {torchaudio.__version__}"


def check_torchvision():
    import torchvision
    return f"torchvision {torchvision.__version__}"


def check_numpy():
    import numpy
    return f"numpy {numpy.__version__}"


def check_whisperx():
    import whisperx  # noqa: F401
    return "importado com sucesso"


def check_demucs():
    # O separate.py deste projeto chama o Demucs via subprocess (`python -m
    # demucs`), não via `import demucs.api` (que nem toda versão do pacote
    # inclui). O que importa de verdade é o módulo base e o CLI existirem.
    import demucs  # noqa: F401
    import importlib.util
    if importlib.util.find_spec("demucs.separate") is None:
        raise ImportError("módulo demucs.separate não encontrado - CLI pode não funcionar")
    return "módulo base + CLI (demucs.separate) disponíveis"


def check_swift_f0():
    import swift_f0  # noqa: F401
    return "importado com sucesso"


def check_librosa():
    import librosa
    return f"librosa {librosa.__version__}"


def check_pyphen():
    import pyphen
    dic = pyphen.Pyphen(lang="pt_BR")
    return f"teste de hifenização: {dic.inserted('coracao')}"


def check_yt_dlp():
    import yt_dlp  # noqa: F401
    return "importado com sucesso"


if __name__ == "__main__":
    print("=" * 60)
    print("USKMaker - verificação de ambiente")
    print("=" * 60)

    check("Python", check_python)
    check("Torch + CUDA", check_torch_cuda)
    check("torchaudio", check_torchaudio)
    check("torchvision", check_torchvision)
    check("numpy", check_numpy)
    check("whisperx (import)", check_whisperx)
    check("demucs (import)", check_demucs)
    check("swift-f0 (import)", check_swift_f0)
    check("librosa", check_librosa)
    check("pyphen (pt_BR)", check_pyphen)
    check("yt-dlp (import)", check_yt_dlp)

    print("=" * 60)
    print(f"Resultado: {len(CHECKS_OK)} OK / {len(CHECKS_FAIL)} falharam")
    if CHECKS_FAIL:
        print("\nFalhas encontradas:")
        for name, err in CHECKS_FAIL:
            print(f"  - {name}: {err}")
        sys.exit(1)
    else:
        print("\nAmbiente pronto para os testes de pipeline (ver README.md).")

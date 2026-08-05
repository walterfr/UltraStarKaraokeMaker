# -*- coding: utf-8 -*-
"""
Test de main.resolve_device: "cpu" sempre respeitado; "cuda"/"auto" só viram
"cuda" se a GPU tiver kernel compilado pra ela (não só presença de driver) -
GPU velha (ex.: GTX 750 Ti, Maxwell sm_50) passa em is_available() mas cai
pra CPU se a capacidade dela não estiver em get_arch_list().

Usa torch FALSO (unittest.mock) - não depende da GPU real desta máquina.

Rodar:  python tests/test_resolve_device.py
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from main import resolve_device


def _fake_torch(available: bool, capability=None, arch_list=None):
    t = MagicMock()
    t.cuda.is_available.return_value = available
    if capability is not None:
        t.cuda.get_device_capability.return_value = capability
    if arch_list is not None:
        t.cuda.get_arch_list.return_value = arch_list
    return t


def test_cpu_pedido_sempre_cpu():
    assert resolve_device("cpu") == "cpu"


def test_cuda_com_capacidade_suportada():
    fake = _fake_torch(True, capability=(8, 6), arch_list=["sm_61", "sm_70", "sm_75", "sm_80", "sm_86", "sm_90"])
    with patch.dict(sys.modules, {"torch": fake}):
        assert resolve_device("cuda") == "cuda"
        assert resolve_device("auto") == "cuda"


def test_gpu_antiga_incompativel_cai_pra_cpu():
    # GTX 750 Ti: Maxwell, sm_50 - fora da lista de kernels do torch atual.
    fake = _fake_torch(True, capability=(5, 0), arch_list=["sm_61", "sm_70", "sm_75", "sm_80", "sm_86", "sm_90"])
    with patch.dict(sys.modules, {"torch": fake}):
        assert resolve_device("auto") == "cpu"


def test_sem_cuda_disponivel_cai_pra_cpu():
    fake = _fake_torch(False)
    with patch.dict(sys.modules, {"torch": fake}):
        assert resolve_device("auto") == "cpu"


if __name__ == "__main__":
    test_cpu_pedido_sempre_cpu()
    test_cuda_com_capacidade_suportada()
    test_gpu_antiga_incompativel_cai_pra_cpu()
    test_sem_cuda_disponivel_cai_pra_cpu()
    print("OK test_resolve_device")

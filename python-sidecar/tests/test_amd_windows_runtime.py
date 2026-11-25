# -*- coding: utf-8 -*-
"""
Test dos ajustes de GPU AMD no Windows (torch ROCm) em main.py:

- _prepare_amd_windows_runtime: KMP_DUPLICATE_LIB_OK=TRUE só no Windows com
  torch ROCm (lido pela versão do pacote, sem importar o torch) - sem isso o
  OpenMP da Intel (CTranslate2) aborta o processo ao achar o do torch ROCm.
- _disable_miopen_on_windows_hip: torch.backends.cudnn.enabled = False só no
  Windows com torch HIP, e USKMAKER_ENABLE_MIOPEN=1 desfaz - o MIOpen do
  Windows não compila os kernels de instance_norm/LSTM (VAD do pyannote).
- resolve_device liga os dois no caminho de sempre.

NVIDIA, CPU e Linux (onde o MIOpen funciona) não podem mudar nada.

Usa torch FALSO - não depende da GPU nem do torch desta máquina.

Rodar:  python tests/test_amd_windows_runtime.py
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import main
from main import _disable_miopen_on_windows_hip, _prepare_amd_windows_runtime, resolve_device

ROCM = "2.9.1+rocm7.13.0a20260421"
CUDA = "2.8.0+cu126"


def _fake_torch(hip):
    return SimpleNamespace(
        version=SimpleNamespace(hip=hip, cuda=None if hip else "12.6"),
        backends=SimpleNamespace(cudnn=SimpleNamespace(enabled=True)),
    )


def _kmp_after(platform, torch_version, preset=None):
    env = {} if preset is None else {"KMP_DUPLICATE_LIB_OK": preset}
    with patch.dict(os.environ, env, clear=False), patch("importlib.metadata.version", return_value=torch_version):
        if preset is None:
            os.environ.pop("KMP_DUPLICATE_LIB_OK", None)
        _prepare_amd_windows_runtime(platform)
        return os.environ.get("KMP_DUPLICATE_LIB_OK")


def test_kmp_so_no_windows_com_torch_rocm():
    assert _kmp_after("win32", ROCM) == "TRUE"


def test_kmp_nao_mexe_em_nvidia_nem_linux():
    assert _kmp_after("win32", CUDA) is None  # NVIDIA no Windows
    assert _kmp_after("linux", ROCM) is None  # ROCm no Linux: um runtime só


def test_kmp_respeita_valor_ja_definido():
    assert _kmp_after("win32", ROCM, preset="FALSE") == "FALSE"


def test_kmp_sem_torch_instalado_nao_quebra():
    with patch("importlib.metadata.version", side_effect=Exception("not installed")):
        os.environ.pop("KMP_DUPLICATE_LIB_OK", None)
        _prepare_amd_windows_runtime("win32")
        assert "KMP_DUPLICATE_LIB_OK" not in os.environ


def test_miopen_desligado_so_no_windows_com_hip():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("USKMAKER_ENABLE_MIOPEN", None)
        t = _fake_torch("7.13.26154")
        assert _disable_miopen_on_windows_hip(t, "win32") is True
        assert t.backends.cudnn.enabled is False


def test_miopen_intacto_fora_do_caso_windows_hip():
    t = _fake_torch("7.13.26154")
    assert _disable_miopen_on_windows_hip(t, "linux") is False  # Linux: MIOpen funciona
    assert t.backends.cudnn.enabled is True
    t = _fake_torch(None)  # NVIDIA: cuDNN de verdade, não mexer
    assert _disable_miopen_on_windows_hip(t, "win32") is False
    assert t.backends.cudnn.enabled is True


def test_miopen_opt_out_pela_variavel():
    with patch.dict(os.environ, {"USKMAKER_ENABLE_MIOPEN": "1"}):
        t = _fake_torch("7.13.26154")
        assert _disable_miopen_on_windows_hip(t, "win32") is False
        assert t.backends.cudnn.enabled is True


def test_resolve_device_amd_windows_liga_os_dois():
    # torch ROCm: GPU AMD aparece como "cuda", arquiteturas gfx* (sem sm_*)
    fake = MagicMock()
    fake.cuda.is_available.return_value = True
    fake.cuda.get_device_capability.return_value = (10, 3)
    fake.cuda.get_arch_list.return_value = ["gfx1030"]
    fake.version.hip = "7.13.26154"
    fake.backends.cudnn.enabled = True
    with patch.dict(sys.modules, {"torch": fake}), patch.object(main.sys, "platform", "win32"), \
            patch("importlib.metadata.version", return_value=ROCM), patch.dict(os.environ, {}, clear=False):
        os.environ.pop("KMP_DUPLICATE_LIB_OK", None)
        os.environ.pop("USKMAKER_ENABLE_MIOPEN", None)
        assert resolve_device("auto") == "cuda"
        assert fake.backends.cudnn.enabled is False
        assert os.environ.get("KMP_DUPLICATE_LIB_OK") == "TRUE"


def test_resolve_device_cpu_pedido_nao_liga_miopen_off():
    fake = MagicMock()
    fake.backends.cudnn.enabled = True
    with patch.dict(sys.modules, {"torch": fake}), patch.object(main.sys, "platform", "win32"):
        assert resolve_device("cpu") == "cpu"
        assert fake.backends.cudnn.enabled is True


if __name__ == "__main__":
    test_kmp_so_no_windows_com_torch_rocm()
    test_kmp_nao_mexe_em_nvidia_nem_linux()
    test_kmp_respeita_valor_ja_definido()
    test_kmp_sem_torch_instalado_nao_quebra()
    test_miopen_desligado_so_no_windows_com_hip()
    test_miopen_intacto_fora_do_caso_windows_hip()
    test_miopen_opt_out_pela_variavel()
    test_resolve_device_amd_windows_liga_os_dois()
    test_resolve_device_cpu_pedido_nao_liga_miopen_off()
    print("OK - test_amd_windows_runtime")

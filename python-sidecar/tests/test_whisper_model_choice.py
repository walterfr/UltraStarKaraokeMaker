# -*- coding: utf-8 -*-
"""
Testes da escolha do modelo do Whisper (resolve_whisper_model).

CONTEXTO (relato real, 02/09/2026 - "Camouflage - The Great Commandment"):
o tamanho do modelo estava FIXO em "medium", como default de parâmetro do
align_lyrics_to_audio, e não era exposto em CLI, servidor nem interface.
Naquela música o Whisper reconheceu 50% das palavras, o log avisou, a
pipeline tentou dois resgates - os dois pioraram - e não havia alavanca
nenhuma pra puxar.

O ponto destes testes é a regra de segurança: a opção não pode piorar quem
já estava funcionando. Máquina modesta e CPU continuam exatamente no
"medium" de antes; só quem tem VRAM sobrando sobe pro modelo grande.

Rodar:  python -m pytest tests/ -v
"""
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from main import (
    WHISPER_LARGE_MIN_VRAM_GB,
    WHISPER_MODEL_BEST,
    WHISPER_MODEL_DEFAULT,
    resolve_whisper_model,
)


def _fake_torch(monkeypatch, vram_gb):
    """Finge um torch cuja GPU tem `vram_gb` de VRAM."""
    props = types.SimpleNamespace(total_memory=int(vram_gb * 1024 ** 3))
    fake = types.SimpleNamespace(
        cuda=types.SimpleNamespace(get_device_properties=lambda i: props)
    )
    monkeypatch.setitem(sys.modules, "torch", fake)


# ---------------------------------------------------------------------------
# Escolha automática
# ---------------------------------------------------------------------------

def test_gpu_com_vram_sobrando_usa_o_modelo_grande(monkeypatch):
    _fake_torch(monkeypatch, 16)          # a RTX 5080 do relato
    assert resolve_whisper_model("auto", "cuda") == WHISPER_MODEL_BEST


def test_gpu_no_limite_ainda_usa_o_grande(monkeypatch):
    _fake_torch(monkeypatch, WHISPER_LARGE_MIN_VRAM_GB)
    assert resolve_whisper_model("auto", "cuda") == WHISPER_MODEL_BEST


def test_gpu_pequena_fica_no_medium(monkeypatch):
    """
    A correção NÃO pode piorar quem já estava funcionando: placa apertada
    continua no modelo de antes em vez de estourar memória no meio da música.
    """
    _fake_torch(monkeypatch, 4)
    assert resolve_whisper_model("auto", "cuda") == WHISPER_MODEL_DEFAULT


def test_cpu_nunca_usa_o_modelo_grande(monkeypatch):
    """large-v3 na CPU levaria dezenas de minutos - na prática, travar."""
    _fake_torch(monkeypatch, 64)          # VRAM irrelevante: o device é cpu
    assert resolve_whisper_model("auto", "cpu") == WHISPER_MODEL_DEFAULT


def test_torch_quebrado_cai_no_medium(monkeypatch):
    """Não saber a VRAM não pode derrubar a geração - escolhe o seguro."""
    fake = types.SimpleNamespace(
        cuda=types.SimpleNamespace(
            get_device_properties=lambda i: (_ for _ in ()).throw(RuntimeError("nope"))
        )
    )
    monkeypatch.setitem(sys.modules, "torch", fake)
    assert resolve_whisper_model("auto", "cuda") == WHISPER_MODEL_DEFAULT


# ---------------------------------------------------------------------------
# Escolha explícita
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pedido", ["medium", "large-v3", "small"])
def test_escolha_explicita_manda_sobre_o_automatico(monkeypatch, pedido):
    _fake_torch(monkeypatch, 16)
    assert resolve_whisper_model(pedido, "cuda") == pedido


def test_escolha_explicita_vale_ate_contra_a_vram(monkeypatch):
    """
    Quem pede large-v3 numa placa pequena recebe large-v3. É uma escolha
    consciente na interface; o automático é que precisa ser prudente.
    """
    _fake_torch(monkeypatch, 4)
    assert resolve_whisper_model("large-v3", "cuda") == "large-v3"


@pytest.mark.parametrize("vazio", ["", "auto", None])
def test_valores_vazios_contam_como_automatico(monkeypatch, vazio):
    _fake_torch(monkeypatch, 16)
    assert resolve_whisper_model(vazio, "cuda") == WHISPER_MODEL_BEST


def test_o_limiar_tem_folga_sobre_o_que_o_modelo_usa():
    """
    O large-v3 pede ~3 GB em float16. O limiar precisa de margem pro que o
    torch já mantém reservado - não pode ser colado no consumo do modelo.
    """
    assert WHISPER_LARGE_MIN_VRAM_GB >= 5.0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

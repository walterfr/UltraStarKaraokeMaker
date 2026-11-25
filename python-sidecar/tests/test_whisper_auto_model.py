# -*- coding: utf-8 -*-
"""
O modelo do Whisper "auto" (padrão do app) precisa virar um nome real antes de
chegar ao faster-whisper, que recusa "auto" com "Invalid model size 'auto'".

A auto-transcrição (sem letra) e a detecção de trechos faltantes na letra
recebiam o "auto" cru: a primeira quebrava a geração e a segunda falhava em
silêncio em toda música (só aparecia no pipeline_debug.log como "Falha na
detecção de gaps (ignorada): Invalid model size 'auto'"). Nada aqui carrega
modelo.

Rodar:  python -m pytest tests/ -v
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main


def test_auto_vira_nome_real():
    assert main.whisper_for("cpu", "auto") == ("cpu", main.WHISPER_MODEL_DEFAULT)
    assert main.whisper_for("cpu", "") == ("cpu", main.WHISPER_MODEL_DEFAULT)


def test_escolha_explicita_passa_direto():
    assert main.whisper_for("cpu", "small") == ("cpu", "small")
    assert main.whisper_for("cpu", "large-v3") == ("cpu", "large-v3")


def test_gpu_sem_ctranslate2_manda_o_whisper_para_a_cpu(monkeypatch):
    # GPU AMD com o CTranslate2 do PyPI: o resto roda na GPU, o Whisper na CPU,
    # e o tamanho do modelo segue o device REAL do Whisper
    monkeypatch.setattr(main, "resolve_whisper_device", lambda device: "cpu")
    assert main.whisper_for("cuda", "auto") == ("cpu", main.WHISPER_MODEL_DEFAULT)


def test_nenhuma_chamada_passa_o_modelo_pedido_cru():
    """Trava a regressão: o valor pedido (whisper_model) nunca vai direto como tamanho."""
    src = Path(main.__file__).read_text(encoding="utf-8")
    cru = re.findall(r"whisper_model_size\s*=\s*whisper_model\s*[,)]", src)
    assert cru == [], "passe por whisper_for() ou resolve_whisper_model() antes"


def test_faster_whisper_recusa_auto_e_aceita_o_padrao():
    """A premissa do conserto, conferida no próprio faster-whisper (pula sem ele)."""
    utils = pytest.importorskip("faster_whisper.utils")
    assert "auto" not in utils.available_models()
    assert main.WHISPER_MODEL_DEFAULT in utils.available_models()
    with pytest.raises(ValueError, match="Invalid model size 'auto'"):
        utils.download_model("auto")

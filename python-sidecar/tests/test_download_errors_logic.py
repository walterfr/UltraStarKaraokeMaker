# -*- coding: utf-8 -*-
"""
Testes do tratamento de erro do download (yt-dlp): extração do motivo real,
tradução para linguagem acionável e retentativa em falha transitória.

Sem rede e sem yt-dlp: o run_subprocess é substituído por um dublê que falha
do jeito que o yt-dlp falha de verdade.

CONTEXTO (relato real, 02/09/2026): um download do YouTube falhou e o que
chegou na tela do usuário foi o CalledProcessError cru - a linha de comando
inteira, com todos os argumentos, e nenhuma pista do motivo. O motivo
("HTTP Error 403: Forbidden") estava no meio do log. Ninguém que não programa
consegue ler aquilo, e ninguém deveria precisar abrir um log pra descobrir que
o YouTube recusou o download.

Rodar:  python -m pytest tests/ -v
"""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import download
from pipeline.download import (
    _extract_yt_dlp_error,
    _friendly_download_error,
    run_yt_dlp,
)


# Saída realista do yt-dlp: o motivo vem no fim, depois de muito ruído.
SAIDA_403 = """[youtube] Extracting URL: https://www.youtube.com/watch?v=abc
[youtube] abc: Downloading webpage
[youtube] abc: Downloading android vr player API JSON
[info] abc: Downloading 1 format(s): 397+140
ERROR: unable to download video data: HTTP Error 403: Forbidden
"""


# ---------------------------------------------------------------------------
# Extração do motivo
# ---------------------------------------------------------------------------

def test_acha_a_linha_de_erro_no_meio_do_ruido():
    assert _extract_yt_dlp_error(SAIDA_403) == \
        "unable to download video data: HTTP Error 403: Forbidden"


def test_sem_linha_de_erro_devolve_vazio():
    assert _extract_yt_dlp_error("[youtube] baixando...\n[info] ok\n") == ""


def test_saida_vazia_ou_none_nao_quebra():
    assert _extract_yt_dlp_error("") == ""
    assert _extract_yt_dlp_error(None) == ""


def test_usa_o_ULTIMO_erro_quando_ha_varios():
    """O yt-dlp tenta formatos em cascata; o que vale é o erro final."""
    saida = "ERROR: formato indisponivel\n[info] tentando outro\nERROR: motivo final\n"
    assert _extract_yt_dlp_error(saida) == "motivo final"


# ---------------------------------------------------------------------------
# Tradução para linguagem útil
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cru,esperado_contem", [
    ("unable to download video data: HTTP Error 403: Forbidden", "recusou"),
    ("Sign in to confirm your age", "idade"),
    ("Private video", "privado"),
    ("Video unavailable", "disponível"),
    ("Requested format is not available", "formato"),
])
def test_causas_conhecidas_viram_frase_em_portugues(cru, esperado_contem):
    assert esperado_contem in _friendly_download_error(cru).lower()


def test_erro_desconhecido_passa_cru_em_vez_de_sumir():
    """Melhor mostrar um erro estranho do que engolir e não dizer nada."""
    assert _friendly_download_error("algo muito esquisito") == "algo muito esquisito"


def test_erro_vazio_ainda_diz_alguma_coisa():
    assert _friendly_download_error("") != ""


# ---------------------------------------------------------------------------
# Retentativa
# ---------------------------------------------------------------------------

def _falha(saida: str):
    return subprocess.CalledProcessError(1, ["yt-dlp"], output=saida, stderr=saida)


def test_403_tenta_de_novo_e_pode_dar_certo(monkeypatch):
    """
    403 no meio do download é intermitente do lado do YouTube (yt-dlp #17395):
    a mesma URL costuma funcionar numa segunda tentativa.
    """
    chamadas = []

    def fake(cmd, **kw):
        chamadas.append(cmd)
        if len(chamadas) == 1:
            raise _falha(SAIDA_403)
        return None

    monkeypatch.setattr(download, "run_subprocess", fake)
    run_yt_dlp(["yt-dlp", "url"])          # não deve levantar
    assert len(chamadas) == 2, "deveria ter tentado uma segunda vez"


def test_erro_permanente_NAO_tenta_de_novo(monkeypatch):
    """Vídeo privado não melhora repetindo - repetir só faz o usuário esperar."""
    chamadas = []

    def fake(cmd, **kw):
        chamadas.append(cmd)
        raise _falha("ERROR: Private video. Sign in if you've been granted access\n")

    monkeypatch.setattr(download, "run_subprocess", fake)
    with pytest.raises(RuntimeError):
        run_yt_dlp(["yt-dlp", "url"])
    assert len(chamadas) == 1, "erro permanente não deve ser repetido"


def test_403_persistente_desiste_depois_da_retentativa(monkeypatch):
    chamadas = []

    def fake(cmd, **kw):
        chamadas.append(cmd)
        raise _falha(SAIDA_403)

    monkeypatch.setattr(download, "run_subprocess", fake)
    with pytest.raises(RuntimeError):
        run_yt_dlp(["yt-dlp", "url"])
    assert len(chamadas) == 2, "uma tentativa + uma retentativa, e para"


# ---------------------------------------------------------------------------
# A mensagem que o usuário realmente vê
# ---------------------------------------------------------------------------

def _mensagem_de_erro(monkeypatch, saida: str) -> str:
    def fake(cmd, **kw):
        raise _falha(saida)
    monkeypatch.setattr(download, "run_subprocess", fake)
    with pytest.raises(RuntimeError) as exc:
        run_yt_dlp(["python", "-m", "yt_dlp", "--no-playlist", "-f", "bestvideo",
                    "-o", "C:\\Karaoke\\x\\video.%(ext)s", "https://y/watch?v=abc"])
    return str(exc.value)


def test_REGRESSAO_a_mensagem_nao_despeja_a_linha_de_comando(monkeypatch):
    """
    O bug original: a tela mostrava a lista inteira de argumentos do
    subprocesso. Nada disso ajuda quem não programa - e escondia o motivo.
    """
    msg = _mensagem_de_erro(monkeypatch, SAIDA_403)
    assert "--no-playlist" not in msg
    assert "bestvideo" not in msg
    assert "returned non-zero exit status" not in msg
    assert "Traceback" not in msg


def test_a_mensagem_diz_o_motivo_e_o_que_fazer(monkeypatch):
    msg = _mensagem_de_erro(monkeypatch, SAIDA_403).lower()
    assert "recusou" in msg or "403" in msg      # o motivo
    assert "arquivo local" in msg                # a saída prática
    assert "yt-dlp" in msg                       # a outra saída


def test_a_mensagem_nomeia_o_que_falhou(monkeypatch):
    def fake(cmd, **kw):
        raise _falha(SAIDA_403)
    monkeypatch.setattr(download, "run_subprocess", fake)
    with pytest.raises(RuntimeError) as exc:
        run_yt_dlp(["yt-dlp"], "o áudio")
    assert "o áudio" in str(exc.value)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

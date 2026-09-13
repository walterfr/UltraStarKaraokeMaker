# -*- coding: utf-8 -*-
"""
Testes da lógica PURA de read_video_info.py (limpeza de título, escolha de
artista/música) e de update_ytdlp.py (detecção de canal, comando de
atualização) - sem rede, sem yt-dlp, sem instalar nada.

Rodar:  python -m pytest tests/ -v
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from read_video_info import pick_artist_title, split_artist_title, strip_title_noise
from update_ytdlp import build_upgrade_command, is_prerelease


# ---------------------------------------------------------------------------
# Limpeza do título do vídeo
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cru,limpo", [
    ("The Great Commandment (Official Video)", "The Great Commandment"),
    ("The Great Commandment [Official Music Video]", "The Great Commandment"),
    ("I Never Lie (Official Audio)", "I Never Lie"),
    ("Enjoy the Silence (Lyrics)", "Enjoy the Silence"),
    ("Love Like Blood [HD]", "Love Like Blood"),
    ("Until Death (Remastered 2019)", "Until Death"),
    ("Close To Me (Official Video) [4K]", "Close To Me"),
])
def test_tira_o_ruido_de_titulo(cru, limpo):
    assert strip_title_noise(cru) == limpo


def test_titulo_limpo_passa_intacto():
    assert strip_title_noise("The Madness of It All") == "The Madness of It All"


def test_nao_come_parenteses_que_fazem_parte_do_nome():
    """
    "(Us Do Part)" é parte do nome da música do Front 242, não ruído.

    Este teste conferia só se o MIOLO sobrevivia (`"Us Do Part" in ...`) - e
    por isso passou verdinho enquanto o parêntese que FECHA era comido. A
    igualdade completa é o que realmente tranca o comportamento.
    """
    assert strip_title_noise("Until Death (Us Do Part)") == "Until Death (Us Do Part)"


def test_titulo_vazio_nao_quebra():
    assert strip_title_noise("") == ""
    assert strip_title_noise(None or "") == ""


# ---------------------------------------------------------------------------
# Divisão artista / música
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("titulo,artista,musica", [
    ("Camouflage - The Great Commandment (Official Video)",
     "Camouflage", "The Great Commandment"),
    ("Zach Top – I Never Lie", "Zach Top", "I Never Lie"),
    ("The Cure | Close To Me", "The Cure", "Close To Me"),
])
def test_divide_no_separador(titulo, artista, musica):
    assert split_artist_title(titulo) == (artista, musica)


def test_divide_no_PRIMEIRO_separador():
    """"Artista - Música - Ao Vivo": o artista está antes do primeiro."""
    a, t = split_artist_title("Camouflage - The Great Commandment - Live 1988")
    assert a == "Camouflage"
    assert t == "The Great Commandment - Live 1988"


def test_sem_separador_nao_inventa_artista():
    """
    Melhor devolver o título e deixar o artista em branco do que chutar uma
    divisão errada - o usuário corrige um campo vazio sem pensar, mas não
    percebe um artista errado que "parece" preenchido.
    """
    a, t = split_artist_title("The Great Commandment")
    assert a is None
    assert t == "The Great Commandment"


def test_hifen_sem_espacos_nao_e_separador():
    """"AC-DC" e "T.N.T" não podem virar artista/música."""
    a, _ = split_artist_title("AC-DC")
    assert a is None


# ---------------------------------------------------------------------------
# Escolha final (yt-dlp -> campos do formulário)
# ---------------------------------------------------------------------------

def test_campos_do_youtube_music_ganham_do_titulo():
    """
    `artist`/`track` vêm da gravadora e já são limpos - qualquer regex em cima
    de um título de vídeo é pior que isso.
    """
    info = {"artist": "Camouflage", "track": "The Great Commandment",
            "title": "CAMOUFLAGE - The Great Commandment (Official Video) [HD]",
            "uploader": "SomeVEVOChannel"}
    assert pick_artist_title(info) == ("Camouflage", "The Great Commandment")


def test_sem_campos_da_gravadora_usa_o_titulo():
    info = {"title": "Camouflage - The Great Commandment (Official Video)",
            "uploader": "Canal Qualquer"}
    assert pick_artist_title(info) == ("Camouflage", "The Great Commandment")


def test_uploader_e_o_ultimo_recurso_para_artista():
    info = {"title": "The Great Commandment", "uploader": "Camouflage Official"}
    a, t = pick_artist_title(info)
    assert a == "Camouflage Official"      # o usuário corrige antes de buscar
    assert t == "The Great Commandment"


def test_info_vazia_nao_quebra():
    assert pick_artist_title({}) == (None, None)


# ---------------------------------------------------------------------------
# Canal do yt-dlp (a armadilha do downgrade)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("versao", [
    "2026.8.30.232658.dev0",
    "2026.9.1.dev",
    "2026.1.1a1",
    "2026.1.1rc2",
])
def test_reconhece_versao_de_teste(versao):
    assert is_prerelease(versao) is True


@pytest.mark.parametrize("versao", [
    "2026.7.4",
    "2025.12.31",
    "2024.4.9",
    "",
])
def test_reconhece_versao_estavel(versao):
    assert is_prerelease(versao) is False


def test_letra_solta_no_texto_nao_vira_pre_release():
    """
    O teste ingênuo `"a" in version` daria True pra qualquer versão. O
    marcador só vale colado num número (2026.1.1a1).
    """
    assert is_prerelease("2026.7.4") is False


def test_REGRESSAO_quem_esta_no_teste_NAO_e_rebaixado():
    """
    O ponto inteiro deste módulo. Quem está no canal de teste está lá porque o
    estável estava quebrado; atualizar "para o mais recente estável" devolveria
    o erro que a pessoa já tinha resolvido.
    """
    cmd = build_upgrade_command("uv.exe", "py.exe", prerelease=True)
    assert "--prerelease" in cmd and "allow" in cmd
    assert any("yt-dlp" in c for c in cmd)


def test_quem_esta_no_estavel_continua_no_estavel():
    """A correção não pode empurrar ninguém para o canal de teste sem pedir."""
    cmd = build_upgrade_command("uv.exe", "py.exe", prerelease=False)
    assert "--prerelease" not in cmd


def test_o_comando_atualiza_o_venv_certo():
    cmd = build_upgrade_command("uv.exe", "C:/venv/python.exe", prerelease=False)
    assert "--python" in cmd
    assert cmd[cmd.index("--python") + 1] == "C:/venv/python.exe"
    assert "--upgrade" in cmd


def test_nao_deixa_casca_de_parentese_vazio():
    """
    Bug pego pelos próprios testes: a alternância do regex não estava
    agrupada, então "[4K]" virava "[ ]" - o ruído saía e a casca ficava,
    indo direto para a consulta ao LRCLIB.
    """
    for cru in ("Close To Me (Official Video) [4K]",
                "Song [HD] ()", "Song (Official Video) []"):
        limpo = strip_title_noise(cru)
        assert "(" not in limpo and ")" not in limpo, limpo
        assert "[" not in limpo and "]" not in limpo, limpo


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
# ---------------------------------------------------------------------------
# Parêntese/colchete que FECHA o nome da música
#
# BUG REAL (07/09/2026, relatado pelo usuário): "Ministry - Effigy (Im Not
# An)" chegava ao formulário como "Effigy (Im Not An" - sem o fecha-parêntese.
# A limpeza terminava com `.strip(" -–—|~·.,()[]")`, que come parêntese de
# ponta seja ele casca ou parte do nome. O título truncado ia para a consulta
# do LRCLIB, para o nome da pasta e para o .txt gerado.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cru,limpo", [
    ("Effigy (Im Not An)", "Effigy (Im Not An)"),
    ("Play with Me (Jane) [7 Edit]", "Play with Me (Jane) [7 Edit]"),
    ("Have In Mind (Extended Mix)", "Have In Mind (Extended Mix)"),
    ("Angel 07 (Extended Version)", "Angel 07 (Extended Version)"),
])
def test_o_parentese_que_fecha_o_nome_fica(cru, limpo):
    assert strip_title_noise(cru) == limpo


@pytest.mark.parametrize("cru,limpo", [
    ("Song (", "Song"),
    ("Song )", "Song"),
    ("Song ]", "Song"),
    (") Song", "Song"),
])
def test_casca_de_parentese_sem_par_sai(cru, limpo):
    """Sem par, é sobra da remoção do ruído - não faz parte do nome."""
    assert strip_title_noise(cru) == limpo


def test_titulo_inteiro_entre_parenteses_fica_como_esta():
    """Estão em par: é o nome escrito assim, não casca."""
    assert strip_title_noise("(Reprise)") == "(Reprise)"


def test_o_ruido_ainda_sai_de_um_titulo_com_parenteses_de_verdade():
    """O nome entre parênteses fica; o "(Official Video)" continua saindo."""
    assert strip_title_noise("Effigy (Im Not An) (Official Video)") == "Effigy (Im Not An)"


def test_divisao_devolve_o_titulo_completo():
    """O caso do usuário, ponta a ponta."""
    assert split_artist_title("Ministry - Effigy (Im Not An) (Official Audio)") == (
        "Ministry",
        "Effigy (Im Not An)",
    )


def test_visualiser_britanico_tambem_e_ruido():
    """Caso real da biblioteca do usuário - a lista só tinha "visualizer"."""
    assert strip_title_noise("Freedom! 90 [Official Visualiser]") == "Freedom! 90"

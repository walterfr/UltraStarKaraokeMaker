# -*- coding: utf-8 -*-
"""
Testes da PRIORIDADE entre âncoras do Whisper e inícios de linha do .lrc.

CONTEXTO (relato real, 03/09/2026, "Cause & Effect - Inside Out", eletrônica
de 1994): o Whisper reconheceu 38% das palavras e a checagem contra o .lrc
demoveu 45 âncoras dele por implausíveis - o .lrc estava demonstravelmente
mais certo. Mesmo assim, em todo início de linha onde o Whisper tinha
ancorado, o .lrc não entrava: a fonte confiável cedia à duvidosa.

A regra desta mudança, e o que estes testes trancam:
  - reconhecimento NORMAL  -> comportamento de antes, sem exceção;
  - reconhecimento BAIXO   -> o .lrc manda nos inícios de linha.
A segunda metade é o objetivo; a primeira é a garantia de não regredir
música que já funciona.

Rodar:  python -m pytest tests/ -v
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.align import (
    LRC_OVERRIDE_RECALL_FLOOR,
    SOURCE_ANCHOR,
    SOURCE_FUZZY,
    SOURCE_INTERPOLATED,
    SOURCE_LRC,
    lrc_duration_mismatch,
    lrc_is_approved,
    measured_recall,
    seed_line_anchors,
    timings_from_anchors,
)


def _anchor(t, source=SOURCE_ANCHOR):
    return (t, t + 0.3, 0.9, source)


# duas linhas de letra: palavra 0 inicia a 1ª, palavra 2 inicia a 2ª
LYRIC_LINES = [("primeira linha", 0), ("segunda linha", 2)]
LRC_LINES = [(10.0, "primeira linha"), (20.0, "segunda linha")]


# ---------------------------------------------------------------------------
# measured_recall
# ---------------------------------------------------------------------------

def test_recall_conta_so_o_que_o_whisper_reconheceu():
    """Realinhamento e .lrc não entram: a pergunta é quanto ELE entendeu."""
    anchors = [_anchor(1), _anchor(2, SOURCE_FUZZY), _anchor(3, SOURCE_LRC), None]
    assert measured_recall(anchors) == 0.5      # 2 de 4


def test_recall_de_lista_vazia_e_zero():
    assert measured_recall([]) == 0.0


def test_recall_sem_nenhuma_ancora_e_zero():
    assert measured_recall([None, None]) == 0.0


# ---------------------------------------------------------------------------
# Comportamento NORMAL (reconhecimento bom) - não pode mudar
# ---------------------------------------------------------------------------

def test_sem_override_a_ancora_medida_e_preservada():
    """
    O caso saudável: o Whisper mediu o início da linha, e uma medição
    acústica é mais precisa que um início de linha de .lrc. Fica como está.
    """
    anchors = [_anchor(9.5), None, _anchor(19.5), None]
    seed_line_anchors(anchors, LYRIC_LINES, LRC_LINES)
    assert anchors[0][0] == 9.5       # intocada
    assert anchors[2][0] == 19.5      # intocada


def test_sem_override_o_lrc_ainda_preenche_os_vaos():
    """O papel histórico do .lrc continua: entrar onde não há medição."""
    anchors = [None, None, None, None]
    seeded = seed_line_anchors(anchors, LYRIC_LINES, LRC_LINES)
    assert seeded == 2
    assert anchors[0][0] == 10.0 and anchors[0][3] == SOURCE_LRC
    assert anchors[2][0] == 20.0


# ---------------------------------------------------------------------------
# Comportamento com OVERRIDE (reconhecimento baixo) - o objetivo
# ---------------------------------------------------------------------------

def test_override_substitui_a_ancora_do_whisper_no_inicio_de_linha():
    """
    O ponto da mudança: com reconhecimento baixo, o início de linha do .lrc
    entra mesmo onde o Whisper já tinha ancorado.
    """
    anchors = [_anchor(3.0), None, _anchor(31.0), None]   # ambas muito erradas
    seeded = seed_line_anchors(anchors, LYRIC_LINES, LRC_LINES,
                               override_measured=True)
    assert seeded == 2
    assert anchors[0][0] == 10.0 and anchors[0][3] == SOURCE_LRC
    assert anchors[2][0] == 20.0 and anchors[2][3] == SOURCE_LRC


def test_override_nao_e_vetado_por_vizinhos_errados():
    """
    REGRESSÃO DO DESENHO: os vizinhos são as âncoras que NÃO estamos
    confiando. Se pudessem vetar por monotonicidade, o modo não faria nada
    justamente nas músicas em que ele existe para agir.
    """
    # vizinho anterior absurdamente tarde (25s) antes de uma linha que começa
    # aos 20s - no modo normal isso bloquearia a semeadura
    anchors = [_anchor(3.0), _anchor(25.0), _anchor(31.0), None]
    seeded = seed_line_anchors(anchors, LYRIC_LINES, LRC_LINES,
                               override_measured=True)
    assert seeded == 2
    assert anchors[2][0] == 20.0


def test_override_so_toca_INICIOS_de_linha():
    """
    Palavras no meio da linha continuam com o que foi medido - o .lrc só sabe
    onde a LINHA começa, não onde cada palavra cai dentro dela.
    """
    anchors = [_anchor(3.0), _anchor(4.0), _anchor(31.0), _anchor(32.0)]
    seed_line_anchors(anchors, LYRIC_LINES, LRC_LINES, override_measured=True)
    assert anchors[1][0] == 4.0 and anchors[1][3] == SOURCE_ANCHOR
    assert anchors[3][0] == 32.0 and anchors[3][3] == SOURCE_ANCHOR


def test_override_mantem_a_ordem_no_tempo():
    """Os tempos do .lrc já são monotônicos; o resultado tem que refletir."""
    anchors = [_anchor(30.0), None, _anchor(5.0), None]   # fora de ordem
    seed_line_anchors(anchors, LYRIC_LINES, LRC_LINES, override_measured=True)
    assert anchors[0][0] < anchors[2][0]


def test_override_sem_lrc_correspondente_nao_inventa_nada():
    anchors = [_anchor(3.0), None, _anchor(31.0), None]
    seeded = seed_line_anchors(anchors, LYRIC_LINES, [], override_measured=True)
    assert seeded == 0
    assert anchors[0][0] == 3.0        # intacta


# ---------------------------------------------------------------------------
# O gatilho
# ---------------------------------------------------------------------------

def test_o_piso_e_o_mesmo_que_dispara_o_aviso_ao_usuario():
    """
    Não faz sentido avisar "as âncoras podem estar erradas" e continuar
    preferindo-as ao .lrc. O aviso e a correção usam o mesmo número.
    """
    import main
    assert LRC_OVERRIDE_RECALL_FLOOR == main.WHISPER_RECALL_FLOOR


@pytest.mark.parametrize("recall,esperado", [
    (0.38, True),    # o caso relatado
    (0.16, True),
    (0.59, True),
    (0.60, False),   # no piso, comportamento de antes
    (0.89, False),   # mediana das músicas boas
])
def test_quando_o_modo_liga(recall, esperado):
    assert (recall < LRC_OVERRIDE_RECALL_FLOOR) is esperado


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
# ---------------------------------------------------------------------------
# Letra APROVADA pelo usuário (tabela "Tempos da letra" da tela de revisão)
#
# Um .lrc aprovado não é palpite do LRCLIB: uma pessoa ouviu ESTA gravação e
# conferiu os inícios de linha. Por isso ele pula as defesas que existem para
# proteger de um palpite de terceiros. Estes testes trancam as três peças de
# que esse caminho depende.
# ---------------------------------------------------------------------------

APPROVED_HEADER = "[ar:Ministry]\n[ti:Effigy]\n[uskmapproved:1]\n[uskmaudio:232.44]\n"


def test_marca_de_aprovacao_e_reconhecida():
    assert lrc_is_approved(APPROVED_HEADER + "[00:10.00]primeira linha\n")


def test_lrc_normal_do_lrclib_nao_passa_por_aprovado():
    """Sem a tag, nada muda - o caminho de sempre continua valendo."""
    assert not lrc_is_approved("[ar:Ministry]\n[00:10.00]primeira linha\n")


def test_marca_tolera_maiuscula_e_espaco():
    assert lrc_is_approved("[USKMAPPROVED: 1 ]\n[00:10.00]x\n")


def test_aprovada_seria_recusada_pela_checagem_de_duracao():
    """
    Justifica o pulo: os tempos aprovados podem ficar longe do fim do áudio
    (música que termina em instrumental longo, por exemplo) e a checagem de
    duração - certa para um palpite do LRCLIB - recusaria um arquivo que uma
    pessoa conferiu de ouvido. Quem pula é o chamador; aqui só se registra
    que sem o pulo a recusa aconteceria.
    """
    curta = [(10.0, "a"), (20.0, "b")]
    assert lrc_duration_mismatch(curta, audio_duration=300.0)


def test_aprovada_substitui_ancora_medida_no_inicio_da_linha():
    """
    O mecanismo em que a aprovação se apoia: no início de linha, o tempo
    conferido de ouvido entra POR CIMA do que o Whisper mediu. Sem
    override_measured, uma âncora errada do Whisper continuaria mandando -
    que é exatamente o defeito que a aprovação existe para resolver.
    """
    anchors = [_anchor(45.2), None, _anchor(50.0), None]
    seeded = seed_line_anchors(
        anchors, LYRIC_LINES, LRC_LINES, override_measured=True
    )
    assert seeded == 2
    assert anchors[0][0] == 10.0 and anchors[0][3] == SOURCE_LRC
    assert anchors[2][0] == 20.0 and anchors[2][3] == SOURCE_LRC


def test_inicios_aprovados_sobrevivem_ate_os_tempos_finais():
    """
    Os inícios semeados precisam CHEGAR na lista de tempos como âncoras: é
    isso que limita a janela do realinhamento (passe 3), que só considera
    corridas de palavras INTERPOLADAS entre duas medidas. Uma palavra do meio
    da linha não pode, portanto, escapar para fora da sua linha.
    """
    anchors = [None, None, None, None]
    seed_line_anchors(anchors, LYRIC_LINES, LRC_LINES, override_measured=True)
    timings = timings_from_anchors(
        anchors, ["primeira", "linha", "segunda", "linha"], language="pt",
        audio_end=30.0,
    )
    assert timings[0].source == SOURCE_LRC and timings[0].start == 10.0
    assert timings[2].source == SOURCE_LRC and timings[2].start == 20.0
    # a palavra do meio ficou interpolada DENTRO da sua linha - o
    # realinhamento vai recebê-la numa janela entre 10 s e 20 s, não solta
    # pela música inteira
    assert timings[1].source == SOURCE_INTERPOLATED
    assert 10.0 <= timings[1].start <= 20.0

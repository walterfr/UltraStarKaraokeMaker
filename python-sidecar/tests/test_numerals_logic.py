"""
Testes puros da expansão de números (pipeline/numerals.py) e da sua
integração com as âncoras. Sem GPU, sem áudio, sem modelo.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.numerals import expand_numeral, expand_tokens  # noqa: E402
from pipeline.align import (  # noqa: E402
    SOURCE_ANCHOR,
    _alignment_tokens,
    _collapse_expanded_words,
    _syllable_weight,
    _whisper_token_unreliable,
    compute_anchors,
)


def _ww(word, start, end, score=0.9):
    return {"word": word, "start": start, "end": end, "score": score}


# --- expand_numeral ---------------------------------------------------------

def test_expand_numero_simples_pt():
    assert expand_numeral("20", "pt") == ["vinte"]


def test_expand_numero_composto_vira_varios_tokens():
    # "1985" -> "mil novecentos e oitenta e cinco"
    out = expand_numeral("1985", "pt")
    assert len(out) > 1
    assert out[0] == "mil"
    assert all(" " not in t for t in out)


def test_expand_respeita_idioma():
    assert expand_numeral("20", "en") == ["twenty"]


def test_palavra_normal_passa_intacta():
    assert expand_numeral("casa", "pt") == ["casa"]


def test_token_misto_nao_e_expandido():
    # conservador: "20anos" não é um número puro, não inventamos nada
    assert expand_numeral("20anos", "pt") == ["20anos"]


def test_numero_gigante_nao_e_expandido():
    # um número de telefone/ID não é cantado por extenso
    assert expand_numeral("123456789", "pt") == ["123456789"]


def test_idioma_desconhecido_nao_quebra():
    # degrada pro comportamento antigo em vez de derrubar a geração
    assert expand_numeral("20", "xx-nao-existe") == ["20"]


# --- expand_tokens (mapa de origem) ----------------------------------------

def test_expand_tokens_mapeia_origem():
    toks, origin = expand_tokens(["Que", "os", "meus", "20"], "pt")
    assert toks == ["Que", "os", "meus", "vinte"]
    assert origin == [0, 1, 2, 3]


def test_expand_tokens_multiplos_pedacos_apontam_pra_mesma_origem():
    toks, origin = expand_tokens(["ano", "1985"], "pt")
    assert toks[0] == "ano"
    assert origin[0] == 0
    # todos os pedaços de "1985" apontam para o índice 1
    assert set(origin[1:]) == {1}
    assert len(origin) == len(toks)


# --- as âncoras NÃO expandem (decisão medida) -------------------------------

def test_ancora_nao_expande_numero_de_proposito():
    """
    Trava a decisão: casar "20" com "vinte" AQUI parece um ganho de graça, mas
    foi medido como regressão grave ("20 e poucos anos": âncoras exatas 166 ->
    100 e 109 de 181 palavras +43,8 s pra frente). O match alonga o bloco
    "Que os meus 20 e poucos anos" de 3+3 para 7 tokens, e o difflib passa a
    ancorar a recursão na repetição errada do refrão. O número é resolvido no
    realinhamento de janela, que é local e não pode fugir do lugar.
    """
    whisper = [_ww("meus", 38.40, 38.66), _ww("vinte", 38.70, 38.98), _ww("e", 39.0, 39.02)]
    real = ["meus", "20", "e"]

    anchors = compute_anchors(whisper, real)

    assert anchors[0] is not None, "'meus' casa normalmente"
    assert anchors[2] is not None, "'e' casa normalmente"
    assert anchors[1] is None, "'20' NÃO vira âncora - fica pro realinhamento"


def test_palavras_normais_nao_sao_afetadas():
    # regressão: nada do caminho comum pode ter mudado
    whisper = [_ww("casa", 1.0, 1.5), _ww("azul", 1.5, 2.0)]
    real = ["casa", "azul"]

    anchors = compute_anchors(whisper, real)

    assert [a[0] for a in anchors] == [1.0, 1.5]
    assert all(a[3] == SOURCE_ANCHOR for a in anchors)


# --- texto que vai pro forced alignment (é aqui que o número é resolvido) ---

def test_texto_do_realinhamento_usa_o_extenso():
    # o vocabulário do wav2vec2 não tem dígito: "20" não casa com frame nenhum
    assert _alignment_tokens("20", "pt") == ["vinte"]
    assert _alignment_tokens("1985", "pt")[0] == "mil"


def test_texto_do_realinhamento_preserva_palavra_normal():
    # inclusive a pontuação: o whisperx já a descarta sozinho
    assert _alignment_tokens("casa,", "pt") == ["casa,"]


def test_colapso_junta_pedacos_numa_palavra_so():
    raw = [{"start": 1.0, "end": 1.4, "score": 0.9},
           {"start": 1.4, "end": 2.0, "score": 0.5},
           {"start": 2.0, "end": 3.2, "score": 0.8}]
    origin = [0, 0, 0]  # os três tokens vieram da MESMA palavra do usuário

    out = _collapse_expanded_words(raw, origin, 1)

    assert out is not None and len(out) == 1
    assert out[0]["start"] == 1.0 and out[0]["end"] == 3.2
    assert out[0]["score"] == 0.5, "score fica com o pior pedaço (honesto)"


def test_colapso_preserva_palavras_separadas():
    raw = [{"start": 1.0, "end": 1.4, "score": 0.9},
           {"start": 1.5, "end": 2.0, "score": 0.8}]
    out = _collapse_expanded_words(raw, [0, 1], 2)

    assert out is not None
    assert [w["start"] for w in out] == [1.0, 1.5]


def test_colapso_sem_timestamp_devolve_none():
    # None => a run volta pra interpolação (comportamento seguro já existente)
    raw = [{"start": None, "end": None, "score": 0.0}]
    assert _collapse_expanded_words(raw, [0], 1) is None


# --- peso silábico ----------------------------------------------------------

def test_peso_silabico_conta_o_que_se_canta():
    # "20" não tem vogal: pesava 1. Cantado ("vinte") são 2 sílabas.
    assert _syllable_weight("20", "pt") == 2
    # "1985" = "mil novecentos e oitenta e cinco"
    assert _syllable_weight("1985", "pt") > 5


def test_peso_silabico_palavra_normal_inalterado():
    assert _syllable_weight("coração", "pt") == 3
    assert _syllable_weight("e", "pt") == 1


# --- issue #8: digito na transcricao do Whisper vira ancora falsa ----------

def test_digito_do_whisper_nao_vira_ancora():
    """
    CASO REAL (Joan Jett - I Love Rock-n-Roll): o Whisper escreve "17", o
    wav2vec2 nao tem digito no vocabulario => timestamp lixo. Se a letra do
    usuario tambem traz "17", o difflib casa EXATO e isso viraria uma ancora
    (confianca maxima) com tempo inventado. O gate recusa a ancora -> a
    palavra cai no realinhamento, que expande o numero.
    """
    whisper = [_ww("about", 10.0, 10.3), _ww("17", 10.4, 10.44), _ww("years", 11.0, 11.4)]
    real = ["about", "17", "years"]

    anchors = compute_anchors(whisper, real)

    assert anchors[0] is not None, "'about' casa normalmente"
    assert anchors[2] is not None, "'years' casa normalmente"
    assert anchors[1] is None, "'17' do Whisper NAO pode virar ancora (timestamp lixo)"


def test_gate_pega_digito_dentro_de_token_maior():
    # "17th", "2nd" - o wav2vec2 tampouco alinha a parte numerica
    assert _whisper_token_unreliable({"word": "17th"}) is True
    assert _whisper_token_unreliable({"word": "2nd"}) is True


def test_gate_nao_pega_palavra_normal():
    # regressao: o caminho comum nao pode perder ancora
    assert _whisper_token_unreliable({"word": "seventeen"}) is False
    assert _whisper_token_unreliable({"word": "casa"}) is False
    assert _whisper_token_unreliable({"word": ""}) is False


def test_palavra_normal_ao_lado_de_digito_ainda_ancora():
    # so o TOKEN com digito e recusado; os vizinhos seguem virando ancora
    whisper = [_ww("meus", 1.0, 1.3), _ww("20", 1.4, 1.44), _ww("anos", 2.0, 2.4)]
    real = ["meus", "20", "anos"]

    anchors = compute_anchors(whisper, real)

    assert [a is not None for a in anchors] == [True, False, True]

# -*- coding: utf-8 -*-
"""
Testes da lógica PURA do align.py (âncoras exatas/fuzzy, demoção de âncoras
suspeitas e interpolação ponderada) - nada aqui precisa de GPU nem de
whisperx instalado (os imports pesados do align.py são locais às funções
que rodam modelo).

Rodar:  python -m pytest tests/ -v   (ou python tests/test_align_logic.py)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.align import (
    SOURCE_ANCHOR,
    SOURCE_FUZZY,
    SOURCE_INTERPOLATED,
    SOURCE_LRC,
    anchor_and_interpolate,
    compute_anchors,
    match_lrc_to_lines,
    parse_lrc,
    seed_line_anchors,
    _fuzzy_pairs,
    _syllable_weight,
)


def _ww(word: str, start: float, end: float, score: float = 0.9) -> dict:
    """Atalho para montar uma palavra no formato de saída do whisperx."""
    return {"word": word, "start": start, "end": end, "score": score}


def test_exact_match_all_anchored():
    whisper = [_ww("Hoje", 1.0, 1.4), _ww("o", 1.5, 1.6), _ww("sol", 1.7, 2.1)]
    real = ["Hoje", "o", "sol"]
    timings = anchor_and_interpolate(whisper, real)
    assert all(t.source == SOURCE_ANCHOR for t in timings)
    assert timings[0].start == 1.0 and timings[2].end == 2.1


def test_fuzzy_recovers_spelling_variant():
    # Whisper grafa "pra" / "ta", letra diz "para" / "está": mesmo evento
    # acústico, o timestamp medido deve ser aproveitado (âncora fuzzy).
    whisper = [
        _ww("vou", 1.0, 1.3),
        _ww("pra", 1.4, 1.6),
        _ww("casa", 1.7, 2.2),
        _ww("ta", 2.5, 2.7),
        _ww("tarde", 2.8, 3.3),
    ]
    real = ["vou", "para", "casa", "está", "tarde"]
    timings = anchor_and_interpolate(whisper, real)
    assert timings[1].source == SOURCE_FUZZY
    assert timings[1].start == 1.4 and timings[1].end == 1.6
    assert timings[3].source == SOURCE_FUZZY
    assert timings[3].start == 2.5


def test_fuzzy_pairs_are_monotonic():
    pairs = _fuzzy_pairs(["casa", "verde", "linda"], ["caza", "verdi", "linta"])
    assert pairs == [(0, 0), (1, 1), (2, 2)]


def test_fuzzy_ignores_single_char_words():
    # similaridade de caracteres não diz nada sobre "e"/"a"/"o"
    assert _fuzzy_pairs(["e"], ["a"]) == []


def test_interpolation_weighted_by_syllables():
    # gap de 2 palavras entre âncoras: "coração" (3+ grupos de vogais) deve
    # receber mais tempo que "e" (1 grupo)
    whisper = [_ww("meu", 1.0, 1.2), _ww("bate", 4.0, 4.4)]
    real = ["meu", "coração", "e", "bate"]
    timings = anchor_and_interpolate(whisper, real)
    interp = [t for t in timings if t.source == SOURCE_INTERPOLATED]
    assert len(interp) == 2
    dur_coracao = interp[0].end - interp[0].start
    dur_e = interp[1].end - interp[1].start
    assert dur_coracao > dur_e
    # ordem temporal preservada e dentro da janela entre âncoras
    assert 1.2 <= interp[0].start < interp[1].start
    assert interp[1].end <= 4.0 + 1e-9


def test_suspicious_isolated_short_anchor_is_demoted():
    # "e" casado sozinho no meio de um trecho que o Whisper inteiro errou:
    # deve ser demovido (âncora suspeita) e virar interpolado.
    whisper = [
        _ww("inicio", 1.0, 1.5),
        _ww("xxx", 2.0, 2.2),
        _ww("yyy", 2.3, 2.5),
        _ww("zzz", 2.6, 2.8),
        _ww("e", 3.0, 3.1),
        _ww("aaa", 3.2, 3.4),
        _ww("bbb", 3.5, 3.7),
        _ww("ccc", 3.8, 4.0),
        _ww("fim", 5.0, 5.4),
    ]
    real = ["inicio", "um", "dois", "tres", "e", "quatro", "cinco", "seis", "fim"]
    anchors = compute_anchors(whisper, real)
    assert anchors[0] is not None and anchors[8] is not None
    assert anchors[4] is None, "âncora curta isolada num gap grande deve ser demovida"


def test_short_anchor_kept_when_neighbors_anchored():
    # o mesmo "e" NÃO deve ser demovido quando os vizinhos estão ancorados
    whisper = [_ww("sol", 1.0, 1.4), _ww("e", 1.5, 1.6), _ww("mar", 1.7, 2.1)]
    real = ["sol", "e", "mar"]
    anchors = compute_anchors(whisper, real)
    assert anchors[1] is not None and anchors[1][3] == SOURCE_ANCHOR


def test_leading_and_trailing_gaps_chain_sequentially():
    whisper = [_ww("meio", 10.0, 10.5)]
    real = ["abre", "alas", "meio", "fecha", "tudo"]
    timings = anchor_and_interpolate(whisper, real)
    # início: encadeia para trás terminando na âncora
    assert timings[1].end <= 10.0 + 1e-9
    assert timings[0].start < timings[1].start
    assert timings[0].start >= 0.0
    # fim: encadeia para frente a partir da âncora (starts distintos, sem
    # empilhar tudo no mesmo timestamp como na versão antiga)
    assert timings[3].start >= 10.5 - 1e-9
    assert timings[4].start > timings[3].start


def test_no_anchor_at_all_does_not_crash():
    timings = anchor_and_interpolate([], ["la", "la", "la"])
    assert len(timings) == 3
    assert all(t.source == SOURCE_INTERPOLATED for t in timings)
    assert timings[0].start < timings[1].start < timings[2].start


def test_syllable_weight_examples():
    assert _syllable_weight("e") == 1
    assert _syllable_weight("coração") >= 3
    assert _syllable_weight("saudade,") == 3
    assert _syllable_weight("") == 1  # nunca zero


def test_monotonic_output_full_mix():
    # mistura de tudo: exata, fuzzy, interpolada - saída deve ser monotônica
    whisper = [
        _ww("hoje", 1.0, 1.3),
        _ww("çeu", 2.0, 2.3),      # fuzzy com "céu"
        _ww("azul", 3.0, 3.4),
        _ww("brilha", 6.0, 6.5),
    ]
    real = ["hoje", "o", "céu", "azul", "sempre", "brilha"]
    timings = anchor_and_interpolate(whisper, real)
    starts = [t.start for t in timings]
    assert starts == sorted(starts), f"timestamps fora de ordem: {starts}"


# --------------------------------------------------------------------------
# LRCLIB: parse do .lrc, casamento de linhas e seeding de âncoras de linha
# --------------------------------------------------------------------------

def test_parse_lrc_basic():
    lrc = "[00:12.34]primeira frase\n[00:20.50]segunda frase\n[01:05.00]terceira"
    parsed = parse_lrc(lrc)
    assert parsed == [(12.34, "primeira frase"), (20.5, "segunda frase"), (65.0, "terceira")]


def test_parse_lrc_skips_metadata_and_empty():
    lrc = "[ar:Artista]\n[ti:Titulo]\n[length:03:20]\n[00:05.00]\n[00:10.00]canta"
    parsed = parse_lrc(lrc)
    # linhas de metadado (tag alfabética) e a linha só-timestamp são ignoradas
    assert parsed == [(10.0, "canta")]


def test_parse_lrc_multiple_stamps_same_line():
    # refrão repetido: um texto com dois timestamps vira duas entradas ordenadas
    lrc = "[00:30.00][01:30.00]refrão que volta"
    parsed = parse_lrc(lrc)
    assert parsed == [(30.0, "refrão que volta"), (90.0, "refrão que volta")]


def test_match_lrc_to_lines_sequential():
    lyric = ["hoje o sol", "brilha no céu", "e vai raiar"]
    lrc = [(1.0, "Hoje o sol"), (5.0, "Brilha no céu!"), (9.0, "E vai raiar")]
    matched = match_lrc_to_lines(lyric, lrc)
    assert matched == {0: 1.0, 1: 5.0, 2: 9.0}


def test_match_lrc_ignores_divergent_lines():
    # a linha do meio da letra não existe no .lrc -> só as pontas casam
    lyric = ["primeira linha", "linha extra do usuario", "ultima linha"]
    lrc = [(1.0, "primeira linha"), (8.0, "ultima linha")]
    matched = match_lrc_to_lines(lyric, lrc)
    assert 0 in matched and matched[0] == 1.0
    assert 2 in matched and matched[2] == 8.0
    assert 1 not in matched


def test_seed_fills_whisper_gap():
    # 2 linhas, 4 palavras; nada medido pelo Whisper (tudo None). O início de
    # cada linha (índices 0 e 2) recebe âncora do .lrc.
    anchors = [None, None, None, None]
    lyric_lines = [("hoje o", 0), ("sol nasce", 2)]
    lrc = [(2.0, "hoje o"), (6.0, "sol nasce")]
    seeded = seed_line_anchors(anchors, lyric_lines, lrc)
    assert seeded == 2
    assert anchors[0] is not None and anchors[0][0] == 2.0 and anchors[0][3] == SOURCE_LRC
    assert anchors[2] is not None and anchors[2][0] == 6.0
    assert anchors[1] is None and anchors[3] is None  # só a 1ª palavra da linha


def test_seed_does_not_overwrite_whisper_anchor():
    # se a 1ª palavra da linha já foi medida pelo Whisper, o .lrc não a toca
    anchors = [(1.5, 1.9, 0.9, SOURCE_ANCHOR), None]
    lyric_lines = [("hoje o", 0)]
    lrc = [(2.0, "hoje o")]
    seeded = seed_line_anchors(anchors, lyric_lines, lrc)
    assert seeded == 0
    assert anchors[0][3] == SOURCE_ANCHOR


def test_seed_skips_when_out_of_order():
    # o .lrc diz que a linha 2 começa em 3.0, mas já há uma âncora medida em
    # 8.0 antes dela: seria não-monotônico, então o seeding pula.
    anchors = [(8.0, 8.4, 0.9, SOURCE_ANCHOR), None]
    lyric_lines = [("primeira", 0), ("segunda linha", 1)]
    lrc = [(1.0, "primeira"), (3.0, "segunda linha")]
    seeded = seed_line_anchors(anchors, lyric_lines, lrc)
    # índice 0 já ancorado; índice 1 (t=3.0) viola monotonicidade (prev end 8.4)
    assert anchors[1] is None
    assert seeded == 0


if __name__ == "__main__":
    import inspect
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn()
                print(f"  ok: {name}")
            except AssertionError as e:
                failed += 1
                print(f"FALHOU: {name}: {e}")
    print("FALHAS:", failed)
    sys.exit(1 if failed else 0)

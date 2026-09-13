# -*- coding: utf-8 -*-
"""
Testes da lógica PURA de video_export.py (conversão beat->segundo, montagem
das tags de karaokê, agrupamento em linhas, quebra de linha, escape do ASS)
- sem ffmpeg, sem áudio e sem renderizar vídeo nenhum.

O módulo foi escrito com essa separação de propósito: build_ass() é
string-entra/string-sai, e só render_mp4() toca disco e chama subprocesso.
Assim o que pode dar errado silenciosamente (um tempo deslocado, uma sílaba
faltando) é testável em milissegundos.

Rodar:  python -m pytest tests/ -v   (ou python tests/test_video_export_logic.py)
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.ultrastar_writer import Note, Song
from pipeline.video_export import (
    ass_escape,
    ass_time,
    beat_to_seconds,
    build_ass,
    group_lines,
    line_to_karaoke_text,
    notes_to_syllables,
    wrap_syllables,
    Syllable,
)


def _note(start, dur, text, singer=0) -> Note:
    return Note(start_beat=start, duration_beats=dur, pitch=0, text=text,
                note_type=":", singer=singer)


def _song(notes, breaks, bpm=240.0, gap_ms=0, duet=False) -> Song:
    return Song(title="T", artist="A", mp3_filename="a.mp3", bpm=bpm,
                gap_ms=gap_ms, notes=notes,
                phrase_breaks_after_index=breaks, duet=duet)


# ---------------------------------------------------------------------------
# Conversão de tempo
# ---------------------------------------------------------------------------

def test_beat_to_seconds_usa_a_formula_oficial():
    # A fórmula do formato é beat*60/(BPM*4) + GAP/1000. Com BPM 240 o beat
    # vale 60/(240*4) = 0,0625 s, então 16 beats = exatamente 1 segundo.
    assert beat_to_seconds(16, 240.0, 0) == 1.0
    assert beat_to_seconds(0, 240.0, 0) == 0.0


def test_beat_to_seconds_soma_o_gap():
    # O #GAP é o offset em MILISSEGUNDOS antes do beat 0 - some, não escale.
    assert beat_to_seconds(16, 240.0, 500) == 1.5


def test_beat_to_seconds_nao_multiplica_por_quatro_duas_vezes():
    """
    Guarda de regressão do bug histórico do projeto (ver beatgrid.py): o "*4"
    é do motor e vale UMA vez. Se alguém "corrigir" isto multiplicando de
    novo, a letra andaria 4x mais rápido que a música - o mesmo sintoma que
    já apareceu uma vez no .txt, e que num vídeo renderizado seria muito mais
    caro de descobrir (só olhando o mp4 pronto).
    """
    bpm = 123.05
    assert abs(beat_to_seconds(266, bpm, 0) - 266 * 60 / (bpm * 4)) < 1e-9
    assert beat_to_seconds(266, bpm, 0) > 30  # ~32,4 s; se fosse /4 daria ~8 s


def test_ass_time_formata_em_centesimos():
    assert ass_time(0) == "0:00:00.00"
    assert ass_time(1.5) == "0:00:01.50"
    assert ass_time(3661.25) == "1:01:01.25"
    assert ass_time(-5) == "0:00:00.00"  # nunca emite tempo negativo


# ---------------------------------------------------------------------------
# Agrupamento em linhas
# ---------------------------------------------------------------------------

def test_group_lines_usa_os_phrase_breaks():
    notes = [_note(0, 1, "a"), _note(1, 1, "b"), _note(2, 1, "c")]
    assert [len(l) for l in group_lines(_song(notes, [0]))] == [1, 2]


def test_group_lines_sem_breaks_devolve_uma_linha_so():
    notes = [_note(0, 1, "a"), _note(1, 1, "b")]
    assert len(group_lines(_song(notes, []))) == 1


def test_group_lines_nao_perde_a_ultima_linha():
    """A cauda depois do último "-" tem que virar linha, não sumir."""
    notes = [_note(0, 1, "a"), _note(1, 1, "b"), _note(2, 1, "c")]
    lines = group_lines(_song(notes, [0]))
    assert sum(len(l) for l in lines) == 3


# ---------------------------------------------------------------------------
# Sílabas e melisma
# ---------------------------------------------------------------------------

def test_notas_de_continuacao_nao_viram_texto():
    """
    "~" é notação de PITCH do UltraStar, não texto. Se virasse sílaba, uma
    palavra sustentada apareceria escrita "star~~~" na tela do vídeo.
    """
    notes = [_note(0, 16, "star "), _note(16, 16, "~"), _note(32, 16, "~")]
    syls = notes_to_syllables(notes, 240.0, 0)
    assert [s.text for s in syls] == ["star "]


def test_continuacao_estende_a_silaba_anterior():
    """O preenchimento tem que correr durante toda a sustentação."""
    notes = [_note(0, 16, "star "), _note(16, 16, "~")]
    syls = notes_to_syllables(notes, 240.0, 0)
    assert syls[0].start_s == 0.0
    assert syls[0].end_s == 2.0  # 32 beats a 240 BPM


def test_continuacao_orfa_no_inicio_e_descartada():
    """Um "~" sem nota anterior não tem o que estender - não pode explodir."""
    syls = notes_to_syllables([_note(0, 16, "~"), _note(16, 16, "ok")], 240.0, 0)
    assert [s.text for s in syls] == ["ok"]


# ---------------------------------------------------------------------------
# Tags de karaokê
# ---------------------------------------------------------------------------

def test_duracao_vai_ate_o_inicio_da_proxima_silaba():
    """
    Cada sílaba é preenchida até a PRÓXIMA começar, não até o próprio fim.
    Aqui a 1ª nota dura 1 s mas a 2ª só entra em 2 s: a tag tem que dizer
    200 centésimos, senão o preenchimento corre e trava parado 1 segundo.
    """
    syls = [Syllable("ab ", 0.0, 1.0), Syllable("cd", 2.0, 3.0)]
    assert "{\\kf200}ab " in line_to_karaoke_text(syls)


def _parse_dialogue(line: str) -> tuple[float, str]:
    """('0:00:01.50', texto) -> (1.5, texto). Só para os testes."""
    campos = line.split(",", 9)
    h, m, s = campos[1].split(":")
    return int(h) * 3600 + int(m) * 60 + float(s), campos[9]


def _quando_cada_silaba_acende(dialogue_line: str) -> list[float]:
    """
    Reconstrói o horário ABSOLUTO (em segundos, no relógio da música) em que
    cada sílaba começa a ser preenchida - que é o que o espectador vê.

    É a leitura de um PLAYER de verdade: no ASS as durações de karaokê são
    relativas ao INÍCIO DO EVENTO, então o relógio parte do Start do Dialogue
    e vai acumulando as tags na ordem. É justamente essa acumulação que o bug
    do adiantamento quebrava.
    """
    import re
    inicio, texto = _parse_dialogue(dialogue_line)
    relogio = inicio
    acendem: list[float] = []
    for tag, centesimos in re.findall(r"\{\\(k|kf)(\d+)\}", texto):
        if tag == "kf":              # sílaba visível: marca quando acende
            acendem.append(round(relogio, 2))
        relogio += int(centesimos) / 100.0
    return acendem


def test_silabas_acendem_no_tempo_REAL_da_nota():
    """
    REGRESSÃO DO BUG DE 02/09/2026 (letra ~3 s adiantada a música inteira).

    Este é o teste que faltava. Os antigos conferiam as durações e o início do
    evento separadamente - ambos certos - sem nunca checar a RELAÇÃO entre os
    dois, que era onde o erro estava. Aqui reconstruímos o horário absoluto em
    que cada sílaba acende, do jeito que um player faz, e comparamos com o
    tempo real da nota.

    O GAP não-nulo é essencial: com #GAP 0 (como quase todos os testes antigos
    usavam) o erro fica pequeno e passa despercebido.
    """
    BPM, GAP = 240.0, 3000          # canto começa 3 s depois do início da faixa
    notes = [_note(0, 8, "Pri"), _note(8, 8, "mei"), _note(16, 8, "ra "),
             _note(96, 8, "Se"), _note(104, 8, "gun"), _note(112, 8, "da ")]
    song = _song(notes, [2, 5], bpm=BPM, gap_ms=GAP)

    esperado = [beat_to_seconds(n["start_beat"] if isinstance(n, dict)
                                else n.start_beat, BPM, GAP) for n in notes]

    principais = [l for l in build_ass(song).splitlines()
                  if l.startswith("Dialogue:") and ",Main," in l]
    medido = [t for l in principais for t in _quando_cada_silaba_acende(l)]

    assert len(medido) == len(esperado), (medido, esperado)
    for got, want in zip(medido, esperado):
        assert abs(got - want) <= 0.02, (
            f"sílaba acende em {got:.2f}s, deveria acender em {want:.2f}s "
            f"(adiantada {want - got:+.2f}s)"
        )


def test_primeira_silaba_nao_acende_no_aparecimento_da_linha():
    """
    Guarda direta e legível do mesmo bug: a linha aparece ANTES para dar tempo
    de ler, então o preenchimento NÃO pode começar junto com ela.
    """
    song = _song([_note(0, 8, "ola "), _note(8, 8, "mundo")], [1],
                 bpm=240.0, gap_ms=3000)
    linha = [l for l in build_ass(song).splitlines() if ",Main," in l][0]
    aparece, _ = _parse_dialogue(linha)
    acende = _quando_cada_silaba_acende(linha)[0]

    assert acende > aparece, "o preenchimento começou junto com a linha"
    assert abs(acende - 3.0) < 0.02, f"deveria acender em 3,00 s, acendeu em {acende:.2f} s"


def test_espera_do_lead_in_e_emitida_como_tag_sem_texto():
    """A pausa é um {\\k...} sem texto na frente - a forma idiomática do ASS."""
    song = _song([_note(0, 8, "oi")], [0], bpm=240.0, gap_ms=3000)
    linha = [l for l in build_ass(song).splitlines() if ",Main," in l][0]
    assert "{\\k220}{\\kf" in linha


def test_sem_lead_in_nenhum_nao_emite_espera():
    """Linha que aparece exatamente quando é cantada não ganha pausa à toa."""
    # com GAP 0 a 1ª linha aparece em 0,00 e é cantada em 0,00
    song = _song([_note(0, 8, "ja")], [0], bpm=240.0, gap_ms=0)
    linha = [l for l in build_ass(song).splitlines() if ",Main," in l][0]
    assert "{\\k0}" not in linha and linha.split(",,")[-1].startswith("{\\kf")


def test_ultima_silaba_usa_o_proprio_fim():
    syls = [Syllable("fim", 0.0, 1.0)]
    assert line_to_karaoke_text(syls) == "{\\kf100}fim"


def test_duracao_nunca_e_zero():
    """Uma sílaba muito curta ainda precisa de pelo menos 1 centésimo."""
    syls = [Syllable("x", 0.0, 0.001)]
    assert "{\\kf1}" in line_to_karaoke_text(syls)


def test_texto_vazio_nao_quebra():
    assert line_to_karaoke_text([]) == ""


# ---------------------------------------------------------------------------
# Escape
# ---------------------------------------------------------------------------

def test_escape_das_chaves_e_barras():
    """
    "{" abre bloco de tags no ASS: sem escape, a letra vira comando e SOME da
    tela sem erro nenhum. Modo de falha silencioso, por isso o teste.
    """
    assert ass_escape("a{b}c") == "a\\{b\\}c"
    assert ass_escape("a\\b") == "a\\\\b"


def test_acentos_passam_intactos():
    """Português é o idioma-alvo do projeto; acento não pode ser mexido."""
    assert ass_escape("coração") == "coração"


# ---------------------------------------------------------------------------
# Quebra de linha
# ---------------------------------------------------------------------------

def test_quebra_so_em_fronteira_de_palavra():
    """Partir "co-ra-ção" no meio da palavra ficaria pior que a linha larga."""
    syls = [Syllable("co", 0, 1), Syllable("ra", 1, 2), Syllable("ção ", 2, 3),
            Syllable("mi", 3, 4), Syllable("nha ", 4, 5)]
    for idx in wrap_syllables(syls, max_chars=6):
        assert syls[idx - 1].text.endswith(" ")


def test_linha_curta_nao_quebra():
    syls = [Syllable("oi ", 0, 1), Syllable("tu", 1, 2)]
    assert wrap_syllables(syls, max_chars=40) == []


def test_palavra_unica_gigante_nao_quebra_no_meio():
    """Sem espaço nenhum não há onde quebrar - melhor largo que picotado."""
    assert wrap_syllables([Syllable("a" * 80, 0, 1)], max_chars=10) == []


# ---------------------------------------------------------------------------
# Arquivo .ass completo
# ---------------------------------------------------------------------------

def _ass_of_two_lines(duet=False, singer2=0):
    notes = [_note(0, 8, "Oi "), _note(8, 8, "voce"),
             _note(160, 8, "tchau", singer=singer2)]
    return build_ass(_song(notes, [1], duet=duet))


def test_ass_tem_as_secoes_obrigatorias():
    ass = _ass_of_two_lines()
    for section in ("[Script Info]", "[V4+ Styles]", "[Events]"):
        assert section in ass


def test_ass_emite_um_dialogue_por_linha_cantada():
    ass = _ass_of_two_lines()
    principais = [l for l in ass.splitlines() if l.startswith("Dialogue:")
                  and ",Main," in l]
    assert len(principais) == 2


def test_ass_mostra_a_proxima_linha_como_previa():
    ass = _ass_of_two_lines()
    previas = [l for l in ass.splitlines() if ",Next," in l]
    # 1 prévia (a 2ª linha aparecendo embaixo durante a 1ª) + 1 contagem
    # regressiva (o intervalo até a 2ª linha passa de 4 s neste fixture).
    assert len(previas) == 2


def test_dueto_usa_estilo_proprio_para_o_segundo_cantor():
    ass = _ass_of_two_lines(duet=True, singer2=2)
    assert "Style: MainP2," in ass
    assert ",MainP2," in ass


def test_sem_dueto_nao_cria_estilo_do_p2():
    assert "MainP2" not in _ass_of_two_lines(duet=False)


def test_linha_nunca_aparece_antes_da_anterior_terminar():
    """
    O lead-in adianta a linha em ~2 s para dar tempo de ler. Em música rápida
    isso faria a linha nova nascer POR CIMA da anterior ainda na tela. O
    aparecimento é limitado pelo fim da anterior - este teste tranca isso.
    """
    # duas linhas coladas: a 2ª começa 0,5 s depois do fim da 1ª
    notes = [_note(0, 16, "um"), _note(24, 16, "dois")]
    ass = build_ass(_song(notes, [0]))
    starts = [l.split(",")[1] for l in ass.splitlines()
              if l.startswith("Dialogue:") and ",Main," in l]
    assert starts[1] >= "0:00:01.00"  # fim da 1ª linha, não 0:00:00.00


def test_musica_sem_notas_gera_ass_valido():
    """Vale ter cabeçalho e nenhum evento - não pode explodir."""
    ass = build_ass(_song([], []))
    assert "[Events]" in ass
    assert "Dialogue:" not in ass


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))


# ---------------------------------------------------------------------------
# Re-renderização avulsa (pós-revisão)
# ---------------------------------------------------------------------------

def test_rerender_sem_song_data_explica_o_motivo(tmp_path, monkeypatch):
    """
    A pasta pode não ter o song_data.json (opção "manter apenas o essencial"
    apaga esse arquivo). A mensagem tem que dizer isso, não estourar um
    KeyError ou um traceback.
    """
    from pipeline.video_export import rerender_from_folder
    import pytest as _pytest
    monkeypatch.setenv("USKMAKER_LANG", "en")
    with _pytest.raises(FileNotFoundError) as exc:
        rerender_from_folder(tmp_path)
    msg = str(exc.value)
    assert "song_data.json" in msg
    assert "essentials" in msg      # aponta a causa provável


@pytest.mark.parametrize("lang,esperado", [("pt", "essencial"), ("en", "essentials")])
def test_mensagens_saem_no_idioma_escolhido(tmp_path, monkeypatch, lang, esperado):
    """
    REGRESSÃO (uso real, 02/09/2026): este caminho roda no TERMINAL, fora da
    interface bilíngue do app - a mensagem é a única coisa que o usuário vê.
    Um usuário de língua inglesa ficou travado num prompt em português.
    """
    from pipeline.video_export import rerender_from_folder
    monkeypatch.setenv("USKMAKER_LANG", lang)
    with pytest.raises(FileNotFoundError) as exc:
        rerender_from_folder(tmp_path)
    assert esperado in str(exc.value)


@pytest.mark.parametrize("loc,esperado", [
    (None,           "en"),   # sem pista nenhuma -> inglês alcança mais gente
    ("en_US",        "en"),
    ("pt_BR",        "pt"),
    ("es_ES",        "en"),   # idioma não suportado cai no inglês, não no pt
])
def test_idioma_vem_do_locale_quando_nao_ha_override(monkeypatch, loc, esperado):
    import locale as _locale
    from pipeline import video_export
    monkeypatch.delenv("USKMAKER_LANG", raising=False)
    monkeypatch.setattr(_locale, "getlocale", lambda *a, **k: (loc, None))
    monkeypatch.setattr(_locale, "getdefaultlocale", lambda *a, **k: (loc, None),
                        raising=False)
    assert video_export._lang() == esperado


def test_override_de_idioma_ganha_do_locale(monkeypatch):
    """O app passa a escolha do usuário; ela manda sobre o locale da máquina."""
    import locale as _locale
    from pipeline import video_export
    monkeypatch.setattr(_locale, "getlocale", lambda *a, **k: ("pt_BR", None))
    monkeypatch.setenv("USKMAKER_LANG", "en")
    assert video_export._lang() == "en"


def test_rerender_sem_audio_explica_o_motivo(tmp_path, monkeypatch):
    """song_data.json presente mas o áudio do pacote sumiu."""
    import json
    from pipeline.video_export import rerender_from_folder
    import pytest as _pytest
    monkeypatch.setenv("USKMAKER_LANG", "en")
    (tmp_path / "song_data.json").write_text(json.dumps({
        "title": "T", "artist": "A", "mp3_filename": "sumiu.mp3",
        "bpm": 240.0, "gap_ms": 0, "notes": [], "phrase_breaks_after_index": [],
    }), encoding="utf-8")
    with _pytest.raises(FileNotFoundError) as exc:
        rerender_from_folder(tmp_path)
    assert "sumiu.mp3" in str(exc.value)


# ---------------------------------------------------------------------------
# Espaço de fim de palavra em nota de continuação
# ---------------------------------------------------------------------------

def test_REGRESSAO_palavras_nao_grudam_quando_o_melisma_carrega_o_espaco():
    """
    BUG REAL (print do usuário, 02/09/2026): "beenlonelysince", "missyou",
    "Oh,and" - palavras coladas na tela, com a letra digitada CERTA.

    Pela convenção do build_song.py, o espaço que separa duas palavras é
    grudado na ÚLTIMA nota da palavra. Quando essa última nota é uma
    continuação de melisma, seu texto é "~ " - til MAIS espaço. Descartar a
    nota inteira (por ser "~") levava o espaço junto.

    Padrão exato tirado dos dados reais do usuário:
        'miss' + '~ ' + 'you, '   ->  tem que virar "miss you, "
    """
    notes = [_note(0, 8, "miss"), _note(8, 8, "~ "), _note(16, 8, "you, ")]
    texto = "".join(s.text for s in notes_to_syllables(notes, 240.0, 0))
    assert texto == "miss you, ", f"saiu {texto!r}"
    assert "missyou" not in texto


def test_continuacao_sem_espaco_nao_inventa_um():
    """
    "~" no MEIO de uma palavra (sustentação de uma sílaba interna) não tem
    espaço nenhum - inventar um partiria a palavra em duas.
    """
    notes = [_note(0, 8, "lo"), _note(8, 8, "~"), _note(16, 8, "nely ")]
    assert "".join(s.text for s in notes_to_syllables(notes, 240.0, 0)) == "lonely "


def test_nao_duplica_espaco_ja_existente():
    notes = [_note(0, 8, "been "), _note(8, 8, "~ "), _note(16, 8, "lonely ")]
    assert "".join(s.text for s in notes_to_syllables(notes, 240.0, 0)) == "been lonely "


def test_varias_continuacoes_o_espaco_da_ultima_conta():
    """Sustentação longa vira vários "~"; só o último carrega o fim da palavra."""
    notes = [_note(0, 8, "been"), _note(8, 8, "~"), _note(16, 8, "~"),
             _note(24, 8, "~ "), _note(32, 8, "lonely ")]
    assert "".join(s.text for s in notes_to_syllables(notes, 240.0, 0)) == "been lonely "


def test_o_til_nunca_aparece_na_tela():
    """O "~" é notação de pitch; só o espaço ao lado dele é texto de verdade."""
    notes = [_note(0, 8, "miss"), _note(8, 8, "~ "), _note(16, 8, "you ")]
    assert "~" not in "".join(s.text for s in notes_to_syllables(notes, 240.0, 0))


def test_silaba_que_fecha_linha_visual_nao_leva_espaco_pendurado():
    """
    Texto centralizado: um espaço no fim da linha conta na largura e empurra
    a linha para a esquerda do centro. Invisível, mas desalinha.
    """
    # sílabas longas o bastante para estourar MAX_CHARS_PER_LINE e forçar
    # uma quebra de verdade - senão o teste passa sem testar nada
    syls = [Syllable("aaaaaaaaaaaa ", 0, 1), Syllable("bbbbbbbbbbbb ", 1, 2),
            Syllable("cccccccccccc ", 2, 3), Syllable("dddddddddddd ", 3, 4)]
    txt = line_to_karaoke_text(syls, 0.0)
    assert " \\N" not in txt, txt
    assert "\\N" in txt          # e a quebra continua existindo

# -*- coding: utf-8 -*-
"""
Testes da lógica pura do harness de avaliação (eval/) - sem GPU/modelo:
parser de .txt UltraStar, segmentação de palavras do chart gold, matching
por onset, avaliação duet e o loader de song_data.json.

Rodar:  python tests/test_eval_logic.py   (ou python -m pytest tests/ -v)
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "eval"))

import usdx_parse
import evaluate
import library_replay
from library_replay import gold_words, match_words, timing_stats

SYNTHETIC_CHART = """#TITLE:Test Song
#ARTIST:Tester
#LANGUAGE:Spanish
#BPM:300,5
#GAP:1000
#MP3:test.mp3
: 0 4 5 Ho
: 4 4 5 la 
: 8 4 7 mun
: 12 4 7 do
- 20
: 24 4 9  bri
: 28 8 9 llo
: 36 4 0 ~
E
: 99 9 9 depois do E deve ser ignorado
"""

DUET_CHART = """#TITLE:Duet
#ARTIST:Two
#BPM:240
#GAP:0
#DUETSINGERP1:Ana
#DUETSINGERP2:Bruno
P 1
: 0 4 5 la
: 4 4 5 la
P 2
: 16 4 12 na
: 20 4 12 na
E
"""


def test_parse_headers_and_timing():
    chart = usdx_parse.parse(SYNTHETIC_CHART)
    assert chart.title == "Test Song"
    assert chart.artist == "Tester"
    assert chart.language == "Spanish"
    assert chart.bpm == 300.5  # vírgula decimal (StrToFloatI18n) aceita
    assert chart.gap_ms == 1000.0
    # fórmula oficial: time = GAP/1000 + beat * 60 / (BPM*4)
    assert abs(chart.beat_to_time(0) - 1.0) < 1e-9
    assert abs(chart.beat_to_time(4) - (1.0 + 4 * 15.0 / 300.5)) < 1e-9


def test_parse_notes_breaks_and_end_marker():
    chart = usdx_parse.parse(SYNTHETIC_CHART)
    assert len(chart.lines) == 2  # quebra "- 20" separa as frases
    assert [n.text for n in chart.lines[0].notes] == ["Ho", "la ", "mun", "do"]
    # espaços NÃO são aparados - marcam fronteira de palavra
    assert chart.lines[0].notes[1].text.endswith(" ")
    assert chart.lines[1].break_beat == 20
    # tudo depois do E é ignorado
    total_notes = sum(len(l.notes) for l in chart.lines)
    assert total_notes == 7


def test_gold_words_segmentation():
    chart = usdx_parse.parse(SYNTHETIC_CHART)
    words = gold_words(chart)
    # "Ho"+"la " -> "Hola"; "mun"+"do" -> "mundo"; " bri"+"llo"+"~" -> "brillo"
    assert [w["text"] for w in words] == ["Hola", "mundo", "brillo"]
    # o hold "~" estende o fim da palavra até o beat 40
    brillo = words[2]
    assert abs(brillo["end"] - chart.beat_to_time(40)) < 1e-9
    # início da palavra vem do primeiro beat dela
    assert abs(brillo["start"] - chart.beat_to_time(24)) < 1e-9


def test_match_words_normalizes_accents_and_case():
    gold = [{"text": "Corazón"}, {"text": "partío"}, {"text": "ya"}]
    hyp = [{"text": "corazon"}, {"text": "partio"}, {"text": "ya"}]
    pairs = match_words(gold, hyp)
    assert pairs == [(0, 0), (1, 1), (2, 2)]


def test_timing_stats_within_1s():
    gold = [{"text": "a", "start": 0.0, "end": 0.5},
            {"text": "b", "start": 10.0, "end": 10.5},
            {"text": "c", "start": 20.0, "end": 20.5}]
    hyp = [{"text": "a", "start": 0.3, "end": 0.8},    # dentro de 1s
           {"text": "b", "start": 11.5, "end": 12.0},  # fora de 1s
           {"text": "c", "start": 20.9, "end": 21.4}]  # dentro de 1s
    stats = timing_stats(gold, hyp, [(0, 0), (1, 1), (2, 2)])
    assert stats["recall"] == 1.0
    assert stats["within_1s"] == round(2 / 3, 3)
    assert stats["onset"]["median_ms"] == 900.0


def test_onset_match_respects_tolerance():
    mk = lambda t: evaluate.TimedNote(t, t + 0.1, 0, "x")
    gen = [mk(0.0), mk(1.0), mk(5.0)]
    ref = [mk(0.05), mk(1.25), mk(9.0)]
    pairs = evaluate._match(gen, ref, tol=0.3)
    # 9.0 está fora da tolerância de qualquer nota gerada
    assert len(pairs) == 2
    starts = {(g.start, r.start) for g, r in pairs}
    assert starts == {(0.0, 0.05), (1.0, 1.25)}


def test_identical_charts_score_perfect():
    chart = usdx_parse.parse(SYNTHETIC_CHART)
    m = evaluate.evaluate(chart, chart)
    assert m["note_count_ratio"] == 1.0
    assert m["match_rate_vs_ref"] == 1.0
    assert m["onset_err_ms_median"] == 0.0
    assert m["lyric_similarity"] == 1.0
    assert m["pitch_within_2st_rate"] == 1.0


def test_duet_chart_flattens_to_single_player():
    # avaliação é single-player por enquanto (USKMaker só gera 1 track):
    # um gold [MULTI] achata P1+P2 em ordem de tempo - o que um jogador
    # sozinho canta cobrindo as duas partes. Se/quando geração de dueto
    # existir, re-portar o keep_tracks/evaluate_duet do usdx-autochart.
    chart = usdx_parse.parse(DUET_CHART)
    all_notes = [n for l in chart.lines for n in l.notes]
    assert len(all_notes) == 4  # as duas partes presentes, nenhuma perdida
    flat = evaluate._flatten(chart)
    assert [t.text for t in flat] == ["la", "la", "na", "na"]
    # ordenado no tempo mesmo vindo de blocos P1/P2 separados
    assert all(a.start <= b.start for a, b in zip(flat, flat[1:]))


def test_song_data_loader_matches_txt_semantics():
    # mesmo conteúdo do SYNTHETIC_CHART, no formato do song_data.json que o
    # rust-core usa pra escrever o .txt - os tempos devem bater exatamente
    data = {
        "title": "Test Song", "artist": "Tester", "language": "es",
        "bpm": 300.5, "gap_ms": 1000, "mp3_filename": "test.ogg",
        "notes": [
            {"start_beat": 0, "duration_beats": 4, "pitch": 5, "text": "Ho", "note_type": ":", "source": "anchor"},
            {"start_beat": 4, "duration_beats": 4, "pitch": 5, "text": "la ", "note_type": ":", "source": "anchor"},
            {"start_beat": 8, "duration_beats": 4, "pitch": 7, "text": "mun", "note_type": ":", "source": "fuzzy"},
            {"start_beat": 12, "duration_beats": 4, "pitch": 7, "text": "do", "note_type": ":", "source": "interpolated"},
            {"start_beat": 24, "duration_beats": 4, "pitch": 9, "text": " bri", "note_type": ":", "source": "lrc"},
            {"start_beat": 28, "duration_beats": 8, "pitch": 9, "text": "llo", "note_type": ":", "source": "anchor"},
            {"start_beat": 36, "duration_beats": 4, "pitch": 0, "text": "~", "note_type": ":", "source": "anchor"},
        ],
        "phrase_breaks_after_index": [3],
    }
    chart = evaluate.chart_from_song_data(data)
    assert len(chart.lines) == 2
    assert len(chart.lines[0].notes) == 4 and len(chart.lines[1].notes) == 3
    ref = usdx_parse.parse(SYNTHETIC_CHART)
    m = evaluate.evaluate(chart, ref)
    assert m["match_rate_vs_ref"] == 1.0
    assert m["onset_err_ms_median"] == 0.0
    # 1 de 7 notas interpolada
    assert evaluate.interpolated_fraction(data) == round(1 / 7, 3)


def test_interpolated_fraction_without_sources():
    assert evaluate.interpolated_fraction({"notes": [{"text": "a"}]}) is None



# --- scan_library: descobrir o audio da musica -----------------------------

def _mk_song_dir(tmp, folder, gold_name, audio_header, extra_files=()):
    d = tmp / folder
    d.mkdir(parents=True)
    (d / gold_name).write_text(
        "\n".join([
            "#TITLE:T",
            "#ARTIST:A",
            f"#MP3:{audio_header}",
            "#BPM:200",
            "#GAP:0",
            ": 0 2 0 la",
            "E",
        ]),
        encoding="utf-8",
    )
    for f in extra_files:
        (d / f).write_bytes(b"x")
    return d


def test_scan_aceita_m4a_o_formato_padrao_do_usdb_syncer(tmp_path):
    """
    O usdb_syncer baixa em M4A por PADRAO. Exigir .mp3 fazia o harness
    descartar em silencio uma biblioteca inteira baixada com os defaults.
    """
    _mk_song_dir(tmp_path, "A - T", "A - T.txt", "A - T.m4a", ["A - T.m4a"])
    songs = library_replay.scan_library(str(tmp_path))
    assert len(songs) == 1
    assert songs[0]["mp3"].endswith("A - T.m4a")


def test_scan_ignora_faixas_separadas_e_pega_a_mistura(tmp_path):
    """
    Com separacao ligada (no usdb_syncer ou aqui) a pasta tem 3 audios.
    O chart diz qual e o principal - "exatamente um audio" nunca bateria.
    """
    _mk_song_dir(
        tmp_path, "A - T", "A - T.txt", "A - T.mp3",
        ["A - T.mp3", "A - T [VOC].mp3", "A - T [INSTR].mp3"],
    )
    songs = library_replay.scan_library(str(tmp_path))
    assert len(songs) == 1
    assert songs[0]["mp3"].endswith("A - T.mp3")
    assert "[VOC]" not in songs[0]["mp3"] and "[INSTR]" not in songs[0]["mp3"]


def test_scan_cai_na_heuristica_quando_o_header_mente(tmp_path):
    # chart cita um arquivo que nao veio junto -> nao desiste, usa o unico audio
    _mk_song_dir(tmp_path, "A - T", "A - T.txt", "nao-existe.mp3", ["A - T.ogg"])
    songs = library_replay.scan_library(str(tmp_path))
    assert len(songs) == 1
    assert songs[0]["mp3"].endswith("A - T.ogg")


def test_scan_pula_pasta_sem_audio(tmp_path):
    _mk_song_dir(tmp_path, "A - T", "A - T.txt", "A - T.mp3")  # sem o audio
    assert library_replay.scan_library(str(tmp_path)) == []


def test_scan_pula_chart_multi(tmp_path):
    _mk_song_dir(tmp_path, "A - T", "A - T [MULTI].txt", "A - T.mp3", ["A - T.mp3"])
    assert library_replay.scan_library(str(tmp_path)) == []


# --- normalize_language: o #LANGUAGE dos charts reais ----------------------

def test_idioma_aceita_codigo_iso():
    # 'pt' era o 2o valor mais comum na biblioteca real (70 musicas) e o mapa
    # de nomes exatos o descartava - justo o idioma que mais nos interessa
    assert library_replay.normalize_language("pt") == "pt"
    assert library_replay.normalize_language("EN") == "en"


def test_idioma_ignora_qualificador_entre_parenteses():
    assert library_replay.normalize_language("Portuguese (Brazil)") == "pt"
    assert library_replay.normalize_language("Japanese (romanized)") == "ja"


def test_idioma_multivalor_usa_o_primeiro():
    # medir no idioma principal e melhor que descartar a musica
    assert library_replay.normalize_language("English, French") == "en"
    assert library_replay.normalize_language("English/Italian") == "en"


def test_idioma_nome_por_extenso_continua_funcionando():
    assert library_replay.normalize_language("Portuguese") == "pt"
    assert library_replay.normalize_language("español") == "es"


def test_idioma_vazio_ou_desconhecido_devolve_none():
    # None => a musica e pulada; chutar o idioma seria pior que nao medir
    assert library_replay.normalize_language("") is None
    assert library_replay.normalize_language(None) is None
    assert library_replay.normalize_language("Klingon") is None


# --- portoes de qualidade de dado (nao e falha do pipeline) ----------------

def _w(*textos):
    return [{"text": t} for t in textos]


def test_romaji_detecta_chart_japones_romanizado():
    """
    CASO REAL: "Abingdon boys school - Innocent sorrow (TV)" diz
    #LANGUAGE:Japanese mas a letra e romaji. Mandavamos 'ja' pro whisper, que
    transcreve em kana/kanji -> zero ancora, w_1s 0.000, 89% interpoladas,
    como se o PIPELINE tivesse falhado.
    """
    gw = _w("Sake", "ta", "mune", "no", "kizuguchi", "ni", "Afure", "nagareru")
    assert library_replay.is_romanized_chart("ja", gw) is True


def test_romaji_nao_dispara_em_letra_japonesa_de_verdade():
    gw = _w("咲", "いた", "胸", "の", "傷口", "に")
    assert library_replay.is_romanized_chart("ja", gw) is False


def test_romaji_nao_dispara_em_idioma_de_escrita_latina():
    # ingles/espanhol/portugues sao latinos por natureza - o portao nao pode
    # engolir a biblioteca inteira
    gw = _w("Dancing", "Queen", "young", "and", "sweet")
    assert library_replay.is_romanized_chart("en", gw) is False
    assert library_replay.is_romanized_chart("pt", gw) is False


class _ChartFalso:
    """Chart minimo com o necessario pro detector de duracao."""
    def __init__(self, fim_s):
        self._fim = fim_s
        n = type("N", (), {"start_beat": 0, "duration": 100})()
        self.lines = [type("L", (), {"notes": [n]})()]

    def beat_to_time(self, beat):
        return self._fim


def test_audio_mais_curto_que_o_chart_e_versao_errada(monkeypatch):
    # CASO REAL: RuPaul - Supermodel, chart ate 270.4s, audio de 248.5s.
    # O chart nao CABE: e outra edicao. Pontuavamos 50s de onset como erro nosso.
    monkeypatch.setattr(library_replay, "_audio_duration", lambda p: 248.5)
    motivo = library_replay.audio_chart_mismatch("x.mp3", _ChartFalso(270.4))
    assert motivo and "outra versão" in motivo


def test_audio_mais_longo_que_o_chart_e_normal(monkeypatch):
    # outro/aplausos/fade depois da ultima nota - nao e problema
    monkeypatch.setattr(library_replay, "_audio_duration", lambda p: 236.7)
    assert library_replay.audio_chart_mismatch("x.mp3", _ChartFalso(230.7)) is None


def test_duracao_desconhecida_nao_conclui_nada(monkeypatch):
    # na duvida, MEDE - o portao so age quando tem prova
    monkeypatch.setattr(library_replay, "_audio_duration", lambda p: None)
    assert library_replay.audio_chart_mismatch("x.mp3", _ChartFalso(999.0)) is None


# --- portao 2: audio deslocado (offset de GAP), so visivel POS-alinhamento --

def _offset_case(gold_starts, hyp_starts):
    gold = [{"text": "w", "start": s, "end": s + 0.4} for s in gold_starts]
    hyp = [{"text": "w", "start": s, "end": s + 0.4} for s in hyp_starts]
    pairs = [(i, i) for i in range(len(gold_starts))]
    return gold, hyp, pairs


def test_offset_constante_e_deslocamento_de_dado():
    # CASO REAL: Paul/Queen/Aerosmith - nosso = 1.00*gold + 67s. Duracao total
    # bate (audio_chart_mismatch nao pega), mas TODO onset erra por 67s.
    g = [3.0 * i for i in range(40)]
    gold, hyp, pairs = _offset_case(g, [s + 67.0 for s in g])
    motivo = library_replay.offset_data_mismatch(gold, hyp, pairs)
    assert motivo and "deslocado" in motivo


def test_offset_bem_alinhado_nao_dispara():
    # w_1s cru ja e otimo -> nao ha offset a remover, mede-se normal
    g = [3.0 * i for i in range(40)]
    gold, hyp, pairs = _offset_case(g, [s + 0.1 for s in g])
    assert library_replay.offset_data_mismatch(gold, hyp, pairs) is None


def test_offset_alinhamento_quebrado_nao_e_confundido_com_dado():
    # Whisper errou a letra: nuvem espalhada, nenhuma reta encaixa em 1s.
    # Tem de continuar contando como FALHA NOSSA (retorna None aqui).
    g = [3.0 * i for i in range(40)]
    scatter = [((-1) ** i) * (2.0 + (i % 7)) for i in range(40)]  # 2..8s, +/-
    gold, hyp, pairs = _offset_case(g, [gi + o for gi, o in zip(g, scatter)])
    assert library_replay.offset_data_mismatch(gold, hyp, pairs) is None


def test_offset_quebra_parcial_nao_dispara():
    # metade certa na reta, metade espalhada -> o ajuste nao chega a 85%
    g = [3.0 * i for i in range(40)]
    h = [gi + (0.1 if i < 12 else ((-1) ** i) * 5.0) for i, gi in enumerate(g)]
    gold, hyp, pairs = _offset_case(g, h)
    assert library_replay.offset_data_mismatch(gold, hyp, pairs) is None


def test_offset_poucos_pares_nao_conclui_nada():
    # amostra pequena demais pra confiar no ajuste linear
    gold, hyp, pairs = _offset_case([0.0, 3.0, 6.0], [67.0, 70.0, 73.0])
    assert library_replay.offset_data_mismatch(gold, hyp, pairs) is None


# --- pitch: o jogo compara modulo 12, e o gold nao manda na oitava ---------

def _fake_pitch_track(midis, dur=1.0):
    """Frames de F0 constante por nota, um segundo cada."""
    import numpy as np
    t, hz, v = [], [], []
    for i, m in enumerate(midis):
        for k in range(10):
            t.append(i * dur + k * dur / 10)
            hz.append(440.0 * (2 ** ((m - 69) / 12.0)))
            v.append(True)
    return np.array(t), np.array(hz), np.array(v)


def test_pitch_oitava_errada_pune_no_absoluto_mas_nao_no_mod12():
    """
    A spec v1 diz: "Game implementations MAY decide to compare pitches
    independently of the octave (i.e. compare pitches modulo 12)". Ou seja a
    OITAVA do gold nao e verdade fundamental - o charter escreve a que quiser.

    CASO REAL (Shakira - Estoy aqui): o erro cru se agrupa em multiplos exatos
    de oitava (64 notas em -12, 54 em -24) - o contorno bate, a oitava nao.
    """
    import numpy as np
    # gold: contorno 0,+4,+7,+4,0... (UltraStar: 0 = C4 = MIDI 60)
    contorno = [0, 4, 7, 4, 0, 4, 7, 4, 0, 4, 7, 4]
    notes = [(float(i), float(i) + 0.9, p) for i, p in enumerate(contorno)]
    # nos medimos o MESMO contorno, uma oitava abaixo
    t, hz, v = _fake_pitch_track([60 + p - 12 for p in contorno])

    m = library_replay.pitch_metrics(notes, t, hz, v)

    # a mediana some dos dois lados, entao uma oitava CONSTANTE ja seria
    # absorvida - o que este teste trava e a metrica mod12 existir e bater
    assert m["within_2st_mod12"] == 1.0
    assert m["contour_corr"] > 0.99


def test_pitch_mod12_nao_perdoa_nota_errada():
    # o mod12 nao pode virar desculpa: nota errada (nao oitava) continua errada
    import numpy as np
    contorno = [0, 4, 7, 4, 0, 4, 7, 4, 0, 4, 7, 4]
    notes = [(float(i), float(i) + 0.9, p) for i, p in enumerate(contorno)]
    # medimos um contorno INVERTIDO (nada a ver com oitava)
    t, hz, v = _fake_pitch_track([60 - p for p in contorno])

    m = library_replay.pitch_metrics(notes, t, hz, v)

    assert m["within_2st_mod12"] < 0.6
    assert m["contour_corr"] < 0

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"[OK]   {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"[FAIL] {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} testes passaram")
    sys.exit(1 if failed else 0)

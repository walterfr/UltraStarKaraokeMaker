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

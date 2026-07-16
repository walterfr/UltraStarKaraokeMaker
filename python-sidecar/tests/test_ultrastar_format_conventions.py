# -*- coding: utf-8 -*-
"""
Verifica a saída da pipeline contra as CONVENÇÕES REAIS do formato
UltraStar - extraídas de uma carta feita à mão pela comunidade (não
inventadas), não só o que a spec formal permite. Existe pra pegar
exatamente a classe de bug já vista neste projeto: "~" (melisma) tomando o
lugar de uma sílaba/palavra real por causa de um limite de palavra errado
(ver align.py, caso real "ver"/"ser" em "Te quiero ver ser").

Referência (opcional - os testes que dependem dela pulam se a pasta não
existir neste ambiente; ela não faz parte do repositório):
    D:\\Canciones Karaoke\\3 Doors Down - It's Not My Time\\...

Rodar:  python -m pytest tests/ -v   (ou python tests/test_ultrastar_format_conventions.py)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REFERENCE_FILE = Path(
    r"D:\Canciones Karaoke\3 Doors Down - It's Not My Time\3 Doors Down - It's Not My Time.txt"
)
# Saída real da pipeline (só existe em máquinas que já rodaram a pipeline
# de verdade pra essa música - não faz parte do repositório).
GENERATED_FILE = Path(__file__).resolve().parents[2] / "New Output" / "Milo J - Ama De Mi Sol" / "Milo J - Ama De Mi Sol.txt"


def parse_notes(txt: str) -> list[tuple[str, int, int, int, str]]:
    """
    Parser mínimo de linhas de nota do formato UltraStar (":"/"*"/"F"),
    ignora header (#...), quebra de frase ("- ...") e fim de arquivo ("E").
    """
    notes: list[tuple[str, int, int, int, str]] = []
    for line in txt.splitlines():
        line = line.rstrip("\n").rstrip("\r")
        if not line or line[0] not in (":", "*", "F"):
            continue
        parts = line.split(" ", 4)
        if len(parts) < 5:
            continue
        note_type, start, dur, pitch, text = parts
        notes.append((note_type, int(start), int(dur), int(pitch), text))
    return notes


def melisma_convention_violations(notes: list[tuple[str, int, int, int, str]]) -> list[str]:
    """
    Convenções observadas em cartas feitas à mão da comunidade:
      1. "~" nunca é a PRIMEIRA nota de uma palavra - só continua uma nota
         que já tem texto real antes dela na MESMA palavra (o texto
         anterior não pode terminar em espaço, que marcaria fim de palavra).
      2. Nenhuma nota tem texto vazio.
      3. Nenhuma nota tem texto só-pontuação, exceto o próprio "~".
    Retorna a lista de violações (vazia = conforme).
    """
    violations: list[str] = []
    prev_text: str | None = None
    for i, (_note_type, start, _dur, _pitch, text) in enumerate(notes):
        stripped = text.strip()
        is_melisma = stripped.startswith("~")  # "~" pode carregar pontuação de borda ("~?", "~,")
        if stripped == "":
            violations.append(f"nota {i} (beat {start}): texto vazio")
        elif is_melisma:
            starts_new_word = prev_text is None or prev_text.endswith(" ")
            if starts_new_word:
                violations.append(
                    f"nota {i} (beat {start}): '~' aparece como PRIMEIRA nota de uma "
                    f"palavra (texto da nota anterior: {prev_text!r})"
                )
        elif not any(c.isalnum() for c in stripped):
            violations.append(f"nota {i} (beat {start}): texto só-pontuação ({stripped!r})")
        prev_text = text
    return violations


def test_parse_notes_reads_reference_file():
    if not REFERENCE_FILE.exists():
        return
    notes = parse_notes(REFERENCE_FILE.read_text(encoding="latin-1"))
    assert len(notes) > 50  # sanity check: o parser realmente leu algo


def test_reference_file_has_no_melisma_convention_violations():
    # valida o PRÓPRIO checker de convenções contra uma carta real feita à
    # mão - se o checker acusar violação aqui, o checker está errado, não a
    # carta de referência.
    if not REFERENCE_FILE.exists():
        return
    notes = parse_notes(REFERENCE_FILE.read_text(encoding="latin-1"))
    violations = melisma_convention_violations(notes)
    assert violations == [], "\n".join(violations)


def test_synthetic_word_boundary_violation_is_detected():
    # garante que o checker REALMENTE pega o bug de verdade ("~" comendo o
    # lugar de uma palavra nova, caso real "ver"/"ser") e não é um checker
    # manco que sempre passa.
    notes = [
        (":", 0, 2, 0, "ver "),  # "ver" TERMINA a palavra (espaço = fronteira)
        (":", 2, 2, 0, "~"),  # violação: deveria ser a palavra "ser" começando, não "~"
    ]
    violations = melisma_convention_violations(notes)
    assert len(violations) == 1
    assert "beat 2" in violations[0]


def test_synthetic_melisma_chain_within_same_word_is_valid():
    # múltiplas notas "~" seguidas são válidas ENQUANTO nenhuma delas segue
    # uma nota que já terminou a palavra (espaço à direita).
    notes = [
        (":", 0, 2, 0, "ver"),
        (":", 2, 2, 0, "~"),
        (":", 4, 2, 0, "~ "),  # última nota da palavra, sem violação
    ]
    assert melisma_convention_violations(notes) == []


def test_generated_song_matches_community_conventions():
    """
    Verifica que a saída de verdade da pipeline (gerada com todos os fixes
    de hoje ativos, incluindo o isolamento de voz principal e a proteção de
    lacuna de voz no melisma) não viola as mesmas convenções de uma carta
    real da comunidade - a prova de que o "~" agora só decora sustentação
    de verdade, não uma sobra de fronteira de palavra errada.
    """
    if not GENERATED_FILE.exists():
        return
    notes = parse_notes(GENERATED_FILE.read_text(encoding="utf-8"))
    assert len(notes) > 100
    violations = melisma_convention_violations(notes)
    assert violations == [], "\n".join(violations)


def test_header_traz_audio_junto_do_mp3():
    """
    #AUDIO e #MP3 apontam para o MESMO arquivo, de propósito.

    A spec v1 (a publicada) exige o #MP3 e trata o #AUDIO como opcional, mas
    manda "desconsiderar o #MP3 se o #AUDIO estiver presente"; a v2 promove o
    #AUDIO a header core. Escrever os dois serve player velho e novo.

    Este writer (Python) precisa sair IGUAL ao rust-core, que é quem escreve
    o .txt final dentro do app.
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from pipeline.ultrastar_writer import Note, Song

    song = Song(
        title="Sangue Latino",
        artist="Rita Lee",
        mp3_filename="Rita Lee - Sangue Latino.ogg",
        bpm=123.05,
        gap_ms=0,
        notes=[Note(start_beat=0, duration_beats=2, pitch=0, text="Ju")],
    )
    txt = song.to_txt()

    assert "#MP3:Rita Lee - Sangue Latino.ogg" in txt
    assert "#AUDIO:Rita Lee - Sangue Latino.ogg" in txt


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

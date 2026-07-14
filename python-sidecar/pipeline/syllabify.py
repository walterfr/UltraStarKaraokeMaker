"""
syllabify.py
Quebra cada palavra alinhada em sílabas, já que o UltraStar espera
(idealmente) uma sílaba cantável por nota, não a palavra inteira.

Usa pyphen (hifenização) com dicionário pt_BR como base. Isso NÃO é
perfeito para canto (hifenização ortográfica != divisão silábica cantada
- ex.: elisões, contrações regionais), mas é um ponto de partida sólido.
Casos que vão exigir ajuste manual futuro (Fase 4 - tela de revisão):
  - Elisão cantada ("de + eu" -> "d'eu")
  - Palavras estendidas por vários beats (ex.: "amoooor")
  - Ad-libs e vocalizações sem "palavra" real
"""

from __future__ import annotations

import pyphen

_dic = pyphen.Pyphen(lang="pt_BR")


def split_word_syllables(word: str) -> list[str]:
    """
    Retorna a lista de sílabas de uma palavra, preservando pontuação simples
    (mantida na última sílaba para não quebrar a leitura da letra na tela).
    """
    if not word:
        return []

    # separa pontuação de borda (vírgula, ponto, reticências etc.) para não
    # atrapalhar a hifenização, e devolve depois
    core = word.strip()
    leading_punct = ""
    trailing_punct = ""

    while core and not core[0].isalnum():
        leading_punct += core[0]
        core = core[1:]
    while core and not core[-1].isalnum():
        trailing_punct = core[-1] + trailing_punct
        core = core[:-1]

    if not core:
        # token era só pontuação (ex.: um "'" isolado por espaço na letra) -
        # não tem conteúdo cantável, não deve virar sílaba/nota própria.
        return []

    if any(not c.isalnum() for c in core):
        # pontuação NO MEIO da palavra (ex.: contração "It's") - a
        # hifenização do pyphen (dicionário pt_BR) não sabe lidar com isso e
        # tende a isolar o caractere de pontuação como se fosse uma sílaba
        # própria. Mais seguro manter a palavra inteira como uma sílaba só
        # do que arriscar uma hifenização sem sentido.
        return [leading_punct + core + trailing_punct]

    hyphenated = _dic.inserted(core)  # ex.: "ca-ro-lin-da"
    syllables = hyphenated.split("-")

    syllables[0] = leading_punct + syllables[0]
    syllables[-1] = syllables[-1] + trailing_punct

    return syllables


if __name__ == "__main__":
    # teste manual rápido
    for w in ["coração", "saudade,", "impossível...", "é"]:
        print(w, "->", split_word_syllables(w))

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

_dic: pyphen.Pyphen | None = None

# Dicionário por idioma da música (código do Whisper). Antes TODO idioma usava
# o pt_BR, e em inglês ele parte palavra demais ("lo-ve"): cada sílaba a mais é
# uma nota a mais. MEDIDO (01/10/2026) contra a divisão dos charts feitos à mão
# de uma biblioteca de ~500 músicas (144 mil palavras em inglês, 8,4 mil em
# sueco) - mesma contagem de sílabas que o chart / divisão idêntica:
#   inglês  pt_BR 0,807 / 0,781 (13,6% com sílaba A MAIS) -> en_US 0,935 / 0,854 (0,5%)
#   sueco   pt_BR 0,934 / 0,887                          -> sv    0,962 / 0,906
# left/right = menor pedaço permitido na borda da palavra. Em inglês, 1 letra
# ("a-way") parte palavra demais no resto (same count 0,833); em sueco 1 na
# esquerda foi o melhor. Idioma sem entrada aqui segue no pt_BR, como antes.
_LANG_DICTS = {
    "en": ("en_US", 2, 2),
    "sv": ("sv", 1, 2),
}
_dic_cache: dict[str, pyphen.Pyphen] = {}

# Contrações faladas e palavras comuns de 2 sílabas que o dicionário tipográfico
# en_US (TeX) não separa por estética de impressão (prefixos de 1 vogal como
# "a-round", "o-ver", "e-ven", além de "to-night" e "clo-ver"), mas que no canto
# têm 2 sílabas claras em notas diferentes.
_EN_SPLITS = {
    "gonna": 3,
    "wanna": 3,
    "gotta": 3,
    "around": 1,
    "away": 1,
    "again": 1,
    "alone": 1,
    "alive": 1,
    "about": 1,
    "above": 1,
    "across": 1,
    "afraid": 1,
    "ahead": 1,
    "apart": 1,
    "asleep": 1,
    "awake": 1,
    "along": 1,
    "among": 1,
    "aside": 1,
    "aware": 1,
    "awhile": 1,
    "ago": 1,
    "over": 1,
    "open": 1,
    "even": 1,
    "evil": 1,
    "enough": 1,
    "tonight": 2,
    "today": 2,
    "clover": 3,
}


def _dictionary(language: str | None) -> pyphen.Pyphen:
    import pyphen

    entry = _LANG_DICTS.get((language or "").lower())
    if entry is None:
        global _dic
        if _dic is None:
            _dic = pyphen.Pyphen(lang="pt_BR")
        return _dic
    key = entry[0]
    if key not in _dic_cache:
        _dic_cache[key] = pyphen.Pyphen(lang=entry[0], left=entry[1], right=entry[2])
    return _dic_cache[key]


def split_word_syllables(word: str, language: str | None = None) -> list[str]:
    """
    Retorna a lista de sílabas de uma palavra, preservando pontuação simples
    (mantida na última sílaba para não quebrar a leitura da letra na tela).
    `language` = código do idioma da música ("en", "sv", ...); sem ele (ou
    idioma sem dicionário próprio) usa o pt_BR de sempre.
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

    lang_low = (language or "").lower()
    cut = _EN_SPLITS.get(core.lower()) if lang_low == "en" else None
    if cut:
        syllables = [core[:cut], core[cut:]]
    elif (
        lang_low == "en"
        and trailing_punct.startswith(("'", "’"))
        and len(core) >= 4
        and core.lower().endswith("in")
    ):
        # G-dropping coloquial em inglês ("Lookin'", "wonderin'", "Thinkin'"):
        # sem o "g" final o pyphen en_US não reconhece o sufixo "-ing" e deixa
        # "Lookin" inteiro ou junta "derin" numa sílaba só. Hifenizar com "g"
        # provisório recupera a mesma divisão de "Looking" / "wondering".
        g_char = "G" if core[-1].isupper() else "g"
        hyphenated = _dictionary(language).inserted(core + g_char)
        syllables = hyphenated.split("-")
        syllables[-1] = syllables[-1][:-1]
        syllables = [s for s in syllables if s]
    else:
        hyphenated = _dictionary(language).inserted(core)  # ex.: "ca-ro-lin-da"
        syllables = hyphenated.split("-")

    syllables[0] = leading_punct + syllables[0]
    syllables[-1] = syllables[-1] + trailing_punct

    return syllables


if __name__ == "__main__":
    # teste manual rápido
    for w in ["coração", "saudade,", "impossível...", "é"]:
        print(w, "->", split_word_syllables(w))

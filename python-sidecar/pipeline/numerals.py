"""
numerals.py - expansão de números por extenso para o ALINHAMENTO.

POR QUE ISTO EXISTE (medido, não suposto - "20 e poucos anos", Raimundos,
16/07/2026):

A letra que o usuário fornece escreve números como DÍGITOS ("Que os meus 20"),
mas ninguém canta "dois-zero" - canta "vinte". Isso quebra os dois passes que
dependem de texto:

  1. Âncoras: o Whisper transcreve "vinte", a letra diz "20". O difflib compara
     token a token e não casa - nem a âncora fuzzy salva (a similaridade de
     caracteres entre "20" e "vinte" é zero).
  2. Realinhamento (wav2vec2): o vocabulário do modelo de alinhamento tem 46
     tokens e NENHUM dígito (verificado: só letras, apóstrofo e hífen). Mandar
     "20" pro forced alignment não tem como casar com frame de áudio nenhum, e
     o CTC colapsa a palavra num piscar.

Efeito medido no caso real: o Whisper mediu "vinte" em 38,70-38,98 (0,28 s,
duração plausível); nós gravávamos a nota de "20" em 38,96-39,00 - 260 ms
atrasada e 6,5x curta demais. Acontecia nas 4 ocorrências, e o pior é que a
nota saía marcada como MEDIDA (source=realign), então nem caía na tela de
revisão.

DECISÃO DE DESIGN: expandimos os números SÓ para comparar/alinhar. O texto que
vai pro .txt continua sendo o do usuário ("20", não "vinte") - a premissa do
USKMaker é que a letra é dele, não nossa para reescrever. (O UltraSinger, que
transcreve do zero, faz o contrário: troca o número no resultado e oferece um
flag --keep_numbers pra desligar. Aqui isso seria um bug, não um recurso.)
"""

from __future__ import annotations

import re

# num2words cobre bem os idiomas que nos interessam; se faltar o idioma (ou a
# lib), degradamos pro comportamento antigo em vez de quebrar a geração.
try:
    from num2words import num2words as _num2words
except ImportError:  # pragma: no cover - só em ambiente incompleto
    _num2words = None

_DIGITS_RE = re.compile(r"^\d+$")

# Acima disso, "por extenso" vira uma frase gigante que quase certamente não é
# o que se canta (ex.: um ano "1985" ok; um número de telefone, não). Também
# protege contra token absurdo travar o num2words.
_MAX_DIGITS = 4

_cache: dict[tuple[str, str], list[str]] = {}


def expand_numeral(token: str, language: str) -> list[str]:
    """
    Devolve o token expandido por extenso, já tokenizado em palavras.

    "20"   + pt -> ["vinte"]
    "1985" + pt -> ["mil", "novecentos", "e", "oitenta", "e", "cinco"]
    "20"   + en -> ["twenty"]
    "casa"       -> ["casa"]            (não é número: devolve intacto)
    "20anos"     -> ["20anos"]          (misto: conservador, não mexe)

    Nunca levanta: idioma desconhecido/lib ausente devolve [token].
    """
    if not _DIGITS_RE.match(token) or _num2words is None:
        return [token]
    if len(token) > _MAX_DIGITS:
        return [token]

    key = (token, language)
    hit = _cache.get(key)
    if hit is not None:
        return hit

    try:
        spelled = _num2words(int(token), lang=language)
    except (NotImplementedError, OverflowError, ValueError):
        # idioma não suportado pelo num2words -> comportamento antigo
        return [token]

    # "oitenta e cinco" / "twenty-one" -> tokens de palavra
    words = [w for w in re.split(r"[\s\-,]+", spelled) if w]
    result = words or [token]
    _cache[key] = result
    return result


def expand_tokens(tokens: list[str], language: str) -> tuple[list[str], list[int]]:
    """
    Expande uma lista de tokens, devolvendo (tokens_expandidos, origem), onde
    `origem[i]` é o índice do token ORIGINAL que gerou o expandido `i`.

    (["Que", "os", "meus", "20"], "pt")
        -> (["Que", "os", "meus", "vinte"], [0, 1, 2, 3])

    (["ano", "1985"], "pt")
        -> (["ano", "mil", "novecentos", "e", "oitenta", "e", "cinco"],
            [0, 1, 1, 1, 1, 1, 1])

    O mapa é o que permite colapsar o resultado de volta pra palavra do usuário.
    """
    out: list[str] = []
    origin: list[int] = []
    for i, tok in enumerate(tokens):
        for piece in expand_numeral(tok, language):
            out.append(piece)
            origin.append(i)
    return out, origin

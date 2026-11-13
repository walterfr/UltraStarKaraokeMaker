#!/usr/bin/env python3
"""
read_video_info.py
Lê os metadados de um vídeo do YouTube SEM BAIXAR NADA e imprime como JSON.
Irmão do read_tags.py (que faz o mesmo para arquivo local) - mesma promessa:
resposta rápida, nunca um traceback, JSON vazio em qualquer falha.

PARA QUE SERVE: pré-preencher artista/título e, principalmente, descobrir a
DURAÇÃO da faixa antes de gerar.

A duração é o que resolve a escolha de letra no LRCLIB. A base é colaborativa
e a mesma música costuma ter dezenas de registros - edit de rádio, versão de
álbum, extendida. CASO REAL (02/09/2026, "Camouflage - The Great Commandment"):
18 registros, 16 com sincronia, durações de 188 s a 398 s. Sem saber que o
áudio tinha 188 s, escolher "o primeiro sincronizado" é sorteio: dá pra pegar
o remix de seis minutos e meio, cujos tempos não servem pra nada.

O artista/título importam ANTES disso: o LRCLIB é consultado POR artista e
título, e o título de um vídeo costuma vir como "Banda - Música (Official
Video) [HD Remaster]". Com esse texto na consulta, nenhuma ordenação salva -
a busca já sai envenenada. Por isso limpamos o ruído aqui.

Uso:   python read_video_info.py <url>
Saída: JSON {"title","artist","duration","uploader"} (ausentes = null).
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata

# Ruído que gravadora/uploader grudam no título e que não é o nome da música.
# Removido do TÍTULO, nunca do artista - "(Band)" não existe, "(Live)" sim.
#
# Palavras que, sozinhas dentro de um (...) ou [...], denunciam o grupo inteiro
# como ruído - em inglês, português e espanhol: "(Video Oficial)", "(Clipe
# Oficial)", "(Letra)", "(Official 4K Video)". Sempre como PALAVRA INTEIRA
# (\b): "(Birthday)" contém "hd" e "(Eclipse)" contém "clip", e os dois ficam.
_NOISE_WORDS = (
    r"official|oficial|v[ií]deo|videoclipe?|clipe?|lyrics?|letras?|[aá]udio"
    r"|visuali[sz]er|legendad[oa]|subtitulad[oa]|hd|hq|4k|8k|1080p|720p"
)

_NOISE_PATTERNS = (
    rf"[\(\[][^\(\)\[\]]*\b(?:{_NOISE_WORDS})\b[^\(\)\[\]]*[\)\]]",
    r"\(\s*remaster(?:ed)?(?:\s*\d{4})?\s*\)",
    r"\[\s*remaster(?:ed)?(?:\s*\d{4})?\s*\]",
    r"\(\s*full\s*album\s*\)",
    r"\bofficial\s+music\s+video\b",
    r"\bofficial\s+video\b",
)

# Separadores usados entre artista e música num título de vídeo. O hífen
# cercado de espaços é o dominante; sem espaços seria perigoso ("AC-DC").
_TITLE_SEPARATORS = (" - ", " – ", " — ", " | ", " ~ ")


# Pontuação de sobra que pode ficar nas pontas depois de tirar o ruído.
# Parênteses e colchetes NÃO entram aqui - ver _drop_unbalanced_brackets.
_TRIM_CHARS = " -–—|~·.,"

# Cada parêntese/colchete e o seu par - usado para decidir se um deles, numa
# das pontas, é casca solta ou parte do nome da música.
_BRACKET_PAIR = {"(": ")", ")": "(", "[": "]", "]": "["}


def _drop_unbalanced_brackets(text: str) -> str:
    """
    Tira SÓ a casca de parêntese/colchete que ficou sem par nas pontas.

    BUG REAL (07/09/2026, "Ministry - Effigy (Im Not An)"): a limpeza antiga
    terminava com `.strip(" -–—|~·.,()[]")`, que come qualquer parêntese das
    pontas - inclusive o que FECHA um nome legítimo. Todo título terminado em
    ")" chegava truncado ao formulário ("Effigy (Im Not An"), e daí para a
    consulta do LRCLIB, para o nome da pasta e para o .txt gerado. O teste que
    existia para isso ("Until Death (Us Do Part)") só conferia se o miolo
    sobrevivia, então o erro passou despercebido.

    Agora um fecha-parêntese só sai se não houver abre-parêntese para ele (e
    vice-versa) - que é o caso de casca de verdade, deixada pela remoção do
    ruído.
    """
    out = text
    while True:
        if out and out[-1] in _BRACKET_PAIR:
            if out.count(_BRACKET_PAIR[out[-1]]) < out.count(out[-1]):
                out = out[:-1].rstrip(_TRIM_CHARS)
                continue
        if out and out[0] in _BRACKET_PAIR:
            if out.count(_BRACKET_PAIR[out[0]]) < out.count(out[0]):
                out = out[1:].lstrip(_TRIM_CHARS)
                continue
        return out


def _is_emoji_junk(c: str) -> bool:
    """Emoji e os invisíveis que só existem grudados nele."""
    if c in "°№":       # categoria So, mas fazem parte de nome ("360°", "№ 5")
        return False
    return (
        unicodedata.category(c) in ("So", "Cs")
        or "\U0001f3fb" <= c <= "\U0001f3ff"    # tom de pele (o resto de Sk fica: "`", "^")
        or "\ufe00" <= c <= "\ufe0f"            # seletores de variação
        or c == "\u20e3"                        # keycap combinante
    )


def _strip_emoji(text: str) -> str:
    """
    Tira emoji SEM deixar invisível para trás: U+2764 U+FE0F largava o U+FE0F,
    o keycap largava U+FE0F e U+20E3, e a família com ZWJ largava os U+200D.

    Mn/Cf NÃO saem em bloco - hindi, árabe e persa dependem deles. O ZWJ só sai
    quando está órfão; entre letras/marcas (conjunto do devanágari: letra +
    virama + ZWJ + letra) ele fica. A vizinhança é a do texto ORIGINAL, senão
    "a<emoji>ZWJ<emoji>b" deixaria o ZWJ "entre letras".
    """
    text = unicodedata.normalize("NFC", text)

    def wordish(c: str) -> bool:
        return unicodedata.category(c)[0] in "LMN" and not _is_emoji_junk(c)

    out = []
    for i, c in enumerate(text):
        if c == "\u200d":
            if not (0 < i < len(text) - 1 and wordish(text[i - 1]) and wordish(text[i + 1])):
                continue
        elif _is_emoji_junk(c):
            continue
        out.append(c)
    return "".join(out)


def _strip_trailing_noise_word(title: str) -> str:
    """
    "Cancao con letra" -> "Cancao". Só no TÍTULO já separado do artista e só
    se sobrar alguma palavra: uma música chamada "Lyrics" continua "Lyrics".
    """
    m = re.search(r"(?:^|\s+)(?:con\s+letra|lyrics?|letra|legendado)$", title, flags=re.IGNORECASE)
    head = title[:m.start()].rstrip(_TRIM_CHARS) if m else ""
    return head if re.search(r"\w", head) else title


def strip_title_noise(text: str) -> str:
    """Tira "(Official Video)", "[HD]", "(Remastered 2019)", emojis e afins."""
    out = _strip_emoji(text)
    for pattern in _NOISE_PATTERNS:
        out = re.sub(pattern, " ", out, flags=re.IGNORECASE)
    # Parênteses/colchetes que ficaram VAZIOS depois de tirar o conteúdo.
    # Sem isto, "Close To Me (Official Video) [4K]" saía "Close To Me [ ]" - o
    # ruído some mas a casca fica, e vai parar na consulta ao LRCLIB.
    out = re.sub(r"[\(\[]\s*[\)\]]", " ", out)
    # sobra de pontuação e espaço duplicado depois das remoções
    out = re.sub(r"\s{2,}", " ", out)
    out = out.strip(_TRIM_CHARS)
    return _drop_unbalanced_brackets(out).strip()


def split_artist_title(video_title: str) -> tuple[str | None, str | None]:
    """
    "Camouflage - The Great Commandment (Official Video)"
        -> ("Camouflage", "The Great Commandment")

    Divide no PRIMEIRO separador: "Artista - Música - Ao Vivo" tem o artista
    antes do primeiro, e o resto é o nome da música. Sem separador, não há
    como saber quem é quem - devolve (None, título limpo) e deixa o usuário
    preencher o artista, em vez de inventar uma divisão errada.
    """
    cleaned = strip_title_noise(video_title or "")
    if not cleaned:
        return None, None
    for sep in _TITLE_SEPARATORS:
        if sep in cleaned:
            artist, _, title = cleaned.partition(sep)
            # " | " DEPOIS da divisão não separa mais nada: é o canal/filme
            # ("Música | Trilha do Filme Tal"). Só sai se sobrar título antes.
            title = re.split(r"\s[|｜]\s", title, maxsplit=1)[0].strip() or title
            artist, title = artist.strip(), _strip_trailing_noise_word(strip_title_noise(title))
            if artist and title:
                return artist, title
    return None, _strip_trailing_noise_word(cleaned)


def pick_artist_title(info: dict) -> tuple[str | None, str | None]:
    """
    Escolhe artista/título a partir do dicionário do yt-dlp.

    ORDEM DELIBERADA: os campos `artist`/`track` vêm do YouTube Music e já são
    os nomes limpos da gravadora - infinitamente melhores que qualquer regex
    em cima de um título de vídeo. Só quando faltam é que caímos na divisão do
    título. `uploader` entra por último como artista: num canal oficial ele é
    o artista, mas num canal de terceiros é o nome do canal - melhor que nada,
    e o usuário corrige antes de buscar a letra.
    """
    artist = (info.get("artist") or "").strip() or None
    track = (info.get("track") or "").strip() or None
    if artist and track:
        return artist, track

    guess_artist, guess_title = split_artist_title(info.get("title") or "")
    raw_uploader = (info.get("uploader") or "").strip()
    clean_uploader = re.sub(r"\s*-\s*Topic$|VEVO$", "", raw_uploader, flags=re.IGNORECASE).strip() or None
    artist = artist or guess_artist or clean_uploader
    title = track or guess_title
    return artist, title


def read_video_info(url: str) -> dict:
    """
    Metadados do vídeo, sem baixar o vídeo.

    `skip_download` + `quiet`: só a extração de informação, que é uma consulta
    rápida à página. Nenhum arquivo é escrito.
    """
    from yt_dlp import YoutubeDL

    from pipeline.proc_utils import ensure_ffmpeg_on_path, yt_cookies_browser

    # Deno (runtime JS do yt-dlp) na pasta bin do USKMaker - ver proc_utils
    ensure_ffmpeg_on_path()
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "extract_flat": False,
    }
    browser = yt_cookies_browser()
    if browser:
        opts["cookiesfrombrowser"] = (browser,)
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    artist, title = pick_artist_title(info or {})
    duration = info.get("duration") if info else None
    return {
        "title": title,
        "artist": artist,
        "duration": float(duration) if duration else None,
        "uploader": (info.get("uploader") or None) if info else None,
    }


def classify_error(message: str) -> str:
    """
    Tipo do erro do yt-dlp, para a interface dizer O QUE fazer: "bot" (o
    YouTube quer sessão logada - ligar os cookies resolve), "age", "private",
    "unavailable", "cookies" (não deu pra ler os cookies do navegador) ou
    "other".
    """
    low = message.lower()
    if "sign in to confirm your age" in low:
        return "age"
    if "sign in to confirm you" in low:
        return "bot"
    if ("could not find" in low and "cookies" in low) or "failed to decrypt" in low \
            or ("cookie" in low and "database" in low):
        return "cookies"
    if "private video" in low:
        return "private"
    if "video unavailable" in low:
        return "unavailable"
    return "other"


if __name__ == "__main__":
    result: dict = {}
    try:
        if len(sys.argv) >= 2:
            result = read_video_info(sys.argv[1])
    except Exception as e:
        # Mesma promessa do read_tags.py: isto é conveniência. Falhar aqui não
        # pode impedir ninguém de gerar a música digitando os campos à mão -
        # mas o MOTIVO vai junto, senão o usuário só vê "não deu" (antes o
        # erro era engolido e o bloqueio "confirm you're not a bot" do YouTube
        # aparecia como uma falha qualquer).
        msg = str(e).replace("ERROR: ", "").strip()
        result = {"error": classify_error(msg), "detail": msg[:300]}
    sys.stdout.write(json.dumps(result))

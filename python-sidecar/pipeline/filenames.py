"""
filenames.py - nome de arquivo seguro para os pacotes.

POR QUE ISTO EXISTE (bug real, reproduzido em 16/07/2026):

Os arquivos do pacote eram montados direto com o texto do usuário
(f"{artist} - {title}.ogg"). O Rust sanitizava a PASTA, mas mandava o
título cru pro sidecar - então bastava um caractere comum pra quebrar, de
três jeitos diferentes e todos ruins:

  - "AC/DC"        -> a barra virava separador de caminho e o .ogg escapava
                      pra outra pasta: o pacote saía sem áudio, sem erro.
  - "Quem?"        -> OSError [Errno 22] Invalid argument: a geração falhava.
  - "Song 2: Live" -> no NTFS o ":" abre um ALTERNATE DATA STREAM: o arquivo
                      visível ficava com 0 byte, o áudio ia parar num stream
                      oculto e NADA reclamava. O pior dos três.

Nenhum é exótico: "Quem?" é título trivial em português e AC/DC existe.

A TABELA vem do usdb_syncer (utils.py, FILENAME_REPLACEMENTS), que é a
ferramenta que baixa/nomeia os milhares de charts do USDB. Copiar a
convenção dele não é só evitar o crash - é fazer nossas pastas casarem com
as da comunidade ("AC-DC", não "AC_DC").

ATENÇÃO: isto é SÓ para nome de arquivo. O texto do usuário vai intacto pros
headers #TITLE/#ARTIST e pras buscas de metadado (sanitizar "AC/DC" numa
query do MusicBrainz quebraria a busca).
"""

from __future__ import annotations

# (caracteres, substituto) - mesma tabela do usdb_syncer.
# '?', ':' e '"' somem; '<' '>' viram parênteses; separadores e curinga viram
# hífen (que é o que a comunidade usa: "AC/DC" -> "AC-DC").
_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ('?:"', ""),
    ("<", "("),
    (">", ")"),
    ("/\\|*", "-"),
)


def sanitize_filename(name: str) -> str:
    """
    Devolve `name` utilizável como nome de arquivo/pasta no Windows.

    "AC/DC - T.N.T."  -> "AC-DC - T.N.T"
    "Rita Lee - Quem?" -> "Rita Lee - Quem"
    "Blur - Song 2: Live" -> "Blur - Song 2 Live"

    Precisa dar exatamente o mesmo resultado que `sanitize_path_component` no
    src-tauri/src/main.rs - o Rust cria a pasta e procura o .txt pelo nome, e
    o Python cria os arquivos dentro. Se as duas divergirem, o app gera o
    pacote e não acha o próprio arquivo.
    """
    for chars, replacement in _REPLACEMENTS:
        for char in chars:
            name = name.replace(char, replacement)

    # caracteres de controle não têm o que fazer num nome de arquivo
    name = "".join(c if ord(c) >= 0x20 else "_" for c in name)

    # o Windows não aceita espaço nem ponto no fim (e o Explorer os come
    # calado, o que faz o arquivo "sumir" de quem procura pelo nome exato)
    name = name.strip().rstrip(" .").strip()

    # sobrou nada? (título só de pontuação) - melhor um nome bobo que um
    # caminho vazio virando a própria pasta
    return name or "musica"

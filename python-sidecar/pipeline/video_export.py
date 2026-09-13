"""
video_export.py
Export opcional: gera um VÍDEO DE KARAOKÊ (.mp4) a partir do mesmo objeto Song
que alimenta o .txt do UltraStar.

POR QUE ISTO CABE AQUI (e por que é barato):
o trabalho difícil - saber QUAL sílaba é cantada em QUE instante - já está
pronto quando esta função roda. O Song já traz, por nota: start_beat,
duration_beats, o texto da sílaba e os phrase_breaks (fim de cada linha). Um
vídeo de karaokê não precisa de mais nada que isso. Então este módulo NÃO
mede nada, não chama IA e não abre o áudio: é tradução de dados.

O CAMINHO ESCOLHIDO (.ass + libass, não desenhar quadro a quadro):
o formato de legenda ASS tem tags de karaokê NATIVAS - "{\\kf<centésimos>}"
pinta a sílaba da esquerda para a direita ao longo da duração dada. É
exatamente o efeito de karaokê, e o libass (embutido no ffmpeg) já sabe
renderizar. Desenhar os quadros na mão (PIL/OpenCV) daria o mesmo resultado
gastando minutos de CPU por música e um monte de código de layout de texto.
As unidades do \\kf são CENTÉSIMOS DE SEGUNDO, que é a mesma precisão que a
gente já entrega (o erro do alinhador é de dezenas de ms - ver align.py), então
não se perde nada na conversão.

O ffmpeg que o app já baixa (gyan.dev "release-essentials", ver
scripts/setup-sidecar.ps1) vem com libass E libx264 - as duas peças
necessárias. Nenhuma dependência nova é instalada por causa deste módulo.

CONVERSÃO DE TEMPO: usa a fórmula OFICIAL do formato, a mesma do beatgrid.py:
    segundos = beat * 60 / (BPM * 4) + GAP/1000
O "* 4" é do motor do jogo e não pode ser aplicado duas vezes - ver a nota
longa em beatgrid.py, onde esse bug já mordeu uma vez.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .proc_utils import ffmpeg_exe, run_subprocess
from .ultrastar_writer import Note, Song

# ---------------------------------------------------------------------------
# Aparência. Valores em pixels de uma tela 1280x720 (PlayResX/Y do .ass).
# ---------------------------------------------------------------------------

VIDEO_W = 1280
VIDEO_H = 720
FPS = 30

# Fontes: "Arial" existe em toda instalação do Windows. NÃO usar uma fonte
# bonita que só existe na máquina de quem desenvolveu - o libass cairia num
# fallback silencioso e o vídeo sairia com outra fonte sem avisar ninguém.
FONT_NAME = "Arial"
FONT_SIZE_MAIN = 58
FONT_SIZE_NEXT = 40

# Cores no formato do ASS: &HAABBGGRR (alfa, AZUL, VERDE, VERMELHO - ordem
# invertida em relação ao HTML, e alfa 00 = opaco). Fácil de errar; por isso
# cada uma vem nomeada e comentada.
COLOR_SUNG = "&H0030C0FF"       # âmbar - sílaba JÁ cantada (PrimaryColour)
COLOR_UNSUNG = "&H00FFFFFF"     # branco - ainda não cantada (SecondaryColour)
COLOR_SUNG_P2 = "&H00FF9040"    # azul - segundo cantor no modo dueto
COLOR_OUTLINE = "&H00000000"    # contorno preto: legível sobre qualquer fundo

# Margem inferior (distância até a base da tela) de cada elemento. O
# alinhamento 2 do ASS ancora no rodapé, então MAIOR = mais para cima.
# Os três valores são espaçados para NÃO colidirem: a linha principal ocupa
# cerca de 65 px de altura a partir de MARGIN_V_MAIN, e a prévia cerca de 45 px
# a partir de MARGIN_V_NEXT. A contagem regressiva fica ACIMA da linha
# principal - ela aparece enquanto a linha já está na tela (é esse o ponto:
# "prepare-se, começa agora"), então precisa de faixa própria.
MARGIN_V_MAIN = 150
MARGIN_V_NEXT = 78
MARGIN_V_COUNTDOWN = MARGIN_V_MAIN + 95

# Quantos segundos antes a linha aparece, para dar tempo de ler.
LEAD_IN_S = 2.2
# Quanto tempo a linha fica depois de terminar (evita sumir no exato instante).
LINGER_S = 0.35

# Contagem regressiva: quando o intervalo ANTES de uma linha passa disto, entram
# três pontos que se acendem no ritmo, como no karaokê comercial. Abaixo disso
# a própria linha anterior ainda está na tela e os pontos só poluiriam.
COUNTDOWN_MIN_GAP_S = 4.0
COUNTDOWN_DOTS = 3
COUNTDOWN_DOT_S = 0.6

# Quebra de linha: mais que isto e a frase não cabe legível na largura da tela.
# Medido para Arial 58 em 1280 px com as margens abaixo.
MAX_CHARS_PER_LINE = 40
MARGIN_LR = 60


@dataclass
class Syllable:
    """Uma sílaba pronta para virar tag de karaokê: texto + janela de tempo."""
    text: str
    start_s: float
    end_s: float
    singer: int = 0


# ---------------------------------------------------------------------------
# Conversão Song -> sílabas -> .ass
# ---------------------------------------------------------------------------


def beat_to_seconds(beat: float, bpm: float, gap_ms: float) -> float:
    """Fórmula oficial do formato (idêntica à de beatgrid.py, invertida)."""
    if bpm <= 0:
        return 0.0
    return beat * 60.0 / (bpm * 4.0) + gap_ms / 1000.0


def ass_escape(text: str) -> str:
    """
    Neutraliza os caracteres que o ASS trata como marcação.

    "{" e "}" abrem/fecham um bloco de tags; uma letra que tenha "{" viraria
    comando e sumiria da tela. "\\" idem. Raro numa letra de música, mas o
    custo de proteger é uma linha e o modo de falha (texto some sem erro) é
    do tipo que ninguém descobre até alguém reclamar.
    """
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def ass_time(seconds: float) -> str:
    """Timestamp do ASS: H:MM:SS.cc (centésimos, não milésimos)."""
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def group_lines(song: Song) -> list[list[Note]]:
    """
    Fatia as notas em LINHAS de tela usando phrase_breaks_after_index - os
    mesmos marcadores "-" que o .txt usa para a rolagem do jogo. Reaproveitar
    isso (em vez de inventar uma regra de quebra própria) mantém o vídeo e o
    pacote UltraStar mostrando exatamente as mesmas frases.
    """
    breaks = set(song.phrase_breaks_after_index)
    lines: list[list[Note]] = []
    current: list[Note] = []
    for i, note in enumerate(song.notes):
        current.append(note)
        if i in breaks:
            lines.append(current)
            current = []
    if current:
        lines.append(current)
    return lines


def notes_to_syllables(notes: list[Note], bpm: float, gap_ms: float) -> list[Syllable]:
    """
    Converte as notas de UMA linha em sílabas exibíveis.

    As notas de continuação ("~") são FUNDIDAS na sílaba anterior em vez de
    virarem entrada própria. No UltraStar o "~" é um recurso de PITCH (a nota
    sustentada que muda de altura no meio da sílaba - ver detect_melisma_notes
    em build_song.py); na tela ele não é texto novo. Se fossem emitidas como
    sílabas, a palavra "star" cantada com melisma apareceria escrita
    "star~~~" - o que é certo no .txt e errado no vídeo.
    """
    syllables: list[Syllable] = []
    for note in notes:
        start = beat_to_seconds(note.start_beat, bpm, gap_ms)
        end = beat_to_seconds(note.start_beat + note.duration_beats, bpm, gap_ms)
        text = note.text

        is_continuation = text.strip() == "~"
        if is_continuation and syllables:
            # só estende a sílaba anterior: o preenchimento continua correndo
            syllables[-1].end_s = max(syllables[-1].end_s, end)

            # ...MAS o espaço de FIM DE PALAVRA tem que sobreviver.
            #
            # BUG REAL (relatado com print, 02/09/2026: "beenlonelysince",
            # "missyou", "Oh,and"): pela convenção do build_song.py, o espaço
            # que separa duas palavras é grudado na ÚLTIMA nota da palavra -
            # e essa última nota pode ser justamente uma continuação de
            # melisma, cujo texto vira "~ " (til MAIS espaço). Descartar a
            # nota inteira levava o espaço junto, e as duas palavras
            # apareciam coladas na tela.
            #
            # Confirmado nos dados reais do usuário: 'let' + '~ ' + 'the ' -
            # sem isto, sai "letthe". O til em si nunca é exibido (é notação
            # de pitch); o espaço ao lado dele é texto de verdade.
            if text.endswith((" ", "\t")) and not syllables[-1].text.endswith(" "):
                syllables[-1].text += " "
            continue
        if is_continuation:
            continue  # "~" órfão no começo da linha: nada a estender, descarta

        syllables.append(
            Syllable(text=text, start_s=start, end_s=end, singer=note.singer)
        )
    return syllables


def wrap_syllables(syllables: list[Syllable],
                   max_chars: int = MAX_CHARS_PER_LINE) -> list[int]:
    """
    Devolve os ÍNDICES de sílabas onde deve entrar uma quebra "\\N" antes.

    Quebra só em fronteira de PALAVRA (sílaba anterior terminando em espaço) -
    partir "co-ra-ção" no meio ficaria pior que a linha larga. Uma frase longa
    sem nenhum espaço (raro) simplesmente não é quebrada.
    """
    breaks: list[int] = []
    width = 0
    for i, syl in enumerate(syllables):
        if width + len(syl.text) > max_chars and i > 0 and syllables[i - 1].text.endswith(" "):
            breaks.append(i)
            width = 0
        width += len(syl.text)
    return breaks


def line_to_karaoke_text(syllables: list[Syllable],
                         lead_in_s: float = 0.0) -> str:
    """
    Monta o texto da linha com as tags de karaokê.

    `lead_in_s` é quanto tempo a linha fica na tela ANTES da primeira sílaba
    ser cantada (o tempo de leitura). Precisa entrar aqui como uma pausa
    explícita - ver o bloco abaixo, que é onde este módulo já errou feio.

    BUG REAL CORRIGIDO (relatado por usuário, 02/09/2026 - "letra ~3 segundos
    adiantada, constante na música inteira"):

    No ASS, as durações de karaokê são RELATIVAS AO INÍCIO DO EVENTO, não ao
    relógio da música. O primeiro "{\\kf}" começa a preencher no instante em
    que a linha APARECE. Como a linha aparece `lead_in_s` antes de ser
    cantada (pra dar tempo de ler), o preenchimento inteiro saía adiantado
    exatamente esse tanto - em toda linha, a música inteira, um deslocamento
    constante. O .txt do jogo estava certo o tempo todo; era só o vídeo.

    A correção é a idiomática do formato: um "{\\k<centésimos>}" SEM TEXTO na
    frente. Ele consome o tempo de leitura sem pintar nada, e só depois o
    preenchimento chega na primeira sílaba - no instante certo.

    Usa "\\k" (salto seco) e não "\\kf" (varredura) de propósito: não há texto
    pra varrer, e um "\\kf" vazio é só uma forma mais confusa de escrever a
    mesma espera.

    POR QUE OS TESTES NÃO PEGARAM: eles conferiam as durações das sílabas e o
    horário de início do evento SEPARADAMENTE, e os dois estavam certos. O que
    ninguém checava era a RELAÇÃO entre eles - que é onde o erro morava. Agora
    há um teste que reconstrói o horário ABSOLUTO em que cada sílaba acende e
    compara com o tempo real da nota (test_video_export_logic.py).

    A duração de cada sílaba vai até o COMEÇO da próxima, não até o próprio
    fim. Numa nota curta seguida de uma pausa, usar o próprio fim faria o
    preenchimento correr e depois PARAR, esperando parado no meio da palavra -
    fica visivelmente errado. Esticando até a próxima, o preenchimento é
    contínuo, que é o que o olho espera.
    """
    if not syllables:
        return ""

    wrap_at = set(wrap_syllables(syllables))
    parts: list[str] = []

    lead_in_cs = int(round(lead_in_s * 100))
    if lead_in_cs > 0:
        parts.append("{\\k%d}" % lead_in_cs)

    for i, syl in enumerate(syllables):
        stop = syllables[i + 1].start_s if i + 1 < len(syllables) else syl.end_s
        duration_cs = max(1, int(round((stop - syl.start_s) * 100)))
        if i in wrap_at:
            parts.append("\\N")
        # A sílaba que FECHA uma linha visual perde o espaço final. O texto é
        # centralizado: um espaço pendurado no fim conta na largura e empurra
        # a linha inteira para a esquerda do centro. Some da tela mas desloca.
        text = syl.text.rstrip() if (i + 1) in wrap_at else syl.text
        parts.append("{\\kf%d}%s" % (duration_cs, ass_escape(text)))
    return "".join(parts)


def _dialogue(start: float, end: float, style: str, text: str,
              margin_v: int) -> str:
    return (
        f"Dialogue: 0,{ass_time(start)},{ass_time(end)},{style},,"
        f"{MARGIN_LR},{MARGIN_LR},{margin_v},,{text}\n"
    )


# Caractere dos pontos da contagem. U+25CF (círculo cheio) existe na Arial do
# Windows, que é a fonte usada aqui - um caractere ausente viraria quadradinho
# na tela sem erro nenhum, então a escolha é conservadora de propósito.
COUNTDOWN_CHAR = "●"


def _countdown_text(dots: int = COUNTDOWN_DOTS) -> str:
    """Pontos que se acendem em sequência, usando a mesma tag de karaokê."""
    return "".join(
        "{\\kf%d}%s " % (int(COUNTDOWN_DOT_S * 100), COUNTDOWN_CHAR)
        for _ in range(dots)
    )


def _styles_block(duet: bool) -> str:
    fmt = ("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
           "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
           "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
           "Alignment, MarginL, MarginR, MarginV, Encoding\n")

    def style(name: str, size: int, primary: str, secondary: str) -> str:
        # BorderStyle 1 + Outline 4 + Shadow 2: contorno grosso e sombra. É o
        # que mantém a letra legível por cima de um clipe claro - sem isso, uma
        # cena de céu branco engole texto branco.
        return (
            f"Style: {name},{FONT_NAME},{size},{primary},{secondary},"
            f"{COLOR_OUTLINE},&H64000000,-1,0,0,0,100,100,0,0,1,4,2,2,"
            f"{MARGIN_LR},{MARGIN_LR},{MARGIN_V_MAIN},1\n"
        )

    out = fmt
    out += style("Main", FONT_SIZE_MAIN, COLOR_SUNG, COLOR_UNSUNG)
    # A linha "próxima" é só uma prévia: cinza, sem karaokê rolando nela.
    out += style("Next", FONT_SIZE_NEXT, "&H00B0B0B0", "&H00B0B0B0")
    if duet:
        out += style("MainP2", FONT_SIZE_MAIN, COLOR_SUNG_P2, COLOR_UNSUNG)
    return out


def build_ass(song: Song, lead_in_s: float = LEAD_IN_S) -> str:
    """
    Song -> conteúdo completo de um arquivo .ass.

    Função PURA (string entra, string sai): não toca disco, não chama ffmpeg.
    É o que permite testar o timing sem renderizar vídeo nenhum - ver
    tests/test_video_export_logic.py.
    """
    lines_of_notes = group_lines(song)
    lines: list[list[Syllable]] = []
    for notes in lines_of_notes:
        syls = notes_to_syllables(notes, song.bpm, song.gap_ms)
        if syls:
            lines.append(syls)

    header = (
        "[Script Info]\n"
        f"Title: {song.artist} - {song.title}\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {VIDEO_W}\n"
        f"PlayResY: {VIDEO_H}\n"
        # WrapStyle 2 = só quebra onde EU pedi (\\N). Sem isto o libass também
        # quebra sozinho onde achar melhor, e a conta de largura feita em
        # wrap_syllables passa a competir com a dele.
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n"
        "YCbCr Matrix: TV.709\n"
        "\n[V4+ Styles]\n"
        + _styles_block(song.duet)
        + "\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text\n"
    )

    events: list[str] = []
    for idx, syls in enumerate(lines):
        line_start = syls[0].start_s
        line_end = max(s.end_s for s in syls)
        prev_end = max(s.end_s for s in lines[idx - 1]) if idx else 0.0

        # Não deixa a linha nova aparecer por cima da anterior ainda na tela.
        appear = max(prev_end + 0.05, line_start - lead_in_s)
        appear = min(appear, line_start)
        disappear = line_end + LINGER_S

        style = "MainP2" if (song.duet and syls[0].singer == 2) else "Main"
        # O tempo REAL de leitura é medido do aparecimento até a 1ª sílaba -
        # não é o lead_in_s nominal, porque `appear` pode ter sido empurrado
        # pra frente pelo fim da linha anterior. Passar o nominal aqui
        # reintroduziria o mesmo deslocamento, só que menor.
        events.append(
            _dialogue(appear, disappear, style,
                      line_to_karaoke_text(syls, line_start - appear),
                      MARGIN_V_MAIN)
        )

        # Prévia da PRÓXIMA linha, embaixo e apagada, enquanto esta é cantada.
        if idx + 1 < len(lines):
            nxt = lines[idx + 1]
            preview = ass_escape("".join(s.text for s in nxt).strip())
            if preview:
                events.append(
                    _dialogue(appear, min(disappear, nxt[0].start_s),
                              "Next", preview, MARGIN_V_NEXT)
                )

        # Contagem regressiva nos intervalos longos (intro, solo, ponte).
        gap = line_start - prev_end
        if gap > COUNTDOWN_MIN_GAP_S:
            cd_len = COUNTDOWN_DOTS * COUNTDOWN_DOT_S
            events.append(
                _dialogue(line_start - cd_len, line_start, "Next",
                          _countdown_text(), MARGIN_V_COUNTDOWN)
            )

    return header + "".join(events)


# ---------------------------------------------------------------------------
# Renderização
# ---------------------------------------------------------------------------


def _background_input_args(background: Path | None) -> tuple[list[str], str]:
    """
    Args de entrada do ffmpeg + o filtro que transforma o fundo em 1280x720.

    Três casos, do melhor para o mais simples:
      - VÍDEO: repete em loop se for mais curto que a música (-stream_loop -1);
      - IMAGEM (capa/background do pacote): vira um fundo estático;
      - NADA: cor sólida escura.
    Em vídeo e imagem entra um escurecimento (eq brightness) - fundo cheio de
    detalhe compete com a letra, e legibilidade ganha de bonito num karaokê.
    """
    video_exts = {".mp4", ".webm", ".mkv", ".mov", ".avi"}
    image_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

    # scale + crop = "cobrir" mantendo proporção (sem barras pretas, sem
    # esticar). force_original_aspect_ratio=increase preenche e o crop apara.
    cover = (
        f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=increase,"
        f"crop={VIDEO_W}:{VIDEO_H},setsar=1"
    )

    if background and background.exists():
        ext = background.suffix.lower()
        if ext in video_exts:
            return (
                ["-stream_loop", "-1", "-i", str(background)],
                f"[0:v]{cover},eq=brightness=-0.18:saturation=0.9,fps={FPS}[bg]",
            )
        if ext in image_exts:
            return (
                ["-loop", "1", "-framerate", str(FPS), "-i", str(background)],
                f"[0:v]{cover},eq=brightness=-0.12[bg]",
            )

    return (
        ["-f", "lavfi", "-i",
         f"color=c=0x0D1220:s={VIDEO_W}x{VIDEO_H}:r={FPS}"],
        "[0:v]null[bg]",
    )


def render_mp4(song: Song, audio_path: Path, dest_mp4: Path,
               background: Path | None = None,
               ass_path: Path | None = None) -> Path:
    """
    Gera o .mp4 final. Devolve o caminho do vídeo.

    O .ass é escrito com um nome FIXO e sem espaços (_karaoke_subs.ass) e o
    ffmpeg roda com cwd na pasta de saída, passando só o nome do arquivo para
    o filtro. Motivo prático: o filtro "subtitles=" recebe o caminho DENTRO da
    string de filtros, onde ":" e "\\" são separadores - um caminho do Windows
    tipo "C:\\Users\\..." precisa de escape duplo e é fonte clássica de erro. Um
    nome relativo e simples evita o problema inteiro em vez de escapá-lo.
    O arquivo fica na pasta de propósito: quem quiser mexer no visual edita o
    .ass e re-renderiza sem rodar a IA de novo.
    """
    out_dir = dest_mp4.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    ass_path = ass_path or (out_dir / "_karaoke_subs.ass")
    ass_path.write_text(build_ass(song), encoding="utf-8")

    bg_args, bg_filter = _background_input_args(background)
    filter_complex = f"{bg_filter};[bg]subtitles={ass_path.name}[v]"

    cmd = [ffmpeg_exe(), "-y"]
    cmd += bg_args
    cmd += ["-i", str(audio_path)]
    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "veryfast", "-crf", "22",
        # AAC é o áudio que todo aparelho de TV/telefone toca sem discutir.
        "-c:a", "aac", "-b:a", "192k",
        # -shortest: o fundo em loop/imagem é infinito; quem manda na duração
        # é a música.
        "-shortest",
        "-movflags", "+faststart",
        str(dest_mp4),
    ]
    run_subprocess(cmd, cwd=str(out_dir))
    return dest_mp4


def export_karaoke_video(song: Song, out_dir: Path, file_base: str,
                         audio_path: Path,
                         video_path: Path | None = None,
                         background_path: Path | None = None,
                         cover_path: Path | None = None) -> Path:
    """
    Ponto de entrada usado pela pipeline.

    Escolhe o melhor fundo disponível (clipe > arte de fundo > capa > cor
    sólida) e renderiza "<Artista> - <Título> (Karaoke).mp4" na pasta do
    pacote. Não decide NADA sobre o áudio: recebe pronto o mesmo arquivo que
    foi para o pacote, então as opções que o usuário já escolheu (backtrack =
    instrumental, transposição de tom) valem no vídeo automaticamente.
    """
    background = next(
        (p for p in (video_path, background_path, cover_path) if p and p.exists()),
        None,
    )
    dest = out_dir / f"{file_base} (Karaoke).mp4"
    return render_mp4(song, audio_path, dest, background=background)


def ffmpeg_has_libass() -> bool:
    """
    Confere se o ffmpeg disponível sabe renderizar legendas.

    Verificação BARATA e feita ANTES de renderizar: um ffmpeg sem libass não
    falha ao iniciar - ele falha ao montar o filtro, depois de já ter aceitado
    tudo, com uma mensagem que não diz "faltou libass". Melhor avisar direito.

    Usa subprocess.run CRU de propósito, e não o run_subprocess do módulo: este
    último ECOA toda a saída no log, e `ffmpeg -filters` despeja centenas de
    linhas que não interessam a ninguém. É uma sonda, não um passo da pipeline.
    """
    try:
        result = subprocess.run(
            [ffmpeg_exe(), "-hide_banner", "-filters"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False,
        )
        return "subtitles" in (result.stdout or "")
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Re-renderização avulsa (sem IA)
# ---------------------------------------------------------------------------

# Mensagens deste caminho AVULSO em dois idiomas.
#
# O log da pipeline é todo em português e continua assim - ele é lido dentro do
# app, que já é bilíngue e enquadra tudo. Este caminho é diferente: o usuário
# roda no terminal, SOZINHO, e a mensagem é a única coisa que ele vê. Um
# usuário de língua inglesa travou exatamente aqui num uso real (02/09/2026),
# olhando para um prompt em português sem saber o que responder.
_MSG = {
    "no_json": {
        "pt": ("Não achei o song_data.json em {dir}. Sem ele não dá para refazer "
               "o vídeo - ele guarda os tempos das sílabas. (A opção 'manter "
               "apenas o essencial' apaga esse arquivo.)"),
        "en": ("No song_data.json in {dir}. The video cannot be rebuilt without "
               "it - it holds the syllable timings. (The 'keep only the "
               "essentials' option deletes this file.)"),
    },
    "no_audio": {
        "pt": "O áudio do pacote não está em {path}. O vídeo precisa dele.",
        "en": "The package audio is missing at {path}. The video needs it.",
    },
    "no_libass": {
        "pt": ("O ffmpeg encontrado não tem suporte a legendas (libass). Rode o "
               "setup do ambiente de IA do USKMaker para baixar o ffmpeg completo."),
        "en": ("The ffmpeg found has no subtitle support (libass). Run USKMaker's "
               "'Set up AI environment' to download the full ffmpeg."),
    },
    "done": {
        "pt": "[OK] Vídeo refeito: {path}",
        "en": "[OK] Video rebuilt: {path}",
    },
    "cli_help": {
        "pt": ("Refaz o vídeo de karaokê (.mp4) de um pacote já gerado, usando os "
               "tempos atuais do song_data.json. Não roda IA."),
        "en": ("Rebuild the karaoke video (.mp4) of an existing package from the "
               "current song_data.json timings. Does not run the AI."),
    },
    "cli_dir": {
        "pt": "Pasta da música (a que tem o song_data.json)",
        "en": "Song folder (the one containing song_data.json)",
    },
}


def _lang() -> str:
    """
    "pt" ou "en". USKMAKER_LANG manda (o app pode passar a escolha do usuário,
    e os testes fixam o idioma); senão vale o locale do sistema. Default "en" -
    quem não configurou nada tem mais chance de ler inglês que português.
    """
    import locale
    import os

    forced = os.environ.get("USKMAKER_LANG", "").strip().lower()
    if forced.startswith("pt"):
        return "pt"
    if forced.startswith("en"):
        return "en"
    try:
        loc = (locale.getlocale()[0] or "") + " " + (locale.getdefaultlocale()[0] or "")
    except Exception:
        loc = ""
    return "pt" if "pt" in loc.lower()[:3] or loc.lower().startswith("pt") else "en"


def msg(key: str, **kw) -> str:
    """Texto de `key` no idioma corrente, já formatado."""
    return _MSG[key][_lang()].format(**kw)



def rerender_from_folder(song_dir: Path) -> Path:
    """
    Refaz o vídeo de karaokê a partir de uma pasta de pacote JÁ PRONTA.

    POR QUE ISTO EXISTE: a tela de Revisão de Alinhamento salva o
    song_data.json corrigido e reescreve o .txt - e só. O .mp4 continua com
    os tempos ANTIGOS, sem nada avisando. Antes disto, aplicar um ajuste de
    meio segundo na revisão exigia reprocessar a música inteira: minutos de
    Demucs e WhisperX para refazer um passo que não depende de IA nenhuma.

    Tudo o que o vídeo precisa já está na pasta depois de uma geração: os
    tempos corrigidos (song_data.json), o áudio do pacote e o fundo. Então
    aqui é só ler e renderizar - segundos de trabalho, não minutos.

    Descobre os arquivos pelo PRÓPRIO song_data.json (mp3_filename,
    video_filename, background_filename, cover_filename), que é a mesma fonte
    que o .txt usa. Assim as opções já escolhidas na geração (backtrack,
    transposição, formato do áudio) continuam valendo sem precisar repeti-las.
    """
    import json

    from .filenames import sanitize_filename

    song_dir = Path(song_dir)
    json_path = song_dir / "song_data.json"
    if not json_path.exists():
        raise FileNotFoundError(msg("no_json", dir=song_dir))

    data = json.loads(json_path.read_text(encoding="utf-8"))
    song = Song(**{**data, "notes": [Note(**n) for n in data["notes"]]})

    audio_path = song_dir / song.mp3_filename
    if not audio_path.exists():
        raise FileNotFoundError(msg("no_audio", path=audio_path))

    def _opt(name: str | None) -> Path | None:
        return (song_dir / name) if name else None

    file_base = sanitize_filename(f"{song.artist} - {song.title}")
    if song.duet:
        file_base = f"{file_base} [DUET]"

    return export_karaoke_video(
        song, song_dir, file_base,
        audio_path=audio_path,
        video_path=_opt(song.video_filename),
        background_path=_opt(song.background_filename),
        cover_path=_opt(song.cover_filename),
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=msg("cli_help"))
    parser.add_argument("--dir", required=True, help=msg("cli_dir"))
    args = parser.parse_args()

    if not ffmpeg_has_libass():
        raise SystemExit(msg("no_libass"))

    destino = rerender_from_folder(Path(args.dir))
    print(msg("done", path=destino))

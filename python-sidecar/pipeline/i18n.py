# -*- coding: utf-8 -*-
"""
i18n.py - mensagens do LOG da pipeline no idioma da interface (pt/en).

POR QUE ISTO EXISTE (29/09/2026): a interface do app é bilíngue (PT-BR/EN,
o usuário escolhe - ver src/i18n.tsx e o tr() do src-tauri/src/main.rs), mas o
log que o app transmite no painel era todo em português fixo ("Etapa 3/6 -
Detectando BPM", "AVISO ..."). Quem escolheu inglês via a tela em inglês e o
log - justamente onde aparecem os avisos que pedem ação - em português.

COMO FUNCIONA
  - Um idioma CORRENTE por processo (set_ui_lang). O sidecar persistente
    (server.py) define o idioma a CADA job (chave "ui_lang"), porque o usuário
    pode trocar o idioma da interface entre uma música e outra da fila sem o
    servidor reiniciar. O modo avulso (python main.py) usa --ui-lang.
  - Default "pt": sem ninguém pedir nada, o log sai IGUAL ao de antes, byte a
    byte. Isso cobre quem usa pela CLI e - importante - o app já instalado com
    um executável mais antigo, que não manda "ui_lang" no job (os .py do
    sidecar são arquivos soltos e podem ser atualizados sem recompilar o app;
    ver a nota em server.py/_mp4_export_fallback).
  - t(chave, **campos) devolve o texto já formatado. Idioma desconhecido cai
    no pt; chave que falta no idioma cai no pt, e chave que não existe devolve
    a própria chave. Uma mensagem de log NUNCA pode derrubar a pipeline.

REGRAS DA TABELA (conferidas por tests/test_i18n_logic.py)
  - Toda chave tem "pt" e "en", com o MESMO conjunto de {campos}.
  - Marcação do rich ([green]OK[/green], [yellow]AVISO[/yellow]...) idêntica
    nos dois idiomas - só a palavra muda, a cor e a estrutura não.
  - O texto "pt" é exatamente o que a pipeline imprimia antes desta mudança.
  - "Etapa N/6" / "Step N/6": a interface lê esse padrão para acender o
    passo corrente (regex no src/App.tsx, que aceita as duas palavras). Mudar
    o formato dessas linhas exige mudar a regex junto.

O QUE FICA DE FORA DE PROPÓSITO
  - debug_log(...) do main.py: o pipeline_debug.log é para quem mantém o
    projeto (lê português) - traduzir só atrapalharia comparar logs antigos.
  - Saída de terceiros (yt-dlp, Demucs, WhisperX, ffmpeg): não é nossa. Em
    especial, o Rust procura "Extracting URL:" do yt-dlp no log (read_source_url).
  - Saídas em JSON lidas por outro componente (fetch_assets.py, read_tags.py,
    read_video_info.py, update_ytdlp.py) e os blocos __main__ de teste manual
    de cada módulo.
  - pipeline/video_export.py tem a sua própria tabela (_MSG, via
    USKMAKER_LANG), anterior a esta e com outra regra de default (locale da
    máquina) - porque o caminho avulso dele roda no terminal, fora do app.
"""
from __future__ import annotations

SUPPORTED_LANGS = ("pt", "en")
DEFAULT_LANG = "pt"

_current_lang = DEFAULT_LANG


def normalize_lang(lang: str | None) -> str:
    """'pt', 'pt-BR', 'EN', 'en_US'... -> 'pt' ou 'en'. Qualquer outra coisa -> 'pt'."""
    code = (lang or "").strip().lower()
    for supported in SUPPORTED_LANGS:
        if code.startswith(supported):
            return supported
    return DEFAULT_LANG


def set_ui_lang(lang: str | None) -> str:
    """Define o idioma do log para o processo inteiro. Devolve o valor efetivo."""
    global _current_lang
    _current_lang = normalize_lang(lang)
    return _current_lang


def get_ui_lang() -> str:
    return _current_lang


def t(key: str, **kw) -> str:
    """
    Texto de `key` no idioma corrente, já formatado com `kw`.

    Tolerante de propósito: é chamado no meio da pipeline, muitas vezes dentro
    de um `except` que já está tratando outro erro - se a mensagem estourasse
    ali, o usuário perderia a geração por causa de um texto de log.
    """
    entry = MESSAGES.get(key)
    if entry is None:
        return key
    template = entry.get(_current_lang) or entry.get(DEFAULT_LANG) or key
    try:
        return template.format(**kw)
    except (KeyError, IndexError, ValueError):
        # campo faltando/formato inválido no idioma corrente: tenta o pt, e
        # em último caso mostra o molde cru (feio, mas não derruba nada)
        try:
            return entry.get(DEFAULT_LANG, template).format(**kw)
        except (KeyError, IndexError, ValueError):
            return template


# ---------------------------------------------------------------------------
# Tabela de mensagens. Prefixo = módulo que imprime ("main." = main.py etc.).
# ---------------------------------------------------------------------------
MESSAGES: dict[str, dict[str, str]] = {
    # ------------------------------------------------------------ main.py
    "main.gpu_too_old": {
        "pt": ("[AVISO] GPU detectada (capacidade sm_{cap}) mas o torch instalado só "
               "suporta a partir de sm_{min_arch} (kernels disponíveis: {archs}) - "
               "caindo para CPU (mais lento, mas funciona)."),
        "en": ("[WARNING] GPU detected (capability sm_{cap}) but the installed torch only "
               "supports sm_{min_arch} and newer (available kernels: {archs}) - "
               "falling back to CPU (slower, but it works)."),
    },
    "main.duet_no_tags": {
        "pt": ("[yellow]AVISO[/yellow] Modo dueto marcado, mas a letra não tem nenhuma tag "
               "[bold]P1:[/bold]/[bold]P2:[/bold]. Marque o início de cada parte (ex.: "
               "\"P1: ...\", \"P2: ...\", \"P1&P2: ...\"). Sem tags, o pacote sai com um "
               "cantor só."),
        "en": ("[yellow]WARNING[/yellow] Duet mode is on, but the lyrics have no "
               "[bold]P1:[/bold]/[bold]P2:[/bold] tags. Mark where each part starts (e.g. "
               "\"P1: ...\", \"P2: ...\", \"P1&P2: ...\"). Without tags, the package comes "
               "out with a single singer."),
    },
    "main.tags_no_duet": {
        "pt": ("[yellow]AVISO[/yellow] A letra traz tags P1:/P2:, mas a caixa de dueto está "
               "desmarcada. As tags serão removidas e o pacote sai como solo. Marque "
               "\"Dueto\" para gerar as duas vozes."),
        "en": ("[yellow]WARNING[/yellow] The lyrics have P1:/P2: tags, but the duet box is "
               "unchecked. The tags will be removed and the package comes out as a solo. "
               "Check \"Duet\" to generate both voices."),
    },
    "main.no_cuda": {
        "pt": ("[yellow]AVISO[/yellow] GPU NVIDIA/CUDA não disponível — o processamento vai "
               "rodar na CPU (funciona, mas é bem mais lento)."),
        "en": ("[yellow]WARNING[/yellow] NVIDIA/CUDA GPU not available — processing will "
               "run on the CPU (it works, but it is much slower)."),
    },
    # As 6 réguas de etapa: a interface acende o passo lendo "Etapa N/" ou
    # "Step N/" (src/App.tsx). Manter "<palavra> N/6" no começo.
    "main.step1": {
        "pt": "[bold cyan]Etapa 1/6 — Obtendo áudio fonte",
        "en": "[bold cyan]Step 1/6 — Getting the source audio",
    },
    "main.step2": {
        "pt": "[bold cyan]Etapa 2/6 — Separando vocal/instrumental (Demucs)",
        "en": "[bold cyan]Step 2/6 — Separating vocals/instrumental (Demucs)",
    },
    "main.step3": {
        "pt": "[bold cyan]Etapa 3/6 — Detectando BPM",
        "en": "[bold cyan]Step 3/6 — Detecting BPM",
    },
    "main.step4": {
        "pt": "[bold cyan]Etapa 4/6 — Alinhando letra ao áudio",
        "en": "[bold cyan]Step 4/6 — Aligning lyrics to audio",
    },
    "main.step5": {
        "pt": "[bold cyan]Etapa 5/6 — Buscando metadados (capa, ano, gênero)",
        "en": "[bold cyan]Step 5/6 — Fetching metadata (cover, year, genre)",
    },
    "main.step6": {
        "pt": "[bold cyan]Etapa 6/6 — Extraindo pitch e montando o .txt",
        "en": "[bold cyan]Step 6/6 — Extracting pitch and building the .txt",
    },
    "main.audio_at": {
        "pt": "[green]OK[/green] Áudio em: {path}",
        "en": "[green]OK[/green] Audio at: {path}",
    },
    "main.video_downloaded": {
        "pt": "[green]OK[/green] Vídeo baixado: {path}",
        "en": "[green]OK[/green] Video downloaded: {path}",
    },
    "main.bgvideo_downloading": {
        "pt": "[cyan]—[/cyan] Baixando videoclipe de fundo ({query})...",
        "en": "[cyan]—[/cyan] Downloading background music video ({query})...",
    },
    "main.bgvideo_ok": {
        "pt": "[green]OK[/green] Videoclipe de fundo: {path}",
        "en": "[green]OK[/green] Background music video: {path}",
    },
    "main.bgvideo_fail": {
        "pt": ("[yellow]AVISO[/yellow] Não consegui baixar um videoclipe de fundo - o pacote "
               "seguirá apenas com a imagem de capa."),
        "en": ("[yellow]WARNING[/yellow] Could not download a background music video - the "
               "package will use only the cover image."),
    },
    "main.vocal_ok": {
        "pt": "[green]OK[/green] Vocal: {path}",
        "en": "[green]OK[/green] Vocals: {path}",
    },
    "main.instrumental_ok": {
        "pt": "[green]OK[/green] Instrumental: {path}",
        "en": "[green]OK[/green] Instrumental: {path}",
    },
    "main.bpm_ok": {
        "pt": "[green]OK[/green] BPM: {bpm:.2f} (este valor BRUTO vai direto para #BPM no .txt)",
        "en": "[green]OK[/green] BPM: {bpm:.2f} (this RAW value goes straight into #BPM in the .txt)",
    },
    "main.bpm_auto_warn": {
        "pt": "[yellow]AVISO[/yellow] BPM detectado automaticamente - confira antes de confiar 100%.",
        "en": "[yellow]WARNING[/yellow] BPM detected automatically - check it before trusting it 100%.",
    },
    "main.whisper_model": {
        "pt": "[cyan]Modelo de reconhecimento:[/cyan] {model}",
        "en": "[cyan]Recognition model:[/cyan] {model}",
    },
    "main.whisper_on_cpu": {
        "pt": "[cyan]Transcrição (Whisper) na CPU; separação e alinhamento na GPU.[/cyan]",
        "en": "[cyan]Transcription (Whisper) on the CPU; separation and alignment on the GPU.[/cyan]",
    },
    "main.rescue4b_skip_duet": {
        "pt": ("[dim]{pct:.0f}% interpoladas, mas em modo dueto o resgate por voz principal "
               "isolada é pulado (descartaria o 2º cantor).[/dim]"),
        "en": ("[dim]{pct:.0f}% interpolated, but in duet mode the isolated-lead-vocal rescue "
               "is skipped (it would discard the 2nd singer).[/dim]"),
    },
    "main.rescue4b_try": {
        "pt": ("[yellow]—[/yellow] {pct:.0f}% das palavras interpoladas - tentando resgate com "
               "a voz principal isolada do coro/apoio..."),
        "en": ("[yellow]—[/yellow] {pct:.0f}% of the words interpolated - trying a rescue with "
               "the lead vocal isolated from the choir/backing vocals..."),
    },
    "main.rescue4b_ok": {
        "pt": ("[green]OK[/green] Resgate melhorou: {before} -> {after} palavras interpoladas "
               "(usando voz principal isolada)."),
        "en": ("[green]OK[/green] Rescue improved it: {before} -> {after} interpolated words "
               "(using the isolated lead vocal)."),
    },
    "main.rescue4b_no": {
        "pt": ("[dim]Resgate não melhorou ({before} -> {after} interpoladas) - mantendo o "
               "alinhamento no stem combinado.[/dim]"),
        "en": ("[dim]Rescue did not improve it ({before} -> {after} interpolated) - keeping "
               "the alignment on the combined stem.[/dim]"),
    },
    "main.rescue4b_fail": {
        "pt": ("[yellow]AVISO[/yellow] Não consegui isolar a voz principal ({err}) - mantendo "
               "o alinhamento no stem combinado do Demucs."),
        "en": ("[yellow]WARNING[/yellow] Could not isolate the lead vocal ({err}) - keeping "
               "the alignment on Demucs's combined stem."),
    },
    "main.rescue4d_try": {
        "pt": ("[yellow]—[/yellow] Ainda {pct:.0f}% interpoladas - tentando resgate com "
               "detecção de voz mais sensível..."),
        "en": ("[yellow]—[/yellow] Still {pct:.0f}% interpolated - trying a rescue with more "
               "sensitive voice detection..."),
    },
    "main.rescue4d_ok": {
        "pt": ("[green]OK[/green] Resgate melhorou: {before} -> {after} palavras interpoladas "
               "(detecção de voz mais sensível)."),
        "en": ("[green]OK[/green] Rescue improved it: {before} -> {after} interpolated words "
               "(more sensitive voice detection)."),
    },
    "main.rescue4d_no": {
        "pt": ("[dim]Resgate não melhorou ({before} -> {after} interpoladas) - mantendo o "
               "alinhamento anterior.[/dim]"),
        "en": ("[dim]Rescue did not improve it ({before} -> {after} interpolated) - keeping "
               "the previous alignment.[/dim]"),
    },
    "main.rescue4d_fail": {
        "pt": ("[yellow]AVISO[/yellow] Não consegui tentar o resgate com VAD sensível ({err}) - "
               "mantendo o alinhamento que já temos."),
        "en": ("[yellow]WARNING[/yellow] Could not try the sensitive-VAD rescue ({err}) - "
               "keeping the alignment we already have."),
    },
    "main.rescue4c_try": {
        "pt": ("[yellow]—[/yellow] {pct:.0f}% das palavras interpoladas: o alinhamento "
               "desabou. Separando o vocal de novo (a separação varia a cada tentativa) e "
               "realinhando..."),
        "en": ("[yellow]—[/yellow] {pct:.0f}% of the words interpolated: the alignment "
               "collapsed. Separating the vocals again (the separation varies on every "
               "attempt) and realigning..."),
    },
    "main.rescue4c_ok": {
        "pt": "[green]OK[/green] A 2ª separação salvou: {before} -> {after} palavras interpoladas.",
        "en": "[green]OK[/green] The 2nd separation saved it: {before} -> {after} interpolated words.",
    },
    "main.rescue4c_no": {
        "pt": ("[dim]A 2ª separação não melhorou ({before} -> {after} interpoladas) - "
               "mantendo a primeira.[/dim]"),
        "en": ("[dim]The 2nd separation did not improve it ({before} -> {after} interpolated) - "
               "keeping the first one.[/dim]"),
    },
    "main.rescue4c_fail": {
        "pt": ("[yellow]AVISO[/yellow] Não consegui separar o vocal de novo ({err}) - "
               "mantendo o alinhamento que já temos."),
        "en": ("[yellow]WARNING[/yellow] Could not separate the vocals again ({err}) - "
               "keeping the alignment we already have."),
    },
    "main.aligner_ctc": {
        "pt": "[cyan]Alinhando a letra inteira de uma vez contra o áudio (CTC)...[/cyan]",
        "en": "[cyan]Aligning the whole lyrics at once against the audio (CTC)...[/cyan]",
    },
    "main.ctc_unsupported": {
        "pt": ("[dim]A letra usa um alfabeto que o alinhador CTC não conhece - usando o "
               "alinhamento pelo Whisper.[/dim]"),
        "en": ("[dim]The lyrics use an alphabet the CTC aligner does not know - using the "
               "Whisper alignment.[/dim]"),
    },
    "main.ctc_failed": {
        "pt": ("[yellow]AVISO[/yellow] O alinhamento CTC falhou ({err}) - usando o "
               "alinhamento pelo Whisper."),
        "en": ("[yellow]WARNING[/yellow] The CTC alignment failed ({err}) - using the "
               "Whisper alignment."),
    },
    "main.ctc_rescue4b_try": {
        "pt": ("[yellow]—[/yellow] {pct:.0f}% das palavras em linhas de confiança baixa - "
               "tentando resgate com a voz principal isolada do coro/apoio..."),
        "en": ("[yellow]—[/yellow] {pct:.0f}% of the words in low-confidence lines - "
               "trying a rescue with the lead vocal isolated from the choir/backing vocals..."),
    },
    "main.ctc_fallback": {
        "pt": ("[yellow]—[/yellow] {pct:.0f}% das palavras em linhas de confiança baixa - "
               "nesse caso o alinhamento pelo Whisper costuma ser melhor; usando ele."),
        "en": ("[yellow]—[/yellow] {pct:.0f}% of the words in low-confidence lines - "
               "the Whisper alignment is usually better in that case; using it."),
    },
    "main.ctc_rescue_ok": {
        "pt": ("[green]OK[/green] Resgate melhorou: {before:.0f}% -> {after:.0f}% das palavras "
               "em linhas de confiança baixa."),
        "en": ("[green]OK[/green] Rescue improved it: {before:.0f}% -> {after:.0f}% of the words "
               "in low-confidence lines."),
    },
    "main.ctc_rescue_no": {
        "pt": ("[dim]Resgate não melhorou ({before:.0f}% -> {after:.0f}% em linhas de confiança "
               "baixa) - mantendo o alinhamento anterior.[/dim]"),
        "en": ("[dim]Rescue did not improve it ({before:.0f}% -> {after:.0f}% in low-confidence "
               "lines) - keeping the previous alignment.[/dim]"),
    },
    "main.ctc_breakdown": {
        "pt": ("    [dim]{ctc} medidas / {low} em linhas de confiança baixa / {interp} sem "
               "letra alinhável (estimadas)[/dim]"),
        "en": ("    [dim]{ctc} measured / {low} in low-confidence lines / {interp} with no "
               "alignable letters (estimated)[/dim]"),
    },
    "main.ctc_low_warn": {
        "pt": ("[yellow]AVISO[/yellow] {pct:.1f}% das palavras estão em linhas de confiança "
               "baixa - vale conferir as linhas marcadas em vermelho na revisão."),
        "en": ("[yellow]WARNING[/yellow] {pct:.1f}% of the words are in low-confidence lines - "
               "worth checking the lines marked in red in the review."),
    },
    "main.words_done": {
        "pt": "[green]OK[/green] {n} palavras processadas.",
        "en": "[green]OK[/green] {n} words processed.",
    },
    "main.words_breakdown": {
        "pt": ("    [dim]{anchor} âncora exata / {fuzzy} fuzzy / {realign} realinhadas no 2º "
               "passe / {lrc} início de linha (.lrc) / {interp} interpoladas (estimadas)[/dim]"),
        "en": ("    [dim]{anchor} exact anchor / {fuzzy} fuzzy / {realign} realigned in the 2nd "
               "pass / {lrc} line start (.lrc) / {interp} interpolated (estimated)[/dim]"),
    },
    "main.interp_warn": {
        "pt": ("[yellow]AVISO[/yellow] {pct:.1f}% das palavras ficaram interpoladas (não foi "
               "possível medi-las no áudio, nem no 2º passe) - maiores sequências seguidas: "
               "{runs}."),
        "en": ("[yellow]WARNING[/yellow] {pct:.1f}% of the words ended up interpolated (they "
               "could not be measured in the audio, not even in the 2nd pass) - longest "
               "consecutive runs: {runs}."),
    },
    "main.align_failed": {
        "pt": ("[bold red]ATENÇÃO[/bold red] A MAIORIA das palavras ({pct:.0f}%) é estimativa "
               "- o alinhamento não conseguiu reconhecer o canto nesta música. O pacote "
               "provavelmente sai fora de sincronia."),
        "en": ("[bold red]ATTENTION[/bold red] MOST of the words ({pct:.0f}%) are estimates "
               "- the alignment could not recognize the singing in this song. The package "
               "will probably be out of sync."),
    },
    "main.align_failed_hint": {
        "pt": ("    [yellow]VALE GERAR ESTA MÚSICA DE NOVO: a separação de voz do Demucs varia a "
               "cada tentativa (mesma entrada, saída diferente - verificado por hash), e uma "
               "separação ruim derruba o alinhamento inteiro. Normalmente a 2ª tentativa "
               "funciona. Se repetir, confira se a letra bate com ESTA gravação (versão ao "
               "vivo, remix e refrão escrito uma vez só atrapalham).[/yellow]"),
        "en": ("    [yellow]IT IS WORTH GENERATING THIS SONG AGAIN: Demucs's voice separation "
               "varies on every attempt (same input, different output - verified by hash), "
               "and a bad separation brings the whole alignment down. The 2nd attempt usually "
               "works. If it happens again, check that the lyrics match THIS recording (live "
               "versions, remixes and a chorus written only once get in the way).[/yellow]"),
    },
    "main.recall_lrc_ok": {
        "pt": ("[green]OK[/green] O Whisper reconheceu pouco ({recall:.0f}% das palavras), mas "
               "a letra sincronizada foi aceita e segurou o alinhamento ({lrc} inícios de "
               "linha, {pct:.1f}% estimadas)."),
        "en": ("[green]OK[/green] Whisper recognized little ({recall:.0f}% of the words), but "
               "the synced lyrics were accepted and held the alignment ({lrc} line starts, "
               "{pct:.1f}% estimated)."),
    },
    "main.recall_low": {
        "pt": ("[bold red]ATENÇÃO[/bold red] O reconhecimento da letra ficou baixo "
               "({recall:.0f}% das palavras) - o Whisper pode ter entendido outra coisa e "
               "ancorado no lugar errado. O pacote pode sair fora de sincronia."),
        "en": ("[bold red]ATTENTION[/bold red] Lyrics recognition was low ({recall:.0f}% of "
               "the words) - Whisper may have heard something else and anchored in the wrong "
               "place. The package may be out of sync."),
    },
    "main.recall_low_hint": {
        "pt": ("    [yellow]Vale conferir a sincronia e, se estiver ruim, GERAR DE NOVO (a "
               "separação de voz varia a cada tentativa). Confira também se a letra bate com "
               "ESTA gravação.[/yellow]"),
        "en": ("    [yellow]Worth checking the sync and, if it is bad, GENERATING AGAIN (the "
               "voice separation varies on every attempt). Also check that the lyrics match "
               "THIS recording.[/yellow]"),
    },
    "main.lyrics_short": {
        "pt": ("[yellow]AVISO[/yellow] A letra fornecida termina em {last:.1f}s, mas o áudio "
               "tem {duration:.1f}s ({uncovered:.1f}s sem nenhuma palavra no final). Isso "
               "costuma acontecer quando um refrão/trecho repetido foi escrito só uma vez na "
               "letra (ex.: letras de sites que usam \"(2x)\"/\"(4x)\" em vez de repetir o "
               "texto por extenso). Se for o caso, reescreva a letra repetindo o trecho "
               "tantas vezes quanto ele é cantado."),
        "en": ("[yellow]WARNING[/yellow] The lyrics provided end at {last:.1f}s, but the audio "
               "is {duration:.1f}s long ({uncovered:.1f}s with no words at the end). This "
               "usually happens when a repeated chorus/section was written only once in the "
               "lyrics (e.g. lyrics sites that use \"(2x)\"/\"(4x)\" instead of writing the "
               "text out). If so, rewrite the lyrics repeating the section as many times as "
               "it is sung."),
    },
    "main.meta_ok": {
        "pt": "[green]OK[/green] Metadados (fonte: {source}):",
        "en": "[green]OK[/green] Metadata (source: {source}):",
    },
    "main.meta_detail": {
        "pt": "    [dim]ano={year} / gênero={genre} / capa={cover} / fundo={bg}[/dim]",
        "en": "    [dim]year={year} / genre={genre} / cover={cover} / background={bg}[/dim]",
    },
    # Palavras soltas do resumo de metadados acima e da fonte ("arquivo" e
    # "nenhuma" são VALORES internos do metadata.source - traduzimos só na
    # hora de mostrar, sem mexer no dado).
    "main.word_yes": {"pt": "sim", "en": "yes"},
    "main.word_no": {"pt": "não", "en": "no"},
    "main.word_cover": {"pt": "capa", "en": "cover"},
    "main.meta_source_file": {"pt": "arquivo", "en": "file"},
    "main.meta_source_none": {"pt": "nenhuma", "en": "none"},
    "main.video_included": {
        "pt": "[green]OK[/green] Vídeo incluído no pacote: {path}",
        "en": "[green]OK[/green] Video included in the package: {path}",
    },
    "main.stems_converting": {
        "pt": "[cyan]Convertendo faixas separadas (voz/instrumental)...[/cyan]",
        "en": "[cyan]Converting separate tracks (vocals/instrumental)...[/cyan]",
    },
    "main.stems_ok": {
        "pt": "[green]OK[/green] Faixas separadas no pacote: {vocals} / {instrumental}",
        "en": "[green]OK[/green] Separate tracks in the package: {vocals} / {instrumental}",
    },
    "main.stems_fail": {
        "pt": "[yellow]AVISO[/yellow] Não consegui incluir as faixas separadas: {err}",
        "en": "[yellow]WARNING[/yellow] Could not include the separate tracks: {err}",
    },
    "main.romanized": {
        "pt": "[green]OK[/green] Letra romanizada (romaji)",
        "en": "[green]OK[/green] Lyrics romanized (romaji)",
    },
    "main.romanize_fail": {
        "pt": ("[yellow]AVISO[/yellow] Não consegui romanizar (pykakasi instalado? rode o "
               "setup do ambiente de novo): {err}"),
        "en": ("[yellow]WARNING[/yellow] Could not romanize (is pykakasi installed? run the "
               "environment setup again): {err}"),
    },
    "main.txt_ok": {
        "pt": "[green]OK[/green] Arquivo UltraStar gerado (Python): {path}",
        "en": "[green]OK[/green] UltraStar file generated (Python): {path}",
    },
    "main.json_ok": {
        "pt": "[green]OK[/green] JSON intermediário exportado: {path}",
        "en": "[green]OK[/green] Intermediate JSON exported: {path}",
    },
    "main.harmonies_try": {
        "pt": "[cyan]Recuperando vozes de apoio/harmonias...[/cyan]",
        "en": "[cyan]Recovering backing vocals/harmonies...[/cyan]",
    },
    "main.harmonies_ok": {
        "pt": "[green]OK[/green] Vozes de apoio somadas ao instrumental.",
        "en": "[green]OK[/green] Backing vocals mixed into the instrumental.",
    },
    "main.harmonies_fail": {
        "pt": ("[yellow]AVISO[/yellow] Não consegui recuperar as vozes de apoio: {err}. O "
               "pacote sai com o instrumental normal."),
        "en": ("[yellow]WARNING[/yellow] Could not recover the backing vocals: {err}. The "
               "package comes out with the normal instrumental."),
    },
    # {instr} e {tone} são os marcadores opcionais abaixo (ou "").
    "main.audio_converted": {
        "pt": "[green]OK[/green] Áudio {instr}{tone}convertido para .ogg: {path}",
        "en": "[green]OK[/green] Audio {instr}{tone}converted to .ogg: {path}",
    },
    "main.audio_tag_instrumental": {
        "pt": "(INSTRUMENTAL) ",
        "en": "(INSTRUMENTAL) ",
    },
    "main.audio_tag_tone": {
        "pt": "(TOM {n:+d}) ",
        "en": "(KEY {n:+d}) ",
    },
    "main.yarg_try": {
        "pt": "[cyan]Exportando pacote para o YARG...[/cyan]",
        "en": "[cyan]Exporting the package for YARG...[/cyan]",
    },
    "main.yarg_ok": {
        "pt": "[green]OK[/green] Pasta YARG pronta: {path}",
        "en": "[green]OK[/green] YARG folder ready: {path}",
    },
    "main.yarg_fail": {
        "pt": "[yellow]AVISO[/yellow] Não consegui exportar para o YARG: {err}. O pacote UltraStar está OK.",
        "en": "[yellow]WARNING[/yellow] Could not export for YARG: {err}. The UltraStar package is OK.",
    },
    "main.mp4_no_libass": {
        "pt": ("[yellow]AVISO[/yellow] O ffmpeg encontrado não tem suporte a legendas "
               "(libass), então não dá para gravar a letra no vídeo. O pacote UltraStar está "
               "OK. Rode o setup do ambiente de novo para baixar o ffmpeg completo."),
        "en": ("[yellow]WARNING[/yellow] The ffmpeg found has no subtitle support (libass), "
               "so the lyrics cannot be burned into the video. The UltraStar package is OK. "
               "Run the environment setup again to download the full ffmpeg."),
    },
    "main.mp4_rendering": {
        "pt": "[cyan]Renderizando vídeo de karaokê (.mp4)...[/cyan]",
        "en": "[cyan]Rendering the karaoke video (.mp4)...[/cyan]",
    },
    "main.mp4_ok": {
        "pt": "[green]OK[/green] Vídeo de karaokê pronto: {path}",
        "en": "[green]OK[/green] Karaoke video ready: {path}",
    },
    "main.mp4_fail": {
        "pt": ("[yellow]AVISO[/yellow] Não consegui renderizar o vídeo de karaokê: {err}. O "
               "pacote UltraStar está OK."),
        "en": ("[yellow]WARNING[/yellow] Could not render the karaoke video: {err}. The "
               "UltraStar package is OK."),
    },
    "main.clean_ok": {
        "pt": "[green]OK[/green] Intermediários removidos: {path}",
        "en": "[green]OK[/green] Intermediate files removed: {path}",
    },
    "main.clean_fail": {
        "pt": ("[yellow]AVISO[/yellow] Não consegui remover a pasta de intermediários "
               "({path}): {err}. O pacote final está OK; a pasta pode ser apagada à mão."),
        "en": ("[yellow]WARNING[/yellow] Could not remove the intermediate files folder "
               "({path}): {err}. The final package is OK; the folder can be deleted by hand."),
    },
    "main.done": {
        "pt": "[bold green]Pipeline concluída",
        "en": "[bold green]Pipeline finished",
    },
    "main.out_ready": {
        "pt": "Pasta pronta em: [bold]{path}[/bold]",
        "en": "Folder ready at: [bold]{path}[/bold]",
    },
    "main.reminder": {
        "pt": ("[yellow]Lembrete:[/yellow] confira o .txt manualmente contra a spec oficial e "
               "teste carregando no UltraStar Deluxe antes de considerar definitivo."),
        "en": ("[yellow]Reminder:[/yellow] check the .txt by hand against the official spec and "
               "test it by loading it in UltraStar Deluxe before considering it final."),
    },

    # --------------------------------------------------------- download.py
    # Estas viram a mensagem de ERRO que a interface mostra quando o download
    # falha (a exceção sobe até o _job_status.json) - não só log.
    "download.what_audio": {"pt": "o áudio", "en": "the audio"},
    "download.what_video": {"pt": "o vídeo", "en": "the video"},
    "download.what_bgvideo": {"pt": "o videoclipe de fundo", "en": "the background music video"},
    "download.cause_age": {
        "pt": ("O vídeo tem restrição de idade e exige login no YouTube. Escolha o seu "
               "navegador em \"Cookies do YouTube\" (nas opções) e gere de novo."),
        "en": ("The video is age-restricted and requires a YouTube login. Pick your browser "
               "under \"YouTube cookies\" (in the options) and generate again."),
    },
    "download.cause_private": {
        "pt": "O vídeo é privado.",
        "en": "The video is private.",
    },
    "download.cause_unavailable": {
        "pt": "O vídeo não está disponível (removido ou bloqueado na sua região).",
        "en": "The video is not available (removed or blocked in your region).",
    },
    "download.cause_bot": {
        "pt": ("O YouTube pediu verificação de robô para este vídeo. Escolha o navegador em "
               "que você está logado no YouTube em \"Cookies do YouTube\" (nas opções) e gere de novo."),
        "en": ("YouTube asked for a bot check for this video. Pick the browser you are signed "
               "in to YouTube with under \"YouTube cookies\" (in the options) and generate again."),
    },
    "download.cause_format": {
        "pt": "O YouTube não ofereceu nenhum formato compatível para este vídeo.",
        "en": "YouTube did not offer any compatible format for this video.",
    },
    "download.cause_cookies_locked": {
        "pt": ("Não foi possível acessar os cookies do navegador (o Chrome/navegador está aberto "
               "e bloqueou o arquivo de cookies). Feche o navegador completamente ou mude "
               "\"Cookies do YouTube\" para \"Desligado\" nas opções."),
        "en": ("Could not access browser cookies (Chrome/browser is open and locked its cookie file). "
               "Close the browser completely or set \"YouTube cookies\" to \"Off\" in options."),
    },
    "download.cause_403": {
        "pt": "O YouTube recusou o download (403). Costuma ser temporário.",
        "en": "YouTube refused the download (403). This is usually temporary.",
    },
    "download.cause_unknown": {
        "pt": "o yt-dlp falhou sem dizer o motivo",
        "en": "yt-dlp failed without saying why",
    },
    "download.retrying": {
        "pt": ("[download] O YouTube recusou ({err}). Isso costuma ser temporário - tentando "
               "mais uma vez..."),
        "en": ("[download] YouTube refused ({err}). This is usually temporary - trying "
               "once more..."),
    },
    "download.failed": {
        "pt": ("Não consegui baixar {what} do YouTube. {detail} Se persistir, use o modo "
               "ARQUIVO LOCAL (baixe a música por fora e aponte o app para ela) ou atualize o "
               "yt-dlp - o YouTube muda com frequência e o yt-dlp precisa acompanhar."),
        "en": ("Could not download {what} from YouTube. {detail} If it persists, use LOCAL "
               "FILE mode (download the song elsewhere and point the app to it) or update "
               "yt-dlp - YouTube changes often and yt-dlp has to keep up."),
    },
    "download.audio_missing": {
        "pt": "yt-dlp rodou mas {path} não foi encontrado.",
        "en": "yt-dlp ran but {path} was not found.",
    },
    "download.video_missing": {
        "pt": "yt-dlp rodou mas nenhum vídeo foi encontrado em {path}",
        "en": "yt-dlp ran but no video was found in {path}",
    },
    "download.extract_failed": {
        "pt": "Falha ao extrair áudio do vídeo baixado: {path}",
        "en": "Failed to extract the audio from the downloaded video: {path}",
    },
    "download.bgvideo_reuse": {
        "pt": "[OK] Videoclipe de fundo já baixado, reaproveitando: {path}",
        "en": "[OK] Background music video already downloaded, reusing: {path}",
    },
    "download.bgvideo_failed": {
        "pt": "[AVISO] Download do videoclipe de fundo falhou (seguindo sem vídeo): {err}",
        "en": "[WARNING] Background music video download failed (continuing without video): {err}",
    },
    "download.bgvideo_none": {
        "pt": "[AVISO] yt-dlp rodou mas nenhum vídeo de fundo foi encontrado (seguindo sem vídeo).",
        "en": "[WARNING] yt-dlp ran but no background video was found (continuing without video).",
    },
    "download.need_source": {
        "pt": "Forneça --url (YouTube) ou --file (mp3/wav local).",
        "en": "Provide --url (YouTube) or --file (local mp3/wav).",
    },

    # --------------------------------------------------------- separate.py
    "separate.diag_before": {
        "pt": "[DIAG] Prestes a chamar subprocess: {cmd}",
        "en": "[DIAG] About to call subprocess: {cmd}",
    },
    "separate.diag_after": {
        "pt": "[DIAG] subprocess do Demucs retornou com sucesso.",
        "en": "[DIAG] Demucs subprocess returned successfully.",
    },
    "separate.no_stems": {
        "pt": ("Demucs rodou mas não encontrei os stems esperados em {path}. Confira a versão "
               "do demucs instalada (a estrutura de pastas pode variar)."),
        "en": ("Demucs ran but I did not find the expected stems in {path}. Check the "
               "installed demucs version (the folder layout may vary)."),
    },
    "separate.no_lead": {
        "pt": ("audio-separator rodou mas não encontrei a voz principal isolada em {path} "
               "(saída reportada: {files})."),
        "en": ("audio-separator ran but I did not find the isolated lead vocal in {path} "
               "(reported output: {files})."),
    },
    "separate.no_backing": {
        "pt": ("audio-separator rodou mas não achei o stem de vozes de apoio em {path} "
               "(arquivos gerados: {files})."),
        "en": ("audio-separator ran but I did not find the backing vocals stem in {path} "
               "(files produced: {files})."),
    },

    # --------------------------------------------------------- beatgrid.py
    "beatgrid.manual_out_of_range": {
        "pt": ("[BPM] Manual {bpm:.2f} usado como veio. Nota: fora da faixa {lo:.0f}-{hi:.0f} "
               "a grade fica mais grossa (1 beat = {beat_ms:.0f} ms), o que arredonda mais as "
               "notas. Um múltiplo por 2 do mesmo andamento dá a mesma música com notas mais "
               "precisas."),
        "en": ("[BPM] Manual {bpm:.2f} used as given. Note: outside the {lo:.0f}-{hi:.0f} range "
               "the grid gets coarser (1 beat = {beat_ms:.0f} ms), which rounds the notes "
               "more. Multiplying the same tempo by 2 gives the same song with more precise "
               "notes."),
    },
    "beatgrid.octave_fix": {
        "pt": "[BPM] Correcao de oitava: {raw:.2f} -> {bpm:.2f} (faixa alvo {lo:.0f}-{hi:.0f})",
        "en": "[BPM] Octave correction: {raw:.2f} -> {bpm:.2f} (target range {lo:.0f}-{hi:.0f})",
    },

    # ------------------------------------------------------- build_song.py
    # Antes saía em pt E en na mesma mensagem (29/09/2026: agora sai uma só,
    # no idioma da interface).
    "build_song.out_of_order": {
        "pt": ("[AVISO] {n} nota(s) fora de ordem no tempo (notas {pairs}): um tempo de "
               "palavra veio errado do alinhamento. Deixadas como estão para a tela de "
               "revisão mostrar - confira e corrija antes de usar a música."),
        "en": ("[WARNING] {n} note(s) out of time order (notes {pairs}): a word timing came "
               "out wrong from alignment. Left as they are so the review screen shows them - "
               "check and fix them before using the song."),
    },

    # ------------------------------------------------- ultrastar_writer.py
    "writer.overlaps_header": {
        "pt": "[ATENÇÃO] Overlaps detectados antes de salvar:",
        "en": "[ATTENTION] Overlaps detected before saving:",
    },
    "writer.overlap": {
        "pt": "Sobreposição entre nota {i} (fim={end}) e nota {j} (início={start})",
        "en": "Overlap between note {i} (end={end}) and note {j} (start={start})",
    },

    # ------------------------------------------------------------ align.py
    "align.ctc_model_fallback": {
        "pt": ("[AVISO] Não consegui carregar o modelo de alinhamento do "
               "idioma ({model}): {err} - usando o modelo multilíngue."),
        "en": ("[WARNING] Couldn't load the language's alignment model "
               "({model}): {err} - using the multilingual model."),
    },
    "align.ctc_lrc_blocks": {
        "pt": ("[INFO] Letra sincronizada APROVADA pelo usuário - {n} inícios de linha "
               "conferidos de ouvido limitam o alinhamento."),
        "en": ("[INFO] Synced lyrics APPROVED by the user - {n} line starts checked by ear "
               "bound the alignment."),
    },
    "align.lrc_approved": {
        "pt": ("[INFO] Letra sincronizada APROVADA pelo usuário - os inícios de linha "
               "conferidos de ouvido mandam sobre as âncoras do Whisper, e as checagens de "
               "duração/reconhecimento não se aplicam."),
        "en": ("[INFO] Synced lyrics APPROVED by the user - the line starts checked by ear "
               "override Whisper's anchors, and the duration/recognition checks do not "
               "apply."),
    },
    "align.approved_seeded": {
        "pt": "[INFO] Letra aprovada: {n} inícios de linha semeados (prioritários).",
        "en": "[INFO] Approved lyrics: {n} line starts seeded (priority).",
    },
    "align.approved_demoted": {
        "pt": "[INFO] Letra aprovada: {n} âncoras implausíveis demovidas.",
        "en": "[INFO] Approved lyrics: {n} implausible anchors demoted.",
    },
    "align.lrc_mismatch": {
        "pt": ("[AVISO] Letra sincronizada (.lrc) ignorada: a duração implícita não bate com "
               "a gravação baixada (provável versão diferente - ao vivo, remix, edição). O "
               "alinhamento segue só com Whisper + forced alignment."),
        "en": ("[WARNING] Synced lyrics (.lrc) ignored: their implied duration does not match "
               "the downloaded recording (probably a different version - live, remix, edit). "
               "Alignment continues with Whisper + forced alignment only."),
    },
    "align.lrc_trusted": {
        "pt": ("[INFO] Reconhecimento baixo ({recall:.0f}%) e .lrc com duração compatível - "
               "os inícios de linha da letra sincronizada passam a ter prioridade sobre as "
               "âncoras do Whisper."),
        "en": ("[INFO] Low recognition ({recall:.0f}%) and a .lrc with a compatible duration - "
               "the synced lyrics' line starts now take priority over Whisper's anchors."),
    },
    "align.lrc_seeded_priority": {
        "pt": "[INFO] Âncoras de linha do .lrc: {n} inícios de linha semeados (prioritários).",
        "en": "[INFO] .lrc line anchors: {n} line starts seeded (priority).",
    },
    "align.lrc_demoted": {
        "pt": "[INFO] Âncoras de linha do .lrc: {n} âncoras implausíveis demovidas.",
        "en": "[INFO] .lrc line anchors: {n} implausible anchors demoted.",
    },
    "align.lrc_offset": {
        "pt": "[INFO] O .lrc estava deslocado {offset:+.2f} s em relação ao áudio (medido nas âncoras do Whisper) - tempos corrigidos.",
        "en": "[INFO] The .lrc was offset by {offset:+.2f} s from the audio (measured on Whisper's anchors) - timings corrected.",
    },
    "align.lrc_offset_rejected": {
        "pt": "[INFO] As âncoras do Whisper sugeriam o .lrc deslocado {offset:+.2f} s, mas o áudio não confirmou - .lrc mantido como está.",
        "en": "[INFO] Whisper's anchors suggested the .lrc was offset by {offset:+.2f} s, but the audio didn't confirm it - .lrc left as is.",
    },
    "align.lrc_seeded": {
        "pt": "[INFO] Âncoras de linha do .lrc: {n} inícios de linha semeados.",
        "en": "[INFO] .lrc line anchors: {n} line starts seeded.",
    },
    "align.realigned": {
        "pt": "[INFO] Realinhamento de janela: {n} palavras medidas no 2º passe.",
        "en": "[INFO] Window realignment: {n} words measured in the 2nd pass.",
    },

    # --------------------------------------------------------- metadata.py
    # Prefixo "[metadata]" igual nos dois idiomas (é o nome do módulo).
    "metadata.tags_failed": {
        "pt": "[metadata] aviso: falha ao ler tags embutidas ({err}) - seguindo sem elas.",
        "en": "[metadata] warning: failed to read embedded tags ({err}) - continuing without them.",
    },
    "metadata.mb_search_failed": {
        "pt": "[metadata] aviso: busca no MusicBrainz falhou ({err}) - seguindo sem ela.",
        "en": "[metadata] warning: MusicBrainz search failed ({err}) - continuing without it.",
    },
    "metadata.mb_release_failed": {
        "pt": "[metadata] aviso: lookup de release no MusicBrainz falhou ({err}).",
        "en": "[metadata] warning: MusicBrainz release lookup failed ({err}).",
    },
    "metadata.caa_failed": {
        "pt": "[metadata] aviso: download da capa no Cover Art Archive falhou ({err}).",
        "en": "[metadata] warning: cover download from the Cover Art Archive failed ({err}).",
    },
    "metadata.itunes_failed": {
        "pt": "[metadata] aviso: busca no iTunes falhou ({err}) - seguindo sem ela.",
        "en": "[metadata] warning: iTunes search failed ({err}) - continuing without it.",
    },
    "metadata.itunes_cover_failed": {
        "pt": "[metadata] aviso: download da capa do iTunes falhou ({err}).",
        "en": "[metadata] warning: iTunes cover download failed ({err}).",
    },
    "metadata.deezer_failed": {
        "pt": "[metadata] aviso: busca/capa no Deezer falhou ({err}) - seguindo sem ela.",
        "en": "[metadata] warning: Deezer search/cover failed ({err}) - continuing without it.",
    },
    "metadata.mb_artist_failed": {
        "pt": "[metadata] aviso: busca de artista no MusicBrainz falhou ({err}).",
        "en": "[metadata] warning: MusicBrainz artist search failed ({err}).",
    },
    "metadata.fanart_no_key": {
        "pt": "[metadata] fanart.tv: FANARTTV_API_KEY não definido neste processo - background pulado.",
        "en": "[metadata] fanart.tv: FANARTTV_API_KEY not set in this process - background skipped.",
    },
    "metadata.fanart_failed": {
        "pt": "[metadata] aviso: consulta ao fanart.tv falhou ({err}) - seguindo sem background.",
        "en": "[metadata] warning: fanart.tv query failed ({err}) - continuing without a background.",
    },
    "metadata.fanart_bg_failed": {
        "pt": "[metadata] aviso: download do background do fanart.tv falhou ({err}).",
        "en": "[metadata] warning: fanart.tv background download failed ({err}).",
    },
    "metadata.lastfm_no_key": {
        "pt": "[metadata] Last.fm: LASTFM_API_KEY não definido neste processo - fonte pulada.",
        "en": "[metadata] Last.fm: LASTFM_API_KEY not set in this process - source skipped.",
    },
    "metadata.lastfm_failed": {
        "pt": "[metadata] aviso: busca no Last.fm falhou ({err}) - seguindo sem ela.",
        "en": "[metadata] warning: Last.fm search failed ({err}) - continuing without it.",
    },
    "metadata.lastfm_cover_failed": {
        "pt": "[metadata] aviso: download da capa do Last.fm falhou ({err}).",
        "en": "[metadata] warning: Last.fm cover download failed ({err}).",
    },
    "metadata.discogs_no_key": {
        "pt": "[metadata] Discogs: DISCOGS_TOKEN não definido neste processo - fonte pulada.",
        "en": "[metadata] Discogs: DISCOGS_TOKEN not set in this process - source skipped.",
    },
    "metadata.discogs_no_image": {
        "pt": "[metadata] Discogs: resultados encontrados, mas nenhum com imagem utilizável.",
        "en": "[metadata] Discogs: results found, but none with a usable image.",
    },
    "metadata.discogs_no_result": {
        "pt": "[metadata] Discogs: nenhum resultado para '{artist} - {title}'.",
        "en": "[metadata] Discogs: no results for '{artist} - {title}'.",
    },
    "metadata.discogs_failed": {
        "pt": "[metadata] aviso: busca/capa no Discogs falhou ({err}) - seguindo sem ela.",
        "en": "[metadata] warning: Discogs search/cover failed ({err}) - continuing without it.",
    },
    "metadata.bad_cover": {
        "pt": "[metadata] aviso: imagem de capa inválida/não processável ({err}).",
        "en": "[metadata] warning: invalid/unprocessable cover image ({err}).",
    },
}

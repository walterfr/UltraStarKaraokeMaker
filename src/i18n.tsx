import { createContext, useContext, useEffect, useState } from "react";

// i18n leve, sem dependências: dicionário tipado + contexto React.
// - Idioma padrão: o do sistema (navigator.language) na primeira execução -
//   cobre a "escolha na instalação" (o instalador NSIS já é PT-BR/EN e o
//   Windows do usuário define o idioma inicial do app).
// - Trocável a qualquer momento pelo seletor no cabeçalho; persiste em
//   localStorage.
// - Placeholders com {nome}, substituídos via o parâmetro `vars` de t().
// Logs técnicos do pipeline Python permanecem em PT (são diagnóstico, não UI).

export type Lang = "pt" | "en";

const STRINGS = {
  pt: {
    // ---- geral / cabeçalho ----
    subtitle: "Gere pacotes UltraStar (letra sincronizada + pitch) a partir de um link do YouTube ou arquivo local.",
    reviewExisting: "Revisar um pacote já gerado...",
    aboutTitle: "Sobre o USKMaker",
    aboutTagline: "Gerador de pacotes de karaokê UltraStar com IA — sincronização de letra, pitch e BPM automáticos, processados localmente.",
    aboutMadeWith: "Feito com ♥ em Fortaleza-CE por @prof.walterfr",
    aboutVersion: "Versão {v}",
    aboutSupport: "Apoie o projeto:",
    aboutPixCopy: "Copiar chave Pix",
    aboutPixCopied: "Chave Pix copiada!",
    aboutClose: "Fechar",
    infoButtonTitle: "Sobre o USKMaker",

    // ---- ambiente ----
    envAI: "Ambiente de IA",
    envNoGpu: "⚠ sem GPU NVIDIA — processamento em CPU (lento)",
    envGpu: "✓ GPU {name}",
    envIncomplete: "Ambiente incompleto — a geração vai falhar até resolver:",
    envNoFfmpeg: "ffmpeg não encontrado no PATH — instale (https://www.gyan.dev/ffmpeg/builds/) e reinicie o app.",
    envNoVorbis: "O ffmpeg instalado não tem suporte a libvorbis (necessário para o áudio .ogg do pacote) — use um build \"full\".",
    setupButton: "Configurar ambiente de IA",
    setupHint: "Baixa o Python, o ffmpeg e as bibliotecas de IA automaticamente (~2 GB). Precisa de internet e leva alguns minutos.",
    setupRunning: "Configurando o ambiente... (baixando ~2 GB, pode levar ~10 min)",
    setupDone: "Ambiente configurado! Pode gerar sua primeira música.",
    setupErrorPrefix: "Falha no setup:",

    // ---- fonte ----
    tabYoutube: "Link do YouTube",
    tabFile: "Arquivo local",
    youtubeLabel: "Link do YouTube",
    withVideoLabel: "Incluir o vídeo no pacote",
    withVideoTip: "Fundo animado no jogo — download maior e mais lento.",
    fileLabel: "Arquivo de áudio/vídeo",
    filePlaceholder: "Nenhum arquivo selecionado",
    browse: "Procurar...",
    bgVideoLabel: "Baixar videoclipe do YouTube para o fundo",
    bgVideoTip: "O áudio continua sendo o seu arquivo; sem vídeo disponível, fica só a capa.",
    bgVideoUrlPlaceholder: "Link do videoclipe (opcional — em branco, busca automática por artista + título)",
    fileFilterName: "Áudio/Vídeo",

    // ---- letra ----
    lyricsLabel: "Letra da música",
    lyricsTip: "Uma linha por frase cantada. Repita refrões por extenso, tantas vezes quanto forem cantados — não use \"(2x)\".",
    lyricsPlaceholder: "Cole a letra aqui...\nUma linha por frase/verso.\nRefrões repetidos devem ser colados de novo, por extenso.",
    lyricsCount: "{lines} {lineWord} · {words} palavras",
    searchLyrics: "Buscar letra (LRCLIB)",
    searchingLyrics: "Buscando letra...",
    lyricsFoundSynced: "Letra sincronizada encontrada — os tempos das linhas serão usados como âncoras do alinhamento. Revise o texto antes de gerar.",
    tagsAutofilled: "Preenchido a partir do arquivo: {fields}. Confira antes de gerar.",
    lyricsFoundPlain: "Letra encontrada (sem sincronia de tempo). Revise antes de gerar.",
    lyricsNotFound: "Letra não encontrada no LRCLIB — confira artista/título ou cole manualmente.",
    lyricsSearchError: "Falha ao consultar o LRCLIB: {msg}",
    lyricsNeedArtistTitle: "Preencha artista e título (acima ou abaixo) antes de buscar a letra.",
    lyricsOverwriteConfirm: "Substituir a letra já colada pela letra encontrada no LRCLIB?",
    lineSingular: "linha",
    linePlural: "linhas",
    lyricWarn2x: "Marcação \"(2x)\" encontrada — o alinhador não entende repetição implícita. Cole o trecho repetido por extenso, tantas vezes quanto ele é cantado.",
    lyricWarnBis: "Marcação \"(bis)\" encontrada — substitua pela repetição escrita por extenso.",
    lyricWarnSection: "Linha de seção como \"[Refrão]\"/\"[Verse]\" encontrada — remova; o arquivo deve conter apenas o texto cantado.",
    lyricWarnLrc: "Timestamps de arquivo .lrc encontrados (\"[00:12]\") — cole a letra pura, sem marcações de tempo; a sincronização é feita pelo próprio USKMaker.",

    // ---- campos ----
    titleLabel: "Título",
    artistLabel: "Artista",
    languageLabel: "Idioma da música",
    langNonLatinHint: "Escreva a letra na escrita nativa deste idioma (ex.: 한국어, 日本語, alfabeto cirílico), não romanizada — senão o reconhecimento não casa com a letra.",
    bpmLabel: "BPM manual (opcional)",
    bpmPlaceholder: "auto",
    bpmTip: "Deixe em branco para detectar automaticamente. Se preencher, o valor digitado vai exatamente como está para o pacote.",
    outDirLabel: "Pasta de saída",
    outDirPlaceholder: "Nenhuma pasta selecionada",
    outDirPick: "Escolher pasta...",
    outDirHint: "O pacote será criado numa subpasta \"Artista - Título\" dentro da pasta escolhida.",
    sectionPackage: "Pacote",
    sectionOptions: "Opções",
    sectionNext: "E agora?",
    cleanWorkLabel: "Remover intermediários ao final",
    cleanWorkHint: "Economiza espaço; deixe desmarcado para reprocessar mais rápido.",
    cleanExtrasLabel: "Só o essencial (apaga .lrc/.log/.json) ⚠",
    cleanExtrasHint: "Apaga os auxiliares (.lrc, .log, .json) e o song_data.json ao final da fila — os pacotes ficarão SEM a tela de revisão. Deixe desmarcado se quiser revisar depois.",
    withStemsLabel: "Faixas separadas (voz + instrumental)",
    withStemsHint: "Permite ao jogo controlar o volume da voz-guia separado do instrumental (subir para aprender, zerar para cantar sozinho). O pacote fica quase 3x maior. A separação já é feita de qualquer jeito — isto só a inclui no pacote.",
    duetLabel: "Dueto (duas vozes)",
    duetHint: "Marque para gerar um dueto. Na letra, comece as linhas de cada cantor com uma tag: \"P1: ...\", \"P2: ...\" ou \"P1&P2: ...\" quando cantam juntos. Uma linha sem tag continua com o cantor da anterior. O pacote sai no formato de dueto (#P1/#P2, blocos P1/P2, sufixo [DUET]).",
    backtrackLabel: "Backtrack (só instrumental)",
    backtrackHint: "O áudio do pacote fica só com o instrumental (sem a voz-guia) — karaokê puro, você canta por cima. Usa a separação da voz que o app já faz; a qualidade depende dela e pode sobrar um resíduo de voz. O alinhamento e as notas não mudam.",

    // ---- validação ----
    valNeedYoutube: "Informe o link do YouTube.",
    valNeedFile: "Selecione um arquivo de áudio/vídeo local.",
    valNeedLyrics: "Cole a letra da música.",
    valNeedTitle: "Informe o título.",
    valNeedArtist: "Informe o artista.",
    valNeedOutDir: "Escolha a pasta de saída.",

    // ---- execução ----
    generate: "Gerar pacote UltraStar",
    generateQueue: "Gerar fila ({n})",
    queueAdd: "+ Adicionar à fila",
    queueHeader: "Fila ({n})",
    queueStatusPending: "na fila",
    queueStatusRunning: "gerando...",
    queueStatusDone: "pronto",
    queueStatusError: "erro",
    queueStatusCancelled: "cancelado",
    queueRemove: "Remover",
    queueReview: "Revisar",
    reviewUnavailableCleaned: "Revisão indisponível: os auxiliares (song_data.json) foram apagados para este pacote.",
    queueOpen: "Abrir pasta",
    queueClearDone: "Limpar concluídas",
    clearFields: "Limpar campos",
    clearConfirm: "Limpar todos os campos? A letra digitada será perdida.",
    generating: "Gerando... ({time})",
    cancel: "Cancelar",
    cancelling: "Cancelando...",
    cancelledInfo: "Geração cancelada. Os arquivos parciais ficaram na pasta de saída e serão reaproveitados se você gerar de novo com a mesma pasta.",
    windowGenerating: "USKMaker — Gerando: {song}",
    notifDoneOne: "✓ Pronto: {song}",
    notifFailOne: "✗ Falhou: {song}",
    notifDoneQueue: "✓ Fila concluída — {ok} ok, {fail} com erro",
    reviewNoPackage: "Não encontrei um pacote nessa pasta (nem song_data.json, nem um .txt de chart). Selecione a pasta de um pacote UltraStar.",
    reviewOurs: "Pacote gerado pelo USKMaker.",
    reviewThirdParty: "Pacote de outra fonte (lido do .txt). Dá para baixar os complementos que faltam; a edição de notas fica só para pacotes gerados aqui.",
    assetCover: "Capa",
    assetBg: "Fundo",
    assetVideo: "Vídeo",
    assetDownloadMissing: "Baixar o que falta: {list}",
    assetDownloading: "Baixando…",
    assetGot: "Baixado: {got}.",
    assetNone: "Nada encontrado para baixar.",
    assetEditNotes: "Editar notas",
    step1: "Obter áudio",
    step1Hint: "segundos (arquivo) · ~1 min (YouTube)",
    step2: "Separar vocal do instrumental",
    step2Hint: "~1–3 min na GPU, o passo mais longo",
    step3: "Detectar BPM",
    step3Hint: "segundos",
    step4: "Alinhar letra ao áudio",
    step4Hint: "~1–2 min",
    step5: "Buscar capa, ano e gênero",
    step5Hint: "segundos",
    step6: "Extrair pitch e montar o pacote",
    step6Hint: "~1 min",
    logDetails: "Detalhes técnicos ({n} linhas de log)",
    errorPrefix: "Erro:",
    unknownError: "Erro desconhecido ao rodar o pipeline.",

    // ---- resultado ----
    resultSuccess: "Pacote gerado com sucesso!",
    resultNotesMeasured: "{n} notas medidas no áudio",
    resultNotesEstimated: " · {n} estimadas — vale revisar",
    resultAlignFailed:
      "{pct}% das notas são estimativas: o app não conseguiu reconhecer o canto nesta música, " +
      "então o pacote provavelmente está fora de sincronia. Vale gerar esta música de novo: " +
      "a separação da voz varia a cada tentativa, e normalmente a segunda funciona. " +
      "Se repetir, confira se a letra bate com esta gravação (versão ao vivo, remix e refrão " +
      "escrito uma vez só atrapalham).",
    resultLowRecall:
      "O app reconheceu só {pct}% da letra na música — pode ter entendido outra coisa e " +
      "colocado as notas no lugar errado. Vale conferir a sincronia; se estiver ruim, gere de " +
      "novo (a separação da voz varia a cada tentativa) e confira se a letra bate com esta gravação.",
    resultReview: "Revisar alinhamento",
    resultReviewHint: "É a melhor forma de acertar trechos: você ajusta as notas sem gerar de novo, então conserta só o pedaço ruim sem mexer no que ficou bom.",
    resultOpenFolder: "Abrir pasta",
    resultRegen: "Gerar de novo",
    resultRegenHint: "Gera esta mesma música outra vez, sem redigitar. A separação do vocal varia a cada tentativa — se saiu ruim, a próxima costuma melhorar. Para acertar trechos, prefira Revisar.",
    resultNewSong: "Nova música",

    // ---- revisão ----
    revTitle: "Revisão",
    revLoading: "Carregando pacote...",
    revBack: "Voltar",
    revClose: "Fechar",
    revSave: "Salvar (.txt + JSON)",
    revSaving: "Salvando...",
    revPlay: "▶ Tocar",
    revPause: "⏸ Pausar",
    revToStart: "Voltar ao início",
    revListenMix: "Ouvir: mix completo",
    revListenVocals: "Ouvir: só o vocal",
    revListenTitle: "Qual áudio ouvir durante a revisão",
    revGap: "GAP (ms)",
    revGapStepTitle: "Desloca a música inteira no tempo",
    revUndo: "↶ Desfazer",
    revRedo: "↷ Refazer",
    revNextFlagged: "⚠ Próxima flagrada ({n})",
    revNextFlaggedTitle: "Seleciona e centraliza a próxima nota estimada ou com score suspeito (não medida com confiança no áudio)",
    revMinimapTitle: "Visão geral da música — clique para navegar; riscos laranja/vermelho = notas estimadas/suspeitas",
    revHints: "Arrastar nota: mover no tempo/pitch · borda direita: duração · duplo-clique/Enter: ouvir a nota · setas: ajuste fino (Shift+←→: duração · Alt+←→: frase inteira) · Del: excluir · roda: rolar · Ctrl+roda: zoom · Espaço: tocar/pausar",
    revLegendTiming: "Timing:",
    revLegendAnchor: "medido (exato)",
    revLegendFuzzy: "medido (grafia≈)",
    revLegendRealign: "medido (2º passe)",
    revLegendInterp: "estimado — conferir",
    revLegendLowScore: "medido, score baixo — conferir",
    revLegendLrc: "início de linha (.lrc)",
    revLegendGolden: "golden",
    revLegendFreestyle: "freestyle",
    revSyllable: "Sílaba",
    revStartBeat: "Início (beat)",
    revDuration: "Duração (beats)",
    revPitch: "Pitch",
    revType: "Tipo",
    revTypeNormal: "Normal",
    revTypeGolden: "Golden",
    revTypeFreestyle: "Freestyle",
    revPhraseBreak: "Quebra de frase após esta nota",
    revNoteTime: "{start}s · {dur}s de duração",
    revDeleteNote: "Excluir nota",
    revSourceAnchor: "medida (match exato)",
    revSourceFuzzy: "medida (grafia aproximada)",
    revSourceRealign: "medida (2º passe na janela)",
    revSourceInterp: "ESTIMADA (interpolada) — conferir",
    revSourceLrc: "início de linha (.lrc sincronizado)",
    revSaved: "Salvo: {path}",
    revWarnings: "Avisos de validação:",
    revNoAudio: "O arquivo de áudio do pacote não foi encontrado — a timeline funciona, mas sem playback.",
    revLoadError: "Erro ao carregar o pacote.",
    revSaveError: "Erro ao salvar.",
    revConfirmDiscard: "Há alterações não salvas. Sair mesmo assim e descartá-las?",
    revNoText: "(sem texto)",
  },
  en: {
    subtitle: "Create UltraStar packages (synced lyrics + pitch) from a YouTube link or a local file.",
    reviewExisting: "Review an existing package...",
    aboutTitle: "About USKMaker",
    aboutTagline: "AI-powered UltraStar karaoke package maker — automatic lyric syncing, pitch and BPM detection, all processed locally.",
    aboutMadeWith: "Made with ♥ in Fortaleza-CE, Brazil by @prof.walterfr",
    aboutSupport: "Support the project:",
    aboutPixCopy: "Copy Pix key",
    aboutPixCopied: "Pix key copied!",
    aboutVersion: "Version {v}",
    aboutClose: "Close",
    infoButtonTitle: "About USKMaker",

    envAI: "AI environment",
    envNoGpu: "⚠ no NVIDIA GPU — CPU processing (slow)",
    envGpu: "✓ GPU {name}",
    envIncomplete: "Incomplete environment — generation will fail until fixed:",
    envNoFfmpeg: "ffmpeg not found on PATH — install it (https://www.gyan.dev/ffmpeg/builds/) and restart the app.",
    setupButton: "Set up AI environment",
    setupHint: "Downloads Python, ffmpeg and the AI libraries automatically (~2 GB). Requires internet and takes a few minutes.",
    setupRunning: "Setting up the environment... (downloading ~2 GB, may take ~10 min)",
    setupDone: "Environment ready! You can generate your first song.",
    setupErrorPrefix: "Setup failed:",
    envNoVorbis: "The installed ffmpeg lacks libvorbis support (needed for the package's .ogg audio) — use a \"full\" build.",

    tabYoutube: "YouTube link",
    tabFile: "Local file",
    youtubeLabel: "YouTube link",
    withVideoLabel: "Include the video in the package",
    withVideoTip: "Animated background in game — bigger, slower download.",
    fileLabel: "Audio/video file",
    filePlaceholder: "No file selected",
    browse: "Browse...",
    bgVideoLabel: "Download a YouTube music video for the background",
    bgVideoTip: "Your file remains the audio; if no video is found, the cover is used.",
    bgVideoUrlPlaceholder: "Music video link (optional — leave blank for automatic search by artist + title)",
    fileFilterName: "Audio/Video",

    lyricsLabel: "Song lyrics",
    lyricsTip: "One line per sung phrase. Write repeated choruses out in full, as many times as they are sung — don't use \"(2x)\".",
    lyricsPlaceholder: "Paste the lyrics here...\nOne line per phrase/verse.\nRepeated choruses must be pasted again, in full.",
    lyricsCount: "{lines} {lineWord} · {words} words",
    searchLyrics: "Search lyrics (LRCLIB)",
    searchingLyrics: "Searching lyrics...",
    lyricsFoundSynced: "Synced lyrics found — line timestamps will be used as alignment anchors. Review the text before generating.",
    tagsAutofilled: "Filled in from the file: {fields}. Double-check before generating.",
    lyricsFoundPlain: "Lyrics found (no time sync). Review before generating.",
    lyricsNotFound: "Lyrics not found on LRCLIB — check artist/title or paste them manually.",
    lyricsSearchError: "LRCLIB request failed: {msg}",
    lyricsNeedArtistTitle: "Fill in artist and title (above or below) before searching for lyrics.",
    lyricsOverwriteConfirm: "Replace the lyrics you already pasted with the ones found on LRCLIB?",
    lineSingular: "line",
    linePlural: "lines",
    lyricWarn2x: "\"(2x)\" marker found — the aligner doesn't understand implicit repetition. Paste the repeated section in full, as many times as it is sung.",
    lyricWarnBis: "\"(bis)\" marker found — replace it with the repetition written out in full.",
    lyricWarnSection: "Section line like \"[Chorus]\"/\"[Verse]\" found — remove it; the lyrics should contain only the sung text.",
    lyricWarnLrc: ".lrc timestamps found (\"[00:12]\") — paste plain lyrics without timing marks; USKMaker does the syncing itself.",

    titleLabel: "Title",
    artistLabel: "Artist",
    languageLabel: "Song language",
    langNonLatinHint: "Type the lyrics in this language's native script (e.g. 한국어, 日本語, Cyrillic), not romanized — otherwise recognition won't match the lyrics.",
    bpmLabel: "Manual BPM (optional)",
    bpmPlaceholder: "auto",
    bpmTip: "Leave blank to detect automatically. If filled, the value you type goes into the package exactly as-is.",
    outDirLabel: "Output folder",
    outDirPlaceholder: "No folder selected",
    outDirPick: "Choose folder...",
    outDirHint: "The package will be created in an \"Artist - Title\" subfolder inside the chosen folder.",
    sectionPackage: "Package",
    sectionOptions: "Options",
    sectionNext: "What's next?",
    cleanWorkLabel: "Remove intermediate files when done",
    cleanWorkHint: "Saves space; leave unchecked to reprocess faster.",
    cleanExtrasLabel: "Essentials only (deletes .lrc/.log/.json) ⚠",
    cleanExtrasHint: "Deletes the helper files (.lrc, .log, .json) and song_data.json at the end of the queue — packages will have NO review screen. Leave unchecked if you want to review later.",
    withStemsLabel: "Separate vocal + instrumental tracks",
    withStemsHint: "Lets the game control the guide vocal's volume separately from the instrumental (turn it up to learn, off to sing solo). Makes the package almost 3x bigger. The separation happens anyway — this just includes it.",
    duetLabel: "Duet (two voices)",
    duetHint: "Tick this to make a duet. In the lyrics, start each singer's lines with a tag: \"P1: ...\", \"P2: ...\", or \"P1&P2: ...\" when they sing together. A line with no tag stays with the previous singer. The package comes out in duet format (#P1/#P2, P1/P2 blocks, [DUET] suffix).",
    backtrackLabel: "Backtrack (instrumental only)",
    backtrackHint: "The package audio keeps only the instrumental (no guide vocal) — pure karaoke, you sing over it. Uses the vocal separation the app already does; quality depends on it and some vocal residue may remain. Alignment and notes are unchanged.",

    valNeedYoutube: "Enter the YouTube link.",
    valNeedFile: "Select a local audio/video file.",
    valNeedLyrics: "Paste the song lyrics.",
    valNeedTitle: "Enter the title.",
    valNeedArtist: "Enter the artist.",
    valNeedOutDir: "Choose the output folder.",

    generate: "Generate UltraStar package",
    generateQueue: "Generate queue ({n})",
    queueAdd: "+ Add to queue",
    queueHeader: "Queue ({n})",
    queueStatusPending: "queued",
    queueStatusRunning: "generating...",
    queueStatusDone: "done",
    queueStatusError: "error",
    queueStatusCancelled: "cancelled",
    queueRemove: "Remove",
    queueReview: "Review",
    reviewUnavailableCleaned: "Review unavailable: the helper files (song_data.json) were deleted for this package.",
    queueOpen: "Open folder",
    queueClearDone: "Clear completed",
    clearFields: "Clear fields",
    clearConfirm: "Clear all fields? The lyrics you typed will be lost.",
    generating: "Generating... ({time})",
    cancel: "Cancel",
    cancelling: "Cancelling...",
    cancelledInfo: "Generation cancelled. Partial files were kept in the output folder and will be reused if you generate again with the same folder.",
    windowGenerating: "USKMaker — Generating: {song}",
    notifDoneOne: "✓ Done: {song}",
    notifFailOne: "✗ Failed: {song}",
    notifDoneQueue: "✓ Queue finished — {ok} ok, {fail} failed",
    reviewNoPackage: "No package found in that folder (no song_data.json, no chart .txt). Select an UltraStar package folder.",
    reviewOurs: "Package generated by USKMaker.",
    reviewThirdParty: "Package from another source (read from the .txt). You can download the missing extras; note editing is only for packages generated here.",
    assetCover: "Cover",
    assetBg: "Background",
    assetVideo: "Video",
    assetDownloadMissing: "Download what's missing: {list}",
    assetDownloading: "Downloading…",
    assetGot: "Downloaded: {got}.",
    assetNone: "Nothing found to download.",
    assetEditNotes: "Edit notes",
    step1: "Get audio",
    step1Hint: "seconds (file) · ~1 min (YouTube)",
    step2: "Separate vocals from instrumental",
    step2Hint: "~1–3 min on GPU, the longest step",
    step3: "Detect BPM",
    step3Hint: "seconds",
    step4: "Align lyrics to audio",
    step4Hint: "~1–2 min",
    step5: "Fetch cover, year and genre",
    step5Hint: "seconds",
    step6: "Extract pitch and build the package",
    step6Hint: "~1 min",
    logDetails: "Technical details ({n} log lines)",
    errorPrefix: "Error:",
    unknownError: "Unknown error while running the pipeline.",

    resultSuccess: "Package generated successfully!",
    resultNotesMeasured: "{n} notes measured from audio",
    resultNotesEstimated: " · {n} estimated — worth reviewing",
    resultAlignFailed:
      "{pct}% of the notes are guesses: the app couldn't make out the singing in this song, " +
      "so the package is probably out of sync. Worth generating this song again: the vocal " +
      "separation varies between attempts, and a second try usually works. If it happens again, " +
      "check that the lyrics match this recording (live versions, remixes and a chorus written " +
      "only once all cause it).",
    resultLowRecall:
      "The app only recognized {pct}% of the lyrics in the song — it may have heard something " +
      "else and placed the notes in the wrong spots. Worth checking the sync; if it's off, generate " +
      "again (the vocal separation varies between attempts) and check the lyrics match this recording.",
    resultReview: "Review alignment",
    resultReviewHint: "This is the best way to fix specific parts: you adjust the notes without generating again, so you fix only the bad bit without touching what came out good.",
    resultOpenFolder: "Open folder",
    resultRegen: "Generate again",
    resultRegenHint: "Generates this same song again, without retyping. Vocal separation varies each attempt — if it came out bad, the next one usually improves. To fix specific parts, prefer Review.",
    resultNewSong: "New song",

    revTitle: "Review",
    revLoading: "Loading package...",
    revBack: "Back",
    revClose: "Close",
    revSave: "Save (.txt + JSON)",
    revSaving: "Saving...",
    revPlay: "▶ Play",
    revPause: "⏸ Pause",
    revToStart: "Back to start",
    revListenMix: "Listen: full mix",
    revListenVocals: "Listen: vocals only",
    revListenTitle: "Which audio to hear while reviewing",
    revGap: "GAP (ms)",
    revGapStepTitle: "Shifts the whole song in time",
    revUndo: "↶ Undo",
    revRedo: "↷ Redo",
    revNextFlagged: "⚠ Next flagged ({n})",
    revNextFlaggedTitle: "Selects and centers the next estimated or suspicious-score note (not confidently measured from audio)",
    revMinimapTitle: "Song overview — click to navigate; orange/red ticks = estimated/suspicious notes",
    revHints: "Drag note: move in time/pitch · right edge: duration · double-click/Enter: play the note · arrows: fine-tune (Shift+←→: duration · Alt+←→: whole phrase) · Del: delete · wheel: scroll · Ctrl+wheel: zoom · Space: play/pause",
    revLegendTiming: "Timing:",
    revLegendAnchor: "measured (exact)",
    revLegendFuzzy: "measured (spelling≈)",
    revLegendRealign: "measured (2nd pass)",
    revLegendInterp: "estimated — check",
    revLegendLowScore: "measured, low score — check",
    revLegendLrc: "line start (.lrc)",
    revLegendGolden: "golden",
    revLegendFreestyle: "freestyle",
    revSyllable: "Syllable",
    revStartBeat: "Start (beat)",
    revDuration: "Duration (beats)",
    revPitch: "Pitch",
    revType: "Type",
    revTypeNormal: "Normal",
    revTypeGolden: "Golden",
    revTypeFreestyle: "Freestyle",
    revPhraseBreak: "Phrase break after this note",
    revNoteTime: "{start}s · {dur}s long",
    revDeleteNote: "Delete note",
    revSourceAnchor: "measured (exact match)",
    revSourceFuzzy: "measured (approximate spelling)",
    revSourceRealign: "measured (2nd pass in window)",
    revSourceInterp: "ESTIMATED (interpolated) — check",
    revSourceLrc: "line start (synced .lrc)",
    revSaved: "Saved: {path}",
    revWarnings: "Validation warnings:",
    revNoAudio: "The package's audio file was not found — the timeline works, but without playback.",
    revLoadError: "Error loading the package.",
    revSaveError: "Error while saving.",
    revConfirmDiscard: "There are unsaved changes. Leave anyway and discard them?",
    revNoText: "(no text)",
  },
} as const;

export type StrKey = keyof (typeof STRINGS)["pt"];

const LANG_KEY = "uskmaker-ui-lang";

function detectLang(): Lang {
  const saved = localStorage.getItem(LANG_KEY);
  if (saved === "pt" || saved === "en") return saved;
  return navigator.language?.toLowerCase().startsWith("pt") ? "pt" : "en";
}

interface I18nValue {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: StrKey, vars?: Record<string, string | number>) => string;
}

const I18nContext = createContext<I18nValue | null>(null);

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>(detectLang);

  useEffect(() => {
    localStorage.setItem(LANG_KEY, lang);
  }, [lang]);

  const t = (key: StrKey, vars?: Record<string, string | number>): string => {
    let s: string = STRINGS[lang][key] ?? STRINGS.pt[key] ?? key;
    if (vars) {
      for (const [k, v] of Object.entries(vars)) {
        s = s.split(`{${k}}`).join(String(v));
      }
    }
    return s;
  };

  return <I18nContext.Provider value={{ lang, setLang: setLangState, t }}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n fora do I18nProvider");
  return ctx;
}

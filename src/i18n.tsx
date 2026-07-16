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
    withVideoLabel: "Incluir o vídeo no pacote (fundo animado no jogo — download maior e mais lento)",
    fileLabel: "Arquivo de áudio/vídeo",
    filePlaceholder: "Nenhum arquivo selecionado",
    browse: "Procurar...",
    bgVideoLabel: "Baixar videoclipe do YouTube para o fundo (o áudio continua sendo o seu arquivo; sem vídeo disponível, fica só a capa)",
    bgVideoUrlPlaceholder: "Link do videoclipe (opcional — em branco, busca automática por artista + título)",
    fileFilterName: "Áudio/Vídeo",

    // ---- letra ----
    lyricsLabel: "Letra da música (uma linha por frase cantada) — repita refrões por extenso, tantas vezes quanto forem cantados",
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
    langPt: "Português",
    langEn: "Inglês",
    langEs: "Espanhol",
    bpmLabel: "BPM manual (opcional)",
    bpmPlaceholder: "Deixe em branco para detectar automaticamente",
    outDirLabel: "Pasta de saída",
    outDirPlaceholder: "Nenhuma pasta selecionada",
    outDirPick: "Escolher pasta...",
    outDirHint: "O pacote será criado numa subpasta \"Artista - Título\" dentro da pasta escolhida.",
    cleanWorkLabel: "Remover arquivos intermediários ao final (economiza espaço; deixe desmarcado para reprocessar mais rápido)",
    cleanExtrasLabel: "Deixar só o essencial: apagar os auxiliares (.lrc, .log, .json) ao final da fila",
    cleanExtrasHint: "Remove também o song_data.json — os pacotes ficarão SEM a tela de revisão. Deixe desmarcado se quiser revisar depois.",
    withStemsLabel: "Incluir faixas separadas de voz e instrumental no pacote",
    withStemsHint: "Permite ao jogo controlar o volume da voz-guia separado do instrumental (subir para aprender, zerar para cantar sozinho). O pacote fica quase 3x maior. A separação já é feita de qualquer jeito — isto só a inclui no pacote.",

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
    resultReview: "Revisar alinhamento",
    resultOpenFolder: "Abrir pasta",
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
    withVideoLabel: "Include the video in the package (animated background in game — bigger, slower download)",
    fileLabel: "Audio/video file",
    filePlaceholder: "No file selected",
    browse: "Browse...",
    bgVideoLabel: "Download a YouTube music video for the background (your file remains the audio; if no video is found, the cover is used)",
    bgVideoUrlPlaceholder: "Music video link (optional — leave blank for automatic search by artist + title)",
    fileFilterName: "Audio/Video",

    lyricsLabel: "Song lyrics (one line per sung phrase) — write repeated choruses out in full, as many times as they are sung",
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
    langPt: "Portuguese",
    langEn: "English",
    langEs: "Spanish",
    bpmLabel: "Manual BPM (optional)",
    bpmPlaceholder: "Leave blank to detect automatically",
    outDirLabel: "Output folder",
    outDirPlaceholder: "No folder selected",
    outDirPick: "Choose folder...",
    outDirHint: "The package will be created in an \"Artist - Title\" subfolder inside the chosen folder.",
    cleanWorkLabel: "Remove intermediate files when done (saves space; leave unchecked to reprocess faster)",
    cleanExtrasLabel: "Keep only the essentials: delete the helper files (.lrc, .log, .json) at the end of the queue",
    cleanExtrasHint: "This also removes song_data.json — packages will have NO review screen. Leave unchecked if you want to review later.",
    withStemsLabel: "Include separate vocal and instrumental tracks in the package",
    withStemsHint: "Lets the game control the guide vocal's volume separately from the instrumental (turn it up to learn, off to sing solo). Makes the package almost 3x bigger. The separation happens anyway — this just includes it.",

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
    resultReview: "Review alignment",
    resultOpenFolder: "Open folder",
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

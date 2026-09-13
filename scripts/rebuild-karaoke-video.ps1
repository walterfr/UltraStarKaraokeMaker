# rebuild-karaoke-video.ps1
#
# Refaz o vídeo de karaokê (.mp4) de UMA música já gerada, usando os tempos
# ATUAIS do song_data.json daquela pasta. Não roda IA nenhuma.
#
# PARA QUE SERVE: a tela de Revisão de Alinhamento salva as correções no
# song_data.json e reescreve o .txt - mas não mexe no .mp4, que fica com os
# tempos antigos. Este script aplica as correções ao vídeo em segundos, em vez
# de reprocessar a música inteira (Demucs + WhisperX) por causa de um ajuste.
#
# COMO USAR (três formas, todas equivalentes):
#   1. Arraste a PASTA da música para cima deste arquivo no Explorador.
#   2. Clique com o botão direito -> "Executar com o PowerShell" e cole o
#      caminho da pasta quando ele pedir.
#   3. Pelo terminal:  .\rebuild-karaoke-video.ps1 -SongDir "C:\Karaoke\Artista - Titulo"
#
# O app instalado tem o mesmo código; este script existe para quem quer rodar
# sem esperar uma versão nova do instalador.
#
# BILÍNGUE (PT-BR/EN), igual à interface do app: o USKMaker detecta o idioma
# do sistema e fala com o usuário na língua dele. Um script auxiliar que fala
# só português deixa metade dos usuários olhando para uma pergunta que não
# entende - foi exatamente o que aconteceu num uso real (02/09/2026), com um
# usuário de língua inglesa travado no prompt do caminho da pasta.
# Comentários seguem em português (convenção do repositório); o que o USUÁRIO
# lê é que precisa dos dois idiomas.

param([string]$SongDir)

$ErrorActionPreference = "Stop"

# Idioma da INTERFACE do Windows (não o formato de data/número, que é outra
# coisa e engana: muita gente usa Windows em inglês com região BR).
$culture = (Get-UICulture).Name
$isPT = $culture -like "pt*"

$T = if ($isPT) {
    @{
        AskPath   = "Cole o caminho da pasta da musica (a que tem o song_data.json)"
        NoFolder  = "Nao achei a pasta: {0}"
        NoJson    = @"
Essa pasta nao tem song_data.json, entao nao da pra refazer o video
(esse arquivo e quem guarda os tempos das silabas).

Se voce marcou "manter apenas o essencial" na geracao, ele foi apagado -
nesse caso a musica precisa ser gerada de novo.
"@
        NoPython  = "Nao achei o Python do USKMaker em {0}. Rode 'Configurar ambiente de IA' no app primeiro."
        NoCode    = "Nao achei o codigo do sidecar (pipeline\video_export.py)."
        Working   = "Refazendo o video de karaoke..."
        LblSong   = "  musica : {0}"
        LblCode   = "  codigo : {0}"
        Done      = "Pronto. O .mp4 da pasta foi refeito com os tempos atuais."
        Failed    = "Falhou (codigo {0}). A mensagem acima diz o motivo."
        ErrLabel  = "ERRO: {0}"
        Bye       = "Enter para fechar"
    }
} else {
    @{
        AskPath   = "Paste the path to the song folder (the one with song_data.json)"
        NoFolder  = "Folder not found: {0}"
        NoJson    = @"
That folder has no song_data.json, so the video cannot be rebuilt
(that file is what holds the syllable timings).

If you ticked "keep only the essentials" when generating, it was deleted -
in that case the song has to be generated again.
"@
        NoPython  = "Could not find the USKMaker Python at {0}. Run 'Set up AI environment' in the app first."
        NoCode    = "Could not find the sidecar code (pipeline\video_export.py)."
        Working   = "Rebuilding the karaoke video..."
        LblSong   = "  song : {0}"
        LblCode   = "  code : {0}"
        Done      = "Done. The .mp4 in that folder was rebuilt with the current timings."
        Failed    = "Failed (exit code {0}). The message above says why."
        ErrLabel  = "ERROR: {0}"
        Bye       = "Press Enter to close"
    }
}

function Fail($msg) {
    Write-Host ""
    Write-Host ($T.ErrLabel -f $msg) -ForegroundColor Red
    Write-Host ""
    Read-Host $T.Bye | Out-Null
    exit 1
}

if (-not $SongDir) { $SongDir = Read-Host $T.AskPath }
# Aspas coladas junto ao caminho são o erro mais comum de quem copia do
# Explorador - tirar aqui evita uma falha boba e confusa.
$SongDir = $SongDir.Trim().Trim('"')

if (-not (Test-Path -LiteralPath $SongDir -PathType Container)) {
    Fail ($T.NoFolder -f $SongDir)
}
if (-not (Test-Path -LiteralPath (Join-Path $SongDir "song_data.json"))) {
    Fail $T.NoJson
}

# O Python do ambiente de IA do USKMaker: e ele que tem as bibliotecas.
$venvPython = Join-Path $env:LOCALAPPDATA "USKMaker\venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    Fail ($T.NoPython -f $venvPython)
}

# O ffmpeg EMBUTIDO. Fora do app a variavel nao vem definida, e o modulo cairia
# no "ffmpeg" do PATH - que a maioria das maquinas nao tem, porque o ponto do
# ffmpeg embutido e justamente nao exigir isso.
$bundledFfmpeg = Join-Path $env:LOCALAPPDATA "USKMaker\bin\ffmpeg.exe"
if (Test-Path -LiteralPath $bundledFfmpeg) { $env:USKMAKER_FFMPEG = $bundledFfmpeg }

# O codigo do sidecar: preferir o que esta ao lado deste script (pasta do
# repositorio / instalacao), e so entao a copia instalada.
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$candidates = @(
    (Join-Path (Split-Path -Parent $scriptDir) "python-sidecar"),
    (Join-Path $scriptDir "python-sidecar"),
    (Join-Path ${env:ProgramFiles} "USKMaker\_up_\python-sidecar")
)
$codeDir = $candidates | Where-Object { Test-Path -LiteralPath (Join-Path $_ "pipeline\video_export.py") } | Select-Object -First 1
if (-not $codeDir) { Fail $T.NoCode }

Write-Host ""
Write-Host $T.Working -ForegroundColor Cyan
Write-Host ($T.LblSong -f $SongDir)
Write-Host ($T.LblCode -f $codeDir)
Write-Host ""

Push-Location $codeDir
try {
    & $venvPython -m pipeline.video_export --dir $SongDir
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}

Write-Host ""
if ($code -eq 0) {
    Write-Host $T.Done -ForegroundColor Green
} else {
    Write-Host ($T.Failed -f $code) -ForegroundColor Red
}
Write-Host ""
Read-Host $T.Bye | Out-Null

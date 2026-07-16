# USKMaker - setup do ambiente de IA (rode uma vez apos instalar o app)
#
# Pode ser disparado de duas formas:
#   - pelo BOTAO "Configurar ambiente de IA" dentro do app (passa -Unattended);
#   - manualmente: clique-direito > "Executar com PowerShell", ou
#     powershell -ExecutionPolicy Bypass -File .\setup-sidecar.ps1
#
# O que faz (NAO exige Python instalado - o uv cuida disso):
#   1. Baixa o uv (gerenciador de Python/pacotes da Astral) para o bin
#   2. Detecta GPU NVIDIA (via nvidia-smi) para escolher o build do torch
#   3. Cria o venv em %LOCALAPPDATA%\USKMaker\venv com Python 3.12 (o uv baixa
#      um Python gerenciado se nao houver 3.12 na maquina)
#   4. Baixa um ffmpeg embutido (com libvorbis) para %LOCALAPPDATA%\USKMaker\bin
#   5. Instala as dependencias do pipeline (torch + requirements) via uv
#   6. Valida a instalacao
#
# Tudo fica em %LOCALAPPDATA%\USKMaker (fora de Program Files, que e
# somente-leitura para usuarios comuns).

param([switch]$Unattended)

$ErrorActionPreference = "Stop"

function Write-Step($msg)  { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Warn2($msg) { Write-Host "    [AVISO] $msg" -ForegroundColor Yellow }
function Pause-IfInteractive { if (-not $Unattended) { Read-Host "`nPressione Enter para sair" } }
function Fail($msg)        { Write-Host "`n[ERRO] $msg" -ForegroundColor Red; Pause-IfInteractive; exit 1 }

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host " USKMaker - configuracao do ambiente de IA " -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan

$uskDir = Join-Path $env:LOCALAPPDATA "USKMaker"
$binDir = Join-Path $uskDir "bin"
$venvDir = Join-Path $uskDir "venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"

# ---------------------------------------------------------------------------
# 1. Localizar o codigo do sidecar (instalado junto com o app, como resource)
# ---------------------------------------------------------------------------
Write-Step "Localizando o codigo do sidecar"

# O script fica em .../scripts/ e o python-sidecar e PASTA IRMA (quando
# distribuido via instalador Tauri, ambos ficam sob resources/_up_/).
#
# IMPORTANTE: quando o app dispara o setup, ele passa o caminho deste script no
# formato "extended-length" (\\?\C:\...) - o resource_dir() do Tauri devolve
# assim no Windows. Esse prefixo QUEBRA o Split-Path/Join-Path no Windows
# PowerShell 5.1 ("Nao existe uma unidade..." / "o valor do argumento 'drive'
# e nulo"). Normalizamos removendo o prefixo antes de qualquer conta de caminho.
$scriptFullPath = if ($PSCommandPath) { $PSCommandPath } else { $MyInvocation.MyCommand.Path }
if ($scriptFullPath) {
    if ($scriptFullPath.StartsWith('\\?\UNC\')) {
        $scriptFullPath = '\\' + $scriptFullPath.Substring(8)
    } elseif ($scriptFullPath.StartsWith('\\?\')) {
        $scriptFullPath = $scriptFullPath.Substring(4)
    }
}
$scriptDir  = Split-Path -Parent $scriptFullPath
$candidatesLocal = @(
    (Join-Path (Split-Path -Parent $scriptDir) "python-sidecar"),  # irmao (instalado)
    (Join-Path $scriptDir "python-sidecar")                         # filho (fallback)
)
$sidecarDir = $candidatesLocal | Where-Object { Test-Path (Join-Path $_ "requirements.txt") } | Select-Object -First 1

if (-not $sidecarDir) {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\uskmaker\python-sidecar"),
        (Join-Path ${env:ProgramFiles} "uskmaker\python-sidecar")
    )
    $sidecarDir = $candidates | Where-Object { Test-Path (Join-Path $_ "requirements.txt") } | Select-Object -First 1
    if (-not $sidecarDir) {
        Fail "Nao encontrei a pasta python-sidecar. Execute este script a partir da pasta de instalacao do USKMaker."
    }
}
Write-Ok "Sidecar em: $sidecarDir"

# ---------------------------------------------------------------------------
# 1b. Git e OBRIGATORIO: o whisperx e instalado de "git+https://..."
# (requirements.txt), entao sem o git o passo de dependencias falha. Checamos
# AQUI, antes de baixar ~2 GB de torch, pra falhar rapido e com instrucao clara
# (caso real reportado em 16/07/2026: o setup morria no meio sem dizer por que).
# ---------------------------------------------------------------------------
Write-Step "Verificando o Git (necessario para instalar o whisperx)"
$gitOk = $null -ne (Get-Command git -ErrorAction SilentlyContinue)
if (-not $gitOk) {
    Fail @"
O Git nao esta instalado (ou nao esta no PATH).

O USKMaker instala o whisperx direto do repositorio dele, entao o Git e
obrigatorio para configurar o ambiente de IA.

O que fazer:
  1. Instale o Git: https://git-scm.com/download/win  (as opcoes padrao servem)
  2. FECHE e abra o app/terminal de novo (pro PATH atualizar)
  3. Rode 'Configurar ambiente de IA' outra vez
"@
}
Write-Ok "Git encontrado: $((git --version) 2>&1)"

New-Item -ItemType Directory -Force -Path $binDir | Out-Null

# ---------------------------------------------------------------------------
# 2. Baixar o uv (nao exige Python previo - ele mesmo instala o Python 3.12)
# ---------------------------------------------------------------------------
Write-Step "Configurando o uv (gerenciador de Python/pacotes)"

$uvExe = Join-Path $binDir "uv.exe"
if (Test-Path $uvExe) {
    Write-Ok "uv ja existe em $binDir"
} else {
    try {
        $uvZipUrl   = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"
        $uvZip      = Join-Path $env:TEMP "uskmaker-uv.zip"
        $uvExtract  = Join-Path $env:TEMP "uskmaker-uv-extract"
        Write-Host "    Baixando uv..."
        Invoke-WebRequest -Uri $uvZipUrl -OutFile $uvZip -UseBasicParsing
        if (Test-Path $uvExtract) { Remove-Item -Recurse -Force $uvExtract }
        Expand-Archive -Path $uvZip -DestinationPath $uvExtract -Force
        $srcUv = Get-ChildItem -Path $uvExtract -Recurse -Filter "uv.exe" | Select-Object -First 1
        if (-not $srcUv) { throw "uv.exe nao encontrado no zip baixado." }
        Copy-Item $srcUv.FullName $uvExe -Force
        Remove-Item $uvZip -Force -ErrorAction SilentlyContinue
        Remove-Item -Recurse -Force $uvExtract -ErrorAction SilentlyContinue
        Write-Ok "uv instalado em $binDir"
    } catch {
        Fail "Falha ao baixar o uv: $($_.Exception.Message)"
    }
}

# ---------------------------------------------------------------------------
# 3. Detectar GPU NVIDIA (escolhe o build do torch: CUDA cu126 ou CPU)
# ---------------------------------------------------------------------------
Write-Step "Detectando GPU NVIDIA"

$hasNvidia = $false
try {
    $null = & nvidia-smi 2>$null
    if ($LASTEXITCODE -eq 0) { $hasNvidia = $true }
} catch { }

if ($hasNvidia) {
    Write-Ok "GPU NVIDIA detectada - torch com CUDA (cu126)."
    $torchIndex = "https://download.pytorch.org/whl/cu126"
} else {
    Write-Warn2 "Nenhuma GPU NVIDIA detectada - torch CPU (funciona, mas ~10 min por musica)."
    $torchIndex = "https://download.pytorch.org/whl/cpu"
}

# ---------------------------------------------------------------------------
# 4. Criar o venv com Python 3.12 (o uv baixa o Python se necessario)
# ---------------------------------------------------------------------------
Write-Step "Criando o ambiente virtual (Python 3.12 via uv)"

if (Test-Path $venvPython) {
    Write-Warn2 "Ja existe um venv em $venvDir - sera reutilizado."
} else {
    & $uvExe venv --python 3.12 "$venvDir"
    if ($LASTEXITCODE -ne 0) { Fail "Falha ao criar o venv com uv." }
    Write-Ok "venv criado em: $venvDir"
}

# ---------------------------------------------------------------------------
# 5. ffmpeg embutido (com libvorbis) em %LOCALAPPDATA%\USKMaker\bin
#     Remove a exigencia de ter o ffmpeg no PATH do sistema.
# ---------------------------------------------------------------------------
Write-Step "Configurando o ffmpeg embutido"

$ffmpegExe = Join-Path $binDir "ffmpeg.exe"
if (Test-Path $ffmpegExe) {
    Write-Ok "ffmpeg embutido ja existe em $binDir"
} else {
    try {
        $zipUrl     = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
        $zipPath    = Join-Path $env:TEMP "uskmaker-ffmpeg.zip"
        $extractDir = Join-Path $env:TEMP "uskmaker-ffmpeg-extract"
        Write-Host "    Baixando ffmpeg (~90 MB)..."
        Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing
        if (Test-Path $extractDir) { Remove-Item -Recurse -Force $extractDir }
        Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force
        $srcFfmpeg = Get-ChildItem -Path $extractDir -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
        if (-not $srcFfmpeg) { throw "ffmpeg.exe nao encontrado no zip baixado." }
        $srcDir = $srcFfmpeg.DirectoryName
        Copy-Item (Join-Path $srcDir "ffmpeg.exe")  $ffmpegExe -Force
        $srcProbe = Join-Path $srcDir "ffprobe.exe"
        if (Test-Path $srcProbe) { Copy-Item $srcProbe (Join-Path $binDir "ffprobe.exe") -Force }
        Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
        Remove-Item -Recurse -Force $extractDir -ErrorAction SilentlyContinue
        Write-Ok "ffmpeg embutido instalado em $binDir"
    } catch {
        Write-Warn2 "Falha ao baixar o ffmpeg embutido: $($_.Exception.Message)"
        Write-Warn2 "O app ainda funciona se voce tiver o ffmpeg (com libvorbis) no PATH."
    }
}

# ---------------------------------------------------------------------------
# 6. Instalar dependencias via uv (o passo demorado - downloads grandes)
# ---------------------------------------------------------------------------
Write-Step "Instalando torch ($(if ($hasNvidia) {'CUDA cu126'} else {'CPU'})) - pode demorar varios minutos"
& $uvExe pip install --python "$venvPython" torch torchaudio torchvision --index-url $torchIndex
if ($LASTEXITCODE -ne 0) { Fail "Falha ao instalar o torch." }

Write-Step "Instalando as demais dependencias do pipeline"
& $uvExe pip install --python "$venvPython" -r (Join-Path $sidecarDir "requirements.txt")
if ($LASTEXITCODE -ne 0) { Fail "Falha ao instalar as dependencias (requirements.txt)." }

# O extra [gpu]/[cpu] traz o onnxruntime, que o audio-separator importa no
# topo do modulo mas NAO declara como dependencia base - sem ele o resgate
# de voz principal falha silenciosamente (cai sempre pro stem do Demucs).
$sepExtra = if ($hasNvidia) { 'gpu' } else { 'cpu' }
Write-Step "Instalando onnxruntime para o audio-separator (extra [$sepExtra])"
& $uvExe pip install --python "$venvPython" "audio-separator[$sepExtra]>=0.44.0"
if ($LASTEXITCODE -ne 0) { Fail "Falha ao instalar audio-separator[$sepExtra] (onnxruntime)." }

# ---------------------------------------------------------------------------
# 7. Validacao final
# ---------------------------------------------------------------------------
Write-Step "Validando a instalacao"

$cudaCheck = & $venvPython -c "import torch; print(torch.cuda.is_available())"
if ($hasNvidia -and $cudaCheck.Trim() -ne "True") {
    Write-Warn2 "GPU NVIDIA detectada mas o torch nao esta enxergando CUDA (verifique o driver)."
} else {
    Write-Ok "torch instalado (CUDA disponivel: $($cudaCheck.Trim()))"
}

& $venvPython -c "import whisperx, demucs, librosa, mutagen, audio_separator.separator" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Ok "Bibliotecas do pipeline importadas com sucesso."
} else {
    # FALHA (nao aviso): sem estas bibliotecas o app NAO gera - o sidecar morre
    # no import, antes de conseguir escrever qualquer log. Terminar aqui com
    # banner verde foi exatamente o que confundiu um usuario (16/07/2026).
    Fail @"
Alguma biblioteca do pipeline nao importou - o ambiente NAO esta pronto.

Rode este setup de novo. Se persistir, confira se o Git esta instalado
(https://git-scm.com/download/win) e abra uma issue com o log acima.
"@
}

Write-Host "`n=============================================" -ForegroundColor Green
Write-Host " Configuracao concluida! Pode usar o USKMaker." -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Green
Write-Host " Na primeira musica, os modelos de IA (Demucs/Whisper)"
Write-Host " serao baixados automaticamente (~2 GB, so na primeira vez)."
Pause-IfInteractive

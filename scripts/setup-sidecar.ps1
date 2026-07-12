# USKMaker - setup do sidecar Python (executar uma unica vez apos instalar o app)
#
# O que este script faz:
#   1. Verifica se o Python 3.12 esta instalado (orienta a instalacao se nao)
#   2. Detecta GPU NVIDIA (via nvidia-smi) para escolher o build certo do torch
#   3. Cria um ambiente virtual em %LOCALAPPDATA%\USKMaker\venv
#   4. Baixa um ffmpeg embutido (com libvorbis) para %LOCALAPPDATA%\USKMaker\bin
#      - assim o usuario NAO precisa mais por o ffmpeg no PATH manualmente
#   5. Instala todas as dependencias do pipeline de IA
#   6. Valida a instalacao (incluindo CUDA, se aplicavel)
#
# Uso:  clique-direito > "Executar com PowerShell", ou:
#   powershell -ExecutionPolicy Bypass -File .\setup-sidecar.ps1
#
# O venv fica em LOCALAPPDATA (nao em Program Files) porque a pasta de
# instalacao do app e somente-leitura para usuarios comuns - o venv precisa
# de escrita (pip, cache de modelos, etc).

$ErrorActionPreference = "Stop"

function Write-Step($msg)  { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Warn2($msg) { Write-Host "    [AVISO] $msg" -ForegroundColor Yellow }
function Fail($msg)        { Write-Host "`n[ERRO] $msg" -ForegroundColor Red; Read-Host "Pressione Enter para sair"; exit 1 }

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host " USKMaker - configuracao do ambiente de IA " -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan

# ---------------------------------------------------------------------------
# 1. Localizar o codigo do sidecar (instalado junto com o app, como resource)
# ---------------------------------------------------------------------------
Write-Step "Localizando o codigo do sidecar"

# O script fica em .../scripts/ e o python-sidecar e PASTA IRMA (quando
# distribuido via instalador Tauri, ambos ficam sob resources/_up_/).
$scriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$candidatesLocal = @(
    (Join-Path (Split-Path -Parent $scriptDir) "python-sidecar"),  # irmao (instalado)
    (Join-Path $scriptDir "python-sidecar")                         # filho (fallback)
)
$sidecarDir = $candidatesLocal | Where-Object { Test-Path (Join-Path $_ "requirements.txt") } | Select-Object -First 1

if (-not $sidecarDir) {
    # fallback: procurar na pasta de instalacao padrao do app
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
# 2. Verificar Python 3.12
# ---------------------------------------------------------------------------
Write-Step "Verificando Python 3.12"

$pythonExe = $null
foreach ($cand in @("py -3.12", "python")) {
    try {
        $ver = Invoke-Expression "$cand --version 2>&1"
        if ($ver -match "Python 3\.12\.") { $pythonExe = $cand; break }
    } catch { }
}

if (-not $pythonExe) {
    Write-Warn2 "Python 3.12 nao encontrado."
    Write-Host  "    Baixe e instale em: https://www.python.org/downloads/"
    Write-Host  "    (marque 'Add python.exe to PATH' na instalacao)"
    Fail "Instale o Python 3.12 e rode este script novamente."
}
Write-Ok "Python 3.12 encontrado ($pythonExe)"

# ---------------------------------------------------------------------------
# 3. Detectar GPU NVIDIA
# ---------------------------------------------------------------------------
Write-Step "Detectando GPU NVIDIA"

$hasNvidia = $false
try {
    $null = & nvidia-smi 2>$null
    if ($LASTEXITCODE -eq 0) { $hasNvidia = $true }
} catch { }

if ($hasNvidia) {
    Write-Ok "GPU NVIDIA detectada - sera instalado o torch com CUDA (cu126)."
    $torchIndex = "https://download.pytorch.org/whl/cu126"
} else {
    Write-Warn2 "Nenhuma GPU NVIDIA detectada - sera instalado o torch CPU."
    Write-Warn2 "O processamento funciona, mas e bem mais lento (~10 min por musica)."
    $torchIndex = "https://download.pytorch.org/whl/cpu"
}

# ---------------------------------------------------------------------------
# 4. Criar venv em %LOCALAPPDATA%\USKMaker\venv
# ---------------------------------------------------------------------------
Write-Step "Criando ambiente virtual"

$venvDir = Join-Path $env:LOCALAPPDATA "USKMaker\venv"
if (Test-Path (Join-Path $venvDir "Scripts\python.exe")) {
    Write-Warn2 "Ja existe um venv em $venvDir - sera reutilizado."
} else {
    New-Item -ItemType Directory -Force -Path (Split-Path $venvDir) | Out-Null
    Invoke-Expression "$pythonExe -m venv `"$venvDir`""
    Write-Ok "venv criado em: $venvDir"
}
$venvPython = Join-Path $venvDir "Scripts\python.exe"

# ---------------------------------------------------------------------------
# 4b. ffmpeg embutido (com libvorbis) em %LOCALAPPDATA%\USKMaker\bin
#     Remove a exigencia de ter o ffmpeg no PATH do sistema. O app aponta para
#     este binario via a env var USKMAKER_FFMPEG (ver resolve_ffmpeg no Rust).
# ---------------------------------------------------------------------------
Write-Step "Configurando o ffmpeg embutido"

$binDir    = Join-Path $env:LOCALAPPDATA "USKMaker\bin"
$ffmpegExe = Join-Path $binDir "ffmpeg.exe"

if (Test-Path $ffmpegExe) {
    Write-Ok "ffmpeg embutido ja existe em $binDir"
} else {
    try {
        New-Item -ItemType Directory -Force -Path $binDir | Out-Null
        # Build estatico "essentials" do gyan.dev - inclui libvorbis (para .ogg).
        $zipUrl     = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
        $zipPath    = Join-Path $env:TEMP "uskmaker-ffmpeg.zip"
        $extractDir = Join-Path $env:TEMP "uskmaker-ffmpeg-extract"
        Write-Host "    Baixando ffmpeg (~90 MB)..."
        Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing
        if (Test-Path $extractDir) { Remove-Item -Recurse -Force $extractDir }
        Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force
        # O zip traz ffmpeg-*-essentials_build\bin\{ffmpeg,ffprobe}.exe
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
        Write-Warn2 "O app ainda funciona se voce tiver o ffmpeg (com libvorbis) no PATH do sistema."
    }
}

# ---------------------------------------------------------------------------
# 5. Instalar dependencias (o passo demorado - downloads grandes)
# ---------------------------------------------------------------------------
Write-Step "Instalando torch ($(if ($hasNvidia) {'CUDA cu126'} else {'CPU'})) - pode demorar varios minutos"
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install torch torchaudio torchvision --index-url $torchIndex
if ($LASTEXITCODE -ne 0) { Fail "Falha ao instalar o torch." }

Write-Step "Instalando as demais dependencias do pipeline"
& $venvPython -m pip install -r (Join-Path $sidecarDir "requirements.txt")
if ($LASTEXITCODE -ne 0) { Fail "Falha ao instalar as dependencias (requirements.txt)." }

# ---------------------------------------------------------------------------
# 6. Validacao final
# ---------------------------------------------------------------------------
Write-Step "Validando a instalacao"

$cudaCheck = & $venvPython -c "import torch; print(torch.cuda.is_available())"
if ($hasNvidia -and $cudaCheck.Trim() -ne "True") {
    Write-Warn2 "GPU NVIDIA detectada mas o torch nao esta enxergando CUDA."
    Write-Warn2 "Verifique se o driver NVIDIA esta atualizado (nvidia-smi deve funcionar)."
} else {
    Write-Ok "torch instalado (CUDA disponivel: $($cudaCheck.Trim()))"
}

& $venvPython -c "import whisperx, demucs, librosa, mutagen" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Ok "Bibliotecas do pipeline importadas com sucesso."
} else {
    Write-Warn2 "Alguma biblioteca nao importou corretamente - o app pode falhar. Rode o script de novo ou abra uma issue."
}

Write-Host "`n=============================================" -ForegroundColor Green
Write-Host " Configuracao concluida! Pode abrir o USKMaker." -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Green
Write-Host " Na primeira musica, os modelos de IA (Demucs/Whisper)"
Write-Host " serao baixados automaticamente (~2 GB, so na primeira vez)."
Read-Host "`nPressione Enter para sair"

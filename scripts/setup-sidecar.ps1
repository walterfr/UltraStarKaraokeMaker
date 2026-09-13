# USKMaker - AI environment setup (run this once after installing the app)
#
# It can be started in two ways:
#   - from the "Configure AI environment" BUTTON inside the app (passes -Unattended);
#   - by hand: right-click > "Run with PowerShell", or
#     powershell -ExecutionPolicy Bypass -File .\setup-sidecar.ps1
#
# What it does (Python does NOT need to be installed - uv handles that):
#   1. Downloads uv (Astral's Python/package manager) into bin
#   2. Detects an NVIDIA GPU (via nvidia-smi) to choose the torch build
#   3. Creates the venv in %LOCALAPPDATA%\USKMaker\venv with Python 3.12 (uv
#      downloads a managed Python if 3.12 is not on the machine)
#   4. Downloads a bundled ffmpeg (with libvorbis) into %LOCALAPPDATA%\USKMaker\bin
#   5. Installs the pipeline dependencies (torch + requirements) via uv
#   6. Validates the installation
#
# Everything lives in %LOCALAPPDATA%\USKMaker (outside Program Files, which is
# read-only for ordinary users).

param([switch]$Unattended)

$ErrorActionPreference = "Stop"

function Write-Step($msg)  { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Warn2($msg) { Write-Host "    [WARNING] $msg" -ForegroundColor Yellow }
function Pause-IfInteractive { if (-not $Unattended) { Read-Host "`nPress Enter to exit" } }
function Fail($msg)        { Write-Host "`n[ERROR] $msg" -ForegroundColor Red; Pause-IfInteractive; exit 1 }

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host " USKMaker - AI environment setup " -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan

$uskDir = Join-Path $env:LOCALAPPDATA "USKMaker"
$binDir = Join-Path $uskDir "bin"
$venvDir = Join-Path $uskDir "venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"

# ---------------------------------------------------------------------------
# 1. Locate the sidecar code (installed alongside the app, as a resource)
# ---------------------------------------------------------------------------
Write-Step "Locating the sidecar code"

# This script lives in .../scripts/ and python-sidecar is its SIBLING folder
# (when shipped through the Tauri installer, both sit under resources/_up_/).
#
# IMPORTANT: when the app starts the setup, it passes this script's path in
# "extended-length" form (\\?\C:\...) - that is what Tauri's resource_dir()
# returns on Windows. That prefix BREAKS Split-Path/Join-Path on Windows
# PowerShell 5.1 ("Cannot find drive..." / "the 'drive' argument value is
# null"). We normalise it away before doing any path arithmetic.
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
    (Join-Path (Split-Path -Parent $scriptDir) "python-sidecar"),  # sibling (installed)
    (Join-Path $scriptDir "python-sidecar")                         # child (fallback)
)
$sidecarDir = $candidatesLocal | Where-Object { Test-Path (Join-Path $_ "requirements.txt") } | Select-Object -First 1

if (-not $sidecarDir) {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\uskmaker\python-sidecar"),
        (Join-Path ${env:ProgramFiles} "uskmaker\python-sidecar")
    )
    $sidecarDir = $candidates | Where-Object { Test-Path (Join-Path $_ "requirements.txt") } | Select-Object -First 1
    if (-not $sidecarDir) {
        Fail "Could not find the python-sidecar folder. Run this script from the USKMaker installation folder."
    }
}
Write-Ok "Sidecar at: $sidecarDir"

# Resolved once, here, because $sidecarDir has just been proven to contain it
# (that is how it was chosen). Both install steps below feed this same file to
# uv - one as the requirement list, one as the version ceiling - and computing
# it inline in each command made those calls awkward to test.
$reqFile = Join-Path $sidecarDir "requirements.txt"

# NOTE: until 2026-07-16 this script required Git here, because whisperx was
# installed from "git+https://...". It now comes from PyPI (see
# requirements.txt), so the setup no longer depends on Git at all.

New-Item -ItemType Directory -Force -Path $binDir | Out-Null

# ---------------------------------------------------------------------------
# 2. Download uv (needs no pre-existing Python - it installs Python 3.12 itself)
# ---------------------------------------------------------------------------
Write-Step "Setting up uv (Python/package manager)"

$uvExe = Join-Path $binDir "uv.exe"
if (Test-Path $uvExe) {
    Write-Ok "uv already exists in $binDir"
} else {
    try {
        $uvZipUrl   = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"
        $uvZip      = Join-Path $env:TEMP "uskmaker-uv.zip"
        $uvExtract  = Join-Path $env:TEMP "uskmaker-uv-extract"
        Write-Host "    Downloading uv..."
        Invoke-WebRequest -Uri $uvZipUrl -OutFile $uvZip -UseBasicParsing
        if (Test-Path $uvExtract) { Remove-Item -Recurse -Force $uvExtract }
        Expand-Archive -Path $uvZip -DestinationPath $uvExtract -Force
        $srcUv = Get-ChildItem -Path $uvExtract -Recurse -Filter "uv.exe" | Select-Object -First 1
        if (-not $srcUv) { throw "uv.exe was not found inside the downloaded zip." }
        Copy-Item $srcUv.FullName $uvExe -Force
        Remove-Item $uvZip -Force -ErrorAction SilentlyContinue
        Remove-Item -Recurse -Force $uvExtract -ErrorAction SilentlyContinue
        Write-Ok "uv installed in $binDir"
    } catch {
        Fail "Failed to download uv: $($_.Exception.Message)"
    }
}

# ---------------------------------------------------------------------------
# 3. Detect the NVIDIA GPU (picks the torch build: CUDA cu128, cu126 or CPU)
# ---------------------------------------------------------------------------
#
# KNOWING THERE IS an NVIDIA GPU IS NOT ENOUGH - the torch build has to contain
# the kernels for that GPU's GENERATION. Each CUDA build covers a set of
# "compute capabilities" (sm_XX), and a card NEWER than the build simply has no
# code to run.
#
# REAL BUG (reported by an RTX 5080 user, 2026-09-02): Blackwell (the RTX 50
# series, sm_120) only got kernels from CUDA 12.8 onwards. With the fixed cu126
# this script used to install, the user downloaded 2.5 GB of CUDA and the
# pipeline fell back to the CPU anyway - and resolve_device in main.py, which
# compares the real capability against torch.cuda.get_arch_list(), did the
# RIGHT thing (fall back to CPU instead of blowing up with "no kernel image is
# available"), but nobody could understand why the new card went unused.
#
# `nvidia-smi --query-gpu=compute_cap` returns the capability directly (e.g.
# "12.0"), with no guesswork based on the card's marketing name - marketing
# names are not a reliable guide to generation.
#
# The rule is DELIBERATELY CONSERVATIVE: only 12.0 and above switches to cu128.
# An older card follows exactly the same path as before, so this fix cannot
# regress anyone who was already working.
Write-Step "Detecting the NVIDIA GPU"

$hasNvidia = $false
try {
    $null = & nvidia-smi 2>$null
    if ($LASTEXITCODE -eq 0) { $hasNvidia = $true }
} catch { }

if ($hasNvidia) {
    # The card's capability. An old driver may not know the compute_cap field;
    # in that case $computeCap stays empty and we fall back to the previous
    # cu126 - the historical, safe behaviour.
    $computeCap = ""
    try {
        $capRaw = & nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>$null
        if ($LASTEXITCODE -eq 0 -and $capRaw) {
            $computeCap = ($capRaw | Select-Object -First 1).ToString().Trim()
        }
    } catch { }

    $capNumber = 0.0
    if ($computeCap -match '^\d+(\.\d+)?$') {
        $capNumber = [double]::Parse($computeCap, [System.Globalization.CultureInfo]::InvariantCulture)
    }

    if ($capNumber -ge 12.0) {
        Write-Ok "NVIDIA Blackwell GPU or newer detected (compute $computeCap) - torch with CUDA (cu128)."
        $torchIndex = "https://download.pytorch.org/whl/cu128"
    } elseif ($capNumber -gt 0) {
        Write-Ok "NVIDIA GPU detected (compute $computeCap) - torch with CUDA (cu126)."
        $torchIndex = "https://download.pytorch.org/whl/cu126"
    } else {
        Write-Warn2 "NVIDIA GPU detected, but the compute capability could not be read - using cu126 (default)."
        $torchIndex = "https://download.pytorch.org/whl/cu126"
    }
} else {
    Write-Warn2 "No NVIDIA GPU detected - CPU torch (it works, but ~10 min per song)."
    $torchIndex = "https://download.pytorch.org/whl/cpu"
}

# The label shown to the user comes from the CHOSEN INDEX above, not from fixed
# text. The install message used to say "CUDA cu126" even while installing
# cu128 on a Blackwell card - only the label was wrong, the download was
# already correct, but it made the RTX 50 fix look like it had not taken hold.
# Deriving it here means the message and reality cannot disagree.
$torchChannel = ($torchIndex -split '/')[-1]   # cu128 | cu126 | cpu
$torchLabel = if ($torchChannel -eq 'cpu') { 'CPU' } else { "CUDA $torchChannel" }

# ---------------------------------------------------------------------------
# 4. Create the venv with Python 3.12 (uv downloads Python if needed)
# ---------------------------------------------------------------------------
Write-Step "Creating the virtual environment (Python 3.12 via uv)"

if (Test-Path $venvPython) {
    Write-Warn2 "A venv already exists at $venvDir - it will be reused."
} else {
    & $uvExe venv --python 3.12 "$venvDir"
    if ($LASTEXITCODE -ne 0) { Fail "Failed to create the venv with uv." }
    Write-Ok "venv created at: $venvDir"
}

# ---------------------------------------------------------------------------
# 5. Bundled ffmpeg (with libvorbis) in %LOCALAPPDATA%\USKMaker\bin
#     Removes the need to have ffmpeg on the system PATH.
# ---------------------------------------------------------------------------
Write-Step "Setting up the bundled ffmpeg"

$ffmpegExe = Join-Path $binDir "ffmpeg.exe"
if (Test-Path $ffmpegExe) {
    Write-Ok "The bundled ffmpeg already exists in $binDir"
} else {
    try {
        $zipUrl     = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
        $zipPath    = Join-Path $env:TEMP "uskmaker-ffmpeg.zip"
        $extractDir = Join-Path $env:TEMP "uskmaker-ffmpeg-extract"
        Write-Host "    Downloading ffmpeg (~90 MB)..."
        Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing
        if (Test-Path $extractDir) { Remove-Item -Recurse -Force $extractDir }
        Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force
        $srcFfmpeg = Get-ChildItem -Path $extractDir -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
        if (-not $srcFfmpeg) { throw "ffmpeg.exe was not found inside the downloaded zip." }
        $srcDir = $srcFfmpeg.DirectoryName
        Copy-Item (Join-Path $srcDir "ffmpeg.exe")  $ffmpegExe -Force
        $srcProbe = Join-Path $srcDir "ffprobe.exe"
        if (Test-Path $srcProbe) { Copy-Item $srcProbe (Join-Path $binDir "ffprobe.exe") -Force }
        Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
        Remove-Item -Recurse -Force $extractDir -ErrorAction SilentlyContinue
        Write-Ok "Bundled ffmpeg installed in $binDir"
    } catch {
        Write-Warn2 "Failed to download the bundled ffmpeg: $($_.Exception.Message)"
        Write-Warn2 "The app still works if you have ffmpeg (with libvorbis) on your PATH."
    }
}

# ---------------------------------------------------------------------------
# 5b. FFmpeg SHARED libraries, for torchcodec
# ---------------------------------------------------------------------------
# The bundled ffmpeg above is a SELF-CONTAINED build - one large .exe with
# everything compiled in and no separate library files beside it. Perfect for
# running ffmpeg; useless to torchcodec, which needs FFmpeg's SHARED libraries
# and looks for them in the folder holding the ffmpeg.exe it finds.
#
# torchcodec arrives with torch 2.8 and is what torchaudio/pyannote reach for
# when decoding audio. Without these files it fails on every attempt and fills
# the log with a warning. Harmless today - the older decoders still work - but
# when whisperx moves to torch 2.9+ those older decoders are gone and this
# stops being cosmetic.
#
# VERSION 7 DELIBERATELY: torchcodec 0.7.0 ships loaders for FFmpeg 4, 5, 6
# and 7 only, and even 0.10.0 stops at 8. An FFmpeg 9 build - which is what a
# "latest" download gives you today - cannot be used by ANY torchcodec.
#
# SEVEN FILES, not six: avfilter-10 pulls in postproc-58. Found the hard way
# (2026-09-05) - with only the six that torchcodec's own core7.dll imports
# directly, five loaded and avfilter-10 failed with "or one of its
# dependencies", a message that never says WHICH one.
#
# Putting the files here is only half of it: since Python 3.8 Windows does not
# search the PATH for a DLL's dependencies, and torchcodec 0.7.0 does nothing
# about that (the PATH lookup only arrived in 0.10.0). The sidecar registers
# this folder itself - see _expose_ffmpeg_dlls in pipeline/proc_utils.py.
#
# NON-FATAL by design: everything else works without these.
Write-Step "Setting up the FFmpeg shared libraries (for torchcodec)"

$ffLibs = @("avcodec-61.dll", "avfilter-10.dll", "avformat-61.dll", "avutil-59.dll",
            "postproc-58.dll", "swresample-5.dll", "swscale-8.dll")
$missingLibs = @($ffLibs | Where-Object { -not (Test-Path (Join-Path $binDir $_)) })

if ($missingLibs.Count -eq 0) {
    Write-Ok "FFmpeg shared libraries already present in $binDir"
} else {
    try {
        $shUrl = "https://github.com/GyanD/codexffmpeg/releases/download/7.1.1/ffmpeg-7.1.1-full_build-shared.zip"
        $shZip = Join-Path $env:TEMP "uskmaker-ffmpeg7-shared.zip"
        $shDir = Join-Path $env:TEMP "uskmaker-ffmpeg7-extract"
        Write-Host "    Downloading the FFmpeg 7.1.1 shared build (~72 MB)..."
        Invoke-WebRequest -Uri $shUrl -OutFile $shZip -UseBasicParsing
        if (Test-Path $shDir) { Remove-Item -Recurse -Force $shDir }
        Expand-Archive -Path $shZip -DestinationPath $shDir -Force
        foreach ($lib in $ffLibs) {
            $srcLib = Get-ChildItem -Path $shDir -Recurse -Filter $lib | Select-Object -First 1
            if (-not $srcLib) { throw "$lib was not found inside the downloaded zip." }
            Copy-Item $srcLib.FullName (Join-Path $binDir $lib) -Force
        }
        Remove-Item $shZip -Force -ErrorAction SilentlyContinue
        Remove-Item -Recurse -Force $shDir -ErrorAction SilentlyContinue
        Write-Ok "FFmpeg shared libraries installed in $binDir"
    } catch {
        Write-Warn2 "Could not install the FFmpeg shared libraries: $($_.Exception.Message)"
        Write-Warn2 "  Not fatal - the app still works; only torchcodec stays unavailable."
    }
}

# ---------------------------------------------------------------------------
# 6. Install dependencies via uv (the slow step - large downloads)
# ---------------------------------------------------------------------------
# TORCH IS PINNED TO THE SERIES WHISPERX REQUIRES (torch~=2.8.0), and that is
# not fussiness - without the pin the install comes out BROKEN on a clean
# machine:
#
#   1. without the pin, this step installed the newest thing on the CUDA index
#      (today torch 2.13.0+cu126) - a ~2.5 GB download;
#   2. the next step (requirements.txt) brings in whisperx, which requires
#      torch~=2.8.0. uv then REPLACES the freshly installed torch with
#      torch 2.8.0 from PyPI - which on Windows is a CPU build;
#   3. result: the user downloads 2.5 GB of CUDA and ends up WITH NO GPU.
#      Worse: the validation at the end of this script said "GPU detected but
#      torch is not seeing CUDA (check your driver)" - blaming their driver for
#      a bug of OURS.
#
# It did not show up here because the dev venv was created while the index
# still served the 2.8 series (whisperx's pin was satisfied by 2.8.0+cu126 -
# a PEP 440 local version satisfies ~=2.8.0). The bug was born when the index
# moved past 2.8, and it hits anyone installing TODAY. Found in clean-machine
# testing (uv --python-preference only-managed), 2026-07-17.
#
# WHEN UPGRADING WHISPERX: check its requires_dist and realign these pins.
# If they drift apart, the same silent damage comes back.
$torchPin = @("torch~=2.8.0", "torchaudio~=2.8.0", "torchvision~=0.23.0")

Write-Step "Installing torch ($torchLabel) - this may take several minutes"
& $uvExe pip install --python "$venvPython" @torchPin --index-url $torchIndex
if ($LASTEXITCODE -ne 0) { Fail "Failed to install torch." }

# ---------------------------------------------------------------------------
# UNTIL 2026-09-05 THIS STEP UPDATED NOTHING AT ALL.
#
# The dependencies are declared with a FLOOR (">=4.0.1"), never a fixed
# ceiling, and `uv pip install` WITHOUT `--upgrade` only checks whether what is
# already installed satisfies the request - and then leaves. On a machine that
# already had the environment, running the setup again printed "Audited N
# packages" and walked away. The user stayed frozen on the versions from the
# day they first installed, FOREVER, with no warning that the command they ran
# to "update" does not update. (yt-dlp escapes this since 2026-09-02 because it
# has its own updater, see update_ytdlp.py - the rest of the pipeline had
# nothing.)
#
# MEASURED (2026-09-05, clean venv with uv):
#   without --upgrade -> rich 13.7.0 stays 13.7.0   ("Audited 1 package")
#   with --upgrade    -> rich 13.7.0 becomes 15.0.0
#
# BUT `--upgrade` ON ITS OWN RESURRECTS THE CPU TORCH BUG described above.
# whisperx asks for torch~=2.8.0, and that ACCEPTS a future 2.8.1. The day
# PyTorch publishes that patch on PyPI (which on Windows is a CPU build),
# --upgrade swaps the CUDA torch for it and the GPU disappears - silently,
# exactly as in the RTX 5080 report. This is not theory: it was measured.
#
# MEASURED (2026-09-05, with a test package imitating the local torch version):
#   --upgrade, index with 2.8.0 only     -> keeps 2.8.0+cu128 (the PEP 440
#                                           local version beats plain 2.8.0)
#   --upgrade, index already has 2.8.1   -> SWITCHES to 2.8.1 AND THE GPU IS GONE
#   --upgrade + a constraints file       -> keeps 2.8.0+cu128 (protected)
#
# So we freeze the torch that is ACTUALLY INSTALLED into a constraints file and
# update everything else on top of it. If for any reason the installed versions
# cannot be read, we update NOTHING: the old behaviour is the safe fallback.
# Better to be out of date than to lose the graphics card.
# ---------------------------------------------------------------------------
Write-Step "Preparing the update (protecting the installed torch)"

# uv SPLITS THE VALUE OF `--constraints` ON WHITESPACE. Measured 2026-09-05:
# `-c`, `--constraints`, `--constraints=VALUE` and the UV_CONSTRAINT
# environment variable ALL split it; only `-r` survives a path with a space.
#
# This file lives in %TEMP%. For anyone whose Windows account name is two
# words that is "C:\Users\John Smith\AppData\Local\Temp\...", so uv would see
# "C:\Users\John" and stop with "File not found" - taking the whole setup down
# with it. That is not hypothetical: the identical failure hit this script from
# the sidecar path on 2026-09-05, before the cause was understood.
#
# Windows keeps an 8.3 short name for such paths ("C:\Users\JOHNSM~1\...") and
# a short name never contains a space, so we hand uv that instead. When 8.3
# names are disabled on the volume the short name comes back unchanged, and
# then we do the SAFE thing rather than the clever one: no upgrade at all,
# exactly as when the installed torch version cannot be read. Being out of date
# beats losing the GPU, and both beat a setup that dies.
function Get-UvSafePath($path) {
    if ($path -notmatch ' ') { return $path }
    try {
        $fso = New-Object -ComObject Scripting.FileSystemObject
        $short = $fso.GetFile($path).ShortPath
        if ($short -and $short -notmatch ' ') { return $short }
    } catch { }
    return $null
}

$constraintsFile = Join-Path $env:TEMP "uskmaker-keep-torch.txt"
$upgradeArgs = @()

# The same PS 5.1 shielding used in the validation further down: with EAP=Stop,
# the first line uv writes to stderr would become a TERMINATING error.
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$frozen = & $uvExe pip freeze --python "$venvPython" 2>&1 | ForEach-Object { "$_" }
$ErrorActionPreference = $prevEAP

# `^torch==` does not match "torchcodec==..." (after "torch" comes "c", not
# "=="), so torchcodec stays free to update - which is what we want, since the
# version that shipped alongside torch 2.8 is permanently broken on Windows.
$torchFrozen = @($frozen | Where-Object { $_ -match '^(torch|torchaudio|torchvision)==' })

if ($torchFrozen.Count -eq 0) {
    Write-Warn2 "Could not read the installed torch version."
    Write-Warn2 "  To be safe, the dependencies will NOT be updated on this run"
    Write-Warn2 "  (updating without that protection could swap CUDA torch for a CPU one)."
} else {
    Set-Content -Path $constraintsFile -Value $torchFrozen -Encoding ASCII
    # Must run AFTER the file exists - the short name is read from the file.
    $constraintsArg = Get-UvSafePath $constraintsFile
    if ($constraintsArg) {
        $upgradeArgs = @("--upgrade", "-c", $constraintsArg)
        Write-Ok "Updating is ON. Frozen: $($torchFrozen -join ', ')"
    } else {
        Write-Warn2 "The temporary folder path contains a space and Windows has no"
        Write-Warn2 "  short name for it, and uv cannot be given a path like that."
        Write-Warn2 "  The dependencies will NOT be updated on this run - protecting the"
        Write-Warn2 "  CUDA torch matters more than being up to date."
    }
}

# The [gpu]/[cpu] extra brings in onnxruntime, which audio-separator imports at
# the top of the module but does NOT declare as a base dependency - without it
# the lead-vocal rescue fails silently (it always falls back to the Demucs
# stem).
#
# THE EXTRA GOES IN THE SAME COMMAND AS requirements.txt, not a second command
# after it. Both halves of that were learned the hard way on 2026-09-05:
#
#   1. As a SECOND, UNCONSTRAINED command it resolved with no version limits at
#      all, so a dependency walked straight past a ceiling this project
#      declares - numpy reached 2.5.2 while requirements.txt says `<2.5`.
#
#   2. The obvious repair - handing requirements.txt back as `-c` - CANNOT WORK
#      on a normal install. uv splits the value of `--constraints` on
#      whitespace, so the standard install path arrives as `C:\Program` and the
#      run dies with "File not found: C:\Program". MEASURED: `-c`,
#      `--constraints`, `--constraints=VALUE` and the UV_CONSTRAINT environment
#      variable ALL split; `-r` is the only one that survives a path with a
#      space in it.
#
# One command, one resolution: every ceiling in requirements.txt applies, the
# per-machine extra still gets picked, and no path is mishandled.
$sepExtra = if ($hasNvidia) { 'gpu' } else { 'cpu' }
Write-Step "Installing/updating the pipeline dependencies (audio-separator extra [$sepExtra])"
& $uvExe pip install --python "$venvPython" @upgradeArgs -r "$reqFile" "audio-separator[$sepExtra]>=0.44.0"
if ($LASTEXITCODE -ne 0) { Fail "Failed to install the dependencies (requirements.txt + audio-separator[$sepExtra])." }

Remove-Item $constraintsFile -Force -ErrorAction SilentlyContinue

# ---------------------------------------------------------------------------
# 7. Final validation
# ---------------------------------------------------------------------------
Write-Step "Validating the installation"

# (the same PS 5.1 shielding as the import validation below: EAP=Continue while
# capturing, and the verdict taken from the exit code, otherwise a stderr line
# from torch kills the script)
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$cudaOut = & $venvPython -c "import torch; print(torch.cuda.is_available())" 2>&1 | ForEach-Object { "$_" }
$cudaExit = $LASTEXITCODE
$ErrorActionPreference = $prevEAP
if ($cudaExit -ne 0) {
    Write-Host "    [FAILED] import torch - end of the traceback:" -ForegroundColor Red
    $cudaOut | Select-Object -Last 15 | ForEach-Object { Write-Host "      $_" -ForegroundColor DarkGray }
    Fail "torch did not import - the environment is NOT ready. The cause is in the lines above."
}
$cudaCheck = ($cudaOut | Where-Object { $_ -match '^(True|False)$' } | Select-Object -Last 1)
if ($hasNvidia -and $cudaCheck -ne "True") {
    # The old message blamed the user's driver. It almost never was the driver:
    # it was a CPU torch installed through faulty detection, or a CUDA build
    # without the card's kernels. Naming the two real suspects saves a lot of
    # time.
    Write-Warn2 "NVIDIA GPU detected but torch is not seeing CUDA."
    Write-Warn2 "  Suspects, in this order: (1) a CPU torch was installed"
    Write-Warn2 "  (run this script again with the GPU visible to nvidia-smi);"
    Write-Warn2 "  (2) the CUDA build does not cover the card's generation; (3) the driver."
} else {
    Write-Ok "torch installed (CUDA available: $cudaCheck)"
}

# torchcodec check, done THE WAY THE APP DOES IT. Importing torchcodec without
# registering the ffmpeg folder first would fail even on a perfect install -
# a check that does not mirror pipeline/proc_utils.py would simply lie.
# Informational only: nothing here can fail the setup.
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$tcCode = "import os; os.add_dll_directory(r'$binDir'); from torchcodec.decoders import AudioDecoder; print('TC_OK')"
$tcOut = & $venvPython -c $tcCode 2>&1 | ForEach-Object { "$_" }
$tcExit = $LASTEXITCODE
$ErrorActionPreference = $prevEAP
if ($tcExit -eq 0 -and ($tcOut -join "`n") -match 'TC_OK') {
    Write-Ok "torchcodec loads (FFmpeg shared libraries found)"
} else {
    Write-Warn2 "torchcodec does not load - harmless today, the older decoders still work."
}

# Each module is tested SEPARATELY and with stderr captured safely.
#
# HISTORY (2026-07-17, a real report): the previous version imported everything
# on a single line with "2>`$null" - and on Windows PowerShell 5.1, with
# `$ErrorActionPreference = "Stop" plus stderr redirection, the FIRST line
# python writes to stderr becomes a TERMINATING NativeCommandError. Result: the
# user saw only "Traceback (most recent call last):" and nothing else - neither
# which module failed nor the exception. The rest of the traceback went to
# `$null. Same family as the v0.3.2 bug (diagnostics that hide the cause).
#
# The rules here: (a) EAP=Continue while capturing (stderr becomes a harmless
# ErrorRecord, and "$_" turns it into text); (b) the verdict comes ONLY from
# the exit code - a WARNING on stderr (e.g. pyannote's torchcodec notice) must
# NOT fail an import that worked; (c) on failure, show the END of the
# traceback, which is where the real exception lives.
# ESSENTIAL modules: without any one of them the sidecar dies on import and the
# app produces nothing. A failure here = environment rejected.
#
# swift_f0 (pitch extraction) was missing from this list (found 2026-07-31, a
# real case): it imports onnxruntime just like audio_separator, but WITHOUT a
# try/except guard in pipeline/pitch.py - if its onnxruntime fails (common
# cause: the VC++ Redistributable is missing), the whole sidecar dies on
# import, except THAT WAS NOT TESTED here - the setup reported "all good" and
# the user only discovered the breakage in the middle of a real generation.
$coreModules = @('whisperx', 'demucs', 'librosa', 'mutagen', 'swift_f0')
# audio_separator = OPTIONAL: it is the lead-vocal rescue (2nd pass). At
# runtime the import is lazy inside a try/except (pipeline/separate.py), so the
# pipeline ALREADY falls back to the Demucs stem without it. Rejecting the
# whole environment over it locked users whose onnxruntime will not load (e.g.
# the Microsoft Visual C++ Redistributable missing on a clean machine) out of
# an app that would have worked. Now it only warns.
$optionalModules = @('audio_separator.separator')
$failedCore = @()
$failedOptional = @()
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
foreach ($mod in ($coreModules + $optionalModules)) {
    $importOut = & $venvPython -c "import $mod" 2>&1 | ForEach-Object { "$_" }
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "import $mod"
    } else {
        if ($optionalModules -contains $mod) { $failedOptional += $mod } else { $failedCore += $mod }
        Write-Host "    [FAILED] import $mod - end of the traceback:" -ForegroundColor Red
        $importOut | Select-Object -Last 15 | ForEach-Object { Write-Host "      $_" -ForegroundColor DarkGray }
    }
}
$ErrorActionPreference = $prevEAP

if ($failedOptional.Count -gt 0) {
    Write-Warn2 @"
An optional module did not import: $($failedOptional -join ', '). The app WORKS without it - the
pipeline falls back to the Demucs stem (you lose only the lead-vocal rescue,
which improves separation on some songs). Common cause: the Microsoft Visual
C++ Redistributable, which onnxruntime needs, is missing. To re-enable the
rescue: install the VC++ Redistributable (x64) and run this setup again.
"@
}

if ($failedCore.Count -eq 0) {
    Write-Ok "The essential pipeline libraries imported successfully."
} else {
    # FAILURE (not a warning): without these libraries the app does NOT
    # generate - the sidecar dies on import, before it can write any log.
    # Ending here with a green banner is exactly what confused a user
    # (2026-07-16).
    Fail @"
These essential libraries did not import: $($failedCore -join ', ') - the environment is NOT ready.

The cause is in the traceback lines above (the last line is the exception).
Run this setup again. If it persists, open an issue and attach those lines.
"@
}

Write-Host "`n=============================================" -ForegroundColor Green
Write-Host " Setup complete! You can now use USKMaker." -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Green
Write-Host " On the first song, the AI models (Demucs/Whisper)"
Write-Host " will be downloaded automatically (~2 GB, first time only)."
Pause-IfInteractive

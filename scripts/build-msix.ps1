# build-msix.ps1 - Gera o pacote MSIX oficial para a Microsoft Store
param(
    [string]$Version = "2.2.0.0"
)

$ErrorActionPreference = "Stop"

$root = "$PSScriptRoot\.."
$msixDir = "$root\packaging\msix"
$staging = "$msixDir\staging"
$outputMsix = "$msixDir\USKMaker_x64.msix"

if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
New-Item -ItemType Directory -Force -Path $staging | Out-Null

Write-Host "==> Preparando staging para MSIX v$Version..." -ForegroundColor Cyan

# Copia executavel
Copy-Item "$root\src-tauri\target\release\USKMaker.exe" -Destination "$staging\USKMaker.exe"

# Copia recursos
$resDir = "$staging\resources"
New-Item -ItemType Directory -Force -Path "$resDir\python-sidecar\pipeline" | Out-Null
New-Item -ItemType Directory -Force -Path "$resDir\scripts" | Out-Null

Copy-Item "$root\python-sidecar\*" -Destination "$resDir\python-sidecar" -Exclude "venv", "__pycache__", ".pytest_cache", "eval_runs"
Copy-Item "$root\python-sidecar\pipeline\*" -Destination "$resDir\python-sidecar\pipeline" -Exclude "__pycache__"
Copy-Item "$root\scripts\*" -Destination "$resDir\scripts"

# Copia Assets e Manifest
Copy-Item "$msixDir\Assets" -Destination "$staging\Assets" -Recurse
Copy-Item "$msixDir\AppxManifest.xml" -Destination "$staging\AppxManifest.xml"

# Localiza MakeAppx
$makeAppx = "C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\makeappx.exe"
if (-not (Test-Path $makeAppx)) {
    $found = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin\*\x64\makeappx.exe" -ErrorAction SilentlyContinue | Select-Object -Last 1
    if ($found) { $makeAppx = $found.FullName }
}

Write-Host "==> Empacotando com MakeAppx..." -ForegroundColor Cyan
& $makeAppx pack /d "$staging" /p "$outputMsix" /o /v

Remove-Item -Recurse -Force $staging -ErrorAction SilentlyContinue

Write-Host "`n[OK] Pacote MSIX criado com sucesso:" -ForegroundColor Green
Write-Host "     $outputMsix" -ForegroundColor Yellow

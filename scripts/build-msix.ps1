# build-msix.ps1 - Gera o pacote MSIX oficial para a Microsoft Store
[CmdletBinding()]
param(
    [string]$Version
)

$ErrorActionPreference = "Stop"

$root = "$PSScriptRoot\.."
$msixDir = "$root\packaging\msix"
$staging = "$msixDir\staging"

if (-not $Version) {
    $pkgJson = Get-Content "$root\package.json" -Raw -Encoding UTF8 | ConvertFrom-Json
    $semver = $pkgJson.version
    $Version = "$semver.0"
}

$outputMsix = "$msixDir\USKMaker_x64.msix"
$versionedMsix = "$msixDir\USKMaker_v$Version`_x64.msix"

if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
New-Item -ItemType Directory -Force -Path $staging | Out-Null

Write-Host "==> Preparando staging para MSIX v$Version..." -ForegroundColor Cyan

# Copia executavel
$exePath = "$root\src-tauri\target\release\USKMaker.exe"
if (-not (Test-Path $exePath)) {
    throw "Executavel release nao encontrado em $exePath. Execute o build antes."
}
Copy-Item $exePath -Destination "$staging\USKMaker.exe"

# Copia recursos essenciais (espelhando tauri.conf.json)
$resDir = "$staging\resources"
$sidecarDir = "$resDir\python-sidecar"
$pipelineDir = "$sidecarDir\pipeline"
$scriptsDir = "$resDir\scripts"

New-Item -ItemType Directory -Force -Path $pipelineDir | Out-Null
New-Item -ItemType Directory -Force -Path $scriptsDir | Out-Null

Copy-Item "$root\python-sidecar\*.py" -Destination $sidecarDir
Copy-Item "$root\python-sidecar\requirements.txt" -Destination $sidecarDir
Copy-Item "$root\python-sidecar\pipeline\*.py" -Destination $pipelineDir
Copy-Item "$root\scripts\setup-sidecar.ps1" -Destination $scriptsDir
Copy-Item "$root\scripts\setup-sidecar.sh" -Destination $scriptsDir

# Copia Assets e Manifest com versao atualizada
Copy-Item "$msixDir\Assets" -Destination "$staging\Assets" -Recurse

[xml]$manifestXml = Get-Content "$msixDir\AppxManifest.xml" -Encoding UTF8
$manifestXml.Package.Identity.Version = $Version
# Garante que MinVersion seja sempre compativel com a Store (>= 10.0.17763.0)
$manifestXml.Package.Dependencies.TargetDeviceFamily.MinVersion = "10.0.17763.0"
$manifestXml.Save("$staging\AppxManifest.xml")
$manifestXml.Save("$msixDir\AppxManifest.xml")

# Localiza MakeAppx
$makeAppx = "C:\Program Files (x86)\Windows Kits\10\bin\10.0.28000.0\x64\makeappx.exe"
if (-not (Test-Path $makeAppx)) {
    $found = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin\*\x64\makeappx.exe" -ErrorAction SilentlyContinue | Select-Object -Last 1
    if ($found) { $makeAppx = $found.FullName }
}

if (-not (Test-Path $makeAppx)) {
    throw "makeappx.exe nao encontrado no Windows SDK."
}

Write-Host "==> Empacotando com MakeAppx ($makeAppx)..." -ForegroundColor Cyan
& $makeAppx pack /d "$staging" /p "$outputMsix" /o /v

# Faz copia com a versao no nome para facilitar organizacao
Copy-Item "$outputMsix" -Destination "$versionedMsix" -Force

Remove-Item -Recurse -Force $staging -ErrorAction SilentlyContinue

Write-Host "`n[OK] Pacote MSIX criado com sucesso:" -ForegroundColor Green
Write-Host "     $outputMsix" -ForegroundColor Yellow
Write-Host "     $versionedMsix" -ForegroundColor Yellow

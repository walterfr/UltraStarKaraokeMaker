<#
.SYNOPSIS
    Script de release local para o USKMaker.

.DESCRIPTION
    Compila o instalador localmente (Windows/NSIS), gera checksums SHA256,
    extrai as notas do changelog e publica a release no GitHub via GitHub CLI (gh).
    Substitui a dependência do GitHub Actions quando a cota de minutos expira.

.PARAMETER Version
    Versão a publicar (ex.: 0.24.1). Se omitido, lê do package.json.

.PARAMETER SkipTests
    Pula a execução das suítes de testes (npm test, cargo test, pytest).

.PARAMETER SkipBuild
    Pula a compilação (reusa artefatos já gerados em src-tauri/target/release).

.PARAMETER WithLinux
    Tenta compilar pacotes Linux (.deb/.AppImage) via WSL, se configurado.

.PARAMETER Draft
    Cria a release como rascunho (Draft) no GitHub.

.PARAMETER Prerelease
    Marca a release como pré-lançamento (Pre-release) no GitHub.

.PARAMETER Force
    Permite rodar mesmo com modificações não commitadas no git.
#>

[CmdletBinding()]
param(
    [string]$Version,
    [switch]$SkipTests,
    [switch]$SkipBuild,
    [switch]$WithLinux,
    [switch]$Draft,
    [switch]$Prerelease,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $repoRoot

# 1. Determina a versão
if (-not $Version) {
    $pkgJsonPath = Join-Path $repoRoot "package.json"
    if (Test-Path $pkgJsonPath) {
        $pkgJson = Get-Content $pkgJsonPath -Raw | ConvertFrom-Json
        $Version = $pkgJson.version
    }
}

if (-not $Version) {
    Write-Error "Versão não especificada e não encontrada no package.json."
}

$Version = $Version.TrimStart('v').Trim()
$tag = "v$Version"
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " USKMaker Local Release: $tag" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# 2. Pré-requisitos
Write-Host "`n[1/6] Verificando pré-requisitos..." -ForegroundColor Yellow

$ghCheck = Get-Command "gh" -ErrorAction SilentlyContinue
if (-not $ghCheck) {
    Write-Error "GitHub CLI ('gh') não foi encontrado no PATH. Instale com: winget install GitHub.cli"
}

# Verifica autenticação no GitHub CLI
$null = gh auth status 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "GitHub CLI ('gh') não autenticado. Execute 'gh auth login' antes de continuar."
}

# Verifica status do Git (apenas arquivos rastreados modificados)
$gitStatus = (git status --porcelain --untracked-files=no)
if ($gitStatus -and -not $Force) {
    Write-Warning "Há alterações não commitadas na árvore de trabalho:"
    $gitStatus | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkYellow }
    Write-Error "Faça commit ou use -Force para ignorar alterações locais."
}

# 3. Testes
if (-not $SkipTests) {
    Write-Host "`n[2/6] Executando testes..." -ForegroundColor Yellow

    Write-Host "-> npm test..." -ForegroundColor Gray
    npm test
    if ($LASTEXITCODE -ne 0) { Write-Error "npm test falhou." }

    Write-Host "-> cargo test (rust-core)..." -ForegroundColor Gray
    cargo test --manifest-path rust-core/Cargo.toml
    if ($LASTEXITCODE -ne 0) { Write-Error "cargo test (rust-core) falhou." }

    $pytestExe = Join-Path $repoRoot "python-sidecar\venv\Scripts\pytest.exe"
    if (Test-Path $pytestExe) {
        Write-Host "-> pytest (python-sidecar)..." -ForegroundColor Gray
        & $pytestExe python-sidecar/tests
        if ($LASTEXITCODE -ne 0) { Write-Error "pytest falhou." }
    } else {
        Write-Warning "venv do python-sidecar não encontrado em python-sidecar/venv. Testes Python pulados."
    }
} else {
    Write-Host "`n[2/6] Testes ignorados (-SkipTests)." -ForegroundColor DarkGray
}

# 4. Compilação Windows
if (-not $SkipBuild) {
    Write-Host "`n[3/6] Compilando instalador do Windows (Tauri NSIS)..." -ForegroundColor Yellow
    npm run tauri build
    if ($LASTEXITCODE -ne 0) { Write-Error "npm run tauri build falhou." }
} else {
    Write-Host "`n[3/6] Build ignorado (-SkipBuild)." -ForegroundColor DarkGray
}

# 5. Localização e hashing de artefatos
Write-Host "`n[4/6] Coletando e gerando checksums dos artefatos..." -ForegroundColor Yellow

$nsisDir = Join-Path $repoRoot "src-tauri\target\release\bundle\nsis"
$installers = Get-ChildItem -Path $nsisDir -Filter "USKMaker_*_x64-setup.exe" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending

if (-not $installers -or $installers.Count -eq 0) {
    Write-Error "Nenhum instalador encontrado em $nsisDir."
}

$mainInstaller = $installers[0]
Write-Host "Instalador encontrado: $($mainInstaller.FullName) ($([math]::Round($mainInstaller.Length / 1MB, 2)) MB)" -ForegroundColor Green

# Gera checksum SHA256
$hash = (Get-FileHash -Path $mainInstaller.FullName -Algorithm SHA256).Hash.ToLower()
$sha256File = "$($mainInstaller.FullName).sha256"
"$hash *$($mainInstaller.Name)" | Out-File -FilePath $sha256File -Encoding ascii
Write-Host "SHA256 gerado: $sha256File ($hash)" -ForegroundColor Green

$assets = @($mainInstaller.FullName, $sha256File)

# Build Linux via WSL (opcional)
if ($WithLinux) {
    Write-Host "`n[4b/6] Verificando WSL para compilação Linux..." -ForegroundColor Yellow
    $wslCheck = Get-Command "wsl" -ErrorAction SilentlyContinue
    if ($wslCheck) {
        Write-Host "WSL detectado. Compilando pacotes Linux via WSL..." -ForegroundColor Gray
        # Converte caminho do Windows para /mnt/x/...
        $wslPath = ($repoRoot -replace '^([A-Za-z]):', '/mnt/$1').ToLower() -replace '\\', '/'
        $wslCmd = "cd '$wslPath' && npm run tauri build -- --target x86_64-unknown-linux-gnu"
        wsl bash -c "$wslCmd"
        if ($LASTEXITCODE -eq 0) {
            $linuxBundleDir = Join-Path $repoRoot "src-tauri\target\x86_64-unknown-linux-gnu\release\bundle"
            $debFiles = Get-ChildItem -Path "$linuxBundleDir\deb" -Filter "*.deb" -ErrorAction SilentlyContinue
            $appImageFiles = Get-ChildItem -Path "$linuxBundleDir\appimage" -Filter "*.AppImage" -ErrorAction SilentlyContinue
            foreach ($f in @($debFiles; $appImageFiles)) {
                if ($f) {
                    $lHash = (Get-FileHash -Path $f.FullName -Algorithm SHA256).Hash.ToLower()
                    $lSha = "$($f.FullName).sha256"
                    "$lHash *$($f.Name)" | Out-File -FilePath $lSha -Encoding ascii
                    $assets += $f.FullName
                    $assets += $lSha
                    Write-Host "Artefato Linux adicionado: $($f.Name)" -ForegroundColor Green
                }
            }
        } else {
            Write-Warning "Build Linux no WSL falhou ou toolchain Linux incompleta. Continuando apenas com Windows."
        }
    } else {
        Write-Warning "WSL não encontrado. Pulando build Linux."
    }
}

# 6. Extração de Release Notes do CHANGELOG.md
Write-Host "`n[5/6] Extraindo notas da versão do CHANGELOG.md..." -ForegroundColor Yellow

$changelogPath = Join-Path $repoRoot "CHANGELOG.md"
$notesContent = ""
if (Test-Path $changelogPath) {
    $changelog = Get-Content $changelogPath -Raw
    # Pega seção do formato ## [0.24.1] até o próximo ## ou fim
    $pattern = "(?ms)^##\s+\[$([regex]::Escape($Version))\].*?(?=^##\s+\[|\Z)"
    if ($changelog -match $pattern) {
        $notesContent = $Matches[0].Trim()
        Write-Host "Notas encontradas para a versão $Version no CHANGELOG.md." -ForegroundColor Green
    }
}

if (-not $notesContent) {
    Write-Warning "Notas para a versão $Version não encontradas no CHANGELOG.md. Usando notas automáticas."
    $notesContent = "Release do USKMaker $tag."
}

$tempNotesFile = [System.IO.Path]::GetTempFileName()
[System.IO.File]::WriteAllText($tempNotesFile, $notesContent, [System.Text.Encoding]::UTF8)

# 7. Publicação no GitHub Releases
Write-Host "`n[6/6] Publicando release $tag no GitHub..." -ForegroundColor Yellow

$localTag = (git tag -l $tag)
if (-not $localTag) {
    Write-Host "Criando tag $tag no git..." -ForegroundColor Gray
    git tag $tag
    git push origin $tag
}

$releaseExists = $false
$null = gh release view $tag 2>&1
if ($LASTEXITCODE -eq 0) {
    $releaseExists = $true
}

if ($releaseExists) {
    Write-Host "Release $tag já existe. Atualizando artefatos e notas..." -ForegroundColor Cyan
    gh release edit $tag --notes-file $tempNotesFile
    gh release upload $tag @assets --clobber
} else {
    Write-Host "Criando release $tag no GitHub..." -ForegroundColor Cyan
    $ghArgs = @("release", "create", $tag)
    $ghArgs += $assets
    $ghArgs += @("--title", "USKMaker $tag", "--notes-file", $tempNotesFile)
    if ($Draft) { $ghArgs += "--draft" }
    if ($Prerelease) { $ghArgs += "--prerelease" }

    gh @ghArgs
}

Remove-Item -Path $tempNotesFile -Force -ErrorAction SilentlyContinue

Write-Host "`n==========================================" -ForegroundColor Green
Write-Host " Release $tag publicada com sucesso!" -ForegroundColor Green
Write-Host " Acesse: https://github.com/walterfr/UltraStarKaraokeMaker/releases/tag/$tag" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green

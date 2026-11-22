param(
    [string]$MakeAppx = "$PSScriptRoot\windows-sdk\bin\10.0.26100.0\x64\makeappx.exe",
    [switch]$SkipTests
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    $python = "$projectRoot\.venv313\Scripts\python.exe"
    [xml]$manifest = Get-Content -Raw -Encoding UTF8 "$PSScriptRoot\AppxManifest.xml"
    $packageVersion = $manifest.Package.Identity.Version
    $storePackage = "dist\store\OttiskPhoto_${packageVersion}_x64_Store.msix"
    if (!(Test-Path -LiteralPath $MakeAppx)) { throw "Microsoft Windows SDK MakeAppx not found: $MakeAppx" }
    if (!$SkipTests) {
        & $python -m unittest discover -s tests
        if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
    }
    & $python -m PyInstaller --noconfirm --clean .\OttiskPhoto-onedir.spec
    if ($LASTEXITCODE -ne 0) { throw 'Onedir build failed' }
    & $python .\tools\prepare_msix.py
    if ($LASTEXITCODE -ne 0) { throw 'Staging failed' }
    New-Item -ItemType Directory -Path dist\store -Force | Out-Null
    & $MakeAppx pack /o /d build\msix-stage /p $storePackage
    if ($LASTEXITCODE -ne 0) { throw 'MSIX packaging failed' }
    # Preserve the independent one-file portable distribution.
    & $python -m PyInstaller --noconfirm --clean .\OttiskPhoto.spec
    if ($LASTEXITCODE -ne 0) { throw 'Portable build failed' }
    & "$PSScriptRoot\install-test-msix.ps1" -SignOnly
    if ($LASTEXITCODE -ne 0) { throw 'Test MSIX signing failed' }
    Get-FileHash $storePackage -Algorithm SHA256
} finally {
    Pop-Location
}

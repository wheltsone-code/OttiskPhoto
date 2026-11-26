param(
    [string]$InkscapeDirectory = 'tmp/converters/inkscape',
    [string]$GhostscriptDirectory = 'tmp/ghostscript-extracted',
    [string]$OutputDirectory = 'import-module'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    if (!(Test-Path -LiteralPath (Join-Path $InkscapeDirectory 'bin/inkscape.com'))) { throw 'Inkscape portable directory is required' }
    if (!(Test-Path -LiteralPath (Join-Path $GhostscriptDirectory 'bin/gswin64c.exe'))) { throw 'Ghostscript extracted directory is required' }
    New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
    $inkscapeTarget=Join-Path $OutputDirectory 'inkscape'
    $ghostscriptTarget=Join-Path $OutputDirectory 'ghostscript'
    New-Item -ItemType Directory -Force -Path $inkscapeTarget,$ghostscriptTarget | Out-Null
    Get-ChildItem -LiteralPath $InkscapeDirectory | Copy-Item -Destination $inkscapeTarget -Recurse -Force
    Get-ChildItem -LiteralPath $GhostscriptDirectory | Copy-Item -Destination $ghostscriptTarget -Recurse -Force
    # These archives identify the exact upstream binary distributions. Keep all
    # runtime files and upstream notices, rather than guessing which DLLs to trim.
    $manifest = [ordered]@{
        schema = 1
        inkscape = '1.4.2 (f4327f4, 2025-05-13)'
        ghostscript = '10.08.0'
        inkscape_archive_sha256 = '757E0358512630E65505A4CCA89885369087F2908469439BC41B5A346604CBD4'
        ghostscript_archive_sha256 = '52A91B8BF09298788D7A57B9206127026C23EACD75405F0A131E26DC381DCE50'
        inkscape_license = 'GPL-2.0-or-later; bundled libraries retain their respective licenses'
        ghostscript_license = 'AGPL-3.0; unmodified separate command-line process'
    }
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText((Join-Path (Resolve-Path $OutputDirectory).Path 'manifest.json'),($manifest | ConvertTo-Json),$utf8)
    Copy-Item -LiteralPath tools/IMPORT_MODULE.md -Destination (Join-Path $OutputDirectory 'README.md') -Force
    Write-Output "Import module prepared in $OutputDirectory. Extract its parent ZIP beside OttiskPhoto.exe."
} finally { Pop-Location }

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $root
try {
    $python = Join-Path $root '.venv313\Scripts\python.exe'
    # Run sequentially, without tests/builds competing for CPU during GUI timings.
    & $python tools\benchmark_to_optimization.py before-repeat --skip-full --reference --synchronous
    if ($LASTEXITCODE -ne 0) { throw 'Original GUI benchmark failed' }
    & $python tools\benchmark_to_optimization.py patched-repeat --skip-full --synchronous
    if ($LASTEXITCODE -ne 0) { throw 'Patched GUI benchmark failed' }
    & $python tools\benchmark_to_optimization.py after
    if ($LASTEXITCODE -ne 0) { throw 'Final GUI/full-image benchmark failed' }
} finally { Pop-Location }

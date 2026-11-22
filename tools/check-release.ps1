# Uses the real frozen applications; never submits a physical print job.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
[xml]$manifest = Get-Content -Raw -Encoding UTF8 "$PSScriptRoot\AppxManifest.xml"
$installed = Get-AppxPackage WeltsOne.605494C5ADEE5
if ($installed.Version -ne $manifest.Package.Identity.Version) { throw 'Installed package version differs from the manifest' }
$variants = @{
    portable = "$root\dist\OttiskPhoto.exe"
    installed = Join-Path $installed.InstallLocation 'App\OttiskPhoto.exe'
}
$previousPreferences = $env:OTTISK_PHOTO_PREFERENCES
$results = @()
try {
    foreach ($variant in @('portable','installed')) {
        $output = "$root\tmp\project-release-check\$variant"
        New-Item -ItemType Directory -Path $output -Force | Out-Null
        $env:OTTISK_PHOTO_PREFERENCES = "$output\preferences.json"
        [IO.File]::WriteAllText($env:OTTISK_PHOTO_PREFERENCES,'{"photos_per_sheet":"9","language":"ru","units":"mm"}',[Text.UTF8Encoding]::new($false))
        foreach ($check in @('project','documents','smoke')) {
            $checkFolder = "$output\$check"
            if ($check -eq 'project') {
                $arguments = @('--project-self-check', ('"' + $checkFolder + '"'))
                $reportFile = "$checkFolder\project-check.json"
            } elseif ($check -eq 'documents') {
                $arguments = @('--document-self-check', ('"' + $checkFolder + '"'), ('"' + "$root\tmp\project-release-check\documents" + '"'))
                $reportFile = "$checkFolder\document-check.json"
            } else {
                $photo = Get-ChildItem "$root\tmp\project-release-check\documents" -Filter '*.jpg' | Where-Object Length -gt 1024 | Select-Object -First 1
                $heic = Get-ChildItem "$root\tmp\project-release-check\documents" -Filter '*.heic' | Select-Object -First 1
                $arguments = @('--self-check', ('"' + $checkFolder + '"'), ('"' + $photo.FullName + '"'), ('"' + $heic.FullName + '"'))
                $reportFile = "$checkFolder\self-check.json"
            }
            $process = Start-Process -FilePath $variants[$variant] -ArgumentList $arguments -WindowStyle Hidden -PassThru -Wait
            if ($process.ExitCode -ne 0) { throw "$variant $check exited with $($process.ExitCode)" }
            $report = Get-Content -Raw -Encoding UTF8 $reportFile | ConvertFrom-Json
            if (!$report.passed) { throw "$variant $check failed: $reportFile" }
            $results += [pscustomobject]@{ variant=$variant; check=$check; passed=$report.passed; executable=$report.executable; report=$reportFile }
        }
    }
    $results | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 "$root\tmp\project-release-check\summary.json"
    $results | Format-Table variant,check,passed
} finally {
    if ($null -eq $previousPreferences) { Remove-Item Env:OTTISK_PHOTO_PREFERENCES -ErrorAction SilentlyContinue }
    else { $env:OTTISK_PHOTO_PREFERENCES = $previousPreferences }
}

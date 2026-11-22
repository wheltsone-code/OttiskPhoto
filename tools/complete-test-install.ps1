$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Start-Transcript -Path "$root\tmp\final-install-admin.log" -Force
try {
    Import-Certificate -FilePath "$root\dist\test\OttiskPhoto-TestOnly.cer" -CertStoreLocation Cert:\LocalMachine\TrustedPeople | Out-Null
    [xml]$manifest = Get-Content -Raw -Encoding UTF8 "$PSScriptRoot\AppxManifest.xml"
    $packageVersion = $manifest.Package.Identity.Version
    Add-AppxPackage -Path "$root\dist\test\OttiskPhoto_${packageVersion}_x64_TestSigned.msix" -ForceApplicationShutdown -ForceUpdateFromAnyVersion
    Get-AppxPackage WeltsOne.605494C5ADEE5 | Format-List Name,Version,Architecture,InstallLocation,PackageFamilyName
} finally {
    Stop-Transcript
}

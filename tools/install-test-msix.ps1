# Run in an elevated PowerShell. Signs a separate copy; Store file is untouched.
param([switch]$SignOnly)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$testFolder = Join-Path $root 'dist\test'
New-Item -ItemType Directory -Path $testFolder -Force | Out-Null
[xml]$manifest = Get-Content -Raw -Encoding UTF8 "$PSScriptRoot\AppxManifest.xml"
$packageVersion = $manifest.Package.Identity.Version
$store = Join-Path $root "dist\store\OttiskPhoto_${packageVersion}_x64_Store.msix"
$test = Join-Path $testFolder "OttiskPhoto_${packageVersion}_x64_TestSigned.msix"
Copy-Item -LiteralPath $store -Destination $test -Force
$subject = 'CN=B2837D41-24F1-433F-9044-BD76EF8258AD'
$certificateFile = Join-Path $testFolder 'OttiskPhoto-TestOnly.cer'
$cert = $null
if (Test-Path -LiteralPath $certificateFile) {
    $existing = Get-PfxCertificate -FilePath $certificateFile
    $cert = Get-ChildItem Cert:\CurrentUser\My | Where-Object {
        $_.Thumbprint -eq $existing.Thumbprint -and $_.Subject -eq $subject -and $_.HasPrivateKey -and $_.NotAfter -gt (Get-Date).AddDays(1)
    } | Select-Object -First 1
}
if (!$cert) {
    $cert = New-SelfSignedCertificate -Type Custom -Subject $subject -FriendlyName 'Ottisk Photo local MSIX test only' -KeyUsage DigitalSignature -KeyAlgorithm RSA -KeyLength 2048 -HashAlgorithm SHA256 -CertStoreLocation Cert:\CurrentUser\My -NotAfter (Get-Date).AddMonths(3) -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3','2.5.29.19={text}')
}
Export-Certificate -Cert $cert -FilePath $certificateFile | Out-Null
& "$PSScriptRoot\windows-sdk\bin\10.0.26100.0\x64\signtool.exe" sign /fd SHA256 /sha1 $cert.Thumbprint $test
if ($LASTEXITCODE -ne 0) { throw 'Test signing failed' }
if ($SignOnly) { return }
Import-Certificate -FilePath $certificateFile -CertStoreLocation Cert:\LocalMachine\TrustedPeople | Out-Null
Add-AppxPackage -Path $test -ForceApplicationShutdown -ForceUpdateFromAnyVersion
Get-AppxPackage WeltsOne.605494C5ADEE5 | Select-Object Name,Version,Architecture,InstallLocation,PackageFamilyName

# fix-ssl-usgs-vpn.ps1
# Fixes pixi/conda/pip SSL certificate errors when on the USGS/DOI VPN.
# Run this once from PowerShell (right-click -> Run with PowerShell, or open PS and run: .\scripts\fix-ssl-usgs-vpn.ps1)

$ErrorActionPreference = "Stop"

Write-Host "`n=== USGS VPN SSL Certificate Fix ===" -ForegroundColor Cyan
Write-Host "This script exports DOI certificates and configures pixi/conda/pip to trust them.`n"

# Detect miniforge/conda location
$possiblePaths = @(
    "$env:LOCALAPPDATA\miniforge3",
    "$env:USERPROFILE\miniforge3",
    "$env:LOCALAPPDATA\miniconda3",
    "$env:USERPROFILE\miniconda3",
    "$env:USERPROFILE\anaconda3"
)
$condaRoot = $possiblePaths | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $condaRoot) {
    Write-Host "ERROR: Could not find miniforge3/miniconda3/anaconda3 installation." -ForegroundColor Red
    Write-Host "Please set `$condaRoot manually in this script and re-run."
    pause
    exit 1
}
Write-Host "Found conda at: $condaRoot" -ForegroundColor Green

# Step 1: Create custom CA bundle directory
$sslDir = "$condaRoot\ssl"
$customBundle = "$sslDir\cacert-custom.pem"
$sourceBundle = "$condaRoot\Library\ssl\cacert.pem"

if (-not (Test-Path $sourceBundle)) {
    $sourceBundle = "$condaRoot\ssl\cacert.pem"
}
if (-not (Test-Path $sourceBundle)) {
    Write-Host "ERROR: Cannot find base cacert.pem at $condaRoot" -ForegroundColor Red
    pause
    exit 1
}

New-Item -ItemType Directory -Path $sslDir -Force | Out-Null
Copy-Item $sourceBundle $customBundle -Force
Write-Host "Created custom bundle from: $sourceBundle" -ForegroundColor Green

# Step 2: Export and append DOI certificates
$certsAdded = 0

# DOIRootCA2
$cert = Get-ChildItem Cert:\LocalMachine\Root | Where-Object { $_.Subject -eq "CN=DOIRootCA2" }
if ($cert) {
    $pem = "-----BEGIN CERTIFICATE-----`n" + [Convert]::ToBase64String($cert.RawData, [System.Base64FormattingOptions]::InsertLineBreaks) + "`n-----END CERTIFICATE-----"
    Add-Content -Path $customBundle -Value "`n`n# DOIRootCA2`n$pem"
    $certsAdded++
    Write-Host "  Added: DOIRootCA2" -ForegroundColor Gray
}

# Federal Common Policy CA G2
$cert = Get-ChildItem Cert:\LocalMachine\Root | Where-Object { $_.Subject -match "Federal Common Policy CA G2" }
if ($cert) {
    $pem = "-----BEGIN CERTIFICATE-----`n" + [Convert]::ToBase64String($cert.RawData, [System.Base64FormattingOptions]::InsertLineBreaks) + "`n-----END CERTIFICATE-----"
    Add-Content -Path $customBundle -Value "`n`n# Federal Common Policy CA G2`n$pem"
    $certsAdded++
    Write-Host "  Added: Federal Common Policy CA G2" -ForegroundColor Gray
}

# Federal Common Policy CA
$cert = Get-ChildItem Cert:\LocalMachine\Root | Where-Object { $_.Subject -match "Federal Common Policy CA," }
if ($cert) {
    $pem = "-----BEGIN CERTIFICATE-----`n" + [Convert]::ToBase64String($cert.RawData, [System.Base64FormattingOptions]::InsertLineBreaks) + "`n-----END CERTIFICATE-----"
    Add-Content -Path $customBundle -Value "`n`n# Federal Common Policy CA`n$pem"
    $certsAdded++
    Write-Host "  Added: Federal Common Policy CA" -ForegroundColor Gray
}

# DOI Intermediate CAs
$intermediates = Get-ChildItem Cert:\LocalMachine\CA | Where-Object { $_.Subject -match "DOIIMCA" }
foreach ($c in $intermediates) {
    $pem = "-----BEGIN CERTIFICATE-----`n" + [Convert]::ToBase64String($c.RawData, [System.Base64FormattingOptions]::InsertLineBreaks) + "`n-----END CERTIFICATE-----"
    $name = ($c.Subject -split ',')[0]
    Add-Content -Path $customBundle -Value "`n`n# $name`n$pem"
    $certsAdded++
    Write-Host "  Added: $name" -ForegroundColor Gray
}

Write-Host "`nAppended $certsAdded DOI certificates to custom bundle." -ForegroundColor Green

# Step 3: Set SSL_CERT_FILE environment variable (user-level, persists across sessions)
[System.Environment]::SetEnvironmentVariable("SSL_CERT_FILE", $customBundle, "User")
$env:SSL_CERT_FILE = $customBundle
Write-Host "Set SSL_CERT_FILE = $customBundle" -ForegroundColor Green

Write-Host "`n=== Done! ===" -ForegroundColor Cyan
Write-Host "Close and reopen your terminal, then run 'pixi install' again."
Write-Host "This fix applies to pixi, conda, pip, and any tool that respects SSL_CERT_FILE.`n"
pause

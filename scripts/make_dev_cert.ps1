# Generates a self-signed dev certificate for VxDesk remote TLS.
#
#   powershell -ExecutionPolicy Bypass -File scripts\make_dev_cert.ps1 [-OutDir .\certs]
#
# Creates a self-signed cert via New-SelfSignedCertificate, exports a PFX, and
# — if openssl is on PATH — converts it to the cert.pem / key.pem pair that the
# Remote settings page expects (tls.cert / tls.key). Without openssl, use the
# PFX with a converter of your choice, e.g.:
#   openssl pkcs12 -in vxdesk-dev.pfx -out vxdesk-dev.crt -clcerts -nokeys
#   openssl pkcs12 -in vxdesk-dev.pfx -out vxdesk-dev.key -nocerts -nodes
#
# DEV ONLY: self-signed certs trigger browser/client warnings. For production
# use a properly issued certificate.

param(
    [string]$OutDir = ".\certs",
    [string]$CertName = "vxdesk-dev",
    [string]$Password = "vxdesk-dev"
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$OutDir = (Resolve-Path $OutDir).Path

$cert = New-SelfSignedCertificate `
    -DnsName "localhost", "vxdesk.local" `
    -CertStoreLocation "Cert:\CurrentUser\My" `
    -NotAfter (Get-Date).AddYears(2) `
    -KeyExportPolicy Exportable `
    -FriendlyName "VxDesk dev (remote TLS)"

$pfxPath = Join-Path $OutDir "$CertName.pfx"
$secure = ConvertTo-SecureString -String $Password -Force -AsPlainText
Export-PfxCertificate -Cert $cert -FilePath $pfxPath -Password $secure | Out-Null
Write-Host "PFX exported: $pfxPath (password: $Password)"

$openssl = Get-Command openssl -ErrorAction SilentlyContinue
if ($openssl) {
    $crtPath = Join-Path $OutDir "$CertName.crt"
    $keyPath = Join-Path $OutDir "$CertName.key"
    & openssl pkcs12 -in $pfxPath -out $crtPath -clcerts -nokeys -passin "pass:$Password"
    & openssl pkcs12 -in $pfxPath -out $keyPath -nocerts -nodes -passin "pass:$Password"
    Write-Host "PEM pair exported:"
    Write-Host "  cert: $crtPath"
    Write-Host "  key : $keyPath"
    Write-Host ""
    Write-Host "Set these paths under Remote -> Settings -> TLS (cert/key)."
} else {
    Write-Host "openssl not found on PATH — convert the PFX manually:"
    Write-Host "  openssl pkcs12 -in $pfxPath -out $CertName.crt -clcerts -nokeys"
    Write-Host "  openssl pkcs12 -in $pfxPath -out $CertName.key -nocerts -nodes"
}

# clean the cert store copy (the PFX/PEMs on disk are the deliverable)
Remove-Item $cert.PSPath -Force
Write-Host "Done. This is a DEV certificate — do not use in production."

param(
  [Parameter(Mandatory = $true)]
  [string]$Path,
  [string]$Thumbprint = $env:OPENTALOS_WINDOWS_CERT_THUMBPRINT,
  [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
if (-not $Thumbprint) {
  throw "OPENTALOS_WINDOWS_CERT_THUMBPRINT is required"
}
if (-not (Test-Path -LiteralPath $Path)) {
  throw "Signing target does not exist: $Path"
}

$signTool = Get-Command signtool.exe -ErrorAction SilentlyContinue
if (-not $signTool) {
  $candidate = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" `
    -Recurse -Filter signtool.exe |
    Where-Object { $_.FullName -match "\\x64\\" } |
    Select-Object -Last 1
  if (-not $candidate) {
    throw "signtool.exe was not found"
  }
  $signTool = $candidate.FullName
} else {
  $signTool = $signTool.Source
}

& $signTool sign /sha1 $Thumbprint /fd SHA256 /tr $TimestampUrl /td SHA256 $Path
if ($LASTEXITCODE -ne 0) {
  throw "signtool failed with exit code $LASTEXITCODE"
}
& $signTool verify /pa /v $Path
if ($LASTEXITCODE -ne 0) {
  throw "signature verification failed"
}

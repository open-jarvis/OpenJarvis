param(
    [Parameter(Mandatory = $true)][string] $Path,
    [Parameter(Mandatory = $true)][string] $ExpectedThumbprint
)

$ErrorActionPreference = 'Stop'
$signature = Get-AuthenticodeSignature -LiteralPath $Path
if ($signature.Status -ne 'Valid') {
    throw "Authenticode verification failed for ${Path}: $($signature.Status)"
}
$expected = $ExpectedThumbprint.Replace(' ', '').ToUpperInvariant()
if ($signature.SignerCertificate.Thumbprint -ne $expected) {
    throw "Unexpected code-signing certificate for $Path"
}
if (-not $signature.TimeStamperCertificate) {
    throw "The Authenticode signature has no timestamp: $Path"
}
Write-Output "Verified timestamped Authenticode signature: $Path"

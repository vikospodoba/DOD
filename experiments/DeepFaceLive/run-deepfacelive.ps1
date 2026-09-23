$ErrorActionPreference = "Stop"

param(
    [string]$PortableDir = (Join-Path $PSScriptRoot "portable")
)

$resolvedPortableDir = Resolve-Path -LiteralPath $PortableDir -ErrorAction SilentlyContinue
if (-not $resolvedPortableDir) {
    throw "Portable directory not found: $PortableDir"
}

$launcher = Get-ChildItem -LiteralPath $resolvedPortableDir.Path -Recurse -File -Filter "DeepFaceLive.bat" |
    Select-Object -First 1

if (-not $launcher) {
    throw @"
DeepFaceLive.bat was not found under:
$($resolvedPortableDir.Path)

Download the official Windows portable build from:
https://github.com/iperov/DeepFaceLive

Then unpack it into experiments\DeepFaceLive\portable or pass -PortableDir with the unpacked folder.
"@
}

Start-Process -FilePath $launcher.FullName -WorkingDirectory $launcher.DirectoryName
Write-Host "Started DeepFaceLive: $($launcher.FullName)"

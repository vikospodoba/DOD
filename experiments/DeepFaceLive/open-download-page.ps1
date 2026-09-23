$ErrorActionPreference = "Stop"

$portableDir = Join-Path $PSScriptRoot "portable"
New-Item -ItemType Directory -Force -Path $portableDir | Out-Null

Start-Process "https://github.com/iperov/DeepFaceLive"
Start-Process $portableDir

Write-Host "Opened the official DeepFaceLive repository and local portable folder:"
Write-Host $portableDir

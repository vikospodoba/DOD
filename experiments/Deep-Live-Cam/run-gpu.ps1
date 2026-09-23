$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$venv = if ($env:DOD_DEEP_LIVE_CAM_VENV) {
    $env:DOD_DEEP_LIVE_CAM_VENV
} elseif ($env:LOCALAPPDATA -and (Test-Path (Join-Path $env:LOCALAPPDATA "DODDeepLiveCam\.venv311\Scripts\python.exe"))) {
    Join-Path $env:LOCALAPPDATA "DODDeepLiveCam\.venv311"
} else {
    Join-Path $root ".venv311"
}
$python = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Python environment not found: $python"
}

$nvidiaRoot = Join-Path $venv "Lib\site-packages\nvidia"
if (Test-Path $nvidiaRoot) {
    $nvidiaBins = Get-ChildItem -Path $nvidiaRoot -Recurse -Directory -Filter bin |
        ForEach-Object { $_.FullName }
    if ($nvidiaBins) {
        $env:PATH = (($nvidiaBins -join ";") + ";" + $env:PATH)
    }
}

$ffmpeg = Get-ChildItem -Path (Join-Path $root "vendor\ffmpeg") -Recurse -Filter ffmpeg.exe -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($ffmpeg) {
    $env:PATH = ((Split-Path $ffmpeg.FullName) + ";" + $env:PATH)
}

if (-not $env:DOD_DISABLE_CUDA_GRAPH) {
    $env:DOD_DISABLE_CUDA_GRAPH = "true"
}
if (-not $env:DOD_CUDA_GPU_MEM_LIMIT_MB) {
    $env:DOD_CUDA_GPU_MEM_LIMIT_MB = "12288"
}
if (-not $env:DOD_EXECUTION_THREADS) {
    $env:DOD_EXECUTION_THREADS = "1"
}

& $python run.py --execution-provider cuda --execution-threads $env:DOD_EXECUTION_THREADS @args

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$deepLiveCamRoot = Join-Path $root "experiments\Deep-Live-Cam"
$venv = if ($env:DOD_DEEP_LIVE_CAM_VENV) {
    $env:DOD_DEEP_LIVE_CAM_VENV
} elseif ($env:LOCALAPPDATA) {
    Join-Path $env:LOCALAPPDATA "DODDeepLiveCam\.venv311"
} else {
    Join-Path $deepLiveCamRoot ".venv311"
}
$python = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "Python environment not found: $python. Run .\setup-deep-live-cam-env.ps1 first."
}

$modelDir = Join-Path $deepLiveCamRoot "models"
$modelCandidates = @(
    Join-Path $modelDir "inswapper_128_fp16.onnx"
    Join-Path $modelDir "inswapper_128.onnx"
)
if (-not ($modelCandidates | Where-Object { Test-Path $_ })) {
    throw "Deep Live Cam model not found. Expected inswapper_128_fp16.onnx or inswapper_128.onnx in $modelDir"
}

$env:DOD_INFERENCE_MODE = "deep_live_cam"
$env:DOD_DEEP_LIVE_CAM_DIR = $deepLiveCamRoot
$env:DOD_MODEL_DIR = $modelDir
$env:DOD_CHARACTERS_DIR = Join-Path $root "characters"
$env:DOD_CHARACTER_IDS = "default-human,west,snoop-dogg,trump,kim-jong-un,boris-johnson"
$env:DOD_DEFAULT_CHARACTER_ID = "default-human"
if (-not $env:DOD_EXECUTION_PROVIDERS) {
    $env:DOD_EXECUTION_PROVIDERS = "cuda,cpu"
}
if (-not $env:CUDA_VISIBLE_DEVICES) {
    $gpuRows = & nvidia-smi --query-gpu=index,memory.free --format=csv,noheader,nounits 2>$null
    $bestGpu = $gpuRows |
        ForEach-Object {
            $parts = $_ -split ","
            if ($parts.Count -ge 2) {
                [pscustomobject]@{
                    Index = $parts[0].Trim()
                    FreeMb = [int]$parts[1].Trim()
                }
            }
        } |
        Sort-Object FreeMb -Descending |
        Select-Object -First 1
    if ($bestGpu) {
        $env:CUDA_VISIBLE_DEVICES = $bestGpu.Index
        Write-Host "Selected CUDA GPU $($bestGpu.Index) with $($bestGpu.FreeMb) MB free."
    }
}
if (-not $env:DOD_EXECUTION_THREADS) {
    $env:DOD_EXECUTION_THREADS = "1"
}
if (-not $env:DOD_DISABLE_CUDA_GRAPH) {
    $env:DOD_DISABLE_CUDA_GRAPH = "true"
}
if (-not $env:DOD_CUDA_GPU_MEM_LIMIT_MB) {
    $env:DOD_CUDA_GPU_MEM_LIMIT_MB = "12288"
}
if (-not $env:DOD_POISSON_BLEND) {
    $env:DOD_POISSON_BLEND = "false"
}
if (-not $env:DOD_COLOR_CORRECTION) {
    $env:DOD_COLOR_CORRECTION = "false"
}
if (-not $env:DOD_MOUTH_MASK_SIZE) {
    $env:DOD_MOUTH_MASK_SIZE = "0"
}
if (-not $env:DOD_SHARPNESS) {
    $env:DOD_SHARPNESS = "0"
}
if (-not $env:DOD_OPACITY) {
    $env:DOD_OPACITY = "1.0"
}
if (-not $env:DOD_FACE_ENHANCER) {
    $env:DOD_FACE_ENHANCER = "none"
}

$nvidiaRoot = Join-Path $venv "Lib\site-packages\nvidia"
if (Test-Path $nvidiaRoot) {
    $nvidiaBins = Get-ChildItem -Path $nvidiaRoot -Recurse -Directory -Filter bin |
        ForEach-Object { $_.FullName }
    if ($nvidiaBins) {
        $env:PATH = (($nvidiaBins -join ";") + ";" + $env:PATH)
    }
}

$ffmpeg = Get-ChildItem -Path (Join-Path $deepLiveCamRoot "vendor\ffmpeg") -Recurse -Filter ffmpeg.exe -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($ffmpeg) {
    $env:PATH = ((Split-Path $ffmpeg.FullName) + ";" + $env:PATH)
}

& $python (Join-Path $root "inference-worker\webrtc_server.py") @args

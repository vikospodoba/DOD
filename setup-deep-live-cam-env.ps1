param(
    [switch]$Force
)

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
$venvPython = Join-Path $venv "Scripts\python.exe"
$requirements = Join-Path $deepLiveCamRoot "requirements.txt"
$insightfaceWheel = Join-Path $deepLiveCamRoot "vendor\insightface-0.7.3-cp311-cp311-win_amd64.whl"
$cudaWheelsDir = Join-Path $deepLiveCamRoot "vendor\wheels"

function Get-Python311Command {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $launcherEntries = & py -0p 2>$null
        foreach ($entry in $launcherEntries) {
            if ($entry -match "3\.11[^\s]*\s+(.+python\.exe)$") {
                return @{
                    Command = $Matches[1]
                    Args = @()
                }
            }
        }

        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & py -3.11 -c "import sys" 2>$null
        $py311ExitCode = $LASTEXITCODE
        $ErrorActionPreference = $previousErrorActionPreference
        if ($py311ExitCode -eq 0) {
            return @{
                Command = "py"
                Args = @("-3.11")
            }
        }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        $version = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($LASTEXITCODE -eq 0 -and $version -eq "3.11") {
            return @{
                Command = "python"
                Args = @()
            }
        }
    }

    throw "Python 3.11 not found. Install Python 3.11 or make it available through the Python launcher."
}

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
    }
}

if (-not (Test-Path $deepLiveCamRoot)) {
    throw "Deep-Live-Cam directory not found: $deepLiveCamRoot"
}

if ((Test-Path $venv) -and -not $Force) {
    Write-Host "Environment already exists: $venv"
    Write-Host "Use -Force to recreate it."
    exit 0
}

if ((Test-Path $venv) -and $Force) {
    Remove-Item -LiteralPath $venv -Recurse -Force
}

$venvParent = Split-Path -Parent $venv
if ($venvParent -and -not (Test-Path $venvParent)) {
    New-Item -ItemType Directory -Path $venvParent -Force | Out-Null
}

$python311 = Get-Python311Command
& $python311.Command @($python311.Args) -m venv $venv
if ($LASTEXITCODE -ne 0) {
    throw "Failed to create Python virtual environment: $venv"
}

Invoke-Checked $venvPython @("-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel")
Invoke-Checked $venvPython @("-m", "pip", "install", "numpy==1.26.4")

if (Test-Path $insightfaceWheel) {
    Invoke-Checked $venvPython @("-m", "pip", "install", "--no-deps", $insightfaceWheel)
}

if (Test-Path $cudaWheelsDir) {
    Get-ChildItem -Path $cudaWheelsDir -Filter *.whl | ForEach-Object {
        Invoke-Checked $venvPython @("-m", "pip", "install", $_.FullName)
    }
}
Invoke-Checked $venvPython @("-m", "pip", "install", "nvidia-cufft-cu12")
Invoke-Checked $venvPython @("-m", "pip", "install", "nvidia-cuda-runtime-cu12")

$filteredRequirements = Join-Path $env:TEMP "deep-live-cam-requirements-$PID.txt"
try {
    Get-Content $requirements |
        Where-Object {
            $_ -notmatch "^\s*insightface==" -and
            $_ -notmatch "^\s*numpy" -and
            $_ -notmatch "^\s*opencv-python==" -and
            $_ -notmatch "^\s*opencv-python-headless==" -and
            $_ -notmatch "^\s*onnx=="
        } |
        Set-Content -Path $filteredRequirements -Encoding ASCII

    Invoke-Checked $venvPython @("-m", "pip", "install", "-r", $filteredRequirements)
    Invoke-Checked $venvPython @(
        "-m", "pip", "install",
        "numpy==1.26.4",
        "opencv-python==4.10.0.84",
        "opencv-python-headless==4.10.0.84",
        "onnx==1.16.1",
        "ml-dtypes==0.5.3",
        "albumentations==1.4.0",
        "cython",
        "easydict",
        "prettytable",
        "scikit-learn"
    )
} finally {
    if (Test-Path $filteredRequirements) {
        Remove-Item -LiteralPath $filteredRequirements -Force
    }
}

Write-Host "Deep Live Cam environment is ready: $venv"
Write-Host "Start the worker with: .\run-deep-live-cam-worker.ps1"

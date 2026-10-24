$ErrorActionPreference = "Stop"
$root = (Resolve-Path $PSScriptRoot).Path
$venvPython = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        & $launcher.Source -3 -m venv (Join-Path $root ".venv")
    }
    else {
        $python = (Get-Command python -ErrorAction Stop).Source
        & $python -m venv (Join-Path $root ".venv")
    }
}

& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r (Join-Path $root "requirements.txt")
Write-Output "Environment ready: $venvPython"

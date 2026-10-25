param(
    [int]$Port = 8791,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path $PSScriptRoot).Path
$url = "http://127.0.0.1:$Port/seewo_student_demo"
$healthUrl = "http://127.0.0.1:$Port/api/health"
$runtimeDir = Join-Path $root ".runtime"
$venvPython = Join-Path $root ".venv\Scripts\python.exe"

function Test-DemoServer {
    try {
        $response = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
        return $response.ok -eq $true
    }
    catch {
        return $false
    }
}

if (-not (Test-DemoServer)) {
    [System.IO.Directory]::CreateDirectory($runtimeDir) | Out-Null
    if (Test-Path $venvPython) {
        $python = $venvPython
    }
    else {
        $python = (Get-Command python -ErrorAction Stop).Source
    }
    $stdout = Join-Path $runtimeDir "demo_stdout.log"
    $stderr = Join-Path $runtimeDir "demo_stderr.log"
    $arguments = @(
        "-m", "src.rehab_affect.scenario_lab_server",
        "--host", "127.0.0.1",
        "--port", $Port,
        "--policy", "rule"
    )
    Start-Process `
        -FilePath $python `
        -ArgumentList $arguments `
        -WorkingDirectory $root `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr | Out-Null

    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 500
        if (Test-DemoServer) {
            $ready = $true
            break
        }
    }
    if (-not $ready) {
        Write-Error "Demo failed to start. Check $stderr"
    }
}

Write-Output "Demo ready: $url"
if (-not $NoBrowser) {
    Start-Process $url
}

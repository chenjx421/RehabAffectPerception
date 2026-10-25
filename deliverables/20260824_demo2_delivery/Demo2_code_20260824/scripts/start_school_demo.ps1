param(
    [int]$Port = 8791,
    [ValidateSet("seewo_student_demo", "seewo_student_demo2")]
    [string]$Page = "seewo_student_demo",
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$url = "http://127.0.0.1:$Port/$Page"
$healthUrl = "http://127.0.0.1:$Port/api/health"
$runtimeDir = Join-Path $projectRoot ".runtime"
$stdoutPath = Join-Path $runtimeDir "seewo_demo_stdout.log"
$stderrPath = Join-Path $runtimeDir "seewo_demo_stderr.log"

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
    $python = (Get-Command python -ErrorAction Stop).Source
    $arguments = @(
        "-m", "src.rehab_affect.scenario_lab_server",
        "--host", "127.0.0.1",
        "--port", $Port,
        "--policy", "rule"
    )
    Start-Process `
        -FilePath $python `
        -ArgumentList $arguments `
        -WorkingDirectory $projectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath | Out-Null

    $ready = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Milliseconds 500
        if (Test-DemoServer) {
            $ready = $true
            break
        }
    }
    if (-not $ready) {
        Write-Error "Demo server did not start. Check $stderrPath"
    }
}

Write-Output "Demo ready: $url"
if (-not $NoBrowser) {
    Start-Process $url
}

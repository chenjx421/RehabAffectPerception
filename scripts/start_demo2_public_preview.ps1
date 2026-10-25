param([int]$Port = 8795)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$previewRoot = Join-Path $projectRoot '.runtime\public-entry'
$cloudflared = Join-Path $projectRoot '.tools\cloudflared.exe'
if (-not (Test-Path -LiteralPath $cloudflared)) { throw 'cloudflared.exe is not available.' }
if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) { throw "Port $Port is already in use." }
[System.IO.Directory]::CreateDirectory($previewRoot) | Out-Null
# Serve this explicit allowlist only. No application routes, media, or credentials.
foreach ($name in @('login.html', 'register.html', 'privacy.html')) {
    $source = Join-Path $projectRoot "deliverables\20260908_platform_entry\$name"
    Copy-Item -LiteralPath $source -Destination (Join-Path $previewRoot $name) -Force
}
$python = (Get-Command python -ErrorAction Stop).Source
$web = Start-Process -FilePath $python -ArgumentList @('-m', 'http.server', $Port, '--bind', '127.0.0.1') -WorkingDirectory $previewRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $projectRoot '.runtime\preview_http.log') -RedirectStandardError (Join-Path $projectRoot '.runtime\preview_http_error.log') -PassThru
$tunnel = Start-Process -FilePath $cloudflared -ArgumentList @('tunnel', '--url', "http://127.0.0.1:$Port", '--no-autoupdate') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $projectRoot '.runtime\preview_tunnel.log') -RedirectStandardError (Join-Path $projectRoot '.runtime\preview_tunnel_error.log') -PassThru
[pscustomobject]@{ StaticPreviewPid = $web.Id; TunnelPid = $tunnel.Id; Port = $Port; Log = '.runtime/preview_tunnel_error.log' } | ConvertTo-Json

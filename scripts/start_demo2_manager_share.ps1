param(
    [ValidateRange(1024, 65535)][int]$Port = 8796,
    [ValidateRange(1024, 65535)][int]$UpstreamPort = 8793,
    [ValidateRange(1, 72)][int]$Hours = 48,
    [string[]]$EdgeAddresses = @()
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$runtime = Join-Path $root '.runtime'
$configPath = Join-Path $runtime 'manager_share_config.json'
$statePath = Join-Path $runtime 'manager_share_state.json'
$cloudflared = Join-Path $root '.tools\cloudflared.exe'
$python = (Get-Command python -ErrorAction Stop).Source
if (-not (Test-Path -LiteralPath $cloudflared)) { throw 'cloudflared.exe is not available.' }
foreach ($edge in $EdgeAddresses) {
    if ($edge -notmatch '^\d{1,3}(\.\d{1,3}){3}:7844$') { throw 'Invalid edge address.' }
    $address = $null
    if (-not [System.Net.IPAddress]::TryParse($edge.Split(':')[0], [ref]$address)) {
        throw 'Invalid edge address.'
    }
}

$probe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
try { $probe.Start() } finally { $probe.Stop() }
$health = Invoke-WebRequest -Uri "http://127.0.0.1:$UpstreamPort/demo2/login" -UseBasicParsing -TimeoutSec 10
if ($health.StatusCode -ne 200) { throw 'The local application is not ready.' }

function New-PrivateToken {
    $bytes = [byte[]]::new(32)
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

[System.IO.Directory]::CreateDirectory($runtime) | Out-Null
$config = [ordered]@{
    invite_secret = New-PrivateToken
    cookie_secret = New-PrivateToken
    expires_at = [DateTimeOffset]::UtcNow.AddHours($Hours).ToUnixTimeSeconds()
    upstream_port = $UpstreamPort
    listen_port = $Port
}
$config | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding utf8
$gateway = $null
$tunnel = $null
$state = $null
try {
$gateway = Start-Process -FilePath $python -ArgumentList @(
    '-B', '-m', 'src.rehab_affect.demo2_manager_gateway', '--config', $configPath
) -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'manager_gateway.log') -RedirectStandardError (Join-Path $runtime 'manager_gateway_error.log') -PassThru

$ready = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Milliseconds 500
    $gateway.Refresh()
    if ($gateway.HasExited) { throw 'Gateway exited; check .runtime/manager_gateway_error.log.' }
    try {
        $page = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/invite" -UseBasicParsing -TimeoutSec 2
        if ($page.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
}
if (-not $ready) { throw 'Gateway is not ready; tunnel was not started.' }

$tunnelLog = Join-Path $runtime 'manager_tunnel_error.log'
$tunnelArguments = @('tunnel', '--url', "http://127.0.0.1:$Port", '--no-autoupdate')
if ($EdgeAddresses.Count -gt 0) {
    foreach ($edge in $EdgeAddresses) {
        $tunnelArguments += @('--edge', $edge)
    }
    $tunnelArguments += @('--protocol', 'http2', '--no-prechecks')
}
$tunnel = Start-Process -FilePath $cloudflared -ArgumentList $tunnelArguments -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'manager_tunnel.log') -RedirectStandardError $tunnelLog -PassThru

$state = [ordered]@{
    gateway_pid = $gateway.Id
    tunnel_pid = $tunnel.Id
    gateway_port = $Port
    upstream_port = $UpstreamPort
    expires_at = $config.expires_at
    origin = ''
    invite_url = ''
}
$state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8
for ($attempt = 0; $attempt -lt 90; $attempt++) {
    Start-Sleep -Seconds 1
    $tunnel.Refresh()
    if ($tunnel.HasExited) { throw 'Tunnel exited; check .runtime/manager_tunnel_error.log.' }
    $log = Get-Content -LiteralPath $tunnelLog -Raw -ErrorAction SilentlyContinue
    $match = [regex]::Match([string]$log, 'https://[a-z0-9-]+\.trycloudflare\.com')
    if ($match.Success -and $log -match 'Registered tunnel connection') {
        $state.origin = $match.Value
        $state.invite_url = $match.Value + '/invite#' + $config.invite_secret
        $state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8
        [pscustomobject]@{
            status = 'link_created_not_yet_verified'
            gateway_pid = $gateway.Id
            tunnel_pid = $tunnel.Id
            origin = $state.origin
            expires_at = $state.expires_at
            private_state_file = $statePath
        } | ConvertTo-Json
        exit 0
    }
}
throw 'No tunnel address yet; check the tunnel log before starting another instance.'
} catch {
    # Only stop processes created by this invocation, never an existing service.
    foreach ($child in @($tunnel, $gateway)) {
        if ($null -ne $child) {
            try {
                $child.Refresh()
                if (-not $child.HasExited) { $child.Kill(); $child.WaitForExit(5000) | Out-Null }
            } catch { }
        }
    }
    if ($null -ne $state) {
        $state.status = 'startup_failed'
        $state.origin = ''
        $state.invite_url = ''
        $state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8
    }
    throw
}

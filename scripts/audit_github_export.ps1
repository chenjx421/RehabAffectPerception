[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) '..'),
    [switch]$IncludeUntrackedSource
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = (Resolve-Path -LiteralPath $RepositoryRoot).Path
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'git is required' }

function Get-GitPathList([string]$Repository) {
    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = 'git'
    $psi.Arguments = '-c core.quotepath=false -C "' + $Repository + '" ls-files -z'
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $psi
    [void]$process.Start()
    $raw = $process.StandardOutput.ReadToEnd()
    $null = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) { throw "git file listing failed: $($process.ExitCode)" }
    return @($raw -split "`0" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

$paths = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
foreach ($item in (Get-GitPathList $root)) { [void]$paths.Add($item) }

if ($IncludeUntrackedSource) {
    $sourceRoots = @('src', 'scripts', 'tests', 'configs', 'docs')
    foreach ($sourceRoot in $sourceRoots) {
        $fullRoot = Join-Path $root $sourceRoot
        if (-not (Test-Path -LiteralPath $fullRoot)) { continue }
        Get-ChildItem -LiteralPath $fullRoot -File -Recurse -Force |
            ForEach-Object {
                $relative = $_.FullName.Substring($root.Length).TrimStart('\')
                [void]$paths.Add($relative)
            }
    }
}

$secretPatterns = @(
    '(?i)sk-[A-Za-z0-9]{20,}',
    '(?i)(api[_-]?key|secret[_-]?key|access[_-]?token|bearer)\s*[:=]\s*[^\s]{12,}',
    '(?i)(password|passwd|private[_-]?key)\s*[:=]\s*[^\s]{6,}',
    '(?i)-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----',
    '(?i)trycloudflare\.com.*(token|secret|key)'
)

$sensitivePathPatterns = @(
    '(?i)(^|\\)(\.runtime|work|tmp|outputs?|output\\playwright|\.playwright-cli|\.tools|data\\raw|data\\processed)(\\|$)',
    '(?i)(\.mp4|\.mov|\.avi|\.mkv|\.wav|\.mp3|\.h5|\.sqlite3?|\.db|\.pem|\.key|\.pfx|\.p12)$',
    '(?i)(iep|diagnos|portrait|face|screenshot|invite|cookie|session|学生资料|人脸|截图)'
)

$readableExtensions = @('.ps1','.py','.js','.ts','.tsx','.jsx','.json','.yaml','.yml','.toml','.ini','.cfg','.env','.md','.txt','.csv','.html','.css','.sql','.xml')
$findings = [System.Collections.Generic.List[object]]::new()

foreach ($relative in $paths) {
    $full = Join-Path $root $relative
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) { continue }

    foreach ($pattern in $sensitivePathPatterns) {
        if ($relative -match $pattern) {
            $findings.Add([pscustomobject]@{ Type = 'PATH'; Path = $relative; Detail = 'sensitive or runtime path' })
            break
        }
    }

    $extension = [System.IO.Path]::GetExtension($full).ToLowerInvariant()
    if ($readableExtensions -notcontains $extension) { continue }
    try { $content = Get-Content -LiteralPath $full -Raw -ErrorAction Stop }
    catch {
        $findings.Add([pscustomobject]@{ Type = 'READ'; Path = $relative; Detail = $_.Exception.Message })
        continue
    }
    foreach ($pattern in $secretPatterns) {
        if ($content -match $pattern) {
            $findings.Add([pscustomobject]@{ Type = 'CONTENT'; Path = $relative; Detail = 'secret pattern matched' })
        }
    }
}

Write-Host 'GitHub export read-only audit'
Write-Host "Repository: $root"
Write-Host "Files checked: $($paths.Count)"
Write-Host 'Read-only: no deletion, database change, cloud action, or git push.'

if ($findings.Count -eq 0) {
    Write-Host 'Result: no path or text rule matched. Manual review is still required.' -ForegroundColor Green
    exit 0
}

Write-Host "Result: $($findings.Count) items need manual handling:" -ForegroundColor Yellow
$findings | Sort-Object Path,Type | Format-Table -AutoSize
Write-Host 'Remove, redact, or ignore these items before making a public version commit.' -ForegroundColor Yellow
exit 2

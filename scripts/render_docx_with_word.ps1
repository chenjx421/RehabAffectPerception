param(
    [Parameter(Mandatory = $true)][string]$InputPath,
    [Parameter(Mandatory = $true)][string]$OutputPdf
)

$ErrorActionPreference = "Stop"
$resolvedInput = (Resolve-Path -LiteralPath $InputPath).Path
$resolvedOutput = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $OutputPdf))
$parent = Split-Path -Parent $resolvedOutput
[System.IO.Directory]::CreateDirectory($parent) | Out-Null

$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
$document = $null
try {
    $document = $word.Documents.Open($resolvedInput, $false, $true)
    $document.ExportAsFixedFormat($resolvedOutput, 17)
}
finally {
    if ($null -ne $document) {
        $document.Close($false)
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($document) | Out-Null
    }
    $word.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

Write-Output $resolvedOutput

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$folder = Join-Path $root 'outputs/source_word_20261012'
$source = Join-Path $folder '辅读学校Demo2_源码汇编与系统说明_20261012.docx'
$pdf = Join-Path $folder 'review.pdf'
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
$document = $null
try {
    $document = $word.Documents.Open($source, $false, $false)
    Write-Output 'Word document opened.'
    foreach ($toc in $document.TablesOfContents) { $toc.Update() }
    $document.Repaginate()
    foreach ($toc in $document.TablesOfContents) { $toc.UpdatePageNumbers() }
    $document.Save()
    Write-Output ('Pages: ' + $document.ComputeStatistics(2))
    $document.ExportAsFixedFormat($pdf, 17)
    Write-Output 'Rendered PDF for verification.'
} finally {
    if ($null -ne $document) {
        $document.Close($false)
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($document) | Out-Null
    }
    $word.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
}

param([switch]$Focus, [switch]$FormControls, [string]$NamePattern = '.', [string]$InvokeName = '', [string]$SetName = '', [string]$SetValue = '')
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$cloudProcess = Get-Process msedge | Where-Object { $_.MainWindowTitle -match '\u8f7b\u91cf\u4e91|\u8f7b\u91cf\u5e94\u7528|\u817e\u8baf\u4e91' } | Select-Object -First 1
if (-not $cloudProcess) { throw 'Cloud console browser window not found' }
$cloudWindow = [System.Windows.Automation.AutomationElement]::FromHandle($cloudProcess.MainWindowHandle)
if ($Focus) { $cloudWindow.SetFocus() }
if ($SetName) {
    $allowedFields = @{
        ([string][char]0x8F93 + [char]0x5165 + 'IP' + [char]0x5730 + [char]0x5740 + [char]0x6216 + 'CIDR' + [char]0x6BB5) = '0.0.0.0/0'
        ([string][char]0x5982 + '53,80,443' + [char]0x6216 + '80-90') = '443'
        ([string][char]0x53EF + [char]0x8F93 + [char]0x5165 + '60' + [char]0x4E2A + [char]0x5B57 + [char]0x7B26) = 'RehabAffect HTTPS'
    }
    if (-not $allowedFields.ContainsKey($SetName) -or $allowedFields[$SetName] -ne $SetValue) { throw 'Only the approved HTTPS firewall fields may be filled' }
    $condition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, $SetName)
    $candidates = @($cloudWindow.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition) | Where-Object { $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Edit })
    if ($candidates.Count -ne 1) { throw 'Expected one firewall input' }
    $pattern = $candidates[0].GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
    if ($pattern.Current.Value -and $pattern.Current.Value -ne $SetValue) { throw 'Existing field differs; not overwritten' }
    $pattern.SetValue($SetValue)
}
if ($InvokeName) {
    $condition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, $InvokeName)
    $matches = $cloudWindow.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)
    $visible = @($matches | Where-Object {
        $_.Current.BoundingRectangle.Width -gt 0 -and $_.Current.BoundingRectangle.Height -gt 0 -and
        $_.Current.BoundingRectangle.Y -ge 120 -and $_.Current.BoundingRectangle.Y -lt 1529
    })
    if ($visible.Count -gt 1) {
        $visible = @($visible | Where-Object { $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Hyperlink })
    }
    if ($visible.Count -ne 1) { throw 'Expected exactly one visible named control' }
    $invoker = $visible[0].GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
    $invoker.Invoke()
}
$elements = $cloudWindow.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
$items = @()
for ($index = 0; $index -lt [Math]::Min($elements.Count, 1200); $index++) {
    $item = $elements.Item($index).Current
    if ((($item.Name -match $NamePattern) -or ($FormControls -and $item.ControlType.ProgrammaticName -match 'Edit|ComboBox')) -and -not $item.IsPassword) {
        $items += [PSCustomObject]@{ Name=$item.Name; Type=$item.ControlType.ProgrammaticName; AutomationId=$item.AutomationId; Class=$item.ClassName; X=$item.BoundingRectangle.X; Y=$item.BoundingRectangle.Y; W=$item.BoundingRectangle.Width; H=$item.BoundingRectangle.Height }
    }
}
$items | ConvertTo-Json -Depth 3 -Compress

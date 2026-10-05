param([string]$mode)
$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'Battery Tray.lnk'

Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
    Where-Object CommandLine -match 'battery_monitor' |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

if ($mode -eq 'uninstall') { Remove-Item $lnk -ErrorAction SilentlyContinue; exit }

$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$s.TargetPath = (Get-Command pyw).Source
$s.Arguments = '"' + (Join-Path $PSScriptRoot 'battery_monitor.py') + '"'
$s.WorkingDirectory = $PSScriptRoot
$s.Description = 'Battery Tray'
$s.Save()

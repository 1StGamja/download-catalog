# Creates "Download Catalog.lnk" in the project root (double-click to start the tray app without a console).
# Usage: powershell -ExecutionPolicy Bypass -File packaging\make_shortcut.ps1
$root = Split-Path $PSScriptRoot -Parent
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) { throw "Create the virtual environment first (see README)." }
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut((Join-Path $root "Download Catalog.lnk"))
$lnk.TargetPath = $pythonw
$lnk.Arguments = '"' + (Join-Path $root "run.pyw") + '"'
$lnk.WorkingDirectory = $root
$lnk.Description = "Download Catalog"
$lnk.Save()
Write-Output "Created: $(Join-Path $root 'Download Catalog.lnk')"

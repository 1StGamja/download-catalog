# Build the installer: dist\DownloadCatalog-Setup-<version>.exe
# Usage: powershell -ExecutionPolicy Bypass -File packaging\build.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
          "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 is required: winget install JRSoftware.InnoSetup" }

$icon = Join-Path $root "packaging\app.ico"
& $py (Join-Path $root "packaging\make_icon.py") $icon
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
& $py -m PyInstaller --noconfirm --clean --windowed --name DownloadCatalog `
    --icon $icon --paths (Join-Path $root "src") `
    --hidden-import pystray._win32 `
    --distpath (Join-Path $root "dist") --workpath (Join-Path $root "build") --specpath (Join-Path $root "build") `
    (Join-Path $root "packaging\entry.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
& $iscc (Join-Path $root "packaging\installer.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup compile failed" }
Get-ChildItem (Join-Path $root "dist\*.exe") | Select-Object Name, @{n='MB';e={[math]::Round($_.Length/1MB,1)}}

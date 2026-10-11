# Installer test: silent install / uninstall, startup choice, update-over-install.
# Usage: powershell -ExecutionPolicy Bypass -File tests\manual\installer_test.ps1
# A separate mutex name is compiled in, so a running Download Catalog on this PC is not touched.
$ErrorActionPreference = "Stop"
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
$out = Join-Path $env:TEMP "dc_installer_test"
New-Item -ItemType Directory -Force $out | Out-Null
& $iscc /Q "/DAppMutexName=DownloadCatalog_InstallerTest" "/O$out" "/FTestSetup" (Join-Path $root "packaging\installer.iss") | Out-Null
$setup = Join-Path $out "TestSetup.exe"
$run = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$dir = Join-Path $env:TEMP "dc_install_target"
$script:fail = 0

function RunVal { (Get-ItemProperty $run -ErrorAction SilentlyContinue).DownloadCatalog }
function Check($label, $cond) {
    if ($cond) { Write-Output "OK   $label" } else { Write-Output "FAIL $label"; $script:fail++ }
}
function Inst($tasks) {
    $p = Start-Process $setup "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LANG=korean /DIR=`"$dir`" /TASKS=`"$tasks`"" -Wait -PassThru
    return $p.ExitCode
}
function Uninst {
    $un = Get-ChildItem $dir -Filter "unins*.exe" | Select-Object -First 1
    Start-Process $un.FullName "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART" -Wait
    Start-Sleep 2
}

$before = RunVal
Check "no startup entry before test" (-not $before)

$code = Inst "autostart"
Check "install (autostart) exit code 0" ($code -eq 0)
Check "DownloadCatalog.exe installed" (Test-Path "$dir\DownloadCatalog.exe")
$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Download Catalog.lnk"
Check "Start-menu shortcut created" (Test-Path $startMenu)
Check "startup entry registered and points to installed exe" ((RunVal) -eq "`"$dir\DownloadCatalog.exe`"")
Uninst
Check "uninstall removes folder" (-not (Test-Path $dir))
Check "uninstall removes startup entry" (-not (RunVal))

$code = Inst "manual"
Check "install (manual) exit code 0" ($code -eq 0)
Check "manual choice: no startup entry" (-not (RunVal))
Uninst

Inst "autostart" | Out-Null
$code = Inst "manual"
Check "update-over-install exits 0" ($code -eq 0)
Check "switching to manual on update removes startup entry" (-not (RunVal))
Uninst
Check "final cleanup: folder gone and no startup entry" ((-not (Test-Path $dir)) -and (-not (RunVal)))

if ($script:fail -eq 0) { Write-Output "`nALL OK" } else { Write-Output "`nSOME FAILED ($script:fail)"; exit 1 }

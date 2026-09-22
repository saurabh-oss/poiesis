# Raise Windows' GPU timeout so a long model batch cannot bugcheck the machine.
#
# Windows kills a GPU kernel that runs longer than TdrDelay seconds (2 by default)
# and, when the driver cannot recover, bugchecks with VIDEO_TDR_FAILURE (0x116).
# A laptop GPU that thermally throttles during a sustained local-model build can
# push one batch past 2 s; this happened on a Legion with an RTX 5070 Ti on
# 2026-09-22. 60 s gives a slow batch room to finish instead of taking Windows
# down. Applies after a reboot. Run from an elevated PowerShell:
#
#   Set-ExecutionPolicy -Scope Process Bypass; .\scripts\raise-gpu-timeout.ps1
#
# To undo: remove the two values and reboot.
$ErrorActionPreference = "Stop"
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Write-Host "This needs an elevated PowerShell: right-click PowerShell, 'Run as administrator', then run it again." -ForegroundColor Red
  exit 1
}
$key = 'HKLM:\SYSTEM\CurrentControlSet\Control\GraphicsDrivers'
New-ItemProperty -Path $key -Name TdrDelay -Value 60 -PropertyType DWord -Force | Out-Null
New-ItemProperty -Path $key -Name TdrDdiDelay -Value 60 -PropertyType DWord -Force | Out-Null
Get-ItemProperty $key | Select-Object TdrDelay, TdrDdiDelay | Format-List
Write-Host "Set. Reboot for it to take effect." -ForegroundColor Green

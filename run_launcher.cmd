@echo off
setlocal
set "PS=powershell.exe"
where pwsh >nul 2>&1 && set "PS=pwsh"
%PS% -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launcher.ps1"

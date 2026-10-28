@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0activate_build.ps1" -Compile %*
exit /b %errorlevel%

@echo off
REM Launch the 3D AI Generator web UI (with CLI progress bar).
setlocal
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\launch_webui.py" %*
exit /b %errorlevel%

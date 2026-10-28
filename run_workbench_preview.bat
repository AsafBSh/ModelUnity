@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Project Python environment missing. See docs\DEVELOPMENT.md.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m scripts.workbench_preview %*

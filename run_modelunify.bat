@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Project Python environment missing. See docs\DEVELOPMENT.md.
    pause
    exit /b 1
)
echo Starting ModelUnify Mesh Workbench...
".venv\Scripts\python.exe" -u -m scripts.launch_workbench %*
if errorlevel 1 pause

@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set "COMFY_MODEL=%~1"
if not defined COMFY_MODEL set "COMFY_MODEL=trellis"
"%~dp0.venv\Scripts\python.exe" -m scripts.comfyui_host setup --model "%COMFY_MODEL%"
pause

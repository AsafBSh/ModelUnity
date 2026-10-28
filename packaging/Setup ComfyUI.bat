@echo off
setlocal
cd /d "%~dp0app"
set "COMFY_MODEL=%~1"
if not defined COMFY_MODEL (
  echo Optional ComfyUI setup: Windows / NVIDIA CUDA
  echo Downloads a separate runtime and the selected multi-GB checkpoints.
  echo 1. TRELLIS.2
  echo 2. Pixal3D single image
  echo 3. Pixal3D fixed-orbit multiview
  echo 4. All variants
  choice /c 1234 /n /m "Select models: "
  if errorlevel 4 (set "COMFY_MODEL=all") else if errorlevel 3 (set "COMFY_MODEL=pixal-mv") else if errorlevel 2 (set "COMFY_MODEL=pixal") else (set "COMFY_MODEL=trellis")
)
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
"%~dp0python\python.exe" -s -m scripts.comfyui_host setup --model "%COMFY_MODEL%"
if errorlevel 1 (
  echo Setup failed. Review the error above. Existing projects and models are preserved.
  pause
  exit /b 1
)
echo Setup complete. Select the model in Generate and use Check model.
pause

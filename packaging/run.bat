@echo off
REM ============================================================
REM  Modelunify (3D AI Generator) - portable launcher
REM
REM  Bundle layout (this file sits at the bundle root):
REM      run.bat                  (you are here)
REM      python\python.exe        embeddable CPython
REM      app\scripts\launch_workbench.py
REM      app\config.yaml, vendor\, assets\, ...
REM      models_cache\            HF + torch caches (created on first run)
REM
REM  Nothing is installed system-wide. Everything (env vars, caches,
REM  output meshes) stays inside this folder, so the whole bundle is
REM  movable / copyable / runnable from a USB drive.
REM ============================================================

setlocal ENABLEEXTENSIONS

REM 1. Anchor every path to this folder. %~dp0 always ends with a backslash.
set "HERE=%~dp0"
cd /d "%HERE%"

REM 2. Confine ALL cache writes to the bundle. The user's
REM    %USERPROFILE%\.cache stays untouched and the bundle keeps
REM    everything it downloads in one place.
set "HF_HOME=%HERE%models_cache\huggingface"
set "HUGGINGFACE_HUB_CACHE=%HF_HOME%\hub"
set "TRANSFORMERS_CACHE=%HF_HOME%\transformers"
set "HF_MODULES_CACHE=%HF_HOME%\modules"
set "TORCH_HOME=%HERE%models_cache\torch"
set "TORCH_EXTENSIONS_DIR=%HERE%models_cache\torch_extensions"
set "HY3DGEN_MODELS=%HERE%models_cache\hy3dgen"
set "U2NET_HOME=%HERE%models_cache\rembg"
set "MPLCONFIGDIR=%HERE%models_cache\matplotlib"
set "NUMBA_CACHE_DIR=%HERE%models_cache\numba"
set "XDG_CACHE_HOME=%HERE%models_cache"
set "GRADIO_TEMP_DIR=%HERE%app\.gradio_tmp"
set "TMP=%HERE%models_cache\tmp"
set "TEMP=%HERE%models_cache\tmp"

REM 3. Make the embedded Python the only Python this process knows about.
set "PYTHONHOME=%HERE%python"
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"
REM    Put the app on the import path so `from scripts import ...` and the
REM    config.yaml-relative paths in web_ui.py resolve correctly.
set "PYTHONPATH=%HERE%app"
REM    Prepend our python\ + Scripts to PATH so spawned subprocesses (gradio
REM    workers, huggingface CLI) pick up the embedded interpreter and its
REM    bundled DLLs (cudnn, cublas, ...) rather than anything the user
REM    might have installed system-wide.
set "PATH=%HERE%python;%HERE%python\Scripts;%HERE%python\Lib\site-packages\torch\lib;%PATH%"

REM 4. Make sure folders exist before Python tries to write to them.
if not exist "%HERE%models_cache"          mkdir "%HERE%models_cache"
if not exist "%TMP%"                       mkdir "%TMP%"
if not exist "%GRADIO_TEMP_DIR%"           mkdir "%GRADIO_TEMP_DIR%"
if not exist "%HERE%app\inputs"            mkdir "%HERE%app\inputs"
if not exist "%HERE%app\outputs"           mkdir "%HERE%app\outputs"
if not exist "%HERE%app\bms_export"        mkdir "%HERE%app\bms_export"
if not exist "%HERE%app\pretrained_weights" mkdir "%HERE%app\pretrained_weights"

REM 5. Sanity check: the bundled interpreter must exist.
if not exist "%HERE%python\python.exe" (
    echo.
    echo [FATAL] Bundled Python is missing.
    echo         Expected: "%HERE%python\python.exe"
    echo         Re-extract the .7z archive; do NOT mix folders from
    echo         different Modelunify versions.
    echo.
    pause
    exit /b 2
)

REM 6. Open Mesh Workbench in its own Edge/Chrome application window.
REM    --browser opens a browser tab; --legacy retains the original UI.
"%HERE%python\python.exe" "%HERE%app\scripts\launch_workbench.py" %*
set "RC=%ERRORLEVEL%"

REM 7. Keep the window open on error so the user can read the traceback.
if not "%RC%"=="0" (
    echo.
    echo [Modelunify exited with code %RC%]
    echo Press any key to close this window.
    pause >nul
)
exit /b %RC%

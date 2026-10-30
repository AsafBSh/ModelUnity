<#
.SYNOPSIS
    Build a portable, no-install Modelunify bundle (Windows x64 + NVIDIA CUDA 12.4).

.DESCRIPTION
    Produces  dist\Modelunify-<version>-portable\         (the working folder)
        and   dist\Modelunify-<version>-portable.7z       (the redistributable)

    The bundle layout is what ComfyUI / Forge portable use:

        Modelunify-<version>-portable\
            run.bat                   <-- user double-clicks this
            Open inputs folder.bat    <-- convenience shortcut
            Open outputs folder.bat   <-- convenience shortcut
            README.txt
            python\                   embeddable CPython 3.11 (~25 MB)
            app\                      your source code + vendor dirs
            models_cache\             (created on first run; HF + torch caches)

    Pretrained model weights are NOT bundled (license-cleanest path) and are
    installed explicitly through Models after launch. Size depends on the
    selected model and its shared dependencies; inference never installs them.

.PARAMETER FromVenv
    Skip the from-scratch pip install. Copy the existing .venv\Lib\site-packages
    into the embeddable Python instead. Much faster (~2 min vs ~25 min) but
    less reproducible. Use during development; do a clean build for releases.

.PARAMETER SkipArchive
    Don't run 7-Zip at the end. Useful when iterating on the layout.

.PARAMETER PythonVersion
    Embeddable Python version to fetch. Defaults to 3.11.9 (same major.minor
    as the project's .venv to avoid ABI surprises with the wheels we install).

.EXAMPLE
    .\build_portable.ps1                   # clean release build
    .\build_portable.ps1 -FromVenv         # fast dev build, copies your .venv
    .\build_portable.ps1 -SkipArchive      # just produce the folder, no .7z
#>

[CmdletBinding()]
param(
    [switch]$FromVenv,
    [switch]$SkipArchive,
    [string]$PythonVersion = '3.11.9',
    [string]$OutputDirectory,
    [switch]$PlanOnly,
    [switch]$IncludePaint,
    [string]$PaintWheelDirectory
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

# ----- 0. Version + paths -----------------------------------------------------
$verLine = Get-Content "$PSScriptRoot\scripts\_version.py" |
           Where-Object { $_ -match 'MODELUNIFY_VERSION' } | Select-Object -First 1
if ($verLine -match '"([^"]+)"') { $appVersion = $matches[1] } else { $appVersion = '0.0' }

$BundleName = "Modelunify-$appVersion-portable"
$DistDir    = Join-Path $PSScriptRoot 'dist'
$BundleDir  = if ($OutputDirectory) { [IO.Path]::GetFullPath($OutputDirectory) } else { Join-Path $DistDir $BundleName }
if (-not $BundleDir.StartsWith($DistDir + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Build output must be a new directory inside this workspace dist/.' }
$PyDir      = Join-Path $BundleDir 'python'
$AppDir     = Join-Path $BundleDir 'app'
$BuildTmp   = Join-Path $DistDir ('_build_tmp_' + [guid]::NewGuid().ToString('N'))

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Modelunify portable build" -ForegroundColor Cyan
Write-Host "  version : $appVersion" -ForegroundColor Cyan
Write-Host "  output  : $BundleDir" -ForegroundColor Cyan
Write-Host "  mode    : $(if ($FromVenv) {'FromVenv (fast)'} else {'Clean install (reproducible)'})" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Plan-only is read-only, including when existing distributions contain user data.
if ($PlanOnly) {
    Write-Host "Sources: scripts/, tools/, vendor/, assets/, docs/."
    Write-Host "Bundle: $BundleDir; scratch: $BuildTmp; IncludePaint=$IncludePaint"
    Write-Host "Existing outputs are never cleaned. CUDA wheels use requirements-cuda124.txt."
    return
}
if (Test-Path -LiteralPath $BundleDir) { throw "Output exists and is preserved: $BundleDir. Choose -OutputDirectory dist/<fresh-name>." }
if ($IncludePaint) {
    $paintCheckpoint = Join-Path $PSScriptRoot 'vendor/Hunyuan3D-2.1/hy3dpaint/ckpt/RealESRGAN_x4plus.pth'
    if (-not (Test-Path -LiteralPath $paintCheckpoint)) { throw 'Paint requires the separately licensed RealESRGAN_x4plus.pth checkpoint.' }
    if (-not $FromVenv -and (-not $PaintWheelDirectory -or -not (Get-ChildItem -LiteralPath $PaintWheelDirectory -Filter '*cp311*win_amd64.whl'))) { throw 'Clean paint builds require cp311 win_amd64 native wheels in -PaintWheelDirectory, built against torch 2.5.1+cu124.' }
}

New-Item -ItemType Directory -Path $BundleDir | Out-Null
New-Item -ItemType Directory -Path $PyDir     | Out-Null
New-Item -ItemType Directory -Path $AppDir    | Out-Null
New-Item -ItemType Directory -Path $BuildTmp  | Out-Null

# ----- 2. Embeddable Python ---------------------------------------------------
Write-Host "[1/7] Fetching embeddable Python $PythonVersion ..." -ForegroundColor Yellow
$embedUrl  = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$embedZip  = Join-Path $BuildTmp "python-$PythonVersion-embed-amd64.zip"
if (-not (Test-Path $embedZip)) {
    Invoke-WebRequest -Uri $embedUrl -OutFile $embedZip -UseBasicParsing
}
Expand-Archive -Path $embedZip -DestinationPath $PyDir -Force

# Enable `site` so pip + Lib\site-packages work. Embeddable Python ships with
# `import site` commented out in pythonNN._pth; uncomment it and append our
# `Lib\site-packages` line so wheels we install are discoverable.
$pthFile = Get-ChildItem -Path $PyDir -Filter 'python*._pth' | Select-Object -First 1
if (-not $pthFile) { throw "Could not find python._pth inside embeddable Python." }
$pth = Get-Content $pthFile.FullName
$pth = $pth -replace '^#\s*import site', 'import site'
if (-not ($pth -contains 'Lib\site-packages')) {
    $pth += 'Lib\site-packages'
}
$pth | Set-Content -Encoding ASCII $pthFile.FullName
Write-Host "      Patched $($pthFile.Name) (site enabled, site-packages on path)."

$EmbedPy = Join-Path $PyDir 'python.exe'

# ----- 3. Site-packages: clean install OR copy from existing .venv -----------
if ($FromVenv) {
    $srcVenv = Join-Path $PSScriptRoot '.venv\Lib\site-packages'
    if (-not (Test-Path $srcVenv)) {
        throw "-FromVenv requested but '$srcVenv' does not exist. Run the standard setup first."
    }
    Write-Host "[2/7] Copying site-packages from existing .venv ..." -ForegroundColor Yellow
    $destSP = Join-Path $PyDir 'Lib\site-packages'
    New-Item -ItemType Directory -Path $destSP -Force | Out-Null
    # Only strip __pycache__ and .git here. Do NOT exclude "tests"/"test"
    # directories: several packages ship `tests` SUBPACKAGES that are imported
    # at runtime (e.g. numpy.testing -> numpy._core.tests._natype, pulled in by
    # scipy -> transformers -> diffusers). Excluding them at copy time breaks
    # the whole import chain with `ModuleNotFoundError: No module named
    # 'numpy._core.tests'`. Bytecode/test trimming, if any, happens in step 5.
    robocopy $srcVenv $destSP `
        /MIR /NFL /NDL /NJH /NJS /NP `
        /XD __pycache__ .git `
        /XF *.pyc *.pyo | Out-Null
    # robocopy returns 0..7 on success
    if ($LASTEXITCODE -ge 8) { throw "robocopy site-packages failed (exit $LASTEXITCODE)" }

    # Also copy the venv's Scripts\ exe shims that are imported as console
    # entry points (e.g. cv2's shipped binaries already live inside site-packages,
    # so this is mostly a no-op, but huggingface-cli etc. live in Scripts).
    $srcScripts = Join-Path $PSScriptRoot '.venv\Scripts'
    $destScripts = Join-Path $PyDir 'Scripts'
    if (Test-Path $srcScripts) {
        New-Item -ItemType Directory -Path $destScripts -Force | Out-Null
        robocopy $srcScripts $destScripts `
            /E /NFL /NDL /NJH /NJS /NP `
            /XF activate* deactivate* python* pythonw* | Out-Null
    }
} else {
    Write-Host "[2/7] Bootstrapping pip into embeddable Python ..." -ForegroundColor Yellow
    $getPip = Join-Path $BuildTmp 'get-pip.py'
    Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile $getPip -UseBasicParsing
    & $EmbedPy $getPip --no-warn-script-location --no-cache-dir
    if ($LASTEXITCODE -ne 0) { throw "get-pip failed (exit $LASTEXITCODE)" }

    Write-Host "      Installing torch / torchvision / torchaudio (CUDA 12.4) ..." -ForegroundColor Yellow
    & $EmbedPy -m pip install --no-warn-script-location --no-cache-dir `
        -r "$PSScriptRoot\requirements-cuda124.txt" `
        --index-url 'https://download.pytorch.org/whl/cu124'
    if ($LASTEXITCODE -ne 0) { throw "torch install failed (exit $LASTEXITCODE)" }

    Write-Host "      Installing project requirements.txt ..." -ForegroundColor Yellow
    & $EmbedPy -m pip install --no-warn-script-location --no-cache-dir `
        -r "$PSScriptRoot\requirements.txt" -c "$PSScriptRoot\requirements-windows-lock.txt" -c "$PSScriptRoot\requirements-cuda124.txt"
    if ($LASTEXITCODE -ne 0) { throw "requirements install failed (exit $LASTEXITCODE)" }

    # Editable install of vendored hy3dgen, mirroring what setup-from-scratch does.
    Write-Host "      Editable-installing vendor/Hunyuan3D-2 (hy3dgen) ..." -ForegroundColor Yellow
    & $EmbedPy -m pip install --no-warn-script-location --no-cache-dir `
        --no-deps -e "$PSScriptRoot\vendor\Hunyuan3D-2"
    if ($LASTEXITCODE -ne 0) { throw "hy3dgen editable install failed (exit $LASTEXITCODE)" }
}

# ----- 4. Copy app code (source + vendor + assets + config) -------------------
Write-Host "[3/7] Copying application code into app\ ..." -ForegroundColor Yellow

$srcRoot = $PSScriptRoot
$copyItems = @(
    'scripts',
    'tools',
    'vendor',
    'assets',
    'docs',
    'config.yaml',
    'requirements.txt',
    'requirements-cuda124.txt',
    'requirements-windows-lock.txt',
    'requirements-optional.txt',
    'benchmarks',
    'README.md'
)
foreach ($item in $copyItems) {
    $srcPath = Join-Path $srcRoot $item
    if (-not (Test-Path $srcPath)) { continue }
    if (Test-Path $srcPath -PathType Container) {
        $destPath = Join-Path $AppDir $item
        # mini_trainset is Hunyuan's example TRAINING dataset (deeply nested
        # SHA-named dirs, 278-char paths). It's useless for inference and its
        # >260-char paths break later Remove-Item cleanup when the OS has
        # LongPathsEnabled=0. Exclude it (and other train/example scratch dirs).
        robocopy $srcPath $destPath `
            /E /NFL /NDL /NJH /NJS /NP `
            /XD __pycache__ .git .venv build .pytest_cache mini_trainset inbox outbox ckpt checkpoints pretrained_weights models_cache .cache `
            /XF *.pyc *.pyo *.pyd *.dll *.lib *.exp *.obj *.pdb *.ilk *.o *.so *.pyd.lock *.pth *.pt *.ckpt *.safetensors *.env* | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "robocopy '$item' failed (exit $LASTEXITCODE)" }
    } else {
        Copy-Item $srcPath -Destination $AppDir -Force
    }
}

# Native extensions and the external checkpoint are an explicit build choice.
if ($IncludePaint) {
    $checkpointDir = Join-Path $AppDir 'vendor/Hunyuan3D-2.1/hy3dpaint/ckpt'
    New-Item -ItemType Directory -Path $checkpointDir -Force | Out-Null
    Copy-Item -LiteralPath $paintCheckpoint -Destination $checkpointDir
    $nativeRenderer = Join-Path $PSScriptRoot 'vendor/Hunyuan3D-2.1/hy3dpaint/DifferentiableRenderer'
    $nativeDestination = Join-Path $AppDir 'vendor/Hunyuan3D-2.1/hy3dpaint/DifferentiableRenderer'
    Get-ChildItem -LiteralPath $nativeRenderer -Filter '*cp311-win_amd64.pyd' | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $nativeDestination
    }
    if (-not $FromVenv) {
        foreach ($wheel in (Get-ChildItem -LiteralPath $PaintWheelDirectory -Filter '*.whl')) {
            & $EmbedPy -m pip install --no-deps $wheel.FullName
            if ($LASTEXITCODE -ne 0) { throw "Native wheel failed: $($wheel.Name)" }
        }
    }
} else {
    Write-Warning 'Shape-only bundle: paint requires checkpoint and matching native extensions. No CPU painting fallback.'
}

# Stub the user-data dirs so the app doesn't have to create them on first run.
foreach ($d in 'inputs','outputs','bms_export','pretrained_weights') {
    New-Item -ItemType Directory -Path (Join-Path $AppDir $d) -Force | Out-Null
}

# ----- 5. Make the hy3dgen editable install RELOCATABLE ----------------------
# The pip editable install writes an absolute path of THIS machine into
# `__editable___hy3dgen_*_finder.py`. Rewrite it to compute the path at
# runtime from sys.executable, so the bundle works wherever it's extracted.
Write-Host "[4/7] Making editable hy3dgen install relocatable ..." -ForegroundColor Yellow
$finder = Get-ChildItem -Path (Join-Path $PyDir 'Lib\site-packages') `
    -Filter '__editable___hy3dgen_*_finder.py' -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($finder) {
    # The _finder.py file is at  <bundle>\python\Lib\site-packages\<file>.py
    # so Path(__file__).resolve().parents[3] == <bundle>, and hy3dgen lives
    # at  <bundle>\app\vendor\Hunyuan3D-2\hy3dgen.
    $newMapping = @'
import pathlib as _modelunify_pl
_MODELUNIFY_BUNDLE = _modelunify_pl.Path(__file__).resolve().parents[3]
MAPPING: dict[str, str] = {'hy3dgen': str(_MODELUNIFY_BUNDLE / 'app' / 'vendor' / 'Hunyuan3D-2' / 'hy3dgen')}
'@
    $existing = Get-Content $finder.FullName -Raw
    if ($existing -match '_MODELUNIFY_BUNDLE') {
        Write-Host "      $($finder.Name) already relocatable, skipping."
    } else {
        $lines = Get-Content $finder.FullName
        $out = New-Object System.Collections.Generic.List[string]
        $replaced = $false
        foreach ($ln in $lines) {
            if (-not $replaced -and $ln -match '^\s*MAPPING:\s*dict\[str,\s*str\]\s*=') {
                $out.Add($newMapping) | Out-Null
                $replaced = $true
            } else {
                $out.Add($ln) | Out-Null
            }
        }
        if (-not $replaced) {
            throw "Could not find MAPPING line inside $($finder.Name). The pip editable layout may have changed - inspect the file manually."
        }
        $out | Set-Content -Encoding UTF8 $finder.FullName
        Write-Host "      Patched $($finder.Name)."
    }
} else {
    Write-Host "      (no editable hy3dgen finder found; nothing to patch)"
}

# ----- 6. Trim fat from site-packages -----------------------------------------
# ONLY __pycache__. We deliberately do NOT touch tests/ subdirectories:
# many packages (numpy, scipy, pandas, ...) ship `tests` subpackages that
# are imported at RUNTIME by other packages via chains like
#   scipy._lib._array_api -> numpy.testing -> numpy._core.tests._natype.
# Deleting them looks harmless but breaks transformers / diffusers imports
# with a `ModuleNotFoundError: No module named 'numpy._core.tests'`.
# The __pycache__ purge alone still shrinks the archive by a solid margin.
Write-Host "[5/7] Trimming __pycache__ from site-packages ..." -ForegroundColor Yellow
$sp = Join-Path $PyDir 'Lib\site-packages'
$trimScript = @'
import pathlib, shutil, sys
root = pathlib.Path(sys.argv[1])
trimmed = 0
for p in root.rglob("__pycache__"):
    try: shutil.rmtree(p); trimmed += 1
    except Exception: pass
print(f"   trimmed {trimmed} __pycache__ dirs")
'@
$trimPy = Join-Path $BuildTmp 'trim.py'
$trimScript | Set-Content -Encoding UTF8 $trimPy
& $EmbedPy $trimPy $sp

# ----- 7. Drop in launcher, helper bats, README -------------------------------
Write-Host "[6/7] Writing launcher + README into bundle root ..." -ForegroundColor Yellow
$packagingDir = Join-Path $PSScriptRoot 'packaging'
foreach ($f in 'run.bat','README.txt','Open inputs folder.bat','Open outputs folder.bat','Setup ComfyUI.bat') {
    $src = Join-Path $packagingDir $f
    if (Test-Path $src) {
        Copy-Item $src -Destination (Join-Path $BundleDir $f) -Force
    } else {
        Write-Warning "Expected $src to exist; skipping. (Run from a fresh checkout.)"
    }
}

# Check copied sources before archiving. These checks do not perform inference.
& $EmbedPy -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Portable dependency check failed.' }
$env:HF_HUB_OFFLINE = '1'
$env:GRADIO_ANALYTICS_ENABLED = 'False'
$checkArgs = @((Join-Path $AppDir 'scripts/check_environment.py'), '--ui')
if ($IncludePaint) { $checkArgs += '--require-paint' }
& $EmbedPy @checkArgs
if ($LASTEXITCODE -ne 0) { throw 'Portable offline UI/prerequisite check failed.' }
& $EmbedPy (Join-Path $AppDir 'scripts/workbench_preview.py') --check
if ($LASTEXITCODE -ne 0) { throw 'Portable CAD workbench construction failed.' }

# ----- 8. 7-Zip --------------------------------------------------------------
if ($SkipArchive) {
    Write-Host "[7/7] -SkipArchive given; not running 7-Zip." -ForegroundColor DarkYellow
} else {
    Write-Host "[7/7] Compressing with 7-Zip (this takes a few minutes) ..." -ForegroundColor Yellow
    $sevenZip = $null
    foreach ($cand in @(
        'C:\Program Files\7-Zip\7z.exe',
        'C:\Program Files (x86)\7-Zip\7z.exe',
        (Get-Command 7z -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
    )) {
        if ($cand -and (Test-Path $cand)) { $sevenZip = $cand; break }
    }
    if (-not $sevenZip) {
        Write-Warning "7z.exe not found. Install 7-Zip or pass -SkipArchive. Folder is ready at $BundleDir."
    } else {
        $archive = "$BundleDir.7z"
        if (Test-Path -LiteralPath $archive) { throw "Archive already exists and is preserved: $archive" }
        & $sevenZip a -t7z -mx=9 -mfb=273 -ms=on -mqs=on $archive "$BundleDir\*" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "7-Zip failed (exit $LASTEXITCODE)" }
        $sizeGB = [math]::Round((Get-Item $archive).Length / 1GB, 2)
        Write-Host "      Wrote $archive ($sizeGB GB)"
    }
}

# ----- Done -------------------------------------------------------------------
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Build complete." -ForegroundColor Green
Write-Host "  Folder : $BundleDir" -ForegroundColor Green
if (-not $SkipArchive) {
    Write-Host "  Archive: $DistDir\$BundleName.7z" -ForegroundColor Green
}
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Smoke test:  cd `"$BundleDir`"  &&  .\run.bat" -ForegroundColor Cyan

[CmdletBinding()]
param([string]$PythonExe = (Join-Path $PSScriptRoot '.venv/Scripts/python.exe'), [switch]$Compile)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$cudaVersion = & $PythonExe -c "import torch; print(torch.version.cuda or '')"
if ($LASTEXITCODE -ne 0 -or -not $cudaVersion) { throw 'Working NVIDIA CUDA torch is required.' }
if (-not $env:CUDA_HOME) { $env:CUDA_HOME = $env:CUDA_PATH }
if (-not $env:CUDA_HOME) { $env:CUDA_HOME = Join-Path $env:ProgramFiles "NVIDIA GPU Computing Toolkit/CUDA/v$cudaVersion" }
$nvcc = Join-Path $env:CUDA_HOME 'bin/nvcc.exe'
if (-not (Test-Path -LiteralPath $nvcc)) { throw "Install CUDA Toolkit $cudaVersion and set CUDA_HOME. The torch runtime cannot compile extensions." }
$nvccVersion = & $nvcc --version
if (-not ($nvccVersion -match "release $([regex]::Escape($cudaVersion)),")) { throw "CUDA Toolkit must match torch CUDA $cudaVersion. Found: $nvccVersion" }
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
if (-not (Test-Path -LiteralPath $vswhere)) { throw 'VS2022 Build Tools with C++ tools are required.' }
$vsPath = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
$vcvars = Join-Path $vsPath 'VC/Auxiliary/Build/vcvarsall.bat'
if (-not (Test-Path -LiteralPath $vcvars)) { throw 'C++ vcvarsall.bat was not found.' }
cmd /c "`"$vcvars`" amd64 >nul && set" | ForEach-Object {
    if ($_ -match '^([^=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process') }
}
if ($LASTEXITCODE -ne 0) { throw 'VS environment initialization failed.' }
$env:CUDA_PATH = $env:CUDA_HOME
$env:Path = (Join-Path $env:CUDA_HOME 'bin') + ';' + $env:Path
$env:DISTUTILS_USE_SDK = '1'
$env:MSSdk = '1'
Write-Host "Build environment: $PythonExe; CUDA Toolkit $cudaVersion; $vsPath"
if ($Compile) {
    Push-Location (Join-Path $PSScriptRoot 'vendor/Hunyuan3D-2.1/hy3dpaint/custom_rasterizer')
    try {
        & $PythonExe -m pip install --no-deps --no-build-isolation .
        if ($LASTEXITCODE -ne 0) { throw 'CUDA rasterizer build failed.' }
    } finally { Pop-Location }
    Push-Location (Join-Path $PSScriptRoot 'vendor/Hunyuan3D-2.1/hy3dpaint/DifferentiableRenderer')
    try {
        & $PythonExe setup.py build_ext --inplace
        if ($LASTEXITCODE -ne 0) { throw 'Mesh inpaint extension build failed.' }
    } finally { Pop-Location }
}

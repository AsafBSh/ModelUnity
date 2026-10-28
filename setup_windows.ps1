[CmdletBinding()]
param([string]$PythonExe, [string]$Environment = '.venv', [switch]$RepairDependencies)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$envPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot $Environment))
if (-not $envPath.StartsWith($PSScriptRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The development environment must be inside this workspace.'
}
$devPython = Join-Path $envPath 'Scripts/python.exe'
if (Test-Path $envPath) {
    & $devPython -c "import sys; assert sys.version_info[:2] == (3,11)"
    if ($LASTEXITCODE -ne 0) { throw 'Existing environment preserved. Check sandbox/base-Python access, or choose -Environment .venv-new and -PythonExe <Python 3.11>.' }
    if (-not $RepairDependencies) { throw 'Existing environment preserved. Use -RepairDependencies to explicitly reconcile its packages.' }
    $snapshotDir = Join-Path $PSScriptRoot '.runtime/setup-history'
    New-Item -ItemType Directory -Path $snapshotDir -Force | Out-Null
    & $devPython -m pip freeze --all | Set-Content -LiteralPath (Join-Path $snapshotDir ((Get-Date -Format 'yyyyMMdd-HHmmss') + '.txt'))
} else {
    if (-not $PythonExe) { throw 'Provide -PythonExe with a full, working CPython 3.11 x64 interpreter path.' }
    & $PythonExe -c "import sys,struct; assert sys.version_info[:2] == (3,11) and struct.calcsize('P') == 8"
    if ($LASTEXITCODE -ne 0) { throw 'CPython 3.11 x64 is required.' }
    & $PythonExe -m venv $envPath
    if ($LASTEXITCODE -ne 0) { throw 'venv creation failed; no existing environment was removed.' }
}
& $devPython -m pip install -r requirements-cuda124.txt --index-url https://download.pytorch.org/whl/cu124
if ($LASTEXITCODE -ne 0) { throw 'CUDA wheel installation failed.' }
& $devPython -m pip install -r requirements.txt -c requirements-windows-lock.txt -c requirements-cuda124.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency resolution failed; torch constraints prohibit CPU substitution.' }
& $devPython -m pip install --no-deps --no-build-isolation -e vendor/Hunyuan3D-2
if ($LASTEXITCODE -ne 0) { throw 'Vendored hy3dgen installation failed.' }
& $devPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependency consistency check failed.' }
& $devPython scripts/check_environment.py
if ($LASTEXITCODE -ne 0) { throw 'Environment smoke check failed.' }

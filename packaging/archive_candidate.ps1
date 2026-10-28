<# Package a validated candidate without projects, caches, inputs or QA outputs. #>
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$BundleDirectory, [string]$OutputArchive, [switch]$PlanOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$distRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot 'dist'))
$bundleRoot = [IO.Path]::GetFullPath($BundleDirectory)
if (-not $bundleRoot.StartsWith($distRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Bundle must be inside this workspace dist/.' }
if (-not $OutputArchive) { $OutputArchive = $bundleRoot + '.7z' }
$archivePath = [IO.Path]::GetFullPath($OutputArchive)
if (-not $archivePath.StartsWith($distRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or [IO.Path]::GetExtension($archivePath) -ne '.7z') { throw 'Archive must be a new .7z inside dist/.' }
foreach ($required in @('run.bat','python/python.exe','app/config.yaml','app/scripts/launch_workbench.py')) {
    if (-not (Test-Path -LiteralPath (Join-Path $bundleRoot $required))) { throw "Missing bundle component: $required" }
}
$entries = @('python','app/scripts','app/tools','app/vendor','app/assets','app/docs','app/config.yaml',
    'app/requirements.txt','app/requirements-cuda124.txt','app/requirements-windows-lock.txt','app/requirements-optional.txt',
    'app/README.md','app/benchmarks','run.bat','README.txt','Open inputs folder.bat','Open outputs folder.bat','Setup ComfyUI.bat')
foreach ($optional in @('BUILD_PROVENANCE.json','VALIDATION_SUMMARY.json')) {
    if (Test-Path -LiteralPath (Join-Path $bundleRoot $optional)) { $entries += $optional }
}
$exclusions = @('-xr!__pycache__','-xr!.git','-x!app\tools\instalod\inbox','-x!app\tools\instalod\inbox\*',
    '-x!app\tools\instalod\outbox','-x!app\tools\instalod\outbox\*')
if ($PlanOnly) {
    @{Bundle=$bundleRoot;Archive=$archivePath;Entries=$entries;Exclusions=$exclusions} | ConvertTo-Json -Depth 3
    return
}
if ((Test-Path -LiteralPath $archivePath) -or (Test-Path -LiteralPath ($archivePath+'.sha256'))) { throw 'Archive/checksum exists and is preserved; select a fresh output.' }
$sevenZip = @('C:\Program Files\7-Zip\7z.exe','C:\Program Files (x86)\7-Zip\7z.exe',
    (Get-Command 7z -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)) |
    Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if (-not $sevenZip) { throw '7-Zip is required to archive the candidate.' }
Push-Location -LiteralPath $bundleRoot
try {
    & $sevenZip a -t7z -mx=5 -mmt=4 -ms=on $archivePath @entries @exclusions
    if ($LASTEXITCODE -ne 0) { throw "7-Zip failed: $LASTEXITCODE" }
    $listing = & $sevenZip l -slt $archivePath
    if ($LASTEXITCODE -ne 0) { throw 'Archive listing failed.' }
    $paths = @($listing | Where-Object { $_ -match '^Path = ' } | ForEach-Object { $_.Substring(7) } | Select-Object -Skip 1)
    $privatePaths = @($paths | Where-Object {
        $_ -match '^(models_cache|app[/\\](projects|\.runtime|\.gradio_tmp|inputs|outputs|bms_export|pretrained_weights))([/\\]|$)' -or
        $_ -match '^app[/\\]tools[/\\]instalod[/\\](inbox|outbox)([/\\]|$)'
    })
    if ($privatePaths.Count) { throw "Archive unexpectedly contains user/QA data: $($privatePaths -join ', ')" }
    & $sevenZip t $archivePath
    if ($LASTEXITCODE -ne 0) { throw 'Archive integrity check failed.' }
    $digest = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    "$digest  $([IO.Path]::GetFileName($archivePath))" | Set-Content -LiteralPath ($archivePath+'.sha256') -Encoding ASCII
    @{Archive=$archivePath;Bytes=(Get-Item -LiteralPath $archivePath).Length;SHA256=$digest;UserDataEntries=0;Integrity='passed'} | ConvertTo-Json
} finally {
    Pop-Location
}

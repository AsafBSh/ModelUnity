[CmdletBinding()]
param([string]$ISCC, [string]$BundleDirectory, [string]$OutputName, [ValidateSet('fast','normal','ultra64')][string]$Compression='normal', [switch]$PlanOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$versionSource = Get-Content -LiteralPath (Join-Path $projectRoot 'scripts/_version.py') -Raw
if ($versionSource -notmatch 'MODELUNIFY_VERSION\s*=\s*"([^"]+)"') { throw 'Application version was not found.' }
$version = $matches[1]
if (-not $BundleDirectory) { $BundleDirectory = Join-Path $projectRoot "dist/Modelunify-$version-portable" }
$BundleDirectory = [IO.Path]::GetFullPath($BundleDirectory)
if (-not (Test-Path -LiteralPath $BundleDirectory -PathType Container)) { throw "Bundle not found: $BundleDirectory" }
if (-not $OutputName) { $OutputName = "Modelunify-$version-Setup" }
if ($OutputName -notmatch '^[a-zA-Z0-9][a-zA-Z0-9._ -]*$') { throw 'OutputName must be a plain filename without an extension or directory.' }
$installerOutput = Join-Path $projectRoot "dist/$OutputName.exe"
if ($PlanOnly) { Write-Host "Version=$version; Bundle=$BundleDirectory; Output=$installerOutput"; return }
if (Test-Path -LiteralPath $installerOutput) { throw "Installer already exists and is preserved: $installerOutput" }
if (-not $ISCC) { $ISCC = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source }
if (-not $ISCC) { throw 'Provide -ISCC with the path to the installed Inno Setup compiler.' }
& $ISCC "/DMyAppVersion=$version" "/DBundleRoot=$BundleDirectory" "/DInstallerName=$OutputName" "/DBundleCompression=lzma2/$Compression" (Join-Path $PSScriptRoot 'installer.iss')
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed: $LASTEXITCODE" }

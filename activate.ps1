# PowerShell activation helper for the 3D AI Generator venv.
Set-Location -Path $PSScriptRoot
& "$PSScriptRoot\.venv\Scripts\Activate.ps1"
Write-Host ""
Write-Host "3D AI Generator venv active. Try:" -ForegroundColor Green
Write-Host "  python scripts\generate_3d.py info"
Write-Host "  python scripts\generate_3d.py single inputs\satellite\YOUR_IMAGE.png"
Write-Host "  python scripts\web_ui.py"

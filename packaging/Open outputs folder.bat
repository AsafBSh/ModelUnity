@echo off
REM Open the folder where generated meshes (.glb) and BMS LOD sets are written.
if not exist "%~dp0app\outputs" mkdir "%~dp0app\outputs"
explorer "%~dp0app\outputs"

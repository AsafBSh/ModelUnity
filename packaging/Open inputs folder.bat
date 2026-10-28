@echo off
REM Open the folder where you drop input images (satellite / ground photos).
REM Modelunify reads from here; you can also drop files via the web UI.
if not exist "%~dp0app\inputs" mkdir "%~dp0app\inputs"
explorer "%~dp0app\inputs"

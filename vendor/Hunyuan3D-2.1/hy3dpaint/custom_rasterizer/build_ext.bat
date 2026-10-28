@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" amd64
set CUDA_HOME=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6
set CUDA_PATH=%CUDA_HOME%
set DISTUTILS_USE_SDK=1
set MSSdk=1
set PATH=%CUDA_HOME%\bin;%PATH%
"C:\AI Projects\3D AI Generator\.venv\Scripts\python.exe" setup.py build_ext --inplace

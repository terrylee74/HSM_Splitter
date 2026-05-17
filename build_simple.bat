@echo off
chcp 65001 >nul
cd /d "%~dp0"

python --version
if errorlevel 1 goto :pyerror

python -m pip install pyinstaller
if errorlevel 1 goto :piperror

echo.
echo Starting build for HSM_Splitter...
python -m PyInstaller --noconfirm --clean HSM_Splitter.spec
if errorlevel 1 goto :builderror

echo.
echo Build successfully completed.
pause
exit /b

:pyerror
echo.
echo Error: Python not found.
pause
exit /b

:piperror
echo.
echo Error: PyInstaller installation failed.
pause
exit /b

:builderror
echo.
echo Error during build. Please check the spec file.
pause
exit /b

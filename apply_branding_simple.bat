@echo off
chcp 65001 >nul
cd /d "%~dp0"

python apply_branding.py
if errorlevel 1 goto :err

echo.
echo Branding applied (v7).
pause
exit /b

:err
echo.
echo Branding failed (v7).
pause
exit /b

@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0"
powershell.exe -NoProfile -File "%~dp0scripts\instalar_tarea.ps1"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" echo No se pudo instalar. Revisa el error y las politicas de PowerShell.
pause
exit /b %RESULT%

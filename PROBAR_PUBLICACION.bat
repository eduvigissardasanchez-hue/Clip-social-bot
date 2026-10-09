@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Ejecuta CONFIGURAR.bat primero.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" main.py test-publication
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%

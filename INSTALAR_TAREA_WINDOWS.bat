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
".venv\Scripts\python.exe" -m app.windows_task
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" echo El instalador no pudo completar el proceso. Revisa el detalle anterior.
pause
exit /b %RESULT%

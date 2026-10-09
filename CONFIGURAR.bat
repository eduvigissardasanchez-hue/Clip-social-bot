@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0"
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"
if errorlevel 1 goto error
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
if errorlevel 1 goto error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto error
for %%D in (pendientes publicados errores data logs) do if not exist "%%D" mkdir "%%D"
if not exist ".env" copy /y ".env.example" ".env" >nul
if errorlevel 1 goto error
echo Configuracion local preparada. Edita .env en tu PC; no compartas sus valores.
echo Consulta README.md antes de la primera prueba.
pause
exit /b 0
:error
echo No se pudo configurar. Instala Python 3.11 o superior con el launcher py.
pause
exit /b 1

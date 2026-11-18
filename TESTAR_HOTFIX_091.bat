@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
set "PY=%LOCALAPPDATA%\BFS\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERRO] Ambiente nao instalado. Execute instalar_dependencias.bat.
  pause
  exit /b 1
)
"%PY%" -m unittest discover -s tests -p test_hotfix_091.py -v
set "RC=%ERRORLEVEL%"
pause
exit /b %RC%

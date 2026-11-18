@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONPATH=%~dp0"
set "PY=%LOCALAPPDATA%\BFS\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERRO] Ambiente nao instalado. Execute instalar_dependencias.bat.
  pause
  exit /b 1
)
"%PY%" "%~dp0scripts\testar_whisper_real.py"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo [ERRO] O teste real de transcricao falhou.
pause
exit /b %RC%

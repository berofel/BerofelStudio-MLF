@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
title BerofelStudio - Validar controles de processo
set "PYTHON=%LOCALAPPDATA%\BFS\venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo [ERRO] Instale o editor primeiro: instalar_dependencias.bat
  pause
  exit /b 1
)
echo =======================================================
echo  Testando pausa, retomada, cancelamento e cache
 echo =======================================================
set "QT_QPA_PLATFORM=offscreen"
"%PYTHON%" -m unittest discover -s tests -p "test_process*.py" -v
if errorlevel 1 (
  echo [ERRO] Testes falharam. Envie o resultado no painel de feedback.
  pause
  exit /b 1
)
echo [OK] Controles de processos passaram nos testes locais.
echo A qualidade de inferencia ainda requer modelos instalados e video real.
pause
exit /b 0

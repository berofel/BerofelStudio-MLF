@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
title BerofelStudio 0.8 - Teste visual acoes
set "PY=%LOCALAPPDATA%\BFS\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERRO] Execute instalar_dependencias.bat primeiro.
  pause
  exit /b 1
)
set "QT_QPA_PLATFORM=offscreen"
"%PY%" -m unittest discover -s tests -p "test_actions_panel.py" -v
set "STATUS=%ERRORLEVEL%"
echo.
if "%STATUS%"=="0" (
  echo [OK] Teste estrutural Qt terminado. Confira se nao houve skips.
  echo Para conferir aparencia e cliques reais, abra ABRIR_BEROFELSTUDIO.bat.
) else (
  echo [ERRO] Teste de interface falhou; copie este relatorio.
)
pause
exit /b %STATUS%

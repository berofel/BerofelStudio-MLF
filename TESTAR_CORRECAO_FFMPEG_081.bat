@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
title BerofelStudio 0.8.1 - Verificar FFmpeg
set "PY=%LOCALAPPDATA%\BFS\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERRO] Ambiente nao encontrado. Execute instalar_dependencias.bat
  pause
  exit /b 1
)
echo [1/2] Testando versoes antigas e recentes do FFmpeg e geracao real.
"%PY%" -m unittest discover -s tests -p test_ffmpeg_compat_081.py -v
if errorlevel 1 (echo [ERRO] Falha no teste de FFmpeg & pause & exit /b 1)
echo.
echo [2/2] Executando testes gerais do editor.
"%PY%" -m unittest discover -s tests -v
if errorlevel 1 (echo [ERRO] Falha nos testes gerais & pause & exit /b 1)
echo [OK] Testes concluidos. Agora abra o editor.
pause

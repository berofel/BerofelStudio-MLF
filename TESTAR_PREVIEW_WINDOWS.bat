@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
title BerofelStudio - Teste de janela e composicao
set "PY_EXE=%LOCALAPPDATA%\BFS\venv\Scripts\python.exe"
if not exist "%PY_EXE%" (
  echo [ERRO] Instale o editor primeiro.
  pause
  exit /b 1
)
echo Teste opcional: uma janela abrira com dois videos sobrepostos.
"%PY_EXE%" scripts\testar_interface.py
set "RET=%ERRORLEVEL%"
if "%RET%"=="0" echo [OK] Preview multitrilha na interface testado neste computador.
if not "%RET%"=="0" echo [ERRO] GUI nao passou no teste. Copie esta tela e envie.
pause
exit /b %RET%

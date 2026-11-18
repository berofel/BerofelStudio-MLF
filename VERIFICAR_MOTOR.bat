@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
title BerofelStudio - Teste do motor
set "PY_EXE=%LOCALAPPDATA%\BFS\venv\Scripts\python.exe"
if not exist "%PY_EXE%" (
  echo [ERRO] Execute instalar_dependencias.bat primeiro.
  pause
  exit /b 1
)
"%PY_EXE%" scripts\diagnostico_motor.py
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" echo [OK] Pipeline de video e audio validado neste Windows.
if not "%RC%"=="0" echo [ERRO] Motor nao passou no teste. Envie a tela ou o log.
pause
exit /b %RC%

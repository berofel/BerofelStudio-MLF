@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
title BerofelStudio - Teste Batata Quente IA
set "BFS_PY=%LOCALAPPDATA%\BFS\venv\Scripts\python.exe"
if not exist "%BFS_PY%" (
  echo [ERRO] Instale o editor pelo instalar_dependencias.bat primeiro.
  pause
  exit /b 1
)
"%BFS_PY%" scripts\testar_batata_quente.py
if errorlevel 1 (
  echo [ERRO] Falha no autoteste; veja a mensagem acima.
  pause
  exit /b 1
)
echo [OK] Teste concluido.
pause

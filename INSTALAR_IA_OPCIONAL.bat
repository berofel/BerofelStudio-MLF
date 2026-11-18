@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
title BerofelStudio - IA opcional
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\instalar_ia.ps1"
if errorlevel 1 (
  echo [ERRO] IA nao instalada. A edicao e o preview continuam utilizaveis.
  pause
  exit /b 1
)
echo [OK] IA opcional instalada.
pause

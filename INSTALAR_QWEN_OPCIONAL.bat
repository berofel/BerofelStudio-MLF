@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
title BerofelStudio - Qwen local opcional
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\instalar_qwen.ps1"
if errorlevel 1 (
  echo [ERRO] Qwen nao instalado. O editor e Silero/Whisper continuam funcionando.
  pause
  exit /b 1
)
echo [OK] Qwen local configurado.
pause

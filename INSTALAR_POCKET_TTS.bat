@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
title BerofelStudio - Instalar Pocket TTS
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\instalar_pocket.ps1"
if errorlevel 1 (
 echo [ERRO] Confira o log na pasta logs.
 pause
 exit /b 1
)
echo [OK] Pocket TTS preparado. Modelo pode exigir autorizacao no Hugging Face.
pause

@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
title BerofelStudio - Continuar instalacao

echo ========================================================
echo   BerofelStudio - RETOMAR A PARTIR DO FFMPEG
echo ========================================================
echo.
echo Reutiliza Python, atualiza apenas as bibliotecas faltantes.
echo Mostra progresso do download do FFmpeg e tenta origem alternativa.
echo.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\continuar_instalacao.ps1"
set "RET=%ERRORLEVEL%"
echo.
if not "%RET%"=="0" (
  echo [ERRO] Instalacao nao concluida. Veja pasta logs.
  pause
  exit /b %RET%
)
echo [OK] Instalacao concluida. Execute ABRIR_BEROFELSTUDIO.bat
pause
exit /b 0

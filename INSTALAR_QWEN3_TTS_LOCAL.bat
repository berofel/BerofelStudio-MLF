@echo off
setlocal
cd /d "%~dp0"
title BerofelStudio - Instalacao local Qwen3
echo Preparando o Qwen3 local. Esta janela permanecera aberta durante a instalacao.
set "LOG_DIR=%LOCALAPPDATA%\BFS\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1
set "LOG_FILE=%LOG_DIR%\qwen3_install.log"
echo O progresso detalhado sera salvo em "%LOG_FILE%".
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\instalar_qwen3_tts_local.ps1" > "%LOG_FILE%" 2>&1
set "RESULT=%ERRORLEVEL%"
echo.
if not "%RESULT%"=="0" (
  echo [ERRO] A instalacao local do Qwen3 nao foi concluida. Consulte o log:
  echo "%LOG_FILE%"
  type "%LOG_FILE%"
  if not defined BFS_NO_PAUSE pause
  exit /b %RESULT%
)
echo Preparacao local do Qwen3 concluida.
if not defined BFS_NO_PAUSE pause
exit /b 0

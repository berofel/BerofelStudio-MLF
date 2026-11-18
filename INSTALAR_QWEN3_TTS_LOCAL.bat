@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\instalar_qwen3_tts_local.ps1"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
  echo.
  echo A instalacao local do Qwen3 nao foi concluida. Nenhum arquivo do projeto foi substituido.
  pause
)
exit /b %RESULT%

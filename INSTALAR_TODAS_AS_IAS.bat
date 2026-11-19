@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
title BerofelStudio - Instalar todas as IAs
set "ERR=0"
echo =======================================================
echo  Silero + Faster-Whisper + Qwen3-TTS
 echo =======================================================
echo O ambiente do editor deve ser instalado primeiro.
echo Os pacotes, modelos e vozes serao baixados se necessario.
echo Qwen3-TTS roda localmente apos o download inicial do modelo.
echo.
if not exist "%LOCALAPPDATA%\BFS\venv\Scripts\python.exe" (
  echo [ERRO] Execute instalar_dependencias.bat primeiro.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\verificar_editor_fechado.ps1" -VenvDir "%LOCALAPPDATA%\BFS\venv"
if errorlevel 1 (
  echo [ERRO] Feche o editor antes de instalar ou atualizar as IAs.
  pause
  exit /b 1
)
echo.
echo [1/3] Silero VAD + Faster-Whisper...
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\instalar_ia.ps1"
if errorlevel 1 (
  echo [ERRO] Falha Whisper/Silero. Consulte logs.
  set "ERR=1"
)
echo.
echo [2/3] Qwen3 + llama.cpp (assistente de IA)...
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\instalar_qwen.ps1"
if errorlevel 1 (
  echo [AVISO] Qwen nao foi preparado. Consulte logs.
  set "ERR=1"
)
echo.
echo [3/3] Qwen3-TTS Base (clonagem e narracao local)
set "INSTALL_QWEN_TTS="
set /p "INSTALL_QWEN_TTS=Baixar aproximadamente 2,5 GB do modelo de voz agora? [s/N]: "
if /i "%INSTALL_QWEN_TTS%"=="s" (
  "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\instalar_qwen3_tts_local.ps1"
  if errorlevel 1 (
    echo [ERRO] Falha ao preparar Qwen3-TTS. Consulte %LOCALAPPDATA%\BFS\logs\qwen3_install.log
    set "ERR=1"
  )
) else (
  echo [INFO] Qwen3-TTS foi adiado; use INSTALAR_QWEN3_TTS_LOCAL.bat quando desejar.
)
echo.
if "%ERR%"=="0" (
  echo [OK] Bibliotecas das IAs instaladas.
) else (
  echo [AVISO] Um ou mais componentes falharam. Confira logs e execute novamente.
)
echo Para validar clonagem real: use uma referencia autorizada em Narração.
echo Para abrir: ABRIR_BEROFELSTUDIO.bat
echo.
pause
if "%ERR%"=="0" exit /b 0
exit /b 1

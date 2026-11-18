@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
title BerofelStudio - Instalar todas as IAs
set "ERR=0"
echo =======================================================
echo  Silero + Faster-Whisper + Qwen + Pocket TTS
 echo =======================================================
echo O ambiente do editor deve ser instalado primeiro.
echo Os pacotes, modelos e vozes serao baixados se necessario.
echo A autorizacao do modelo Pocket TTS pode exigir uma conta Hugging Face.
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
echo [2/3] Qwen3 + llama.cpp...
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\instalar_qwen.ps1"
if errorlevel 1 (
  echo [AVISO] Qwen nao foi preparado. Consulte logs.
  set "ERR=1"
)
echo.
echo [3/3] Pocket TTS + amostras CC0...
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\instalar_pocket.ps1"
if errorlevel 1 (
  echo [ERRO] Falha ao instalar Pocket TTS. Consulte logs.
  set "ERR=1"
)
echo.
if "%ERR%"=="0" (
  echo [OK] Bibliotecas das IAs instaladas.
) else (
  echo [AVISO] Um ou mais componentes falharam. Confira logs e execute novamente.
)
echo IMPORTANTE: Pocket TTS pode exigir aceitar as condicoes do modelo no Hugging Face.
echo Se necessario: AUTORIZAR_POCKET_TTS.bat
echo Teste de voz real: TESTAR_POCKET_TTS.bat
echo Para abrir: ABRIR_BEROFELSTUDIO.bat
echo.
pause
if "%ERR%"=="0" exit /b 0
exit /b 1

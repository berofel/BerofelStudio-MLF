@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
title BerofelStudio - Autorizar Pocket TTS
set "PY_EXE=%LOCALAPPDATA%\BFS\venv\Scripts\python.exe"
if not exist "%PY_EXE%" (
 echo Instale primeiro: INSTALAR_POCKET_TTS.bat
 if not defined BFS_NO_PAUSE pause
 exit /b 1
)
echo ======================================================
echo  1. Abra https://huggingface.co/kyutai/pocket-tts
echo  2. Entre na sua conta e ACEITE as condicoes do modelo.
echo  3. Crie um token pessoal no Hugging Face.
echo  4. Cole o token somente no prompt que aparecera abaixo.
echo ======================================================
echo.
set "HF_EXE=%LOCALAPPDATA%\BFS\venv\Scripts\hf.exe"
if not defined BFS_CLONE_ACTIVATION_LOG set "BFS_CLONE_ACTIVATION_LOG=%LOCALAPPDATA%\BFS\logs\pocket_clone_activation.log"
set "ACTIVATION_LOG=%BFS_CLONE_ACTIVATION_LOG%"
if not exist "%LOCALAPPDATA%\BFS\logs" mkdir "%LOCALAPPDATA%\BFS\logs" >nul 2>&1
if not exist "%HF_EXE%" (
 echo [ERRO] CLI do Hugging Face ausente. Execute INSTALAR_POCKET_TTS.bat primeiro.
 if not defined BFS_NO_PAUSE pause
 exit /b 1
)
"%HF_EXE%" auth login
if errorlevel 1 (
 echo [ERRO] Login nao concluido. Confira o token.
 if not defined BFS_NO_PAUSE pause
 exit /b 1
)
"%PY_EXE%" scripts\preparar_modelo_pocket.py > "%ACTIVATION_LOG%" 2>&1
set "ACTIVATION_RESULT=%ERRORLEVEL%"
type "%ACTIVATION_LOG%"
if not "%ACTIVATION_RESULT%"=="0" (
 echo [ERRO] A ativacao falhou; use o diagnostico acima para identificar rede ou permissao.
 if not defined BFS_NO_PAUSE pause
 exit /b %ACTIVATION_RESULT%
)
echo [OK] Modelo pronto.
if not defined BFS_NO_PAUSE pause

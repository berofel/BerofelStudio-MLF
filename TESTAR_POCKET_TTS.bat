@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set "PY_EXE=%LOCALAPPDATA%\BFS\venv\Scripts\python.exe"
if not exist "%PY_EXE%" (
 echo Execute instalar_dependencias.bat e INSTALAR_POCKET_TTS.bat primeiro.
 pause
 exit /b 1
)
"%PY_EXE%" scripts\testar_pocket.py --real --offline
if errorlevel 1 (
 echo [ERRO] Teste de voz falhou. Aceite os termos e execute AUTORIZAR_POCKET_TTS.bat.
 pause
 exit /b 1
)
echo [OK] Pocket TTS testado com WAV real.
pause

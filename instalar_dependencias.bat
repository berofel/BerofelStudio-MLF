@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
title BerofelStudio - Instalacao completa Windows

echo ========================================================
echo   BerofelStudio - INSTALACAO PARA WINDOWS LIMPO
 echo ========================================================
echo.
echo Este instalador NAO depende de Python preinstalado.
echo Ele baixa Python, Visual C++, FFmpeg/FFprobe, pacotes
echo Python. Parakeet TDT v3 e Silero ficam no instalador opcional de IA.
echo Pode aparecer uma confirmacao do Windows para Visual C++.
echo.

set "PS_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS_EXE%" (
  echo [ERRO] Windows PowerShell nao encontrado.
  echo Sistema necessario: Windows 10 ou Windows 11, 64 bits.
  pause
  exit /b 1
)
"%PS_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\instalar_windows.ps1"
set "RET=%ERRORLEVEL%"
echo.
if not "%RET%"=="0" (
  echo [ERRO] Instalacao incompleta. Veja o erro acima e a pasta logs.
  echo Pode executar este arquivo novamente apos corrigir a causa.
  pause
  exit /b %RET%
)
echo [OK] Instalacao da versao atual concluida; o launcher exibira a versao e a pasta carregadas.
echo Agora abra ABRIR_BEROFELSTUDIO.bat
pause
exit /b 0

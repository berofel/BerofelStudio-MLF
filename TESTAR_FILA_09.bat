@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
title BerofelStudio 0.9 - Fila Inteligente e Revisao em Massa
set "PY=%LOCALAPPDATA%\BFS\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERRO] Python do ambiente Berofel nao encontrado.
  echo Execute instalar_dependencias.bat antes deste teste.
  pause
  exit /b 1
)
echo ========================================================
echo   BerofelStudio 0.9 - Testes do editor e fila de IA
echo ========================================================
echo Testa cortes em lote, dependencias, VAD, cache,
echo sincronismo de legendas, exportacao e processos.
echo Modelos reais so podem ser validados com arquivos de voz.
echo.
set "QT_QPA_PLATFORM=offscreen"
"%PY%" -m unittest discover -s tests -v
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
 echo [ERRO] Alguns testes falharam. Copie a saida da janela.
) else (
 echo [OK] Testes concluidos. Observe SKIPPED e erros do Windows.
)
echo.
pause
exit /b %RESULT%

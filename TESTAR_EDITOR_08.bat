@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
title BerofelStudio 0.8 - Teste de acoes independentes
set "PY=%LOCALAPPDATA%\BFS\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERRO] Python/venv do editor nao encontrado.
  echo Execute instalar_dependencias.bat e tente novamente.
  pause
  exit /b 1
)
echo ==========================================================
echo  BerofelStudio 0.8 - Testes locais da versao completa
 echo ==========================================================
echo Inclui testes de selecao, cache, IA simulada, exportacao
 echo FFmpeg, pausa/cancelamento e painel grafico com Qt.
echo.
set "QT_QPA_PLATFORM=offscreen"
"%PY%" -m unittest discover -s tests -v
set "STATUS=%ERRORLEVEL%"
echo.
if not "%STATUS%"=="0" (
  echo [ERRO] Algum teste falhou. Copie o resultado do terminal.
) else (
  echo [OK] Testes concluidos. Confira se algum teste ficou SKIPPED.
  echo [NOTA] Modelos reais precisam de verificacao separada.
)
pause
exit /b %STATUS%

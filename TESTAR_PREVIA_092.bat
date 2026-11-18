@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
title BerofelStudio - teste da previa continua
set "PY=%LOCALAPPDATA%\BFS\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERRO] O Python do BerofelStudio nao foi encontrado.
  echo Instale/atualize usando instalar_dependencias.bat.
  pause
  exit /b 1
)
echo ============================================================
echo  BerofelStudio - teste da previa
echo ============================================================
"%PY%" -c "from berofel import __version__; print('Versao do codigo local:', __version__)"
if errorlevel 1 (
  echo [ERRO] Nao foi possivel identificar a versao local do editor.
  exit /b 1
)
echo Os testes usam apenas midia sintetica temporaria. Nao usam seus arquivos.
echo Cobre 300/500 cortes e timeline de 80 minutos com 800 cortes.
echo Prepara seeks em 30 regioes e decodifica audio/video no inicio, meio e fim.
 echo.
"%PY%" -m unittest discover -s tests -p test_preview_092_many_cuts.py -v
set "RESULT=%ERRORLEVEL%"
echo.
if not "%RESULT%"=="0" (
echo [ERRO] Teste falhou. Envie esta tela para analise.
) else (
echo [OK] Teste do motor concluido.
echo Abra o editor e reproduza a timeline cortada pela IA.
)
pause
exit /b %RESULT%

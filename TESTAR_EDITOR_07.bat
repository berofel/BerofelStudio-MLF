@echo off
setlocal
cd /d "%~dp0"
set "PY=%LOCALAPPDATA%\BFS\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERRO] Ambiente nao instalado. Execute instalar_dependencias.bat antes.
  pause
  exit /b 1
)
echo [BEROFELSTUDIO 0.7] Testando os recursos novos de edicao...
"%PY%" -m unittest discover -s tests -p test_editor_07.py -v
if errorlevel 1 (echo [ERRO] Testes falharam. & pause & exit /b 1)
echo [OK] Testes de edicao 0.7 aprovados.
pause

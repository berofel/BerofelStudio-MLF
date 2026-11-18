@echo off
setlocal EnableExtensions
set "APP_ROOT=%~dp0"
cd /d "%APP_ROOT%"
chcp 65001 >nul
if not exist "%APP_ROOT%main.py" (
  echo [ERRO] Este atalho nao aponta para uma pasta valida do BerofelStudio.
  echo Pasta esperada: "%APP_ROOT%"
  pause
  exit /b 1
)
for %%F in ("%APP_ROOT%berofel\ui\studio_header.py" "%APP_ROOT%berofel\ui\library_panel.py" "%APP_ROOT%berofel\ui\preview_transport.py") do (
  if not exist "%%~F" (
    echo [ERRO] Interface atual incompleta: %%~nxF nao encontrado.
    echo Reextraia a atualizacao para: "%APP_ROOT%"
    pause
    exit /b 1
  )
)
set "PY_EXE=%LOCALAPPDATA%\BFS\venv\Scripts\python.exe"
if not exist "%PY_EXE%" (
  echo [AVISO] BerofelStudio ainda nao esta preparado.
  echo Execute instalar_dependencias.bat primeiro.
  pause
  exit /b 1
)
rem Prioriza sempre o codigo desta pasta, inclusive se houver outra copia instalada.
set "PYTHONPATH=%APP_ROOT%;%PYTHONPATH%"
title BerofelStudio - codigo local
"%PY_EXE%" -c "import berofel; from berofel import __version__; print('BerofelStudio local:', __version__); print('Modulo carregado:', berofel.__file__)"
if errorlevel 1 (
  echo [ERRO] Nao foi possivel importar a versao do codigo nesta pasta.
  pause
  exit /b 1
)
echo Codigo atual: "%APP_ROOT%"
"%PY_EXE%" scripts\verificar.py --strict --quick --editor-only
if errorlevel 1 (
  echo.
  echo [ERRO] Faltam dependencias ou algo esta danificado.
  echo Execute instalar_dependencias.bat para reparar.
  pause
  exit /b 1
)
if /i "%~1"=="--verificar" (
  echo [OK] Launcher validado para o codigo atual desta pasta.
  exit /b 0
)
echo Iniciando BerofelStudio...
"%PY_EXE%" scripts\abrir_com_log.py
if errorlevel 1 (
  echo.
  echo [ERRO] O editor fechou com erro. Veja a mensagem acima.
  pause
  exit /b 1
)
exit /b 0

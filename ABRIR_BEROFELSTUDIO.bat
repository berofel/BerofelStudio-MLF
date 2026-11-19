@echo off
rem Compatibilidade com atalhos antigos. O VBScript inicia o código desta
rem pasta usando pythonw.exe, sem manter uma janela CMD aberta.
set "LAUNCHER=%~dp0ABRIR_BEROFELSTUDIO.vbs"
if not exist "%LAUNCHER%" exit /b 1
start "" wscript.exe //B //Nologo "%LAUNCHER%"
exit /b 0

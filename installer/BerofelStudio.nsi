Unicode true
RequestExecutionLevel user
SetCompressor /SOLID zlib
Name "BerofelStudio ${APP_VERSION}"
OutFile "${OUTPUT_DIR}\BerofelStudio-${APP_VERSION}-Setup-x64.exe"
InstallDir "$LOCALAPPDATA\BerofelStudio"
InstallDirRegKey HKCU "Software\BerofelStudio" "InstallDir"
Icon "${APP_SOURCE}\assets\brand\berofel_studio.ico"
UninstallIcon "${APP_SOURCE}\assets\brand\berofel_studio.ico"
VIProductVersion "0.10.0.0"
VIAddVersionKey /LANG=1046 "ProductName" "BerofelStudio"
VIAddVersionKey /LANG=1046 "CompanyName" "BerofelStudio"
VIAddVersionKey /LANG=1046 "FileDescription" "Instalador do BerofelStudio para Windows x64"
VIAddVersionKey /LANG=1046 "ProductVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=1046 "FileVersion" "${APP_VERSION}"
ShowInstDetails show
ShowUnInstDetails show
SetDateSave on
SetOverwrite on
BrandingText "BerofelStudio"

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"

!define MUI_ABORTWARNING
!define MUI_ICON "${APP_SOURCE}\assets\brand\berofel_studio.ico"
!define MUI_UNICON "${APP_SOURCE}\assets\brand\berofel_studio.ico"
!define MUI_WELCOMEPAGE_TITLE "Instalação do BerofelStudio"
!define MUI_WELCOMEPAGE_TEXT "Este instalador prepara o editor e, se selecionados, os motores locais de IA. A instalação inicial requer conexão com a internet."
!define MUI_FINISHPAGE_RUN_FUNCTION "LaunchBerofelStudio"
!define MUI_FINISHPAGE_RUN_TEXT "Abrir BerofelStudio agora"
!define MUI_FINISHPAGE_RUN

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "PortugueseBR"

Var InstallWhisperBase
Var InstallQwen3

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "O BerofelStudio requer Windows 10/11 de 64 bits (x64)."
    Abort
  ${EndIf}
  StrCpy $InstallWhisperBase ""
  StrCpy $InstallQwen3 ""
  SetShellVarContext current
FunctionEnd

Function LaunchBerofelStudio
  ExecShell "open" "$INSTDIR\ABRIR_BEROFELSTUDIO.vbs"
FunctionEnd

Section "Faster-Whisper Base, Silero e corretor pt-BR (~150 MB)" SEC_WHISPER
  StrCpy $InstallWhisperBase " -InstallWhisperBase"
SectionEnd

Section "Qwen3-TTS Base 0.6B (modelo ~2,5 GB + runtime; requer internet e vários GB livres)" SEC_QWEN3
  StrCpy $InstallQwen3 " -InstallQwen3"
SectionEnd

Section "BerofelStudio (obrigatório)" SEC_EDITOR
  SectionIn RO
  SetOutPath "$INSTDIR"
  File /r "${APP_SOURCE}\*"

  WriteRegStr HKCU "Software\BerofelStudio" "InstallDir" "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\BerofelStudio"
  CreateShortCut "$SMPROGRAMS\BerofelStudio\BerofelStudio.lnk" "$INSTDIR\ABRIR_BEROFELSTUDIO.vbs" "" "$INSTDIR\assets\brand\berofel_studio.ico" 0
  CreateShortCut "$SMPROGRAMS\BerofelStudio\Desinstalar BerofelStudio.lnk" "$INSTDIR\Uninstall.exe" "" "$INSTDIR\assets\brand\berofel_studio.ico" 0

  DetailPrint "Preparando Python, bibliotecas, FFmpeg e testes locais..."
  ExecWait '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\scripts\instalar_windows.ps1" -SkipQwenPrompt$InstallWhisperBase$InstallQwen3' $0
  ${If} $0 != 0
    MessageBox MB_ICONSTOP "A preparação das dependências falhou (código $0). Consulte os logs em $INSTDIR\logs."
    Abort
  ${EndIf}
SectionEnd

Section "Criar atalho na área de trabalho" SEC_DESKTOP
  CreateShortCut "$DESKTOP\BerofelStudio.lnk" "$INSTDIR\ABRIR_BEROFELSTUDIO.vbs" "" "$INSTDIR\assets\brand\berofel_studio.ico" 0
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\BerofelStudio.lnk"
  Delete "$SMPROGRAMS\BerofelStudio\BerofelStudio.lnk"
  Delete "$SMPROGRAMS\BerofelStudio\Desinstalar BerofelStudio.lnk"
  RMDir "$SMPROGRAMS\BerofelStudio"
  DeleteRegKey HKCU "Software\BerofelStudio"
  RMDir /r "$INSTDIR"
  ; Modelos, perfis vocais, cache e projetos em %LOCALAPPDATA%\BFS permanecem.
SectionEnd

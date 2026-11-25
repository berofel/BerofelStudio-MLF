Unicode true
RequestExecutionLevel user
SetCompressor /SOLID zlib
Name "BerofelStudio ${APP_VERSION}"
OutFile "${OUTPUT_DIR}\BerofelStudio-${APP_VERSION}-Setup-x64.exe"
InstallDir "$LOCALAPPDATA\BerofelStudio"
InstallDirRegKey HKCU "Software\BerofelStudio" "InstallDir"
Icon "${APP_SOURCE}\assets\brand\berofel_studio.ico"
UninstallIcon "${APP_SOURCE}\assets\brand\berofel_studio.ico"
VIProductVersion "${APP_FILE_VERSION}"
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
!include "FileFunc.nsh"

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

Var InstallParakeetTdt
Var InstallQwen3

!macro ExtractUpdateChecker
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  File /oname=check_latest_release.ps1 "${APP_SOURCE}\scripts\check_latest_release.ps1"
!macroend

Function LaunchBerofelStudio
  ExecShell "open" "$INSTDIR\ABRIR_BEROFELSTUDIO.vbs"
FunctionEnd

Section "Parakeet TDT v3 ONNX INT8/CPU, Silero e corretor pt-BR (~700 MB)" SEC_PARAKEET
  StrCpy $InstallParakeetTdt " -InstallParakeetTdt"
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
  ExecWait '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\scripts\instalar_windows.ps1" -SkipQwenPrompt$InstallParakeetTdt$InstallQwen3' $0
  ${If} $0 != 0
    MessageBox MB_ICONSTOP "A preparação das dependências falhou (código $0). Consulte os logs em $INSTDIR\logs."
    Abort
  ${EndIf}
SectionEnd

Section "Criar atalho na área de trabalho" SEC_DESKTOP
  CreateShortCut "$DESKTOP\BerofelStudio.lnk" "$INSTDIR\ABRIR_BEROFELSTUDIO.vbs" "" "$INSTDIR\assets\brand\berofel_studio.ico" 0
SectionEnd

; Defined after the component sections so /COREONLY can safely reference their IDs.
Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "O BerofelStudio requer Windows 10/11 de 64 bits (x64)."
    Abort
  ${EndIf}
  ${GetParameters} $R0
  ; Used by the clean Windows CI smoke test to install the editor without
  ; downloading optional multi-gigabyte neural models.
  ${GetOptions} $R0 "/COREONLY" $R3
  ${IfNot} ${Errors}
    SectionSetFlags ${SEC_PARAKEET} 0
    SectionSetFlags ${SEC_QWEN3} 0
  ${EndIf}
  ClearErrors
  ${GetOptions} $R0 "/NOUPDATECHECK" $R1
  ${IfNot} ${Errors}
    Goto update_check_done
  ${EndIf}
  ; An older downloaded setup hands off to the newest published release before
  ; touching the existing installation. Network failures offer a safe fallback.
  !insertmacro ExtractUpdateChecker
  !ifdef APP_ALLOW_PRERELEASE
    ExecWait '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "$PLUGINSDIR\check_latest_release.ps1" -CurrentVersion "${APP_VERSION}" -IncludePrerelease -InstallLatest' $R2
  !else
    ExecWait '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "$PLUGINSDIR\check_latest_release.ps1" -CurrentVersion "${APP_VERSION}" -InstallLatest' $R2
  !endif
  ${If} $R2 == 10
    Abort
  ${ElseIf} $R2 == 20
    MessageBox MB_ICONEXCLAMATION|MB_YESNO "Nao foi possivel confirmar/baixar a versao mais recente do GitHub. Consulte $TEMP\BerofelStudio-update-check.log. Deseja continuar com a versao ${APP_VERSION} incluida neste setup?" IDYES update_check_done
    Abort
  ${ElseIf} $R2 != 0
    MessageBox MB_ICONSTOP "A verificacao de atualizacao terminou inesperadamente (codigo $R2). A instalacao foi cancelada para evitar instalar uma versao incorreta."
    Abort
  ${EndIf}
  update_check_done:
  StrCpy $InstallParakeetTdt ""
  StrCpy $InstallQwen3 ""
  SetShellVarContext current
FunctionEnd

Section "Uninstall"
  Delete "$DESKTOP\BerofelStudio.lnk"
  Delete "$SMPROGRAMS\BerofelStudio\BerofelStudio.lnk"
  Delete "$SMPROGRAMS\BerofelStudio\Desinstalar BerofelStudio.lnk"
  RMDir "$SMPROGRAMS\BerofelStudio"
  DeleteRegKey HKCU "Software\BerofelStudio"
  RMDir /r "$INSTDIR"
  ; Modelos, perfis vocais, cache e projetos em %LOCALAPPDATA%\BFS permanecem.
SectionEnd

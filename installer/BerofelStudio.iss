#ifndef SourceRoot
  #define SourceRoot ".."
#endif
#ifndef AppVersion
  #define AppVersion "0.10.0-alpha.1"
#endif

#define AppDisplayName "BerofelStudio"
#define AppId "{3F5B7188-0871-49B8-AB79-D4E1A39BB661}"

[Setup]
AppId={#AppId}
AppName={#AppDisplayName}
AppVersion={#AppVersion}
AppVerName={#AppDisplayName} {#AppVersion}
AppPublisher=BerofelStudio
AppPublisherURL=https://github.com/berofel/BerofelStudio-MLF
DefaultDirName={localappdata}\BerofelStudio
DefaultGroupName=BerofelStudio
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=BerofelStudio-{#AppVersion}-Setup-x64
SetupIconFile={#SourceRoot}\assets\brand\berofel_studio.ico
UninstallDisplayIcon={app}\assets\brand\berofel_studio.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ChangesAssociations=no
Uninstallable=yes
DisableWelcomePage=no
DisableDirPage=no
DisableReadyMemo=no
MinVersion=10.0.10240
VersionInfoCompany=BerofelStudio
VersionInfoDescription=Instalador do BerofelStudio para Windows x64
VersionInfoProductName=BerofelStudio
VersionInfoProductVersion=0.10.0.0
VersionInfoVersion=0.10.0.0

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"; Flags: checkedonce
Name: "whisperbase"; Description: "Instalar transcrição Faster-Whisper Base, Silero e corretor pt-BR offline (~150 MB)"; GroupDescription: "Componentes locais de IA:"; Flags: checkedonce
Name: "qwen3"; Description: "Instalar Qwen3-TTS Base local (~2,5 GB; requer internet e espaço em disco)"; GroupDescription: "Componentes locais de IA:"; Flags: checkedonce

[Dirs]
Name: "{app}\logs"
Name: "{app}\tools\ffmpeg"

[Files]
Source: "{#SourceRoot}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion; Excludes: ".git\*,.venv\*,venv\*,env\*,__pycache__\*,*.pyc,build\*,dist\*,logs\*,tools\*,*.gguf,*.safetensors,*.pt,*.pth,*.ckpt,*.onnx,*.tflite,*.engine,*.model,*.bin,*.exe,*.dll,*.pyd,*.so,*.dylib,*.lib,*.wav,*.mp3,*.flac,*.ogg,*.m4a,*.aac,*.wma,*.mp4,*.mov,*.mkv,*.avi,*.webm,*.bfs,*.bfsproject,*.bfsproj,*.sqlite,*.sqlite3,*.db,*.zip,*.7z,*.rar,*.bundle"

[Icons]
Name: "{autoprograms}\BerofelStudio"; Filename: "{app}\ABRIR_BEROFELSTUDIO.vbs"; WorkingDir: "{app}"; IconFilename: "{app}\assets\brand\berofel_studio.ico"
Name: "{autodesktop}\BerofelStudio"; Filename: "{app}\ABRIR_BEROFELSTUDIO.vbs"; WorkingDir: "{app}"; IconFilename: "{app}\assets\brand\berofel_studio.ico"; Tasks: desktopicon

[UninstallDelete]
Type: filesandordirs; Name: "{app}\build"

[Code]
function AdditionalInstallArguments: String;
begin
  Result := '';
  if WizardIsTaskSelected('whisperbase') then
    Result := Result + ' -InstallWhisperBase';
  if WizardIsTaskSelected('qwen3') then
    Result := Result + ' -InstallQwen3';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  Params: String;
  PowerShell: String;
begin
  if CurStep = ssPostInstall then begin
    PowerShell := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
    Params := '-NoProfile -ExecutionPolicy Bypass -File "' +
      ExpandConstant('{app}\scripts\instalar_windows.ps1') +
      '" -SkipQwenPrompt ' + AdditionalInstallArguments;
    WizardForm.StatusLabel.Caption :=
      'Preparando Python, dependências do editor e FFmpeg. Esta etapa pode baixar arquivos grandes.';
    if not Exec(PowerShell, Params, ExpandConstant('{app}'), SW_SHOW,
                ewWaitUntilTerminated, ResultCode) then
      RaiseException('Não foi possível iniciar a preparação das dependências do BerofelStudio.');
    if ResultCode <> 0 then
      RaiseException('A preparação das dependências falhou (código ' +
                      IntToStr(ResultCode) + '). Consulte os logs na pasta do BerofelStudio.');
  end;
end;

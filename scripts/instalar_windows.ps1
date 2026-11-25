# BerofelStudio bootstrap for clean Windows 10/11 x64.
# Installs the fully functional editor core. IA is optional.
param(
    [switch]$InstallParakeetTdt,
    [switch]$InstallQwen3,
    [switch]$SkipQwenPrompt
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$root = Split-Path -Parent $PSScriptRoot
$localRoot = Join-Path $env:LOCALAPPDATA 'BerofelStudio'
$downloads = Join-Path $localRoot 'downloads'
$pythonDir = Join-Path $localRoot 'Python312'
$pythonExe = Join-Path $pythonDir 'python.exe'
# Mantenha o venv FORA da pasta descompactada: Windows sem LongPaths habilitado
# nao consegue instalar Qt em pastas com caminhos longos.
$venvDir = Join-Path $env:LOCALAPPDATA 'BFS\venv'
$venvExe = Join-Path $venvDir 'Scripts\python.exe'
$ffmpegFolder = Join-Path $root 'tools\ffmpeg'
$logs = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $downloads,$logs | Out-Null
$logFile = Join-Path $logs ('instalacao_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '.log')
$transcriptStarted = $false

function Step([string] $message) {
    Write-Host "`n====================================================" -ForegroundColor Cyan
    Write-Host "  $message" -ForegroundColor Cyan
    Write-Host "===================================================="
}
function Fetch([string] $uri, [string] $dest, [int] $minBytes = 1024) {
    Write-Host "Baixando: $uri"
    $temp = "$dest.download"
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }
    Invoke-WebRequest -Uri $uri -OutFile $temp -UseBasicParsing -MaximumRedirection 5
    if ((Get-Item -LiteralPath $temp).Length -lt $minBytes) {
        throw "Download inesperadamente pequeno: $uri"
    }
    Move-Item -LiteralPath $temp -Destination $dest -Force
}
function Check-SignedExe([string] $file, [string] $expectedPublisher) {
    $sig = Get-AuthenticodeSignature -LiteralPath $file
    if ($sig.Status -ne 'Valid' -or $null -eq $sig.SignerCertificate) {
        throw "Assinatura digital invalida: $file ($($sig.Status))"
    }
    if ($sig.SignerCertificate.Subject -notmatch $expectedPublisher) {
        throw "Editor da assinatura digital inesperado: $($sig.SignerCertificate.Subject)"
    }
}
function Run-Python([string[]] $argsList) {
    & $venvExe @argsList
    if ($LASTEXITCODE -ne 0) {
        throw "Comando Python falhou, codigo $LASTEXITCODE : $($argsList -join ' ')"
    }
}
function Valid-Python([string] $path) {
    if (-not (Test-Path -LiteralPath $path)) { return $false }
    try {
        & $path -c 'import sys; assert sys.version_info[:2]==(3,12) and sys.maxsize>2**32'
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

try {
    Start-Transcript -LiteralPath $logFile -ErrorAction Stop | Out-Null
    $transcriptStarted = $true
    & (Join-Path $PSScriptRoot 'verificar_editor_fechado.ps1') -VenvDir $venvDir
    Step '1/7 - Checando Windows e arquitetura'
    if (-not [Environment]::Is64BitOperatingSystem) {
        throw 'Este pacote requer Windows 10/11 de 64 bits (x64).'
    }
    if ([Environment]::OSVersion.Version.Major -lt 10) {
        throw 'Este pacote requer Windows 10 ou 11.'
    }
    Write-Host "Windows: $([Environment]::OSVersion.Version) | Local: $root"
    Write-Host 'Python do Microsoft Store NAO sera utilizado.'

    Step '2/7 - Python 3.12 x64 (instalacao automatica)'
    if (-not (Valid-Python $pythonExe)) {
        $pyInstaller = Join-Path $downloads 'python-3.12.10-amd64.exe'
        if (-not (Test-Path -LiteralPath $pyInstaller)) {
            Fetch 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' $pyInstaller
        }
        Check-SignedExe $pyInstaller 'Python Software Foundation'
        Write-Host 'Instalando Python para este usuario, sem depender do PATH...'
        $arguments = @(
            '/quiet', 'InstallAllUsers=0', 'Include_launcher=0',
            'PrependPath=0', 'AppendPath=0', 'Include_pip=1',
            'Include_test=0', 'Include_doc=0', 'AssociateFiles=0',
            ('TargetDir="' + $pythonDir + '"')
        )
        $proc = Start-Process -FilePath $pyInstaller -ArgumentList $arguments -PassThru -Wait
        if ($proc.ExitCode -ne 0 -and $proc.ExitCode -ne 3010) {
            throw "Instalador do Python retornou $($proc.ExitCode)."
        }
        if (-not (Valid-Python $pythonExe)) {
            throw "Python nao foi criado em $pythonDir. Veja os logs de instalacao do Windows."
        }
    } else {
        Write-Host 'Python 3.12 64-bit ja instalado pelo BerofelStudio.'
    }
    & $pythonExe --version

    Step '3/7 - Microsoft Visual C++ Runtime x64'
    $vc = Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64' -ErrorAction SilentlyContinue
    $vcOk = $false
    if ($vc -and $vc.Installed -eq 1) {
        try { $vcOk = ([version](($vc.Version.ToString()).TrimStart('v')) -ge [version]'14.50.0.0') } catch { $vcOk = $false }
    }
    if ($vcOk) {
        Write-Host "Visual C++ ja instalado: $($vc.Version)"
    } else {
        $vcInstaller = Join-Path $downloads 'vc_redist.x64.exe'
        # A URL oficial e atualizada frequentemente. Baixar de novo para garantir versao recente.
        Fetch 'https://aka.ms/vc14/vc_redist.x64.exe' $vcInstaller
        Check-SignedExe $vcInstaller 'Microsoft Corporation'
        Write-Host 'O Windows pode solicitar permissao de administrador (UAC). Autorize.'
        $proc = Start-Process -FilePath $vcInstaller -Verb RunAs -ArgumentList '/install /quiet /norestart' -Wait -PassThru
        if ($proc.ExitCode -notin @(0, 1638, 3010)) {
            throw "Visual C++ retornou codigo $($proc.ExitCode)."
        }
        if ($proc.ExitCode -eq 3010) { Write-Warning 'Windows recomendou reiniciar o computador apos a instalacao.' }
    }

    Step '4/7 - Ambiente Python isolado e bibliotecas completas'
    Write-Host "Ambiente Python curto: $venvDir"
    if (Test-Path -LiteralPath (Join-Path $root '.venv')) {
        Write-Warning 'Existe uma pasta .venv antiga perto do projeto. Ela sera ignorada por causa do limite de caminhos do Windows.'
    }
    if ($venvDir.Length -gt 110) {
        throw "O caminho do ambiente e excepcionalmente longo ($venvDir). Extraia o projeto para uma pasta curta e verifique LOCALAPPDATA."
    }
    if ((Test-Path -LiteralPath $venvExe) -and (-not (Valid-Python $venvExe))) {
        Write-Warning 'Ambiente Python curto antigo ou quebrado detectado. Recriando...'
        Remove-Item -LiteralPath $venvDir -Recurse -Force
    }
    if (-not (Test-Path -LiteralPath $venvExe)) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $venvDir) -Force | Out-Null
        & $pythonExe -m venv $venvDir
        if ($LASTEXITCODE -ne 0) { throw "Nao foi possivel criar o ambiente Python: $LASTEXITCODE" }
    }
    if (-not (Test-Path -LiteralPath $venvExe)) { throw 'Python do ambiente isolado nao encontrado.' }
    Run-Python @('-m','ensurepip','--upgrade')
    Run-Python @('-m','pip','install','--disable-pip-version-check','--upgrade','pip','setuptools','wheel')
    Run-Python @('-m','pip','install','--disable-pip-version-check','--only-binary=:all:','-r',(Join-Path $root 'requirements.txt'))
    Run-Python @('-m','pip','check')

    Step '5/7 - FFmpeg e FFprobe (progresso e fonte alternativa)'
    & (Join-Path $PSScriptRoot 'instalar_ffmpeg.ps1') -ProjectRoot $root

    Step '6/9 - Autoteste do motor FFmpeg (dois videos + audio)'
    Run-Python @((Join-Path $root 'scripts\diagnostico_motor.py'))

    if ($InstallParakeetTdt) {
        Step '7/9 - Parakeet TDT v3 INT8/CPU, Silero ONNX e dicionário pt-BR offline'
        $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        & $powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'instalar_ia.ps1')
        if ($LASTEXITCODE -ne 0) { throw 'A instalação de Parakeet TDT/Silero falhou. Consulte o log próprio.' }
    } else {
        Write-Host 'Parakeet TDT v3 foi adiado. Instale por INSTALAR_TODAS_AS_IAS.bat.' -ForegroundColor Yellow
    }

    Step '8/9 - Qwen3-TTS Base 0.6B (motor único de voz, ambiente isolado)'
    $prepareQwen3 = [bool]$InstallQwen3
    if (-not $prepareQwen3 -and -not $SkipQwenPrompt) {
        $answer = Read-Host 'Preparar Qwen3-TTS Base local agora? Sao baixados aprox. 2,5 GB [s/N]'
        $prepareQwen3 = $answer -match '^(s|sim|y|yes)$'
    }
    if ($prepareQwen3) {
        $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        & $powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'instalar_qwen3_tts_local.ps1')
        if ($LASTEXITCODE -ne 0) { throw 'A instalacao local do Qwen3-TTS falhou. Consulte o log proprio do Qwen3.' }
    } else {
        Write-Host 'Qwen3-TTS foi adiado. Use Narração > Preparar Qwen3 local quando desejar.' -ForegroundColor Yellow
    }

    Step '9/9 - Verificacao final da instalacao principal'
    Run-Python @((Join-Path $root 'scripts\verificar.py'),'--strict','--quick','--editor-only')
    $versionSource = Join-Path $root 'berofel\__init__.py'
    if (-not (Test-Path -LiteralPath $versionSource -PathType Leaf)) {
        throw "Arquivo de versão do aplicativo não foi instalado: $versionSource"
    }
    $versionText = Get-Content -LiteralPath $versionSource -Raw
    $versionMatch = [regex]::Match($versionText, "__version__\s*=\s*'([^']+)'")
    if (-not $versionMatch.Success) { throw 'A versão do BerofelStudio não foi encontrada em berofel/__init__.py.' }
    $appVersion = $versionMatch.Groups[1].Value
    Write-Host "`n[OK] Instalacao do BerofelStudio $appVersion concluida." -ForegroundColor Green
    Write-Host 'Motor único de narração e clonagem: Qwen3-TTS Base 0.6B.'
    Write-Host 'Parakeet TDT v3/Silero: INSTALAR_TODAS_AS_IAS.bat.'
    Write-Host "Abra: $root\ABRIR_BEROFELSTUDIO.bat" -ForegroundColor Green
    Write-Host "Log de instalacao: $logFile"
    exit 0
} catch {
    Write-Host "`n[ERRO] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'Confirme internet, espaco em disco, Windows x64 e permissao para Visual C++.'
    Write-Host "Log: $logFile"
    exit 1
} finally {
    if ($transcriptStarted) { Stop-Transcript | Out-Null }
}

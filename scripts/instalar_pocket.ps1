param([switch]$CatalogOnly)
# Complementa o ambiente existente; executado também pelo instalador principal.
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$venvDir=Join-Path $env:LOCALAPPDATA 'BFS\venv'
$venv=Join-Path $venvDir 'Scripts\python.exe'
$logs=Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$log=Join-Path $logs ('pocket_tts_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '.log')
$started=$false
try {
    Start-Transcript -LiteralPath $log -ErrorAction Stop | Out-Null
    $started=$true
    & (Join-Path $PSScriptRoot 'verificar_editor_fechado.ps1') -VenvDir $venvDir
    if (-not (Test-Path -LiteralPath $venv)) { throw 'Execute instalar_dependencias.bat primeiro.' }
    Write-Host '[1/4] Instalando Pocket TTS e dependencias do PyTorch/CPU...' -ForegroundColor Cyan
    & $venv -m pip install --disable-pip-version-check --only-binary=:all: -r (Join-Path $root 'requirements-pocket-tts.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Instalacao do Pocket TTS falhou.' }
    & $venv -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Conflito nas dependencias de IA.' }
    Write-Host '[2/4] Preparando estados de voz portugueses precomputados (sem WAV de referência)...' -ForegroundColor Cyan
    & $venv (Join-Path $PSScriptRoot 'preparar_vozes_pocket.py')
    Write-Host '[3/4] Verificando biblioteca e dependencias...' -ForegroundColor Cyan
    & $venv (Join-Path $PSScriptRoot 'testar_pocket.py')
    if ($LASTEXITCODE -ne 0) { throw 'Pocket TTS nao pode ser importado.' }
    Write-Host '[4/4] Validacao de clonagem pessoal...' -ForegroundColor Cyan
    $cloneReady=$false
    if ($CatalogOnly) {
        Write-Host 'Preparacao dos pesos gated adiada para o fluxo explicito no editor.' -ForegroundColor Yellow
    } else {
        Write-Host 'Esta etapa pode baixar o checkpoint oficial de clonagem, que e grande e requer aceite dos termos.' -ForegroundColor Yellow
        $accepted=Read-Host 'Voce ja aceitou os termos em https://huggingface.co/kyutai/pocket-tts e quer preparar a clonagem agora? [s/N]'
        if ($accepted -match '^(s|sim|y|yes)$') {
            $cloneReady=$true
            & $venv (Join-Path $PSScriptRoot 'preparar_modelo_pocket.py')
            if ($LASTEXITCODE -ne 0) {
                $cloneReady=$false
                Write-Warning 'Os pesos nao foram validados; voz de catalogo continua instalada.'
                Write-Host 'Tente depois em Narracao > Preparar clonagem local ou AUTORIZAR_POCKET_TTS.bat.' -ForegroundColor Yellow
            }
        }
    }
    if ($cloneReady) {
        Write-Host '[OK] Pocket TTS e clonagem de voz foram validados. Veja TESTAR_POCKET_TTS.bat.' -ForegroundColor Green
    } else {
        Write-Host '[OK] Pocket TTS de catalogo instalado; clonagem de voz pessoal continua pendente.' -ForegroundColor Yellow
        Write-Host 'Conclua o aceite e use Narração > Preparar clonagem local (ou AUTORIZAR_POCKET_TTS.bat) quando o Hugging Face estiver acessivel.' -ForegroundColor Yellow
    }
    exit 0
} catch {
    Write-Host "[ERRO] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Log: $log"
    exit 1
} finally { if ($started) { Stop-Transcript | Out-Null } }

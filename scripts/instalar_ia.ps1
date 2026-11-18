# Complemento opcional para Faster-Whisper; não altera o instalador base.
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$venvDir=Join-Path $env:LOCALAPPDATA 'BFS\venv'
$venv=Join-Path $venvDir 'Scripts\python.exe'
$logs=Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$log=Join-Path $logs ('ia_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '.log')
$started=$false
try {
    Start-Transcript -LiteralPath $log -ErrorAction Stop | Out-Null
    $started=$true
    & (Join-Path $PSScriptRoot 'verificar_editor_fechado.ps1') -VenvDir $venvDir
    if (-not (Test-Path -LiteralPath $venv)) { throw 'Execute instalar_dependencias.bat antes de instalar a IA.' }
    Write-Host '[1/3] Instalando bibliotecas da transcricao e todas as dependencias indiretas.' -ForegroundColor Cyan
    & $venv -m pip install --disable-pip-version-check --only-binary=:all: -r (Join-Path $root 'requirements-ai.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar bibliotecas de IA.' }
    Write-Host '[2/3] Baixando Whisper Base para uso offline (internet necessaria).' -ForegroundColor Cyan
    & $venv (Join-Path $PSScriptRoot 'preparar_modelos.py')
    if ($LASTEXITCODE -ne 0) { throw 'Falha no download do modelo.' }
    Write-Host '[3/3] Autoteste de pacotes e modelo.' -ForegroundColor Cyan
    & $venv (Join-Path $PSScriptRoot 'verificar.py') --ai --strict
    if ($LASTEXITCODE -ne 0) { throw 'Autoteste da IA falhou.' }
    Write-Host '[OK] Analise experimental de repeticoes instalada.' -ForegroundColor Green
    exit 0
} catch {
    Write-Host "[ERRO] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Log: $log"
    exit 1
} finally { if ($started) { Stop-Transcript | Out-Null } }

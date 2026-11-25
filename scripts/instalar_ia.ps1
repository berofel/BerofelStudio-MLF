# Complemento opcional para Parakeet TDT v3 INT8/CPU e Silero VAD ONNX.
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
    Write-Host '[1/4] Instalando onnx-asr/ONNX Runtime CPU e dependencias.' -ForegroundColor Cyan
    & $venv -m pip install --disable-pip-version-check --only-binary=:all: -r (Join-Path $root 'requirements-ai.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar bibliotecas de IA.' }
    Write-Host '[2/4] Baixando e validando Parakeet TDT v3 INT8 e Silero VAD ONNX.' -ForegroundColor Cyan
    & $venv (Join-Path $PSScriptRoot 'instalar_parakeet_tdt_v3.py')
    if ($LASTEXITCODE -ne 0) { throw 'Falha no download ou teste local do Parakeet TDT v3.' }
    Write-Host '[3/4] Autoteste de pacotes e modelo.' -ForegroundColor Cyan
    & $venv (Join-Path $PSScriptRoot 'verificar.py') --ai --strict
    if ($LASTEXITCODE -ne 0) { throw 'Autoteste da IA falhou.' }
    Write-Host '[4/4] Preparando dicionario ortografico pt-BR local (VERO).' -ForegroundColor Cyan
    & $venv (Join-Path $PSScriptRoot 'instalar_corretor_pt_br.py')
    if ($LASTEXITCODE -ne 0) {
        Write-Warning 'O ASR continua instalado; a revisao ortografica pode ser preparada depois com scripts\instalar_corretor_pt_br.py.'
    }
    Write-Host '[OK] Parakeet TDT v3 INT8/CPU e Silero ONNX preparados para uso offline.' -ForegroundColor Green
    exit 0
} catch {
    Write-Host "[ERRO] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Log: $log"
    exit 1
} finally { if ($started) { Stop-Transcript | Out-Null } }

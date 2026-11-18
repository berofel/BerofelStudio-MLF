# Retoma a instalacao do BerofelStudio sem reinstalar Python e pip.
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$root = Split-Path -Parent $PSScriptRoot
$venvDir = Join-Path $env:LOCALAPPDATA 'BFS\venv'
$venvExe = Join-Path $venvDir 'Scripts\python.exe'
$logs = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$logFile = Join-Path $logs ('continuacao_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '.log')
$transcript = $false
try {
    Start-Transcript -LiteralPath $logFile -ErrorAction Stop | Out-Null
    $transcript = $true
    & (Join-Path $PSScriptRoot 'verificar_editor_fechado.ps1') -VenvDir $venvDir
    Write-Host 'BerofelStudio: retomando somente etapas que faltam.' -ForegroundColor Cyan
    if (-not (Test-Path -LiteralPath $venvExe)) { throw "Ambiente Python nao encontrado: $venvExe. Rode instalar_dependencias.bat." }
    Write-Host 'Verificando e instalando bibliotecas faltantes para o codigo atual...'
    & $venvExe -m pip install --disable-pip-version-check --only-binary=:all: -r (Join-Path $root 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao completar pacotes Python. Rode instalar_dependencias.bat.' }
    & $venvExe -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependencias Python incompletas. Rode instalar_dependencias.bat.' }
    Write-Host "`nETAPA 5/7 - FFmpeg e FFprobe (com progresso, tempo limite e fonte alternativa)" -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot 'instalar_ffmpeg.ps1') -ProjectRoot $root
    Write-Host "`nETAPA 6/7 - Testando composicao multitrilha" -ForegroundColor Cyan
    & $venvExe (Join-Path $PSScriptRoot 'diagnostico_motor.py')
    if ($LASTEXITCODE -ne 0) { throw 'Falha no teste de composicao FFmpeg.' }
    Write-Host "`nETAPA 7/7 - Verificando instalacao" -ForegroundColor Cyan
    & $venvExe (Join-Path $PSScriptRoot 'verificar.py') --strict --quick --editor-only
    if ($LASTEXITCODE -ne 0) { throw 'Autoteste encontrou problemas. Veja o log.' }
    Write-Host '[OK] Instalacao retomada e concluida.' -ForegroundColor Green
    Write-Host "Abra ABRIR_BEROFELSTUDIO.bat. Log: $logFile" -ForegroundColor Green
    exit 0
} catch {
    Write-Host "[ERRO] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Log: $logFile"
    exit 1
} finally {
    if ($transcript) { Stop-Transcript | Out-Null }
}

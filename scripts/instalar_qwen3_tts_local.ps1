$ErrorActionPreference='Stop'
$base=Join-Path $env:LOCALAPPDATA 'BFS\qwen3_tts'
$venv=Join-Path $base 'venv'
$python=Join-Path $venv 'Scripts\python.exe'
New-Item -ItemType Directory -Force -Path $base | Out-Null

try {
  if(-not (Test-Path -LiteralPath $python)) {
    $launcher=Get-Command py.exe -ErrorAction SilentlyContinue
    if(-not $launcher) { throw 'Python 3.12 e o launcher py.exe são necessários. Instale Python 3.12 (64 bits) e tente novamente.' }
    & $launcher.Source -3.12 -m venv $venv
    if($LASTEXITCODE -ne 0) { throw 'Não foi possível criar o ambiente isolado Python 3.12.' }
  }
  $runtimeReady=$false
  if(Test-Path -LiteralPath $python) {
    & $python -c "import torch,qwen_tts,importlib.metadata; assert importlib.metadata.version('qwen-tts')=='0.1.1'; print(qwen_tts.__file__)" *> $null
    $runtimeReady=($LASTEXITCODE -eq 0)
  }
  if(-not $runtimeReady) {
    Write-Host '[1/3] Instalando PyTorch CPU no ambiente isolado. Isso pode levar alguns minutos.' -ForegroundColor Cyan
    & $python -m pip install --upgrade pip
    if($LASTEXITCODE -ne 0) { throw 'Falha ao atualizar pip no ambiente isolado.' }
    & $python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
    if($LASTEXITCODE -ne 0) { throw 'Falha ao instalar PyTorch CPU.' }
    Write-Host '[2/3] Instalando Qwen3-TTS e dependências isoladas.' -ForegroundColor Cyan
    & $python -m pip install qwen-tts==0.1.1
    if($LASTEXITCODE -ne 0) { throw 'Falha ao instalar qwen-tts==0.1.1.' }
  } else { Write-Host '[1/3] Runtime Qwen3 isolado já está instalado.' -ForegroundColor Cyan }
  $complete=(Test-Path -LiteralPath (Join-Path $base 'model\config.json')) -and
            (Test-Path -LiteralPath (Join-Path $base 'model\model.safetensors')) -and
            (Test-Path -LiteralPath (Join-Path $base 'model\preprocessor_config.json')) -and
            (Test-Path -LiteralPath (Join-Path $base 'model\tokenizer_config.json')) -and
            (Test-Path -LiteralPath (Join-Path $base 'model\vocab.json')) -and
            (Test-Path -LiteralPath (Join-Path $base 'model\merges.txt')) -and
            (Test-Path -LiteralPath (Join-Path $base 'model\speech_tokenizer\config.json')) -and
            (Test-Path -LiteralPath (Join-Path $base 'model\speech_tokenizer\configuration.json')) -and
            (Test-Path -LiteralPath (Join-Path $base 'model\speech_tokenizer\model.safetensors')) -and
            (Test-Path -LiteralPath (Join-Path $base 'model\speech_tokenizer\preprocessor_config.json'))
  if(-not $complete) {
    Write-Host '[3/3] Baixando o modelo público Qwen3-TTS Base 0.6B (~2,5 GB).' -ForegroundColor Cyan
    & $python (Join-Path $PSScriptRoot 'baixar_qwen3_tts_local.py')
    if($LASTEXITCODE -ne 0) { throw 'Falha no download/verificação do modelo.' }
  } else { Write-Host '[3/3] Pesos Qwen3 já estão completos; download ignorado.' -ForegroundColor Cyan }
  Write-Host 'Preparação concluída. A geração usa CPU e os pesos locais; reinicie o BerofelStudio.' -ForegroundColor Green
} catch {
  Write-Error $_
  exit 1
}

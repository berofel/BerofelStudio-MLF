param(
  [Parameter(Mandatory=$true)][string]$BuildDirectory,
  [Parameter(Mandatory=$true)][string]$Q4ModelPath,
  [Parameter(Mandatory=$true)][string]$TokenizerPath,
  [switch]$Replace
)
$ErrorActionPreference='Stop'
$build=(Resolve-Path -LiteralPath $BuildDirectory).Path
$model=(Resolve-Path -LiteralPath $Q4ModelPath).Path
$tokenizer=(Resolve-Path -LiteralPath $TokenizerPath).Path
$required=@('qwen3-tts-cli.exe','libqwen3tts.dll','libomp.dll','libc++.dll','libunwind.dll')
foreach($name in $required){
  if(-not (Test-Path -LiteralPath (Join-Path $build $name) -PathType Leaf)){
    throw "Runtime nativo incompleto: falta $name em $build"
  }
}
if((Get-Item -LiteralPath $model).Length -lt 800MB){
  throw 'O modelo informado é pequeno demais para um Qwen3-TTS 0.6B Q4_0 experimental válido.'
}
if((Get-Item -LiteralPath $tokenizer).Length -lt 400MB){
  throw 'O tokenizer informado parece incompleto.'
}
$destination=Join-Path $env:LOCALAPPDATA 'BFS\qwen3_tts\native_turbo'
$bin=Join-Path $destination 'bin';$models=Join-Path $destination 'models'
New-Item -ItemType Directory -Force -Path $bin,$models | Out-Null
$files=@{}
foreach($name in $required){$files[(Join-Path $bin $name)]=(Join-Path $build $name)}
$files[(Join-Path $models 'qwen3-tts-0.6b-q4_0.gguf')]=$model
$files[(Join-Path $models 'qwen3-tts-tokenizer-f16-f32.gguf')]=$tokenizer
foreach($target in $files.Keys){
  if(Test-Path -LiteralPath $target){
    $sourceHash=(Get-FileHash -LiteralPath $files[$target] -Algorithm SHA256).Hash
    $targetHash=(Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
    if($sourceHash -eq $targetHash){continue}
    if(-not $Replace){throw "Arquivo existente diferente, preservado: $target. Use -Replace para substituí-lo com backup."}
    $backup="$target.backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Copy-Item -LiteralPath $target -Destination $backup
  }
  $pending="$target.installing"
  Copy-Item -LiteralPath $files[$target] -Destination $pending -Force
  if((Get-FileHash -LiteralPath $files[$target] -Algorithm SHA256).Hash -ne
     (Get-FileHash -LiteralPath $pending -Algorithm SHA256).Hash){
    Remove-Item -LiteralPath $pending -Force
    throw "Falha na verificação do arquivo copiado: $target"
  }
  Move-Item -LiteralPath $pending -Destination $target -Force
}
Write-Host "Runtime Turbo Q4 instalado e verificado em: $destination"
Write-Host 'O modo Original continua selecionado por padrão; reinicie o BerofelStudio para mostrar a opção experimental.'

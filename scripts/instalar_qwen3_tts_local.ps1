$ErrorActionPreference='Stop'
$base=Join-Path $env:LOCALAPPDATA 'BFS\qwen3_tts'
$venv=Join-Path $base 'venv'
$python=Join-Path $venv 'Scripts\python.exe'
New-Item -ItemType Directory -Force -Path $base | Out-Null

function Invoke-NativeCommand {
  param([Parameter(Mandatory=$true)][string]$FilePath,
        [Parameter(Mandatory=$true)][string[]]$Arguments)
  # Do not use the PowerShell call operator here: on Windows PowerShell,
  # native stderr (including an expected ImportError in the probe) can become
  # a terminating RemoteException when ErrorActionPreference is Stop.
  $start=New-Object System.Diagnostics.ProcessStartInfo
  $start.FileName=$FilePath
  $start.UseShellExecute=$false
  $start.CreateNoWindow=$true
  $start.RedirectStandardOutput=$true
  $start.RedirectStandardError=$true
  $quotedArguments=foreach($argument in $Arguments) {
    $value=[string]$argument
    if($value -notmatch '[\s"]') { $value; continue }
    $builder=New-Object System.Text.StringBuilder
    [void]$builder.Append('"')
    $slashes=0
    foreach($character in $value.ToCharArray()) {
      if($character -eq '\') { $slashes++; continue }
      if($character -eq '"') {
        [void]$builder.Append(('\' * (2*$slashes+1)))
        [void]$builder.Append('"')
        $slashes=0
        continue
      }
      if($slashes) { [void]$builder.Append(('\' * $slashes)); $slashes=0 }
      [void]$builder.Append($character)
    }
    if($slashes) { [void]$builder.Append(('\' * (2*$slashes))) }
    [void]$builder.Append('"')
    $builder.ToString()
  }
  $start.Arguments=[string]::Join(' ',[string[]]$quotedArguments)
  $process=New-Object System.Diagnostics.Process
  $process.StartInfo=$start
  try {
    [void]$process.Start()
    # Read both pipes asynchronously to avoid deadlock on verbose pip output.
    $stdoutTask=$process.StandardOutput.ReadToEndAsync()
    $stderrTask=$process.StandardError.ReadToEndAsync()
    $process.WaitForExit()
    $stdout=$stdoutTask.GetAwaiter().GetResult()
    $stderr=$stderrTask.GetAwaiter().GetResult()
    if($stdout) { Write-Host $stdout.TrimEnd() }
    if($stderr) { Write-Host $stderr.TrimEnd() }
    return $process.ExitCode
  } finally {
    $process.Dispose()
  }
}

try {
  if(-not (Test-Path -LiteralPath $python)) {
    $launcher=Get-Command py.exe -ErrorAction SilentlyContinue
    if(-not $launcher) { throw 'Python 3.12 e o launcher py.exe são necessários. Instale Python 3.12 (64 bits) e tente novamente.' }
    $venvExit=Invoke-NativeCommand -FilePath $launcher.Source -Arguments @('-3.12','-m','venv',$venv)
    if($venvExit -ne 0) { throw 'Não foi possível criar o ambiente isolado Python 3.12.' }
  }
  $runtimeReady=$false
  if(Test-Path -LiteralPath $python) {
    $probeExit=Invoke-NativeCommand -FilePath $python -Arguments @('-c',"import sys,torch,torchaudio,qwen_tts,importlib.metadata; from packaging.version import Version; tv=Version(torch.__version__.split('+')[0]); av=Version(torchaudio.__version__.split('+')[0]); assert sys.maxsize>2**32; assert importlib.metadata.version('qwen-tts')=='0.1.1'; assert torch.version.cuda is None; assert ((av>=Version('2.11') and tv>=Version('2.11')) or tv.release[:2]==av.release[:2]); print(qwen_tts.__file__)")
    $runtimeReady=($probeExit -eq 0)
    if(-not $runtimeReady) { Write-Host 'Runtime incompleto; vou instalar as dependências no ambiente isolado.' -ForegroundColor Yellow }
  }
  if(-not $runtimeReady) {
    Write-Host '[1/3] Instalando PyTorch CPU no ambiente isolado. Isso pode levar alguns minutos.' -ForegroundColor Cyan
    $pipExit=Invoke-NativeCommand -FilePath $python -Arguments @('-m','pip','install','--disable-pip-version-check','--timeout','120','--retries','10','--upgrade','pip')
    if($pipExit -ne 0) { throw 'Falha ao atualizar pip no ambiente isolado.' }
    # Keep the CPU pair pinned: independently selecting latest torch and
    # torchaudio can produce incompatible/mismatched versions on Windows.
    $torchExit=Invoke-NativeCommand -FilePath $python -Arguments @('-m','pip','install','--disable-pip-version-check','--timeout','120','--retries','10','torch==2.11.0','torchaudio==2.11.0','--index-url','https://download.pytorch.org/whl/cpu')
    if($torchExit -ne 0) { throw 'Falha ao instalar PyTorch CPU.' }
    Write-Host '[2/3] Instalando Qwen3-TTS e dependências isoladas.' -ForegroundColor Cyan
    $qwenExit=Invoke-NativeCommand -FilePath $python -Arguments @('-m','pip','install','--disable-pip-version-check','--timeout','120','--retries','10','qwen-tts==0.1.1')
    if($qwenExit -ne 0) { throw 'Falha ao instalar qwen-tts==0.1.1.' }
  } else { Write-Host '[1/3] Runtime Qwen3 isolado já está instalado.' -ForegroundColor Cyan }
  # The isolated worker imports the editor's audio normalizer, which relies on
  # imageio_ffmpeg. Install it here too; the main editor venv is not inherited.
  $ffmpegDependencyExit=Invoke-NativeCommand -FilePath $python -Arguments @('-m','pip','install','--disable-pip-version-check','--timeout','120','--retries','10','imageio-ffmpeg>=0.6,<1')
  if($ffmpegDependencyExit -ne 0) { throw 'Falha ao instalar imageio-ffmpeg no ambiente Qwen isolado.' }
  $validationExit=Invoke-NativeCommand -FilePath $python -Arguments @('-c',"import sys,torch,torchaudio,qwen_tts,imageio_ffmpeg,importlib.metadata; from packaging.version import Version; tv=Version(torch.__version__.split('+')[0]); av=Version(torchaudio.__version__.split('+')[0]); assert sys.maxsize>2**32, 'Python 64-bit obrigatório'; assert importlib.metadata.version('qwen-tts')=='0.1.1', 'versão qwen-tts inesperada'; assert torch.version.cuda is None, 'o runtime deve ser CPU'; assert ((av>=Version('2.11') and tv>=Version('2.11')) or tv.release[:2]==av.release[:2]), 'combinação torch/torchaudio incompatível'; print('Runtime CPU validado:',torch.__version__,torchaudio.__version__); print('FFmpeg Python validado:',imageio_ffmpeg.__file__)")
  if($validationExit -ne 0) { throw 'O runtime foi instalado, mas a validação de torch/torchaudio/Qwen falhou. Consulte a saída acima.' }
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
    $modelExit=Invoke-NativeCommand -FilePath $python -Arguments @((Join-Path $PSScriptRoot 'baixar_qwen3_tts_local.py'))
    if($modelExit -ne 0) { throw 'Falha no download/verificação do modelo.' }
  } else { Write-Host '[3/3] Pesos Qwen3 já estão completos; download ignorado.' -ForegroundColor Cyan }
  Write-Host 'Preparação concluída. A geração usa CPU e os pesos locais; reinicie o BerofelStudio.' -ForegroundColor Green
} catch {
  $failure=$_
  Write-Host ''
  Write-Host '[ERRO] A preparação local do Qwen3 falhou.' -ForegroundColor Red
  Write-Host ('Causa: '+$failure.Exception.ToString()) -ForegroundColor Red
  if($failure.InvocationInfo -and $failure.InvocationInfo.PositionMessage) {
    Write-Host $failure.InvocationInfo.PositionMessage -ForegroundColor DarkRed
  }
  if($failure.ScriptStackTrace) { Write-Host $failure.ScriptStackTrace -ForegroundColor DarkRed }
  Write-Host ('O ambiente parcial foi preservado para permitir nova tentativa. Caminho: '+$base) -ForegroundColor Yellow
  exit 1
}

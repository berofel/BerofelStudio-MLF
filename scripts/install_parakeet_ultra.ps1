param(
  [switch]$ModelOnly,
  [switch]$RuntimeOnly
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'Continue'
$version = '0.4.2'
$base = Join-Path $env:LOCALAPPDATA 'BFS'
$toolRoot = Join-Path $base "tools\transcribe.cpp\$version"
$runtimeFinal = Join-Path $toolRoot 'runtime'
$modelFinal = Join-Path $base 'models\parakeet-ultra\parakeet-ultra-Q8_0.gguf'
$wheelFinal = Join-Path $toolRoot 'transcribe_cpp-0.4.2-py3-none-any.whl'
$tempRoot = Join-Path $env:TEMP "berofel-parakeet-install-$PID"
New-Item -ItemType Directory -Force -Path $toolRoot,(Split-Path $modelFinal -Parent),$tempRoot | Out-Null

function Get-Sha256([string]$Path) {
  return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Save-Verified([string]$Url,[string]$Destination,[string]$ExpectedHash) {
  if (Test-Path -LiteralPath $Destination) {
    if ((Get-Sha256 $Destination) -eq $ExpectedHash) { return }
  }
  $partial = "$Destination.partial"
  Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue
  Invoke-WebRequest -Uri $Url -OutFile $partial
  $actual = Get-Sha256 $partial
  if ($actual -ne $ExpectedHash) {
    Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue
    throw "Checksum SHA-256 inválido para $([IO.Path]::GetFileName($Destination)): $actual"
  }
  Move-Item -LiteralPath $partial -Destination $Destination -Force
}

try {
  if (-not $ModelOnly) {
    $runtimeContract = Join-Path $runtimeFinal 'contract.json'
    $runtimeHealthy = $false
    if ((Test-Path -LiteralPath (Join-Path $runtimeFinal 'transcribe.dll')) -and
        (Test-Path -LiteralPath $runtimeContract)) {
      try {
        $installedContract = Get-Content -LiteralPath $runtimeContract -Raw | ConvertFrom-Json
        $runtimeHealthy = ($installedContract.version -eq $version -and
          $installedContract.backends -contains 'cpu' -and
          $installedContract.backends -contains 'vulkan')
      } catch { $runtimeHealthy = $false }
    }
    $wheelHash = '2e4a5d3e7ba78918969ccb1ee06f3d5c6c79664e0626d0da0ffe832f465e6d51'
    $wheelHealthy = ((Test-Path -LiteralPath $wheelFinal) -and
                     ((Get-Sha256 $wheelFinal) -eq $wheelHash))
    $archive = Join-Path $tempRoot 'transcribe-native-windows-x86_64-cpu-vulkan.tar.gz'
    if (-not $runtimeHealthy -or -not $wheelHealthy) {
      Save-Verified 'https://github.com/handy-computer/transcribe.cpp/releases/download/v0.4.2/transcribe-native-0.4.2-windows-x86_64-cpu-vulkan.tar.gz' `
        $archive '6094102cf57b404b050707ceb258b12ce647b92e801b5d46077214e5b030c8aa'
      if (-not $wheelHealthy) {
        $wheelTemp = Join-Path $tempRoot 'transcribe_cpp-0.4.2-py3-none-any.whl'
        Save-Verified 'https://github.com/handy-computer/transcribe.cpp/releases/download/v0.4.2/transcribe_cpp-0.4.2-py3-none-any.whl' `
          $wheelTemp $wheelHash
        $wheelStaged = "$wheelFinal.new"
        Copy-Item -LiteralPath $wheelTemp -Destination $wheelStaged -Force
        Move-Item -LiteralPath $wheelStaged -Destination $wheelFinal -Force
      }
    }
    if (-not $runtimeHealthy) {
      $extract = Join-Path $tempRoot 'runtime'
      New-Item -ItemType Directory -Force -Path $extract | Out-Null
      & tar.exe -xzf $archive -C $extract
      if ($LASTEXITCODE -ne 0) { throw 'Falha ao extrair o runtime transcribe.cpp.' }
      $native = Get-ChildItem -LiteralPath $extract -Directory | Select-Object -First 1
      if (-not $native -or -not (Test-Path (Join-Path $native.FullName 'transcribe.dll'))) {
        throw 'O pacote oficial não contém transcribe.dll no caminho esperado.'
      }
      $stagedRuntime = "$runtimeFinal.new"
      if (Test-Path -LiteralPath $stagedRuntime) {
        Remove-Item -LiteralPath $stagedRuntime -Recurse -Force
      }
      Move-Item -LiteralPath $native.FullName -Destination $stagedRuntime
      if (Test-Path -LiteralPath $runtimeFinal) {
        $staleName = "runtime.stale-$([DateTime]::UtcNow.ToString('yyyyMMddHHmmss'))"
        Rename-Item -LiteralPath $runtimeFinal -NewName $staleName
      }
      Move-Item -LiteralPath $stagedRuntime -Destination $runtimeFinal
    }
  }

  if (-not $RuntimeOnly) {
    Save-Verified 'https://huggingface.co/handy-computer/parakeet-ultra-gguf/resolve/0601ff70a9762452712c552da05c17b9ddf8d968/parakeet-ultra-Q8_0.gguf' `
      $modelFinal '007a59761e9258779f189df396b50d12b83bb5b79e66df4b955c230d2f2a0a59'
  }

  $required = @((Join-Path $runtimeFinal 'transcribe.dll'),$wheelFinal)
  if (-not $ModelOnly) {
    foreach ($file in $required) {
      if (-not (Test-Path -LiteralPath $file)) { throw "Arquivo de runtime ausente: $file" }
    }
    $contract = Get-Content (Join-Path $runtimeFinal 'contract.json') -Raw | ConvertFrom-Json
    if ($contract.version -ne $version -or $contract.backends -notcontains 'vulkan' -or $contract.backends -notcontains 'cpu') {
      throw 'Runtime instalado não corresponde à versão/backends esperados.'
    }
  }
  if (-not $RuntimeOnly -and (Get-Sha256 $modelFinal) -ne '007a59761e9258779f189df396b50d12b83bb5b79e66df4b955c230d2f2a0a59') {
    throw 'Validação final do modelo falhou.'
  }
  Write-Host 'Parakeet Ultra Q8 local verificado.' -ForegroundColor Green
  Write-Host "Runtime: $runtimeFinal"
  Write-Host "Binding: $wheelFinal"
  Write-Host "Modelo: $modelFinal"
  Write-Host 'A opção aparecerá no seletor de ASR depois de reiniciar o Berofel Studio.'
}
catch {
  Write-Error "Instalação Parakeet não concluída: $($_.Exception.Message)"
  exit 1
}
finally {
  Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}

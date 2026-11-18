# Instalador FFmpeg do BerofelStudio (Windows PowerShell 5.1)
# Tenta gyan.dev e, em caso de falha, GitHub BtbN com checksum SHA256.
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$venvDir = Join-Path $env:LOCALAPPDATA 'BFS\venv'
& (Join-Path $PSScriptRoot 'verificar_editor_fechado.ps1') -VenvDir $venvDir
$ProgressPreference = 'SilentlyContinue' # A barra visual do Invoke-WebRequest nao e usada.
$downloadDir = Join-Path $env:LOCALAPPDATA 'BerofelStudio\downloads'
$stageDir = Join-Path $env:LOCALAPPDATA 'BFS\ffmpeg_stage'
$targetDir = Join-Path $ProjectRoot 'tools\ffmpeg'
New-Item -ItemType Directory -Force -Path $downloadDir,$targetDir | Out-Null

function Download-Progress([string]$url, [string]$destination, [int64]$minBytes=1000) {
    $partial = "$destination.download"
    if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force }
    Write-Host "Baixando: $url"
    Write-Host 'Conexao: aguarde no maximo 35 segundos pelo primeiro dado; depois o progresso aparece abaixo.'
    $request = $null
    $response = $null
    $stream = $null
    $output = $null
    $clock = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $request = [System.Net.HttpWebRequest]::Create($url)
        $request.Method = 'GET'
        $request.Timeout = 35000
        $request.ReadWriteTimeout = 35000
        $request.UserAgent = 'BerofelStudio-Installer/0.1'
        $request.AllowAutoRedirect = $true
        $request.MaximumAutomaticRedirections = 7
        $response = $request.GetResponse()
        $size = [int64]$response.ContentLength
        $stream = $response.GetResponseStream()
        $stream.ReadTimeout = 35000
        $output = [System.IO.File]::Open($partial, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
        $buffer = New-Object byte[] 131072
        [int64]$count = 0
        [int]$lastReport = -1
        while ($true) {
            $read = $stream.Read($buffer,0,$buffer.Length)
            if ($read -le 0) { break }
            $output.Write($buffer,0,$read)
            $count += $read
            $seconds = [int][Math]::Floor($clock.Elapsed.TotalSeconds)
            if ($seconds -ge ($lastReport + 4)) {
                $lastReport = $seconds
                $mb = [Math]::Round($count / 1MB, 1)
                if ($size -gt 0) {
                    $pct = [Math]::Round((100.0 * $count / $size),1)
                    Write-Host "Progresso: $mb MB / $([Math]::Round($size / 1MB,1)) MB ($pct`%)"
                } else { Write-Host "Progresso: $mb MB recebidos" }
            }
        }
        $output.Flush()
        $output.Dispose(); $output = $null
        if ($count -lt $minBytes) { throw "Arquivo recebido e pequeno demais: $count bytes" }
        if ($size -ge 0 -and $count -ne $size) { throw "Download incompleto: $count / $size bytes" }
        Move-Item -LiteralPath $partial -Destination $destination -Force
        Write-Host "[OK] Download recebido: $([Math]::Round($count / 1MB,1)) MB"
    } catch {
        if ($request) { try { $request.Abort() } catch {} }
        if ($output) { $output.Dispose() }
        if ($stream) { $stream.Dispose() }
        if ($response) { $response.Dispose() }
        if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue }
        throw "Download falhou/sem atividade por tempo demais: $($_.Exception.Message)"
    } finally {
        if ($output) { $output.Dispose() }
        if ($stream) { $stream.Dispose() }
        if ($response) { $response.Dispose() }
        $clock.Stop()
    }
}

function Download-Retry([string]$url, [string]$dest, [int64]$minimum = 1000) {
    for ($attempt=1; $attempt -le 2; $attempt++) {
        try { Download-Progress $url $dest $minimum; return }
        catch {
            Write-Warning "Tentativa $attempt/2 falhou: $($_.Exception.Message)"
            if ($attempt -eq 2) { throw }
            Start-Sleep -Seconds 2
        }
    }
}

function Expected-Hash([string]$checksumPath, [string]$fileName) {
    $lines = Get-Content -LiteralPath $checksumPath -ErrorAction Stop
    $specific = $lines | Where-Object { $_ -match [regex]::Escape($fileName) } | Select-Object -First 1
    if (-not $specific -and $lines.Count -eq 1) { $specific = $lines[0] }
    if (-not $specific) { throw "Checksum nao encontrado para $fileName" }
    $match = [regex]::Match([string]$specific,'(?i)\b[a-f0-9]{64}\b')
    if (-not $match.Success) { throw "Checksum SHA256 invalido em $checksumPath" }
    return $match.Value.ToUpperInvariant()
}

function Get-ValidatedArchive([string]$source, [string]$archiveName, [string]$archiveUrl, [string]$checksumUrl) {
    $archive = Join-Path $downloadDir $archiveName
    $checksum = Join-Path $downloadDir ($source + '.sha256')
    Download-Retry $checksumUrl $checksum 64
    $expected = Expected-Hash $checksum $archiveName
    $possible = @($archive, (Join-Path $env:USERPROFILE ('Downloads\' + $archiveName)))
    foreach ($candidate in $possible) {
        if (Test-Path -LiteralPath $candidate) {
            $actual = (Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToUpperInvariant()
            if ($actual -eq $expected) {
                Write-Host "[OK] ZIP valido no cache ou Downloads: $candidate"
                return $candidate
            }
            Write-Warning "ZIP com checksum divergente, ignorado: $candidate"
        }
    }
    Download-Retry $archiveUrl $archive 1000000
    $actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($actual -ne $expected) { throw "SHA256 nao confere em $source. Arquivo recusado." }
    Write-Host '[OK] SHA256 conferido com checksum publicado pelo distribuidor.'
    return $archive
}

function Install-Archive([string]$zipFile) {
    if (Test-Path -LiteralPath $stageDir) { Remove-Item -LiteralPath $stageDir -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $stageDir | Out-Null
    Write-Host 'Extraindo os executaveis FFmpeg/FFprobe. Pode usar disco sem usar rede.'
    Expand-Archive -LiteralPath $zipFile -DestinationPath $stageDir -Force
    $ff = Get-ChildItem -LiteralPath $stageDir -Filter 'ffmpeg.exe' -Recurse -File | Select-Object -First 1
    $probe = Get-ChildItem -LiteralPath $stageDir -Filter 'ffprobe.exe' -Recurse -File | Select-Object -First 1
    if (-not $ff -or -not $probe) { throw 'ZIP sem ffmpeg.exe e ffprobe.exe.' }
    Copy-Item -LiteralPath $ff.FullName -Destination (Join-Path $targetDir 'ffmpeg.exe') -Force
    Copy-Item -LiteralPath $probe.FullName -Destination (Join-Path $targetDir 'ffprobe.exe') -Force
    Remove-Item -LiteralPath $stageDir -Recurse -Force
}

function Valid-Tools() {
    $ffmpeg = Join-Path $targetDir 'ffmpeg.exe'
    $ffprobe = Join-Path $targetDir 'ffprobe.exe'
    if (-not (Test-Path -LiteralPath $ffmpeg) -or -not (Test-Path -LiteralPath $ffprobe)) { return $false }
    & $ffmpeg -hide_banner -version | Select-Object -First 1 | Out-Host
    if ($LASTEXITCODE -ne 0) { return $false }
    & $ffprobe -hide_banner -version | Select-Object -First 1 | Out-Host
    return ($LASTEXITCODE -eq 0)
}

if (Valid-Tools) {
    Write-Host '[OK] FFmpeg e FFprobe ja funcionam. Nada a baixar.' -ForegroundColor Green
    return
}

$sources = @(
    @{ name='gyan'; zip='ffmpeg-release-essentials.zip'; url='https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'; sum='https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip.sha256' },
    @{ name='btbn'; zip='ffmpeg-master-latest-win64-gpl.zip'; url='https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip'; sum='https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/checksums.sha256' }
)
$failures = @()
foreach ($source in $sources) {
    try {
        Write-Host "`nTentando origem: $($source.name)" -ForegroundColor Cyan
        $zipFile = Get-ValidatedArchive $source.name $source.zip $source.url $source.sum
        Install-Archive $zipFile
        if (-not (Valid-Tools)) { throw 'Os executaveis extraidos nao passaram na verificacao.' }
        Write-Host '[OK] FFmpeg e FFprobe instalados e testados.' -ForegroundColor Green
        return
    } catch {
        Write-Warning "Origem $($source.name) falhou: $($_.Exception.Message)"
        $failures += "$($source.name): $($_.Exception.Message)"
    }
}
throw "Nao foi possivel instalar FFmpeg por nenhuma fonte. Verifique firewall/conexao. Detalhes: $($failures -join ' | ')"

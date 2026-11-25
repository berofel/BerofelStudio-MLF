# Resolve and optionally install the newest published BerofelStudio Release.
# This script is embedded in the NSIS installer and also supports offline tests
# through -MetadataJsonPath. It never downloads source code or executes API data.
param(
    [Parameter(Mandatory = $true)][string]$CurrentVersion,
    [switch]$IncludePrerelease,
    [switch]$InstallLatest,
    [switch]$CheckOnly,
    [switch]$VerifyChecksumOnly,
    [string]$VerifyPackagePath = '',
    [string]$VerifyChecksumPath = '',
    [string]$MetadataJsonPath = ''
)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$repository = 'berofel/BerofelStudio-MLF'
$apiUrl = "https://api.github.com/repos/$repository/releases?per_page=100"

function Parse-BfsVersion([string]$value) {
    $match = [regex]::Match($value, '^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$')
    if (-not $match.Success) { return $null }
    return [pscustomobject]@{
        Major = [int]$match.Groups[1].Value
        Minor = [int]$match.Groups[2].Value
        Patch = [int]$match.Groups[3].Value
        Pre = $match.Groups[4].Value
    }
}

function Compare-BfsVersion([string]$left, [string]$right) {
    $a = Parse-BfsVersion $left
    $b = Parse-BfsVersion $right
    if (-not $a -or -not $b) { throw "Versao SemVer invalida: '$left' ou '$right'." }
    foreach ($field in @('Major','Minor','Patch')) {
        if ($a.$field -gt $b.$field) { return 1 }
        if ($a.$field -lt $b.$field) { return -1 }
    }
    if (-not $a.Pre -and $b.Pre) { return 1 }
    if ($a.Pre -and -not $b.Pre) { return -1 }
    if (-not $a.Pre -and -not $b.Pre) { return 0 }
    $ap = @($a.Pre.Split('.')); $bp = @($b.Pre.Split('.'))
    for ($i = 0; $i -lt [Math]::Min($ap.Count,$bp.Count); $i++) {
        $an = 0L; $bn = 0L
        $isAn = [long]::TryParse($ap[$i], [ref]$an)
        $isBn = [long]::TryParse($bp[$i], [ref]$bn)
        if ($isAn -and $isBn) {
            if ($an -gt $bn) { return 1 }; if ($an -lt $bn) { return -1 }
        } elseif ($isAn -and -not $isBn) { return -1
        } elseif (-not $isAn -and $isBn) { return 1
        } else {
            $comparison = [string]::Compare($ap[$i],$bp[$i],[StringComparison]::OrdinalIgnoreCase)
            if ($comparison -gt 0) { return 1 }; if ($comparison -lt 0) { return -1 }
        }
    }
    if ($ap.Count -gt $bp.Count) { return 1 }
    if ($ap.Count -lt $bp.Count) { return -1 }
    return 0
}

function Get-ReleaseInstaller($release) {
    if ($release.draft) { return $null }
    $tag = [string]$release.tag_name
    $parsed = Parse-BfsVersion $tag
    if (-not $parsed) { return $null }
    $version = $tag.TrimStart('v')
    $exeName = "BerofelStudio-$version-Setup-x64.exe"
    $sumName = "$exeName.sha256"
    $exe = @($release.assets | Where-Object { $_.name -ceq $exeName } | Select-Object -First 1)
    $sum = @($release.assets | Where-Object { $_.name -ceq $sumName } | Select-Object -First 1)
    if (-not $exe -or -not $sum) { return $null }
    $base = "https://github.com/$repository/releases/download/$tag/"
    if ($exe[0].browser_download_url -cne ($base + $exeName) -or
        $sum[0].browser_download_url -cne ($base + $sumName)) {
        throw "URLs dos artefatos da release '$tag' nao correspondem ao repositorio esperado."
    }
    return [pscustomobject]@{ Tag=$tag; Version=$version; Exe=$exe[0]; Checksum=$sum[0] }
}

function Get-PublishedReleases {
    if ($MetadataJsonPath) {
        return @(Get-Content -LiteralPath $MetadataJsonPath -Raw | ConvertFrom-Json)
    }
    $response = Invoke-RestMethod -Uri $apiUrl -Method Get -TimeoutSec 15 -Headers @{
        Accept = 'application/vnd.github+json'
        'X-GitHub-Api-Version' = '2022-11-28'
        'User-Agent' = 'BerofelStudio-Installer'
    }
    return @($response)
}

function Get-Sha256Hex([string]$path) {
    $sha = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead($path)
    try { return [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','') }
    finally { $stream.Dispose(); $sha.Dispose() }
}

function Test-InstallerPackage([string]$packagePath, [string]$checksumPath,
                               [string]$expectedName, [string]$apiDigest = '') {
    if (-not (Test-Path -LiteralPath $packagePath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $checksumPath -PathType Leaf)) {
        throw 'O instalador ou seu manifesto SHA-256 nao foi encontrado.'
    }
    if ([IO.Path]::GetFileName($packagePath) -cne $expectedName) {
        throw 'O nome local do instalador nao corresponde ao asset publicado.'
    }
    $sumLine = Get-Content -LiteralPath $checksumPath -Raw
    $sumMatch = [regex]::Match($sumLine, '(?im)^\s*([a-f0-9]{64})\s+\*?' + [regex]::Escape($expectedName) + '\s*$')
    if (-not $sumMatch.Success) { throw 'O SHA-256 publicado nao corresponde ao nome do instalador.' }
    $digestMatch = [regex]::Match($apiDigest, '^sha256:([a-f0-9]{64})$')
    if ($digestMatch.Success -and $sumMatch.Groups[1].Value -ine $digestMatch.Groups[1].Value) {
        throw 'O checksum lateral diverge do digest informado pela API do GitHub.'
    }
    $file = Get-Item -LiteralPath $packagePath
    if ($file.Length -lt 1MB -or $file.Length -gt 2GB) {
        throw "Tamanho inesperado para o instalador: $($file.Length) bytes."
    }
    $actualHash = Get-Sha256Hex $packagePath
    if ($actualHash -ine $sumMatch.Groups[1].Value) {
        throw 'SHA-256 divergente; o instalador baixado foi recusado.'
    }
    return $actualHash
}

$downloadDirectory = ''
try {
    if ($VerifyChecksumOnly) {
        if (-not $VerifyPackagePath -or -not $VerifyChecksumPath) {
            throw 'Informe -VerifyPackagePath e -VerifyChecksumPath para verificar um pacote local.'
        }
        $verifyName = [IO.Path]::GetFileName($VerifyPackagePath)
        [void](Test-InstallerPackage $VerifyPackagePath $VerifyChecksumPath $verifyName)
        Write-Output 'STATUS=CHECKSUM_VALID'
        exit 0
    }
    $current = Parse-BfsVersion $CurrentVersion
    if (-not $current) { throw "Versao instalada invalida: '$CurrentVersion'." }
    $eligible = @()
    foreach ($release in (Get-PublishedReleases)) {
        if (-not $IncludePrerelease -and $release.prerelease) { continue }
        $candidate = Get-ReleaseInstaller $release
        if ($candidate) { $eligible += $candidate }
    }
    if (-not $eligible.Count) {
        Write-Output 'STATUS=NO_RELEASE_WITH_INSTALLER'
        exit 0
    }
    $latest = $eligible[0]
    foreach ($candidate in $eligible | Select-Object -Skip 1) {
        if ((Compare-BfsVersion $candidate.Version $latest.Version) -gt 0) { $latest = $candidate }
    }
    $comparison = Compare-BfsVersion $latest.Version $CurrentVersion
    if ($comparison -le 0) {
        Write-Output "STATUS=UP_TO_DATE VERSION=$CurrentVersion"
        exit 0
    }
    Write-Output "STATUS=UPDATE_AVAILABLE VERSION=$($latest.Version)"
    if ($CheckOnly -or -not $InstallLatest) { exit 0 }

    $downloadDirectory = Join-Path ([IO.Path]::GetTempPath()) ('BerofelStudio-update-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $downloadDirectory | Out-Null
    $exePath = Join-Path $downloadDirectory $latest.Exe.name
    $sumPath = Join-Path $downloadDirectory $latest.Checksum.name
    Invoke-WebRequest -Uri $latest.Checksum.browser_download_url -OutFile $sumPath -TimeoutSec 30 -UseBasicParsing
    Invoke-WebRequest -Uri $latest.Exe.browser_download_url -OutFile $exePath -TimeoutSec 120 -UseBasicParsing
    [void](Test-InstallerPackage $exePath $sumPath $latest.Exe.name ([string]$latest.Exe.digest))

    $process = Start-Process -FilePath $exePath -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "O instalador $($latest.Version) terminou com codigo $($process.ExitCode)." }
    Write-Output 'STATUS=LATEST_INSTALLER_COMPLETED'
    exit 10
} catch {
    $message = [string]$_.Exception.Message
    $logPath = Join-Path ([IO.Path]::GetTempPath()) 'BerofelStudio-update-check.log'
    try { Add-Content -LiteralPath $logPath -Encoding UTF8 -Value ("{0:o} {1}" -f [DateTime]::UtcNow,$message) } catch {}
    Write-Output "ERROR=$message"
    Write-Output "LOG=$logPath"
    Write-Output 'STATUS=UPDATE_CHECK_FAILED'
    exit 20
} finally {
    if ($downloadDirectory -and (Test-Path -LiteralPath $downloadDirectory)) {
        $resolved = [IO.Path]::GetFullPath($downloadDirectory)
        $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
        if ($resolved.StartsWith($tempRoot,[StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $resolved -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

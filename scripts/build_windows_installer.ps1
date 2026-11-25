param(
    [string]$CompilerPath = '',
    [string]$OutputDirectory = ''
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $repo 'dist' }

$status = & git -C $repo status --porcelain
if ($LASTEXITCODE -ne 0) { throw 'Não foi possível consultar o estado Git.' }
if ($status) { throw 'O pacote de release exige uma árvore Git limpa; faça commit das alterações validadas primeiro.' }
$commit = (& git -C $repo rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or -not $commit) { throw 'Commit Git não disponível.' }

if (-not $CompilerPath) {
    $command = Get-Command makensis.exe -ErrorAction SilentlyContinue
    if ($command) { $CompilerPath = $command.Source }
    else {
        $candidates = @(
            (Join-Path ${env:ProgramFiles(x86)} 'NSIS\makensis.exe'),
            (Join-Path $env:ProgramFiles 'NSIS\makensis.exe')
        )
        $CompilerPath = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    }
}
if (-not $CompilerPath -or -not (Test-Path -LiteralPath $CompilerPath)) {
    throw 'NSIS makensis.exe não foi encontrado. Instale o compilador oficial NSIS para gerar o instalador Windows.'
}

$versionText = Get-Content -LiteralPath (Join-Path $repo 'berofel\__init__.py') -Raw
$versionMatch = [regex]::Match($versionText, "__version__\s*=\s*'([^']+)'")
if (-not $versionMatch.Success) { throw 'Não foi possível ler berofel.__version__.' }
$version = $versionMatch.Groups[1].Value
$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$buildId = [guid]::NewGuid().ToString('N')
$archive = Join-Path $tempRoot ("BerofelStudio-$buildId.zip")
$stage = Join-Path $tempRoot ("BerofelStudio-stage-$buildId")
$stageFull = [IO.Path]::GetFullPath($stage)
if (-not $stageFull.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'O caminho temporário calculado está fora da pasta temporária.'
}
New-Item -ItemType Directory -Path $stageFull | Out-Null
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

try {
    & git -C $repo archive --format=zip --output=$archive HEAD
    if ($LASTEXITCODE -ne 0) { throw 'Não foi possível criar o snapshot limpo de release.' }
    Expand-Archive -LiteralPath $archive -DestinationPath $stageFull -Force

    # git archive includes only tracked release source. Local model/media/cache
    # files are not in the archive; keep installer inputs untouched.
    $testsDirectory = Join-Path $stageFull 'tests'
    if (Test-Path -LiteralPath $testsDirectory -PathType Container) {
        Remove-Item -LiteralPath $testsDirectory -Recurse -Force
    }

    $script = Join-Path $stageFull 'installer\BerofelStudio.nsi'
    if (-not (Test-Path -LiteralPath $script -PathType Leaf)) {
        throw "O script NSIS não está no staging limpo: $script"
    }
    $compilerArgs = @(
        "/DAPP_SOURCE=`"$stageFull`"",
        "/DOUTPUT_DIR=`"$OutputDirectory`"",
        "/DAPP_VERSION=$version",
        'installer\BerofelStudio.nsi'
    )
    Push-Location -LiteralPath $stageFull
    try {
        & $CompilerPath @compilerArgs
        $compilerExitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($compilerExitCode -ne 0) { throw "NSIS encerrou com código $compilerExitCode." }
    $installer = Join-Path $OutputDirectory "BerofelStudio-$version-Setup-x64.exe"
    if (-not (Test-Path -LiteralPath $installer)) { throw 'O executável do instalador não foi criado.' }
    $hash = Get-FileHash -LiteralPath $installer -Algorithm SHA256
    Set-Content -LiteralPath ($installer + '.sha256') -Encoding ascii -Value ("{0}  {1}" -f $hash.Hash.ToLowerInvariant(), (Split-Path -Leaf $installer))
    Write-Host "Instalador: $installer"
    Write-Host "SHA-256: $($hash.Hash)"
} finally {
    if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
    if (Test-Path -LiteralPath $stageFull) {
        $resolved = [IO.Path]::GetFullPath($stageFull)
        if (-not $resolved.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'A pasta de staging saiu da pasta temporária; limpeza recursiva cancelada.'
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}

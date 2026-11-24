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
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($command) { $CompilerPath = $command.Source }
    else {
        $candidate = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'
        if (Test-Path -LiteralPath $candidate) { $CompilerPath = $candidate }
    }
}
if (-not $CompilerPath -or -not (Test-Path -LiteralPath $CompilerPath)) {
    throw 'Inno Setup 6 não foi encontrado. Instale o compilador oficial para gerar o instalador Windows.'
}

$versionText = Get-Content -LiteralPath (Join-Path $repo 'berofel\__init__.py') -Raw
$versionMatch = [regex]::Match($versionText, "__version__\s*=\s*'([^']+)'")
if (-not $versionMatch.Success) {
    throw 'Não foi possível ler berofel.__version__.'
}
$version = $versionMatch.Groups[1].Value
$archive = Join-Path ([IO.Path]::GetTempPath()) ("BerofelStudio-$commit.zip")
$stage = Join-Path ([IO.Path]::GetTempPath()) ("BerofelStudio-$commit")
if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage | Out-Null
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

try {
    & git -C $repo archive --format=zip --output=$archive HEAD
    if ($LASTEXITCODE -ne 0) { throw 'Não foi possível criar o snapshot limpo de release.' }
    Expand-Archive -LiteralPath $archive -DestinationPath $stage -Force
    $iss = Join-Path $stage 'installer\BerofelStudio.iss'
    & $CompilerPath "/DSourceRoot=`"$stage`"" "/DAppVersion=$version" "/O$OutputDirectory" $iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup encerrou com código $LASTEXITCODE." }
    $installer = Join-Path $OutputDirectory "BerofelStudio-$version-Setup-x64.exe"
    if (-not (Test-Path -LiteralPath $installer)) { throw 'O executável do instalador não foi criado.' }
    $hash = Get-FileHash -LiteralPath $installer -Algorithm SHA256
    Set-Content -LiteralPath ($installer + '.sha256') -Encoding ascii -Value ("{0}  {1}" -f $hash.Hash.ToLowerInvariant(), (Split-Path -Leaf $installer))
    Write-Host "Instalador: $installer"
    Write-Host "SHA-256: $($hash.Hash)"
} finally {
    if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
}

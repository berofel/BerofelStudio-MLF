param(
    [Parameter(Mandatory=$true)]
    [string]$VenvDir
)

$ErrorActionPreference = 'Stop'
$prefix = [IO.Path]::GetFullPath($VenvDir).TrimEnd('\') + '\'
$activeIds = @(
    foreach ($process in (Get-Process -Name python,pythonw -ErrorAction SilentlyContinue)) {
        $imagePath = $null
        try { $imagePath = $process.Path } catch {}
        if (-not $imagePath) {
            try { $imagePath = $process.MainModule.FileName } catch {}
        }
        if (-not $imagePath) { continue }
        try { $imagePath = [IO.Path]::GetFullPath($imagePath) } catch { continue }
        if ($imagePath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
            $process.Id
        }
    }
)

if ($activeIds.Count -gt 0) {
    $ids = ($activeIds | Sort-Object -Unique) -join ', '
    throw "BerofelStudio ou uma tarefa do ambiente Python ainda esta ativa (PID: $ids). Feche o editor e aguarde os workers terminarem antes de instalar/atualizar. Nenhum processo foi encerrado."
}

Write-Host '[OK] Nenhum processo Python do ambiente do BerofelStudio esta ativo.' -ForegroundColor Green

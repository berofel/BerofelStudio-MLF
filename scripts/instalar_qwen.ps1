# Qwen3 1.7B GGUF via Hugging Face + llama.cpp CPU via release oficial GitHub.
# Instalacao OPCIONAL: nenhum limite artificial de RAM/CPU, sem carregar no editor.
$ErrorActionPreference='Stop'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$base=Join-Path $env:LOCALAPPDATA 'BFS'
$tools=Join-Path $base 'tools\llama'
$models=Join-Path $base 'models'
$downloads=Join-Path $base 'downloads'
$stage=Join-Path $base 'stage_llama'
$exe=Join-Path $tools 'llama-cli.exe'
$model=Join-Path $models 'Qwen3-1.7B-Q4_K_M.gguf'
$candidateModel=$model+'.installing'
$expectedModelHash='D2387CA2DBFEE2FFABCE7120D3770DADCA0B293052BC2F0E138FDC940D9BC7B5'

function Download-WithProgress([string]$url, [string]$dest, [long]$min) {
    $partial="$dest.download"
    $resume=0
    if(Test-Path -LiteralPath $partial){
        $resume=(Get-Item -LiteralPath $partial).Length
        Write-Host "Encontrado download parcial: $([math]::Round($resume/1MB,1)) MB. Tentando retomar." -ForegroundColor Cyan
    }
    if((Test-Path -LiteralPath $dest) -and (Get-Item -LiteralPath $dest).Length -ge $min){
        Write-Host "Arquivo de download ja presente: $dest" -ForegroundColor Cyan
        return
    }
    Write-Host "Baixando $url" -ForegroundColor Cyan
    $req=$null;$response=$null;$stream=$null;$out=$null
    try {
        $req=[System.Net.HttpWebRequest]::Create($url)
        $req.Timeout=35000;$req.ReadWriteTimeout=35000;$req.AllowAutoRedirect=$true
        $req.UserAgent='BerofelStudio-AI-0.4'
        if($resume -gt 0){$req.AddRange($resume)}
        $response=$req.GetResponse()
        $stream=$response.GetResponseStream();$stream.ReadTimeout=35000
        # Alguns servidores ignoram o Range. Reinicia em vez de concatenar dois arquivos.
        $partialResponse=([int]$response.StatusCode -eq 206)
        if(-not $partialResponse){$resume=0}
        $mode=if($resume -gt 0){[System.IO.FileMode]::Append}else{[System.IO.FileMode]::Create}
        $out=[System.IO.File]::Open($partial,$mode,[System.IO.FileAccess]::Write)
        $buf=New-Object byte[] 131072
        [long]$got=$resume
        $last=[System.Diagnostics.Stopwatch]::StartNew();$lastReport=0
        [long]$expected=if($response.ContentLength -ge 0){$resume+$response.ContentLength}else{-1}
        while($true){
            $n=$stream.Read($buf,0,$buf.Length)
            if($n -le 0){break}
            $out.Write($buf,0,$n);$got+=$n
            if(($last.Elapsed.TotalSeconds-$lastReport) -ge 4){
                $lastReport=$last.Elapsed.TotalSeconds
                $mb=[math]::Round($got/1MB,1)
                if($expected -gt 0){
                    $pct=[math]::Round($got*100.0/$expected,1)
                    Write-Host "Recebidos: $mb MB de $([math]::Round($expected/1MB,1)) MB ($pct`%)"
                }else{Write-Host "Recebidos: $mb MB"}
            }
        }
        $out.Dispose();$out=$null
        if($got -lt $min){throw "Download menor que o esperado: $got bytes"}
        if($expected -ge 0 -and $got -ne $expected){throw 'Download parcial'}
        Move-Item -LiteralPath $partial -Destination $dest -Force
    }catch{
        if($req){try{$req.Abort()}catch{}}
        Write-Warning 'Download interrompido: o arquivo parcial sera preservado para a proxima tentativa.'
        throw
    }finally{
        if($out){$out.Dispose()};if($stream){$stream.Dispose()};if($response){$response.Dispose()}
    }
}

try {
    & (Join-Path $PSScriptRoot 'verificar_editor_fechado.ps1') -VenvDir (Join-Path $base 'venv')
    New-Item -ItemType Directory -Force -Path $tools,$models,$downloads | Out-Null
    if(-not (Test-Path -LiteralPath $exe)){
        Write-Host '[1/2] Consultando release oficial do llama.cpp...'
        # Desde v1.0.0, a release marcada como 'latest' pode conter somente
        # nightly-tag.txt; procurar releases ANTERIORES que tenham binário.
        # Fallback v0.9.0: versão oficial confirmada com Windows CPU x64.
        $headers=@{'User-Agent'='BerofelStudio'; 'Accept'='application/vnd.github+json'}
        $urls=@(
            'https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=30',
            'https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/v0.9.0'
        )
        $asset=$null
        foreach($endpoint in $urls){
            try {
                $response=Invoke-RestMethod -Uri $endpoint -Headers $headers -TimeoutSec 35
                foreach($release in @($response)){
                    if($release.draft){continue}
                    $candidate=$release.assets | Where-Object {
                        $_.name -match '^llama-.*-bin-win-cpu-x64\.zip$' -and
                        [long]$_.size -ge 1000000
                    } | Select-Object -First 1
                    if($candidate -and $candidate.browser_download_url){
                        $asset=$candidate
                        Write-Host "Release compatível: $($release.tag_name) - $($candidate.name)" -ForegroundColor Cyan
                        break
                    }
                }
                if($asset){break}
            } catch {
                Write-Warning "Falha na consulta $endpoint : $($_.Exception.Message)"
            }
        }
        if(-not $asset){
            throw 'Nao foi possivel localizar um ZIP Windows CPU x64 nas releases oficiais. Verifique internet/GitHub API e tente novamente.'
        }
        $zip=Join-Path $downloads $asset.name
        Download-WithProgress $asset.browser_download_url $zip 1000000
        if($asset.digest -match '^sha256:([a-fA-F0-9]{64})$'){
            if((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash -ne $Matches[1]){throw 'SHA256 do llama.cpp nao confere.'}
        }
        if(Test-Path -LiteralPath $stage){Remove-Item -LiteralPath $stage -Recurse -Force}
        Expand-Archive -LiteralPath $zip -DestinationPath $stage -Force
        $binary=Get-ChildItem -LiteralPath $stage -Filter 'llama-cli.exe' -Recurse -File | Select-Object -First 1
        if(-not $binary){throw 'ZIP sem llama-cli.exe.'}
        # O EXE depende das DLLs adjacentes; copia os arquivos do mesmo diretorio.
        Copy-Item -Path (Join-Path $binary.DirectoryName '*') -Destination $tools -Recurse -Force
        Remove-Item -LiteralPath $stage -Recurse -Force
        if(-not (Test-Path -LiteralPath $exe)){throw 'llama-cli.exe ausente apos extracao.'}
    }else{Write-Host '[1/2] llama-cli ja instalado.'}
    $candidateReady=$false
    if(Test-Path -LiteralPath $candidateModel){
        $candidateReady=(Get-Item -LiteralPath $candidateModel).Length -ge 800MB
        $candidateHash=''
        if($candidateReady){$candidateHash=(Get-FileHash -LiteralPath $candidateModel -Algorithm SHA256).Hash.ToUpperInvariant()}
        if(-not $candidateReady -or $candidateHash -ne $expectedModelHash){
            $preserved=$candidateModel+'.invalid-'+(Get-Date -Format 'yyyyMMdd_HHmmss')
            Move-Item -LiteralPath $candidateModel -Destination $preserved
            $candidateReady=$false
            Write-Warning "Candidato incompleto/invalido preservado em: $preserved"
        }
    }
    if(-not (Test-Path -LiteralPath $model) -or (Get-Item -LiteralPath $model).Length -lt 800MB){
        if(-not $candidateReady){
            Write-Host '[2/2] Buscando modelo Qwen3 1.7B Q4_K_M. Download de aproximadamente 1.3 GB.'
            $repo='ggml-org/Qwen3-1.7B-GGUF'
            $hf=Invoke-RestMethod -Uri ('https://huggingface.co/api/models/'+$repo) -TimeoutSec 35
            $entry=$hf.siblings | Where-Object { $_.rfilename -match 'Qwen3-1\.7B-Q4_K_M\.gguf$' } | Select-Object -First 1
            if(-not $entry){throw 'Modelo Qwen GGUF nao encontrado no repositorio informado.'}
            $url='https://huggingface.co/'+$repo+'/resolve/main/'+$entry.rfilename+'?download=true'
            Download-WithProgress $url $candidateModel 800MB
        }else{Write-Host '[2/2] Reutilizando modelo candidato completo para verificacao.'}
        $candidateHash=(Get-FileHash -LiteralPath $candidateModel -Algorithm SHA256).Hash.ToUpperInvariant()
        if($candidateHash -ne $expectedModelHash){
            $preserved=$candidateModel+'.invalid-'+(Get-Date -Format 'yyyyMMdd_HHmmss')
            Move-Item -LiteralPath $candidateModel -Destination $preserved
            throw "Hash SHA256 do candidato Qwen nao confere. Arquivo preservado em: $preserved"
        }
        $backup=$null
        if(Test-Path -LiteralPath $model){
            $backup=$model+'.partial-backup-'+(Get-Date -Format 'yyyyMMdd_HHmmss')
            Move-Item -LiteralPath $model -Destination $backup
            Write-Host "Modelo parcial anterior preservado em: $backup" -ForegroundColor Yellow
        }
        try{Move-Item -LiteralPath $candidateModel -Destination $model -Force}
        catch{
            if($backup -and -not (Test-Path -LiteralPath $model)){
                Move-Item -LiteralPath $backup -Destination $model -Force
            }
            throw
        }
    }else{Write-Host '[2/2] Qwen3 1.7B ja esta em cache.'}
    $actual=(Get-FileHash -LiteralPath $model -Algorithm SHA256).Hash.ToUpperInvariant()
    if($actual -ne $expectedModelHash){
        throw "Hash SHA256 do modelo Qwen existente nao confere. Arquivo mantido intacto em: $model"
    }
    Write-Host '[OK] Qwen local preparado. Abra o editor e escolha Qwen Contextual.' -ForegroundColor Green
    Write-Host "Executavel: $exe"
    Write-Host "Modelo: $model"
    exit 0
}catch{
    Write-Host "[ERRO] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'Sem Qwen, o editor e a transcricao continuam funcionando.'
    exit 1
}

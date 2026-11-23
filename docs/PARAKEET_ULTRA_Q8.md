# ASR Parakeet Ultra Q8 (opcional)

Faster-Whisper continua sendo o padrão. Parakeet só é selecionado pelo usuário
no campo **Motor de transcrição local** da área de ações avulsas. O modelo
Q8_0 não substitui o Whisper instalado, e os resultados ficam em etapas/cache
separados por motor, modelo, idioma, dispositivo e versão do runtime.

## Instalação

No PowerShell, execute `scripts/install_parakeet_ultra.ps1`. O instalador obtém
o runtime Windows `transcribe.cpp` 0.4.2, a binding Python correspondente e o
modelo Parakeet Ultra Q8_0; valida SHA-256 e instala em `%LOCALAPPDATA%\BFS`.
Não baixa arquivos ao abrir o editor. `-ModelOnly` e `-RuntimeOnly` permitem
reparar uma parte. Um runtime incompleto é preservado com sufixo `stale-*` e
substituído por uma extração validada. Depois da instalação, reinicie o Studio.

O modelo, runtime e binding ficam fora do repositório. O instalador só baixa
arquivos de URLs fixadas e não coleta nem envia gravações. A execução normal é
local/offline. O runtime `transcribe.cpp` é MIT; confirme os avisos incluídos
no pacote nativo ao redistribuí-lo. Os pesos do modelo e o conjunto FLEURS de
teste têm licença CC-BY-4.0; este projeto não redistribui nenhum dos dois.

## Backends

* **CPU**: caminho compatível, seis threads por padrão.
* **Vulkan**: opt-in, usa o dispositivo Vulkan detectado; retorna erro legível
  se o runtime/dispositivo não puder ser inicializado.

Ambos pedem timestamps por palavra. Os tempos inteiros em milissegundos da
binding são convertidos para segundos e limitados à duração do WAV. O contrato
da etapa normaliza-os para a mesma representação usada pelo Faster-Whisper.
Parakeet requer WAV PCM16 mono a 16 kHz; o pipeline já extrai esse formato.

## Benchmark reproduzível

O benchmark abaixo exige referências correspondentes a WAVs `pt_br_*.wav`,
mas nunca baixa exemplos. Ele reporta latência/RTF p50 e p95, WER normalizada,
tempo de carregamento, CPU agregado, pico do working set e medições por arquivo:

```powershell
python scripts/benchmark_parakeet_asr.py `
  --audio-dir C:\dados\fleurs-ptbr `
  --references C:\dados\pt_br.trans.txt `
  --backend vulkan --threads 6 --runs 3 `
  --output C:\dados\parakeet-benchmark.json
```

### Medição desta implementação

Windows x64, AMD Ryzen 7 5700G, 16 GB RAM, GPU integrada Radeon com Vulkan,
modelo Q8_0, runtime 0.4.2, seis threads. Amostra: 20 áudios FLEURS PT-BR,
275,88 segundos no total, 3 inferências por arquivo em Parakeet (modelo
carregado uma vez). Faster-Whisper base/int8 foi medido nos mesmos WAVs, uma
inferência por arquivo. WER é média macro do erro de edição de palavras por
arquivo, normalizando acentos e caixa; é apenas um pequeno conjunto de teste,
não uma garantia de qualidade em gravações de gameplay ou narração espontânea.

| Motor | Carregamento | Latência p50 / p95 | RTF p50 / p95 | WER macro | CPU agregada | Pico working set |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Faster-Whisper base/int8, CPU | 0,303 s | 0,694 / 0,925 s | 0,05194 / 0,06972 | 14,32% | 603,61% | 258,13 MiB |
| Parakeet Ultra Q8_0, CPU | 0,225 s | 0,753 / 1,125 s | 0,05523 / 0,05729 | 4,38% | 593,27% | 1.219,04 MiB |
| Parakeet Ultra Q8_0, Vulkan | 0,652 s | 0,422 / 0,641 s | 0,03217 / 0,03903 | 4,38% | 118,44% | 917,56 MiB |

Neste conjunto, Vulkan reduziu latência mediana em cerca de 39% frente ao
Faster-Whisper medido e obteve menor WER no texto de referência. É uma amostra
pequena, sem avaliação humana e sem arquivos do usuário. O backend é opcional;
Faster-Whisper continua padrão e deve ser preferido se Vulkan não iniciar ou se
a voz/contexto real produzir resultados piores.

## Validação

Além dos testes unitários do adaptador e cache, a integração foi executada com
três WAVs reais FLEURS através de `StageRunner` (uma sessão/modelo por lote),
incluindo palavras com timestamps. O pipeline completo de áudio usou FFmpeg,
Parakeet e gerou relatório com 36 palavras no arquivo principal; os tempos
ficaram entre 0,32 e 17,44 s para uma fonte de 17,76 s. Repetir a análise
produziu dois hits de cache e zero misses. Também foi reproduzido o fluxo de
geração direta do worker nos dispositivos CPU e Vulkan.

Os testes de regressão cobrem cache isolado, opção opt-in, conversão/clamping
de timestamps e proteção RMS de áudio audível durante pausas. A reprodução
física em alto-falantes e o fluxo completo de exportação MP4 com mídia do
usuário não foram validados nesta execução. Não se deve marcar esses itens como
validados com base no benchmark ASR.

Os exemplos FLEURS usados na medição foram baixados para uma pasta temporária,
sob CC-BY-4.0, e não foram incluídos no Git. Registros JSON podem ser recriados
com `scripts/benchmark_parakeet_asr.py`.

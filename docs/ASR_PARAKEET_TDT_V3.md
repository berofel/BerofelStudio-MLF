# Transcrição local: Parakeet TDT v3 ONNX INT8/CPU

O único ASR do editor é o nemo-parakeet-tdt-0.6b-v3, carregado em INT8
com CPUExecutionProvider. Não há seleção, fallback ou importação ativa de
Faster-Whisper. Os arquivos ONNX e o Silero VAD ficam fora do repositório em
%LOCALAPPDATA%\BFS\models\.

## Preparar uma vez

Feche o editor e execute INSTALAR_IA_OPCIONAL.bat. O instalador instala
onnx-asr[cpu,hub]==0.12.0 e ONNX Runtime, baixa o TDT v3 INT8 e o Silero ONNX,
carrega ambos para validar o conjunto e grava berofel-install.json. A
instalação requer internet; depois dela, a aplicação usa caminhos locais e
transcreve offline. O modelo é publicado sob CC-BY-4.0; o runtime onnx-asr é
MIT. Verifique os avisos de atribuição antes de redistribuir os pesos.

## Como o pipeline economiza processamento

1. FFmpeg normaliza uma única cópia temporária do áudio para mono PCM16/16 kHz.
2. Uma instância do Silero ONNX calcula as regiões de fala uma vez e as limita
   a janelas de até 20 s. O TDT só recebe essas regiões, com seus offsets
   remapeados ao tempo do arquivo original.
3. Uma instância TDT atende todos os trechos pendentes de uma operação; ela não
   é recarregada por trecho. O modelo é liberado ao fim do worker para não ficar
   ocupando RAM quando o editor não está transcrevendo.
4. O cache depende da mídia, intervalo, arquivos do modelo/VAD, versão do
   pipeline e número de threads. Transcrição válida do projeto pode evitar a
   inferência. O padrão local de ASR é quatro threads, sem lançar análises em
   paralelo; os seis threads usados pelos estágios Qwen permanecem intactos.
5. INT8 é a única quantização usada. O aplicativo não troca silenciosamente
   para Whisper, GGUF, Vulkan ou outro modelo.

## Diagnóstico e benchmark

scripts\verificar.py --ai --strict verifica dependências e os arquivos locais.
Para repetir a medição, coloque amostras de fala autorizadas em WAV PCM16 mono
16 kHz e execute:

    python scripts\benchmark_parakeet_tdt.py C:\caminho\das\amostras --repeats 3

O teste sequencial compara 2, 4, 6 e 8 threads e registra carga do modelo,
mediana de inferência, RTF, RSS e número de palavras. O JSON é salvo na pasta
das amostras.

### Medição local nesta máquina

Em AMD Ryzen 7 5700G, Windows, ONNX Runtime 1.31.1, onnx-asr 0.12.0, foi
medido um conjunto local autorizado de nove amostras de dublagem (3,95–18,21 s;
93,878 s de áudio somados), normalizadas para PCM16 mono/16 kHz. Duas inferências
por arquivo, modelo recarregado entre configurações. Os resultados são deste
conjunto e desta máquina; não são uma medida de WER nem uma validação linguística
cega.

| Threads | Carga fria | RTF mediano entre arquivos | Latência p50/p95 por inferência | RSS após inferência |
|---:|---:|---:|---:|---:|
| 2 | 4,561 s | 0,0572 | 0,452 / 1,042 s | 867,1 MiB |
| 4 | 4,342 s | 0,0442 | 0,385 / 0,732 s | 869,8 MiB |
| 6 | 4,384 s | 0,0519 | 0,478 / 0,942 s | 877,3 MiB |
| 8 | 4,390 s | 0,0500 | 0,447 / 0,843 s | 879,1 MiB |

Quatro threads foi a configuração mais rápida nesta medição: 14,8% menor RTF
mediano e 16,2% menor soma de latências que seis threads. A diferença é
observacional em duas repetições e pode variar com carga do sistema. Por isso,
o ASR adota quatro threads, mas o usuário pode repetir o script no PC de destino.
Uma conferência real de transcrição em uma amostra curta reconheceu a frase
“Cadê o Zé Gotinha? Cadê o nosso querido Zé Gotinha?” com timestamps por palavra;
os outros áudios entraram no benchmark de velocidade, sem transcrição de
referência anotada para calcular WER/CER.

A amostra de 6,06 s usada no teste isolado levou 0,271 s em quatro threads
(RTF 0,0448), com carga em 4,552 s e RSS de 768,1 MiB após a inferência. O RSS
de 869,8 MiB no conjunto maior é o valor posterior à execução, não um pico de
memória amostrado continuamente. A instalação dos pesos ocupa cerca de 670 MB
em disco. O editor mantém o modelo somente no worker da transcrição e o encerra
ao terminar para devolver memória às demais funções.

## Referências técnicas

O README do onnx-asr documenta TDT v3 multilíngue, INT8, timestamps e carregar
modelos a partir de um diretório local. A documentação recomenda VAD para
áudios extensos porque modelos de ASR geralmente operam em trechos de
aproximadamente 20–30 s. O editor aplica seu Silero separado e passa as regiões
ao TDT, evitando uma segunda segmentação interna.

- https://github.com/istupakov/onnx-asr/blob/main/docs/usage.md
- https://github.com/istupakov/onnx-asr/blob/main/docs/troubleshooting.md
- https://huggingface.co/istupakov/parakeet-tdt-0.6b-v3-onnx

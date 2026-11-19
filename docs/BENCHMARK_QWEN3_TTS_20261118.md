# Benchmark do Qwen3-TTS Base — Windows — 18/11/2026

## Ambiente e método

Foi usado `Qwen/Qwen3-TTS-12Hz-0.6B-Base`, `qwen-tts==0.1.1`, PyTorch CPU, Windows x64, Ryzen 7 5700G e 16 GB de RAM. O teste desativou consultas à rede e usou a gravação autorizada já configurada no editor. Caminho, transcrição e áudio do usuário não foram registrados. Os caches de WAV e prompt foram isolados em uma pasta temporária.

## Resultados observados

| Texto | Duração do WAV | Tempo de parede | RTF (tempo / áudio) | Modelo | Prompt de voz |
|---|---:|---:|---:|---|---|
| Curto, português | 10,32 s | 66,776 s | 6,47 | 1 carregamento na sessão | primeira preparação, miss |
| Longo, português | 51,68 s | 297,598 s | 5,76 | mesmo processo, sem recarga | reutilizado, hit |
| Curto, português, 4 threads | 10,32 s | 62,530 s | 6,06 | 1 carregamento na sessão | primeira preparação, miss |

O pico agregado de RSS amostrado do processo de teste e seus filhos foi 6,41 GiB. Ambos os WAVs tinham sinal e foram gerados com cache de áudio frio. O PID do worker permaneceu igual nos dois pedidos e `model_load_count` permaneceu em 1. A latência medida é maior que a duração do áudio: esta configuração não é tempo real.

## Comparações solicitadas e estado da evidência

| Variante | Evidência neste PC | Decisão |
|---|---|---|
| Python Qwen CPU float32 | Benchmark acima e fluxo Qt real Qwen → player → timeline → WAV/MP4 | Mantida como padrão. |
| Recarregar modelo por pedido | Testes anteriores em processo isolado comprovaram síntese, mas não houve A/B controlado no mesmo texto/condições. | Evitado no app; um worker persistente carrega uma vez por sessão. |
| Recalcular/reutilizar prompt | Primeira chamada miss e a seguinte hit, mesmo PID e um carregamento do modelo. Não foi comparada a igualdade da saída nem a latência isolada da mesma frase. | Prompt versionado em NPZ sem pickle e invalidado por chave/fingerprint. |
| Threads | Mesmo texto curto e mesmo PC: 8 threads 66,776 s/RTF 6,47 e 4 threads 62,530 s/RTF 6,06; RSS amostrado 6,41 vs 5,73 GiB. Uma execução por configuração, sem ordem aleatória ou repetição estatística. | Padrão conservador alterado para 4 threads; comparação 1/2/8/12 e repetição controlada ainda pendentes. |
| INT8 | A/B controlado de uma frase curta realizado em 19/11/2026; a conversão dinâmica melhorou o tempo de inferência, mas reduziu o indicador cosine do encoder de speaker. | Permanece experimental; float32 continua padrão pela prioridade de fidelidade. |
| INT4 | Sem backend Qwen Base compatível validado; não foi baixado nem convertido. | Não habilitar. |
| Streaming de áudio | A API Python instalada não possui `generate_voice_clone_streaming`; geração entrega resultado após `generate_voice_clone`. | Nenhum preview incremental comprovado neste backend. |
| Backend nativo | Não compilado nem validado no Windows deste projeto. | Não substituir antes de validar API, qualidade, licença, distribuição e prompt de clonagem. |

O principal ganho comprovado é estrutural: não recarregar o modelo por pedido e reutilizar o prompt da voz. O worker mantém a memória ocupada durante a sessão e libera-a ao fechar o editor. A comparação de threads, precisão e backends permanece pendente; números publicados para hardware diferente não foram tratados como resultado deste computador.

## Revalidação após a configuração 4 intra-op / 1 inter-op — 19/11/2026

O benchmark foi repetido neste Ryzen 7 5700G, com o mesmo modelo CPU e cache
temporário vazio, em modo offline. Esta rodada capturou saída mais curta e é
complementar aos resultados anteriores, não uma comparação controlada entre
versões: texto/duração diferem e cada configuração tem uma única amostra.

| Texto | Duração WAV | Tempo parede | RTF | Condicionamento | Worker |
|---|---:|---:|---:|---|---|
| Curto, português | 5,04 s | 36,10 s | 7,16 | Miss; referência preparada nesta sessão | PID 15512 |
| Longo, português | 48,48 s | 259,93 s | 5,36 | Hit; reutilizado no mesmo worker | Mesmo PID |

O pico agregado amostrado foi 6,48 GiB. Houve 1 carregamento do modelo, ambos
os WAVs tinham sinal e não houve hit do cache de áudio. O caso curto inclui a
latência de carregar o modelo/preparar a voz; portanto, o RTF do caso longo é
mais representativo de uma sessão aquecida. Essa medição não prova o tempo de
inicialização de uma máquina diferente.

## Fontes oficiais e limites das otimizações

- A documentação da API oficial descreve `create_voice_clone_prompt` seguido
  de `generate_voice_clone` e recomenda guardar/reutilizar o prompt de voz.
- A mesma API descreve `non_streaming_mode=False` como simulação de entrada de
  texto em streaming; não disponibiliza fluxo de áudio incremental no método
  `generate_voice_clone` usado pelo editor. O áudio chega após a geração do
  trecho.
- O Base oficial disponível é BF16; o carregador deste app converte para
  `torch.float32` em CPU. A distribuição oficial `qwen-tts` não ativa INT8/INT4
  neste caminho. A investigação dinâmica INT8 feita depois, fora do worker do
  editor, está documentada abaixo; ela não foi habilitada.
- A API `torch.ao.quantization.quantize_dynamic` documenta `qint8` e `float16`
  como tipos dinâmicos simples. O ensaio local confirmou que `quint4x2` é
  rejeitado pelo Qwen/PyTorch instalado. [Documentação oficial PyTorch](https://docs.pytorch.org/docs/stable/generated/torch.ao.quantization.quantize_dynamic.html).
- Backend alternativo investigado: [Qwen3-TTS ONNX Runtime](https://github.com/zhangluoyang/qwen3-tts-onnxruntime), que declara Apache-2.0 e oferece código Python/C++ e streaming. O exportador aceita caminho de modelo e CPU/FP32; fiz uma prova isolada com o Qwen Base 0.6B neste Windows. Com Torch 2.5.1 CPU, NumPy 2.4.6 e ONNX 1.21, `tokenizer12hz_encode`, `tokenizer12hz_decode_chunk`, `text_project` e `codec_embed` foram exportados/verificados; sinais sintéticos passaram no encode e em três comprimentos de decode. A exportação do `talker_core` falhou no wrapper com incompatibilidade de dimensão (`mat1 2×1024` vs `mat2 2048×1024`), antes de validar geração/clonagem. Por isso ONNX não é backend funcional para o app e não foi integrado. Os artefatos e o ambiente da prova ficaram em `%TEMP%`, sem alterar pesos, cache, venv ou projeto do usuário.
- O [port Rust/ONNX/llama.cpp anunciado na discussão oficial Qwen](https://github.com/QwenLM/Qwen3-TTS/discussions/187) declara suporte a CPU/Q4 e clonagem; os números publicados pelo autor são para i9-13980HX e RTX 2080 Ti, não para o hardware alvo, e não foram reproduzidos aqui. O fork de streaming [dffdeeq/Qwen3-TTS-streaming](https://github.com/dffdeeq/Qwen3-TTS-streaming) requer um ambiente CUDA/FlashAttention nas instruções para Windows e anuncia resultados em RTX 5090; não serve como substituto comprovado para CPU.
- O venv Qwen local tem `onnxruntime 1.32.0` com `CPUExecutionProvider`, mas não contém artefatos exportados do Qwen. A simples presença do runtime não valida o pipeline Base/voice prompt. A variante mais rápida com qualidade aceitável continua **não determinada**; o app mantém o backend oficial testado em float32.

Fontes consultadas: [repositório oficial Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS),
[API oficial de inferência](https://github.com/QwenLM/Qwen3-TTS/blob/main/qwen_tts/inference/qwen3_tts_model.py),
[model card Base 0.6B](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base).

## Comparação controlada de lifecycle — 19/11/2026

`scripts/benchmark_qwen3_warm_cpu.py --threads 4 --compare-lifecycle` repetiu
a **mesma frase de 10,32 s** com a mesma referência, WAV cache distinto por caso
e cache de voz compartilhado. Os testes foram em ordem fixa e uma vez cada;
portanto, mostram o custo desta sessão, não uma faixa estatística.

| Cenário | Tempo parede | RTF | Cache do perfil | Processo/modelo |
|---|---:|---:|---|---|
| Worker frio + condicionamento novo | 62,97 s | 6,10 | miss | PID 5664, 1 carga |
| Mesmo worker + perfil em memória | 53,99 s | 5,23 | hit | Mesmo PID 5664, sem recarga |
| Worker/modelo recarregado + perfil em disco | 62,46 s | 6,05 | hit | PID 19308, 1 carga nessa sessão |

Pico agregado amostrado: 5,73 GiB. Todos os WAVs tinham sinal e nenhum usou
cache de áudio. O ensaio mostra que o perfil em memória reduz cerca de 9 s
frente a carregar o modelo novamente nessa execução; a leitura do prompt do
disco preserva o condicionamento entre sessões, mas não evita o custo de
carregar o próprio modelo após fechar o editor. O worker permanece quente
somente durante a sessão atual.

Reprodução: execute o comando indicado com o modelo instalado e uma referência
autorizada já configurada no painel. O script opera offline, mantém o texto e o
caminho da gravação fora da saída, usa pastas temporárias e encerra todos os
workers no final.

## Fontes técnicas

- [Repositório oficial Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS)
- [Implementação oficial da API de inferência](https://github.com/QwenLM/Qwen3-TTS/blob/main/qwen_tts/inference/qwen3_tts_model.py)
- [Modelo Base 0.6B no Hugging Face](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base)
- [Implementação comunitária Rust cgisky1980/Qwen3-TTS-Rust](https://github.com/cgisky1980/Qwen3-TTS-Rust) — não validada nem usada pelo app.
- [Projeto comunitário yet-another-ai/qts](https://github.com/yet-another-ai/qts) — não validado nem usado pelo app.

## Reproduzir

Execute `scripts/benchmark_qwen3_warm_cpu.py` no venv da distribuição após salvar e autorizar um perfil Qwen na aba Narração. O script imprime somente medições/cache, usa caches de saída temporários e para o worker ao final.

O benchmark atualizado registra latência até o WAV, custo de carregamento por
pedido (zero quando o worker já está aquecido), tempo de prompt/preparação,
tempo interno de inferência, RTF, RMS, RSS agregado e CPU normalizada pelos
processadores lógicos. Por padrão usa textos curto, médio e longo. A opção
`--prepare-profile-first` mede primeiro a preparação explícita do perfil em
cache temporário vazio e depois testa as três durações com o modelo e a voz
preparados. Esses campos instrumentam execuções futuras; não são resultados
medidos até a próxima rodada real com referência autorizada.

### Benchmark de desempenho seguro — referência sintética — 19/11/2026

Executado no Ryzen 7 5700G, 16 GB, Windows, Qwen3-TTS Base 0.6B CPU, 4
threads, offline. O sinal de referência foi sintético e usou x-vector-only;
os números medem infraestrutura/latência, não fidelidade, qualidade ou
semelhança com uma pessoa.

| Etapa/caso | Áudio | Latência | RTF | Carregamento do modelo nesta solicitação | Preparação/reuso do prompt |
|---|---:|---:|---:|---:|---:|
| Preparar perfil explícito, worker frio | — | 8,425 s total | — | 7,435 s | 0,576 s; miss |
| Curta, worker e perfil aquecidos | 6,32 s | 30,808 s | 4,875 | 0 s | 0,0006 s; hit |
| Média, worker e perfil aquecidos | 30,00 s | 150,100 s | 5,003 | 0 s | 0,0006 s; hit |
| Longa, worker e perfil aquecidos | 43,36 s | 221,437 s | 5,107 | 0 s | 0,0006 s; hit |

Cada WAV tinha amostras finitas e RMS positivo; nenhum foi servido do cache de
áudio. O mesmo PID carregou o modelo uma vez. Pico RSS agregado amostrado de
6,16 GiB; CPU média/pico de 24,7%/26,5%, normalizada pelos processadores
lógicos. A rodada curta anterior com o mesmo prompt de teste variou para 4,16 s
de áudio e 20,48 s de geração, ilustrando a variabilidade de duração da saída.
Essas medições não afirmam que a narração de uma voz humana terá exatamente o
mesmo RTF; é necessária a rodada equivalente com perfil próprio/autorizado.

Os smoke tests de aplicação aceitam `--synthetic-reference` para validar a
inferência real, Qt, timeline, player, DSP e exportação sem usar amostras de
pessoas. Esses testes explicitamente não comprovam clonagem ou identidade:

```powershell
python scripts/validar_fluxo_qwen3_editor.py --synthetic-reference
python scripts/validar_ajuste_fino_tts_local.py --synthetic-reference
```

## Investigação isolada de INT8 — 19/11/2026

Foi testada a quantização dinâmica INT8 do PyTorch 2.15.0+cpu, em processos
temporários e sem alterar worker ou modelo armazenado. `inplace=False` falhou
porque o `deepcopy` interno não serializa um `dict_keys` do objeto Qwen. Com
`inplace=True`, 249 camadas lineares foram quantizadas e o caminho de clonagem
gerou áudio finito e com sinal. Uma comparação controlada usou o mesmo texto
curto em português, referência autorizada, prompt preparado, semente 42 e o
mesmo speaker encoder FP32 para pontuar as saídas:

| Variante | Duração WAV | Inferência | RTF | Cosine speaker ↔ referência | Pico RSS do processo |
|---|---:|---:|---:|---:|---:|
| Float32 | 10,16 s | 53,591 s | 5,275 | 0,977502 | 5,488 GiB |
| Dynamic INT8 | 10,16 s | 47,916 s | 4,716 | 0,944985 | 5,892 GiB |

A comparação reproduzível levou 6,111 s para carregar o modelo, 0,657 s para
preparar o prompt e 15,791 s para converter INT8. O ganho de 10,6% é do tempo
de inferência com o modelo já convertido, não do caminho frio de primeira
geração; o pico de RSS amostrado foi 7,4% maior em INT8. O score cosine caiu
0,032517. Esse score é um indicador automatizado de semelhança do
speaker, não uma avaliação perceptiva/MOS. Foram feitas duas execuções pareadas
curtas, sem repetição estatística; o resultado sugere um trade-off mensurável,
mas não prova uma degradação audível nem equivalência de qualidade. Não foram
medidos textos longos. Uma investigação exploratória anterior leu RSS apenas
ao final de cada geração e indicou menos memória para INT8; esse valor não era
pico. A tabela acima substitui essa leitura pela amostragem contínua do script.

INT4 foi investigado no modelo Qwen carregado: a API dinâmica instalada rejeitou
`torch.quint4x2` com `AssertionError` antes de substituir camadas (“only
supported dtypes ... qint8 and float16”). Portanto não existe variante INT4
gerável por essa API neste ambiente. Não instalei `torchao` nem converti o modelo
para formato de terceiros; não há uma implementação INT4 local validada para
clonagem Base.

O PyTorch emitiu avisos de depreciação para a API dinâmica usada. Por prioridade
de fidelidade e por não haver validação perceptiva/texto longo, INT8 permanece
experimental e não foi ligado à distribuição. A versão do editor segue em
float32. INT4, backend nativo e streaming incremental continuam sem
implementação/teste apropriado para o prompt de clonagem. Nenhuma quantização
persistente foi feita nem qualquer perfil/cache do usuário foi alterado.

Para repetir a comparação pareada, execute no venv isolado do Qwen, com uma
referência autorizada e transcrição configuradas no painel Narração:

```powershell
& "$env:LOCALAPPDATA\BFS\qwen3_tts\venv\Scripts\python.exe" `
  scripts/benchmark_qwen3_precision.py --confirm-own-or-authorized-voice --threads 4
```

O script opera offline, usa o mesmo prompt e semente nos dois caminhos, amostra
RSS durante cada inferência, mantém os WAVs apenas em memória e imprime métricas
sem revelar referência ou texto. Na execução reproduzida em 19/11/2026, ambos
os WAVs tinham 10,16 s e sinal finito/não silencioso; score e duração coincidiram
com a comparação pareada anterior, enquanto os tempos variaram conforme
esperado em uma máquina de uso geral.
O cosine é uma proxy automatizada de semelhança de speaker, não uma pontuação
perceptiva de qualidade.

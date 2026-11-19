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
| INT8 / INT4 | A/B de tempo, RAM e qualidade não executado; a distribuição Python não ativa essas quantizações. | Não ativar sem validar clonagem e qualidade. INT4 exige outro backend ou conversão. |
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
  neste caminho. Conversão/quantização de comunidade não foi testada com
  `voice_clone_prompt` e não foi habilitada.
- Não foi compilado backend nativo Windows compatível com o prompt Base. Logo,
  a versão mais rápida/precisa entre backends, INT8 e INT4 ainda é **não
  medida**; a decisão atual é usar o backend oficial testado com precisão
  completa.

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

Execute `scripts/benchmark_qwen3_warm_cpu.py` no venv da distribuição após configurar uma referência e transcrição no painel Narração. O script imprime somente medições/cache, usa caches de saída temporários e para o worker ao final.

## Investigação isolada de INT8 — 19/11/2026

Foi testada a quantização dinâmica INT8 do PyTorch 2.15.0+cpu, num processo
temporário e sem alterar o worker ou o modelo armazenado. A primeira tentativa
`inplace=False` falhou porque o `deepcopy` interno do PyTorch não consegue
serializar um `dict_keys` presente no objeto Qwen. Com `inplace=True`, a
conversão levou 15,86 s, quantizou 249 camadas lineares e o caminho real
`create_voice_clone_prompt` → `generate_voice_clone` produziu áudio finito e
com sinal: 10,16 s a 24 kHz em 48,09 s de inferência (RTF 4,73). A preparação
da referência levou 1,06 s; o carregamento observado em uma inicialização
separada do mesmo ensaio levou 6,05 s. O teste usou a referência local já
autorizada, manteve texto e caminho privados e operou offline.

Esse resultado prova compatibilidade funcional pontual da clonagem com INT8,
mas **não** prova qualidade vocal equivalente: ainda falta comparação A/B
perceptiva e de sinal com a precisão original, repetição de medições, RSS sob
quantização e texto longo. A conversão também impõe custo inicial significativo
e usa uma API PyTorch marcada como depreciada. Portanto, INT8 permanece somente
uma variante experimental de diagnóstico; a distribuição continua em float32,
única precisão validada integralmente no fluxo do editor. INT4, backend nativo
e streaming de áudio incremental continuam sem implementação/teste apropriados
para o prompt de clonagem. Não foi feita quantização persistente nem foi alterado
qualquer perfil/cache do usuário.

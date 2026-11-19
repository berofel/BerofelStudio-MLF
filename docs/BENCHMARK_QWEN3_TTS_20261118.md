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

## Fontes técnicas

- [Repositório oficial Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS)
- [Implementação oficial da API de inferência](https://github.com/QwenLM/Qwen3-TTS/blob/main/qwen_tts/inference/qwen3_tts_model.py)
- [Modelo Base 0.6B no Hugging Face](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base)
- [Implementação comunitária Rust cgisky1980/Qwen3-TTS-Rust](https://github.com/cgisky1980/Qwen3-TTS-Rust) — não validada nem usada pelo app.
- [Projeto comunitário yet-another-ai/qts](https://github.com/yet-another-ai/qts) — não validado nem usado pelo app.

## Reproduzir

Execute `scripts/benchmark_qwen3_warm_cpu.py` no venv da distribuição após configurar uma referência e transcrição no painel Narração. O script imprime somente medições/cache, usa caches de saída temporários e para o worker ao final.

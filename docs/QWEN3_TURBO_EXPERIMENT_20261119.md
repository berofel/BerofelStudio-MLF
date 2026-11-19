# Operação Qwen Turbo — experimento local (19/11/2026)

## Escopo e segurança

Branch isolada: `experiment/qwen3-turbo`. O backend Qwen oficial Python/float32 continua padrão e recuperável. A referência imutável `backup/qwen3-0.6b-stable` aponta para `4e4b820265ae1f38bf3d0ab7ee2b6f87febd1463`.

Backup externo verificado: `C:\Users\Berofel\Desktop\BerofelStudio_QwenTurbo_Backup_20261119-095515`. Inclui bundle Git da referência, manifestos e cópia local de configuração/perfis; os arquivos privados/modelos permanecem fora do Git. Restauração de código em outra pasta: `git clone "C:\Users\Berofel\Desktop\BerofelStudio_QwenTurbo_Backup_20261119-095515\BerofelStudio-stable.bundle" <pasta-destino>` e então `git switch backup/qwen3-0.6b-stable`. O bundle contém `feat/qwen3-base-optimized` no commit `4e4b820265ae1f38bf3d0ab7ee2b6f87febd1463` e a tag de backup. A pasta externa completa deve ser preservada para recuperar também dados locais; os hashes SHA-256 dos artefatos foram conferidos contra `backup_manifest.json`.

O runtime experimental fica em `%LOCALAPPDATA%\BFS\qwen3_tts\native_turbo`. Para instalá-lo de um build local, execute `scripts\install_qwen3_turbo_runtime.ps1` com os caminhos do build, modelo Q4 e tokenizer. O script valida arquivos e hashes, recusa substituir arquivos diferentes sem `-Replace` e cria cópia `.backup-*` antes da substituição.

## Implementação

O editor tem uma rota opcional `qwen3-tts-native-q4` para narração rápida. O modo original permanece selecionado inicialmente; Turbo aparece somente quando o runtime e os pesos locais existem. A interface avisa que a rota é experimental e permite retornar ao motor oficial.

A rota Turbo usa exclusivamente Qwen3-TTS 12Hz 0.6B Base, convertido para GGUF Q4_0 misto, com speaker encoder preservado em F16. A primeira utilização de uma gravação autorizada normaliza a referência e cria um x-vector com o próprio encoder nativo; esse vetor versionado é guardado localmente e reutilizado. O prompt nativo não é intercambiável com o embedding calculado pelo worker PyTorch em todas as precisões: o teste misto encontrou regressão de inteligibilidade com esse embedding, por isso o adaptador usa o encoder compatível do runtime experimental.

O servidor nativo persiste durante a sessão e carrega o modelo uma vez. Para o modo Turbo, o build experimental recebe PCM float32 por callback nativo, o grava em arquivo temporário incremental e o worker encaminha chunks à thread Qt; `QAudioSink` converte para PCM16 mono 24 kHz e toca enquanto a síntese continua. O WAV final completo continua sendo validado e salvo normalmente. O modo Original não abre nem toca o stream Turbo. O callback usa 6 frames (~0,5 s por chunk); chamadas sem callback mantêm o caminho sem streaming. Cache de frase idêntica existe, mas não é contado como ganho para texto novo.

A conversão Q4 é experimental: `scripts/prepare_qwen3_tts_cpp_q4_mixed.py` cria conversor separado e nunca modifica o conversor upstream. Tensor shapes incompatíveis voltam para F16. `scripts/enable_qwen3_tts_cpp_stream_file.py` habilita o arquivo PCM incremental no servidor e mantém um backup do `main.cpp` do checkout nativo. Para reconstruir o servidor experimental, aplique esse script ao checkout separado e execute `cmake --build <diretório-build> --target qwen3-tts-cli`; depois instale o executável pelo instalador verificado. A distribuição oficial do conversor investigado documenta F16/F32/Q8_0 e não declara suporte upstream a K-quants; Q4 e o stream-file são alterações locais e devem ser tratados como tal. O código nativo investigado é MIT; preservar notices do upstream e das bibliotecas de runtime. Nenhum modelo/runtime foi incluído no Git.

Reverificação do backend C++ escolhido: o README do fork [CHE3MZ/qwen3-tts.cpp](https://github.com/CHE3MZ/qwen3-tts.cpp) lista um build Windows (`tools/build-scripts/build.bat`) e builds AVX2/AVX512 com Clang-cl; a lista de formatos do conversor upstream é F16/F32/Q8_0, não K-quants. Por isso a integração Q4 existente depende de patches/conversor experimental local. O projeto de origem [predict-woo/qwen3-tts.cpp](https://github.com/predict-woo/qwen3-tts.cpp) documenta um quickstart macOS e F16/Q8_0, sem instruções Windows visíveis no README consultado. O projeto separado [gabriele-mastrapasqua/qwen3-tts](https://github.com/gabriele-mastrapasqua/qwen3-tts) é C puro e documenta Windows beta via WSL2. Neste computador não há CMake, Ninja, MSBuild/Visual Studio nem compilador C++ no PATH ou nos diretórios VS padrão consultados; portanto não pude reconstruir o fork upstream ou verificar uma variante Q8/INT8 nova nesta rodada. O binário CHE3MZ Q4 já instalado continua sendo o único backend nativo realmente medido aqui.

## Resultados medidos

Máquina: Windows x64, Ryzen 7 5700G, 16 GB RAM; modelo e referências já em disco; execução CPU offline; 4 threads; mesmas frases de teste em português, mas geração estocástica produz durações diferentes. RTF = tempo de geração / duração de áudio. RSS é pico amostrado do processo/árvore e pode variar conforme método de coleta.

| Backend/configuração | Repetições | Mediana do tempo | Duração mediana | RTF mediano | Pico RSS mediano | WER ASR mediana |
|---|---:|---:|---:|---:|---:|---:|
| Oficial Python F32, referência | 1 | 54,333 s | 10,48 s | 5,184 | 5,674 GiB | 0,9* |
| Nativo Q8_0, perfil x-vector preparado | 3 | 6,099 s | 5,04 s | 1,210 | 2,209 GiB | 0,1 |
| Nativo Q4_0 misto, x-vector preparado | 3 | 4,995 s | 4,88 s | 1,047 | 1,947 GiB | 0,2 |
| Nativo Q4_0, integração do serviço | 1 | 4,634 s | 4,56 s | 1,016 | 2,085 GiB | n/a |
| Nativo Q4_0, callback incremental | 2 | 8,313 s* | 7,20 s* | 1,155* | n/a | n/a |


a) WER é apenas comparação ASR local por Faster-Whisper base/Português/beam 1, não métrica perceptiva. Amostras curtas e estocásticas; não comprova naturalidade nem semelhança biométrica. O áudio oficial de referência teve WER elevado nesta execução, por isso não trate a tabela como superioridade acústica conclusiva. É necessária avaliação auditiva comparativa.

* Mediana das duas medições com callback incremental.

Q4 foi ~13,5% mais rápido em RTF e usou ~12% menos RSS que Q8 nas medianas observadas; em relação ao oficial medido, RTF caiu cerca de 79,8%. A duração de saída variou entre gerações, então RTF é mais informativo que comparar tempo bruto. Modelo nativo frio carregou em ~0,78–0,99 s; reutilização de x-vector custa 0 s no cache. Preparação de novo perfil ficou em ~6,6–7,0 s, separada da síntese.

### Sweep repetido de threads e perfis no editor

Em 19/11/2026 foi executado um sweep Q4 controlado no Ryzen 7 5700G/16 GB: mesmo texto português, mesmo x-vector autorizado, mesmo modelo em servidor persistente, três gerações inéditas por configuração (sem cache de frase). WAVs e `results.json` estão fora do repositório em `C:\Users\Berofel\Desktop\BerofelStudio_QwenTurbo_Benchmark_20261119\thread_sweep_q4_20261119`. Tempos são mediana (intervalo observado), RSS é pico amostrado:

| Q4 threads | Carga do processo | Geração mediana (intervalo) | Duração mediana | RTF mediano (intervalo) | Pico RSS mediano | WER Whisper mediana (amostras) |
|---:|---:|---:|---:|---:|---:|---:|
| 2 | 0,782 s | 13,518 s (12,102–14,066) | 8,24 s | 1,644 (1,6405–1,6587) | 2,295 GiB | 0,200 (0,133; 0,200; 0,200) |
| 4 | 0,795 s | 7,707 s (7,340–10,132) | 7,52 s | 1,021 (1,0194–1,0249) | 2,370 GiB | 0,333 (0,400; 0,133; 0,333) |
| 6 | 0,894 s | 7,411 s (6,570–12,615) | 7,92 s | 0,944 (0,9358–0,955) | 2,555 GiB | 0,200 (0,200; 0,200; 0,533) |
| 8 | 0,821 s | 7,718 s (7,351–7,809) | 7,84 s | 0,978 (0,9745–0,996) | 2,264 GiB | 0,267 (0,267; 0,200; 0,267) |

Turbo ficou configurável em 6 threads (menor mediana de tempo/RTF); Equilibrado em 8 (quase a mesma velocidade mediana, menor RAM amostrada e intervalo temporal/ASR mais estável neste pequeno conjunto). 6 threads teve uma geração e uma transcrição atípicas. Esses 3 exemplos por perfil não bastam para afirmar qualidade perceptiva ou estabilidade geral. WER é proxy de transcrição, não avaliação de voz, semelhança nem naturalidade. A opção Original continua padrão/fallback.

Foram adicionadas variáveis de ajuste local `BEROFEL_QWEN3_NATIVE_TURBO_THREADS` e `BEROFEL_QWEN3_NATIVE_BALANCED_THREADS` (1–8; Turbo ainda aceita a variável legada). O cache do embedding não varia com threads, permitindo que os dois perfis compartilhem o condicionamento. Cache de áudio segue separado por perfil e configuração.

No teste real pela rota canônica do serviço, Turbo e Equilibrado geraram WAV mono 24 kHz com o mesmo perfil local autorizado e texto português inédito; ambos reportaram corretamente 6/8 threads. O teste do painel também seleciona cada modo. A Narração mantém os dois últimos WAVs no histórico da sessão com botões “Ouvir” e “Ouvir geração anterior”, permitindo comparar amostras recentes A/B sem regenerar a primeira.

Comparação A/B inicial (antes do ajuste de encerramento), em modo offline, com exatamente a mesma frase e o mesmo perfil autorizado: Turbo levou 7,660 s de ponta a ponta, sintetizou 7,20 s (RTF 0,948); Equilibrado levou 13,347 s de ponta a ponta ao trocar o servidor de 6 para 8 threads, sintetizou 7,52 s (RTF 0,969). Ambos foram WAV PCM mono 24 kHz, não cacheados e reutilizaram o x-vector. Faster-Whisper base/int8, resample 24→16 kHz, Português/beam 1: WER 0,267 (Turbo) e 0,400 (Equilibrado) contra a frase. É uma amostra estocástica e WER não avalia naturalidade nem identidade vocal. Os WAVs estão somente na pasta externa de benchmark (`Comparacao_qwen3-tts-native-q4_20261119_115552_3092cea0.wav` e `Comparacao_qwen3-tts-native-q4-balanced_20261119_115605_da2af9f3.wav`).

O tempo extra ao alternar perfil foi rastreado até o encerramento do servidor: o adaptador enviava `{"operation":"shutdown"}`, comando não definido pelo servidor JSON-line upstream, e esperava o timeout de 5 s antes de terminar o processo. O wrapper agora fecha stdin e permite saída por EOF; se não terminar em 2 s, usa terminate/kill como fallback. Medição real no runtime instalado: troca de 6→8 threads caiu de 5,923 s para 0,981 s (modelo carregado em 0,857 s; sobrecusto de encerramento estimado 0,124 s).

Nova comparação A/B offline, mesmo texto novo e mesma referência, após essa correção: Turbo 9,433 s ponta a ponta, carga 0,786 s, geração 8,618 s, duração 9,12 s, RTF 0,945; Equilibrado 10,512 s ponta a ponta, carga 0,899 s, geração 9,414 s, duração 9,68 s, RTF 0,973. Sem cache de áudio; x-vector em cache. Artefatos externos: `Comparacao_pipefix_qwen3-tts-native-q4_20261119_120100_6c93d0ac.wav` e `Comparacao_pipefix_qwen3-tts-native-q4-balanced_20261119_120111_aedcb2aa.wav`.

### Referência pareada com o Qwen oficial

No mesmo Windows/CPU, em execução offline e sem cache de frase, os três modos geraram a frase “No Berofel Studio, esta mesma frase compara os modos Original, Turbo e Equilibrado para medir velocidade e clareza em português brasileiro.” com a mesma referência vocal autorizada. Medidas de uma execução (sem inferência de mediana):

| Modo | Carregamento | Síntese | WAV | RTF | WER Whisper base/int8 |
|---|---:|---:|---:|---:|---:|
| Original Qwen oficial | 7,735 s | 48,891 s | 8,16 s | 5,992 | 0,190 |
| Turbo Q4 · 6 threads | 0,850 s | 11,100 s | 11,52 s | 0,964 | 0,048 |
| Equilibrado Q4 · 8 threads | 0,813 s | 11,660 s | 11,84 s | 0,985 | 0,143 |

Tempo ponta a ponta medido foi 57,121 / 11,983 / 12,713 s, respectivamente. Pico agregado amostrado (processo chamador e filhos) nesta execução foi 5,203 GiB, dominado pela inferência oficial; não é pico separado por perfil. O Faster-Whisper leu 16 kHz após resampling local de 24 kHz; uma sentença e decoding estocástico são insuficientes para inferir qualidade geral. Além disso, o motor oficial usa prompt com referência/transcrição, enquanto o adaptador nativo testado usa x-vector sem ICL (a clonagem ICL nativa falhou nos limites de frames e não está habilitada); é o mesmo áudio-fonte autorizado, mas o condicionamento não é idêntico. Não interprete WER menor como maior semelhança de voz.

WAVs pareados, privados, fora do Git: `Matched_qwen3-tts-local_20261119_120619_e4c0206e.wav`, `Matched_qwen3-tts-native-q4_20261119_120632_f127aa95.wav`, `Matched_qwen3-tts-native-q4-balanced_20261119_120645_b219cc66.wav` em `C:\Users\Berofel\Desktop\BerofelStudio_QwenTurbo_Benchmark_20261119\matched_original_comparison_arquivos\narracoes`.

### Tamanhos curto, médio e longo com stream PCM

Em 19/11/2026 executei `scripts/benchmark_qwen3_native_lengths.py --confirm-own-or-authorized-voice --repeats 1` no Ryzen 7 5700G, com `HF_HUB_OFFLINE=1` e `TRANSFORMERS_OFFLINE=1`. Cada um dos seis pedidos foi uma inferência inédita, sem cache de áudio e com x-vector reutilizado; o callback recebeu chunks PCM e os WAVs temporários foram validados como não silenciosos. Os resultados abaixo são uma repetição por célula (não medianas); o texto estocástico também produziu durações diferentes:

| Texto | Perfil | Síntese | Duração WAV | RTF | Primeiro PCM desde a chamada |
|---|---|---:|---:|---:|---:|
| Curto (66 caracteres) | Turbo Q4 / 6 threads | 5,707 s | 5,20 s | 1,098 | 3,19 s |
| Curto (66 caracteres) | Equilibrado Q4 / 8 threads | 8,043 s | 7,12 s | 1,130 | 3,88 s |
| Médio (231 caracteres) | Turbo Q4 / 6 threads | 21,801 s | 19,92 s | 1,094 | 8,45 s |
| Médio (231 caracteres) | Equilibrado Q4 / 8 threads | 17,276 s | 15,28 s | 1,131 | 6,86 s |
| Longo (738 caracteres) | Turbo Q4 / 6 threads | 58,044 s | 52,72 s | 1,101 | 21,15 s |
| Longo (738 caracteres) | Equilibrado Q4 / 8 threads | 54,779 s | 47,76 s | 1,147 | 19,58 s |

Carregamento do servidor em cada caso ficou entre 0,800 e 0,818 s; preparação do perfil foi 0 s reportados e o cache do embedding acertou em todos. Pico agregado amostrado nas seis gerações: 1,946 GiB; pico de CPU agregado normalizado pelos processadores lógicos: 51,7%. O primeiro chunk não é o início da frase inteira reproduzida: é o primeiro bloco PCM de aproximadamente 0,5 s que o stream incremental disponibiliza. O Turbo venceu em RTF neste conjunto, mas uma repetição não define um vencedor estável e as saídas têm durações distintas. JSON sem transcrições ou caminhos privados: `C:\Users\Berofel\Desktop\BerofelStudio_QwenTurbo_Benchmark_20261119\native_lengths_results.json`; os WAVs de execução foram removidos com o diretório temporário. Não foi feita avaliação perceptiva ou ASR nesta rodada.

### Tamanho do chunk de preview

Para investigar o atraso inicial, medi o mesmo texto curto com chunks de 1, 2, 3 e 6 frames, duas inferências inéditas por perfil e configuração, alternando a ordem dos perfis. O teste registra a primeira chamada do callback PCM desde o início da geração e remove apenas os caches temporários próprios. Um chunk de 1 frame não melhorou consistentemente o primeiro PCM e quase duplicou o custo (RTF ~2,1); 2 e 3 frames também elevaram o RTF. Não encontrei ganho de latência repetível que justifique perder vazão ou criar mais gravações/consultas no fluxo. O padrão permanece em 6 frames; a variável local `BEROFEL_QWEN3_NATIVE_STREAM_CHUNK_FRAMES` agora permite experimentação entre 1 e 12, com valor padrão 6.

| Chunk (frames) | Perfil | Síntese mediana | RTF mediano | Primeiro PCM mediano |
|---:|---|---:|---:|---:|
| 1 | Turbo Q4 | 15,080 s | 2,094 | 3,634 s |
| 2 | Turbo Q4 | 8,291 s | 1,524 | 3,101 s |
| 3 | Turbo Q4 | 8,339 s | 1,333 | 3,450 s |
| 6 | Turbo Q4 | 7,007 s | 1,123 | 3,528 s |
| 1 | Equilibrado Q4 | 13,299 s | 2,173 | 2,978 s |
| 2 | Equilibrado Q4 | 9,463 s | 1,546 | 2,882 s |
| 3 | Equilibrado Q4 | 7,579 s | 1,353 | 2,739 s |
| 6 | Equilibrado Q4 | 5,871 s | 1,147 | 2,731 s |

São medianas de apenas duas gerações; a saída do modelo é estocástica e o carregamento frio aparece em uma das medições. Os JSONs de cada configuração ficam fora do Git em `C:\Users\Berofel\Desktop\BerofelStudio_QwenTurbo_Benchmark_20261119\native_lengths_chunk_<frames>_results.json`. Para reproduzir: `scripts/benchmark_qwen3_native_lengths.py --confirm-own-or-authorized-voice --repeats 2 --lengths curta --chunk-frames <1|2|3|6>`.

### Sampling rápido por solicitação

O protocolo JSON do servidor Qwen nativo aceita `temperature` e `top_k` por pedido ([implementação do servidor](https://github.com/CHE3MZ/qwen3-tts.cpp/blob/main/src/main.cpp); parâmetros documentados em [`tts_params`](https://github.com/CHE3MZ/qwen3-tts.cpp/blob/main/src/qwen3_tts.h)). Medi a configuração padrão (0,9/50), uma opção greedy (0/1) e uma intermediária (0,7/20), sempre Base Q4, CPU/6 threads, x-vector em cache, modo offline e duas gerações inéditas por célula. O benchmark limitou o pedido curto a 256 tokens e o médio a 512; nenhuma geração normal chegou perto do limite. O ASR é Faster-Whisper Base/int8 local, com WAV convertido a PCM16/16 kHz; WER é apenas proxy de inteligibilidade, não qualidade vocal.

| Texto | Sampling | Síntese mediana | RTF mediano | WER Whisper mediano |
|---|---|---:|---:|---:|
| Curto (73 caracteres) | Padrão 0,9/50 | 5,345 s | 0,961 | 0,091 |
| Curto (73 caracteres) | Greedy 0/1 | 5,249 s | 0,938 | 0,364 |
| Curto (73 caracteres) | Intermediário 0,7/20 | 5,902 s | 0,958 | 0,137 |
| Médio (231 caracteres) | Padrão 0,9/50 | 17,712 s | 0,954 | 0,038 |
| Médio (231 caracteres) | Intermediário 0,7/20 | 18,279 s | 0,952 | 0,025 |

Greedy ficou somente 1,8% mais rápido no texto curto e aumentou WER de 0,091 para 0,364; por isso não foi ligado ao Turbo. A opção intermediária não acelerou de forma consistente e foi mais lenta no curto e no médio. Uma tentativa greedy de texto médio chegou a aproximadamente 9 GiB no processo nativo e foi interrompida antes do limite de geração para evitar esgotar a RAM; ela não conta como áudio validado. Nenhum ajuste de sampling foi integrado como modo novo; o editor permanece nos parâmetros padrão. Script reproduzível: `scripts/benchmark_qwen3_native_sampling.py --confirm-own-or-authorized-voice --repeats 2 --length curta|media --asr-wer`. Amostras e `results.json` privados, fora do repositório, nas pastas `native_sampling_curta_20261119_125849` e `native_sampling_media_20261119_125941` dentro do diretório externo de benchmark.

#### Rechecagem de sampling no CLI e limitação do proxy ASR

No CLI one-shot, comparei padrão 0,9/50 com 0,7/20, 6 threads, duas inferências inéditas por tamanho e o mesmo perfil/texto. RTF mediano curto: 1,149 (padrão) e 1,117 (0,7/20); médio: 1,019 e 1,018. Não há ganho repetível relevante no texto médio. WER Faster-Whisper Base/int8 variou por amostra: curto 0,500/0,500 no padrão contra 0,333/0,500 no 0,7/20; médio 0,487/0,436 contra 0,513/0,436. Não existe melhora consistente, portanto nenhum preset de sampling foi integrado ao editor.

Esta rodada também mostrou que o WER não é um critério suficiente de qualidade neste perfil: o mesmo Whisper transcreveu mal amostras nativas e a referência F32 de controle (numa execução, WER 1,0, transcript repetido “Eples”). Isso não prova que o áudio seja inaudível; confirma que é preciso escutar as amostras, junto com as métricas automatizadas. A amostra F32 de controle (12,4 s gerados em 70,03 s, sem cache de frase) e as amostras Q4 permanecem privadas no diretório local de benchmark para avaliação auditiva. Sem validação subjetiva, naturalidade e inteligibilidade percebida continuam não aprovadas.

### Alternativa em C puro investigada

O repositório [gabriele-mastrapasqua/qwen3-tts](https://github.com/gabriele-mastrapasqua/qwen3-tts) declara suporte ao Base 0.6B, clonagem por referência, perfis x-vector/`.qvoice`, streaming PCM, INT8/INT4, MIT e SIMD AVX2. A documentação atual chama a rota Windows de beta via WSL2; a evidência de x86 publicada mede um Ryzen 7 6800H sob WSL2, não este Ryzen 7 5700G. As observações desse projeto (incluindo RTF/Q4/threads) não são comparáveis diretamente com as do runtime CHE3MZ, por serem builds, caminhos de inferência e metodologias diferentes.

Verificação local sem instalar componentes: `wsl.exe` existe apenas como launcher de instalação; `wsl --status` e `wsl -l -q` exibiram a ajuda do instalador, e nenhuma distribuição WSL aparece. GCC, Clang, Make, CMake e Ninja também não estão disponíveis no PATH. Assim, não há toolchain/distribuição Linux já pronta para compilar e validar esse backend aqui. Não instalei WSL2 nem outra distribuição. Como alternativa Windows já funcional, o backend CHE3MZ Q4 integrado gerou no fluxo canônico local a RTF 0,944–0,985 nos casos medidos; mantenho-o opt-in e não substituo o Original. A alternativa C puro fica como investigação não executada até existir build suportado nativamente para Windows ou uma decisão explícita de disponibilizar ambiente WSL2 de desenvolvimento.

### Perfil dos estágios internos do CLI Q4

Para medir a divisão de custo dentro do motor, usei o CLI Windows Q4 instalado diretamente, com um x-vector autorizado já em cache, execução offline e 6 threads. Cada medição é um processo CLI novo (logo inclui inicialização/carregamento no tempo de parede); os tempos internos `Generate` e `Decode` vêm do próprio binário. Foram feitas duas gerações inéditas por tamanho, sem cache de frase. O script salva WAVs e stdout/stderr locais fora do repositório em `Desktop\BerofelStudio_QwenTurbo_Benchmark_20261119\native_stages_<timestamp>`.

| Texto | Mediana parede | Mediana WAV | RTF mediano | `Generate` | `Decode` | RAM pico mediano |
|---|---:|---:|---:|---:|---:|---:|
| Curto (72 caracteres) | 6,552 s | 5,72 s | 1,149 | 2,096 s (37,7%) | 3,464 s (62,3%) | 1,966 GiB |
| Médio (231 caracteres) | 18,567 s | 18,24 s | 1,019 | 6,602 s (37,7%) | 10,914 s (62,3%) | 2,673 GiB |

Percentuais são a fração do `Total` interno do CLI (medianas de duas amostras); `Generate` agrupa a geração autoregressiva, incluindo Talker/Code Predictor, e `Decode` é o decodificador acústico. O executável não expõe subtempos separados para prefill do Talker e Code Predictor. Tokenização e `Encode` apareceram como 0–1 ms, arredondados pelo próprio CLI. Assim, o maior estágio medido é o decoder acústico (~62%); otimizar apenas o Code Predictor não atacaria o maior custo observado. Tempo até o primeiro PCM não é exposto pelo modo CLI de WAV; para streaming do editor, mantenho as medições anteriores (~2,7–3,5 s para texto curto, conforme configuração/chunk). CPU de pico amostrada foi ~37,6–37,8% da capacidade lógica total; o processo fez uso concentrado de parte dos 16 processadores lógicos, não representa o percentual de um núcleo.

Os resultados incluem saída WAV mono PCM16/24 kHz com RMS verificado acima de silêncio; não medem naturalidade ou semelhança vocal. Reprodutibilidade: `scripts\benchmark_qwen3_native_stages.py --confirm-own-or-authorized-voice --lengths curta media --repeats 2 --threads 6`. Dependências do script (`numpy`, `psutil`) já existem no venv do editor. A versão do script também registra os logs brutos do CLI e interrompe com erro se não houver WAV válido ou se o sinal estiver silencioso.

### Sweep de threads do CLI e confirmação do gargalo

Para confirmar o perfil de threads com os tempos internos, repeti o CLI em 2, 4, 6 e 8 threads, CPU/offline, mesmo perfil e textos curto/médio, sem cache de texto. 2 threads tem uma amostra por tamanho; 4, 6 e 8 têm duas. Cada execução inicia um processo CLI novo, portanto o RTF abaixo inclui startup no tempo de parede. Medianas dos estágios internos são separadas do tempo total:

| Threads | RTF parede curto | RTF parede médio | `Decode` mediano curto/médio | `Generate` mediano curto/médio | Pico RAM amostrado curto/médio |
|---:|---:|---:|---:|---:|---:|
| 2 (n=1) | 1,794 | 1,712 | 7,522 / 23,425 s | 4,129 / 13,080 s | 2,036 / 2,878 GiB |
| 4 (n=2) | 1,202 | 1,091 | 4,187 / 14,373 s | 2,419 / 8,279 s | 1,998 / 2,867 GiB |
| 6 (n=2) | 1,149 | 1,019 | 3,464 / 10,914 s | 2,096 / 6,602 s | 1,966 / 2,673 GiB |
| 8 (n=2) | 1,135 | 1,031 | 3,912 / 11,325 s | 2,392 / 6,886 s | 2,004 / 2,698 GiB |

6 threads permanece a recomendação Turbo: menor RTF mediano no texto médio e melhor mediana observada do decoder nos dois comprimentos. No curto, 8 threads ficou próximo e ligeiramente abaixo no RTF de parede, mas o estágio interno total foi mais longo; as durações geradas e o startup variam. O decoder continua consumindo aproximadamente 62–65% do total interno em todos os perfis. 2 threads perde vazão, e 4 threads ficou mais lento que 6/8 neste ensaio. São poucas repetições estocásticas; isso confirma uma configuração prática, não uma lei para toda máquina/carga. Todos os WAVs deste sweep foram PCM16 mono 24 kHz, RMS acima de 0,028, sem amostras clipadas. Os resultados, áudio e logs ficam fora do Git em subpastas `native_stages_*` de `C:\Users\Berofel\Desktop\BerofelStudio_QwenTurbo_Benchmark_20261119`; nenhum áudio de referência ou gerado foi adicionado ao repositório.

#### Primeiro chunk por threads no serviço persistente

Também executei `scripts/benchmark_qwen3_native_lengths.py --confirm-own-or-authorized-voice --repeats 1 --lengths curta --chunk-frames 6` com Turbo/Equilibrado em 4, 6 e 8 threads. A referência x-vector foi reaproveitada em todos os casos e nenhum WAV de frase veio do cache. Uma chamada por célula:

| Threads | Turbo: primeiro chunk | Turbo: geração / RTF | Equilibrado: primeiro chunk | Equilibrado: geração / RTF |
|---:|---:|---:|---:|---:|
| 4 | 3,579 s | 7,268 s / 1,180 | 2,563 s | 6,386 s / 1,191 |
| 6 | 3,142 s | 5,969 s / 1,114 | 2,399 s | 6,039 s / 1,094 |
| 8 | 3,270 s | 6,288 s / 1,139 | 2,741 s | 6,979 s / 1,118 |

No caso Turbo, o primeiro chunk inclui a carga inicial do servidor (0,79–0,81 s); o perfil Equilibrado reutilizou o processo Q4 já carregado na execução pareada, então sua latência é aquecida. 6 threads foi melhor nas duas comparações observadas, mas só houve uma repetição. Os JSONs de cada execução agora usam nomes que incluem os dois limites de threads, para que o sweep não sobrescreva o arquivo anterior: `native_lengths_chunk_6_threads4-4_results.json`, `...threads6-6...` e `...threads8-8...` no diretório externo. As WAVs temporárias são removidas pelo benchmark.

Não foram obtidas métricas separadas de prefill/talker/code predictor para o runtime nativo. No oficial, o profiler mediu carga 6,008 s, prompt 0,655 s, prefill 0,413 s, 131 chamadas autoregressivas 47,645 s, das quais code predictor aninhado somou ~35,166 s; geração API 54,333 s, primeiro code frame ~0,7 s (não era áudio tocável). Isso aponta o code predictor como parcela dominante no backend oficial, mas não prova a mesma divisão interna no nativo. O script `scripts/benchmark_qwen3_stages.py` registra estágios oficiais.

## Testes / evidência da integração

- `tests.test_qwen3_native_tts` e testes Turbo do painel: testes focados passaram; teste opcional real passou usando modelo/perfil local.
- Validação real adicional pelo controle **Gerar** na interface, em sessão offline (`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`), com perfil autorizado configurado: Turbo Q4 enviou 10 chunks/453.120 bytes e Equilibrado Q4 enviou 10 chunks/460.800 bytes ao callback de prévia. Em ambos, o WAV produzido não estava silencioso, o player reproduziu/pausou e buscou posição (volume silenciado no teste automatizado), o bloco foi inserido na timeline, WAV e MP4 foram exportados com áudio e o projeto foi salvo/reaberto. A checagem do fluxo confirma ainda que o embedding vocal preparado foi reutilizado. O tempo total do smoke test Qt foi 7,2 s (Turbo) e 7,4 s (Equilibrado), incluindo montagem/exportação; não é latência de síntese. Script reproduzível: `scripts/validar_fluxo_qwen3_editor.py --configured-fast-profile --native-engine qwen3-tts-native-q4` ou `qwen3-tts-native-q4-balanced` com `--confirm-own-or-authorized-voice`. A saída física foi silenciada; a escuta subjetiva A/B ainda precisa do usuário.
- Repetição do fluxo de UI depois de tornar o tamanho do chunk configurável, mantendo o padrão 6: offline, Turbo enviou 12 chunks/552.960 bytes (8,3 s no smoke completo) e Equilibrado 10 chunks/430.080 bytes (7,0 s). Ambos voltaram a passar WAV, player/busca, timeline, exportações e reabertura do projeto.
- Benchmark nativo curto/médio/longo offline e com callback PCM, 6 inferências inéditas: `scripts/benchmark_qwen3_native_lengths.py`. O resultado acima é uma rodada exploratória, não uma mediana.
- Fluxo Qt real em modo offscreen e ambiente offline (`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`): ação Gerar no painel → WAV não silencioso → media source/player em reprodução → clipe inserido na timeline → export WAV e MP4 com streams de áudio/vídeo. WAV: 2.880.102 bytes; MP4: 122.415 bytes; 10 s. Artefatos privados de teste ficaram fora do repositório em `C:\Users\Berofel\Desktop\BerofelStudio_QwenTurbo_Benchmark_20261119`.
- O playback foi iniciado pelo player Qt; o teste foi offscreen e não prova que o som foi ouvido nos alto-falantes.
- Streaming real pelo callback nativo: primeiro chunk PCM em 3,053 s após modelo/perfil prontos; 16 chunks, 698.880 bytes PCM, WAV final 7,28 s. O tempo não inclui eventual preparo inicial de perfil/modelo; retorno da chamada inclui métricas separadas para esses tempos.
- Segunda medição do serviço após a correção de ordenação: geração 8,218 s para 7,12 s de áudio; primeiro chunk 3,062 s depois de modelo/perfil prontos e 3,849 s desde o início da solicitação, incluindo 0,787 s de carga. 15 chunks totalizaram 683.520 bytes, exatamente `frames × 4` do WAV float32 intermediário; a interface recebe PCM16, metade desse tamanho.
- Fluxo real de geração via ação do editor, offscreen e com sink de áudio simulado: 453.120 bytes PCM16 foram escritos para um WAV de 9,44 s (mesma contagem de amostras mono/24 kHz); o clipe foi inserido na timeline. O teste não emitiu gravação nos alto-falantes. Separadamente, o dispositivo Windows reportou suporte a 24 kHz mono e o `QAudioSink` real processou 150 ms de amostras silenciosas. A avaliação auditiva comparativa da voz ainda depende do usuário.
- Avaliação auditiva, comparação subjetiva da voz clonada e teste com firewall de rede continuam pendentes. O único perfil autorizado presente na estação neste ensaio é uma referência MP3 de 6,06 s; após conversão mono PCM16/24 kHz, 55,3% dos frames ficam abaixo do limiar simples de silêncio, e sua transcrição salva tem 3 palavras. O Whisper Base local reconheceu 8 palavras e WER 2,667 contra essa transcrição; como o próprio ASR também falhou nos áudios gerados, isto é um sinal de referência/avaliador insuficiente, não uma prova de erro da transcrição. Nenhum áudio ou perfil foi alterado.

## Limitações e restauração

A rota Turbo usa x-vector apenas. O CLI nativo oferece ICL (`reference + ref-text`); a primeira tentativa falhou porque o MP3 do perfil não foi normalizado. Após usar o normalizador FFmpeg do editor, ICL executou, mas consumiu 43,09 s para a frase curta, usou os 256 tokens permitidos, gerou 20,48 s com repetição forte segundo Whisper Base e teve RSS de 3,16 GB e memória física reportada de 4,46 GB. Não é um backend Turbo validado e não foi integrado. O modo x-vector permaneceu rápido (RTF mediano ~1,02–1,15 nestes testes), mas o WER do Whisper Base variou muito; sem referência mais adequada e escuta humana, a inteligibilidade/fidelidade do Q4 não está aprovada. Clonagem detalhada mantém o backend oficial. Q4 pode variar em pronúncia/fidelidade e não deve ser selecionado automaticamente sem ouvir. Sem GPU dedicada, quantização agressiva INT4 e modo Turbo são experimentais. Não foram implementadas otimizações de Code Predictor além da quantização; não houve destilação ou remoção de codebooks.

Para rollback de código: `git switch feat/qwen3-base-optimized` ou checkout de `backup/qwen3-0.6b-stable`. Para rollback integral, restaure a pasta externa; o bundle Git sozinho não contém dados de voz/modelos. O backend original não foi alterado nem removido.

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

Verificação local sem instalar componentes: `wsl.exe` existe apenas como launcher de instalação; `wsl --status` e `wsl -l -q` exibiram a ajuda do instalador, e nenhuma distribuição WSL aparece. GCC, Clang, Make, CMake e Ninja também não estão disponíveis no PATH. Assim, não há toolchain/distribuição Linux já pronta para compilar e validar esse backend aqui. Não instalei WSL2 nem outra distribuição. Como alternativa Windows já funcional, o backend CHE3MZ Q4 integrado gerou no fluxo canônico local RTF 0,944–0,985; mantenho-o opt-in e não substituo o Original.

Uma verificação posterior encontrou o asset [CPU Windows x64 do CHE3MZ release-1.0](https://github.com/CHE3MZ/qwen3-tts.cpp/releases/tag/release-1.0). Baixei-o somente para a pasta externa `native_release_1_0_20261119`; o SHA-256 coincidiu com o digest da API de Releases (`ce90df…9d3170cd`). A assinatura Authenticode está ausente. O build carregou o mesmo GGUF Q4_0 por caminho direto, aceitou o embedding de 4100 bytes e o servidor JSON produziu WAV válido. Comparação offline, mesmo perfil/embedding/texto, 6 threads e três pedidos inéditos quentes por binário:

| Binário CPU | RTF mediano | Tempo de parede mediano | Áudio mediano |
|---|---:|---:|---:|
| Instalado atual | 0,955 | 5,885 s | 6,16 s |
| CHE3MZ release-1.0 | 0,991 | 5,435 s | 5,36 s |

O tempo bruto menor do release acompanha uma duração de fala também menor; normalizado por áudio, ele foi ~3,8% mais lento. Não é uma atualização comprovadamente mais rápida e não foi conectado ao editor. Modelos, embeddings e WAVs dessa prova ficaram em pasta externa, fora do Git. A execução CLI atual continua preferível até surgir um candidato com ganho repetível.

O release mais recente [gabriele-mastrapasqua/qwen3-tts v0.23.0](https://github.com/gabriele-mastrapasqua/qwen3-tts/releases/tag/v0.23.0) publica executáveis Linux ARM64/x86_64 e macOS ARM64, mas nenhum Windows. O README documenta Windows via WSL2; como não há WSL instalado e a missão não o torna dependência obrigatória, não há binário C puro para testar nativamente nesta estação.

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

### Sweep de tamanho do chunk de prévia (19/11/2026)

Foi comparado o tamanho do chunk PCM em 1, 2, 3, 4, 5 e 6 frames na rota
persistente do serviço, com texto curto inédito em português, perfil autorizado
já preparado, cache de frase isolado, modo offline e duas repetições por valor.
Cada execução também testou Equilibrado; a tabela resume Turbo (6 threads).
Os resultados são medianas de apenas duas amostras e a duração gerada variou
entre amostras. O tempo até o primeiro chunk é desde a solicitação, incluindo
carga do servidor quando ocorria.

| Frames | Primeiro chunk mediano | Geração mediana | RTF mediano | RSS agregado máximo por rodada |
|---:|---:|---:|---:|---:|
| 1 | 3,108 s | 11,575 s | 2,082 | 1,911 GiB |
| 2 | 3,144 s | 8,217 s | 1,500 | 1,916 GiB |
| 3 | 3,256 s | 7,312 s | 1,297 | 1,922 GiB |
| 4 | 3,554 s | 7,514 s | 1,204 | 1,923 GiB |
| 5 | 3,453 s | 6,751 s | 1,155 | 1,928 GiB |
| 6 | 3,484 s | 6,526 s | 1,110 | 1,932 GiB |

Chunks de 1 frame anteciparam o primeiro PCM em somente ~0,38 s em relação a
6 frames, mas levaram ~77% mais tempo para concluir a geração. O tamanho 5
ficou próximo em latência inicial e cerca de 3,4% mais lento em RTF que 6; com
duas amostras não há evidência de vantagem consistente. Mantive 6 frames como
padrão, priorizando a conclusão rápida sem uma perda mensurável de responsividade
inicial. O primeiro chunk ainda leva aproximadamente 3,1–3,5 s no perfil Turbo
nesta medição; o stream não torna o modelo instantâneo.

Script reproduzível: `scripts/benchmark_qwen3_native_lengths.py
--confirm-own-or-authorized-voice --repeats 2 --lengths curta --chunk-frames N`.
Resultados JSON locais foram gravados no diretório externo de benchmark; os
WAVs temporários foram removidos. Nenhum modelo, perfil ou áudio de usuário foi
alterado. São medições de latência, não avaliação de qualidade perceptiva.

### Sweep adicional de threads acima de 8 (19/11/2026)

O limite experimental do adaptador foi contornado apenas no processo de
benchmark, sem alterar o código do editor. Mesmo backend Q4, texto médio novo
(231 caracteres), perfil autorizado já condicionado, 6 frames/chunk, offline,
duas repetições por valor e sem cache de áudio. A tabela usa mediana; cada WAV
variou em duração por amostragem estocástica.

| Threads | Primeiro chunk mediano | Geração mediana | RTF mediano | Pico CPU agregado observado | Pico RSS agregado |
|---:|---:|---:|---:|---:|---:|
| 6 | 6,951 s | 18,494 s | 1,099 | 39,2% | 1,936 GiB |
| 8 | 7,280 s | 19,600 s | 1,126 | 56,8% | 1,936 GiB |
| 10 | 7,735 s | 20,576 s | 1,104 | 64,1% | 1,936 GiB |
| 12 | 7,551 s | 19,641 s | 1,096 | 76,8% | 1,936 GiB |
| 16 | 8,823 s | 20,276 s | 1,171 | 100,3% | 1,936 GiB |

12 threads ficou somente ~0,2% abaixo do RTF de 6 threads, sem redução
confiável do tempo absoluto; seu primeiro chunk foi ~0,6 s mais lento. A
medição curta equivalente também não apontou vantagem consistente de 10–12,
e 16 threads saturou a CPU e foi mais lento. Mantive o limite do editor em 8
e Turbo em 6 threads: subir a concorrência não oferece ganho prático comprovado
neste Ryzen 7 5700G, e 6 threads preserva melhor a margem para a interface.
Esse sweep é pequeno e não representa todo uso simultâneo do computador.

O ensaio foi executado por uma cópia temporária do benchmark em diretório
externo; o WAV temporário foi apagado após a validação de sinal. Não houve
mudança no runtime, modelo, cache persistente ou configuração do editor.

### Compilação portátil Windows e comparação de revisões C++

Preparei um toolchain LLVM-MinGW portátil fora do projeto. O arquivo oficial
`llvm-mingw-20261117-ucrt-x86_64.zip` (191.082.415 bytes) teve SHA-256
`4d002e330a0f703625aa5ccbc37e96f8f824413e163bfc7336774aabd2c3a412`, igual
ao digest publicado pela API de releases. O runtime experimental foi compilado
como Release com `-march=native` (GGML informou CPU backend nativo), AVX2/FMA/F16C,
sem CUDA/Vulkan. Construí separadamente CHE3MZ `release-1.0`
(`1433de988873d289aae097e18f8b2508d507f687`) e `main`
(`e04c79a2b37be8b4696e918e728edd5e7541a379`), ambos com GGML submodule
`707321c4cf6d21cb4bc831aa8b687dbf01a521ce`. O build do main precisou apenas
de `#include <math.h>` em uma cópia externa de `audio_tokenizer_encoder.cpp`
para os headers do libc++; essa alteração não foi feita no Berofel Studio nem
commitada. Desativei exemplos/testes GGML opcionais depois de falhas de headers
em `common.cpp`/`mnist-common.cpp`; os alvos das bibliotecas e do CLI foram
compilados. Referências: [repositório CHE3MZ](https://github.com/CHE3MZ/qwen3-tts.cpp)
e [releases LLVM-MinGW](https://github.com/mstorsjo/llvm-mingw/releases).

Comparação de inferência real, offline, mesma referência autorizada e x-vector,
mesmo modelo Q4/tokenizer, frase curta de 72 caracteres e média de 231, 6 threads,
temperatura 0,9/top-k 50, duas execuções inéditas por caso. Todos os WAVs foram
mono PCM16/24 kHz, não silenciosos e sem clipping. RTF é a métrica principal:

| Binário | Curto: parede / duração / RTF | Médio: parede / duração / RTF | RSS mediano curto/médio |
|---|---:|---:|---:|
| Atual instalado | 7,172 s / 6,48 s / 1,108 | 20,221 s / 19,92 s / 1,016 | 1,999 / 2,767 GiB |
| `release-1.0` recompilado AVX2 | 6,407 s / 5,68 s / 1,129 | 18,550 s / 18,14 s / 1,024 | 1,945 / 2,637 GiB |
| `main` recompilado AVX2 | 7,018 s / 6,32 s / 1,112 | 18,826 s / 18,28 s / 1,031 | 1,998 / 2,675 GiB |
| release Windows oficial 1.0 | 7,032 s / 5,88 s / 1,197 | 19,763 s / 18,40 s / 1,074 | 1,962 / 2,659 GiB |

Apesar de alguns tempos de parede menores, o RTF dos dois builds AVX2 ficou
igual ou ligeiramente pior que o instalado: a saída também ficou mais curta.
O total interno do engine por segundo de áudio foi ~0,954/0,963 no instalado,
~0,954/0,967 no release recompilado e ~0,959/0,971 no main recompilado (curto/médio).
Portanto não há evidência de aceleração computacional útil para substituir o
binário em uso. O release oficial Windows 1.0 foi mais lento no RTF.

Whisper Base/int8 local, beam 1, foi usado apenas como proxy de inteligibilidade
(n=2 por comprimento): WER mediano curto/médio foi 0,500/0,487 no instalado,
0,459/0,385 no build `release-1.0` e 0,625/0,513 no build `main`; o release
oficial teve 0,417/0,359. O cosine do encoder nativo vs referência (também proxy,
n=2) foi 0,976/0,973 no instalado e 0,967/0,971 no build recompilado. Essas
métricas são instáveis em frases curtas e não aprovam naturalidade nem identidade.
As amostras A/B current vs build main estão na pasta externa
`AB_AVX2_vs_installed` com manifest SHA-256; ficam fora do Git por conterem a voz
autorizada. A escuta humana ainda é necessária.

O CLI foi testado, mas não conectado ao editor: não superou o runtime atual em
RTF, e o build alternativo não reproduziu o adaptador de streaming validado.
Nenhum DLL, modelo, preset, embedding ou configuração do runtime ativo foi
substituído. Não foi executada a suíte upstream completa do C++.

#### Fast-math e prefill não-streaming

`-ffast-math` sem ressalvas falhou na compilação do GGML porque as rotinas
exigem aritmética com NaN/Inf. Com `-fno-finite-math-only`, o build compilou,
mas ficou mais lento que o build `main` normal: RTF mediano curto/médio 1,138/
1,045 contra 1,112/1,031. Não foi integrado nem submetido a avaliação acústica.

Também comparei `--non-streaming` no CLI atual compilado, mesmo Q4, 6 threads,
mesmo perfil/textos/parâmetros, n=2, sem cache de frase. RTF mediano padrão vs
não-streaming: curto 1,155 vs 1,165; médio 1,031 vs 1,061. A opção não trouxe
ganho de throughput e ficou desativada. WAVs passaram formato/sinal/clipping;
não foi necessária uma rodada ASR porque nenhum modo venceu em RTF.

Por fim, compilei o mesmo `main` com `GGML_CPU_REPACK=OFF` para comparar o
repacking Q4 padrão ligado/desligado. Com repack desligado, RTF mediano foi
1,191 (curto) e 1,037 (médio), contra 1,112 e 1,031 no build normal ligado;
não houve ganho. Os quatro WAVs continuaram válidos e sem clipping, mas a
variante não foi avaliada por ASR por já perder em desempenho e não foi integrada.

O build com `GGML_LTO=ON` + IPO também compilou. No texto curto, RTF mediano
foi 1,176 contra 1,112 no `main` normal. Um dos dois textos médios atingiu o
limite de 512 tokens e produziu 40,96 s de áudio; esse resultado é uma falha de
geração/cap e foi excluído de qualquer comparação de qualidade. A única execução
média sem cap não permite inferir ganho; LTO não foi aprovado nem conectado ao
editor. Os dois arquivos GGUF Q4 locais (`qwen3-tts-0.6b-q4_0.gguf` e
`qwen3-tts-0.6b-q4_0-exp.gguf`) também foram verificados: mesmo tamanho e SHA-256,
portanto não constituem duas quantizações para A/B.

Os comandos de benchmark e binários experimentais ficam apenas na pasta externa
`C:\\Users\\Berofel\\Desktop\\BerofelStudio_QwenTurbo_Benchmark_20261119\\portable_build`.
As únicas alterações na árvore Git desta rodada são os registros técnicos; o
backend Original e o Turbo integrado continuam executáveis e intocados.

- `tests.test_qwen3_native_tts` e testes Turbo do painel: testes focados passaram; teste opcional real passou usando modelo/perfil local.
- Validação real adicional pelo controle **Gerar** na interface, em sessão offline (`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`), com perfil autorizado configurado: Turbo Q4 enviou 10 chunks/453.120 bytes e Equilibrado Q4 enviou 10 chunks/460.800 bytes ao callback de prévia. Em ambos, o WAV produzido não estava silencioso, o player reproduziu/pausou e buscou posição (volume silenciado no teste automatizado), o bloco foi inserido na timeline, WAV e MP4 foram exportados com áudio e o projeto foi salvo/reaberto. A checagem do fluxo confirma ainda que o embedding vocal preparado foi reutilizado. O tempo total do smoke test Qt foi 7,2 s (Turbo) e 7,4 s (Equilibrado), incluindo montagem/exportação; não é latência de síntese. Script reproduzível: `scripts/validar_fluxo_qwen3_editor.py --configured-fast-profile --native-engine qwen3-tts-native-q4` ou `qwen3-tts-native-q4-balanced` com `--confirm-own-or-authorized-voice`. A saída física foi silenciada; a escuta subjetiva A/B ainda precisa do usuário.
- Repetição do fluxo de UI depois de tornar o tamanho do chunk configurável, mantendo o padrão 6: offline, Turbo enviou 12 chunks/552.960 bytes (8,3 s no smoke completo) e Equilibrado 10 chunks/430.080 bytes (7,0 s). Ambos voltaram a passar WAV, player/busca, timeline, exportações e reabertura do projeto.
- Benchmark nativo curto/médio/longo offline e com callback PCM, 6 inferências inéditas: `scripts/benchmark_qwen3_native_lengths.py`. O resultado acima é uma rodada exploratória, não uma mediana.
- Fluxo Qt real em modo offscreen e ambiente offline (`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`): ação Gerar no painel → WAV não silencioso → media source/player em reprodução → clipe inserido na timeline → export WAV e MP4 com streams de áudio/vídeo. WAV: 2.880.102 bytes; MP4: 122.415 bytes; 10 s. Artefatos privados de teste ficaram fora do repositório em `C:\Users\Berofel\Desktop\BerofelStudio_QwenTurbo_Benchmark_20261119`.
- O playback foi iniciado pelo player Qt; o teste foi offscreen e não prova que o som foi ouvido nos alto-falantes.
- Streaming real pelo callback nativo: primeiro chunk PCM em 3,053 s após modelo/perfil prontos; 16 chunks, 698.880 bytes PCM, WAV final 7,28 s. O tempo não inclui eventual preparo inicial de perfil/modelo; retorno da chamada inclui métricas separadas para esses tempos.
- Segunda medição do serviço após a correção de ordenação: geração 8,218 s para 7,12 s de áudio; primeiro chunk 3,062 s depois de modelo/perfil prontos e 3,849 s desde o início da solicitação, incluindo 0,787 s de carga. 15 chunks totalizaram 683.520 bytes, exatamente `frames × 4` do WAV float32 intermediário; a interface recebe PCM16, metade desse tamanho.
- Fluxo real de geração via ação do editor, offscreen e com sink de áudio simulado: 453.120 bytes PCM16 foram escritos para um WAV de 9,44 s (mesma contagem de amostras mono/24 kHz); o clipe foi inserido na timeline. O teste não emitiu gravação nos alto-falantes. Separadamente, o dispositivo Windows reportou suporte a 24 kHz mono e o `QAudioSink` real processou 150 ms de amostras silenciosas. A avaliação auditiva comparativa da voz ainda depende do usuário.
- Avaliação auditiva, comparação subjetiva da voz clonada e teste com firewall de rede continuam pendentes. O único perfil autorizado presente na estação neste ensaio é uma referência MP3 de 6,06 s; após conversão mono PCM16/24 kHz, 55,3% dos frames ficam abaixo do limiar simples de silêncio, e sua transcrição salva tem 3 palavras. O Whisper Base local reconheceu 8 palavras e WER 2,667 contra essa transcrição; como o próprio ASR também falhou nos áudios gerados, isto é um sinal de referência/avaliador insuficiente, não uma prova de erro da transcrição. Nenhum áudio ou perfil foi alterado. A validação de gravação foi ajustada para avisar acima de 50% quase silencioso (antes o limiar era >60%); a checagem real do perfil agora apresenta esse aviso, e o seletor mostra a recomendação imediatamente quando detectar problema. A gravação não é reescrita.

## Limitações e restauração

### Investigação adicional: Q3_K a partir dos pesos originais

- Os pesos originais do Talker continuam disponíveis localmente em `%LOCALAPPDATA%\BFS\qwen3_tts\model\model.safetensors` (1.829.344.272 bytes); o speech tokenizer está em `model\speech_tokenizer\model.safetensors`. O modelo Turbo instalado é um GGUF Q4_0 de 1.080.258.176 bytes. Nenhum desses arquivos foi modificado.
- O runtime C++ atual reconhece e desquantiza Q3_K, mas o conversor GGUF do projeto (`scripts/convert_tts_to_gguf.py`) só oferece F16/F32/Q8_0 e documenta explicitamente que os K-quants ainda não têm quantização Python implementada. A biblioteca `gguf` 0.19.0 expõe o enum e o caminho de desquantização Q3_K, mas `gguf.quants.quantize()` não implementa a quantização K; o próprio `tools/model-converter/setup_models.py` deixa Q3_K desabilitado e adverte sobre artefatos audíveis.
- O conversor nativo de pesos do GGUF é uma ferramenta separada que não está presente no build externo disponível. Portanto não foi produzido Q3_K, nem se tentou converter o Q4 para Q3 (o que degradaria os pesos por quantização em cascata). Produzir esse candidato exigiria implementar/validar um conversor nativo de checkpoint Qwen3-TTS, abrangendo nomes, tensores e metadados específicos, além de quantização de Talker/tokenizer compatível. Esse trabalho não é um ajuste seguro de configuração e ficou fora deste ensaio; nenhum runtime ou perfil do editor foi alterado.
- A dependência `gguf` foi instalada somente sob `portable_build\gguf-python` na pasta externa de benchmark para inspeção, sem alterar o venv do editor. Não há dependência nova no produto.
- Conclusão deste ensaio: não existe evidência de que um Q3_K gere ganho suficiente para justificar a qualidade e o risco do conversor incompleto. Manter o Q4 Turbo experimental como estava e o backend oficial Original intacto. Para avançar com Q3_K, o próximo experimento deve implementar um conversor reproduzível fora do runtime do editor e validar todos os tensores/metadados, geração, áudio A/B e qualidade antes de integrar.

### Avaliação de backend alternativo Pure C

- Foi inspecionado e clonado fora do repositório do editor o projeto `gabriele-mastrapasqua/qwen3-tts`, commit `ef339be58a778b062e1c14382347964552eae007` (licença MIT). A implementação documenta execução do Base 0.6B, clonagem a partir de referência, perfis `.qvoice`/x-vector, streaming, português, SIMD AVX2 e modos INT8/INT4. A documentação publica números de outro hardware (Ryzen 7 6800H/M1), que não são evidência de desempenho neste 5700G.
- Neste Windows não há distribuição WSL instalada e o projeto documenta Windows via WSL2; também não há OpenBLAS disponível no PATH/local para o build descrito. Testei uma compilação sintática nativa da fonte `main.c` com o LLVM-MinGW portátil x86_64-w64-windows-gnu. Ela falhou imediatamente: `posix_memalign` não está declarado em `qwen_tts_kernels.h:16` e `setenv` não está declarado em `main.c:1035`. A árvore também usa APIs POSIX `mmap`, `unistd` e pthread. Portanto seria necessário um port/compatibilidade Windows mais amplo, além da dependência BLAS, antes de gerar um executável; esse trabalho não é um simples ajuste de build. Não se instalou WSL, dependência global nem ferramenta adicional no sistema, e nenhum código do projeto foi integrado.
- O backend atual `qwen3-tts.cpp` continua sendo a única alternativa nativa realmente medida neste ambiente e não superou o serviço instalado em RTF/qualidade proxy. Nenhum modo mais rápido que o Turbo já integrado foi comprovado nesta rodada. O Pure C deve ser a próxima avaliação experimental se/quando houver toolchain Windows suportado ou WSL2/OpenBLAS disponível; o Original permanece a opção estável.

A rota Turbo usa x-vector apenas. O CLI nativo oferece ICL (`reference + ref-text`); a primeira tentativa falhou porque o MP3 do perfil não foi normalizado. Após usar o normalizador FFmpeg do editor, ICL executou, mas consumiu 43,09 s para a frase curta, usou os 256 tokens permitidos, gerou 20,48 s com repetição forte segundo Whisper Base e teve RSS de 3,16 GB e memória física reportada de 4,46 GB. Não é um backend Turbo validado e não foi integrado. O modo x-vector permaneceu rápido (RTF mediano ~1,02–1,15 nestes testes), mas o WER do Whisper Base variou muito; sem referência mais adequada e escuta humana, a inteligibilidade/fidelidade do Q4 não está aprovada. Clonagem detalhada mantém o backend oficial. Q4 pode variar em pronúncia/fidelidade e não deve ser selecionado automaticamente sem ouvir. Sem GPU dedicada, quantização agressiva INT4 e modo Turbo são experimentais. Não foram implementadas otimizações de Code Predictor além da quantização; não houve destilação ou remoção de codebooks.

### Atualização — backend Pure C compilado no Windows e benchmark de threads

Após aquela primeira tentativa de compilação falhar, consegui compilar uma cópia
experimental do Pure C em um MSYS2 portátil, sem instalar WSL2 e sem modificar
o repositório do editor. Corrijo a observação anterior: o backend agora foi
compilado e executado nesta máquina Windows, embora dependa do runtime MSYS2 e
de DLLs auxiliares. O binário não é uma distribuição Windows nativa sem runtime.
O fonte e o toolchain continuam fora do Git do produto, em
`BerofelStudio_QwenTurbo_Benchmark_20261119`; o build usou o upstream MIT no
commit `ef339be58a778b062e1c14382347964552eae007` e um ajuste apenas na cópia
externa para headers POSIX e caminho do OpenBLAS.

O teste usou o modelo oficial local `Qwen3-TTS-12Hz-0.6B-Base`, uma referência
autorizada convertida para mono PCM16/24 kHz e um perfil x-vector preparado uma
vez, reutilizado durante as solicitações. A geração foi feita por streaming
HTTP local, modelo mantido carregado, modo `--quant-mixed-cpu` (Talker INT8 e
Code Predictor INT4), seed 42/43/44, sem cache de frases. Cada texto teve três
repetições. O tempo inclui o fluxo de áudio e salvamento WAV; TTFA é o primeiro
chunk de PCM recebido. Resultados válidos da execução limpa:

| Threads | Texto | Parede mediana | Duração de áudio mediana | RTF mediano | TTFA mediano | RSS de pico |
|---:|---|---:|---:|---:|---:|---:|
| 6 | Médio | 10,965 s | 12,24 s | 0,896 | 0,607 s | 3,435 GiB |
| 8 | Médio | 11,224 s | 11,52 s | 0,974 | 0,629 s | 3,499 GiB |
| 6 | Longo | 26,761 s | 26,72 s | 1,002 | 0,730 s | 3,435 GiB |
| 8 | Longo | 25,196 s | 28,00 s | 0,900 | 0,686 s | 3,499 GiB |

O 8-thread foi ~5,8% mais rápido em tempo de parede e RTF no texto longo, mas
ficou ~2,4% mais lento no texto médio; portanto não há vencedor universal. A
configuração de 6 threads permanece a escolha equilibrada para o editor; 8
threads é candidato para síntese longa quando a responsividade do restante do
editor não for prioridade. O modelo/perfil já estavam carregados nesses
números. O processo Pure C levou ~2,8 s para inicializar e usar ~3,33 GiB RSS;
em contraste, o adaptador Q4 integrado mediu ~0,80 s de carga, ~2,69 s até o
primeiro chunk e ~6,80 s totais para a frase curta. Assim, iniciar o novo
servidor não melhora a primeira reprodução de uma sessão; o benefício possível
é em solicitações seguintes e textos longos.

O percentual de CPU não foi coletado com amostragem independente nesta rodada;
não infiro utilização a partir do número de threads. Pico de RSS foi lido do
processo servidor após as solicitações.

#### Medição de CPU e ajuste de threads (frase curta, 19/11/2026)

Para complementar o ensaio anterior, `scripts/benchmark_qwen3_purec_cpu.py`
inicia o servidor por configuração e amostra CPU/RSS do processo a cada 100 ms.
O script não salva áudio e não transmite dados. Foram feitas três gerações com
texto, seed (42), perfil x-vector, modelo residente e quantização mixed CPU
iguais. O modelo carregou a frio em cada servidor; o tempo de geração e TTFA
abaixo são para as solicitações subsequentes, sem esse carregamento. CPU média
é percentual da capacidade agregada de 16 processadores lógicos; pico de CPU é
percentual equivalente a um núcleo (pode exceder 100%).

| Threads | Carga inicial do modelo | Áudio | Parede mediana | RTF mediano | Primeiro chunk | CPU média total | RSS pico |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 2 | 2,77 s | 11,92 s | 16,172 s | 1,357 | 0,634 s | 22,3% | 3,44 GiB |
| 4 | 2,86 s | 11,92 s | 10,519 s | 0,882 | 0,567 s | 38,9% | 3,44 GiB |
| 6 | 2,71 s | 11,92 s | 9,026 s | 0,757 | 0,544 s | 53,1% | 3,44 GiB |
| 8 | 2,43 s | 11,92 s | 9,925 s | 0,833 | 0,627 s | 66,6% | 3,44 GiB |

Nesta frase curta, 6 threads venceram: cerca de 9,4% menos tempo que 8 threads
e 14,2% menos que 4 threads. O resultado é compatível com a recomendação de 6
threads para uso geral; 8 threads consumiram mais CPU e foram mais lentas neste
ensaio. O teste anterior com textos médios/longos teve variação e indicou que
8 threads pode favorecer algumas sínteses longas. Portanto, manter 6 como
padrão equilibrado é mais sustentado pelos dados atuais; a opção de 8 threads
continua útil para benchmark por projeto, sem garantia de aceleração.

O JSON bruto com as três medições por configuração foi guardado fora do Git em
`C:\Users\Berofel\Desktop\BerofelStudio_QwenTurbo_Benchmark_20261119\purec_cpu_threads_20261119.json`.
Reproduza com `python scripts/benchmark_qwen3_purec_cpu.py --exe <qwen_tts.exe>
--model <Qwen3-Base-local> --voice <x-vector-autorizado.bin> --threads 2 4 6 8
--repeats 3 --output <relatorio.json>`. A execução requer `psutil` e `numpy`
no Python do benchmark e o runtime DLL do Pure C. Não inclui CPU de outros
processos ou atraso de áudio físico do dispositivo.

#### Comparação controlada de precisão (6 threads)

O mesmo script foi estendido para `float` (sem flag de quantização), `int8`
(`--int8`) e `mixed-cpu` (`--quant-mixed-cpu`). Foram feitas três repetições
com modelo/perfil carregados, mesma frase portuguesa e seed 42. O servidor foi
reiniciado entre modos. Uma amostra WAV por modo e o JSON completo foram salvos
na pasta externa de benchmark, sem incluir gravações no Git.

| Modo | Carga do servidor | Parede mediana | Áudio mediano | RTF | Primeiro chunk | CPU média total | Pico RSS |
|---|---:|---:|---:|---:|---:|---:|---:|
| Float | 2,92 s | 13,90 s | 10,32 s | 1,347 | 0,662 s | 47,3% | 2,97 GiB |
| INT8 | 2,80 s | 8,88 s | 10,96 s | 0,810 | 0,559 s | 53,1% | 3,49 GiB |
| Mixed CPU (Talker INT8 + Code Predictor INT4) | 2,69 s | 8,72 s | 11,92 s | 0,731 | 0,537 s | 52,5% | 3,44 GiB |

Contra float, INT8 reduziu a parede em 36,1%; mixed CPU reduziu-a em 37,3%
e atingiu RTF abaixo de 1. Mixed CPU foi 1,8% mais rápido que INT8 nesta
amostra, com saída 0,96 s mais longa. Isso torna mixed CPU o mais rápido deste
ensaio, mas a diferença contra INT8 é pequena e pode variar por texto/seed.
Nenhum modo atingiu geração de 10 segundos de áudio em poucos segundos com o
modelo frio; esses tempos medem geração quente após a carga inicial.

Como verificação automática grosseira, Faster-Whisper Base/int8 local, beam 1,
transcreveu os mesmos 3 WAVs com WER 0,077 para cada configuração (um erro de
palavra sobre 13). Float e INT8 produziram “Berofel Stúdio”; mixed omitiu um
“e” e reconheceu “Studios”. Os WAVs não tiveram clipping (pico PCM: float 4.728,
INT8 4.156, mixed 3.396 numa escala de 32.767). O teste é curto, o ASR erra e
não mede semelhança da voz, naturalidade ou qualidade subjetiva. Ouvir as
amostras é necessário antes de aprovar a configuração Turbo. Os arquivos são
`samples_6threads\float_j6.wav`, `int8_j6.wav`, `mixed-cpu_j6.wav`, em
`C:\Users\Berofel\Desktop\BerofelStudio_QwenTurbo_Benchmark_20261119`.

Comando para repetir os modos e salvar amostras fora do repositório:
`python scripts/benchmark_qwen3_purec_cpu.py --exe <qwen_tts.exe> --model
<Qwen3-Base-local> --voice <x-vector-autorizado.bin> --threads 6
--quantizations float int8 mixed-cpu --repeats 3 --output <relatorio.json>
--samples-dir <pasta-local-privada>`.

Como proxy de inteligibilidade, Faster-Whisper Base/int8 local (beam 1) deu
WER mediano j6/j8 de 0,00/0,069 nos textos médios e 0,00/0,00 nos longos,
sem clipping detectado. O conjunto é pequeno e o ASR pode errar segmentação;
isso não mede naturalidade, semelhança vocal ou qualidade percebida. Uma rodada
curta adicional mostrou WER mediano de 0,071 para INT8 e mixed CPU, contra 0,071
em BF16; o ganho de velocidade não provocou piora mensurável nesse indicador,
mas a duração gerada mudou entre precisões. WAVs comparáveis e manifestos com
as transcrições ficam fora do Git na pasta de benchmark para escuta local.

#### Integração experimental no Berofel Studio

O Pure C foi conectado ao serviço canônico de narração por meio dos backends
opt-in `qwen3-tts-purec-mixed` (Turbo) e `qwen3-tts-purec-int8` (Equilibrado);
o modelo Original permanece padrão e o Q4 existente continua selecionável como fallback. O seletor só oferece Pure C se
encontrar o executável e os pesos Base locais. O perfil de voz é um x-vector
privado em cache, preparado uma vez e reutilizado; a síntese usa o servidor
HTTP local em processo oculto, e envia PCM incremental ao player Qt. Como o
servidor upstream carrega um único x-vector na inicialização, trocar de perfil
reinicia o servidor/modelo; fechar o editor encerra o worker. Alterar o texto
não refaz a preparação do perfil. O modo Pure C não exige transcrição de
referência porque usa somente o x-vector; a rota Original continua aceitando a
transcrição de referência.

O adaptador está em `berofel/services/qwen3_purec_tts.py`, roteado por
`narration_service.py`, exposto condicionalmente em `narration_panel.py` e
integrado ao fluxo da janela, streaming, inserção na timeline e encerramento do
worker. Não foi adicionado pacote Python. A build experimental local e suas
DLLs foram instaladas em `%LOCALAPPDATA%\BFS\qwen3_tts\purec\bin`; o modelo
existente em `%LOCALAPPDATA%\BFS\qwen3_tts\model` é reutilizado sem cópia ou
alteração. O PATH global não foi editado. Avisos de licença estão na pasta
`%LOCALAPPDATA%\BFS\qwen3_tts\purec\licenses`.

Validação real pela janela Qt em modo offscreen, usando perfil autorizado,
interface de narração, execução em worker, inserção do WAV na timeline e
exportação: um caso gerou clipe de 6,24 s; exportou WAV de 6,24 s e MP4 de
6,24 s, ambos com áudio, e o MP4 também com vídeo. Uma rodada de integração
anterior mediu, para voz temporária diferente e 8 threads, perfil 1,85 s,
carga do modelo 2,13 s, geração 3,39 s para 4,56 s de voz e primeiro PCM em
0,477 s após a requisição. O teste usa execução silenciosa de áudio do host; a
rota de streaming foi exercitada, mas a qualidade ainda requer escuta humana.

O runtime MSYS2/OpenBLAS instalado é apenas local para este experimento e não
foi copiado para o repositório. `ldd` confirmou dependências fora do Windows
padrão: `msys-2.0.dll`, GCC runtime, OpenBLAS, OpenMP e WinPthreads. Apesar dos
avisos copiados, ainda não existe instalador público que valide e empacote os
componentes/termos aplicáveis; não distribua esse runtime com releases antes de
completar essa revisão. A versão testada do editor detecta automaticamente o
backend no próximo início. A instância antiga já aberta continua carregando a
versão anterior até ser fechada e reiniciada.

#### Vinculação do servidor local

Na inspeção final do servidor, foi identificado que o padrão upstream vinculava
o listener HTTP a `INADDR_ANY`, o que poderia expor a API de clonagem/síntese à
rede local. A cópia experimental do fonte foi corrigida para vincular somente
`127.0.0.1`; o executável local foi recompilado e substituído. O SHA-256 da
build no diretório de benchmark e do executável instalado em
`%LOCALAPPDATA%\BFS\qwen3_tts\purec\bin\qwen_tts.exe` confere:
`3A5F89D923BFDBEA29327BD4111ECD651AFA3EF448B2643B6EA8AD63DD907D13`.
O listener foi iniciado em porta de teste e `Get-NetTCPConnection` confirmou
`127.0.0.1:<porta>`, sem bind wildcard. O patch de fonte está em
`patches/qwen3_purec_loopback.patch` para reproduzir a alteração sobre o commit
upstream registrado acima. O binário local é experimental e não distribuído.

Depois da substituição, o teste Qt real foi repetido com os caminhos padrão do
editor e modo offline: narração gerada de 7,04 s, WAV e MP4 com 7,04 s, áudio
presente em ambos e vídeo presente no MP4. O teste não realizou avaliação
auditiva. A checagem automatizada completa e a revisão de licença do runtime
redistribuível ainda são necessárias antes de qualquer release.

Também acrescentei uma checagem de bind ao teste de integração real do serviço:
ele inspeciona as conexões do processo servidor e falha se o listener não for
exatamente `127.0.0.1`. Ela passou tanto para Turbo mixed quanto para INT8, com
`HF_HUB_OFFLINE=1` e `TRANSFORMERS_OFFLINE=1`. Em execuções separadas do serviço,
mixed gerou 4,08 s de áudio em 3,377 s, com primeiro PCM em 0,513 s; INT8 gerou
4,24 s em 3,732 s, com primeiro PCM em 0,533 s. Esses tempos de geração não
incluem os ~1,95 s de preparo do x-vector nem os ~2,6–2,7 s de carga do modelo.
Isso confirma que o servidor HTTP não é acessível pela interface de rede, mas
não equivale a bloquear toda a rede do Windows; o teste de rede bloqueada no
sistema operacional continua pendente.

O Pure C declara MIT; OpenBLAS usa BSD-3-Clause ([documentação oficial](https://www.openmathlib.org/OpenBLAS/docs/)); o pacote `msys2-runtime` declara GPL-3.0-or-later ([manifesto upstream](https://github.com/msys2/MSYS2-packages/blob/master/msys2-runtime/PKGBUILD)); e as bibliotecas GCC só recebem a exceção de runtime onde o arquivo aplicável traz o aviso correspondente ([GCC Runtime Library Exception](https://www.gnu.org/licenses/gcc-exception-3.1.html)). O executável e DLLs foram copiados para o diretório local de runtime do usuário apenas para validação. A distribuição pública continua bloqueada até auditar avisos e obrigações de cada DLL exata.

A auditoria por DLL, versão de pacote, SPDX e SHA-256 está em
[`PUREC_WINDOWS_RUNTIME_LICENSE_AUDIT.md`](PUREC_WINDOWS_RUNTIME_LICENSE_AUDIT.md).
O build local importa `msys-2.0.dll` (GPL-3.0-or-later); por isso nenhum
bundle público é liberado. A tentativa MinGW sem MSYS runtime falhou em APIs
POSIX ausentes e não substituiu o executável validado.

Para rollback de código: `git switch feat/qwen3-base-optimized` ou checkout de `backup/qwen3-0.6b-stable`. Para rollback integral, restaure a pasta externa; o bundle Git sozinho não contém dados de voz/modelos. O backend original não foi alterado nem removido.

Na validação posterior, ambos os modos Pure C foram selecionados dentro do
editor offline, geraram áudio, foram inseridos na timeline e exportados em WAV
e MP4 com as faixas esperadas. O modo INT8 usa `--int8`; alternar entre ele e
Turbo reinicia o servidor para aplicar a precisão correta. Original continua
selecionado por padrão até o usuário escolher explicitamente um modo
experimental.

### Revalidação do serviço canônico (19/11/2026)

Repeti `PureCRealIntegrationTests.test_real_profile_generation_stream_and_wave_through_canonical_service`
com o Python do venv de produção do instalador, `HF_HUB_OFFLINE=1` e
`TRANSFORMERS_OFFLINE=1`. O teste cria uma cópia temporária da referência
autorizada, prepara o perfil isoladamente, sintetiza texto português inédito,
confere WAV mono 24 kHz não silencioso e verifica que o processo servidor
escuta somente em loopback. Resultados desta repetição:

| Perfil | Duração WAV | Preparação do perfil | Carga do modelo | Síntese | Primeiro PCM | Chunks |
|---|---:|---:|---:|---:|---:|---:|
| Turbo mixed · 6 threads | 4,72 s | 1,953 s | 2,650 s | 3,851 s | 0,510 s | 56 |
| Equilibrado INT8 · 6 threads | 3,92 s | 1,952 s | 2,498 s | 3,494 s | 0,532 s | 46 |

Comandos usados: definir `BEROFEL_RUN_PUREC_TURBO_INTEGRATION=1`, selecionar
`BEROFEL_PUREC_TEST_ENGINE=qwen3-tts-purec-mixed` ou
`qwen3-tts-purec-int8`, e executar o teste acima com
`%LOCALAPPDATA%\BFS\venv\Scripts\python.exe`. Ambos passaram (1 teste por
perfil). O cache do perfil foi intencionalmente isolado e iniciou como miss;
esta repetição mede a preparação, não o caso de reutilização. Permanecem
válidas as medições anteriores de cache hit e exportação Qt descritas acima.

Também ampliei o teste para duas frases inéditas sequenciais no mesmo processo,
com o mesmo perfil autorizado e o cache isolado. Na primeira solicitação o
x-vector foi preparado e o servidor carregou o modelo; na segunda, o teste
exigiu `profile_cache_hit=true`, `profile_prepare_seconds=0`,
`model_load_seconds=0` e o mesmo PID do servidor. Resultados observados:

| Perfil | Solicitação | Síntese | Duração | Primeiro PCM | Preparação | Carga do modelo |
|---|---:|---:|---:|---:|---:|---:|
| Turbo mixed · 6 threads | 1ª, cache frio | 3,229 s | 3,92 s | 0,523 s | 1,953 s | 3,643 s |
| Turbo mixed · 6 threads | 2ª, texto novo | 3,723 s | 4,72 s | 0,505 s | 0 s | 0 s |
| Equilibrado INT8 · 6 threads | 1ª, cache frio | 4,474 s | 5,20 s | 0,532 s | 1,954 s | 2,428 s |
| Equilibrado INT8 · 6 threads | 2ª, texto novo | 4,128 s | 4,80 s | 0,523 s | 0 s | 0 s |

Esta execução revelou e corrigiu a telemetria de servidor residente: o
adaptador antes repetia o tempo da carga inicial nas chamadas seguintes. Agora
o campo representa a carga incremental desta solicitação; a carga ocorrida
durante a primeira preparação continua associada à primeira geração. São duas
amostras por modo, úteis para confirmar cache/modelo persistente, não para
declarar latência típica nem qualidade acústica geral.

Depois da alteração, repeti também o fluxo Qt completo com Turbo mixed e
projeto temporário, em execução offline: a janela gerou a narração, inseriu o
clipe na timeline e exportou WAV e MP4. O clipe e os dois arquivos exportados
mediram 5,20 s; ambos continham áudio e o MP4 também continha vídeo. Comando:
`BEROFEL_RUN_PUREC_GUI_INTEGRATION=1`,
`BEROFEL_PUREC_TEST_ENGINE=qwen3-tts-purec-mixed`, modo Qt offscreen e o teste
`PureCEditorIntegrationTests.test_editor_generates_and_inserts_purec_clip`.
O teste passou em 11,185 s. Os artefatos ficaram no diretório temporário do
teste; nenhum áudio ou projeto de usuário foi alterado.

### A/B controlado entre os três backends locais

Usei o mesmo perfil autorizado, a mesma frase inédita em português e seis
threads para comparar CHE3MZ Q4, Pure C mixed (Talker INT8/Code Predictor INT4)
e Pure C INT8. Cada configuração recebeu uma frase de aquecimento; depois
foram feitas três sínteses novas sem cache de WAV, mantendo cada servidor ativo
durante seu bloco. O callback PCM do editor mediu a chegada do primeiro chunk.
O script automatizado está em `scripts/benchmark_qwen3_turbo_backends.py`.

| Backend | Síntese mediana | RTF mediano (intervalo) | Primeiro PCM mediano (intervalo) | Pico CPU da máquina | Pico RSS do processo do motor |
|---|---:|---:|---:|---:|---:|
| CHE3MZ Q4 Turbo · 6 threads | 17,158 s | 1,110 (1,094–1,141) | 5,928 s (5,51–6,61) | 43,3% | 2,761 GiB |
| Pure C mixed Turbo · 6 threads | 10,136 s | 0,756 (0,750–0,760) | 0,599 s (0,596–0,600) | 81,0% | 3,513 GiB |
| Pure C INT8 Equilibrado · 6 threads | 11,116 s | 0,832 (0,828–0,839) | 0,622 s (0,617–0,633) | 79,9% | 3,557 GiB |

Na rodada de aquecimento, antes das três medições quentes, o primeiro uso
mediu: CHE3MZ — perfil 6,948 s, modelo 0,794 s, parede total 23,222 s; Pure C
mixed — perfil 1,964 s, modelo 2,698 s, parede total 16,609 s; Pure C INT8 —
perfil já em cache (0 s), modelo 2,958 s, parede total 14,881 s. Os tempos de
síntese quente excluem preparação e carga; a parede da primeira solicitação
inclui essas etapas.

Como proxy de inteligibilidade, transcrevi as mesmas nove saídas com
Faster-Whisper Base/int8, quatro threads, português e beam 1: WER mediano
CHE3MZ 0,200; Pure C mixed 0,167; Pure C INT8 0,067. O INT8 ficou cerca de 10%
mais lento que mixed, mas teve WER inferior nesta frase. O conjunto é pequeno,
contém termos raros (nome do produto/modelo) e não mede naturalidade, timbre ou
fidelidade de voz; não há avaliação auditiva cega. Todos os WAVs eram mono
PCM16/24 kHz, RMS acima de 0,02 e sem clipping detectado. Amostras e JSONs
locais, fora do Git: `C:\Users\Berofel\Desktop\BerofelStudio_QwenTurbo_Benchmark_20261119\ab_same_text_cpu_delta`.

Conclusão limitada a este Ryzen 7 5700G: **Pure C mixed é a opção de menor
latência comprovada**, com primeiro PCM próximo de 0,6 s e RTF ~0,76. **INT8 é
uma alternativa equilibrada**, cerca de 10% mais lenta, com menor erro de
transcrição nesta única frase. Escolha final de qualidade ainda requer ouvir
as amostras; o Qwen oficial Original continua preservado para clonagem
detalhada e fallback. O pico CPU/RSS foi amostrado a cada 100 ms durante cada
pedido e não representa a carga total do Windows nem toda a sessão.

#### Revalidação dos dois modos no editor (19/11/2026)

Após a comparação acima, repeti separadamente o fluxo Qt com o modo INT8
selecionado e a geração real do serviço canônico. A execução foi offline
(`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`), com a referência autorizada
local, e incluiu criar o WAV, inserir o bloco na timeline e exportar WAV e MP4.

| Modo | Duração do bloco/WAV | Duração MP4 | Faixas verificadas |
|---|---:|---:|---|
| Pure C INT8 no editor | 4,24 s | 4,24 s | áudio no WAV e no MP4; vídeo no MP4 |

Na repetição do serviço com caches isolados, INT8 preparou o perfil em 1,952 s,
carregou o modelo em 2,557 s e gerou 4,08 s de áudio em 3,623 s (primeiro PCM
em 0,533 s desde o pedido). Uma segunda frase inédita no mesmo processo teve
cache do perfil, carga incremental do modelo e preparo de perfil iguais a zero;
gerou 4,56 s em 3,954 s e entregou o primeiro PCM em 0,523 s. Esses dois
pedidos verificam persistência/reuso, mas não constituem benchmark de mediana.

Reprodução: `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`,
`BEROFEL_RUN_PUREC_GUI_INTEGRATION=1`,
`BEROFEL_PUREC_TEST_ENGINE=qwen3-tts-purec-int8` e
`python -m unittest discover -s tests -p test_qwen3_purec_tts.py -v`.
Para a repetição do serviço, definir também
`BEROFEL_RUN_PUREC_TURBO_INTEGRATION=1` e desligar a variável de GUI. Ambos os
testes foram executados com o Python instalado em
`%LOCALAPPDATA%\BFS\venv\Scripts\python.exe`. Qt rodou offscreen; o teste
confirma o caminho de reprodução/player e a inserção, mas não prova som nos
alto-falantes. Continua necessária a avaliação auditiva do usuário.

#### Pré-carga do Turbo ao selecionar uma voz (19/11/2026)

O painel agora inicia o preparo em segundo plano quando o usuário seleciona
explicitamente um perfil salvo autorizado junto com um dos modos Pure C. A
restauração automática das preferências ao abrir o editor não dispara carga de
modelo; perfis temporários não salvos nem vozes sem autorização também não são
pré-carregados. A tarefa usa a fila já existente, deixando a timeline e a
edição manual disponíveis enquanto trabalha. Ao clicar em Gerar após o preparo,
o serviço reutiliza o mesmo servidor e o mesmo x-vector.

O primeiro teste de interface real revelou que a função de pré-preparo Pure C
recebia `control` e `stage` duplicados pela camada `Task`. O encaminhamento foi
corrigido para deixar a fila fornecer esses parâmetros uma única vez. A
revalidação no Qt offline selecionou o perfil salvo, aguardou o preparo e
gerou uma frase inédita pelo botão normal de Narração:

| Modo | Pré-carga na seleção | Primeira geração depois do preparo | Primeiro PCM | Perfil/modelo recarregados |
|---|---:|---:|---:|---|
| Turbo mixed | 4,830 s (uma execução, cache isolado) | 5,129 s para WAV de 6,48 s | 0,531 s desde Gerar | não: 0 s / 0 s, mesmo PID |
| INT8 | 4,725 s (uma execução, cache isolado) | 4,968 s para WAV de 5,76 s | 0,549 s desde Gerar | não: 0 s / 0 s, mesmo PID |

Esta medição mostra a latência deslocada para o período em que o usuário está
escolhendo a voz/escrevendo o texto; não elimina o custo total de inicializar
modelo e perfil, nem representa mediana. Reprodução: variáveis
`BEROFEL_RUN_PUREC_GUI_INTEGRATION=1`,
`BEROFEL_PUREC_TEST_ENGINE=qwen3-tts-purec-mixed`,
`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, depois
`python -m unittest tests.test_qwen3_purec_tts.PureCEditorIntegrationTests.test_user_selecting_saved_profile_prewarms_server_before_first_generation -v`.

Depois da correção do encaminhamento, a suíte completa do editor passou com
integrações reais offline ativas: **320 testes passaram, 1 foi ignorado**.
Incluiu a geração pela interface, inserção na timeline, exportação WAV/MP4 e
prewarm Turbo mixed. O prewarm INT8 também passou pelo teste de interface real
separado. Estes testes Qt são offscreen e não certificam saída nos alto-falantes.

#### Auditoria isolada do upstream v0.23.0 e INT4 no Base 0.6B (19/11/2026)

Uma reavaliação da versão upstream `v0.23.0` (`e391ec5467b0218eeb175f4888ad65b259d1e7c7`)
encontrou quantização INT4 disponível para o Base 0.6B. Compilei essa revisão
em um clone temporário fora do repositório do editor, usando o MSYS2 portátil
já existente. A compilação exigiu incluir caminhos OpenBLAS e declarações GNU
explicitamente; o executável depende de `msys-2.0.dll` e DLLs OpenBLAS. Portanto,
isso valida um experimento local, não um pacote nativo autossuficiente nem um
runtime aprovado para distribuição. O upstream ainda classifica Windows como
beta via WSL2 em seu guia de build.

O binário passou `--self-test` e informou AVX2 no Ryzen, com Q4 AVX2 disponível
para os kernels de lote. Fiz uma comparação exploratória com a mesma frase em
português e o mesmo perfil autorizado, salvo como `.qvoice` pelo próprio
backend. As execuções após o preparo carregaram o mesmo perfil reutilizável;
foram uma amostra por modo, não uma mediana. O modelo foi o único Qwen Base
0.6B local. O Faster-Whisper Base/int8 offline foi usado só como proxy de
inteligibilidade; WER é calculado por distância de edição em palavras e não
substitui audição humana. Correção: os números de WER originalmente anotados
na primeira execução usaram o sinal de 24 kHz como se fosse 16 kHz. Eles foram
descartados e recalculados após reamostrar corretamente o WAV para 16 kHz.

| Perfil v0.23 | Síntese reportada | Áudio | RTF | TTFA | WER proxy | Observação |
|---|---:|---:|---:|---:|---:|---|
| Original FP32 | 17,4 s | 11,20 s | 1,56 | 2,275 s | 0,167 | Modelo carregou em 0,431 s; sem amostra PCM no limite |
| INT8 | 12,3 s | 11,68 s | 1,05 | 1,683 s | 0,167 | WAV íntegro; sem amostra PCM no limite |
| Misto (`--quant-mixed-cpu`) | 11,1 s | 11,36 s | 0,98 | 1,663 s | 0,500 | WAV íntegro; sem amostra PCM no limite |
| INT4, amostra livre | 47,1 s | 47,52 s | 0,99 | 1,624 s | 1,933 | Whisper produziu 60 palavras, com repetições; 517 amostras PCM no limite |
| INT4, `--seed 42` | 24,5 s | 26,56 s | 0,92 | 1,638 s | 0,967 | Whisper reconheceu 3 palavras; sem amostra PCM no limite |

O INT4 tem primeira resposta semelhante, mas EOS/duração e inteligibilidade
variaram muito entre estas duas amostras e ficaram muito piores que FP32/INT8.
Não é uma opção utilizável com base nesta evidência. O modo misto deste build
também ficou abaixo da qualidade proxy do INT8 e da configuração atual Pure C
Turbo já integrada. Assim, **nenhuma variante v0.23 foi promovida**: manter os
backends atuais `Pure C mixed` (Turbo) e `Pure C INT8` (Equilibrado), com
backend oficial Original como fallback. Os resultados do build novo não devem
ser confundidos com o benchmark anterior do Pure C já integrado; são versões
e caminhos de compilação distintos.

Os WAVs A/B e o `.qvoice` experimental foram guardados apenas no diretório de
benchmark fora do Git; o áudio privado original e os perfis do editor não
foram movidos nem alterados. A medição de memória foi apenas observacional
durante o processo INT4 (working set visto em ~3,64 GB), não um pico amostrado
de forma contínua. Não foi medido CPU/RAM para os outros quatro modos neste
ensaio. A avaliação auditiva humana e testes do build v0.23 dentro do editor
continuam pendentes; por isso, a decisão é rejeitar a promoção, não certificar
qualidade perceptiva geral.

#### Escala de threads nos backends integrados (19/11/2026)

O harness agora aceita `--threads 2|4|6|8`, aplica a escolha aos dois
backends configuráveis e registra-a no JSON. O adaptador Pure C também fixa
`OPENBLAS_NUM_THREADS=1`: o servidor Qwen controla seu próprio pool e não deve
herdar um pool OpenBLAS independente configurado para todos os núcleos. Para
cada valor, executei uma preparação/aquecimento e três frases inéditas, com o
mesmo perfil autorizado e o mesmo texto em português, em cache isolado e offline.
CPU é pico do processo/filhos como percentagem da máquina; RSS é o pico desse
processo/árvore. A qualidade proxy usa Faster-Whisper Base/int8 offline, WAV
reamostrado de 24 para 16 kHz, e WER de palavra por distância de edição. São
três repetições de uma única frase, não uma avaliação ampla de pronúncia.

| Backend | Threads | RTF mediano | Primeiro PCM | Pico CPU máquina | Pico RSS | WER mediano (intervalo) |
|---|---:|---:|---:|---:|---:|---:|
| Pure C mixed · Turbo | 2 | 1,194 | 0,892 s | 28,2% | 3,517 GiB | 0,200 (0,167–0,200) |
| Pure C mixed · Turbo | 4 | 0,842 | 0,653 s | 52,5% | 3,515 GiB | 0,167 (0,100–0,200) |
| Pure C mixed · Turbo | 6 | 0,751 | 0,595 s | 77,0% | 3,520 GiB | 0,133 (0,133–0,233) |
| Pure C mixed · Turbo | 8 | **0,712** | **0,572 s** | 96,4% | 3,515 GiB | 0,133 (0,033–0,167) |
| Pure C INT8 · Equilibrado | 2 | 1,251 | 0,889 s | 28,0% | 3,558 GiB | 0,133 (0,100–0,167) |
| Pure C INT8 · Equilibrado | 4 | 0,898 | 0,663 s | 54,9% | 3,567 GiB | 0,067 (0,033–0,067) |
| Pure C INT8 · Equilibrado | 6 | **0,826** | 0,619 s | 81,6% | 3,554 GiB | 0,100 (0,033–0,200) |
| Pure C INT8 · Equilibrado | 8 | 0,838 | 0,595 s | 98,0% | 3,563 GiB | 0,100 (0,067–0,100) |

Turbo mixed escalou até oito threads, com redução de cerca de 5% no RTF frente
a seis, ao custo de ocupar quase toda a CPU medida. INT8 não ganhou velocidade
ao passar de seis para oito e também chegou perto da saturação da máquina.
Por isso, seis threads continuam o padrão recomendado durante edição manual;
o painel de Narração agora permite selecionar 2, 4, 6 ou 8 threads para o modo
Turbo mixed, persiste a escolha entre sessões e informa a configuração usada no
WAV gerado. O usuário pode selecionar oito para acelerar uma geração isolada,
sabendo que resta pouca folga de CPU para outros trabalhos. O teste Qt real em oito threads
gerou, inseriu na timeline e exportou WAV/MP4 com áudio e vídeo, mas não mediu
latência de interação por instrumento externo.

As métricas completas e os WAVs estão apenas nos diretórios locais
`controlled_threads_2`, `controlled_threads_4`, `controlled_threads_6` e
`controlled_threads_8`, fora do Git.

#### Controle de threads de Turbo no painel do editor

O painel de Narração agora expõe 2/4/6/8 threads somente para Pure C mixed.
Seis seguem como padrão recomendado para manter CPU disponível durante edição;
oito é uma escolha explícita para uma geração isolada mais rápida, com aviso de
que o servidor precisa reiniciar quando a configuração muda e que a CPU ficará
quase saturada. A opção é salva nas preferências locais e enviada na solicitação
e no pré-aquecimento do perfil, de forma que o motor efetivamente recebe o mesmo
orçamento selecionado. O resultado exibido inclui o número de threads utilizado.

Validação real em 19/11/2026, offline e com a interface Qt: selecionei Turbo
mixed e 8 threads, gerei a narração, inseri o clipe na timeline e exportei WAV e
MP4. A síntese produziu WAV de 4,96 s; o WAV exportado durou 4,96 s e o MP4
4,9667 s, ambos com áudio; o MP4 também continha vídeo. O servidor já estava
quente e o perfil autorizado teve cache hit. Um teste separado de pré-aquecimento
reportou primeira amostra PCM em 0,493 s e síntese de 5,36 s em 4,04 s. Esses
valores descrevem essas execuções específicas, não garantem latência em toda
frase ou em outra máquina. A suíte offline completa após a integração passou:
326 testes, um ignorado por exigir integração de outro backend, nenhum erro.

Uma consulta direta à DLL OpenBLAS sem o servidor ativo mostrou o padrão de 16
threads. O servidor Qwen, contudo, assume a propriedade do orçamento BLAS e
configura a própria biblioteca para uma thread; a comparação repetida com o
limite explícito no adaptador ficou praticamente igual à execução anterior de
2 threads (Turbo 1,203→1,194 RTF; INT8 1,250→1,251). O limite explícito foi
mantido como proteção contra builds que não apliquem essa política interna.

Após essas mudanças, rodei a suíte completa offline, com as integrações reais
Pure C e Qt habilitadas: **324 testes, 1 ignorado, todos os demais aprovados**.
Também executei fluxos Qt separados com Turbo mixed em 8 threads e INT8 em 6;
ambos geraram a narração, inseriram na timeline e exportaram WAV/MP4 com áudio
e vídeo presentes. No ensaio Turbo/8, WAV e MP4 duraram 6,32/6,33 s; no
INT8/6, 5,52/5,53 s. Qt rodou offscreen, então esses resultados não medem som
nos alto-falantes nem latência visual de interação.

Fontes upstream: [repositório Qwen3-TTS Pure C](https://github.com/gabriele-mastrapasqua/qwen3-tts),
[guia de build](https://github.com/gabriele-mastrapasqua/qwen3-tts/blob/main/docs/building.md)
e [release v0.23.0](https://github.com/gabriele-mastrapasqua/qwen3-tts/releases/tag/v0.23.0).

#### Comparação offline em três durações e proxy de inteligibilidade (19/11/2026)

Ampliei o harness para três roteiros fixos em português (curto: 61 caracteres;
médio: 224; longo: 702), mantendo a mesma referência autorizada, Qwen3 Base
0.6B e seis threads. Cada motor foi aquecido uma vez; depois foram feitas três
inferências inéditas por duração (27 WAVs), com o cache de frases isolado e
limpo antes de cada inferência. O processo ficou offline. A primeira resposta
é o primeiro chunk PCM reportado pelo adaptador; RSS e CPU são picos amostrados
da árvore do processo durante cada chamada. RTF = tempo de síntese/duração WAV.

| Backend · 6 threads | Duração texto | Geração mediana | RTF | Primeiro áudio | Pico RSS mediano | WER Base/int8 mediano (intervalo) |
|---|---:|---:|---:|---:|---:|---:|
| Nativo Q4 | Curto | 6,094 s | 1,120 | 2,398 s | 2,301 GiB | 0,100 (0,100–0,500) |
| Nativo Q4 | Médio | 18,955 s | 1,115 | 6,597 s | 2,304 GiB | 0,128 (0,077–0,154) |
| Nativo Q4 | Longo | 58,963 s | 1,132 | 20,599 s | 2,313 GiB | 0,269 (0,261–0,412) |
| Pure C mixed · Turbo | Curto | 4,414 s | **0,798** | **0,520 s** | 3,489 GiB | **0,000 (0,000–0,100)** |
| Pure C mixed · Turbo | Médio | 12,284 s | **0,764** | **0,623 s** | 3,532 GiB | 0,077 (0,026–0,128) |
| Pure C mixed · Turbo | Longo | 37,521 s | **0,806** | **0,945 s** | 3,570 GiB | 0,076 (0,067–0,101) |
| Pure C INT8 · Equilibrado | Curto | 4,436 s | 0,853 | 0,543 s | 3,535 GiB | 0,000 (0,000–0,000) |
| Pure C INT8 · Equilibrado | Médio | 13,044 s | 0,829 | 0,643 s | 3,564 GiB | **0,051 (0,051–0,077)** |
| Pure C INT8 · Equilibrado | Longo | 38,949 s | 0,874 | 0,981 s | 3,607 GiB | **0,067 (0,050–0,151)** |

Nas frases médias e longas, Turbo mixed foi aproximadamente 5,8% e 3,7% mais
rápido que INT8, respectivamente, mas teve WER ligeiramente maior nesta pequena
amostra. INT8 utilizou cerca de 0,04 GiB a mais de RSS nos textos longos e não
foi o perfil mais rápido. O nativo Q4 usou menos memória, mas foi mais lento e
teve latência inicial e WER muito maiores nos textos longos. Para este Ryzen,
Pure C mixed é a opção de velocidade com qualidade proxy utilizável; INT8 é uma
alternativa ligeiramente melhor neste WER, sem afirmar superioridade acústica.

WER foi calculado por edição de palavras com Faster-Whisper Base/int8 CPU local,
após reamostragem correta de 24 kHz para 16 kHz. Ele detecta algumas omissões e
repetições, mas não mede naturalidade, semelhança da voz nem qualidade percebida.
São três gerações estocásticas de um roteiro por classe e um único perfil; as
variações do roteiro e sotaques não foram exploradas. A avaliação auditiva do
usuário continua necessária. Os resultados brutos e WAVs comparáveis estão
somente em `C:\Users\Berofel\Desktop\BerofelStudio_QwenTurbo_Benchmark_20261119\multi_length_6threads_20261119`;
`results.json` contém tempos e recursos, e `asr_wer_results.json` traz os WERs
e transcrições ASR. Nada disso foi adicionado ao Git.

Reprodução do ensaio: no PowerShell, com o venv de desenvolvimento ativo,
defina `HF_HUB_OFFLINE=1` e `TRANSFORMERS_OFFLINE=1` e execute
`python scripts/benchmark_qwen3_turbo_backends.py --confirm-own-or-authorized-voice --threads 6 --lengths short medium long --repeats 3 --output-dir <pasta-nova-fora-do-repo>`.
O harness requer o modelo e os três runtimes locais já instalados e uma voz
local autorizada. Para a verificação de texto, foi usado Faster-Whisper Base
int8 local e o procedimento de reamostragem 24→16 kHz descrito acima.

#### Sweep comparável de 8 threads (19/11/2026)

Repeti o mesmo benchmark offline, com os mesmos três roteiros e perfil vocal,
três gerações inéditas por tamanho e cache de frases isolado. Os WAVs e JSON
continuam fora do Git em
`C:\Users\Berofel\Desktop\BerofelStudio_QwenTurbo_Benchmark_20261119\multi_length_8threads_20261119`.
O WER foi calculado depois, com Faster-Whisper Base/int8 em CPU e reamostragem
24→16 kHz. Valores são medianas de três amostras; CPU é pico amostrado como
percentual da máquina. A comparação do WER usa o mesmo áudio, modelo de ASR e
procedimento da rodada de 6 threads.

| Backend · 8 threads | Texto | Geração mediana | RTF | Primeiro áudio | Pico CPU | Pico RSS | WER mediano (intervalo) |
|---|---|---:|---:|---:|---:|---:|---:|
| Nativo Q4 | Curto | 6,230 s | 1,153 | 2,454 s | 57,1% | 2,249 GiB | 0,100 (0,100–0,200) |
| Nativo Q4 | Médio | 20,726 s | 1,136 | 7,156 s | 57,5% | 2,252 GiB | 0,205 (0,128–0,205) |
| Nativo Q4 | Longo | 58,563 s | 1,155 | 20,108 s | 58,1% | 2,260 GiB | 0,244 (0,210–0,345) |
| Pure C mixed · Turbo | Curto | **3,903 s** | **0,787** | **0,493 s** | 98,7% | 3,495 GiB | **0,000 (0,000–0,000)** |
| Pure C mixed · Turbo | Médio | 12,375 s | **0,731** | **0,584 s** | 98,3% | 3,523 GiB | 0,077 (0,077–0,077) |
| Pure C mixed · Turbo | Longo | **35,398 s** | **0,774** | **0,860 s** | 101,5% | 3,571 GiB | 0,101 (0,092–0,151) |
| Pure C INT8 · Equilibrado | Curto | **4,117 s** | 0,872 | 0,524 s | 92,3% | 3,540 GiB | 0,000 (0,000–0,000) |
| Pure C INT8 · Equilibrado | Médio | 12,963 s | 0,845 | 0,620 s | 101,9% | 3,570 GiB | **0,051 (0,051–0,103)** |
| Pure C INT8 · Equilibrado | Longo | 38,888 s | 0,890 | 0,934 s | 96,9% | 3,608 GiB | **0,118 (0,076–0,126)** |

Em relação à rodada de 6 threads, Pure C mixed/8 reduziu o tempo de geração
mediano em 11,6% no texto curto e 5,7% no longo; no médio ficou 0,7% mais
lento. O primeiro chunk chegou 5–9% antes nas três classes. O RTF variou também
porque a duração sintetizada estocástica não foi idêntica. INT8/8 reduziu o
tempo bruto em 7,2% no curto, 0,6% no médio e 0,2% no longo, enquanto seus
RTFs foram ligeiramente piores que em 6 threads. O pico de RSS permaneceu
próximo ao de 6 threads.

Conclusão operacional: 8 threads é a opção mais rápida observada para Turbo
em textos curtos e longos e reduz a latência até a prévia, mas satura quase
toda a CPU medida. Para manter maior espaço de CPU para reprodução e interface,
6 threads continua uma escolha padrão razoável; usuários priorizando velocidade
podem selecionar 8 no painel de Narração. Não há evidência suficiente para
afirmar que uma configuração seja melhor para qualidade vocal: o WER é apenas
um proxy de transcrição, as gerações são estocásticas e a avaliação auditiva
direta ainda não foi feita. O modo Original e o backend oficial continuam
intactos como fallback.

Reprodução da rodada: mesmo comando acima, substituindo `--threads 6` por
`--threads 8` e usando uma pasta de saída vazia. Os arquivos
`results.json` e `asr_wer_results.json` contêm as métricas agregadas; os 27 WAVs
externos são amostras privadas para avaliação auditiva local e não foram
incluídos no repositório.

#### Varredura completa de threads: 2/4/6/8 (19/11/2026)

Para fechar a comparação de thread budget, repeti o mesmo protocolo a 2 e 4
threads. Os resultados de 6 e 8 threads são as rodadas acima. Cada célula de
tempo, RTF, primeiro áudio e WER segue a ordem Curto/Médio/Longo; tempos são
medianas de três WAVs inéditos por classe. RTFs são calculados por WAV antes da
mediana, e não pela divisão de duas medianas. CPU e RSS são os maiores valores
medianos entre as três classes. Os testes foram offline, no mesmo Ryzen 7
5700G/16 GB, com a mesma referência autorizada e Faster-Whisper Base/int8 para
WER. Os 108 WAVs, JSONs detalhados e relatórios ASR ficam fora do Git nas
pastas `multi_length_{2,4,6,8}threads_20261119` dentro de
`C:\Users\Berofel\Desktop\BerofelStudio_QwenTurbo_Benchmark_20261119`.

| Backend / threads | Geração mediana (s) S/M/L | RTF S/M/L | Primeiro áudio (s) S/M/L | Pico CPU | Pico RSS mediano | WER mediano S/M/L |
|---|---|---|---|---:|---:|---|
| Pure C mixed / 2 | 6,754 / 19,993 / 58,890 | 1,250 / 1,227 / 1,256 | 0,756 / 0,953 / 1,559 | 28,7% | 3,555 GiB | 0,000 / 0,077 / 0,076 |
| Pure C mixed / 4 | 4,689 / 12,905 / 41,091 | 0,862 / 0,840 / 0,891 | 0,561 / 0,680 / 1,080 | 56,1% | 3,556 GiB | 0,000 / 0,103 / 0,076 |
| Pure C mixed / 6 | 4,414 / 12,284 / 37,521 | 0,798 / 0,764 / 0,806 | 0,520 / 0,623 / 0,945 | 79,5% | 3,570 GiB | 0,000 / 0,077 / 0,076 |
| Pure C mixed / 8 | 3,903 / 12,375 / 35,398 | 0,787 / 0,731 / 0,774 | 0,493 / 0,584 / 0,860 | 101,5% | 3,571 GiB | 0,000 / 0,077 / 0,101 |
| Pure C INT8 / 2 | 6,373 / 19,786 / 57,620 | 1,306 / 1,248 / 1,297 | 0,762 / 0,945 / 1,563 | 28,8% | 3,612 GiB | 0,000 / 0,051 / 0,067 |
| Pure C INT8 / 4 | 4,931 / 14,001 / 42,549 | 0,939 / 0,898 / 0,943 | 0,560 / 0,691 / 1,095 | 54,8% | 3,615 GiB | 0,000 / 0,051 / 0,118 |
| Pure C INT8 / 6 | 4,436 / 13,044 / 38,949 | 0,853 / 0,829 / 0,874 | 0,543 / 0,643 / 0,981 | 79,7% | 3,607 GiB | 0,000 / 0,051 / 0,067 |
| Pure C INT8 / 8 | 4,117 / 12,963 / 38,888 | 0,872 / 0,845 / 0,890 | 0,524 / 0,620 / 0,934 | 101,9% | 3,608 GiB | 0,000 / 0,051 / 0,118 |
| Nativo Q4 / 2 | 8,849 / 30,971 / 100,721 | 1,809 / 1,796 / 1,835 | 3,498 / 11,024 / 35,370 | 15,8% | 2,358 GiB | 0,100 / 0,154 / 0,261 |
| Nativo Q4 / 4 | 7,000 / 20,662 / 66,424 | 1,182 / 1,187 / 1,209 | 2,652 / 7,040 / 22,488 | 29,3% | 2,334 GiB | 0,200 / 0,256 / 0,151 |
| Nativo Q4 / 6 | 6,094 / 18,955 / 58,963 | 1,120 / 1,115 / 1,132 | 2,398 / 6,597 / 20,599 | 43,8% | 2,313 GiB | 0,100 / 0,128 / 0,269 |
| Nativo Q4 / 8 | 6,230 / 20,726 / 58,563 | 1,153 / 1,136 / 1,155 | 2,454 / 7,156 / 20,108 | 58,1% | 2,260 GiB | 0,100 / 0,205 / 0,244 |

No equipamento avaliado, Pure C mixed é a rota mais rápida em todas as
combinações de texto e threads comparadas. 8 threads ganhou no tempo bruto
curto e longo, mas não no médio; o ganho de 6→8 é pequeno no RTF e leva o pico
amostrado de CPU para aproximadamente toda a capacidade da máquina. Se o
aplicativo estiver sendo usado simultaneamente para reprodução/edição, 6
threads oferece o melhor compromisso observado; em geração isolada e quando
cada segundo importa, selecionar 8 é a escolha mais rápida. Dois threads
reduzem a pressão de CPU, mas deixam o Turbo com RTF 1,23–1,26 nos textos
médio/longos. O nativo Q4 fica mais lento e demora muito mais para entregar o
primeiro áudio, mesmo usando menos RAM; não é recomendado como perfil Turbo
neste computador. INT8 não superou consistentemente mixed em velocidade; seu
WER mediano foi menor em alguns comprimentos, mas as diferenças variam por
amostra e não medem qualidade vocal.

O cálculo de CPU é amostrado por intervalo, pode exceder 100% por variação do
sampling e deve ser tratado como tendência, não telemetria de precisão. Os
testes usaram apenas três sínteses estocásticas por combinação, um perfil e um
roteiro por tamanho. WER não prova naturalidade, identidade, estabilidade ou
qualidade para publicação; ainda falta comparar as amostras por audição humana.
Isso impede declarar um vencedor de qualidade acústica, mas não altera o
resultado de desempenho medido.

Reprodução dos ensaios 2/4: use o comando documentado acima, altere `--threads`
para `2` ou `4` e informe uma nova pasta externa. Os relatórios ASR detalhados
estão junto de `results.json` em cada pasta; nenhuma gravação ou amostra foi
adicionada ao repositório.

#### Fluxo Qwen no MainWindow e responsividade Qt (19/11/2026)

Executei a classe de integração opt-in `PureCEditorIntegrationTests` no
Windows com `QT_QPA_PLATFORM=offscreen`, sem rede e com o perfil local
autorizado. **2 testes reais passaram**: o usuário selecionou perfil/motor,
pré-carregou o modelo, gerou áudio inédito, recebeu chunks PCM no
`NarrationStreamPlayer`, inseriu uma narração na timeline e exportou MP4. A
exportação verificou áudio e vídeo presentes e duração de 5,84 s. No teste de
reutilização, o pré-aquecimento levou 4,703 s; a narração de 7,20 s levou
5,658 s de síntese (RTF 0,786), primeiro chunk em 0,520 s, cache do perfil
atingido e 0 s de nova preparação/carregamento na geração. Estes tempos
dependem da execução e não incluem avaliação por alto-falantes.

Também medi o caminho real `MainWindow.generate_narration_ui` com 8 threads e
o modelo em cache, com timer Qt de 10 ms durante a geração: primeira resposta
de síntese em 0,491 s, percentil 95 do intervalo do timer de 10,43 ms, máximo
23,12 ms e nenhum intervalo acima de 50 ms. Não houve diálogo de erro; o WAV
foi produzido. A plataforma foi offscreen, portanto isso verifica o event loop
e entrega enfileirada dos chunks, não fluidez visual em monitor nem saída em
alto-falantes.

Durante a revisão encontrei que o teste de prewarm instrumentava o serviço com
um `Mock` de assinatura genérica; `Task` inspeciona a assinatura para decidir
quais callbacks encaminhar e, assim, o próprio teste deixava de passar
`audio_chunk` ao trabalho. O teste agora usa uma função instrumentada com a
assinatura preservada, afirma que o primeiro chunk chegou ao player e executa
as configurações Qt em diretório temporário, para não salvar preferências de
teste no perfil real do usuário. A classe de integração foi repetida após a
correção e ambos os testes passaram.

Artefatos de áudio para comparação auditiva local permanecem fora do Git em
`C:\Users\Berofel\Desktop\BerofelStudio_QwenTurbo_Benchmark_20261119\ui_responsiveness_prepared_6_8_20261119`.

#### Instrumentação de etapas no serviço Pure C (19/11/2026)

Adicionei medidas separadas para preparar o payload, aguardar os cabeçalhos HTTP,
ler o fluxo, converter/analisar PCM, entregar callbacks, escrever/fechar o WAV e
substituir atomicamente o arquivo final. O serviço continua expondo também o
tempo do primeiro chunk, geração, preparação do perfil e carregamento do modelo.
O servidor Pure C instalado (v0.23.0) entrega PCM em streaming e health counters,
mas não expõe no contrato HTTP tempos internos separados do Talker, Code Predictor
e decoder. `stream_read_seconds` mede o período de leitura bloqueante, que inclui
a inferência; não deve ser interpretado como perfil interno dos componentes.

A execução real opt-in `test_real_profile_generation_stream_and_wave_through_canonical_service`
passou offline com perfil autorizado: áudio de 4,48 s, geração de 3,692 s
(RTF 0,824), primeiro chunk em 0,512 s e 53 chunks/215.040 bytes. Após o
preparo em cache, uma frase inédita gerou 5,60 s de áudio em 4,421 s; preparação
do perfil e carregamento atribuídos à solicitação ficaram em 0 s e primeiro
chunk em 0,506 s. Nesta execução instrumentada, leitura do stream foi 3,687 s;
escrita WAV 1,46 ms; análise PCM 1,34 ms; conversão float 0,59 ms; callback
0,03 ms; fechamento WAV 0,24 ms e replace 0,41 ms.

Uma nova rodada offline de três WAVs curtos por backend, com 6 threads, confirmou
as medidas no harness integrado. Medianas: CHE3MZ Q4 6,676 s de geração para
5,84 s de áudio (RTF 1,123, primeiro chunk 2,519 s, RSS 2,280 GiB); Pure C
mixed 3,910 s para 4,96 s (RTF 0,788, primeiro chunk 0,521 s, RSS 3,490 GiB);
Pure C INT8 4,377 s para 5,04 s (RTF 0,868, primeiro chunk 0,543 s, RSS
3,545 GiB). No Pure C mixed, medianas por solicitação foram: payload 0,011 ms;
headers 0,574 ms; stream read 3,906 s; WAV write 1,277 ms; análise PCM
1,263 ms; conversão 0,695 ms; callback 0,024 ms; fechamento 0,221 ms;
replace 0,377 ms. Os caminhos de quantização Pure C passaram pelos mesmos
códigos de instrumentação. O caminho Q4 nativo não possui esses campos, daí
valores `null` em seu relatório.

Essas medidas localizam a inferência dentro da leitura do stream como o custo
principal e confirmam que preparação do WAV não é o limitador. Não dividem o
custo entre Talker, Code Predictor e decoder acústico. Essa subdivisão exigiria
instrumentação no runtime nativo e uma nova compilação licenciada; não foi
inventada a partir de tempos observáveis no cliente. O relatório JSON detalhado
e WAVs desta rodada estão fora do Git em
`C:\Users\Berofel\Desktop\BerofelStudio_QwenTurbo_Instrumented_20261119`.
A avaliação auditiva comparativa ainda está pendente e os números de uma rodada
curta não substituem as varreduras multi-comprimento já documentadas.

Reprodução: execute `tests.test_qwen3_purec_tts.PureCRealIntegrationTests.test_real_profile_generation_stream_and_wave_through_canonical_service`
com `BEROFEL_RUN_QWEN3_PUREC_INTEGRATION=1` e o ambiente local offline; para a
rodada controlada use `scripts/benchmark_qwen3_turbo_backends.py` com perfil
autorizado, diretório externo novo, `--threads 6 --lengths short --repeats 3`.

#### Confirmação do endpoint de métricas e capacidades SIMD local (19/11/2026)

Consultei o binário Pure C instalado com `--caps`: runtime x86-64 reporta CPU
`SSE2 AVX AVX2 FMA`; kernels de matvec/atenção, RMS e conversão usam AVX2,
e INT8 usa widen+FMA AVX2 (sem VNNI/AVX-512). O identificador do build diz
`SIMD=portable`, mas a listagem do dispatcher confirma que esse rótulo não
significa execução escalar: AVX2 está presente e selecionado para as formas
indicadas. O pool do CLI single informa 1 thread; o serviço é configurado com
seu pool próprio via `--prefork-threads`.

Também subi o servidor local com `--metrics-port`, gerei uma frase curta e
consultei `/metrics`. O endpoint mostrou somente `qwen_tts_build_info`,
`qwen_tts_metrics_throttled_total`, `qwen_tts_workers` e a nota de que o servidor
single não mantém contadores de requisição. Não há histograma de duração ou
etapas. Assim, além dos campos que cronometramos no cliente, não há telemetria
interna adicional acessível neste build sem instrumentar/recompilar o runtime.
A conclusão sobre limite de observabilidade foi verificada no executável local,
não inferida apenas da documentação upstream.

#### Perfil interno do CLI Pure C: Talker, Code Predictor e decoder (19/11/2026)

O binário local imprime `Prefill`, `Talker step`, `Code Predictor`, `Speech decoder`,
tempo de geração e TTFA no caminho CLI. Isso permite medir as etapas do mesmo
runtime, embora não exponha cada camada do Talker/CP separadamente. Criei
`scripts/benchmark_qwen3_purec_stages.py` para executar o CLI real com perfil
x-vector local autorizado, seeds pareados por repetição, 6 threads, 3 repetições,
textos curtos/médios, WAV validado e captura de log, RAM e CPU. O modelo é
carregado em processo novo a cada amostra; o custo de carregar fica separado do
tempo interno de geração. A rodada offline produziu 12 WAVs em
`C:\Users\Berofel\Desktop\BerofelStudio_QwenTurbo_PureCStages_20261119`.

Medianas registradas pelo CLI (não somar os tempos do decoder como etapas
seriais: ele sobrepõe a geração e só a drenagem final se soma à espera):

| Modo solicitado | Texto | Carregamento | Prefill | Talker | Code Predictor | Decoder total (drenagem) | Geração / RTF | TTFA CLI | RAM pico |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `--quant-mixed-cpu` | Curto | 0,984 s | 0,377 s | 1,088 s | **2,673 s** | 2,525 s (0,228 s) | 4,4 s / **0,83** | 1,261 s | 3,429 GiB |
| `--int8` | Curto | 0,859 s | 0,380 s | 0,889 s | **2,343 s** | 2,162 s (0,210 s) | 3,9 s / 0,90 | 1,310 s | 3,457 GiB |
| `--quant-mixed-cpu` | Médio | 0,972 s | 0,500 s | 4,602 s | **9,032 s** | 8,942 s (0,163 s) | 14,4 s / **0,77** | 1,434 s | 3,456 GiB |
| `--int8` | Médio | 0,855 s | 0,500 s | 4,716 s | **10,264 s** | 9,368 s (0,228 s) | 15,8 s / 0,83 | 1,450 s | 3,505 GiB |

Neste perfil, Code Predictor é o maior dos dois estágios autoregressivos
serializados: aproximadamente 66–73% da soma Talker + Code Predictor. O decoder
leva tempo de parede parecido com o CP, mas executa em paralelo; o dreno final
mediano ficou entre 0,16 e 0,23 s. O mixed teve RTF menor em curto e médio,
embora `--int8` tenha geração bruta mediana mais rápida no curto porque o áudio
resultante também foi menor. São apenas três saídas estocásticas por caso; as
métricas não substituem audição humana.

**Auditoria da precisão nos logs locais:** para `--quant-mixed-cpu`, o processo
imprime `QWEN_CP_PREC=int4` e `Quantizing CP weights to Q4_0`, mas depois a seção
`MODEL SOURCES` diz `CP linear: ... BF16 -> INT8 at load` e a linha de camadas
também mostra `[INT8]`. Consultei a fonte oficial upstream no commit
`e391ec5467b0218eeb175f4888ad65b259d1e7c7`: `qwen_tts_code_predictor.c` usa
`QWEN_CP_PREC` para selecionar e executar `qwen_cp_quantize_q4`; depois restaura
os flags globais do Talker. Os resumos posteriores em `qwen_tts_gguf.c` e na
linha “layers loaded” usam esses flags globais, não o override do CP. Isso
explica as linhas contraditórias como diagnóstico desatualizado, enquanto os
logs explícitos de `QWEN_CP_PREC=int4`/quantização Q4 confirmam o caminho pedido.
O modo `--int8` registra INT8 sem essa divergência. A tag fonte auditada é
[gabriele-mastrapasqua/qwen3-tts v0.23.0](https://github.com/gabriele-mastrapasqua/qwen3-tts/blob/e391ec5467b0218eeb175f4888ad65b259d1e7c7/qwen_tts_code_predictor.c#L436);
o executável instalado não informa seu hash/revisão de fonte (`source_fp=unknown`),
portanto a atribuição exata do binário permanece limitada, embora as mensagens
e o comportamento observado correspondam à lógica dessa versão. O benchmark
preserva as linhas por WAV em `precision_log_lines` para auditoria.

A primeira execução de prova direta (curta) reportou 1,143 s Talker, 2,744 s
Code Predictor, 2,630 s decoder com 0,254 s de drain, 0,386 s prefill, RTF
0,82, 0,925 s carregamento e TTFA de 1,278 s. Os resultados estão coerentes com
a rodada de três repetições e confirmam que o caminho CLI dá visibilidade
interna que o endpoint HTTP de streaming não oferece. O endpoint server continua
sendo a medição de experiência do editor, com TTFA ~0,5 s nas medições anteriores.

Reproduza com o Python local do editor:

```powershell
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
& "$env:LOCALAPPDATA\BFS\venv\Scripts\python.exe" scripts/benchmark_qwen3_purec_stages.py `
  --confirm-own-or-authorized-voice --threads 6 --lengths short medium --repeats 3 `
  --modes mixed int8 --output-dir "$env:USERPROFILE\Desktop\PureC_Stage_Benchmark"
```

#### Proxy ASR das amostras com perfil interno (19/11/2026)

Para obter um indício automático adicional, transcrevi os mesmos 12 WAVs em cópias
temporárias a 16 kHz com Faster-Whisper Base/int8 local, seis threads e língua
portuguesa. Os WAVs 24 kHz originais não foram alterados. WER mediano (três
repetições; menor é melhor):

| Modo solicitado | Curto (11 palavras) | Médio (43 palavras) |
|---|---:|---:|
| `--quant-mixed-cpu` | 0,091 | 0,047 |
| `--int8` | 0,273 | 0,047 |

No texto médio os modos empataram neste proxy. No texto curto, a variância foi
alta e o número de palavras é pequeno; não há base para eleger a qualidade de
um modo. WER mede apenas erros de transcrição e não avalia naturalidade, timbre,
prosódia ou ruído. O resultado detalhado/transcrições estão em
`C:\Users\Berofel\Desktop\BerofelStudio_QwenTurbo_PureCStages_20261119\asr_wer_results.json`,
fora do Git e sem gravações de referência. A escuta humana continua necessária.

#### Gate para quantização sub-4 do Code Predictor

A fonte v0.23 tem `QWEN_CP_Q2_FFN`, mas a auditoria do código mostra que a
variável só é consultada dentro de `qwen_cp_quantize_q4`; combiná-la com `--int8`
não aplica Q2. Confirmei isso em uma execução de smoke: o log registrou apenas
quantização INT8 e não registrou Q2, portanto o WAV não é uma amostra Q2 e não
entrou nas tabelas. A opção exigiria `--quant-mixed-cpu`/ramo de CP Q4.

Não avancei para essa configuração porque a avaliação de qualidade upstream
v0.23 no Base 0.6B fechou sub-4 com **NO GO**: acordo teacher-forced por
codebook foi 9% no experimento anterior de Q2 FFN híbrido; os candidatos Q2_K/Q2_0
mais recentes chegaram a 4,9%/1,3%, contra 46,3% para Q4_0 e ~79,4% para INT8.
São métricas de códigos do modelo, não WER nem escuta, mas mostram degradação muito
maior do que uma pequena concessão de qualidade. Mantive essa técnica fora da
produção e não consumi tempo de benchmark em um candidato já reprovado pelo gate
de compatibilidade de código acústico. Evidência primária, versão fixada:
[docs/quant-sub4.md no upstream v0.23.0](https://github.com/gabriele-mastrapasqua/qwen3-tts/blob/e391ec5467b0218eeb175f4888ad65b259d1e7c7/docs/quant-sub4.md#L1).

#### Varredura de `QWEN_POOL_SPIN` no Ryzen 7 5700G (19/11/2026)

A fonte upstream documenta `QWEN_POOL_SPIN` como número de ciclos de spin
antes do worker estacionar e alerta que o ótimo depende da CPU. Adicionei a
opção `--pool-spin` ao benchmark interno; sem ela, a variável é removida do
ambiente filho para medir o default do executável. Fiz 3 repetições por valor,
6 threads, perfil autorizado já preparado, seeds repetíveis, Mixed CPU, offline;
curto foi testado com default/0/1024/4096/8192/16384/65536 e médio com
default/1024/4096. A fonte upstream define 4096 em builds x86, e os resultados
de default e 4096 explícito foram praticamente iguais.

| Pool spin | Curto: geração / RTF / TTFA / CP / CPU | Médio: geração / RTF / TTFA / CP / CPU |
|---:|---|---|
| default (x86=4096) | 4,30 s / 0,83 / 1,27 s / 2,58 s / 71,1% | 14,40 s / 0,77 / 1,41 s / 8,99 s / 75,3% |
| 0 | 4,60 s / 0,86 / 1,29 s / 2,74 s / 63,6% | — |
| 1024 | 4,30 s / 0,81 / 1,23 s / 2,56 s / 67,2% | 14,50 s / 0,78 / 1,34 s / 9,11 s / 70,8% |
| 4096 | 4,40 s / 0,83 / 1,25 s / 2,62 s / 70,8% | 14,40 s / 0,77 / 1,38 s / 8,96 s / 73,7% |
| 8192 | 4,50 s / 0,85 / 1,24 s / 2,75 s / 75,3% | — |
| 16384 | 4,70 s / 0,88 / 1,34 s / 2,88 s / 75,3% | — |
| 65536 | 4,50 s / 0,85 / 1,25 s / 2,78 s / 74,4% | — |

Nenhum valor superou o default em ambos os tamanhos. `1024` empatou no curto,
mas ficou 0,1 s mais lento no médio; TTFA foi marginalmente menor e CPU/RSS
não mostraram ganho prático para edição. Valores 0, 16384 e 65536 foram mais
lentos no curto. Recomendação: conservar o default do runtime (4096 neste x86)
e não expor outro controle no editor. WAVs, logs e JSONs por repetição ficam
fora do Git em `C:\Users\Berofel\Desktop\BerofelStudio_QwenTurbo_PoolSpin_20261119`
e `C:\Users\Berofel\Desktop\BerofelStudio_QwenTurbo_PoolSpinMedium_20261119`.

#### A/B de `OPENBLAS_NUM_THREADS` no serviço HTTP do editor (19/11/2026)

A recomendação upstream para builds capazes de controlar OpenBLAS é deixar
`OPENBLAS_NUM_THREADS` ausente, para que o motor dimensione o BLAS. O executável
Windows deste ambiente, porém, reporta `blas=claimed but no thread control` e
`openblas threads now -1`; não confirma que o símbolo de controle/consulta BLAS
esteja disponível. Avaliei o caminho HTTP canônico com o mesmo adaptador e
modelo, perfil preparado, 6 threads, Pure C mixed, três frases curtas e três
médias inéditas por condição, cache de narração isolado e resultados externos.
A única mudança no experimento temporário foi retirar a variável do ambiente do
processo em vez de fixá-la em 1; nenhum código de produto ou configuração global
foi alterado.

| OPENBLAS_NUM_THREADS | Geração curta | RTF curto | Primeiro áudio curto | Geração média | RTF médio | Primeiro áudio médio |
|---|---:|---:|---:|---:|---:|---:|
| `1` (política do editor) | 4,636 s | 0,783 | 0,535 s | 14,150 s | 0,754 | 0,644 s |
| ausente (`engine_default`) | 4,941 s | 0,779 | **0,508 s** | 14,380 s | 0,749 | 0,643 s |

A remoção antecipou o primeiro chunk curto em 27 ms, praticamente empatou no
médio e não melhorou a geração total; os RTFs diferem menos de 0,005. Saídas
estocásticas tiveram durações distintas, então geração total e RTF não apontam
um vencedor confiável com apenas três repetições. As medições CLI independentes
também não mostraram ganho total consistente para 1, 2, 4 ou ambiente ausente.
Como este build não confirma controle de threads pelo próprio motor, mantive a
política do editor em uma thread para evitar risco de uma equipe BLAS sem limite
sobrepor-se ao pool CPU. O resultado não justifica mudar o backend produtivo.

Amostras HTTP e relatório estão fora do Git em
`C:\Users\Berofel\Desktop\BerofelStudio_QwenTurbo_ServerOpenBLAS_20261119\results.json`.
A fonte upstream documenta a política de ownership e a condição de ausência da
variável para builds com controle efetivo em
[feature-flags.md v0.23.0](https://github.com/gabriele-mastrapasqua/qwen3-tts/blob/e391ec5467b0218eeb175f4888ad65b259d1e7c7/docs/feature-flags.md#L248).

#### Medição longa no serviço canônico (19/11/2026)

Para responder à comparação entre duração falada e tempo de geração, usei o
serviço de narração Pure C mixed, com seis threads, modelo já carregado e perfil
autorizado já preparado. Três WAVs inéditos, gerados a partir do mesmo roteiro
de 226 palavras, tiveram duração mediana de 81,84 s e levaram 71,219 s para
sintetizar (RTF 0,872); o primeiro áudio ficou disponível em 1,444 s. Portanto,
nesse modo aquecido a síntese foi cerca de 13% mais rápida que a reprodução,
mas ainda próxima de tempo real. O roteiro produziu 82 s, não 60 s exatos.

Essa rodada específica tinha `offline: false`; ela comprova o caminho real do
serviço e a reutilização de modelo/perfil em cache, mas não deve ser citada como
validação offline. Os testes de integração offline descritos acima são a
evidência separada para essa condição. O backend Original continua sendo o
padrão inicial e sua medição anterior foi muito mais lenta (10,16 s de áudio em
52,78 s, RTF 5,195). Na auditoria das preferências atuais do editor, o modo
salvo era `qwen3-tts-purec-mixed`, com seis threads, e `is_ready()` confirmou
que o runtime Pure C estava disponível. Essa preferência é local e pode mudar
quando o usuário troca o backend.

Os WAVs e o relatório da rodada longa permanecem fora do Git em
`C:\Users\Berofel\Desktop\BerofelStudio_QwenTurbo_OneMinute_20261119_210207`.

Repeti os dois testes `PureCEditorIntegrationTests` na branch experimental com
`BEROFEL_RUN_PUREC_GUI_INTEGRATION=1`, `QT_QPA_PLATFORM=offscreen` e os modos
offline do Hugging Face ativos; ambos passaram. O teste de edição gerou WAV de
5,12 s, colocou o clipe na timeline e exportou MP4 com vídeo e áudio presentes
(5,133 s). O teste de prewarm gerou 6,16 s em 4,875 s (RTF 0,791), com primeiro
chunk em 0,523 s, cache vocal atingido e 0 s de carregamento/preparo atribuídos
à geração; o prewarm inicial levou 4,676 s. A execução foi offscreen, sem
validação visual em monitor ou escuta física. Saída integral do teste: dois
testes passaram em 20,555 s.

#### Amostras A/B Original e Turbo para escuta (19/11/2026)

Gerei amostras inéditas pelo serviço canônico com o mesmo texto em português e
o mesmo perfil local autorizado, sob `HF_HUB_OFFLINE=1` e
`TRANSFORMERS_OFFLINE=1`. O perfil Original usa referência/transcrição; o Pure C
usa o x-vector preparado para esse perfil. A amostragem interna dos backends
não compartilha uma seed configurável pelo contrato do editor, então isto
compara a experiência geral e inteligibilidade, mas não isola somente a
quantização.

| Amostra | Duração | Geração | RTF | Inicialização do motor | Integridade WAV |
|---|---:|---:|---:|---:|---|
| Original, texto de referência salvo inconsistente | 14,88 s | 77,291 s | 5,194 | 48,331 s | mono, 24 kHz, não silencioso |
| Original, transcrição ASR temporária | 7,12 s | 37,716 s | 5,297 | 7,513 s | mono, 24 kHz, não silencioso |
| Turbo Mixed, 6 threads | 6,96 s | 5,480 s | 0,787 | 2,437 s | mono, 24 kHz, não silencioso |

O primeiro par mostrou uma degradação causada pelo texto de referência e não é
uma comparação justa da qualidade do backend Original. As amostras e JSON estão
fora do Git em
`C:\Users\Berofel\Desktop\BerofelStudio_QwenTurbo_ABListen_20261119`.

Como proxy adicional, transcrevi os dois WAVs offline com Faster Whisper
Base/int8 em CPU. O leitor de caminho falhou por incompatibilidade entre
Faster Whisper e PyAV (`metadata_errors`); contornei isso lendo PCM diretamente,
reamostrando de 24 kHz para 16 kHz (taxa esperada pelo array de entrada) e
passando o array ao ASR. Com normalização de caixa e pontuação, o WER foi 1,000
para Original (hipótese repetitiva, “Infus, infus...”) e 0,056 para Turbo Mixed
(uma palavra divergente: “sua” por “soar”). Isso é um alerta forte de possível
falha nessa geração Original, mas a auditoria seguinte mostrou que essa amostra
usara o `ref_text` salvo (18 caracteres), cuja correspondência com a transcrição
ASR da própria referência era ruim (WER proxy 2,667). Portanto, ela não é uma
comparação justa da capacidade do backend Original.

Para controlar isso, gerei uma terceira amostra Original com uma transcrição
ASR da referência, somente para essa chamada e sem atualizar o perfil. O
resultado ficou inteligível: WER 0,056, igual ao Turbo Mixed. O áudio durou
7,12 s e a geração levou 37,716 s (RTF 5,297); o Turbo durou 6,96 s e levou
5,480 s (RTF 0,787). Assim, neste controle, o Turbo foi cerca de 6,8 vezes
mais rápido na síntese, com o proxy de conteúdo empatado. O Original validado
para a escuta A/B é
`comparison_arquivos\narracoes\A_Original_ASR_Reference_20261119_212450_f2db546a.wav`;
o Turbo é o arquivo `B Turbo Mixed_purec_970eb35d.wav` da mesma pasta. O ASR não
avalia naturalidade, timbre ou identidade vocal; a escuta humana ainda é
necessária. A divergência do texto de referência salvo deve ser corrigida no
perfil para o modo Original padrão. O painel agora oferece “Atualizar
transcrição do perfil” para persistir essa correção sem substituir a gravação,
recriar o perfil ou alterar sua autorização. Não alterei o perfil real durante
esta implementação.

Também calculei a similaridade de speaker embedding para o Original corrigido e
o Turbo, comparando ambos com a mesma referência e usando o encoder oficial
Qwen 0.6B Base FP32 como avaliador. Os cossenos foram 0,976927 (Original) e
0,972541 (Turbo). A diferença de 0,004386 é pequena neste proxy e não indica
grande perda de identidade vocal no Turbo, mas embeddings não substituem
avaliação perceptual.

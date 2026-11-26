# Qualidade e benchmark vocal — estado da etapa

O ASR usado no fluxo BVI é **Parakeet TDT v3 ONNX INT8 em CPU**, junto ao Silero VAD local. Faster-Whisper não faz parte desta rota e não foi usado nos resultados abaixo.

## Smoke test local Parakeet em amostra autorizada (26/11/2026)

Foi executada uma chamada nova do adaptador canônico `parakeet_asr.transcribe_file` sobre uma amostra local autorizada de voz do usuário, convertida temporariamente por FFmpeg para PCM16 mono a 16 kHz. O Parakeet reportou `parakeet-tdt-0.6b-v3-int8`, backend `onnxruntime-cpu`, quatro threads, 8,712 s de mídia, 20 palavras agrupadas e um segmento; a chamada de VAD+ASR levou 5,090 s após os imports Python. O diretório temporário foi removido e nem áudio nem texto reconhecido foram incluídos no log ou repositório. Esta é uma execução única; o tempo exclui a conversão FFmpeg e não tem medição de RAM, repetição estatística ou referência textual humana. Confirma que a rota da branch usa Parakeet local, não a precisão do texto nem a qualidade da voz.

## Revisão das janelas escolhidas em referências locais autorizadas (26/11/2026)

O seletor foi chamado para nove amostras autorizadas da pasta local de dublagens; nomes e conteúdo não foram registrados. Os arquivos tinham de 3,947 a 18,207 s. O resultado escolhido foi uma janela de 3 s em sete arquivos, uma janela de 6 s em um e o arquivo inteiro de 8,712 s no restante. Os pontos iniciais retornados incluíram posições posteriores ao início da mídia, consistente com a busca de atividade ao longo do material. A chamada ocorreu com cache persistente existente e não isolado; por isso, seus 5,091 s agregados não são uma medição controlada de uma varredura fria de todos os arquivos. O seletor continua sendo heurístico: esse resultado documenta que janelas curtas são frequentes, mas não demonstra que clonem melhor que janelas mais longas. Nenhuma síntese comparativa ou avaliação auditiva foi feita nesta medição; a calibração de duração e qualidade continua pendente.

### Correção de comparabilidade e repetição com cache de seleção v8

A auditoria encontrou que janelas com menos de quatro segundos não recebiam o resumo acústico, mas ainda podiam ser comparadas a janelas medidas usando subconjuntos diferentes de pesos. O seletor agora mede janelas de pelo menos dois segundos (100 quadros de 20 ms) e, quando há alguma leitura PCM bem-sucedida, compara somente candidatos medidos; se todas falharem, usa explicitamente o ranking VAD anterior. A versão de preparação passou a 8 para invalidar condicionamentos e resultados de seleção antigos.

Após essa invalidação, um processo novo percorreu as mesmas nove amostras: duração de mídia agregada 93,888 s e tempo de parede agregado 4,953 s, incluindo FFprobe/FFmpeg, leitura de identidade e análise de referência, mas excluindo importação/startup do Python. O cache foi invalidado pela mudança para v8; não é comparação controlada com o tempo anterior. O resultado continuou em sete janelas de 3 s, uma de 6 s e uma de 8,712 s. Logo, o defeito de comparação foi corrigido sem deslocar a escolha observada neste conjunto, mas ainda não sabemos se a janela curta preserva melhor a identidade vocal: isso requer sínteses pareadas e avaliação auditiva. Testes da inteligência vocal: 56 passaram; testes locais Qwen: 29 passaram; `compileall` passou. A suíte completa passou após a alteração: 666 testes, 6 ignorados, em 68,987 s.

## Reutilização real do cache de verificação Parakeet (26/11/2026)

O inspetor foi executado sobre a amostra de voz CC0 `assets/voices/stuart_bell.wav` (8,454 s), sem alterar o WAV. A primeira checagem carregou e chamou Parakeet TDT v3 ONNX INT8 via `onnxruntime-cpu`, reconhecendo 23 palavras; a segunda, para o mesmo conteúdo, retornou `cache_hit=true` e o mesmo texto reconhecido, mesmo alterando o parâmetro de threads de 4 para 8. O cache temporário foi removido ao fim do processo. O texto ASR não foi registrado neste documento. Esta execução comprova a integração real do cache com o Parakeet instalado, não a precisão do reconhecimento, qualidade vocal ou desempenho em gravações longas. O texto esperado é comparado novamente a cada chamada, fora do cache, e requer validação humana para ser tratado como referência.

## Verificação exploratória de identidade Pure C

Em 25/11/2026, foi gerada uma frase nova com a referência local autorizada, Qwen3-TTS Base Pure C INT8/6 threads e arquivo de saída em diretório temporário. A síntese levou 8,925 s e produziu WAV PCM válido de 5,12 s (245.804 bytes). O botão/manual checker extraiu os x-vectors da referência e saída pelo mesmo backend; a operação levou 10,370 s. O servidor terminou no mesmo perfil, INT8 e seis threads que tinha antes. O arquivo temporário foi removido. O valor do cosseno foi deliberadamente omitido deste relatório versionado para não persistir uma métrica derivada da gravação vocal privada. Esse experimento demonstra que o caminho de cálculo e restauração funciona para um par; não calibra um limiar, não mede MOS, não constitui avaliação auditiva e não permite concluir fidelidade geral. A comparação está marcada `calibrated=false` e nunca aprova/rejeita áudio automaticamente.

A execução inicial apontou que o sandbox podia ler, mas não escrever no cache/log privado do aplicativo. Repeti a medição com ambos redirecionados para uma pasta temporária gravável dentro do workspace; essa pasta foi removida no encerramento. Isso é uma limitação do sandbox de teste, não uma alteração de diretórios privados do aplicativo.

## Roteiro longo em Pure C INT8

Uma execução nova em 25/11/2026 usou 2.804 caracteres/453 palavras em PT-BR, uma referência autorizada, Qwen3-TTS Base Pure C INT8/6 threads e cache vazio para aquele texto. O serviço dividiu o texto em três pedidos respeitando frases/palavras e juntou as partes em um WAV PCM16 mono 24 kHz sem reinferência por cache: síntese total 200,09 s, WAV final 172,08 s/8.259.884 bytes, RTF 1,163. Parakeet TDT v3 ONNX INT8/CPU levou 16,36 s; reconheceu 455 palavras e estimou WER 2,65%/CER 1,22%, com última palavra reconhecida em 172,0799 s e sem aviso de lacuna final. WER/CER são estimativas do Parakeet, não ground truth humano nem avaliação auditiva. O arquivo, perfil vetorial temporário e cache do teste foram removidos. Pico de RAM/CPU não foi coletado, e o WMI do ambiente continua sem permitir confirmar o modelo físico da CPU. É um único ensaio de aproximadamente 2,9 minutos, não um benchmark p50/p95 nem validação de roteiros de 4/10 minutos.

Em outro ensaio inédito, o texto PT-BR tinha 4.861 caracteres/779 palavras e foi gerado sem cache em cinco partes pelo mesmo Pure C INT8/6 threads. O serviço produziu um único WAV contínuo PCM16 mono 24 kHz de 311,36 s (5:11), 14.945.324 bytes, em 371,51 s (6:11), RTF 1,193. A verificação Parakeet TDT v3 ONNX INT8/CPU levou 26,66 s, reconheceu 778 palavras e estimou WER 1,28%/CER 0,50%; a última palavra terminou em 311,36 s e `ending_review=false`. Essas taxas vêm do próprio ASR e não são ground truth ou prova auditiva. Durante a execução, uma captura isolada de `Get-Process` mostrou o processo Qwen com 3.778.101.248 bytes de working set (~3,78 GB decimais / 3,52 GiB); isso não é pico de RAM. Modelo físico/CPU e RAM total não foram confirmados. Áudio, transcrição e vetores temporários foram removidos; não houve autoplay. É um ensaio único, não uma distribuição p50/p95, teste de dez minutos ou avaliação perceptiva.

Ensaio longo adicional em 25/11/2026: 13.458 caracteres/2.021 palavras passaram pelo planejador e foram sintetizados em 12 partes, sem cache, com Pure C INT8/6 threads e referência local autorizada. O serviço entregou um único WAV PCM16 mono 24 kHz de 873,68 s (14:33,68; 41.936.684 bytes) após 1.218,73 s de síntese (20:18,73; RTF 1,395). Parakeet TDT v3 ONNX INT8/CPU levou 82,90 s, reconheceu 2.020 palavras e calculou WER estimado de 0,74%/CER de 0,42%; a última palavra reconhecida terminou em 873,68 s e `ending_review=false`. Como nas outras execuções, essas taxas comparam a saída do modelo ao texto solicitado e não são transcrição humana de referência, prova auditiva ou medida de identidade vocal. A duração excedeu a meta de dez minutos e comprova a montagem de um WAV longo nesta execução; o texto repetitivo do teste não demonstra naturalidade narrativa. Não foram medidos pico de RAM/CPU nem p50/p95, hardware físico não foi confirmado e nenhum ouvinte avaliou a amostra. WAV e caches temporários foram removidos após a coleta; a geração permaneceu sem autoplay.

## Microbenchmark do sumarizador PCM

Em 25/11/2026, no ambiente virtual do aplicativo (Python 3.12, NumPy 2.5.4; identificação física de CPU indisponível), comparei a implementação padrão e a rota NumPy com o mesmo buffer sintético: seno de 145 Hz, 16 kHz, 30 s/480.000 amostras, 20 ms por quadro. Após uma chamada de aquecimento, foram feitas nove medições por rota, alternadas. Medianas: Python puro 0,155741 s; NumPy 0,006898 s; aceleração observada de 22,58×. Ambos calculam os mesmos campos e o teste de regressão compara a saída numérica. É microbenchmark do resumo de PCM apenas: não inclui leitura/decodificação, FFmpeg, Silero, seleção de janela, não mede RAM/CPU do host e não representa ganho equivalente no tempo total de preparação da voz. NumPy continua opcional; a rota Python é mantida como fallback.

## Execução exploratória real — 25/11/2026

### Parakeet em janelas com WAV real autorizado

Após trocar o adaptador de arquivo para leitura por regiões, fiz uma verificação local em uma referência vocal já autorizada: FFmpeg preparou PCM16 mono 16 kHz e `transcribe_file` executou sem spans VAD pré-calculados. Duas execuções isoladas em processos novos, cada uma com janela de 3,0 s e Parakeet TDT v3 INT8 + Silero ONNX em CPU, levaram 6,05 s e 4,64 s, reconheceram seis palavras e retornaram `memory_strategy=streamed_pcm_windows`. Na segunda, medição `psutil` amostrada a cada 25 ms registrou RSS inicial de 63,2 MiB, pico de 766,7 MiB e aumento de 703,5 MiB durante carga+VAD+ASR. São duas amostras exploratórias curtas, não p50/p95 nem comparação com a versão anterior; páginas do modelo possivelmente estavam no cache do sistema operacional na segunda execução. O acesso WMI para confirmar o nome da CPU e RAM física foi negado, portanto não atribuo esses números ao Ryzen 7 5700G. O texto não foi gravado neste relatório. Nenhum Whisper foi chamado.

### Escala em gameplay real — Parakeet TDT v3 ONNX INT8/CPU

Usei o vídeo de gameplay de 1h20 previamente indicado pelo usuário, sem modificar o original. FFmpeg extraiu apenas a faixa de áudio para WAV PCM16 mono 16 kHz temporário. Em cada linha foi iniciado um processo Python novo; Silero usou 1 thread, Parakeet 4 threads e `CPUExecutionProvider`. `vad_asr` inclui a varredura VAD e a inferência, não inclui carregamento dos modelos. RSS foi amostrado a cada 50 ms. Não foi usado Whisper.

| Intervalo | PCM temporário | Extração FFmpeg | Carga VAD | Carga Parakeet | VAD + ASR | Total medido | RTF VAD+ASR | Pico RSS | Blocos VAD | Regiões reconhecidas | Palavras |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 5 min | — | 1,39 s | 0,25 s | 4,31 s | 6,75 s | 12,70 s | 0,0225 | 957,3 MiB | 10 | 23 | 367 |
| 20 min | — | 3,86 s | 0,25 s | 4,30 s | 28,53 s | 36,94 s | 0,0238 | 956,7 MiB | 40 | 108 | 1.565 |
| 1h20 (4.837,85 s) | 147,6 MiB | 9,48 s | 0,25 s | 4,36 s | 90,95 s | 105,05 s | 0,0188 | 963,9 MiB | 162 | 364 | 4.088 |

`Total medido = FFmpeg + carga Silero + carga Parakeet + VAD/ASR`. No cenário completo, o RTF incluindo esses custos foi 0,0217. Os PCM temporários foram apagados automaticamente e o vídeo não foi reescrito. Os tempos vieram de uma execução por tamanho; não são p50/p95, CPU física foi ocultada pelo WMI e não houve comparação com Faster-Whisper nem com a implementação anterior. A contagem de palavras não mede precisão: sem transcrição humana alinhada não há WER/CER válido, e não foi feita avaliação auditiva do texto reconhecido. O teste comprova que a rota streaming concluiu o áudio completo em CPU sem manter o PCM inteiro em RAM; não comprova qualidade da transcrição nem a edição/renderização automática do vídeo.

### Varredura de threads no mesmo recorte real de cinco minutos

Extraí novamente os primeiros 300 s do mesmo vídeo (FFmpeg 0,33 s; Windows provavelmente já mantinha páginas do arquivo em cache). Silero ficou em 1 thread. Para cada configuração, carreguei um modelo Parakeet ONNX INT8 com o número de threads indicado e executei três transcrições completas do mesmo WAV, incluindo a VAD. O modelo foi reutilizado dentro das três repetições e removido antes da configuração seguinte. Cada repetição devolveu 367 palavras e 10 blocos VAD, mas isso não é avaliação de acurácia.

| Threads Parakeet | Carga do modelo | VAD+ASR mediana (n=3) | Máximo observado | RTF mediano | Pico RSS observado |
|---:|---:|---:|---:|---:|---:|
| 2 | 4,281 s | 8,156 s | 8,188 s | 0,02719 | 1.015,0 MiB |
| 4 | 4,407 s | **6,937 s** | 7,094 s | **0,02312** | 1.019,9 MiB |
| 6 | 4,359 s | 7,171 s | 7,282 s | 0,02390 | 1.025,1 MiB |
| 8 | 4,391 s | 7,859 s | 8,047 s | 0,02620 | 1.029,8 MiB |

Quatro threads venceram neste recorte; seis threads ficaram cerca de 3,4% mais lentas na mediana e oito, cerca de 13,3%. Isso sustenta manter o padrão atual de quatro threads do ASR, sem forçar seis ou oito. São somente três repetições em um conteúdo, não uma calibração universal. O p95 não é reportado: com n=3, a implementação nearest-rank o reduziria ao máximo observado. O RSS é do mesmo processo durante configurações sequenciais; arenas ONNX podem permanecer alocadas, portanto não é uma comparação isolada de memória por thread. O nome/contagem de CPU não foi acessível via WMI. Nenhuma configuração foi alterada no produto.

Registro histórico da execução exploratória anterior: o ambiente foi anotado como Ryzen 7 5700G (8C/16T), 16 GB RAM; referência vocal autorizada local de 3 s; síntese Pure C 0.6B, seis threads; um único texto PT-BR curto por backend. Foram usadas saídas WAV novas, sem cache de áudio. A checagem textual dos WAVs foi feita pelo Parakeet TDT v3 ONNX INT8/CPU já instalado. Os arquivos temporários foram removidos após a análise. Na validação longa registrada acima, o WMI negou acesso, então não foi possível confirmar que o host atual corresponde a esse hardware anotado.

| Backend | Tempo total | Duração WAV | RTF total | Inicialização/modelo | Resultado Parakeet |
|---|---:|---:|---:|---:|---|
| Turbo Mixed CPU (`qwen3-tts-purec-mixed`) | 13,07 s | 9,28 s | 1,408 | 2,682 s | WER-like 0,056; CER-like 0,021; lacuna final 0,0 s |
| Equilibrado INT8 (`qwen3-tts-purec-int8`) | 10,94 s | 9,04 s | 1,210 | 2,773 s | WER-like 0,056; CER-like 0,021; lacuna final 0,0 s |

Cada configuração foi executada uma vez, em sequência; a segunda reutilizou o cache do perfil, mas reiniciou o servidor ao trocar precisão. É uma medição exploratória de uma frase curta, não comparação científica nem p50/p95. WER/CER-like vieram do mesmo ASR local e não são ground truth; ambos os resultados exigem revisão auditiva. Não houve avaliação auditiva cega, pontuação de identidade, medição de RAM de pico, nem teste de narração longa. Logo, esses números não demonstram superioridade geral de INT8 sobre Mixed.

Também foi concluída uma chamada real de transcrição de referência via Parakeet CPU + Silero + FFmpeg: trecho selecionado de 3 s, seis palavras reconhecidas, 7,56 s de execução. A interface do adaptador não expõe confiança nessa chamada. Esse teste curto confirma o caminho de execução, não a precisão do ASR em conteúdo geral.

### Investigação de expressividade no Pure C local

Com a mesma referência local autorizada, mesmo texto-alvo, Qwen 0.6B Base, INT8 e seis threads, o binário foi exercitado em duas rotas. A transcrição da janela de referência foi obtida pelo Parakeet TDT v3 ONNX INT8/CPU. O modo CLI `--emo-ref` + `--emo-ref-text` aceitou os argumentos e gravou WAV mono 24 kHz de 4,32 s em 11,564 s (RTF total exploratório 2,677). A baseline CLI sem esses argumentos gravou WAV válido de 4,24 s em 5,222 s (RTF total 1,231). Uma execução por condição, sem escuta; não prova que a interpretação emocional melhorou. O custo sugere carga/condicionamento one-shot e não justifica substituir a rota persistente normal.

Separadamente, duas requisições ao servidor residente usaram seed 42; a segunda incluía `emotion: joy`. Ambas tiveram status HTTP 200, duração 3,76 s e o mesmo SHA-256 (`2fbcd01b5c85a62f…e825f2ed5`). Nesta build instalada o campo não alterou a saída. Não se deve expor emoção neural via API nesta versão como se tivesse efeito. Upstream pode ter evoluído depois da build local; o SHA executável e a incompatibilidade estão registrados em `VOICE_BACKEND_CAPABILITIES.md`.

### Integração experimental do estilo por exemplo — serviço real do editor

Em 25/11/2026, duas chamadas sequenciais ao serviço canônico de narração do editor usaram o perfil vocal autorizado local, o mesmo texto PT-BR, Pure C INT8 e seis threads. A primeira usou a rota padrão; a segunda reiniciou o servidor com `--emo-ref` e `--emo-ref-text`, usando a transcrição já revisada obtida com Parakeet TDT v3 ONNX INT8/CPU. Não houve reprodução automática. Os dois WAVs foram válidos, novos e tiveram hashes diferentes.

| Rota | Tempo de parede | Carga/reinício reportado | Duração WAV | Cache do x-vector |
|---|---:|---:|---:|---|
| Padrão | 8,60 s | 3,222 s | 3,44 s | miss |
| Estilo por exemplo | 19,927 s | 9,670 s | 6,48 s | hit |

É uma única comparação exploratória; o servidor carregado com o exemplo quase dobrou o tempo de parede e gerou WAV mais longo. O hash diferente prova apenas que a configuração alterou a saída. Não prova emoção identificável, naturalidade superior ou identidade preservada. Não houve escuta ou medição de RAM. Por isso, a caixa é opcional, fica desligada por padrão e sua seleção pode tornar a geração substancialmente mais lenta. O encerramento do worker foi feito antes de remover o diretório temporário de cache/log.

O fluxo foi ainda executado pela interface Qt real do editor, em modo offscreen, com um perfil autorizado, INT8 e seis threads. Na repetição mais recente, o WAV final tinha 6,88 s e o teste levou 24,692 s; o painel concluiu sem erros, `server_status()` confirmou `emotion_by_example=true`, e os players de timeline e narração permaneceram parados. Este teste comprova integração funcional e silêncio automático, não a qualidade perceptiva do estilo.

O cache padrão de perfil sob `%LOCALAPPDATA%\\BFS` não era gravável pelo processo Codex sandbox nesta sessão. Para concluir a inferência sem alterar ACLs, os testes apontaram `BEROFEL_QWEN3_PUREC_PROFILE_CACHE` e logs para uma pasta temporária gravável. Isso é uma restrição do processo sandbox, não uma falha observada do aplicativo executado normalmente pelo usuário.

## Procedimento reproduzível para benchmark comparativo

## Procedimento reproduzível pendente

1. Usar o mesmo texto, perfil autorizado, configuração de seis threads, máquina sem carga concorrente e WAV sem cache.
2. Medir separadamente inicialização do worker, preparação do condicionamento, inferência e finalização do WAV com relógio monotônico.
3. Calcular `RTF = tempo total / duração real do WAV`; reportar RTF inferência e RTF completo.
4. Repetir Turbo Mixed CPU e Equilibrado INT8 em ordem alternada; registrar mediana e p95, RAM máxima e tamanho/duração WAV.
5. Para texto, usar Parakeet local para rascunho comparativo, corrigir manualmente a referência e reportar WER/CER. Transcrição automática isolada não é ground truth.
6. Para identidade e naturalidade, comparar clipes com loudness alinhado em teste auditivo cego. Não substituir avaliação humana por similaridade de x-vector.

Os testes unitários do pacote não comprovam qualidade acústica. No primeiro checkpoint histórico, a suíte tinha 590 aprovações e 6 skips. Na revisão mais recente, após a leitura Parakeet por janelas e a inspeção de integridade do WAV, `python -m unittest discover -s tests -q` passou em **599 testes e ignorou 6**, em 66,181 s. Os seis skips permanecem skips e não são contados como aprovados. `pytest` não está instalado no ambiente virtual, então não foi executado nem instalado; o projeto usa a suíte unittest existente. A integração Qt de estilo por exemplo foi exercitada anteriormente em modo offscreen, via `BEROFEL_RUN_PUREC_GUI_INTEGRATION=1`, e passou em 25,930 s, WAV de 7,52 s e reprodução parada. Isso não substitui validação manual da interface gráfica.


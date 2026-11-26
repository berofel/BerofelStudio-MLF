# Berofel Clip Engine — medição com gravação real

Data: 25/11/2026  
Arquivo testado: `Teste Video Minecraft...mp4` (mídia local do usuário; não incluída no repositório).

## Ambiente observado

- Windows x64; AMD Family 25 Model 80, 8 núcleos físicos e 16 lógicos.
- 15,4 GiB de RAM visível, com 8,2 GiB disponíveis antes do teste.
- O nome comercial exato da CPU não ficou acessível ao processo; portanto não afirmo que esta execução foi comprovadamente num Ryzen 7 5700G.
- Parakeet: `nemo-parakeet-tdt-0.6b-v3`, ONNX INT8, `onnx-asr 0.12.0`, `onnxruntime 1.31.1`, `CPUExecutionProvider`; quatro threads de ASR.

## Fluxo e tempos

O vídeo tinha 80,63 min (4.837,9 s), 3,847 GB e faixas de áudio e vídeo segundo FFprobe. Não encontrei transcrição/projeto válido para esta fonte. A execução usou a pipeline existente: extração PCM em nove trechos de 600 s, Silero VAD local e Parakeet TDT v3 INT8/CPU. Nenhum Whisper, Qwen ou serviço remoto foi chamado.

| Etapa | Resultado observado |
|---|---:|
| Extração + VAD + Parakeet | 101,0 s |
| Palavras com timestamps | 4.053 |
| Cache misses da pipeline | 27 (9 extrações, 9 VAD, 9 Parakeet) |
| RTF ponta a ponta ASR/VAD | 0,0209 (101,0 ÷ 4.837,9) |
| Repetição imediata da pipeline | 0,61 s; 27 hits, 0 misses |
| Clip Engine — Equilibrado, perfil Gameplay | 7,781 s |
| Frames acústicos de 20 ms | 241.893 |
| Duração de áudio decodificada pelo Clip Engine | 4.837,9 s, em streaming |
| Candidatos após ranking/diversidade | 10 |
| Miniaturas visuais já em cache | 129 |
| Candidatos com cobertura visual suficiente | 0 |
| RSS no retorno da análise | 48,75 MiB |

O RTF inclui extração, VAD e inferência, e não é somente tempo de inferência do Parakeet. O Clip Engine reutilizou os timestamps produzidos e não fez uma segunda transcrição. A repetição comprovou reutilização das 27 etapas persistidas, sem novas chamadas ao Parakeet.

O RSS de 48,75 MiB é a leitura do processo ao final da análise, não o pico de RAM. Pico, CPU média/p95 e tempo de inferência isolado não foram instrumentados nesta execução. A medição de 7,781 s inclui leitura das features acústicas e ranking; não inclui exportação/renderização.

## Limites da evidência

- O resultado comprova que a pipeline completa de transcrição Parakeet e o Clip Engine processaram esta mídia real no ambiente observado. Não comprova precisão editorial nem adequação dos dez melhores clipes.
- Não havia anotações humanas para Precision@K, Recall ou erro de limites. Os títulos e scores são heurísticos; uma nota alta não significa viralidade.
- A cobertura do cache de thumbnails era insuficiente para os candidatos. O componente visual permaneceu ausente, corretamente; nenhum quadro novo foi extraído.
- Não foi feita revisão auditiva dos dez candidatos, teste de prévia visível, inserção na timeline ou exportação.
- A análise foi não destrutiva. A mídia original não foi alterada. Como o cache padrão do perfil de execução era sem permissão de escrita, os artefatos de teste ficaram sob `%TEMP%\berofel_clip_real_validation`; nenhuma transcrição ou mídia foi adicionada ao Git.

Esta gravação passa a ser uma fixture de medição real, mas a avaliação de qualidade continua pendente de revisão humana dos candidatos e de medições de pico de RAM/CPU.

# Berofel Clip Engine — validação desta execução

Data: 25/11/2026  
Branch: `feat/berofel-clip-engine`  
Base auditada: `3398391` (`feat: add specialized clip editorial profiles`)

## Auditoria funcional

- A branch já integra o Clip Engine à UI, à fila de tarefas, ao preview e à inserção não destrutiva na timeline.
- A transcrição usada é `project.transcripts`, com timestamps absolutos produzidos pelo fluxo Parakeet TDT v3 ONNX INT8/CPU. O serviço de clipagem não importa nem chama o Parakeet; sem palavras persistidas, não cria candidatos por ASR.
- No modo rápido, só lê waveforms visuais completos já armazenados e não decodifica PCM se a waveform faltar. O modo equilibrado faz extração PCM em streaming e cacheia RMS/pico/clipping; o avançado acrescenta TextRank local. A análise visual opcional só acessa miniaturas já em cache.
- O ranking é determinístico e heurístico. A branch identifica perguntas, possíveis respostas, ganchos, mudanças lexicais de tópico, densidade/novidade, desfecho e ritmo; a interface mostra evidências, cobertura, avisos e controles de revisão.
- Não há chamada de Whisper/Faster-Whisper, LLM, embeddings neurais ou serviço remoto no fluxo do Clip Engine.

## Testes

Antes da regressão adicional, a suíte completa executou **627 testes: 621 aprovados e 6 ignorados**, em 67,382 s. Os skips permanecem condicionados a dependências/modelos locais conforme os próprios testes.

Foi acrescentado `test_saved_parakeet_transcript_is_ranked_without_invoking_any_asr`, que passa transcrição persistida, muda o perfil, exige candidatos e verifica que o serviço `parakeet_asr.transcribe_file` não é chamado nem áudio é decodificado. O conjunto focado `test_clipper.py` passou em **24 testes**, em 1,373 s. A suíte completa será repetida após esta alteração.

## Benchmark sintético repetido

Comando:

```powershell
python scripts/benchmark_clip_engine_synthetic.py --lengths 5 20 60 80 120 --repeats 2
```

Fixture de transcrição PT-BR repetitiva, sem mídia real, áudio, vídeo ou Parakeet. Cada célula abaixo é mediana de duas execuções. O pico é o maior aumento de RSS observado por amostragem de 10 ms, limitado ao processo de benchmark.

| Duração | Rápido (s) | Equilibrado (s) | Avançado (s) | Maior RSS amostrado (MiB) |
|---:|---:|---:|---:|---:|
| 5 min | 0,2747 | 0,2732 | 0,2822 | 1,168 |
| 20 min | 1,0962 | 1,0946 | 1,1424 | 3,688 |
| 60 min | 3,3485 | 3,2813 | 3,3995 | 9,246 |
| 80 min | 4,3671 | 4,3868 | 4,5656 | 5,258 |
| 120 min | 6,5725 | 6,5853 | 6,8186 | 10,336 |

O número de candidatos retornados foi sete em todos os cenários; chamadas ao Parakeet e decodificação de áudio foram zero. O modo avançado custou de cerca de 0,01 a 0,25 s a mais nesta fixture. Isso mede escalabilidade do processamento textual sintético, não desempenho ponta a ponta nem precisão editorial.

O relatório real anterior nesta branch documenta um arquivo de 80,63 min: extração/VAD/Parakeet em 101,0 s e Clip Engine equilibrado em 7,781 s; a repetição do pipeline ASR reutilizou 27/27 etapas em 0,61 s. Essa medição e o RSS final reportado não são novas medições desta execução; não havia uma sessão do editor aberta para revisar os candidatos, e o relatório registra que não foram feitas avaliação humana, preview visível ou exportação real.

## Limites ainda abertos

- Não há conjunto de clipes anotado por pessoas nesta execução; Precision@K, Recall, erro de bordas, completude, duplicidade editorial e preferência humana permanecem sem validação.
- Mudanças de RMS ou miniaturas não provam emoção, ação, humor, relevância ou viralidade. A análise visual é mudança de imagem, não reconhecimento semântico.
- O usuário ainda precisa revisar a seleção antes de inserir ou exportar. A validação desta rodada foi automatizada/offscreen; não foi uma sessão gráfica manual.
- As medidas de tempo e memória sintéticas não substituem benchmark end-to-end no Ryzen 7 5700G com os arquivos de mídia reais.

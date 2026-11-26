# Berofel Clip Engine — validação desta execução

Data: 26/11/2026
Branch: `feat/berofel-clip-engine`  
Base auditada: `3398391` (`feat: add specialized clip editorial profiles`)

## Auditoria funcional

- A branch já integra o Clip Engine à UI, à fila de tarefas, ao preview e à inserção não destrutiva na timeline.
- A transcrição usada é `project.transcripts`, com timestamps absolutos produzidos pelo fluxo Parakeet TDT v3 ONNX INT8/CPU. O serviço de clipagem não importa nem chama o Parakeet; sem palavras persistidas, não cria candidatos por ASR.
- No modo rápido, só lê waveforms visuais completos já armazenados e não decodifica PCM se a waveform faltar. O modo equilibrado faz extração PCM em streaming e cacheia RMS/pico/clipping; o avançado acrescenta TextRank local. A análise visual opcional só acessa miniaturas já em cache.
- O ranking é determinístico e heurístico. A branch identifica perguntas, possíveis respostas, ganchos, mudanças lexicais de tópico, densidade/novidade, desfecho e ritmo; a interface mostra evidências, cobertura, avisos e controles de revisão.
- Sem palavras Parakeet persistidas, a análise pode produzir candidatos de revisão a partir de picos relativos de áudio nos modos Equilibrado/Avançado ou de mudanças isoladas em miniaturas pré-existentes com Análise visual. Esses candidatos permanecem sem transcrição e sem rótulo de ação; recebem nota parcial ajustada pela cobertura e aviso de revisão.
- Não há chamada de Whisper/Faster-Whisper, LLM, embeddings neurais ou serviço remoto no fluxo do Clip Engine.

## Testes

Depois da alteração, `python -m unittest discover -s tests -q` executou **633 testes: 627 aprovados e 6 ignorados**, em 67,969 s. Os skips permanecem condicionados a dependências/modelos locais conforme os próprios testes.

Foi acrescentada cobertura para ausência de transcrição: sugestão por burst sintético medido, proxy visual esparso em miniaturas locais, NMS, invalidação do ranking após alteração de thumbnail, ausência de chamada ao Parakeet e apresentação/ajuste temporal no diálogo Qt. `test_clipper.py` passou em **25 testes**, `test_clip_visual_signals.py` em **8 testes** e `test_actions_panel.py` em **89 testes**. `test_saved_parakeet_transcript_is_ranked_without_invoking_any_asr` confirma também que perfil diferente não chama `parakeet_asr.transcribe_file` nem decodifica PCM no modo Rápido.

## Extensão DSP do Clip Engine — 26/11/2026

O modo Equilibrado passou a medir, no mesmo fluxo PCM de 16 kHz/20 ms, fluxo espectral normalizado por magnitude e taxa de cruzamento por zero. A taxa ZCR é armazenada como diagnóstico, sem peso editorial. A novidade espectral mede somente mudança acústica: entra com contribuição máxima pequena (0,20 na dimensão de áudio), não inicia candidatos por conta própria e não afirma detectar emoção, risada, fala ou importância. O modo Rápido continua consumindo apenas a waveform existente. O extrator avançou para v6, invalidando uma vez somente as features PCM antigas sem esse sinal; transcrições Parakeet permanecem compatíveis e não são refeitas.

Teste sintético de mudança de frequência a volume constante confirmou um pico local de fluxo espectral; teste em blocos confirmou paridade com alimentação PCM em uma única peça, e o contrato rejeita NaN/Inf e timestamps fora de ordem. Testes direcionados: `test_clip_audio_signals.py` **20/20**, `test_clipper.py` **27/27** e `test_actions_panel.py` **91/91** (inclui UI Qt offscreen e consulta de miniatura em cache sem solicitar decodificação). Suíte completa final: **649 testes executados, 643 aprovados e 6 ignorados**; `git diff --check` e `compileall` passaram.

Benchmark reproduzível: `python scripts/benchmark_clip_audio_features.py --minutes 5 80 --repeats 1`. A execução desta sessão, em PCM sintético por streaming, teve estes resultados:

| Duração | Referência RMS/pico/clipping | DSP atual | Aumento de tempo | Pico RSS amostrado da referência → DSP |
|---:|---:|---:|---:|---:|
| 5 min | 0,3075 s | 0,4122 s | 0,1047 s | 4,60 → 4,33 MiB |
| 80 min | 4,3335 s | 5,2426 s | 0,9091 s | 29,13 → 11,68 MiB |

Uma repetição por célula não representa p50/p95 nem desempenho em Ryzen específico. O sinal foi gerado sinteticamente e o teste exclui FFmpeg, leitura de disco, ASR, VAD, ranking e qualidade editorial. A queda de memória veio da troca de listas de floats Python por buffers float32 tipados; a pequena diferença de tempo é o custo observado dos FFTs. O script registra separadamente CPU, parede, frames e RSS amostrado.

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
- A busca sem transcrição não consegue distinguir ação relevante de corte de cena, efeito, explosão ou movimento. Resultados desse caminho são apenas pistas para revisão, com cobertura de evidência menor; não são um modo de clipagem sem supervisão.
- O usuário ainda precisa revisar a seleção antes de inserir ou exportar. A validação desta rodada foi automatizada/offscreen; não foi uma sessão gráfica manual.
- As medidas de tempo e memória sintéticas não substituem benchmark end-to-end no Ryzen 7 5700G com os arquivos de mídia reais.
- A pasta mencionada anteriormente em `D:\Edição CapCut\vídeos` não está disponível neste ambiente; nenhum arquivo real adicional foi analisado em 26/11.

## Correção de integração posterior

Na revisão de 26/11 foi encontrada uma divergência entre o serviço e a entrada da UI: `analyze_clips` aceitava transcrição vazia e possuía a rota de eventos, mas `MainWindow.open_clipper` impedia abrir a ferramenta sem palavras salvas. A guarda foi removida para blocos de áudio/vídeo. Sem transcrição, a UI passa a explicar que somente áudio/miniaturas disponíveis podem contribuir e que Parakeet não será executado. O alcance continua sendo de revisão, sem cortes automáticos.

Foi acrescentado um teste Qt de regressão que abre um clipe sem transcrição e verifica o despacho com lista de palavras vazia e zero chamadas a `parakeet_asr.transcribe_file`. Ele passou no ambiente virtual do aplicativo com Qt offscreen. A janela visível do editor não foi operada manualmente nesta sessão. A rota de serviço sem ASR também permanece coberta pelos testes de `test_clipper.py` e `test_clip_visual_signals.py`.

### Revalidação automatizada desta correção

- `python -m unittest discover -s tests -q`: **637 testes executados, 631 aprovados e 6 ignorados**, em 67,822 s. A execução foi feita com o Python do venv do aplicativo, que contém PySide6, NumPy, Pillow e SciPy.
- Testes focados: Clipador **25/25**, sinais de áudio **18/18**, sinais visuais **8/8**, e novo teste Qt de entrada sem transcrição **1/1**.
- Benchmark sintético atual, uma repetição por célula, 5/20/60/80/120 min: Rápido **0,290/1,097/3,290/4,394/6,615 s**; Equilibrado **0,286/1,098/3,298/4,433/6,598 s**; Avançado **0,294/1,143/3,432/4,556/6,856 s**. No caso de 120 min, aumento de RSS amostrado foi 12,6/7,9/8,1 MiB, respectivamente. Cada cenário retornou sete candidatos, zero chamadas Parakeet e zero segundos de áudio decodificado: este benchmark mede somente transcrição sintética e construção/ranking de candidatos, não pipeline real nem qualidade editorial.
- A pasta de mídia mencionada em `D:\Edição CapCut\vídeos` não existe neste ambiente. Não foi possível executar benchmark novo com gravação real nem avaliação humana.

## Reauditoria nesta rodada

Branch atual: `feat/berofel-clip-engine-mmr`. O serviço ativo foi confirmado como `berofel/services/parakeet_asr.py`: `onnx-asr.load_model("nemo-parakeet-tdt-0.6b-v3", quantization="int8")`, `CPUExecutionProvider`, `.with_timestamps()`, entradas WAV PCM16 mono 16 kHz. A rota do Clip Engine recebe palavras persistidas do projeto; `analyze_clips` não importa ou instancia o modelo. A ação opcional separada de completar transcrições chama o pipeline Parakeet já existente, não um segundo reconhecedor.

Nesta rodada foram executados no venv do aplicativo:

- `test_clipper.py`: 27/27 passaram.
- `test_clip_visual_signals.py`: 8/8 passaram.
- `test_long_narration.py`: 8/8 passaram, incluindo preservação dos frames vizinhos ao regenerar um trecho.
- `test_narration_fast_profile_ui.py`: 20/20 passaram em Qt offscreen, incluindo seleção/dispatch da regeneração segmentada.
- `test_clip_audio_signals.py`: 22/22 passaram.
- Suíte completa, executada com `%LOCALAPPDATA%\BFS\venv\Scripts\python.exe -m unittest discover -s tests -q`: **655 testes, OK, 6 ignorados**, em 68,279 s. Um teste negativo de CLI imprimiu a mensagem de argumento inválido esperada e a suíte terminou sem falhas.

O inventário de janelas do Windows não mostrou o BerofelStudio aberto e este checkout não contém um executável compilado para iniciar; não houve nova leitura de mídia real, sessão visível, exportação nem avaliação humana nesta rodada. Os resultados end-to-end e sintéticos citados acima são medições anteriores e não devem ser interpretados como benchmark novo. O F0 não está no ranking do Clip Engine; as features atuais são RMS, pico, clipping, fluxo espectral e ZCR. Sons/ações/emoções não são classificados semanticamente. A pontuação continua uma ordenação editorial heurística e o conjunto humano para Precision@K/Recall ainda não existe nesta validação.

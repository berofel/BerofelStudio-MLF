# Auditoria global de qualidade e experiência — 24/11/2026

## Escopo e limite desta revisão

Inspecionei o HEAD local `6b2f535` da branch `fix/functional-ui-tts-clipper`, a arquitetura em `berofel/core`, `berofel/services`, `berofel/ui`, os fluxos da limpeza, clipador, narração, legendas, timeline, composição/exportação, proxy, cache e recuperação, além dos relatórios e testes já versionados. A árvore estava limpa e a branch acompanhava `origin/fix/functional-ui-tts-clipper`.

Esta é uma auditoria principalmente estática e documental. Ela não equivale a abrir e operar o BerofelStudio numa sessão gráfica com mídia real. A validação registrada anteriormente informa 466 testes aprovados e 5 ignorados; nesta etapa executei somente os testes focados do Clipador: 12 passaram. Não executei a suíte completa. A documentação também deixa pendente a validação auditiva de Qwen/Parakeet, edição prolongada com mídia real, build/instalador limpo e medição real da gravação longa do usuário.

## Síntese

O projeto já tem escolhas arquiteturais valiosas: um modelo canônico de projeto/timeline, edições não destrutivas, cache por identidade do arquivo, workers separados da thread visual, preview/exportação baseados no mesmo grafo FFmpeg e proxies que não substituem a fonte no render final. Essas bases devem ser protegidas.

Os maiores ganhos de qualidade de vida não dependem de acrescentar mais IA. São: consistência entre a prévia e o resultado final, menor custo de desfazer em projetos grandes, gerenciamento previsível de mídia/cache, diagnóstico de tarefa mais observável, fechar a diferença entre nomes de preset e comportamento real, e validação end-to-end com projetos reais.

## Achados confirmados no código

| Prioridade | Achado | Evidência no workspace | Efeito para o usuário |
|---|---|---|---|
| P0 | Presets com nome de animação não fazem animação | `caption_styles.py` define 24 presets. “Palavra por palavra”, “Karaokê” e “Destaque progressivo” são propriedades visuais estáticas; o modelo de clip não contém sincronização/animação de palavras e `_make_title_png` rasteriza todo o texto em um PNG estático. | A expectativa gerada pelo nome não corresponde ao resultado. Renomear como estático ou implementar destaque somente quando houver timestamps reais. |
| P0 | Biblioteca de transições é pequena | `library_panel.py` lista Dissolvência, Slide e Zoom; `Project.transition_overlap` aceita apenas `dissolve`, `slide`, `zoom`. | A área “Transições” existe, mas não oferece uma biblioteca profissional ampla. Documentar e sinalizar claramente os três tipos funcionais; expandir com prévia, duração e undo somente por implementação no compositor. |
| P1 | Histórico de undo armazena cópias integrais do projeto | `MainWindow.snapshot/undo/redo` usa `copy.deepcopy(self.project)` e conserva até 80 snapshots. O projeto pode carregar transcrições, fila de revisão e até 1.000 falas multivozes. | Memória e latência de edição podem crescer com o projeto; a profundidade fixa de 80 operações não representa custo real. A evolução ideal é histórico por comandos/deltas ou snapshots com orçamento de memória e checkpoint periódico. |
| P1 | Recuperação é um snapshot único sobrescrito | `project_recovery.py` mantém `project.berofel.json.autosave`, grava atomicamente e oferece recuperação se for mais novo. O timer visual dispara a cada 120 s. | Existe recuperação básica, mas não histórico navegável nem retenção escalonada. Falha/corrupção ou uma edição ruim posterior pode deixar apenas uma versão de resgate. Adicionar versões rotativas e ação explícita de restaurar como cópia. |
| P1 | Preview usa dois processos FFmpeg por janela | `docs/DECISOES_ARQUITETURAIS.md` registra fluxo separado de vídeo BGRA e áudio PCM, embora ambos usem o mesmo filtergraph. | Pode haver decodificação/composição duplicada e disputa de CPU. Instrumentar tempo de início, dropped frames, buffers, carga por processo e sincronismo antes de trocar a arquitetura; avaliar decoder compartilhado/proxy como experimento, não refatorar às cegas. |
| P1 | Projeto mantém mídia por referências e não há empacotamento/relocação descrito | `Project.save` guarda `media`, clips e timestamps em JSON; o arquivo de projeto não inclui a mídia-fonte. Há localização de arquivos e proxies, mas não encontrei fluxo equivalente a “coletar/arquivar projeto” na auditoria. | Mover pastas entre computadores/discos pode quebrar fontes. Criar “Empacotar projeto” com seleção de mídia usada, cópia opcional, manifesto/hash e verificação de espaço; incluir/excluir proxy/cache separadamente. |
| P1 | Clipador é ranking editorial heurístico e depende de transcrição pronta | `clipper.py` exige palavras/timestamps existentes; cria janelas por stride, sinais acústicos RMS/pico/clipping e regras de gancho/limites. A própria documentação diz que não entende semântica, perguntas/respostas, emoção, tema ou viralidade; usa apenas primeira faixa de áudio e não analisa imagem. | Bom como ferramenta leve de triagem, ainda insuficiente para “melhores momentos” de entrevista/gameplay. Cortes podem ter contexto incompleto, resposta separada da pergunta ou evento visual relevante ignorado. A prioridade deve ser completude textual e diversidade, não LLM gerador. |
| P1 | Contexto de limpeza é Python local; Qwen legado continua em um caminho de fila | O `ActionsPanel` chama `execute_automatic_cleanup`; esse método constrói `EditOptions` e chama `analyze_automatic_cleanup`, com `enable_qwen=False`. `automatic_cleanup.py` combina Silero/Whisper/cache com regras determinísticas. `run_edit_queue`/`execute_edit_queue` conserva uma rota Qwen histórica; a busca de referências não encontrou uma chamada da interface atual para `execute_edit_queue`. | O botão atual das três opções já segue a arquitetura leve desejada. O código legado pode causar confusão de manutenção e divergência de resultados; antes de removê-lo, mapear entradas antigas, testes e compatibilidade de projeto. |
| P2 | Progresso percentual não significa progresso intrínseco do modelo | O painel permite estado indeterminado e cronômetro; em Parakeet, o avanço é por trecho porque o runtime não expõe callback durante inferência. | A UI deve mostrar etapa/atividade e tempo sem sugerir percentuais falsos. Percentual parado não basta para classificar travamento; heartbeat/log/CPU e deadline precisam aparecer como sinais separados. |
| P2 | Atalhos não têm uma central de descoberta completa | A revisão anterior registra guarda de foco para Ctrl+C/V/Z e algumas dicas; janela de consulta/personalização e tooltips completos permaneciam pendentes. O README também descreve atalhos históricos que não coincidem sempre com os comandos atuais. | Usuário precisa reaprender ações e pode encontrar conflito entre menu, toolbar e campo de texto. Um único registry de comandos deve dirigir QAction, menu, botão, tooltip e painel pesquisável. |
| P2 | Fontes de legenda limitadas a famílias fixas e fontes do SO | Painel lista Arial, Calibri, Segoe UI, Verdana e Georgia. O renderizador escolhe arquivos de fonte locais com fallback. | Um projeto pode renderizar diferente em outra máquina, ou cair em fonte genérica. Empacotar apenas fontes com licença compatível ou guardar referência/fallback explícito e alertar quando faltar. |
| P2 | Aspect ratio altera dimensões do projeto, mas precisa de QA visual em vários elementos | `set_project_aspect` salva largura/altura e atualiza o projeto; seleção de modo de enquadramento e margem para legenda deve ser validada com clips, títulos, keyframes e transições reais. | É possível preservar timeline sem garantir composição agradável. O projeto deve distinguir “ajustar”, “preencher/recortar” e enquadramento manual por clip, com undo e preview. |
| P3 | Monólito de UI concentra muita orquestração | `berofel/ui/window.py` tem aproximadamente 4.746 linhas e gerencia seleção, tarefas, projetos, Qwen, edição, legendas, clipador, timeline e exportação. | Correções pequenas aumentam risco de regressão e dificultam testar ações fora do Qt. Extrair controllers por domínio de forma incremental, mantendo contratos e sem reconstruir o editor. |

## Contextualização internacional

As referências globais convergem em alguns fundamentos práticos:

1. **Mídia e projeto são objetos diferentes.** Premiere, Resolve e Kdenlive mantêm referências aos originais, proxies e cache como ativos administrados. Kdenlive documenta bins/tags, proxy por projeto ou por clip, backup e arquivo do projeto; o Resolve oferece cache, proxies e arquivamento seletivo de mídia/cache; Premiere oferece ingest/proxy e versões de Auto Save. Isso sugere priorizar “Localizar mídia”, “Substituir fonte”, “Empacotar/arquivar” e painel de cache, sem duplicar mídia automaticamente.
2. **Proxy, cache de render e cópia otimizada resolvem problemas diferentes.** O Resolve documenta alternativas separadas de proxy, optimized media, timeline proxy e render cache. O Berofel já possui proxy e cache de features; falta uma interface clara para estado, tamanho, invalidação, prioridade e limpeza segura.
3. **Texto deve ser um caminho editorial com timestamps estáveis.** Premiere oferece transcrição textual, correção de transcript e criação de captions com presets/limites de comprimento/linhas. Berofel já guarda transcrição e captions editáveis, mas a oportunidade é melhorar revisão por palavra, navegação texto↔playhead e consistência de timebase sem rerodar ASR.
4. **Recuperação deve ser uma função navegável, não só um arquivo técnico.** Resolve, Premiere e Kdenlive documentam backups/restauração/arquivamento; Berofel tem autosave recuperável, mas ainda pode tornar a recuperação mais explícita e oferecer versões nomeadas.
5. **Interoperabilidade deve ser incremental.** Um formato de troca como OpenTimelineIO pode ser estudado para export/import de estrutura de cortes e metadados, sem substituir o JSON canônico nem prometer compatibilidade de efeitos que não tenham mapeamento.

Referências primárias consultadas:

- Adobe Premiere — [proxies](https://helpx.adobe.com/premiere/desktop/organize-media/ingest-proxy-workflow/create-proxies.html), [Auto Save](https://helpx.adobe.com/premiere/desktop/get-started/preferences-and-settings/auto-save-preferences.html), [captions](https://helpx.adobe.com/premiere/desktop/add-text-images/insert-captions/create-captions.html), [Text-Based Editing](https://helpx.adobe.com/premiere/desktop/edit-projects/edit-video-using-text-based-editing/overview-of-text-based-editing.html).
- Blackmagic Design — [DaVinci Resolve Reference Manual 21.1: proxies/cache](https://documents.blackmagicdesign.com/UserManuals/DaVinciResolveReferenceManual.pdf?_v=1636009211000), [project archive e backups](https://documents.blackmagicdesign.com/UserManuals/DaVinci_Resolve_21.1_Reference_Manual.pdf?_v=1788850810000).
- Kdenlive — [proxies](https://docs.kdenlive.org/en/project_and_asset_management/project_settings/proxy_settings.html), [project files e assets](https://docs.kdenlive.org/en/project_and_asset_management/file_management/project_files.html), [estrutura de diretório/backup](https://docs.kdenlive.org/en/project_and_asset_management/file_management/folder_structure.html), [project archive/bin](https://docs.kdenlive.org/en/project_and_asset_management.html).
- Blender VSE — [proxy media](https://docs.blender.org/manual/en/latest/editors/video_sequencer/sequencer/sidebar/proxy.html).
- Shotcut — [referência oficial de atalhos](https://shotcut.org/howtos/keyboard-shortcuts/).
- OpenTimelineIO — [formato/API de intercâmbio editorial](https://github.com/AcademySoftwareFoundation/OpenTimelineIO/blob/main/docs/index.rst); suporta estrutura/timing/metadata, não incorpora mídia.
- FFmpeg — [documentação de filtergraph e controle de threads](https://ffmpeg.org/ffmpeg.html).

O objetivo não é copiar a quantidade de recursos dos produtos profissionais. É adotar seus padrões de previsibilidade, organização de mídia, feedback e reversibilidade que tenham custo compatível com um editor local leve.

## Roteiro recomendado para elevar qualidade sem pesar a IA

### Fase 1 — Confiabilidade e observabilidade (maior retorno imediato)

- Montar um conjunto de projetos de referência pequeno, real e autorizado: entrevista, gameplay com faixa de microfone separada, gravação sem fala, voz baixa com música, cortes numerosos e várias faixas.
- Instrumentar abrir projeto, importar, seek, play, parar, gerar legenda, gerar narração, gerar proxy e exportar: tempo até primeiro quadro/áudio, tempo total, p50/p95, quadros perdidos, pico RSS, número de processos, cache hit/miss e erro FFmpeg. Mostrar no histórico de processo sem usar porcentagem artificial.
- Criar uma matriz de resultado: esperado visual, esperado auditivo, tempo e comparação com export. Automatizar ffprobe e análise de duração/sincronia; revisão humana para qualidade editorial e voz.

### Fase 2 — Engenharia de recortes contextuais em Python

- Reutilizar a única transcrição por versão e seus timestamps; não passar áudio/transcrição completa para modelo generativo.
- Construir segmentação determinística por pausas, pontuação, turnos, conectivos, pergunta/resposta e fronteiras temáticas aproximadas (TextTiling/TF-IDF em janelas locais).
- Gerar candidatos com início-desenvolvimento-fechamento; penalizar aberturas dependentes (“porque”, “e daí”) e final interrompido; expandir candidato até completar pergunta/resposta sem ultrapassar duração alvo mais que a tolerância.
- Usar pontuação explicável de completude, novidade, densidade e limites naturais. Deduplicar por sobreposição + conteúdo, preservar diversidade de assunto e expor evidência ao usuário.
- Usar regras conservadoras de proteção de números, negação, sujeitos, entidades e locutor. Ambiguidade vira revisão. Não chamar isso de previsão de viralização.
- Testar ablação e precisão/recall em trechos PT-BR anotados. Só inserir MiniLM/ONNX como camada opcional se a avaliação humana provar ganho que compense RAM/latência.

### Fase 3 — Edição cotidiana e desempenho

- Trocar undo por operações/deltas em modelo de domínio, com snapshots de recuperação periódicos e limite de memória; testar Undo/Redo de grupos, clips vinculados, texto, transições e keyframes.
- Tornar projeto portátil: localizar/relink em lote, gerenciar arquivos duplicados, copiar mídia usada, gerar manifesto, validar hash, abrir arquivo compactado em cópia e mostrar espaço necessário.
- Adicionar um gerenciador de proxy/cache com estado por clip, botão proxy/original, tamanho em disco, data, invalidação e limpeza segura. Não apagar fonte nem cache ativo.
- Medir opções de preview: 640/960/1280, proxies, fps, seek, export; manter áudio responsivo e evitar múltiplas inferências pesadas simultâneas.
- Refatorar a janela em controladores pequenos a partir de fronteiras de serviço já existentes. Não iniciar reescrita de UI.

### Fase 4 — Polimento acessível

- Tornar preset estático ou animado explicitamente; não prometer “karaokê” sem alinhamento por palavra real.
- Catálogo de presets com preview fiel ao renderer e fonte disponível/licenciada.
- Central de atalhos e tooltips derivados de registro único, com bloqueio em campos de texto.
- Navegação de transcript/caption por palavra e teclado, seleção legível, foco visível, área de clique suficiente e teste DPI 100/125/150% em janela nativa.

## O que está bem encaminhado e não deve ser perdido

- Projeto canônico separado da UI; JSON com migração v1/v2 e formato atual v3.
- Escrita atômica do projeto e autosave em worker com lock/mtime de proteção.
- Corte não destrutivo e tempos de transcrição mantidos na mídia-fonte.
- Mesmo compositor `export_multitrack` para preview e export, evitando dois resultados visuais divergentes.
- Proxy opcional por fingerprint de origem; exportação usa sempre a fonte original.
- Limpeza dos três controles atual usa `automatic_cleanup.py`, Silero/ASR já existentes, cache e regras Python. Contexto sozinho consulta VAD sem transformar pausa em corte; as sugestões vão à revisão.
- Qwen TTS fica em runtime local separado; os benchmarks documentados não prometem tempo real. Preserve mensagens honestas de desempenho e o fato de gerar não iniciar playback.
- Render do clipador usa PCM streaming e dados em cache; resultados são sugestões manuais, não mudanças destrutivas.

## Limites que impedem uma conclusão funcional total

- Não foi possível observar esta rodada em sessão interativa do BerofelStudio com mídia real; os registros anteriores documentam capturas Qt e testes offscreen, mas não playback/percepção prolongados neste ambiente.
- Sem clips PT-BR humanos anotados, não dá para estimar precisão/recall de Contexto nem comparar com qualidade editorial “antes/depois”. Fixtures determinísticas servem para regressão, não comprovam taxa de acerto humana.
- Não realizei inferência real Qwen, Parakeet CPU/Vulkan, export de projeto do usuário ou build do instalador nesta auditoria.
- Métricas anteriores de Qwen/clipper são específicas dos arquivos e configurações documentados; não representam benchmark da branch atual em novas condições.

## Incrementos aplicados após o estudo

O Clipador ajusta localmente um candidato para manter uma pergunta junto da resposta imediatamente próxima quando os timestamps indicam proximidade e existe uma pista de resposta (“porque”, “a resposta”, entre outras) ou mudança de locutor conhecida. Também pode recuar o início de uma resposta dependente para incluir sua pergunta. A expansão nunca ultrapassa a duração máxima configurada; quando não cabe, o limite original permanece. A lista de turnos é calculada uma vez por varredura, não uma vez por janela. A justificativa aparece junto das razões textuais do candidato.

A seleção de resultados também foi ampliada para evitar gastar vagas com transcrições quase duplicadas que aparecem em janelas temporais diferentes. A comparação remove acentos, ignora uma lista pequena de palavras funcionais PT-BR e só elimina o candidato inferior quando há ao menos cinco termos de conteúdo comuns, cobertura lexical de 92% ou mais e Jaccard de 82% ou mais. Um teste confirma que um candidato com novos detalhes permanece. A versão do clipador foi incrementada para invalidar caches de resultados antigos. Ambas as melhorias usam apenas Python e o texto/timestamps já existentes; não adicionam LLM, embeddings, modelos, APIs ou dependências.

Arquivos alterados nesta etapa: `berofel/services/clipper.py`, `berofel/services/clip_audio_signals.py`, `tests/test_clipper.py`, `tests/test_clip_audio_signals.py` e esta documentação. Resultado: **23 testes focados passaram** (12 de candidatos/limites e 11 de sinais/ranking) e a suíte completa passou com **473 testes aprovados e 5 ignorados** no Python `%LOCALAPPDATA%\\BFS\\venv`; `git diff --check` passou. Os ignorados são testes condicionados a pesos/backend GUI local e corretor VERO não instalado, conforme marcadores dos próprios testes. As fixtures são determinísticas/sintéticas, não gravações humanas, e não demonstram precisão editorial real nem benchmark de desempenho end-to-end.

Microbenchmark isolado da seleção lexical: 600 candidatos sintéticos, 35 termos gerados por candidato, selecionar até 50; 7 execuções em Windows 10, Python 3.12.10, memória reportada pelo sistema 15 GiB; mediana **17,67 ms**, mínimo 17,49 ms, pico rastreado pelo `tracemalloc` **0,26 MiB**. O modelo exato da CPU não pôde ser lido porque a consulta WMI retornou acesso negado. Esse teste mede somente seleção/deduplicação de texto, sem extração FFmpeg, ASR/VAD, Qt, nem avaliação semântica humana; não representa o tempo total do Clipador.

## Recomendação executiva

O próximo incremento deve calibrar completude, deduplicação e diversidade em transcrições humanas rotuladas, e avaliar candidatos com abertura dependente e final interrompido sem cortar automaticamente casos ambíguos. Antes de adicionar modelo semântico, medir se regras locais deixam lacunas editoriais importantes. Em paralelo, o maior débito transversal é reduzir o custo de undo e tornar projeto/cache portáteis e observáveis.


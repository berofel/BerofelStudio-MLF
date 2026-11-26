# Berofel Clip Engine — reranking MMR

Data: 26/11/2026
Branch de trabalho: `feat/berofel-clip-engine-mmr`

## Auditoria confirmada

- ASR existente: `nemo-parakeet-tdt-0.6b-v3`, artefatos ONNX INT8, adaptador `onnx-asr==0.12.0`, `CPUExecutionProvider`, com Silero ONNX local para VAD. A integração do clipador lê as palavras persistidas em `project.transcripts`; `analyze_clips` não carrega nem chama Parakeet. O runtime e o formato foram confirmados em `berofel/services/parakeet_asr.py`, `requirements-ai.txt` e no caminho de integração da janela.
- Cada palavra Parakeet fornece texto, `start`, `end` e `probability=None`; após a conversão do projeto, os tempos são mantidos como segundos absolutos de origem. Não há confiança calibrada nem diarização garantida.
- Modo Rápido usa a waveform visual existente (proxy de pico, 100 ms), quando completa; não inicia nova decodificação se ela faltar. Equilibrado/Avançado calculam PCM mono em streaming com FFmpeg e cacheiam RMS, pico e clipping a cada 20 ms. O Avançado adiciona TextRank lexical local. A opção visual lê miniaturas já existentes em cache.
- TextRank e mudanças de tópico usam somente texto local. Candidatos preservam início/fim de palavras ou segmentos disponíveis, carregam justificativas e cobertura e passam pela revisão; o motor não aplica cortes nem renderiza candidatos automaticamente.

## Mudança implementada

O seletor final agora utiliza uma variante determinística de Maximal Marginal Relevance (MMR):

`utility = 0.75 * relevance - 0.25 * max(similarity_to_selected)`

- `relevance` é o score editorial existente normalizado de 0 a 1.
- A similaridade combina IoU temporal (65%) e cosseno sobre conjuntos esparsos de termos de conteúdo (35%).
- A seleção continua rejeitando contenção temporal acima do limite atual e duplicatas lexicais quase idênticas. Isso preserva os guardrails anteriores; o MMR organiza diversidade entre os candidatos restantes.
- `lambda=0.75` é uma escolha heurística inicial, não calibrada com preferência humana. A entrada inválida de intervalo é ignorada; o parâmetro fora de `[0,1]` produz erro explícito.
- O cache de ranking foi elevado da versão 8 para 9. O cache acústico permanece na versão 5 porque seu formato/extrator não mudou.
- Nenhuma dependência foi adicionada; nada foi copiado de projetos externos.

## Referências e licenças

- TextTiling: Hearst, 1997, segmentação por coesão lexical ([ACL Anthology](https://aclanthology.org/J97-1003/)); o projeto usa uma aproximação local, não copia código.
- TextRank: Mihalcea e Tarau, 2004 ([ACL Anthology](https://aclanthology.org/W04-3252/)); implementação local esparsa e limitada.
- MMR: Carbonell e Goldstein, SIGIR 1998 ([DOI/ACM](https://doi.org/10.1145/290941.291025)); foi adaptado o princípio de relevância + novidade, não o código do paper.
- Auto-Editor usa condições baseadas em áudio/movimento ([repositório](https://github.com/WyattBlue/auto-editor)); PySceneDetect documenta detectores por diferença e histograma e informa BSD-3-Clause ([repositório](https://github.com/Breakthrough/PySceneDetect), [licença](https://github.com/Breakthrough/PySceneDetect/blob/main/LICENSE)). Não são dependências do Clip Engine. A análise visual local atual é só uma mudança de miniatura, sem semântica de cena.
- Os detalhes de ranking de produtos comerciais não são públicos; nenhuma técnica interna foi presumida.

## Validação executada

- `python -m unittest discover -s tests -p test_clip_audio_signals.py -v`: **20/20 passaram**.
- `python -m unittest discover -s tests -p test_clipper.py -v`: **27/27 passaram**.
- `python -m unittest discover -s tests -q`: **648 testes, OK; 6 ignorados** por pré-condições existentes. Uma mensagem de uso do benchmark Qwen aparece por um teste negativo de argumentos; não é falha da suíte.
- `python -m compileall -q` nos dois serviços e no teste alterado: passou.
- `python scripts/benchmark_clip_engine_synthetic.py --lengths 5 20 60 80 120 --repeats 2`: texto PT-BR sintético repetitivo, 2 repetições por modo/duração, sem mídia, áudio, vídeo, Parakeet ou anotações humanas. Medianas de parede:

| Duração | Rápido | Equilibrado | Avançado |
|---:|---:|---:|---:|
| 5 min | 0,282 s | 0,277 s | 0,288 s |
| 20 min | 1,115 s | 1,115 s | 1,155 s |
| 60 min | 3,334 s | 3,350 s | 3,458 s |
| 80 min | 4,453 s | 4,467 s | 4,626 s |
| 120 min | 6,685 s | 6,670 s | 6,931 s |

O maior aumento de RSS amostrado em cada modo no cenário de 120 min foi 13,00 / 6,48 / 5,02 MiB. A amostragem de RSS é aproximada e esses valores incluem todo o motor da fixture; não são pico exato do processo nem memória de pipeline completa. Com apenas duas repetições não se reporta p95. Os resultados mostram escala de processamento sintético, não melhora de qualidade editorial.

## Limites e próximos passos

- Não havia arquivo real adicional ou conjunto humano de momentos relevantes acessível nesta execução. Precision@K, Recall, completude, erro de fronteira, preferência editorial e calibração de `lambda` continuam sem medida.
- Não houve nova sessão da interface gráfica, preview ou exportação real nesta mudança; a seleção MMR afeta somente a ordenação/lista retornada.
- O extrator não calcula F0, fluxo espectral ou risadas; a waveform de 100 ms não contém essas informações. Essas características só devem ser acrescentadas se um benchmark humano mostrar utilidade suficiente para justificar o custo.
- Eventos acústicos ou mudança visual são cues observáveis, não classificação de ação/emoção. Sem palavra cronometrada não significa silêncio.
- O usuário continua revisando candidatos antes da inserção/exportação. Não há alegação de viralidade nem de competitividade equivalente aos produtos comerciais.

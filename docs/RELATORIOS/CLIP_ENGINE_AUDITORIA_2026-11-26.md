# Auditoria e validação do Berofel Clip Engine

Data: 26/11/2026  
Branch: `feat/berofel-clip-engine-mmr`  
ASR local observado: `nemo-parakeet-tdt-0.6b-v3`, ONNX INT8, `onnx-asr 0.12.0`, ONNX Runtime CPU.

## Arquitetura confirmada

- `berofel/services/parakeet_asr.py` usa o Parakeet TDT v3 INT8 pela API local de `onnx-asr`, com `CPUExecutionProvider`. Os timestamps de tokens retornados por essa versão são segundos relativos ao áudio de inferência; o adaptador agrupa tokens em palavras e soma o offset do trecho. Probabilidade/confiança permanece `None` e a resposta não cria diarização.
- `window.open_clipper` entrega ao motor as palavras de `project.transcripts`; `analyze_clips` não carrega nem chama ASR. Se há palavras ausentes, a interface oferece uma ação explícita que usa a rota Parakeet existente apenas nos blocos faltantes.
- A waveform persistida é um proxy de pico, 4 kHz, por amostra de 100 ms em tiles de 60 s. Não equivale a RMS, fluxo espectral, F0 ou VAD. O modo Rápido a consome sem nova decodificação e mantém a evidência identificada como aproximada.
- Equilibrado/Avançado decodificam áudio de forma limitada por streaming com FFmpeg, quadros de 20 ms e cache. TextRank localizado é ativado só no modo Avançado. Recursos visuais consultam miniaturas que já existem, sem pedir extração; pontuação visual ausente permanece indisponível.
- Os candidatos respeitam timestamps de origem, bordas disponíveis de palavra, perfil, contexto local, eventos acústicos e supressão temporal/lexical de redundância. A inserção na timeline é explícita, não destrutiva e reversível. O Clipador não exporta nem renderiza candidatos antes da escolha.

## Alteração desta revisão

Foi acrescentado o controle **Pontuação mínima** (0–100) solicitado no escopo do Clip Engine. Ele filtra o ranking armazenado depois da análise. A nota mínima não é incluída na chave do cache; portanto, ajustar o filtro reutiliza transcrição, features e candidatos previamente calculados. O retorno registra a nota mínima, candidatos visíveis, candidatos antes do filtro e o estado `below_minimum_score` quando nenhum resultado atinge o limite. O valor inicial é zero.

Arquivos alterados: `berofel/services/clipper.py`, `berofel/ui/clipper_dialog.py`, `tests/test_clipper.py`, `tests/test_actions_panel.py`, `docs/CLIPADOR_INTELIGENTE.md` e `CHANGELOG.md`.

## Testes

- Baseline antes da alteração: `python -m unittest discover -s tests -v` executou 662 testes, 6 ignorados, sem falha.
- Após a alteração: `python -m unittest discover -s tests -p 'test_clip*.py' -v` aprovou 64 testes; `python -m unittest discover -s tests -p 'test_actions_panel.py' -q` aprovou 91 testes.
- Suíte completa após a alteração: `python -m unittest discover -s tests -q` aprovou 664 testes, com 6 ignorados, em 68,986 s.
- `compileall` nos módulos e testes alterados passou.
- `pytest` não está instalado no ambiente local `BFS\venv`; a suíte existente foi executada pelo `unittest` que o projeto já usa.
- Testes de widget são executados headless/offscreen e não provam o comportamento da versão compilada nem substituem captura manual da janela.

## Benchmark sintético reproduzível

Arquivo bruto: `CLIP_ENGINE_SYNTHETIC_BENCHMARK_2026-11-26.json`. 45 execuções: 5 durações (5, 20, 60, 80 e 120 min), 3 modos e 3 repetições por combinação. São transcrições PT-BR determinísticas repetitivas. **Não há mídia decodificada, Parakeet, waveform, FFmpeg, vídeo, VAD ou evidência de qualidade editorial.** Tempo inclui segmentação/ranking da fixture. P95 abaixo usa nearest-rank com somente três observações e equivale ao máximo observado; serve como faixa experimental, não estimativa estatística confiável. RSS é aumento máximo amostrado em intervalos de 10 ms.

| Entrada | Modo | Parede p50 (s) | Parede p95¹ (s) | CPU p50 (s) | Maior aumento RSS amostrado (MiB) |
|---:|---|---:|---:|---:|---:|
| 5 min | Rápido | 0,2830 | 0,2953 | 0,2812 | 1,250 |
| 5 min | Equilibrado | 0,2842 | 0,2852 | 0,2812 | 0,137 |
| 5 min | Avançado | 0,2929 | 0,2942 | 0,2969 | 0,094 |
| 20 min | Rápido | 1,1288 | 1,1342 | 1,1250 | 4,180 |
| 20 min | Equilibrado | 1,1355 | 1,1369 | 1,1250 | 1,168 |
| 20 min | Avançado | 1,1766 | 1,1778 | 1,1875 | 1,270 |
| 60 min | Rápido | 3,4145 | 3,4211 | 3,4062 | 11,840 |
| 60 min | Equilibrado | 3,4058 | 3,4331 | 3,4062 | 2,465 |
| 60 min | Avançado | 3,5279 | 3,5286 | 3,5312 | 2,512 |
| 80 min | Rápido | 4,5458 | 4,6836 | 4,5469 | 6,965 |
| 80 min | Equilibrado | 4,5546 | 4,6413 | 4,5781 | 4,312 |
| 80 min | Avançado | 4,7938 | 4,8687 | 4,7812 | 3,418 |
| 120 min | Rápido | 6,9153 | 6,9822 | 6,9062 | 13,656 |
| 120 min | Equilibrado | 6,8424 | 6,8989 | 6,8438 | 4,852 |
| 120 min | Avançado | 7,1892 | 7,2377 | 7,1875 | 4,000 |

¹ P95 baseado em n=3; para robustez, colete mais repetições em condições controladas. Estes números não devem ser comparados a tempo ponta a ponta de um vídeo real.

## Medição real existente e limites

O relatório [CLIP_ENGINE_REAL_BENCHMARK_2026-11-25.md](CLIP_ENGINE_REAL_BENCHMARK_2026-11-25.md) registra uma medição anterior de 80,63 min: extração/VAD/Parakeet em 101,0 s; Clip Engine Equilibrado em 7,781 s; repetição da pipeline ASR em 0,61 s com 27 hits e nenhuma nova inferência. O processo reportou RSS final de 48,75 MiB, não pico. A gravação não possuía rótulos humanos e a cobertura visual era insuficiente. O arquivo não estava acessível neste novo workspace para repetir a revisão dos candidatos.

Não há Precision@K, Recall, erro de limites, completude, taxa de duplicidade humana ou preferência editorial rotulada. As notas são heurísticas explicáveis e não probabilidade de viralidade. A análise visual em cache mede mudança entre imagens 32×18 e não reconhece ações/objetos. O motor não calcula F0, não tem diarização/confiança Parakeet e não descobre semanticamente ação silenciosa. A suíte e o benchmark sintético não eliminam essas limitações.

A [matriz oficial de suporte da NVIDIA](https://docs.nvidia.com/nim/speech/26.10.0/reference/support-matrix/asr.html) lista o idioma português do modelo TDT v3 como `pt-PT`; não lista uma variante `pt-BR`. O adaptador atual usa seleção automática de idioma. Portanto, a qualidade da transcrição em fala brasileira coloquial não é garantida pelo código do Clip Engine e exige revisão humana. Mantivemos o Parakeet configurado pelo projeto sem adicionar fallback ASR.

## Pesquisa, escolha e licenças

- [TextTiling (Hearst, 1997)](https://aclanthology.org/J97-1003/) fundamenta a ideia de coesão lexical local; o código atual usa uma aproximação por vizinhança e turnos.
- [TextRank (Mihalcea & Tarau, 2004)](https://aclanthology.org/W04-3252/) fundamenta ranking esparso de sentenças; a implementação local não reproduz a avaliação científica original.
- [Auto-Editor](https://github.com/WyattBlue/auto-editor) apresenta intervalos e regras declarativas de áudio/movimento; nenhuma cópia foi incorporada.
- [PySceneDetect](https://github.com/Breakthrough/PySceneDetect) tem licença BSD-3-Clause e ferramentas de corte de cena; não foi adicionado como dependência porque o Clip Engine atual consulta somente cache de thumbnails.
- [ClipsAI](https://github.com/ClipsAI/clipsai) é MIT, mas o fluxo documentado inclui WhisperX. O adaptador de ASR e o código não foram importados; a transcrição permanece exclusivamente no Parakeet existente.
- [Claggeta Clipper](https://github.com/Claggeta/clipper) informa licença “to be decided”; excluído da reutilização de código.
- [Klap](https://klap.app/how-it-works) e [OpusClip](https://www.opus.pro/) foram usados apenas como referências públicas de autonomia contextual, explicação do ranking, revisão, legenda, reenquadramento e proporções. Os algoritmos proprietários não são observáveis nem foram inferidos.
- Nenhum pacote, modelo, código de terceiros ou dependência nova foi incluído por esta alteração.

## Estado da validação de interface

Os testes de integração validam o despacho em segundo plano e a montagem do diálogo em modo headless. A tentativa de inspeção visual encontrou dois processos do BerofelStudio (alpha.1 e alpha.4), mas a ferramenta de automação não expôs essas janelas como superfícies controláveis; portanto, o novo controle não foi confirmado por interação gráfica. Também permanecem pendentes captura da versão instalada/compilada, revisão auditiva dos clipes e exportação real. Não foi feita alteração na compilação nesta revisão.

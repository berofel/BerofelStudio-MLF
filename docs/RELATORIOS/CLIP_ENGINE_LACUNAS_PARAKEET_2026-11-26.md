# Clip Engine — eventos em lacunas da transcrição

Data: 26/11/2026  
Branch: `feat/berofel-clip-engine`  
Versão do editor: `0.10.0-alpha.4`

## Causa encontrada

O motor já podia sugerir eventos acústicos/visuais quando não havia transcrição no clipe. Porém, quando a mídia tinha alguma palavra transcrita, os eventos visuais eram calculados somente para o caso de transcrição vazia; eventos de áudio sem alinhamento a palavras também não podiam formar um candidato. Em vídeos com fala e gameplay sem fala, os trechos silenciosos ficavam invisíveis para o ranking complementar.

## Alteração

- Eventos de energia fora dos timestamps de palavras e mudanças em miniaturas já armazenadas agora podem gerar candidatos em lacunas longas da transcrição.
- Os eventos seguem como cues sem classificação semântica e não alteram a nota dos candidatos com fala.
- Uma lacuna significa “não há palavra Parakeet cronometrada aqui”; não comprova que não exista fala, silêncio ou conteúdo relevante.
- A revisão distingue “sem palavras nesta janela” de “sem transcrição no arquivo”.
- Os limites de trim do candidato ficam dentro da lacuna que originou a sugestão.
- A versão do cache de ranking mudou para 8. O cache de features acústicas permaneceu na versão 5, pois a extração de RMS/pico não mudou.
- Não foi adicionada dependência; o Parakeet permanece TDT v3 ONNX INT8/CPU e não é chamado pelo Clip Engine.

## Validação executada

- `tests/test_clipper.py`: 27 testes passaram, incluindo candidatos visuais em lacuna com transcrição existente, ausência de chamada ao Parakeet e trims limitados à lacuna.
- `tests/test_clip_audio_signals.py`: 18 passaram.
- `tests/test_clip_visual_signals.py`: 8 passaram.
- `tests/test_actions_panel.py`: 90 passaram, incluindo a nova verificação do rótulo “Sem palavras do Parakeet nesta janela”.
- `tests/test_clip_engine_evaluator.py`: 4 passaram (matching único, métricas vazias, envelope de cache e timestamp inválido).
- `python -m compileall` nos arquivos alterados passou.
- Suíte completa final (`python -m unittest discover -s tests -q`): 643 testes executados, 637 aprovados e 6 ignorados por pré-condições locais. O texto de uso do benchmark que aparece no log é esperado pelo teste negativo de validação de argumentos.
- Benchmark sintético repetido duas vezes por combinação, entrada com texto determinístico e sem áudio/vídeo real, sem Parakeet e sem decodificação:

| Duração do texto | Rápido mediano | Equilibrado mediano | Avançado mediano | Maior RSS incremental amostrado |
|---:|---:|---:|---:|---:|
| 5 min | 0,29 s | 0,29 s | 0,29 s | 1,28 MiB |
| 20 min | 1,10 s | 1,09 s | 1,14 s | 3,66 MiB |
| 60 min | 3,30 s | 3,31 s | 3,41 s | 9,59 MiB |
| 80 min | 4,39 s | 4,41 s | 4,57 s | 5,45 MiB |
| 120 min | 6,60 s | 6,59 s | 6,85 s | 10,35 MiB |

As medidas de RSS são incrementos amostrados a cada 10 ms no processo do benchmark, não um pico exato. A comparação com a validação anterior sugere que não houve regressão mensurável na escala textual; não é comparação A/B no mesmo checkout nem benchmark ponta a ponta.

## Limitações desta validação

- Os 6 skips da suíte total são condicionais a modelos/recursos locais, conforme os testes.
- A pasta `D:\Edição CapCut\vídeos` mencionada anteriormente não existe neste ambiente. Não foi possível validar se os novos candidatos são editorialmente bons em gameplay real.
- Não há rótulos de clipes anotados por humanos. Precision@K, recall, erro de borda, taxa de duplicidade editorial e preferência humana continuam sem medida.
- O ambiente não tinha janela do editor aberta e não há executável compilado neste checkout; a validação Qt foi automatizada/offscreen, não inspeção visual manual.
- Mudança de energia pode ser efeito do jogo, fala omitida ou ruído; mudança de thumbnail pode ser corte, movimento de câmera ou ruído visual. A revisão manual continua necessária.

## Pesquisa revisada

TextTiling e TextRank são usados somente como princípios/algoritmos locais, não como código copiado. Auto-Editor documenta combinação de sinais de áudio e movimento; PySceneDetect separa detectores de conteúdo, histograma e limiar. O Clipador ainda não instala esses projetos nem executa um detector de cena completo. MomentClip foi lido como exemplo de pipeline por sinais e shortlist, mas suas opções de LLM/ASR não foram incorporadas. Claggeta Clipper não foi reutilizado devido ao estado de licença indicado pelo próprio repositório. Referências e limites estão em `docs/CLIPADOR_INTELIGENTE.md`.

# Clip Engine — seleção global de candidatos

Data: 26/11/2026  
Branch: `feat/berofel-clip-engine-mmr`

## Causa corrigida

O motor calculava MMR e aplicava `max_candidates` dentro do loop de cada bloco da timeline. Ao selecionar vários blocos da mesma mídia, os mesmos tempos de origem podiam ocupar posições em cada resultado local. O limite efetivamente observado na lista final podia, portanto, multiplicar-se pelo número de blocos selecionados.

## Implementação

- Após filtrar a pontuação mínima, o motor reúne os candidatos de todos os blocos e executa uma seleção MMR final limitada a `max_candidates`.
- Cada cache por bloco conserva até 50 itens (teto já permitido pela interface); o limite escolhido pelo usuário é aplicado uma vez globalmente. A versão do cache de ranking avançou para 10; caches de transcrição, waveform e DSP não mudaram.
- A comparação de IoU e contenção temporal só ocorre entre candidatos da mesma origem. Arquivos diferentes podem ter timestamps coincidentes sem representar o mesmo intervalo de mídia.
- Candidatos com texto ainda podem ser considerados redundantes lexicalmente entre origens diferentes; isso é uma heurística intencional de diversidade, não equivalência semântica garantida.
- Os resultados locais continuam cacheados separadamente. A seleção global é uma etapa barata após a leitura do cache e não solicita Parakeet, waveform, PCM ou vídeo.
- Nenhuma mídia é editada ou renderizada. A aprovação e inserção na timeline permanecem explícitas.

## Validação

- `test_clip_audio_signals.py`: 24 testes passaram. Foram adicionadas regressões para intervalos iguais em origens diferentes e sobreposição na mesma origem.
- `test_clipper.py`: 31 testes passaram. Novo teste confirma que blocos duplicados da mesma origem ocupam apenas uma posição quando o limite global é um.
- `python -m unittest discover -s tests -q`: **669 testes executados, OK, 6 ignorados**, em 69,265 s. A mensagem de uso do benchmark Qwen decorre de um teste negativo de argumentos e a suíte terminou com exit code zero.
- `compileall` nos serviços e testes alterados e `git diff --check`: passaram.
- Os testes usam fixture sintética e mocks da extração de áudio; não comprovam qualidade editorial humana nem comportamento no binário compilado.
- Não foi realizada medição de benchmark nem inspeção gráfica manual nesta alteração; a seleção global percorre no máximo o conjunto limitado de candidatos locais já retornados pelos blocos.

## Referências e limites

- A fonte do ASR local foi confirmada no código: Parakeet TDT v3 ONNX INT8 pelo `onnx-asr`, timestamps do adaptador agrupados para palavras, sem confiança calibrada ou diarização garantida. A documentação do `onnx-asr` confirma `nemo-parakeet-tdt-0.6b-v3`, quantização INT8 e retorno de tokens/timestamps/log-probabilities; o editor usa somente os campos efetivamente produzidos no seu runtime. Nenhum outro ASR é chamado pelo ranking.
- MMR segue o princípio de equilibrar relevância e diversidade. TextRank e TextTiling são referências de ranking/coesão lexical; as implementações locais são variantes heurísticas, não reproduções integrais dos artigos.
- Fontes consultadas: [onnx-asr usage](https://github.com/istupakov/onnx-asr/blob/main/docs/usage.md), [TextRank](https://aclanthology.org/W04-3252/), [TextTiling](https://aclanthology.org/J97-1003/), [SciPy `find_peaks`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.find_peaks.html), [Auto-Editor](https://github.com/WyattBlue/auto-editor), [PySceneDetect license](https://github.com/Breakthrough/PySceneDetect/blob/main/LICENSE), [MomentClip](https://github.com/Yuu-yu09/clipper) e [Claggeta Clipper](https://github.com/Claggeta/clipper).
- Nenhum código externo foi copiado nem nova dependência adicionada. O Claggeta Clipper declara licença “to be decided”, então não é fonte de código para incorporação. Auto-Editor documenta regras combináveis de áudio/movimento; PySceneDetect declara BSD 3-Clause, mas continua fora das dependências.
- Produtos comerciais servem como referência de fluxo e revisão; seus algoritmos internos não são públicos e não foram inferidos.
- A qualidade editorial do ranking continua sem conjunto humano anotado. Pontuação e diversidade não representam potencial comprovado de viralização.

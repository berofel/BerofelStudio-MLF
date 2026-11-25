# Motor discursivo local: contexto, ironia e mudanças de assunto

## O que foi acrescentado

`berofel/services/discourse_features.py` reúne sinais textuais determinísticos
usados pelo motor de limpeza e pelo clipador. Não carrega ASR, LLM, embeddings,
modelo de linguagem, rede ou dependência nova. Recebe apenas transcrições e
tempos já disponíveis no projeto.

O detector de ironia registra marcadores explícitos, contraste de polaridade,
aspas, risos e exagero, além do contexto textual próximo. Menções didáticas a
“ironia/sarcasmo” e negações como “não foi sarcasmo” não são consideradas
intenção irônica. A polaridade reconhece negação local simples e interrompe
seu escopo em conectivos adversativos explícitos como “mas”. O módulo
discursivo também marca reações (“nossa”, “caramba”), humor textual, perguntas
retóricas possíveis e comandos de correção/reinício. Esses são indícios
determinísticos explicáveis, não uma afirmação sobre intenção, emoção ou
potencial de viralização. Na limpeza, sinais contextuais protegem trechos para
revisão em vez de ordenar um corte. No clipador, justificativas são exibidas e
o escore discursivo contribui com peso pequeno para o ranking editorial.

A segmentação de assunto inspira-se no princípio do TextTiling: comparar a
coesão lexical de blocos adjacentes e procurar vales perto de fronteiras entre
falas. Foi implementada sobre as falas já segmentadas pelo Berofel, com uma
janela local e similaridade Jaccard ponderada por contagem. Marcadores como
“mudando de assunto” funcionam como evidência adicional. Mudanças internas são
expostas ao ranking e podem reduzir a coerência de um candidato que atravessa
diversos tópicos. Reações/humor/perguntas/correções recebem, no máximo, peso
de 8% no componente semântico (mantendo o peso total normalizado); os demais
componentes e o limitador de coerência continuam valendo. Candidatos com
mudança de locutor conhecida não usam a fala do locutor diferente como contexto
de ironia. Isso não cria novos tempos nem altera o áudio.

Os índices palavra→fala são construídos uma vez por análise do clipador. As
novas características participam da versão de cache `CLIPPER_VERSION=4`,
evitando reutilizar resultados antigos sem esses dados. A ausência da nova
característica continua compatível com chamadas antigas de pontuação.

## Por que os sinais são conservadores

Uma frase positiva pode ser sincera, irônica, citada ou humorística. Até a
combinação “perfeito, travou de novo” é apenas uma suspeita textual; tom,
prosódia, situação e contexto compartilhado podem inverter sua interpretação.
Por isso as explicações dizem “possíveis sinais” e não aplicam cortes. A
transcrição do ASR pode omitir palavras, então o áudio original permanece a
fonte de verdade.

As regras usam vocabulários pequenos e explícitos. Negação usa uma janela local
curta, não análise sintática completa; ironia sem marcas textuais, sarcasmo
dependente de prosódia, humor sutil, fala sobreposta, mudança de tópico sem
vocabulário novo e erros de transcrição podem escapar. Reação, humor, pergunta
retórica e autocorreção são sugestões de relevância editorial e podem gerar
falsos positivos. Não há corpus humano PT-BR anotado neste trabalho; os testes
são fixtures determinísticas e não medem precisão/recall nem ganho real de
seleção no mundo real. Nenhum benchmark sintético é apresentado como medição
de precisão editorial.

## Pesquisa técnica e licenças

Estas referências foram usadas para orientar conceitos, não para copiar código
ou adicionar dependências:

* [NLTK TextTiling](https://www.nltk.org/api/nltk.tokenize.texttiling.html):
  segmentação de subtemas por coesão lexical; usada como referência conceitual.
* [TF-IDF do scikit-learn](https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfVectorizer.html):
  ponderação lexical e relação entre produto normalizado e similaridade cosseno;
  nenhuma dependência scikit-learn foi adicionada.
* [GATE/JAPE](https://gate.ac.uk/sale/pg/pg.pdf): regras declarativas em fases
  como referência de organização de padrões; nenhuma implementação foi
  incorporada.
* [spaCy: rule-based matching](https://spacy.io/usage/rule-based-matching/):
  referência para padrões determinísticos; o serviço não carrega spaCy.
* [ACL: Humans Require Context to Infer Ironic Intent](https://aclanthology.org/P14-2084/)
  e [Towards a Contextual Pragmatic Model to Detect Irony](https://aclanthology.org/P15-2106/):
  motivam tratar contexto como evidência necessária, sem inferir intenção de
  uma palavra isolada.
* [PySceneDetect API](https://www.scenedetect.com/api/) e
  [benchmarks](https://www.scenedetect.com/benchmarks/): referência de engenharia
  para separar mudanças de conteúdo de movimento rápido. Não foi instalado nem
  conectado a este motor textual; análise visual é uma etapa independente.

## Testes

Os testes de `tests/test_discourse_features.py`, `tests/test_clip_audio_signals.py`,
`tests/test_automatic_cleanup.py` e `tests/test_clipper.py` cobrem menções e
negações, contraste de polaridade, resolução sincera, papéis de fala, mudança
de assunto, reação/humor/pergunta/correção, exclusão de contexto entre
locutores conhecidos, peso limitado no ranking e integração de metadados.
As fixtures são sintéticas e não substituem avaliação auditiva humana.

Após as novas pistas, um microbenchmark sintético com 2.004 falas e 2.003
fronteiras, cinco repetições no Python 3.12/Windows, mediu p50 de 1,0751 s
(mínimo 1,0716 s; máximo 1,0778 s) para TextTiling leve mais análise discursiva
de cada fala, com pico rastreado pelo `tracemalloc` de 1,149 MiB. Isso mede
somente regras de texto sintético; não inclui áudio, ASR, VAD, decodificação,
RSS total do processo nem GUI e não é benchmark end-to-end nem evidência de
qualidade. Na validação completa atual, `python -m unittest discover -s tests
-v` executou 522 testes: todos passaram e 5 foram ignorados por dependências
opcionais ausentes. Os testes direcionados de discurso (12), sinais/ranking do
clipador (12), clipador (14) e limpeza automática (34) também passaram.

## Observação separada: sotaque PT-BR no TTS

Na avaliação auditiva do usuário, uma fala multivozes soou como português
europeu, enquanto o restante foi considerado satisfatório. O Qwen3 aceita o
rótulo genérico `Portuguese`; ele não oferece um seletor explícito PT-BR/PT-PT.
No Pure C, o caminho rápido usa somente o vetor de locutor e ignora a
transcrição da referência, o que pode enfraquecer a pista regional. Para
corrigir apenas o perfil afetado, a opção com melhor condicionamento é gerar
essa fala usando **Original Qwen3 Base**, com áudio de referência e transcrição
PT-BR revisada, ou preparar uma referência brasileira mais representativa. Não
há fallback silencioso nem garantia automática de sotaque. O restante dos
perfis Pure C permanece inalterado.

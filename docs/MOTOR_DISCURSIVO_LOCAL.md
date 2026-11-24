# Motor discursivo local: ironia e mudanças de assunto

## O que foi acrescentado

`berofel/services/discourse_features.py` reúne sinais textuais determinísticos
usados pelo motor de limpeza e pelo clipador. Não carrega ASR, LLM, embeddings,
modelo de linguagem, rede ou dependência nova. Recebe apenas transcrições e
tempos já disponíveis no projeto.

O detector de ironia registra marcadores explícitos, contraste de polaridade,
aspas, risos e exagero, além do contexto textual próximo. O resultado é uma
heurística explicável, nunca uma afirmação sobre a intenção do locutor. Na
limpeza, sinais contextuais protegem trechos para revisão em vez de ordenar um
corte. No clipador, podem enriquecer a justificativa e o ranking; a seleção
continua editorial e depende da conferência do áudio.

A segmentação de assunto inspira-se no princípio do TextTiling: comparar a
coesão lexical de blocos adjacentes e procurar vales perto de fronteiras entre
falas. Foi implementada sobre as falas já segmentadas pelo Berofel, com uma
janela local e similaridade Jaccard ponderada por contagem. Marcadores como
“mudando de assunto” funcionam como evidência adicional. Mudanças internas são
expostas ao ranking e podem reduzir a coerência de um candidato que atravessa
diversos tópicos. Isso não cria novos tempos nem altera o áudio.

Os índices palavra→fala são construídos uma vez por análise do clipador. As
novas características participam da versão de cache `CLIPPER_VERSION=3`,
evitando reutilizar resultados antigos sem esses dados. A ausência da nova
característica continua compatível com chamadas antigas de pontuação.

## Por que os sinais são conservadores

Uma frase positiva pode ser sincera, irônica, citada ou humorística. Até a
combinação “perfeito, travou de novo” é apenas uma suspeita textual; tom,
prosódia, situação e contexto compartilhado podem inverter sua interpretação.
Por isso as explicações dizem “possíveis sinais” e não aplicam cortes. A
transcrição do ASR pode omitir palavras, então o áudio original permanece a
fonte de verdade.

As regras usam vocabulários pequenos e explícitos. Sinônimos distantes, ironia
sem marcas textuais, falas sobrepostas, mudança de tópico sem vocabulário novo
e erros de transcrição podem escapar. Não há corpus humano PT-BR anotado neste
trabalho; os testes são fixtures determinísticas e não medem precisão/recall
editorial no mundo real.

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

Os testes de `tests/test_discourse_features.py`, `tests/test_automatic_cleanup.py`
e `tests/test_clipper.py` cobrem marcadores, contraste, resolução sincera,
papéis de fala, mudança de assunto, contexto irônico e integração de metadados.
As fixtures são sintéticas e não substituem avaliação auditiva humana.

Um microbenchmark sintético com 2.004 falas e 2.003 fronteiras, cinco
repetições aquecidas neste Windows, mediu p50 de 0,1242 s e máximo de 0,1260 s
para TextTiling leve mais 300 verificações de ironia. Não inclui áudio, ASR,
VAD, decodificação nem GUI e não é benchmark end-to-end. Na validação da suíte,
513 testes passaram e 5 foram ignorados; uma primeira execução teve uma falha
transitória em um teste de slider Qt, que passou isoladamente e na execução
completa seguinte.

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

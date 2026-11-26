# Berofel Clip Engine

O Clipador é uma ferramenta local de descoberta e revisão, não um editor automático destrutivo nem uma previsão de viralização. Ele propõe intervalos ancorados nos timestamps do Parakeet já persistidos no projeto. Não instala nem executa Whisper, Faster-Whisper, LLM, embeddings neurais ou um segundo ASR. A seleção e o ranking são Python/NumPy determinísticos.

## Backend e dados de entrada auditados

- ASR em `berofel/services/parakeet_asr.py`: `nemo-parakeet-tdt-0.6b-v3`, quantização ONNX INT8, `onnx-asr==0.12.0`, `onnxruntime` com `CPUExecutionProvider`, `.with_timestamps()`. VAD usa o Silero ONNX local. Os arquivos de palavra contêm texto, `start`, `end` e `probability=None`; a confiança não é fabricada. O projeto mapeia os tempos para `source_start`/`source_end` absolutos da mídia.
- O adaptador do Clip Engine também aceita documentos com `segments` temporizados em `source_start`/`source_end`. Se um segmento não contiver palavras com seus próprios tempos, ele permanece uma unidade indivisível: nenhuma marcação por palavra é interpolada. As opções de borda e a justificativa identificam essa precisão reduzida. A confiança `probability`/`confidence` só participa se for numérica, finita e estiver em `[0,1]`; a penalidade máxima é 8% do score bruto, multiplicada pela cobertura observada, e vem marcada como não calibrada. No Parakeet atualmente instalado esses valores são `None`, então a pontuação vigente não recebe esse ajuste.
- Limite linguístico importante: a matriz oficial consultada da NVIDIA lista o Parakeet TDT v3 multilíngue com locale de português `pt-PT`, não uma variante `pt-BR`. O adaptador local seleciona idioma automaticamente e não declara confiança calibrada. O Clip Engine reutiliza a saída como está; nomes, gírias e fala brasileira podem ter erros, portanto confirme a transcrição e os limites no preview. Nenhum ASR alternativo ou fallback é executado.
- O Clipador recebe `project.transcripts` em `window.open_clipper`; a função `analyze_clips` só recebe os clipes selecionados e esse texto/timestamp salvo. A análise nunca instancia nem chama o ASR. Se faltarem palavras, a pessoa pode escolher **Transcrever faltantes com Parakeet**; essa ação chama o pipeline modular existente em modo `transcribe`, somente nos blocos sem palavras persistidas, grava os resultados no projeto/cache e então permite atualizar os candidatos. Sem essa ação, a análise segue apenas com sinais existentes ou PCM, sem ASR.
- A waveform da timeline em `services/timeline_visuals.py` é um envelope visual de pico mono a 4 kHz, um valor por 100 ms, dividido em tiles de 60 s. Ela não contém RMS, FFT, F0, fluxo espectral nem VAD. O Clipador agora pode consumi-la sem pedir uma decodificação nova, no modo **Rápido**. O envelope é explicitamente classificado como `waveform_peak_proxy`; não é tratado como RMS nem como clipping.
- No modo **Equilibrado**, a extração PCM usa FFmpeg em streaming, mono float 16 kHz e quadros de 20 ms. Em uma única passagem calcula RMS, pico, fração de clipping, fluxo espectral normalizado e taxa de cruzamento por zero. Esses sinais ficam no cache; o áudio nunca é carregado integralmente na RAM.

## Uso

1. Para candidatos com contexto de fala, use uma transcrição salva ou escolha **Transcrever faltantes com Parakeet**. A ação é opcional e explícita; reutiliza o serviço/cache do editor e não instala nem inicia outro reconhecedor. Também é possível procurar mudanças acústicas/visuais sem transcrever.
2. Selecione clipes/fonte e abra **Ações IA → Clipador Inteligente**.
3. Escolha duração, quantidade, sensibilidade acústica, perfil editorial e modo. A opção **Análise visual** é independente e lê somente miniaturas já salvas no cache da timeline; não solicita quadros faltantes nem decodifica o vídeo.
4. Revise nota, cobertura das evidências, componentes, justificativas e avisos.
5. Miniaturas aparecem junto aos títulos somente quando já existem no cache da timeline; o painel não pede decodificação de quadros. Reproduza candidatos, ajuste limites em bordas reais de palavras e marque os desejados.
6. Use **Adicionar marcados à timeline**. A inserção é não destrutiva e pode ser desfeita; o arquivo original não muda.

O modo Rápido só usa tiles de waveform já presentes para o intervalo inteiro. Se faltar qualquer tile, ele continua com texto/timestamps quando existem e informa que não havia waveform completa; não inicia FFmpeg escondido. Sem texto e sem sinais já cacheados, não inventa candidatos. O modo Equilibrado calcula PCM se ainda não houver o cache PCM. O modo Avançado também calcula PCM e executa TextRank local esparso somente nas falas de cada candidato. Os resultados persistidos ficam separados por modo para não confundir envelope de pico com RMS. TextRank é uma centralidade relativa entre falas daquele candidato, não uma medida absoluta de qualidade.

No modo Rápido, as chaves do ranking e dos quadros acústicos incluem a identidade dos tiles de waveform existentes. Se a timeline gerar ou substituir esses tiles após uma análise sem waveform, uma nova análise invalida somente o resultado derivado da waveform e atualiza o score sem decodificar o áudio. Alterar opções continua reutilizando as características compatíveis.

Sem transcrição, candidatos são gerados somente quando há picos acústicos relativos à própria gravação ou mudanças suficientemente isoladas em miniaturas cacheadas. O detector visual aplica limiar robusto e supressão de máximos próximos; é um proxy de mudança de imagem, não detecção semântica de cena. A pontuação usa apenas dimensões observadas, expõe cobertura e reduz a nota parcial em direção a 50 quando a cobertura é baixa. O painel mostra “Sem transcrição” em vez de texto inventado e permite trim temporal curto. O Parakeet só é iniciado após a ação explícita **Transcrever faltantes com Parakeet**.

Quando já existe uma transcrição, mudanças acústicas/visuais em lacunas longas fora dos timestamps de palavras também podem gerar candidatos complementares, desde que caibam na duração configurada. Um intervalo sem palavras cronometradas não prova silêncio nem ausência de fala: a UI o identifica como janela sem palavras Parakeet e pede conferência no áudio. Esses candidatos pontuam somente dimensões acústicas/visuais, têm cobertura parcial e mantêm os controles de ajuste dentro da lacuna. Os eventos não entram na pontuação de candidatos falados.

O alcance selecionado sem transcrição permanece elegível no diálogo principal. Antes, a janela principal bloqueava esse caminho e pedia para transcrever, apesar de o serviço e o diálogo já oferecerem candidatos baseados em eventos; essa lacuna de integração foi corrigida. Sem transcrição, o modo Rápido ainda precisa de waveform/miniaturas existentes. Equilibrado/Avançado podem ler PCM da fonte em streaming, sem abrir uma transcrição.

## Etapas existentes e evolução desta versão

1. Normaliza palavras da transcrição e rejeita timestamps inválidos, mantendo tempos absolutos da mídia.
2. Agrupa falas, detecta perguntas/respostas próximas, mudanças de locutor conhecidas, frases dependentes, ganchos e sinais discursivos. Aberturas interrogativas PT-BR como “você sabia”, “já imaginou” e “será que” podem marcar uma pergunta sem pontuação quando há pausa natural de ao menos 700 ms e o fim não parece incompleto. Uma resposta pode ser ligada sem diarização por marcador explícito ou sobreposição suficiente de termos de conteúdo entre turnos adjacentes; uma palavra compartilhada isolada não basta. A relação é uma heurística local e não afirma equivalência semântica.
3. Usa coesão lexical por vizinhança, inspirada no princípio de TextTiling, para sugerir possíveis mudanças de tópico.
4. Constrói janelas a partir de palavras/turnos e ajusta para palavras e fins de frase; não cria timestamps por divisão uniforme de texto.
5. Detecta aumentos de nível alinhados aos intervalos de palavras. O modo equilibrado usa RMS medido e uma pequena contribuição positiva de novidade espectral relativa; Rápido usa somente o proxy de pico da waveform. A taxa de cruzamento por zero é retida como característica acústica para diagnóstico e extensões futuras, não recebe peso editorial nesta versão.
6. Calcula uma nota relativa 0–100 e reporta componentes medidos: gancho, contexto, áudio, densidade/novidade lexical, desfecho e densidade de fala. Características ausentes ficam `null`; o ranking renormaliza apenas pesos disponíveis e reporta cobertura. A pontuação não representa probabilidade de viralização.
7. Seleciona candidatos com Maximal Marginal Relevance (MMR): preserva o score editorial existente e reduz a prioridade de itens semelhantes aos já escolhidos. A similaridade combina cosseno esparso dos termos de conteúdo com IoU temporal. Mantém também a rejeição explícita de sobreposição excessiva e de duplicatas lexicais quase idênticas; uma versão com informação nova continua elegível. `lambda=0,75` é o ponto inicial experimental, não um parâmetro calibrado com preferência humana.
8. Gera um título sugerido por extração de uma frase existente na transcrição, usando pistas lexicais/estruturais e limite de caracteres; nunca inventa uma frase nem usa modelo generativo. O título é recalculado quando o usuário ajusta os limites do candidato.
9. Apresenta candidatos ao usuário. Nenhum é inserido, cortado ou renderizado automaticamente.

Perfis disponíveis: Geral, Podcast, Gameplay, Tutorial, Terror, Humor, Debate, Vlog, Lives, Aulas, Histórias, Notícias, Entrevistas, Motivacional, Esportivo e Personalizado. Cada perfil define pesos editoriais iniciais diferentes, aplicados somente às dimensões realmente disponíveis. “Personalizado” começa com os pesos-base do perfil Geral e pode ser combinado com o grupo de pesos avançados. São presets heurísticos, ainda sem calibração humana. Modos disponíveis: Rápido (waveform de timeline em cache), Equilibrado (PCM e regras) e Avançado (PCM, regras e TextRank local). A análise visual é um controle opcional independente dos modos. Ela compara diferenças de quadro e histogramas de miniaturas existentes após reduzi-las a 32×18 em escala de cinza. Só contribui para o ranking com pelo menos cinco amostras e 50% de cobertura; mudanças visuais não identificam objetos, ações ou relevância semântica. Se não houver miniaturas suficientes, o componente visual permanece ausente.

O grupo recolhido **Ajuste avançado de pesos · experimental** permite alterar as prioridades por dimensão depois de escolher um perfil. Os valores são normalizados para soma 1; evidências ausentes continuam `null` e não recebem nota inventada. Esse controle recalcula somente os resultados/ranking com o cache de áudio existente, não chama o Parakeet nem decodifica PCM novamente. Pesos são preferências experimentais, não parâmetros calibrados por aprovação humana.

O campo **Pontuação mínima** filtra os candidatos classificados, entre 0 e 100. Ele não participa da identidade da análise persistida: aumentar ou reduzir o limite relê o ranking em cache, sem nova chamada ao Parakeet, reextração acústica, leitura de vídeo ou renderização. O painel informa quando todos os resultados ficaram abaixo do limite. Nota zero mantém a lista sem esse filtro.

Depois de consultar os resultados em cache de cada bloco, o Clipador aplica o limite escolhido e faz uma seleção MMR final sobre todo o alcance. Assim, vários blocos da mesma origem não consomem posições com versões sobrepostas do mesmo acontecimento. A sobreposição temporal só é comparada quando a origem coincide; timestamps iguais em mídias diferentes não significam que sejam o mesmo evento. A comparação lexical continua sendo uma heurística de redundância, não uma prova de equivalência. As listas individuais em cache permanecem separadas e reutilizáveis; essa seleção global não altera transcrições, áudio nem timeline.

## Pontuação

Os pesos iniciais estão em `clip_audio_signals.CLIP_SCORE_PROFILES`. Para cada candidato, usa-se a média ponderada dos componentes disponíveis:

`score = 100 × Σ(peso_i × valor_i) / Σ(peso_i disponíveis)`

`evidence_coverage = Σ(peso_i disponíveis)`

No perfil Geral, os pesos são: gancho 0,20; contexto/limites 0,20; áudio 0,15; valor lexical 0,15; desfecho 0,15; ritmo/densidade 0,10; visual 0,05. No modo de waveform, o peso acústico é reduzido a 55% do valor configurado porque o envelope de pico é grosseiro. Cada outro perfil tem um vetor próprio no código. Nenhum peso está calibrado por avaliação humana; são heurísticas editoriais.

Informação lexical combina proporção de termos de conteúdo e razão de termos únicos. Desfecho usa classes de turno e marcadores explícitos; ritmo usa a união dos timestamps de palavras dividida pelo intervalo, sem dupla contagem. Isso não mede utilidade, verdade ou emoção como fatos. Sinais discursivos e possíveis reações permanecem cues para revisão.

Quando há PCM medido, mas nenhum pico relativo à fala é encontrado, a dimensão acústica fica em 0,5 (neutra) e a interface explica que não houve pico; não confunde falta de um evento positivo com áudio ausente. Se o áudio/feature realmente falta, a dimensão fica indisponível e seu peso não entra no cálculo. O piso do detector foi reduzido a -80 dBFS para não suprimir automaticamente microfones de baixo ganho; a decisão continua exigindo aumento relativo sobre a mediana local e timestamps de fala.

## Cache e desempenho

- Os arrays RMS/pico/clipping/fluxo espectral/ZCR de PCM e waveform proxy são caches separados, indexados por identidade da fonte, intervalo, taxa, tamanho de quadro e versão própria do extrator acústico. A versão do extrator é 6 e a do ranking é 10. O ranking antigo é invalidado para incluir a seleção MMR global; features acústicas permanecem compatíveis e não são recalculadas. Nenhum Parakeet é executado por essa invalidação.
- O proxy visual usa cache `.npz` separado, indexado pela mídia/intervalo e pelo caminho, tamanho e `mtime_ns` de cada thumbnail existente. Alterar o perfil reutiliza as diferenças de quadro/histogramas; criar ou alterar miniaturas invalida somente essa extração. A coleta de caminhos chama `get_thumb(..., request=False)`, e a escrita é atômica e entra no limite geral do cache do Clipador.
- Quando a análise visual está ligada, a classificação final relê o manifesto das miniaturas antes de consultar resultado persistido, para que uma miniatura nova/substituída não deixe o ranking antigo visível. O cálculo das diferenças continua vindo do cache visual se a identidade das miniaturas não mudou.
- Resultados incluem texto/timestamps, opções, perfil, modo e versão da regra. Alterar duração/perfil pode recalcular candidatos e ranking, mas nunca solicita uma nova transcrição. As características de áudio continuam reutilizáveis.
- O limite de nota é aplicado depois da leitura do ranking persistido. Assim, alterar apenas a nota mínima não invalida candidatos, transcrição ou características; o retorno também informa quantos candidatos havia antes do filtro.
- `score_clip` e avisos agora recortam os arrays com busca binária, em vez de criar uma máscara sobre todos os frames para cada candidato. A busca de tópicos internos também limita a consulta às fronteiras dentro do candidato.
- Para candidatos sem fala transcrita, as mudanças de miniaturas usam MAD/percentis e NMS temporal. Scores de evento são contraídos conforme a cobertura das evidências do perfil; essa é uma proteção de ranking experimental, não uma métrica de qualidade validada.
- O cache segue em `%LOCALAPPDATA%\BFS\cache\clipper` ou `BEROFEL_CLIPPER_CACHE`; os artefatos reconhecidos estão sujeitos ao limite configurável `BEROFEL_CLIPPER_CACHE_MAX_MB`. Cache corrompido é ignorado e pode ser refeito.
- A chamada roda na fila de trabalho existente, permite cancelamento durante decodificação e não renderiza candidatos.

## Pesquisa e licenças

Referências consultadas em 26/11/2026; não copiamos código de terceiros:

- TextTiling (Hearst, 1997) baseia segmentação temática em coocorrência/cohesão lexical entre blocos: [ACL Anthology](https://aclanthology.org/J97-1003/). O projeto usa uma aproximação local por turnos, não replica o algoritmo experimental completo.
- TextRank (Mihalcea e Tarau, 2004) é uma técnica de ranking em grafo para texto: [ACL Anthology](https://aclanthology.org/W04-3252/). O modo Avançado implementa uma variante local, esparsa e limitada por vizinhança; não é uma reprodução integral do experimento do artigo.
- MMR (Carbonell e Goldstein, SIGIR 1998) equilibra relevância e novidade para formar uma lista: [registro ACM/DOI](https://doi.org/10.1145/290941.291025). Aqui, relevância é o score editorial já calculado; similaridade é uma aproximação lexical/temporal determinística. Isso reduz concentração em candidatos parecidos, mas não prova qualidade editorial.
- `scipy.signal.find_peaks` documenta altura, distância, largura e prominência para picos: [SciPy](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.find_peaks.html). O Clipador não depende do SciPy nem aplica essa função; usa agregados RMS/pico e fluxo espectral por FFT calculados com NumPy.
- Auto-Editor usa condições de áudio/movimento para localizar intervalos e tem repositório sob Unlicense: [repositório](https://github.com/WyattBlue/auto-editor). Referência conceitual; nenhum código foi copiado.
- PySceneDetect oferece detectores de corte/alteração de cena e tem licença BSD 3-Clause: [projeto](https://github.com/Breakthrough/PySceneDetect), [licença](https://github.com/Breakthrough/PySceneDetect/blob/main/LICENSE). Não está instalado nem integrado aqui; a análise visual atual é apenas um proxy de mudança entre JPEGs de thumbnail em cache e não substitui detecção de cenas.
- MomentClip (`Yuu-yu09/clipper`) informa MIT; seu README cita componentes opcionais, incluindo Faster-Whisper, que não usamos. Viral Clipper (`davidkamere/clipper`) foi inspecionado, mas não localizei licença no repositório consultado; nenhum código foi copiado/adaptado. AI Video Clipping Studio e AutoClip indicam MIT; foram usados como leitura arquitetural, sem reutilização de código.
- Klap descreve publicamente transcrição, seleção de momentos autossuficientes, ranking e edição/revisão: [como funciona](https://klap.app/how-it-works). Isso informa requisitos de experiência do usuário, não revela seu algoritmo proprietário.
- Claggeta Clipper indica “License to be decided”; não usar nem adaptar código dele até que haja licença compatível.
- A leitura do MomentClip/`Yuu-yu09/clipper` é útil como referência de desenho “sinais primeiro, shortlist depois”, mas o próprio repositório descreve uso opcional de Faster-Whisper, visão e juiz LLM; esses componentes não entram no Berofel. A licença foi verificada no repositório antes de qualquer consideração de reutilização; nenhum arquivo foi copiado.
- A documentação do OpusClip é referência de fluxo editorial e opções de produto, não de implementação: os detalhes proprietários não são observáveis e não foram inferidos. O Auto-Editor mostra uma composição declarativa de regras de áudio/movimento e margens; o Berofel mantém o próprio modelo de timeline e não importa sua implementação.
- A página pública “How Klap Works” descreve seleção de momentos a partir de transcrição cronometrada, autonomia contextual, começo rápido, conclusão da ideia, ranking explicado, edição posterior, múltiplas proporções e reenquadramento. A página comercial do OpusClip apresenta clipping por gênero, recorte, legendas e edição. São referências de produto/fluxo; alegações de “viralidade” e algoritmos proprietários não foram reproduzidos nem tratados como métricas científicas.
- ClipsAI (MIT) documenta segmentação e composição como biblioteca, mas sua integração padrão usa WhisperX; não reutilizamos ASR nem código. A documentação consultada do Claggeta Clipper declara que sua licença ainda será decidida, portanto foi excluído de qualquer reutilização. Nenhuma dependência foi adicionada por esta pesquisa.

## Testes e limites conhecidos

Testes determinísticos existentes cobrem timestamps, bordas, pergunta/resposta, mudanças de tópico, RMS/picos, cache e deduplicação. O relatório de validação atual registra os testes novos para eventos em lacunas de transcrição e trims limitados; o número mais recente de testes deve ser lido nesse relatório. `pytest` não está instalado nesse runtime; a suíte disponível é `unittest`. As medições sintéticas não comprovam que um pico ou mudança visual seja um evento editorial relevante.

Para comparar resultados com momentos marcados manualmente, `scripts/evaluate_clip_engine.py` lê um JSON de resultado já salvo e um arquivo local `{"labels":[{"start":12.4,"end":35.0}]}` em segundos da mídia original. Exemplo:

```powershell
python scripts\evaluate_clip_engine.py --result caminho\resultado.json --labels caminho\marcacoes.json --top-k 5
```

O relatório calcula Precision@K e Recall@K com correspondência temporal um-para-um, erro total de início/fim e uma taxa de duplicidade estritamente temporal. Não lê mídia, não inicia Parakeet e não avalia semântica, completude ou potencial de viralização. Use a mesma política de marcação em todos os vídeos e separe vídeos de calibração dos de validação.

### Benchmark sintético de escala (25/11/2026)

`python scripts/benchmark_clip_engine_synthetic.py --repeats 3 --output relatorio.json` gera transcrição determinística repetitiva e mede somente o motor textual/candidatos. No ensaio exploratório de uma repetição por cenário, com 691/2.763/8.286/11.048/16.572 palavras para 5/20/60/80/120 minutos, todos os modos usaram `Clip(kind="image")`: **não houve PCM, VAD, Parakeet ou extração de vídeo**. Os tempos são tempo de parede de uma execução, em segundos; memória é o maior aumento de RSS observado por amostragem de 10 ms, não um pico garantido.

| Duração do texto sintético | Rápido | Equilibrado | Avançado | Maior aumento de RSS amostrado entre modos |
|---:|---:|---:|---:|---:|
| 5 min | 0,282 | 0,280 | 0,277 | 1,23 MiB |
| 20 min | 1,065 | 1,080 | 1,109 | 3,60 MiB |
| 60 min | 3,211 | 3,293 | 3,346 | 8,99 MiB |
| 80 min | 4,297 | 4,293 | 4,457 | 6,67 MiB |
| 120 min | 6,432 | 6,406 | 6,647 | 11,44 MiB |

O Avançado acrescenta TextRank local; sem áudio, Rápido e Equilibrado percorreram essencialmente a mesma rota textual. Isto mede escala computacional da fixture, não p50/p95, qualidade de clipes, desempenho no Ryzen 7 5700G ou pipeline real. No modo Equilibrado, o tempo de CPU foi 0,281/1,078/3,297/4,281/6,391 s, com 7 candidatos retornados em cada tamanho. Nenhuma melhoria editorial é declarada medida.

A primeira passagem do benchmark encontrou custo alto ao coletar as palavras próximas de cada candidato: a serialização examinava toda a transcrição por candidato. A consulta foi alterada para limites binários sobre timestamps ordenados. O ensaio subsequente de 15 cenários (uma repetição por combinação) terminou em aproximadamente 60 s no total; o maior caso, 120 min sintéticos/16.572 palavras, concluiu em 6,4–6,7 s por modo.

Uma medição real do arquivo `Teste Video Minecraft...mp4` (80,63 min) completou extração + Silero + Parakeet em 101,0 s e o Clip Engine Equilibrado em 7,781 s; a repetição do ASR reutilizou 27/27 etapas em 0,61 s. Detalhes, RTF e limites da medição estão em [CLIP_ENGINE_REAL_BENCHMARK_2026-11-25.md](RELATORIOS/CLIP_ENGINE_REAL_BENCHMARK_2026-11-25.md). Essa gravação não tem anotações humanas, então Precision@K, Recall, erro de limites e qualidade editorial continuam sem medida. Pico de RAM, CPU média/p95, avaliação auditiva, prévia visual visível e exportação real também não foram medidos. F0, avaliação de fala e reconhecimento semântico de cenas/ações continuam pendentes. O fluxo espectral recém-adicionado detecta mudança acústica, mas ainda não foi validado contra eventos humanos rotulados. O modo sem transcrição encontra apenas mudanças relativas de energia e imagem; não descobre o que ocorreu na tela.

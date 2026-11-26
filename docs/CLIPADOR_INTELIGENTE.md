# Berofel Clip Engine

O Clipador é uma ferramenta local de descoberta e revisão, não um editor automático destrutivo nem uma previsão de viralização. Ele propõe intervalos ancorados nos timestamps do Parakeet já persistidos no projeto. Não instala nem executa Whisper, Faster-Whisper, LLM, embeddings neurais ou um segundo ASR. A seleção e o ranking são Python/NumPy determinísticos.

## Backend e dados de entrada auditados

- ASR em `berofel/services/parakeet_asr.py`: `nemo-parakeet-tdt-0.6b-v3`, quantização ONNX INT8, `onnx-asr==0.12.0`, `onnxruntime` com `CPUExecutionProvider`, `.with_timestamps()`. VAD usa o Silero ONNX local. Os arquivos de palavra contêm texto, `start`, `end` e `probability=None`; a confiança não é fabricada. O projeto mapeia os tempos para `source_start`/`source_end` absolutos da mídia.
- O Clipador recebe `project.transcripts` em `window.open_clipper`; a função `analyze_clips` só recebe os clipes selecionados e esse texto/timestamp salvo. A busca não instancia nem chama o serviço Parakeet. Sem palavras salvas, pede que o usuário transcreva em Ações IA e não decodifica áudio para gerar candidatos.
- A waveform da timeline em `services/timeline_visuals.py` é um envelope visual de pico mono a 4 kHz, um valor por 100 ms, dividido em tiles de 60 s. Ela não contém RMS, FFT, F0, fluxo espectral nem VAD. O Clipador agora pode consumi-la sem pedir uma decodificação nova, no modo **Rápido**. O envelope é explicitamente classificado como `waveform_peak_proxy`; não é tratado como RMS nem como clipping.
- No modo **Equilibrado**, a extração PCM atual permanece: FFmpeg em streaming, mono float 16 kHz, quadros de 20 ms, com RMS, pico e fração de clipping armazenados em cache. O áudio nunca é carregado integralmente na RAM.

## Uso

1. Transcreva o material uma vez pela ferramenta Parakeet existente.
2. Selecione clipes/fonte e abra **Ações IA → Clipador Inteligente**.
3. Escolha duração, quantidade, sensibilidade acústica, perfil editorial e modo.
4. Revise nota, cobertura das evidências, componentes, justificativas e avisos.
5. Reproduza candidatos, ajuste limites em bordas reais de palavras e marque os desejados.
6. Use **Adicionar marcados à timeline**. A inserção é não destrutiva e pode ser desfeita; o arquivo original não muda.

O modo Rápido só usa tiles de waveform já presentes para o intervalo inteiro. Se faltar qualquer tile, ele continua somente com texto/timestamps e informa que não havia waveform completa; não inicia FFmpeg escondido. O modo Equilibrado calcula PCM se ainda não houver o cache PCM. O modo Avançado também calcula PCM e executa TextRank local esparso somente nas falas de cada candidato. Os resultados persistidos ficam separados pelo modo para não confundir envelope de pico com RMS. TextRank é uma centralidade relativa entre falas daquele candidato, não uma medida absoluta de qualidade.

## Etapas existentes e evolução desta versão

1. Normaliza palavras da transcrição e rejeita timestamps inválidos, mantendo tempos absolutos da mídia.
2. Agrupa falas, detecta perguntas/respostas próximas, mudanças de locutor conhecidas, frases dependentes, ganchos e sinais discursivos.
3. Usa coesão lexical por vizinhança, inspirada no princípio de TextTiling, para sugerir possíveis mudanças de tópico.
4. Constrói janelas a partir de palavras/turnos e ajusta para palavras e fins de frase; não cria timestamps por divisão uniforme de texto.
5. Detecta aumentos de nível alinhados aos intervalos de palavras. O modo equilibrado usa RMS medido; Rápido usa somente o proxy de pico da waveform.
6. Calcula uma nota relativa 0–100 e reporta componentes medidos: gancho, contexto, áudio, densidade/novidade lexical, desfecho e densidade de fala. Características ausentes ficam `null`; o ranking renormaliza apenas pesos disponíveis e reporta cobertura. A pontuação não representa probabilidade de viralização.
7. Seleciona candidatos diversos com supressão de sobreposição e deduplicação lexical conservadora. Informação nova tende a preservar uma versão parcialmente sobreposta.
8. Apresenta candidatos ao usuário. Nenhum é inserido, cortado ou renderizado automaticamente.

Perfis disponíveis: Geral, Podcast, Gameplay, Tutorial, Terror, Humor, Debate e Vlog. Cada perfil muda pesos de dimensões realmente disponíveis. Modos disponíveis: Rápido (waveform de timeline em cache), Equilibrado (PCM e regras) e Avançado (PCM, regras e TextRank local). O componente visual continua indisponível e aparece como ausente: ainda não há extração visual conectada ao Clipador. Em Gameplay, ausência de movimento visual reduz a cobertura, não cria um score visual fictício.

## Pontuação

Os pesos iniciais estão em `clip_audio_signals.CLIP_SCORE_PROFILES`. Para cada candidato, usa-se a média ponderada dos componentes disponíveis:

`score = 100 × Σ(peso_i × valor_i) / Σ(peso_i disponíveis)`

`evidence_coverage = Σ(peso_i disponíveis)`

No perfil Geral, os pesos são: gancho 0,20; contexto/limites 0,20; áudio 0,15; valor lexical 0,15; desfecho 0,15; ritmo/densidade 0,10; visual 0,05. No modo de waveform, o peso acústico é reduzido a 55% do valor configurado porque o envelope de pico é grosseiro. Cada outro perfil tem um vetor próprio no código. Nenhum peso está calibrado por avaliação humana; são heurísticas editoriais.

Informação lexical combina proporção de termos de conteúdo e razão de termos únicos. Desfecho usa classes de turno e marcadores explícitos; ritmo usa a união dos timestamps de palavras dividida pelo intervalo, sem dupla contagem. Isso não mede utilidade, verdade ou emoção como fatos. Sinais discursivos e possíveis reações permanecem cues para revisão.

## Cache e desempenho

- Os arrays RMS/pico/clip de PCM e waveform proxy são caches separados, indexados por identidade da fonte, intervalo, taxa, tamanho de quadro e versão do extrator.
- Resultados incluem texto/timestamps, opções, perfil, modo e versão da regra. Alterar duração/perfil pode recalcular candidatos e ranking, mas nunca solicita uma nova transcrição. As características de áudio continuam reutilizáveis.
- `score_clip` e avisos agora recortam os arrays com busca binária, em vez de criar uma máscara sobre todos os frames para cada candidato. A busca de tópicos internos também limita a consulta às fronteiras dentro do candidato.
- O cache segue em `%LOCALAPPDATA%\BFS\cache\clipper` ou `BEROFEL_CLIPPER_CACHE`; os artefatos reconhecidos estão sujeitos ao limite configurável `BEROFEL_CLIPPER_CACHE_MAX_MB`. Cache corrompido é ignorado e pode ser refeito.
- A chamada roda na fila de trabalho existente, permite cancelamento durante decodificação e não renderiza candidatos.

## Pesquisa e licenças

Referências consultadas em 25/11/2026; não copiamos código de terceiros:

- TextTiling (Hearst, 1997) baseia segmentação temática em coocorrência/cohesão lexical entre blocos: [ACL Anthology](https://aclanthology.org/J97-1003/). O projeto usa uma aproximação local por turnos, não replica o algoritmo experimental completo.
- TextRank (Mihalcea e Tarau, 2004) é uma técnica de ranking em grafo para texto: [ACL Anthology](https://aclanthology.org/W04-3252/). O modo Avançado implementa uma variante local, esparsa e limitada por vizinhança; não é uma reprodução integral do experimento do artigo.
- `scipy.signal.find_peaks` documenta altura, distância, largura e prominência para picos: [SciPy](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.find_peaks.html). O Clipador não depende do SciPy nem aplica essa função; a versão atual usa agregados RMS/pico existentes.
- Auto-Editor usa condições de áudio/movimento para localizar intervalos e tem repositório sob Unlicense: [repositório](https://github.com/WyattBlue/auto-editor). Referência conceitual; nenhum código foi copiado.
- PySceneDetect oferece detectores de corte/alteração de cena e tem licença BSD 3-Clause: [projeto](https://github.com/Breakthrough/PySceneDetect), [licença](https://github.com/Breakthrough/PySceneDetect/blob/main/LICENSE). Não está instalado nem integrado aqui; análise visual permanece pendente.
- MomentClip (`Yuu-yu09/clipper`) informa MIT; seu README cita componentes opcionais, incluindo Faster-Whisper, que não usamos. Viral Clipper (`davidkamere/clipper`) foi inspecionado, mas não localizei licença no repositório consultado; nenhum código foi copiado/adaptado. AI Video Clipping Studio e AutoClip indicam MIT; foram usados como leitura arquitetural, sem reutilização de código.
- Klap descreve publicamente transcrição, seleção de momentos autossuficientes, ranking e edição/revisão: [como funciona](https://klap.app/how-it-works). Isso informa requisitos de experiência do usuário, não revela seu algoritmo proprietário.
- Claggeta Clipper indica “License to be decided”; não usar nem adaptar código dele até que haja licença compatível.

## Testes e limites conhecidos

Testes determinísticos existentes cobrem timestamps, bordas, pergunta/resposta, mudanças de tópico, ironia heurística, RMS/picos, cache e deduplicação. Esta alteração acrescenta cobertura de componentes/perfis e leitura de waveform em cache sem decode. Os 30 testes focados de `test_clip_audio_signals.py` e `test_clipper.py` passaram. A primeira execução da suíte completa encontrou uma regressão Qt: a tarefa consultava `self.timeline.visual_cache`, embora o cache pertença a `self.timeline.view`. A referência foi corrigida, o teste real de despacho Qt passou e a execução seguinte de `python -m unittest discover -s tests -q` passou em **611 testes, com 6 skips**, em 66,686 s. `pytest` não está instalado, mas a suíte existente é `unittest`; não foi instalado outro pacote. `py_compile` dos arquivos alterados e `git diff --check` também passaram.

Não há nesta execução gravações humanas anotadas para calcular Precision@K, Recall, erro de limites ou qualidade editorial, nem foi executado benchmark end-to-end de 5–120 min ou coleta de CPU/RAM no Ryzen 7 5700G. Logo, nenhuma melhoria de qualidade editorial ou meta de desempenho é declarada medida. A análise espectral/fluxo, F0, adaptação por feedback, deteção visual e acontecimentos sem fala continuam como melhorias futuras, e não são declaradas implementadas. A interface foi exercitada por teste Qt offscreen, não por inspeção manual de uma janela visível.

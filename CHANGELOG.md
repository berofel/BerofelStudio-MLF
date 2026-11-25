## Próxima atualização (ainda não publicada)

- Normalização PT-BR do narrador: datas com dia inexistente ficam intactas, horários usam formas brasileiras naturais (incluindo 1h30, meia-noite e meio-dia) e as chaves de cache avançam para o normalizador v2.
- A seleção inteligente da janela vocal agora incrementa a versão de preparação do perfil para invalidar x-vectors/condicionamentos calculados pela regra anterior.
- Adicionado analisador leve de PCM em quadros de 20 ms para RMS, pico, crest factor, clipping, cruzamentos por zero e distribuição de nível. Ele não finge medir SNR sem amostras de ruído confiáveis e ainda não muda o ranking vocal sem calibração.
- O relatório de verificação de referência exibe crest factor, ZCR e percentis RMS do trecho condicionado, identificando SNR como não estimado quando não há uma referência de ruído válida.
- A verificação opcional do WAV com Parakeet informa a lacuna entre a última palavra reconhecida e o fim do arquivo, pedindo revisão auditiva para finais com intervalo grande; timestamps não são tratados como prova de truncamento.
- A comparação textual do Parakeet normaliza números e unidades em uma cópia interna para não penalizar `45%` versus “quarenta e cinco por cento”; a transcrição mostrada permanece intacta.
- Voice Intelligence 2.0 (etapa inicial): normalização de fala PT-BR sem alterar o texto de origem/legendas, seleção de referência vocal com ranking VAD e análise PCM limitada aos melhores candidatos, chaves de cache versionadas e inspeção de texto da narração opcional usando exclusivamente Parakeet TDT v3 ONNX INT8/CPU. Validação local com Parakeet e geração Pure C em ambos os presets documentada em `docs/VOICE_QUALITY_BENCHMARK.md`; avaliação auditiva, GUI e benchmark estatístico ainda pendentes.
- Narração longa: removido o teto de 2.048 tokens por solicitação do Qwen Original; textos extensos são divididos em limites de frase/palavra e unidos em um WAV único, sem impor limite de caracteres no campo. A rota Pure C usa trechos sequenciais por não expor orçamento de tokens na API empacotada.
- A tela de narração explica que Qwen3-TTS Base não inclui locutores pré-gravados; perfis autorizados são locais e não são distribuídos pelo instalador.
- O cronômetro da limpeza automática agora encerra quando a análise retorna, antes da janela de revisão. A aplicação posterior das sugestões continua sendo uma tarefa cronometrada separadamente.
- Testes de regressão para textos acima de 1.700 caracteres, divisão sem perda de palavras e consolidação dos trechos em WAV contínuo.
- Adicionado dicionário de pronúncia PT-BR editável por referência vocal. Regras privadas em JSON local alteram somente a cópia falada enviada ao Qwen; roteiro, transcrição e legendas permanecem intactos. Correspondência contextual é local à ocorrência, substituições não encadeiam e textos longos aplicam o dicionário uma única vez antes de dividir em trechos.
- O manifesto de capacidades Pure C agora identifica `--emo-ref` e seus requisitos como opções da CLI, sem inferir suporte HTTP. O binário instalado anuncia esses argumentos, mas o adaptador de narração ainda não os envia; controles neurais de emoção continuam indisponíveis até validação da API e da saída real.
- A geração Pure C e o backend nativo calculam hashes de gravações por blocos de 1 MiB, evitando materializar referências vocais longas integralmente na RAM durante a preparação das chaves de cache.
- Mensagens dos instaladores Windows e fixtures de regressão passaram a identificar Parakeet TDT v3/Silero como o ASR local; nenhuma rota de Whisper foi adicionada.
- Corrigida a reavaliação acústica da janela de referência: os candidatos pré-ranqueados agora são convertidos para os registros esperados pelo ranqueador PCM, evitando falha quando FFmpeg mede candidatos reais.
- Suíte no venv completo do aplicativo: 571 aprovados, 5 ignorados. Uma síntese curta real por preset (Mixed e INT8, seis threads) e checagem Parakeet CPU foram registradas como medições exploratórias, sem alegar avaliação perceptiva ou superioridade estatística.
- A verificação técnica da referência vocal agora exibe F0 descritiva via YIN, com confiança, faixa robusta e exclusão de quadros não vozeados/duvidosos; o dado não altera x-vector, seleção ou síntese. Testes determinísticos e microbenchmark sintético de 30 s documentados em `VOICE_INTELLIGENCE_2_0.md`.
- Investigada a expressividade do binário Pure C instalado: `--emo-ref` na CLI gera WAV, mas a rota HTTP do servidor produziu o mesmo WAV (hash idêntico com seed fixo) com `emotion: joy` e sem o campo. A documentação agora distingue esse comportamento local dos recursos descritos pelo upstream; nenhum controle foi ativado sem efeito comprovado.

# 0.10.0-alpha.4 — instalação sem janela de terminal

- O setup executa o bootstrap PowerShell oculto com `nsExec` do NSIS e encaminha as mensagens de etapa para o painel de detalhes do próprio instalador; não abre uma janela de CMD/PowerShell durante a preparação do editor.
- As rotinas opcionais de Parakeet e Qwen também iniciam PowerShell em modo oculto e não interativo.
- Adicionados testes de contrato para o modo oculto e o encaminhamento de status; os textos de distribuição passam a indicar alpha.4.
- A barra nativa representa o progresso geral do setup; não é mostrada porcentagem falsa para downloads externos sem progresso confiável.

# 0.10.0-alpha.3 — instalador atualizável

- A instalação limpa no Windows encontrou um falso negativo ao validar FFmpeg: o pipeline PowerShell fechava a saída nativa cedo e deixava um exit code vazio. A validação agora captura a saída completa e exige banners/exit codes válidos para FFmpeg e FFprobe; o fallback BtbN pode concluir a instalação.
- O smoke test do setup prepara o Visual C++ assinado no runner sem UAC interativo, limita a espera do instalador e preserva logs de falha como artefato de CI.
- A versão final da instalação é lida do arquivo canônico `berofel/__init__.py` após o diagnóstico Python; falhas do bootstrap em modo silencioso encerram com código explícito, sem aguardar uma caixa de diálogo invisível.
- O manifesto principal inclui NumPy e SciPy, usados diretamente pelos serviços de áudio, clipe e preparo de referências do Qwen; a ausência foi detectada na coleta da suíte em Windows limpo.
- O instalador Windows consulta as Releases públicas do GitHub antes de instalar. Se existir uma versão SemVer mais nova com EXE e checksum, baixa ambos, valida o SHA-256 e inicia o setup atualizado antes de alterar a instalação existente.
- Falha de rede ou de validação oferece uma escolha explícita para continuar com o setup já baixado; `/NOUPDATECHECK` permite instalação manual/rollback.
- O build publica nomes versionados e um alias estável para a página de Releases; tags de release precisam corresponder à versão declarada no código.
- O workflow Windows testa a suíte, compila e faz instalação limpa em runner Windows antes de publicar: valida dependências, abertura da janela Qt, atalho, preservação de dados e desinstalação. Dispara em PRs para `main`, pushes em `main`/branches `feat/*` e `fix/*`, e tags versionadas.
- A instalação segue online e os modelos continuam opcionais/de fontes externas; checksum não substitui assinatura Authenticode, que ainda não está disponível.

# Preparação do instalador Windows único — 24/11/2026

- Preparação da prévia `0.10.0-alpha.2`: a janela Qt agora prefere o mesmo ICO multirresolução que identifica o instalador e os atalhos do Windows; o cabeçalho continua renderizando o SVG-fonte.
- O build do instalador verifica se os scripts/dependências essenciais estão no snapshot e recusa empacotar pesos de IA ou gerar um EXE acima do limite de publicação do GitHub Releases.
- Documentado o fluxo para baixar e conferir o SHA-256, os requisitos de internet/modelos e o estado ainda não assinado do instalador.
- Fonte do ícone segue o vetor existente `berofel_studio_mark.svg`, igual ao símbolo da referência do usuário; adicionado ícone Windows multi-resolução, ícone da janela Qt e atalhos de desktop/Menu Iniciar no instalador.
- Criado instalador NSIS por usuário, bootstrap idempotente do editor, dependências fixadas, FFmpeg validado por SHA-256 e seleção de Whisper Base/Silero e Qwen3-TTS Base.
- Criado workflow GitHub para compilar no Windows, publicar EXE+SHA-256 em Releases via tag e anexar artefato em execução manual. NSIS usa o compressor zlib para manter uma licença compatível com distribuição comercial.
- Limite documentado: o EXE baixa Python, bibliotecas e modelos na instalação; não é offline. Qwen 0.6B (~2,5 GB) e modelos privados não entram em Git/GitHub.
- A compilação NSIS passou no runner Windows do GitHub Actions e o EXE+SHA-256 foi gerado como artefato de build. A instalação completa em uma máquina limpa ainda não foi validada; a publicação pública depende de sincronizar o código local atual com o remoto.

# Limpeza automática modular local

## Correções funcionais e acessibilidade de ferramentas — 24/11/2026

- O cronômetro compacto aparece no cabeçalho, atualiza pelo relógio monotônico sem depender do progresso e mantém o tempo final após sucesso, erro ou cancelamento; tarefas sem total exibem progresso indeterminado.
- O painel de legendas ganhou rolagem e uma biblioteca sempre acessível com 24 estilos locais. O estilo pode ser escolhido antes da primeira legenda e é usado ao criar novos blocos; alterar estilo não executa transcrição. Família, peso, tamanho, texto/contorno, alinhamento, fundo, opacidade e sombra são propriedades persistidas e renderizadas.
- O seletor junto à prévia altera a resolução do projeto (incluindo formatos vertical, quadrado, 4:5, clássico, ultrawide e personalizado) em uma edição reversível; a timeline continua intacta.
- A biblioteca lateral agora expõe os três efeitos que o renderer já suporta: dissolvência, slide e zoom. Efeitos adicionais pedidos ainda não estão implementados e não são apresentados como disponíveis.
- O idioma padrão visível passou a indicar Português brasileiro (PT-BR). O Qwen recebe o idioma suportado `Portuguese`; não há parâmetro oficial de dialeto brasileiro.
- Pesquisa e limites atuais documentados em `docs/REFERENCIAS_TECNICAS_2026.md`; runtimes locais conferidos: Qwen3-TTS 0.6B Base, qwen-tts 0.1.1, PyTorch 2.15.0+cpu, Transformers 4.57.3 e Pure C configurado com seis threads.
- Validação: suíte completa 466 testes, 5 ignorados, passou (59,1 s); oito testes de UI/renderização focados repetidos depois das mudanças passaram. Não houve síntese real nem inspeção GUI porque o computador não expôs uma janela do editor ao controlador visual.

## Revisão global em andamento — 23/11/2026

- O worker ASR em lote grava stderr temporário em arquivo, evitando bloqueio de pipe cheio e preservando o final do diagnóstico; a UI informa que o Parakeet só reporta progresso por trecho concluído.
- Corrigido o clique direito na timeline: seleciona o clipe alvo, preserva multisseleção quando apropriado e captura IDs estáveis para o menu de contexto.
- WAVs de narração concluídos passam a ser registrados na biblioteca mesmo quando a geração não insere o áudio imediatamente na timeline.
- Adicionado comando para inserir a última narração já gerada; reutiliza o WAV e não reinicia a síntese nem a reprodução.
- O painel de legendas agora também edita a cor do contorno e a posição horizontal, propriedades já suportadas pelo projeto e pelo renderizador.
- Atalhos de edição não capturam Ctrl+C/Ctrl+V/desfazer/exclusão enquanto o foco está em um campo textual ou de configuração; ações mantêm uma tabela central com identificadores para testes e consulta.
- Validação da rodada anterior: 81 testes do painel/timeline passaram. Após legenda, atalhos e correção do worker ASR: 460 testes passaram, 5 ignorados, sem falhas (69,5 s).

## Motor contextual Python V3 — 23/11/2026

- Integrados ao motor existente comandos falados de regravação e busca reversa de tentativas; os comandos servem como âncora e não são incluídos nos cortes sugeridos.
- A assinatura contextual protege sujeito e forma interrogativa, compara números escritos com dígitos e impede que aliases ortográficos alterem palavras críticas.
- Adicionados testes para pontes de regravação, tentativas longas, proteção pergunta/resposta, quantidades e aliases críticos.
- Benchmark comparativo sintético com 17.500 palavras/2.499 pausas, três execuções por versão: HEAD p50 4,319 s e 3,63 MiB temporários; integração p50 4,817 s e 3,61 MiB. O custo de ~12% de tempo foi registrado sem alegação de ganho de velocidade; ainda falta avaliação humana anotada.

## Motor Contextual Python V2 integrado — 23/11/2026

- Mescladas ao motor existente as comparações direcionais por informação, busca de sufixos longos, retomadas marcadas e reinícios sem pausa, sem adicionar outro serviço ASR/VAD, motor contextual ou opção à interface.
- Assinaturas locais/cacheadas agora consideram condições, modalidade, referências temporais e entidades, além de ações, quantidades e negação; mudanças de locutor conhecidas, complementos e continuidades ficam protegidos.
- Correções com marcador explícito e divergência ficam obrigatoriamente para confirmação individual, fora de seleção/aprovação em massa.
- Propostas de módulos diferentes não são mais fundidas. Sobreposições são sinalizadas, não entram na seleção em massa e bloqueiam aplicação conjunta até desmarcar uma.
- O comparador pode reutilizar o carregador VERO/Hunspell existente para alias ortográfico apenas na análise, com cache limitado; transcrição, legendas e timestamps permanecem intactos.
- O refino RMS opcional não foi integrado porque o pipeline não mantém PCM original em memória no planejador; não há reabertura/renderização adicional de mídia.
- Testes existentes de limpeza foram ampliados para sufixos, retomada sem pausa, informação crítica, locutor, complemento, alias sem mutação e sobreposição. Suíte principal: 441 passaram, 5 ignorados; suíte V2: 28 sem falhas, 2 opcionais de RMS ignorados por NumPy ausente.
- Benchmark sintético integrado (46 mil palavras/1.999 pausas): cinco repetições, p50 5,627 s, máximo observado 5,631 s, 38,2 MiB RSS amostrado incluindo os dados de entrada e 5,42 MiB de alocação temporária rastreada. O equipamento reportou CPU AMD família 25/modelo 80, 8C/16T; o modelo comercial exato não pôde ser consultado. Não inclui VAD/ASR/áudio humano e não demonstra precisão editorial.

## Revisão ortográfica local pt-BR — 23/11/2026

- Adicionado botão **Revisar ortografia** no painel de legendas, com sugestões pontuais e aplicação individual; o usuário confirma no campo e salva com **Aplicar texto**.
- Integrado Spylls como dependência pequena do conjunto opcional de IA e criado instalador idempotente para VERO/Hunspell pt-BR em pasta BFS versionada, com verificação de integridade upstream e aviso de licença.
- O corretor não reescreve transcrições, palavras temporizadas ou arquivos de origem; não usa LLM e funciona offline depois de instalado.
- Adicionados testes de spans, sugestões, texto obsoleto, descoberta da pasta versionada e aplicação pelo painel Qt. Neste ambiente, Spylls 0.1.7 e o VERO pt-BR foram instalados localmente, os checksums foram validados e uma palavra com erro produziu uma sugestão real.
- Nomes técnicos/camelCase confirmados em legendas manuais ou editadas são protegidos na revisão local; palavras comuns e auto-legendas inalteradas não entram como exceção.

## Disfluências e ênfase — 23/11/2026

- O módulo Vícios detecta aberturas curtas literalmente reiniciadas, como “eu vou, eu vou mostrar”, exigindo pontuação de reinício, proximidade temporal e continuação da fala.
- Palavras de ênfase repetidas, como “muito muito”, deixam de virar cortes lexicais automáticos.
- Os intervalos mantêm os tempos da mídia original e continuam sujeitos à revisão existente.
- Microbenchmark sintético de 50 mil palavras: mediana 0,108 s em sete execuções aquecidas e 4,47 MiB de pico temporário via `tracemalloc` (sem medir RSS, VAD ou Whisper).

## Pesquisa open source e ASR local — 23/11/2026

- Reduzida a coleta de hotwords de projeto: processamento incremental evita cópias e ordenação de todos os tokens; microbenchmark sintético de 50 mil palavras caiu de 0,1556 s para 0,1462 s e de 19,36 MiB para 0,035 MiB de alocação temporária medida.
- Hotwords vindas de ASR agora precisam reaparecer em fontes diferentes ou em posições separadas por 30 s; legendas manuais e auto-legendas editadas pelo usuário contam como confirmação.
- Registrada pesquisa de Faster-Whisper, Buzz, WordCraft, Hunspell/Spylls e dicionários pt-BR VERO. Nenhum modelo ou pacote foi instalado.
- Cobertos feedback de erro do ASR, casing de termos confirmados e filtragem de legenda automática não editada.

## Evolução linguística local — 23/11/2026

- O detector contextual agora agrupa frases usando uma assinatura linguística em cache e equivalências pequenas, controladas e específicas do editor; elas ajudam na busca de candidatos e não decidem cortes isoladamente.
- Pausas curtas entre palavras deixam de forçar novos blocos por conta própria, e reticências permanecem com a tentativa interrompida até uma pausa VAD ou pontuação final confiável.
- Marcadores de autocorreção podem reconhecer correções explícitas de números e negação apenas quando a nova oração mantém evidências do mesmo tópico; mudanças de ação ou entidades distintas continuam protegidas.
- A limpeza pode fornecer vocabulário local do produto ao Faster-Whisper somente quando precisa criar uma transcrição. A dica é incluída na chave do cache, não altera o texto/timestamps e não ativa Qwen/LLM.
- O vocabulário de transcrição agora também aproveita, com limites, termos recorrentes ou reconhecidos com alta confiança em transcrições já salvas no projeto; palavras comuns e itens de baixa confiança são filtrados.
- As rotas Uma voz/legendas/transcrição da fila e Batata Quente usam a mesma dica contextual, com cache segregado pelas opções de reconhecimento.
- Normalização controlada de formas coloquiais/sem acento serve somente para comparação; o texto original permanece intacto.
- Cobertura adicionada para correções, continuidade, equivalências protegidas, normalização e passagem/cache de hotwords. A precisão editorial ainda precisa de um corpus de voz PT-BR anotado por humanos.

- A fila principal de limpeza agora exibe somente **Remover silêncios**, **Vícios de linguagem** e **Contexto**; “Edição completa” marca apenas esses três módulos.
- Silêncios reutiliza o Silero existente sem Whisper; Vícios reutiliza a transcrição do projeto ou executa somente Faster-Whisper; Contexto usa o mesmo VAD como metadado de pausas e não remove pausas por si só.
- Vícios e reformulações são analisados por regras Python determinísticas, sem Qwen/LLM. Contradições de negação, números escritos/digitais, ações opostas, continuidade e informação distintiva bloqueiam cortes automáticos.
- Resultados seguem para a revisão humana já existente e o corte permanece não destrutivo/undoável; os atalhos antigos para Silêncio/Vícios/Contexto também usam o novo motor local.
- Cobertura determinística dos sete conjuntos de opções e dos casos PT-BR está em `tests/test_automatic_cleanup.py`; instruções em `docs/LIMPEZA_AUTOMATICA_LOCAL.md`.

## Correção da narração silenciosa — 22/11/2026

- Gerar uma narração de Uma voz não encaminha mais PCM ao `QAudioSink`; o backend continua sintetizando e salvando o WAV, e a escuta só começa pelos comandos manuais.
- Removido o vínculo de chunks de áudio do dispatcher de tarefas da janela. A inserção de WAVs na timeline e a geração/regeneração multivozes não iniciam Play.
- Os controles **Ouvir narração**, **Ouvir última narração**, **Ouvir fala selecionada** e Play da timeline permanecem explícitos.
- Validado nos dois perfis Pure C aprovados, com 6 threads, pelo aplicativo Qt em modo offscreen; suíte completa: 393 testes aprovados.
- O validador Qt de multivozes agora também pode regenerar uma fala real e verificar os hashes dos WAVs não selecionados. Esta validação foi realizada com uma referência autorizada; teste com locutores distintos continua dependendo de perfis adicionais.

## Preparação do teste de aceitação com três locutores

- O validador offline aceita `--profile-v3` e monta o roteiro real de 100 falas na proporção V1/V2/V3 de 70/20/10; rejeita perfis não autorizados e gravações repetidas.
- O modo de 100 falas Qwen fica pronto para rodar com três referências autorizadas diferentes. Nesta máquina, apenas uma referência distinta está cadastrada; houve teste sintético de fila, não inferência Qwen com três locutores.
- A regeneração de uma fala agora tem cobertura de teste para o ripple dos blocos seguintes e Undo/Redo sem alterar os demais WAVs.

## Alternância multivozes sem recarga no perfil Native Q4

- O diagnóstico offline agora também mede `qwen3-tts-native-q4`, preservando executável e modelo instalados e isolando embeddings/cache temporários.
- Validado mesmo PID entre V1/V2, carga de modelo apenas no primeiro lote e WAVs não silenciosos; resultado documentado sem alegar locutores distintos.
- A aba Várias vozes explica que Pure C recarrega ao trocar perfil e que Native Q4 mantém o modelo residente, com preparação inicial de embeddings por perfil.
- Corrigido o botão “Preparar perfil” para usar o encoder de embedding Native Q4 e aquecer seu worker, em vez de chamar o preparador Original.
- Em roteiros Native Q4, embeddings ausentes são preparados em série antes da carga do servidor; uma instância de síntese atende todos os personagens, sem sobrepor modelos na memória.
- O projeto registra preparo vocal e carga do modelo separadamente; a UI exibe ambos junto ao RTF.
- Smoke real de troca V1→V2 confirmou o mesmo PID, 0 s de recarga entre falas, WAVs audíveis e preflight separado; smoke Qt real confirmou cache, clips, pausa, round-trip e exportação WAV sincronizada.

## Revalidação real do worker Original em multivozes

- Smoke offline gerou duas falas pelo Qwen3 Original usando um único PID e uma carga do modelo; o segundo prompt vocal foi servido sem recarregar pesos e teve acerto de cache.
- Métricas e limites documentados em `docs/NARRACAO_MULTIVOZES.md`. Foi usada a mesma gravação autorizada com dois IDs de teste; isso não comprova duas identidades vocais distintas.

## Multivozes: checkpoints isolados por execução e recuperação sem sobrescrever edições

- Cada fila em segundo plano agora escreve progresso em checkpoint próprio, sem competir com o checkpoint canônico editado pelo usuário.
- Na reabertura, checkpoints incrementais só restauram o estado das falas quando o fingerprint do roteiro corresponde ao projeto; título, início da timeline e perfis não usados vêm sempre do projeto atual.
- A retomada valida que o WAV de cada fala ainda existe e contém áudio antes de marcá-la como gerada; arquivos ausentes ou silenciosos deixam a fala pendente para regeneração.
- WAVs inválidos no próprio projeto também são reconciliados mesmo sem checkpoint. Um arquivo aprovado ainda válido é preservado se um checkpoint temporário apontar para uma saída defeituosa; estados `generating` interrompidos voltam como pendentes.
- Edições manuais atualizam o checkpoint canônico. WAVs concluídos de uma execução antiga continuam reaproveitáveis pelo cache, mas seus textos não substituem o roteiro atualizado.
- Teste cobre checkpoint de execução desatualizado, edição concorrente e recuperação do progresso quando os dados de síntese ainda coincidem.

## Validação offline de troca de referências entre lotes

- Reexecutado smoke real com Pure C INT8, Pure C Mixer e Original, usando dois trechos temporários da mesma referência autorizada. O Original manteve o worker/modelo; Pure C recarregou o runtime ao trocar a referência, conforme o limite do servidor instalado.
- Os três fluxos geraram WAVs não silenciosos na ordem V1→V2 e removeram seus artefatos temporários. O resultado está documentado como teste de troca/worker, sem alegar locutores distintos.

## Smoke reproduzível do cache de fala nos perfis Pure C

- Adicionado `scripts/validar_cache_voz_multivozes_real.py`, que exige confirmação da referência local, executa offline, valida um WAV próprio por alias e verifica uma única inferência para falas idênticas no mesmo perfil.
- Executado em Pure C INT8 e Pure C Mixer: `cache_hit=false/true`, arquivos separados com hashes iguais e sinais PCM não silenciosos. Métricas completas documentadas; a referência é da mesma pessoa, portanto não comprova identidades vocais diferentes.

## Smoke Qt real de multivozes e exportação WAV

- Adicionado `scripts/validar_multivoice_ui_cache_real.py` para gerar roteiro duplicado pela janela Qt real, conferir dois clips, salvar/reabrir projeto e exportar WAV do roteiro offline.
- INT8 e Mixer passaram com uma inferência, WAVs separados por fala, pausa de 200 ms preservada na timeline e exportação estéreo 48 kHz com duração sincronizada. V1/V2 usam intencionalmente o mesmo perfil autorizado; o smoke não valida vozes de locutores diferentes.

## Multivozes: cache compartilha síntese idêntica entre personagens da mesma voz

- A chave de síntese usa conteúdo e identidade/perfil vocal, sem depender do alias V1–V10.
- Falas com texto, perfil e backend idênticos reaproveitam o áudio pronto e copiam para um WAV próprio por fala, mantendo blocos independentes na timeline.
- Testes verificam uma única chamada de síntese, arquivos separados e conteúdo idêntico; o caminho usa o SHA-256 completo para identificar cache.
- Smoke offline com Qwen3-TTS Pure C INT8 confirmou uma síntese para duas falas iguais, WAVs independentes com hashes iguais, primeira saída em 0,491 s e inferência em 4,016 s (uma execução, sem atribuição de hardware).

## Multivozes: regeneração individual reaproveita a pasta de cache

- Regenerar uma fala mantém o ID do roteiro e escreve apenas seu progresso em checkpoint próprio; a nova síntese usa o cache persistente do roteiro, sem alterar o checkpoint canônico até a fala validar.
- A regeneração carrega somente o perfil associado à fala selecionada, mesmo se outros slots configurados tiverem perfis removidos ou indisponíveis.
- Após a troca validada, o checkpoint completo do roteiro é atualizado; os WAVs das demais falas continuam associados ao projeto.
- O checkpoint temporário daquela regeneração é removido somente depois que o resultado validado e o projeto foram salvos.
- Teste Qt verifica o ID/pasta preservados, o perfil usado e a integridade dos demais WAVs.

## Multivozes: inserção idempotente após geração em lote

- A conclusão de uma fila agora atualiza o bloco existente da fala, preserva posição manual e ajustes DSP e não cria duplicatas ao gerar novamente um roteiro.
- O roteiro enviado ao worker é uma cópia imutável. Se texto, vozes, ordem, pausa ou backend mudarem durante a síntese, a resposta antiga não substitui a edição recente.
- A interface carrega apenas os perfis associados a falas do roteiro; slots configurados mas não usados não bloqueiam a fila se seu perfil não estiver disponível.
- Inclusão de fala ausente e mudanças de duração abrem espaço apenas na sequência do próprio roteiro.
- Exceções ao aplicar resultados assíncronos agora são tratadas pelo fluxo de erro do editor, em vez de escapar do callback Qt.
- Testes cobrem idempotência, posição manual, DSP, bloqueio e fingerprint de entrada.

## Multivozes: ripple seguro ao regenerar uma fala

- A regeneração individual agora desloca apenas os clipes posteriores pertencentes ao mesmo roteiro, sem mover mídia independente nem outros roteiros na mesma camada.
- A operação é recusada quando o clipe-alvo ou uma fala seguinte está em camada bloqueada; isso evita reposicionamento parcial. A verificação é repetida quando o WAV novo fica pronto, caso o estado da timeline mude durante a síntese.
- Edição, remoção e reordenação de falas também respeitam camadas bloqueadas e restauram a lista salva sem aplicar uma alteração parcial.
- Testes cobrem preservação de mídia alheia e bloqueio atômico do ripple.

## Multivozes: cancelamento seguro da regeneração individual

- Adicionado teste de regressão que cancela uma síntese no meio da regeneração e verifica que o WAV aprovado continua byte a byte intacto, ligado à fala e presente no checkpoint recuperável.
- Validação direcionada passou; o roteiro permanece pendente para retomar a fala alterada.

## Pure C: serialização segura de preparação vocal

- Ao preparar uma referência sem x-vector em cache, o adapter agora serializa a extração com a inferência e encerra o servidor Pure C residente antes de iniciar o extrator. Isso evita duas instâncias do Qwen 0.6B ocuparem RAM simultaneamente em trocas para novos perfis.
- Após extrair e validar o vetor, o servidor do perfil selecionado é iniciado normalmente. Cache hit preserva o caminho aquecido já existente.
- Teste verifica a sequência parar → extrair → iniciar; evidência e limite de troca por perfil descritos em `docs/NARRACAO_MULTIVOZES.md`.

## Diagnóstico de troca de perfis multivozes

- Adicionado smoke offline que cria dois perfis temporários a partir de segmentos diferentes de uma gravação autorizada e mede troca real nos backends Pure C INT8 e Mixer, removendo os artefatos temporários ao final.
- A execução gerou WAVs não silenciosos e mostrou recarga do servidor/modelo por troca. Os segmentos são do mesmo locutor, então isso não certifica identidades vocais distintas; a validação aguarda o segundo perfil autorizado.
- Dois testes cobrem a seleção dos segmentos e rejeição de gravações silenciosas/curtas. Detalhes em `docs/NARRACAO_MULTIVOZES.md`.

## Branch `feat/qwen3-multivoice-narration` — Uma voz / Várias vozes

- A aba Narração agora separa os modos Uma voz e Várias vozes. Pure C INT8 e Pure C mixed são destacados com os identificadores instalados e seis threads; os modos Original e Q4 continuam em Outros perfis.
- Adicionado parser determinístico Berofel Script V1, associação de até dez personagens a perfis locais autorizados, prévia em tabela e fila serial agrupada pelo perfil de voz. Cada fala gera WAV individual e a timeline recebe os blocos na ordem narrativa, com pausa configurável.
- Adicionados IDs permanentes, JSON de roteiro no projeto, checkpoint incremental para retomada, cache por texto/perfil/backend/runtime e edição, reordenação, inserção, remoção e regeneração individual sem apagar a versão de áudio aprovada.
- Adicionadas ações para salvar WAV individual e exportar o roteiro completo pelo grafo de áudio já usado pelo editor.
- **Limite:** o servidor Pure C atual fixa o x-vector na inicialização; ao trocar de perfil, a fila serial reinicia esse único servidor/modelo. O carregamento único entre personagens exige suporte do runtime que não existe no binário instalado.
- Validação real pela interface em roteiros de 100 falas nos perfis Pure C INT8 e Pure C Mixed: WAVs individuais, 100 clips em ordem, salvamento/reabertura, WAV completo e MP4 (Mixed). Resultados, limites de uma única voz autorizada disponível e métricas estão em `docs/NARRACAO_MULTIVOZES.md`.
- Regeneração real de uma fala preservou os outros WAVs e suportou Undo/Redo. Adicionado teste de geração/união de fala segmentada. A troca real entre perfis de pessoas diferentes permanece sem validação porque havia apenas um perfil vocal autorizado no ambiente.
- O painel multivozes agora avisa quando personagens usam perfis Pure C diferentes, pois cada troca exige reinício e recarga do servidor/modelo.
- Para roteiros com vários perfis sem recarga entre personagens, o painel explica que Original reutiliza um worker e até 64 prompts vocais em memória, com a contrapartida de inferência mais lenta.
- Incluído smoke real offline para Original com timeout e cache temporário; a primeira tentativa travou na importação do Qwen e motivou a correção de startup, seguida da validação real registrada abaixo.
- O worker Original agora informa as fases de inicialização PyTorch/Qwen/pesos na interface e devolve erros de carga ao editor, sem ocultá-los como espera indefinida.
- A carga local do Qwen evita importar o pacote completo librosa/numba; a compatibilidade para load, soxr e filtros mel segue as APIs usadas pelo Qwen, e a saída mel foi comparada com a implementação instalada.
- Após a correção, o backend Original Qwen foi validado por uma sessão offline nova: prompt vocal persistido reaproveitado, WAV audível inserido na timeline, player, exportação WAV/MP4 e projeto reaberto; latência fria observada ficou documentada como fallback lento.
- O smoke de dois lotes Original passou offline com o mesmo worker/PID e apenas uma carga do modelo; o segundo prompt foi recuperado do cache persistente. As duas IDs usaram a mesma gravação, então isso não valida vozes distintas.
- Adicionado smoke opt-in com duas referências artificiais para medir troca de perfil Pure C em INT8 e Mixer, incluindo preparação, recarga, primeiro áudio e geração; não é teste de identidade ou qualidade vocal.
- O editor visual aceita trocar uma fala para qualquer perfil já configurado, mesmo que o personagem ainda não apareça no roteiro importado; perfis extras não usados não impedem a geração.
- O painel avisa quando personagens diferentes apontam para o mesmo perfil vocal, deixando explícito que eles terão a mesma identidade de voz.
- O painel também detecta perfis distintos criados da mesma gravação de referência, usando o SHA-256 já persistido no manifesto, para não sugerir identidades diferentes por IDs duplicados. A suíte completa passou: 359 testes aprovados, 4 ignorados.
- Auditoria do código upstream Pure C (`qwen_tts_server.c`/`qwen_tts.h`) confirma que `speaker` seleciona slots preset e que o contexto carrega um único x-vector clonado; não há campo de embedding por requisição. Registrar essa fronteira evita tratar a recarga por personagem como cache ou como recurso já concluído.
- Smoke offline para dois perfis reais agora isola a seleção dos perfis: exige autorização explícita, IDs diferentes e hashes de gravação distintos. Testes cobrem as recusas e o caminho válido sem carregar modelo nem acessar perfis reais.

## Validação local Turbo sem proxy externo

- Fluxo UI→Qwen Pure C mixed→timeline→WAV/MP4 repetido com proxy externo indisponível em `127.0.0.1:9`, loopback liberado e Hugging Face offline. Gerou clipe de 4,32 s em 9,869 s e exportou WAV/MP4 com áudio e vídeo. A sessão não tinha privilégio de administrador; portanto isso não substitui o teste com regra de firewall de saída.

## Operação Qwen Turbo — correção de transcrição em perfis salvos

- Perfis de voz existentes agora permitem atualizar e persistir apenas a transcrição de referência, sem regravar nem substituir a amostra, alterar autorização ou recriar o perfil. No modo Original, o prompt vocal é preparado de novo com a transcrição atualizada.
- Testes de serviço e interface cobrem persistência após reabertura, preservação da gravação/autorização e despacho do prewarm; validação direcionada: 13 testes passaram.
- A chave do cache do prompt inclui o hash da transcrição: a correção produz um prompt novo sem reutilizar o condicionamento anterior.

## Correção incremental — referências de voz com pausas longas

- A verificação de gravação agora recomenda outra amostra quando mais de 50% do áudio estiver quase silencioso; ao escolher o arquivo, o painel mostra esse aviso sem alterar a gravação original.
- Validado com o perfil local atual (55,3% quase silencioso) e com teste Qt; suíte: 312 aprovados, 1 ignorado.

## Atualização do fluxo de voz — diretriz Qwen Base único

- Rota canônica de narração migrada para `services/narration_service.py`; qualquer backend legado diferente do Qwen3-TTS Base é rejeitado. Pocket TTS deixa de ter worker, dependências e atalhos de instalação na árvore executável. Modelos, perfis, projetos e áudios já presentes no PC não foram removidos.
- O painel separa o uso rápido de perfis preparados da clonagem detalhada, valida localmente duração, nível, clipping e silêncio da referência e mantém a exigência de transcrição/autorização. A gravação original é somente lida; o perfil recebe uma cópia privada.
- A voz usa `create_voice_clone_prompt` e `generate_voice_clone`; o cache NPZ versionado, sem pickle, é reutilizável entre inicializações e invalidado pelo fingerprint da amostra, texto e modelo. Worker CPU persiste aquecido durante a sessão.
- A autorização explícita é registrada junto ao perfil ao salvar/confirmar; perfis antigos sem esse estado pedem confirmação uma vez, e os perfis autorizados não exigem novo clique em cada narração rápida.
- A configuração padrão é 4 threads CPU + 1 thread inter-op, baseada na medição anterior do Ryzen 7 5700G (uma execução: 62,53 s/RTF 6,06 com 4 threads contra 66,78 s/RTF 6,47 com 8). INT8/INT4, backend nativo e streaming incremental seguem desativados por falta de validação compatível com clonagem e qualidade.
- Adicionada verificação técnica de referência e cobertura de cache persistente/seleção única do modelo nos testes.
- Worker Qwen e benchmark agora separam carregamento do modelo, preparação/reuso do perfil vocal e inferência; o benchmark também amostra CPU normalizada e RSS do processo e filhos.
- Os validadores Qt e DSP aceitam referência sintética para smoke tests reais offline de Qwen, player, timeline e exportação sem alegar identidade vocal.
- Preparação de prompt permite o modo oficial x-vector-only sem transcrição; o benchmark sintético curto/médio/longo registra carregamento, prompt, geração, RTF, RSS e CPU. Ver resultados e limites no relatório técnico.
- Clonagem detalhada pode gerar sem transcrição de referência usando o caminho x-vector-only oficial; transcrição continua exigida ao salvar um perfil para narração rápida reutilizável.
- O smoke test Qt agora aciona a ação real Gerar no painel Narração, e não injeta diretamente uma requisição no controlador. Com referência sintética, Qwen offline percorreu player, timeline, WAV, MP4 e salvar/reabrir projeto em 35,7 s; isso valida integração, não semelhança vocal.
- Um segundo smoke test prepara um perfil local temporário pela mesma sessão Qwen e gera pela biblioteca rápida da UI; o metadado confirmou reutilização do prompt, um único worker/modelo, e o fluxo de player/timeline/WAV/MP4/projeto terminou em 32,7 s. Referência sintética não valida identidade vocal.
- O smoke test rápido agora encerra o worker após preparar o perfil e o reinicia antes da geração; a segunda sessão recuperou o prompt persistido (cache hit; um carregamento do modelo) e concluiu o fluxo offline em 40,4 s. Isso simula a fronteira de sessão do worker, não a avaliação de voz pessoal.
- A referência configurada foi validada com Qwen real na UI e na rota rápida usando uma cópia de perfil temporária; geração, player, timeline, WAV/MP4 e projeto passaram offline. O original permaneceu sem alteração, e os artefatos temporários foram removidos ao fim.
- Um benchmark local de cosine do encoder de speaker foi adicionado, sem persistir ou imprimir gravação, texto ou caminho. O resultado é documentado como proxy técnica, nunca como prova perceptiva de identidade.
- Os testes Qt agora usam diretórios QSettings temporários e restauram a configuração global ao terminar; isso impede gravações acidentais no perfil Windows do usuário.
- O fluxo real autorizou a criação local do perfil “Minha voz Qwen3 Base” e cache de prompt persistente; em um processo novo, o perfil foi relido e o condicionamento preparado reutilizado. A cópia é privada em AppData; o arquivo de origem e as preferências existentes foram preservados.
- Uma segunda instância Qt gerou com o perfil persistido sem nova preparação vocal; cache hit, modelo carregado uma vez, saída não silenciosa e exportações WAV/MP4 offline passaram em 65,4 s de fluxo total.
- Histórico de performance continua em `docs/BENCHMARK_QWEN3_TTS_20261118.md`; a semelhança perceptiva ainda requer avaliação auditiva pelo usuário, pois o cosine do encoder não é prova de identidade.

## 0.10.0-alpha.1 — restauração do Qwen3-TTS (18/11/2026)

- Diretriz de motor único: somente Qwen3-TTS Base 0.6B no fluxo padrão. Worker persistente carrega uma vez por sessão e reutiliza prompt de clonagem versionado. Benchmark Ryzen 7 5700G/16 GB: RTF 6,47 (curto) e 5,76 (longo), pico RSS 6,41 GiB; não é tempo real. INT8/INT4, streaming e backend nativo permanecem não qualificados. Ver `docs/BENCHMARK_QWEN3_TTS_20261118.md`.
- Comparação pontual do texto curto: 4 threads mediram 62,530 s/RTF 6,06 e RSS 5,73 GiB; 8 threads mediram 66,776 s/RTF 6,47 e RSS 6,41 GiB. O padrão local foi reduzido a 4 threads; são medições únicas, não um ótimo universal.

- Qwen3-TTS Base 0.6B passa a ser o único motor selecionável e padrão para novas narrações. Novas solicitações exigem amostra de referência autorizada e transcrição; Pocket TTS não é mais carregado pelo painel nem instalado pelos instaladores padrão. Seus arquivos/caches existentes não são apagados.
- Corrigido o caminho de instalação isolado do Qwen3 com `imageio-ffmpeg`, usado para normalizar referências; geração mantém `local_files_only` e modo offline após o download inicial.
- O worker limitava nenhuma geração curta: a API do Qwen aplicava o default de 2048 tokens também a uma frase, o que produziu timeout no CPU. Agora `max_new_tokens` é estimado pelo tamanho do texto e limitado a 2048.
- Perfis de voz Qwen persistem a gravação privada e a transcrição de referência. A gravação de origem permanece intacta.
- O instalador principal e `INSTALAR_TODAS_AS_IAS.bat` pedem confirmação explícita antes do download do modelo de voz (~2,5 GB); setup é isolado e reutilizável.
- Evidência real offline no Windows: referência local salva + transcrição produziram WAV mono 24 kHz, 10,96 s, sinal válido, em 72,2 s (pico agregado amostrado 5,76 GiB). No fluxo real da janela Qt, a chamada Qwen nova inseriu narração na timeline, reproduziu/buscou pelo player (saída silenciada para o teste), exportou WAV e MP4 com áudio/vídeo, decodificou áudio não silencioso do MP4 e salvou/reabriu o projeto; fluxo completo 49,2 s. A transcrição e os caminhos privados não são registrados.
- 1.7B, semelhança perceptiva/biométrica, execução em rede bloqueada por firewall e reprodução audível pelos alto-falantes não foram validados; o worker de inferência foi validado offline com pesos já instalados.

## 0.10.0-alpha.1 — atualização local de prévia

- O instalador principal agora oferece configurar o Pocket TTS local no mesmo fluxo. A confirmação antecede a instalação das dependências CPU potencialmente grandes; os pesos gated de clonagem só são baixados após confirmação separada de que os termos oficiais já foram aceitos. O BAT dedicado continua disponível para instalação/reparo.
- O worker Pocket TTS passou a operar em modo estritamente offline durante a geração: pesos ausentes causam instrução clara para ativar a clonagem, sem download de rede implícito. A aquisição continua no autorizador explícito.
- Pocket TTS agora é a opção inicial para novas configurações de clonagem; preferências Qwen já salvas são mantidas durante a etapa de transição.
- `docs/CLONAGEM_LOCAL_POCKET_TTS.md` registra a auditoria do backend Qwen no ZIP antigo, a diferença entre síntese local e download inicial de modelo e o estado real de validação da clonagem pessoal.
- Ações IA e Narração saem do cabeçalho e permanecem na navegação lateral; Legendas abre um inspector fixo à direita, sem diálogo de texto, com lista de cues, edição, estilo, posição e presets.
- O instalador Qwen prepara `imageio-ffmpeg` também no ambiente Python isolado, necessário ao worker para normalizar a amostra de referência; a validação de TorchAudio respeita a ABI estável oficial.
- Qwen agora tenta uma vez novamente quando a resposta não segue o JSON esperado, reconhece alguns formatos equivalentes e mantém a validação estrita dos IDs de palavra. Se continuar inválida, reporta lote/tamanho sem expor a transcrição; outras etapas permanecem preservadas.

## Experimento Qwen Turbo — 19/11/2026

- Adicionado perfil Q4 Equilibrado (8 threads) ao lado do Q4 Turbo (6 threads), configuráveis por ambiente; Original permanece o padrão e fallback.
- Narração agora mantém histórico das duas últimas gerações para comparação A/B na própria área, sem inferir novamente o áudio anterior.
- Sweep repetido no Ryzen 7 5700G: Q4 a 6 threads mediana de RTF 0,944; 8 threads RTF 0,978 e menor RSS amostrado (2,264 GiB vs. 2,555 GiB). WER Whisper é proxy e a qualidade subjetiva ainda aguarda avaliação.
- Testes reais no runtime local geraram voz com ambos os perfis; os dados, condições e limitações estão em `docs/QWEN3_TURBO_EXPERIMENT_20261119.md`.
- Corrigida a troca de perfil nativo: o processo agora encerra por EOF (o comando JSON de shutdown anterior não era suportado pelo servidor). A alternância medida entre 6 e 8 threads caiu de 5,923 s para 0,981 s; a nova comparação inédita manteve RTF 0,945/0,973.
- Comparação offline pareada com texto e referência iguais contra o Qwen oficial: RTF 5,992 (Original), 0,964 (Turbo) e 0,985 (Equilibrado). WER é apenas proxy em uma frase; os condicionamentos do Original e nativo Q4 diferem e essa comparação não prova fidelidade vocal.

- Adiciona motor opcional Qwen3-TTS Base 0.6B para clonar voz de referência localmente em CPU, sem login ou gate; download inicial explícito, ambiente Python isolado e botão de preparação na aba Narração.
- A interface permite transcrever opcionalmente o áudio de referência para melhorar a clonagem, preserva a confirmação de autorização e separa essa rota da voz rápida de catálogo Pocket TTS.
- Adiciona cache local por conteúdo, worker offline após a instalação, saída WAV durável e testes sintéticos de fluxo, cache e privacidade. Não baixou nem executou os pesos reais nesta sessão; desempenho/qualidade ficam pendentes de validação no PC após a preparação.

- Combos, controles numéricos e sliders da interface não mudam ao rolar um painel: a roda só altera o controle focado e, sem foco, segue para o painel rolável pai.
- O worker Pocket TTS distingue IDs de catálogo de perfis `.safetensors` do usuário, mantém a validação dos pesos de clonagem e salva o estado derivado da amostra em cache privado local para não reexecutar o encoder a cada narração. O áudio de referência não é alterado nem enviado. O gate/aceite dos pesos oficiais continua obrigatório na primeira preparação.
- Adiciona o Clipador Inteligente: ranking revisável de candidatos a partir de transcrições existentes e análise PCM streaming (RMS/pico/clipping), cache persistente, prévia pelo monitor do editor, ajuste de limites em palavras e inserção/marcadores reversíveis na timeline. Não dispara Whisper/Qwen nem modifica arquivos-fonte. Detalhes e limitações em `docs/CLIPADOR_INTELIGENTE.md`.
- Testes sintéticos cobrem limites e timestamps absolutos, cache/invalidação, fallback sem áudio/transcrição, sinais RMS/eventos, streaming FFmpeg, integração do botão/diálogo, fila em segundo plano, inserção com Undo e marcadores com Undo.
- A ativação de clonagem agora pré-verifica o checkpoint completo antes do carregamento do Pocket TTS, que poderia cair silenciosamente nos pesos de catálogo. O diagnóstico separa bloqueio de rede/firewall de falta de login/aceite HF e aparece no próprio painel; não registra token nem envia áudio de usuário.
- Os quatro presets CC0 Voice-Zero agora usam os IDs de estados precomputados do Pocket TTS, que funcionam com pesos de catálogo sem passar WAVs pelo encoder gated. O instalador pré-carrega os estados portugueses quando a rede permite, encerra tentativas redundantes após falha de rede, deixa de baixar WAVs de referência e preserva qualquer arquivo legado já existente.
- Qwen escolhe threads separadas do Whisper: com pelo menos 16 CPUs lógicas, 15 GiB totais e 6 GiB disponíveis, usa até 75% das CPUs (máximo 12); com 12–15 CPUs e a mesma margem usa até metade (máximo 8); em hardware com menos margem conserva o perfil econômico/equilibrado. O `llama-server` reutiliza o prefixo fixo do prompt; API e CLI usam semente fixa 42 com temperatura 0 para repetir melhor a amostragem.
- Checkpoints de lote Qwen agora incluem fingerprint do texto do lote, IDs, modelo e executáveis llama.cpp (caminho/tamanho/data), versão do prompt, ação e parâmetros de inferência; texto editado com IDs preservados ou atualização do backend não reutilizam uma decisão antiga. O cache da etapa também inclui esses fingerprints.
- O diagnóstico do autorizador Pocket TTS reconhece `LocalEntryNotFoundError` como ausência de checkpoint no cache quando o Hub não está acessível, orientando a verificar rede antes de repetir a ativação.
- Workers do Pocket TTS/Qwen e o teste de narração configuram stdout/stderr para UTF-8 no Windows, evitando que erros com acentos virem `UnicodeEncodeError` quando o console usa CP1252.
- Adiciona regressão automatizada que inicializa os dois workers sob CP1252 e confirma que mensagens de erro com caracteres acentuados continuam em UTF-8.
- O instalador Pocket TTS agora informa separadamente se a clonagem pessoal foi validada ou se apenas as vozes de catálogo estão prontas, evitando mensagem de sucesso ambígua quando os pesos gated não estão disponíveis.
- Adiciona teste de integração do worker de clonagem com amostra e modelo sintéticos, verificando normalização mono/24 kHz, condicionamento, geração do WAV final, remoção do temporário e preservação byte a byte da referência original.
- `TESTAR_POCKET_TTS.bat --clone` agora executa, após a autorização dos pesos, uma síntese real pela rota de voz personalizada com referência sintética local, sem gravação pessoal.
- O validador Qwen mede carga do modelo e duração de cada lote, e aceita `--threads` para comparar perfis. No PC atual, 800 palavras passaram offline em 141,76 s com 12 threads/seed 42 (lotes 60,73/59,78/19,53 s), contra 147,88 s com 8 threads e 172,61 s com 4 threads; perfil automático passou com 12 threads em 22,06 s para 100 palavras. A saída com 12 threads repetiu as 27 propostas; 8 threads retornou 38. O cache de prefixo e o paralelismo podem alterar logits entre perfis, então os cortes continuam sujeitos à aprovação humana.
- StageRunner remove o JSON de progresso do Qwen de tentativas anteriores antes de retomar e também o limpa em falhas/timeouts, evitando que o cabeçalho mostre um lote antigo como se a IA ainda estivesse trabalhando.
- Adiciona teste de ciclo completo do corte aprovado: pares AV e legendas sobreviventes são salvos e reabertos com IDs, tempos, grupos e texto preservados.
- Depois de aprovar cortes da IA, os trechos resultantes permanecem selecionados e a timeline os traz para a área visível sem mudar o zoom; isso destaca os blocos preservados e os espaços criados pelos cortes.
- O botão de ativação da clonagem agora acompanha o processo do Hugging Face e informa no painel se o teste sintético confirmou o encoder ou se a autorização falhou; o autorizador fecha automaticamente quando aberto pelo editor, sem reter a janela em `pause`.
- O BAT da raiz desempata instalações com o mesmo SemVer pela data mais recente dos módulos-fontes relevantes (ignorando caches e logs) e pelo caminho, garantindo que cópias novas da mesma versão sejam selecionadas de modo previsível.
- O worker de narração agora exige confirmação explícita da capacidade de clonagem no modelo Pocket TTS; APIs incompatíveis falham com instruções em vez de serem presumidas como compatíveis.
- A timeline sincroniza o retângulo de navegação do `QGraphicsView` após reconstruir a cena, recalculando a barra horizontal para projetos/cortes maiores; Ctrl+roda aplica zoom mantendo o ponto sob o cursor.
- Ao limpar a sequência, a cena agora zera também o retângulo e os limites das barras horizontal/vertical, evitando que uma timeline vazia conserve rolagem do projeto anterior.
- A regressão da barra compacta verifica porcentagem centralizada, descrição da etapa em fonte menor e altura máxima de 53 px no cabeçalho.
- A velocidade pelo painel de Narração tem teste de integração que comprova retiming do par AV vinculado e das legendas automáticas, com Undo/Redo preservando a sincronização.
- O smoke test nativo de 300 cortes agora mede pixels no quadro recebido e no monitor exibido; não declara sucesso apenas pela contagem de sinais de vídeo.
- `TESTAR_PREVIEW_WINDOWS.bat` agora falha se o widget receber quadros pretos ou não exibir imagem; o script nativo passou com dois vídeos sintéticos e brilho médio de 84,7 na entrada e no monitor.
- O cache de narração inclui a versão instalada do Pocket TTS e SHA-256 de amostras de voz personalizadas; alteração de motor ou conteúdo não reaproveita WAV sintetizado obsoleto.
- O cache TTS tem poda LRU configurável (`BEROFEL_TTS_CACHE_MAX_MB`, padrão 2048 MiB), remove apenas entradas identificadas como próprias, preserva o item em uso e apaga outputs parciais antigos; JSONs temporários do worker são limpos após sucesso ou falha.
- Com pitch e velocidade de narração ativos juntos, o motor combina tempo e pitch em um passe Rubber Band com formantes preservados, evitando dois time-stretch em cascata.

- Inicia o módulo real de Ajuste Fino: EQ de graves/médios/agudos por clipe no painel Narração, pitch independente de ±4 semitons e controle de velocidade de 0,70× a 1,30×. EQ/pitch têm bypass; o estado por clipe é não destrutivo, salvo no projeto e desfeito com Undo. O grafo compartilhado da prévia/exportação aplica FFmpeg `bass`, `equalizer`, `treble`, `alimiter`, `asetrate`, `aresample`, `atempo` e `rubberband` quando disponível, sem nova inferência TTS. Testes espectrais medem as bandas; teste sintético confirma pitch e duração preservada dentro da tolerância e exportação MP4 com o pitch aplicado.
- Adiciona exportação da mixagem da timeline em WAV PCM sem perdas pelo grafo de áudio compartilhado, com validação automatizada do WAV PCM 24-bit/48 kHz contendo EQ.
- Ao alterar EQ ou pitch durante a reprodução, a prévia atualiza os filtros nomeados via `azmq` quando disponíveis, sem reiniciar FFmpeg; a integração mede o sinal e confirma 440 Hz → aproximadamente 415 Hz para pitch −1 st → 440 Hz com bypass. Se `rubberband`/`azmq` não estiver disponível, a prévia volta do playhead com o grafo atualizado. Os passos da velocidade são quantizados a 0,05×.
- Presets próprios de voz agora podem ser salvos, renomeados, recarregados e excluídos. O arquivo local usa JSON com versão de schema e guarda somente parâmetros DSP.
- O painel de Narração permite copiar EQ, pitch, bypass, preset e velocidade de um clipe e colar em outro como uma única ação de Undo; velocidade fora do intervalo do painel não substitui a do destino.
- A colagem não bloqueia EQ/pitch quando um clipe AV vinculado está bloqueado e velocidade/preservação já coincidem; se alterar o tempo do par, a operação é rejeitada inteira para evitar dessincronização.
- Velocidade ajustada no painel de Narração ativa preservação de pitch via filtro Rubber Band quando presente e detectado no FFmpeg; a exportação usa o mesmo caminho. Sem o filtro, mantém `atempo` e avisa sobre a alteração de pitch.
- Pitch deslocado usa o filtro Rubber Band em modo tempo fixo e com formantes preservados quando o build de FFmpeg o disponibiliza; builds sem esse backend mantêm o fallback `asetrate`/`atempo`.
- Corrige o adaptador do worker Pocket TTS para encaminhar `rafael` como ID de voz predefinida, sem tratá-lo como um arquivo local; adiciona teste de regressão e uma validação offline completa TTS→DSP→WAV/MP4.
- Limita a extração do estado vocal de referências longas a 30 segundos usando a opção `truncate` da API Pocket TTS; a amostra original permanece intacta.
- Atualiza o BAT de autorização para o CLI atual `hf auth login` e testa a codificação de uma amostra sintética temporária antes de declarar a clonagem pronta; o probe recusa pesos somente de catálogo e não usa áudio do usuário.
- Fortalece a validação de ajuste fino com comparação amostra a amostra entre prévia e WAV, além da diferença de duração entre áudio/vídeo e decodificação do MP4.
- Processamento de pitch passa pelo limitador de segurança mesmo quando o EQ está neutro; teste de nível alto confirma o teto sem clipping inesperado.
- Mostra a seção de Ressonância Vocal desabilitada com explicação: a build atual só oferece preservação/alteração automática de formantes junto ao pitch, não controle independente.
- EQ do clipe selecionado agora atualiza filtros nomeados no processo de áudio ativo via FFmpeg `azmq`; só a banda alterada gera comando. O editor limita o backlog de áudio, cancela a janela pré-carregada com valores antigos e mantém os ajustes por projeto para os trechos seguintes.
- Os comandos de EQ ao vivo agora rodam em worker dedicado, fora do thread Qt, e coalescem movimentos rápidos para aplicar o valor mais recente por clipe. Se o canal ZMQ falhar, o editor recompõe a prévia no playhead com os parâmetros salvos.
- Acrescenta PyZMQ ao núcleo para controle local em loopback, teste de integração contra FFmpeg ativo e medidor sintético de latência/RSS em `scripts/medir_eq_ao_vivo.py`; avisos de licença estão em `docs/THIRD_PARTY_NOTICES.md`.
- Corrige o diagnóstico da clonagem: o Pocket TTS pode cair em pesos apenas de catálogo se os pesos gated não forem autorizados/baixados. O painel oferece link dos termos e botão para abrir `AUTORIZAR_POCKET_TTS.bat` num terminal interativo; o diálogo de erro também traz os passos necessários. O autorizador não marca mais o modo catálogo como clonagem pronta. Rascunho, voz, idioma, caminho da amostra, título e quantização persistem localmente, sem memorizar o aceite de autorização; a MainWindow também salva imediatamente ao fechar. Amostras MP3/FLAC/OGG/M4A são decodificadas pelo FFmpeg incluído para WAV mono PCM16 temporário de até 30 s; os originais não são alterados. Vozes `.safetensors` e catálogo seguem sem conversão.
- Cortes aprovados da IA e aparos manuais agora mantêm vídeo e áudio separados vinculados sincronizados; faixa bloqueada impede alteração parcial, e cada trecho sobrevivente recebe seu próprio grupo. Velocidade e análise de seleções AV vinculadas também evitam duplicar ou desincronizar o par.
- Ao aparar um clipe, legendas automáticas agora acompanham as palavras que restaram na fonte; cues sem palavras sobreviventes são removidos, e texto revisado pelo usuário é preservado e desvinculado quando seu trecho sai do clipe.
- Se uma legenda revisada atravessa um corte e não cabe em um trecho sobrevivente, o texto continua no projeto como legenda manual sem âncora obsoleta.
- Acrescenta regressão para a política Silero: pausas menores que o limite não viram cortes, os intervalos mantêm margem de segurança e regiões de fala sobrepostas são unificadas.
- A barra da Batata Quente agora acompanha os lotes textuais concluídos pelo Qwen, mostrando clipe, lote atual e estado. O avanço dentro de uma inferência individual permanece estável até o lote terminar.
- Adiciona o símbolo da marca enviado pelo usuário como asset SVG escalável no cabeçalho, com gradiente azul/coral e nome acessível para leitores de tela.
- Reduz a saída do Qwen para 320 tokens, limita cada inferência a 5 minutos e cada análise de clipe a 18 minutos por tentativa, mostra o clipe em andamento e retoma os lotes já salvos no cache.
- Alinha `scripts/testar_qwen_real.py` ao mesmo limite calculado por lote usado pelo editor; o teste manual informa o limite aplicado em vez de poder aguardar duas horas.
- Analisa a resposta JSON final do Qwen, ignora o exemplo ecoado pelo llama-cli e recupera apenas itens completos quando a saída é truncada; IDs, ordem e confiança continuam validados. Qwen local passou offline com 800 palavras sintéticas.
- Reorganiza o cabeçalho para “Berofel Studio”, remove o fluxo redundante de etapas e exibe o progresso compacto no topo, com porcentagem na barra e etapa em texto menor; durante ocioso, a barra some para liberar espaço do editor.
- Move as ferramentas de timeline para uma faixa vertical ao lado da Biblioteca, com rolagem própria, nomes acessíveis e dicas completas; a timeline fica sem a antiga barra horizontal de ferramentas.
- Ajusta os rótulos da faixa vertical para símbolos e abreviações legíveis no espaço disponível; nomes completos permanecem nas dicas e na acessibilidade. Captura nativa confirma a interface durante uma tarefa Qwen simulada.
- Oculta as barras dos painéis, listas, ferramentas, propriedades e editores de texto sem desativar a rolagem por roda/trackpad; preserva as barras horizontal e vertical da timeline (a vertical aparece quando necessária).
- Envia a transcrição completa de cada clipe ao Qwen como lotes somente de `{id,text}`, com sobreposição de contexto; o modelo devolve IDs a remover e o editor calcula os tempos usando Whisper. Usa `llama-server` local para manter o modelo carregado entre lotes, com fallback para `llama-cli`, e salva cada resposta no cache para retomar falhas.
- Documenta a regra editorial do Qwen e a fórmula de conversão Whisper→corte em [FLUXO_QWEN_TEXTO_E_TIMESTAMPS.md](docs/FLUXO_QWEN_TEXTO_E_TIMESTAMPS.md); aprovações continuam manuais e os cortes são reversíveis.
- Corrige a rolagem horizontal da timeline pela roda/trackpad também quando o cursor está sobre os cabeçalhos de faixa; adiciona controles de página esquerda/direita.
- Em janelas estreitas, oculta qualidade e volume do transporte quando não cabem, evitando sobreposição dos controles de reprodução.
- Se Qwen falhar (incluindo `WinError 206`), a fila registra e mostra a falha, mas continua com as transcrições e legendas das etapas concluídas; falha de Qwen não bloqueia legendas nem cancela cortes Silero já revisáveis.
- Mantém `ABRIR_BEROFELSTUDIO.bat` na raiz selecionando automaticamente o launcher válido da versão mais nova encontrada.
- Regressão Qt da interface, navegação horizontal e ferramentas: 49 testes passaram; suíte completa local: 225 testes passaram no Windows com Qt offscreen.
- O passo legado “Revisar” reabre sugestões pendentes e preserva marcações no projeto/autosave; antes de cortar, valida a identidade e o intervalo dos clipes analisados para recusar resultados obsoletos após edição manual.
- Qwen cria prompts em pasta curta com nome único, tentativas limitadas e fallback para TEMP quando `%LOCALAPPDATA%` não permite escrita; elimina a espera sem fim ao iniciar a etapa.
- Transições que afetam clipes com áudio separado agora são atômicas: se qualquer faixa de áudio vinculada estiver bloqueada, rejeitam a operação antes de mover o vídeo ou aplicar fades; a mensagem explica como desbloquear.
- Distingue na barra da timeline o modo de arraste `Slide [G]` do ajuste numérico `Slide ±s`; tooltip e nome acessível deixam explícito que o segundo recebe segundos.
- A recuperação só oferece autosaves mais novos que passam pelo loader do projeto; snapshots truncados ou de versão incompatível não impedem a abertura do projeto original nem alteram seus bytes.
- O fluxo de abertura reutiliza o objeto de recuperação já validado, evitando recarregar duas vezes projetos grandes antes de exibi-los.
- Adiciona opção reversível “Preservar tom ao alterar velocidade” no inspector de áudio. O FFmpeg `rubberband` mantém o pitch ao acelerar/desacelerar; prévia e exportação usam o mesmo grafo, com estado salvo no projeto.
- Propaga a opção de preservar tom entre áudio e vídeo vinculados, inclui o estado ao separar áudio e desfaz a alteração do par AV numa única operação.
- No Windows, Qwen usa caminhos curtos 8.3 para `llama-cli`, modelo GGUF e prompt quando o volume os fornece; em `WinError 206`, o relatório identifica o comprimento de cada caminho e orienta a mover executável/modelo para uma pasta curta sem alterar os originais.
- Limita a memória do cache de waveforms a 96 tiles LRU e ativa poda periódica dos thumbnails/waveforms persistentes acima de 256 MB; somente artefatos finais reconhecidos da timeline são elegíveis, preservando originais e arquivos desconhecidos.
- Ao fechar a janela, interrompe o decoder FFmpeg da cache visual e aguarda a thread encerrar (incluindo a corrida de inicialização), sem gravar artefatos parciais.
- Adiciona ferramenta Slide à timeline: desloca o clipe entre vizinhos contíguos, preserva os limites externos da sequência, ajusta trechos de fonte conforme speed, mantém grupos AV/legendas automáticas sincronizados e rejeita mudanças em faixas bloqueadas ou bordas inválidas; Undo restaura o estado completo.
- Adiciona modo de arraste Slide [G] na timeline: encaixa o clipe deslocado quando o ímã está ativo e pré-visualiza em vídeo/áudio as três bordas compensadas sem alterar o projeto antes de soltar; confirma vizinhos/grupo AV como uma única operação, [V] volta à seleção e Ctrl+Z desfaz.
- Aproxima a revisão do layout legado: a janela de sugestões fica à direita e o botão “Ver trecho no monitor” busca a sugestão com contexto e reproduz pela prévia/timeline principal, convertendo o offset da fonte pela velocidade do clipe; não cria um segundo player.
- Limita a prévia de revisão ao fim do trecho sugerido e posiciona o cursor nesse limite; pausar ou buscar manualmente cancela o limite e preserva os controles normais.
- Adiciona curva Bézier com controles C1/C2 ajustáveis no inspector; editar os pontos do keyframe é reversível, e Python/FFmpeg usam a mesma fórmula.
- Mantém na composição clips válidos abaixo de 80 ms: teste FFmpeg confirma que legenda de 0,05 s e áudio continuam sincronizados na prévia e no MP4 a 3×, 4× e 10×.
- Adiciona “Aprovar e aplicar TODOS” à revisão de IA; um clique marca e envia todos os cortes aprovados ao fluxo existente, inclusive sugestões ocultas por filtro, com Undo do projeto.
- Permite excluir keyframes de qualquer propriedade pelo menu de contexto do próprio marcador; a operação respeita faixas bloqueadas e pode ser desfeita.
- Separa marcadores de keyframes por propriedade e permite retimar qualquer canal animável na timeline; preserva valor/easing, aplica snap e bloqueia colisões com undo por operação.
- Aplica o ímã de timeline ao arrastar keyframes de volume e alças de fade; alinhamento considera playhead, marcadores, bordas de clipes vizinhos e limites do clipe, e funciona também com o snap desligado.
- Torna cortes de grupos AV atômicos diante de faixas bloqueadas: não divide só vídeo ou só áudio, preserva links e evita snapshots vazios; seleção mista ainda divide clipes independentes editáveis.
- Mostra as rampas de fade de áudio na timeline com curva verde-clara e alças arrastáveis para mudar a duração; os ajustes seguem a duração após speed, combinam-se à automação de volume, atualizam o mesmo modelo da prévia/exportação e podem ser desfeitos.
- Adiciona botões e atalhos de quadro anterior/próximo no monitor (`,` e `.`), com avanço pelo FPS do projeto e timecode `HH:MM:SS:FF`; transporte compacto se adapta a monitores estreitos sem sobrepor controles.
- Endurece o BAT raiz contra sufixos de versão desconhecidos: compara alpha, beta, rc e estável em ordem SemVer, ignora instalações incompletas e não trata `-dev` como versão estável; há regressão PowerShell com instalações de teste.
- Permite arrastar os pontos dourados da automação de volume diretamente na timeline; valores e tempo local são atualizados com snapshot para Undo, e colisões com outro keyframe são recusadas.
- Adiciona exclusão de ponto de automação de volume pelo menu de contexto do próprio nó, também reversível com Undo.
- Refaz o estado vazio do monitor com o fluxo visual do editor legado: ícone de reprodução, instrução clara e botão laranja de importação; o modo compacto mantém a ação visível em monitores com pouca altura e encaminha o clique ao importador do app atual.
- Corrige a chamada de importação cortada no canvas curto e registra captura nativa do Windows; a raiz mantém um launcher que seleciona a versão mais nova pelo `berofel.__version__`.
- Torna redimensionável e persistente a divisão vertical entre área do editor/monitor e timeline; a faixa Batata Quente permanece no meio, sem sobrepor nenhum painel, e a proporção escolhida é restaurada ao reabrir.
- Adiciona “Restaurar layout padrão” ao menu Projeto; recupera os tamanhos dos painéis, a aba Assistente IA e o zoom padrão da timeline sem modificar clipes ou mídia.
- Mantém Selecionar [V] e Lâmina [B] sempre visíveis na barra da timeline; o estado laranja dos botões acompanha clique e atalhos, eliminando a dependência de uma barra global oculta.
- Adiciona integração FFmpeg com tom audível e legenda automática vinculados à fonte após mudança de velocidade: ambos aparecem entre 0,50–0,75 s na prévia e no MP4 a 2×, com silêncio/sem legenda fora do intervalo.
- Desenha a automação de volume como curva dourada dentro do clipe de áudio/vídeo; a linha usa o tempo local após velocidade, mantém os pontos no retângulo do clip e explica no tooltip como arrastar keyframes.
- Ao selecionar clipes de áudio, oculta as alças de transformação visual da prévia; o clipe segue selecionado e editável na timeline.
- Ajusta os rótulos da Biblioteca abaixo de 245 px para manter título e ações legíveis em 800×620; tooltips preservam a descrição completa e a janela restaura os rótulos longos ao ampliar o painel.
- Coloca as páginas Mídia e Marcadores da Biblioteca em áreas de rolagem vertical; em alturas reduzidas, os filtros e ações continuam acessíveis sem mudar a posição dos painéis. Teste cobre os botões Importar/Relink no modo compacto.
- Captura nativa no Windows (plugin Qt `windows`) confirma a composição da janela em 1366×768 e 800×620; a menor largura também foi verificada após o ajuste responsivo.
- Revalida a reprodução com `QT_SCALE_FACTOR=1.5` no plugin Windows: 30 quadros, playhead avançando e decoder de áudio iniciado com 300 cortes. A área de trabalho desta máquina limitou a janela a 909×499 lógico (1364×749 pixels); a tela física 1920×1080 não está disponível neste monitor.
- Protege instalação e retomada contra atualização do venv em uso: um pré-check local identifica `python.exe`/`pythonw.exe` do `%LOCALAPPDATA%\\BFS\\venv`, informa os PIDs e pede para fechar o editor; não encerra nenhum processo. Ambos os instaladores foram exercitados e pararam antes de tocar dependências enquanto o editor estava ativo.
- Estende o bloqueio seguro aos instaladores opcionais Whisper/Silero, Pocket TTS, Qwen e FFmpeg; `INSTALAR_TODAS_AS_IAS.bat` verifica uma vez antes de iniciar a fila. O modelo Qwen agora é baixado para um candidato, tem SHA-256 validado antes de entrar no caminho ativo e um modelo existente com hash divergente nunca é apagado.
- Adiciona smoke test Windows reproduzível com FFmpeg sintético: a MainWindow real inicia a prévia com 300 cortes, recebe quadros e inicia o decoder de áudio; a captura acontece durante a reprodução, com volume zerado e preferências Qt isoladas em diretório temporário.
- Reconstrói a barra superior como componente Qt separado, usando a marca e o fluxo Importar → Analisar → Revisar → Exportar do legado, com ações conectadas à janela e ao motor multitrilha atuais.
- Extrai a biblioteca para `LibraryDock` com navegação lateral Mídia/Marcadores, pesquisa, filtros por tipo, arraste para a timeline e navegação por marcadores do projeto.
- Substitui controles verticais do preview por transporte horizontal com início/fim, saltos de 5 s, timecode, qualidade, volume e quadro final; os sinais atuam sobre a `LivePreview` canônica.
- Reestiliza a timeline com superfícies grafite, grade de baixo contraste e seleção/playhead laranja, mantendo waveforms e thumbnails do cache sob demanda.
- Remodela a revisão de cortes como cartão de assistente local com motivo, navegação por sugestão e decisões “Manter/Cortar”, preservando seleção em massa e corte reversível.
- Acrescenta filtros por tipo e texto ao diálogo de revisão em massa; navegação segue apenas os resultados visíveis, seleção visível preserva marcações ocultas e “Selecionar TODOS” continua abrangendo todas as sugestões.
- Coloca o Assistente IA na primeira aba do inspetor, com estado local visível; mantém Propriedades e Narração em abas laterais e destaca a fila de edição em laranja.
- Reorganiza o inspetor em grupos recolhíveis para bloco/tempo, movimento, cor/recorte, aparência, áudio e keyframes; os controles continuam conectados ao mesmo projeto e motor de edição.
- Conecta o atalho de ferramentas “Cor e recorte” ao grupo correspondente no Inspetor do clipe, em vez de exibir um placeholder de efeitos; brilho, contraste, saturação e recorte continuam gravados no projeto canônico.
- Adiciona slip de fonte pelo botão da timeline e menu contextual: desloca vídeo/áudio vinculados sem mudar duração/posição, limita às bordas do arquivo e permite Undo; legendas automáticas da janela antiga são invalidadas e textos revisados manualmente são preservados.
- Adiciona edição roll pela barra da timeline e menu contextual: ajusta a emenda entre clipes adjacentes sem alterar a duração externa do par, mantém áudio separado vinculado, keyframes/legendas acompanham as janelas de fonte e Undo restaura o corte.
- Ao separar áudio, preserva fades, filtros, keyframes de volume e a mixagem (ganho, pan, mute e solo) da faixa de origem; Undo restaura o vídeo com áudio incorporado.
- Transições em vídeo com áudio separado agora deslocam o clipe de áudio vinculado junto com o overlap e aplicam crossfade nas duas faixas de áudio; prévia PCM e MP4 exportado foram verificados. Estilos inválidos são rejeitados antes de alterar a timeline.
- Prompts do Qwen usam `%LOCALAPPDATA%\\BFS\\tmp`, com caminho curto previsível no Windows; há fallback para a pasta temporária do sistema se o perfil não permitir criação. Os prompts continuam em arquivos limitados por lote para evitar `WinError 206`.
- Adiciona `scripts/testar_qwen_real.py` para repetir o teste offline de 800 palavras com o modelo local e validar o caminho curto de prompt.
- O launcher da raiz agora varre as pastas de instalação, valida os componentes da interface e escolhe a maior versão lida em `berofel/__init__.py`, sem depender do sufixo numérico da pasta.
- Erros Qwen `WinError 206` agora abrem um diálogo não modal com instruções para o launcher atual e caminhos curtos; a exceção original permanece expandível, a edição continua acessível e o relatório completo segue no painel Batata Quente.
- Localiza os controles do aviso Qwen em português e dimensiona “Mostrar detalhes” pelo texto; captura offscreen confirma que o rótulo não é cortado.
- Adapta contexto e tamanho de lote do Qwen à RAM disponível: 2K/4K em perfis econômicos, 8K em configuração equilibrada e 16K em workstation; modelo, contexto e tamanho de lote identificam o cache. Threads continuam ajustadas ao hardware.
- Valida a invalidação seletiva do cache Qwen quando contexto muda: Whisper/VAD permanecem reutilizados e somente Qwen é reexecutado.
- Aplica o perfil adaptativo também às exportações FFmpeg: filtros usam os limites de preview e o encoder reserva de 1–2 threads em economia, até 6 em equilíbrio e até 16 em workstation.
- Remove rótulos de versão obsoletos dos instaladores; o instalador principal lê `berofel.__version__` da pasta escolhida. O relatório de validação 0.3 passa a identificar-se como histórico e aponta para os resultados 0.10 atuais.
- Integração Windows gera um MP4 curto após separar áudio: FFprobe confirma vídeo/áudio e duração; PCM estéreo confirma pan à esquerda e fades de entrada/saída preservados.
- Adiciona Ctrl+C/Ctrl+V e ações no menu contextual: cola os clipes no playhead com IDs e vínculos novos, inclui áudio agrupado/legendas ancoradas e mantém Undo/Redo; o arquivo de origem não é duplicado nem alterado.
- Compacta a faixa Batata Quente quando ociosa: medição Qt a 1366×768 reduziu a altura reservada de cerca de 110 px para 28 px, liberando espaço vertical para preview/timeline. Ao iniciar uma tarefa, os controles e métricas reaparecem.
- Recalcula as larguras da barra da timeline depois do tema Qt, mantendo visíveis os rótulos completos “Dissolvência” e “Separar áudio”; em telas estreitas, a barra continua rolável.
- Mantém o título da timeline em uma linha e localiza o rótulo do monitor como “PRÉVIA”; conferido em captura Qt a 1366×768 contra as referências do ZIP legado.
- Dá nomes acessíveis aos controles de cada camada e diferencia as cores ativas de ocultar imagem, silenciar, solo e bloqueio, preservando as mesmas ações de faixa.
- Desenha o progresso do fluxo Importar → Analisar → Revisar → Exportar com conectores contínuos e estados distintos de etapa concluída, atual e seguinte.
- Em larguras abaixo de 1180 px, recolhe apenas atalhos duplicados do topo (Analisar também está no fluxo; Narração permanece na aba do inspetor), mantém Projeto/Salvar/Exportar e os quatro passos legíveis, e compacta o transporte da prévia sem sobrepor tempo, qualidade e volume. A aba de ações também reflowa campos/atalhos e não exige rolagem horizontal.
- Registra as fontes Segoe UI, Segoe UI Symbol e Segoe UI Emoji do Windows quando o plugin Qt não detecta fontes do sistema; em janelas estreitas, encurta visualmente as abas do Inspetor, mas mantém nomes completos em dicas acessíveis. A timeline agora expõe rolagem vertical quando as faixas excedem a altura, sincronizada com os cabeçalhos, e barras de rolagem usam a paleta grafite/laranja do editor.
- Repete a regressão responsiva do Qt com `QT_SCALE_FACTOR=1.5`: os controles continuam dentro dos painéis em 800×620, 1024×768, 1366×768 e 1920×1080. É uma verificação lógica do Qt offscreen; não representa medição de DPI nativo numa sessão Windows interativa.
- Persiste tamanho da janela, proporções dos painéis Biblioteca/Preview/Inspector, aba aberta do inspetor, qualidade e volume da prévia, zoom da timeline e estado do ímã entre inicializações.
- Corrige o envio de transcrições extensas ao Qwen no Windows: prompts passam por arquivos temporários em vez de argumentos de linha de comando, são divididos em blocos limitados com sobreposição de palavras e usam contexto de 8192 tokens. A versão do prompt no cache foi elevada para refazer resultados incompatíveis.
- Acrescenta stress da prévia em timeline sintética de 80 minutos com 800 cortes: 30 posições distribuídas têm comandos preparados e áudio/vídeo são decodificados no início, meio e último minuto. O BAT de stress identifica a versão instalada/local dinamicamente e descreve esta cobertura.
- Corrige o autoteste `testar_whisper_real.py` para incluir a raiz do app no `sys.path`, permitindo que o BAT de validação importe o worker real.
- Faz `TESTAR_POCKET_TTS.bat` executar offline e testar duas sínteses reais em português; WAVs, projeto e cache de teste ficam em `TemporaryDirectory` e não são gravados em Documentos do usuário.
- Endurece a validação das respostas Qwen: IDs precisam ser strings contíguas na ordem original, e confiança malformada/infinita descarta apenas a proposta inválida sem interromper o worker.
- Confirma em execução Windows offline com llama.cpp real que a etapa Qwen processa 800 palavras pelo worker no perfil adaptativo equilibrado (8K/16.384 caracteres), retorna JSON sem `WinError 206` e usa os prompts curtos sob `%LOCALAPPDATA%\\BFS\\tmp`.
- Fortalece a regressão Qt de edição durante a Batata Quente com um worker real bloqueado na thread pool: divide e desfaz um clipe enquanto o worker continua ativo, depois confirma que a fila é liberada ao concluir.
- Exercita a MainWindow com 300 cortes sequenciais e áudio: confirma quadros e PCM, avanço até a janela seguinte e seek no meio da timeline. Corrige a limpeza de diretórios temporários quando a janela fecha enquanto leitores FFmpeg ainda encerram; cancelamento após o worker produzir um resultado também limpa recursos temporários aninhados.
- Atualiza `ABRIR_BEROFELSTUDIO.bat` para mostrar a versão, a pasta de código e o caminho do módulo Python realmente carregado, validar os módulos visuais atuais, priorizar essa cópia local no `PYTHONPATH` e oferecer `--verificar` sem abrir outra janela.
- Centraliza a versão do app em `berofel.__version__` e usa esse valor no título da janela.
- Drena `stderr` do FFmpeg em paralelo, preserva os últimos diagnósticos e encerra sua thread ao parar a prévia.
- Normaliza timestamps do áudio após filtros de velocidade e atraso de faixa; seek acelerado e mixagem compartilhada por prévia/export mantêm os pontos temporais alinhados.
- Seleciona threads de FFmpeg e IA conforme núcleos e memória disponível, com perfis automáticos de economia, equilibrado e desempenho.
- Cortes não destrutivos mantêm fades de áudio apenas nas bordas originais do clipe.
- Legendas automáticas guardam âncora de fonte, acompanham velocidade/movimento/trim e são repartidas por palavra quando split/corte cruza um cue; texto editado e legendas manuais são preservados.
- Ao abrir projeto com autosave mais novo e diferente, oferece recuperação sem substituir o original; o projeto recuperado continua salvando no caminho canônico.
- Serializa snapshots de autosave em worker Qt, sem bloquear a interface nem iniciar gravações concorrentes.
- Descarta snapshots quando o projeto foi salvo manualmente após a captura; autosave e salvamento manual compartilham bloqueio de arquivo.
- Marca arquivos ausentes na biblioteca e permite relink manual de fonte; clipes e transcrições acompanham o caminho, enquanto a cobertura de IA antiga é invalidada.
- Acrescenta mixer por faixa com ganho e balanço estéreo, aplicado pela composição comum de prévia e exportação e preservado por undo/save/load.
- Acrescenta solo de áudio por faixa, respeitado na prévia e na exportação sem ocultar o vídeo; a ação pode ser desfeita e o estado persiste no projeto.
- Ao fechar a janela, para o debounce de quadro e ignora erros de workers atrasados, evitando alertas modais após o fechamento.
- Limita a espera do FFmpeg ao gerar ondas da timeline; um decoder travado é encerrado e não deixa o worker visual preso indefinidamente.
- Adiciona regressões para mixer/solo de faixa, relink de mídia ausente, emenda AAC de export fragmentado (20 s/40 cortes), sincronismo de áudio após seek em velocidade 2×, recuperação Qt de autosave, legendas após cortes, reprodução Qt/FFmpeg em duas janelas, 300 cortes sintéticos, fades e cancelamento do leitor de erros.
- Exercita a conexão MainWindow → LivePreview → widget do monitor com MP4 sintético de vídeo+áudio: quadros chegam ao canvas, o pipe PCM alimenta o relógio, o cursor avança até o fim e o botão retorna ao estado parado.
- Adiciona navegação anterior/próximo entre keyframes da propriedade ativa no Inspetor; os botões refletem os limites disponíveis e movem prévia/cursor sem alterar o histórico do projeto.
- Acrescenta stress de 500 cortes sequenciais: confirma janela limitada a no máximo 28 segmentos concorrentes, comando FFmpeg abaixo do limite do Windows e geração efetiva de quadros e PCM; mantém o caso de 300 com exportação completa.
- Validação local em 16/11/2026: 139 testes automatizados passaram no venv Windows (Python 3.12.10), incluindo reflow/rolagem vertical da Biblioteca em janela compacta, invalidação seletiva do cache Qwen por perfil, perfis de threads de exportação, limites adaptativos de contexto/lote Qwen, recuperação Qwen `WinError 206` não modal, caminho curto persistente para prompts, transição com áudio separado na prévia e exportação, roll com áudio separado, revisão filtrada, edição não destrutiva, recuperação, 300 cortes na MainWindow e layout responsivo. A suíte de stress de prévia cobre 300 cortes com export MP4/FFprobe, 500 cortes com pipes limitados e timeline sintética de 80 min/800 cortes com 30 seeks preparados e decodificação de áudio/vídeo no início, meio e último minuto. Silero/Whisper, Qwen e Pocket TTS também foram executados localmente conforme `docs/VALIDACAO_IA.md`. Os testes longos usam mídia sintética e não substituem a gravação original de 80 minutos, cuja execução integral permanece pendente.
- Validação local de IA em 16/11/2026: Silero+Whisper executados pelo pipeline real com cache 3/3 na segunda passagem; Whisper real offline com WAV PCM16; Qwen real pelo StageRunner com 800 palavras sintéticas, sem WinError 206; Pocket TTS real offline produziu WAV de 3,28 s e reaproveitou o cache na segunda chamada, com todo o teste em diretório temporário. O texto sintético não mede qualidade editorial/perceptiva. A execução integral do projeto de 80 minutos permanece pendente.
- Regressão responsiva adicional sob `QT_SCALE_FACTOR=1.5`: passou em 800×620, 1024×768, 1366×768 e 1920×1080 (Qt offscreen; sem alegação de validação de DPI nativo interativo).

## 0.9.2 — prévia após cortes da IA (Windows)

- Evita `FileNotFoundError [WinError 206]`: a prévia FFmpeg gera somente janelas limitadas por densidade de clipes e comprimento do comando, em vez de todos os clipes restantes.
- Pré-carrega a próxima janela enquanto a atual toca, avançando automaticamente na timeline; mensagens e timeout impedem travamento silencioso.
- Cache dos metadados de mídia (FFprobe) por caminho, tamanho e data de modificação.
- Exportação de projetos muito fragmentados por janelas codificadas e unidas sem recodificação de vídeo; preserva fontes e cache.
- A validação `TESTAR_PREVIA_092.bat` cobre 300 cortes sintéticos: limite do comando, decodificação dos pipes de vídeo/áudio e export MP4 com duração/streams conferidos por FFprobe.

---

## 0.9.1 — hotfix 13/11/2026

- Corrige falha Whisper 1.2.1 / PyAV 19 `metadata_errors`, usando diretamente áudio PCM16 lido via NumPy.
- Corrige seleção do ZIP Windows CPU x64 do llama.cpp quando a `releases/latest` não oferece binários.
- Mantém transcrição em lote, cache, Batata Quente e todas as ferramentas da versão 0.9.
- Acrescenta testes de regressão e bat para verificação real do Whisper instalado.

# BerofelStudio 0.9 — Edição combinada, fila inteligente e cortes em massa

- Diálogo de sugestões: seleção total e desmarcação total de um clique, contador e opção de continuar sem cortes.
- Aba Ações IA: grupo de checkboxes, preset Edição completa, visualização da ordem e botão Aplicar Edição.
- Orquestrador `batch_editing.py`: Silero primeiro, Whisper reaproveitando somente janelas de fala (opcional), Qwen com transcrição pronta e resultados em cache por etapa.
- Reportes com tempos absolutos preservados em blocos acelerados, divididos e em seleção In/Out; legendas geradas após os cortes aprovados.
- Edição e preparo de prévia independentes da fila de IA; não aplica resultados a blocos alterados durante um processo.
- Adicionados testes do orquestrador, cache dependente, remapeamento e verificação `TESTAR_FILA_09.bat`.
- GUI Windows e inferências reais de modelos continuam pendentes de teste. O ZIP antigo 5.0 fornecido contém apenas um coletor, não a UI antiga.

---

# BerofelStudio 0.8.1 — Compatibilidade FFmpeg (13/11/2026)

- Corrigida opção `-filter_complex_script`, removida no FFmpeg 9.
- Adicionado detector de compatibilidade: FFmpeg antigo usa `-filter_complex_script`; moderno usa `-/filter_complex`.
- Alteração aplicada ao vídeo e áudio da prévia, à exportação MP4 e ao quadro isolado.
- Filtragem permanece em arquivo, evitando o limite de tamanho de comando no Windows.
- Nova suíte de regressão: `TESTAR_CORRECAO_FFMPEG_081.bat`.
- Modelos, transcrições, cache e projetos antigos preservados.

# Novidades da versão 0.8 — ações independentes e escopos

- Nova aba fixa **⚙ Ações IA** com seletor de um bloco, múltiplos blocos, faixa, intervalo global, intervalo da faixa ou projeto inteiro. Resumo prévio de duração e quantidade.
- Pipeline específico por ação: transcrição sem Silero; Silero sem transcrição; legendas Whisper sem Qwen; Qwen sem Silero. A análise contextual é somente leitura, sem aplicar cortes.
- Criação de legendas automáticas e manuais como clipes de texto editáveis; SRT filtrado por escopo e com legendas editadas.
- Cache de cobertura do Whisper no projeto com fingerprint de arquivo, modelo, idioma e intervalo de fonte; reutilização após divisão, mudança de velocidade e faixas. Processamento repetido de áudio/vídeo do mesmo trecho deduplicado.
- Resolução correta de recortes In/Out com velocidade alterada; propostas nunca saem do bloco original.
- Monitor Batata Quente, pausa/cancelamento e instaladores anteriores mantidos.
- Testes novos de escopos, cache, retiming, Qwen independente, SRT/legendas editáveis e duplicação de fontes.
- Limitação de validação: GUI PySide6 e inferência real dos modelos não foram executadas neste ambiente Linux.

---

# BerofelStudio Studio 0.7 — Edição profissional de precisão (13/11/2026)

- Velocidade de reprodução de **0,25× a 10×** por clipe, alterando vídeo, áudio, duração e tempos de legendas; FFmpeg `setpts` + `atempo` encadeado.
- Keyframes persistentes de posição X/Y, escala, opacidade, volume e rotação, com interpolação linear, ease-in, ease-out e suave. Prévia e exportação partilham filtros de composição FFmpeg.
- Transições por sobreposição com dissolvência, slide e zoom; fades de vídeo e áudio.
- Snapping (ímã), ripple delete, marcadores, botões de zoom/ajustar timeline, atalhos J/K/L, M, F, S e menus contextuais.
- Arraste de posição diretamente na prévia, Ctrl+roda para escala; inspector com cor, recorte, rotação, filtros de voz, propriedades temporais.
- Agrupar/desagrupar, separar áudio vinculado ao vídeo, dividir/retimar preservando pares de grupo.
- Waveforms e miniaturas produzidas por janela visível, cache persistente no disco e thread dedicada.
- Proxies H.264 opcionais e não destrutivos, gerados sob demanda; apenas a prévia usa proxy, exportações usam os originais.
- Mantém sistema Batata Quente, IA selecionada sob demanda, narração Pocket TTS, monitor fixo e instaladores anteriores; **não exige novas dependências Python** além da base 0.6.
- Testes de integração FFmpeg e de persistência/sincronismo adicionados. **Ainda falta homologação da interface e instalação em Windows real.**

---

# BerofelStudio 0.4 — Batata Quente IA

- Inclusão de `ai_cache.py`: cache versionado com fingerprint de fonte/intervalo/configurações e gravação atômica.
- Inclusão de `ai_worker.py`: processos independentes para FFmpeg/PCM16, Silero VAD/ONNX, Faster-Whisper e Qwen/llama.cpp.
- Inclusão de `ai_pipeline.py`: orquestração somente dos blocos selecionados; reaproveitamento por etapa; resultados e tempos de origem.
- Inclusão de `subtitles.py`: transcrições persistentes no JSON do projeto e SRT sincronizado após cortes.
- Interface com Transcrever IA, Silero+Whisper, Qwen Contextual e Exportar SRT. Revisão antes dos cortes.
- Novos instaladores opcionais e autoteste Windows: INSTALAR_TODAS_AS_IAS.bat, INSTALAR_QWEN_OPCIONAL.bat e TESTAR_BATATA_QUENTE.bat.
- Testes de cache, seleção, invalidação, JSON Qwen, remapeamento temporal e migração preservados.

> As IAs com modelos reais e os instaladores do Windows requerem validação local. Nenhuma meta de velocidade foi certificada nesta versão.

---

# BerofelStudio Studio 0.3 — Mudanças em relação à Alpha 0.2

- Prévia **ao vivo** da composição (FFmpeg BGRA + PCM + Qt) substitui reprodução isolada do bloco. Play/Pause seguem o tempo da timeline.
- Mistura simultânea de áudios vindos de qualquer camada e combina vídeos, imagens e títulos na ordem definida pelo usuário.
- Pipeline de preview recorta o projeto a partir do cursor **antes** de decodificar, preservando os tempos de origem. 640/960/1280px ajustáveis.
- Quadro final usa janela local para evitar renderizar toda a história desde 0s durante o scrubbing.
- FFmpeg exportação com feedback real de progresso, saída temporária atômica e bloqueio para sobrescrever mídia original.
- Preview MP4 de reserva na barra ☰ quando live falha.
- Instalador Windows prepara Python + VC++ + PySide6 + Pillow + FFmpeg, verifica os binários e realiza autoteste com 2 vídeos e áudio; Faster-Whisper em .bat separado.
- Launcher escreve tracebacks de falha no diretório `logs`.
- 14 testes automatizados do núcleo e composição + diagnóstico CLI.
- MLT/Pocket TTS/Silero VAD **não** integrados; experiência Windows depende de teste real no usuário.

## Studio 0.5 — Narração Pocket TTS e vozes autorizadas (13/11/2026)

- Painel **Narração** fixo na lateral direita, com botão permanente no cabeçalho.
- Editor de texto livre: narrar textos inéditos independentemente da transcrição.
- Botão para aproveitar as palavras transcritas dos blocos selecionados.
- Seleção de idioma, voz, amostra particular e confirmação de consentimento.
- Catálogo de quatro vozes de amostra CC0 da coleção oficial Voice-Zero:
  Bill Boerst, Caro Davy, Peter Yearsley e Stuart Bell. Downloads no instalador.
- Voz oficial brasileira/portuguesa Rafael como preset, sem redistribuir seu áudio.
- Geração em subprocesso isolado que descarrega o modelo após o trabalho.
- Cache persistente por texto/voz/idioma/quantização; cópia durável para mídia do projeto.
- WAV pode ser ouvido, salvo ou colocado na timeline numa camada universal `Narração`.
- Instaladores `INSTALAR_POCKET_TTS.bat`, `INSTALAR_TODAS_AS_IAS.bat` atualizado,
  `AUTORIZAR_POCKET_TTS.bat` e `TESTAR_POCKET_TTS.bat`.
- **Limitação de instalação:** pesos do Pocket TTS em `kyutai/pocket-tts` podem
  exigir que o próprio usuário aceite as condições no Hugging Face e faça login.
- Os 25 testes automatizados de lógica e infraestrutura passaram no Linux; a
  execução com PyTorch e o comportamento visual do Qt no Windows exigem teste real.
- Ainda não há substituição automática/fonema a fonema da fala original:
  narrações entram em faixa separada para posicionamento e mixagem manuais.

## Studio 0.6 — Visualizador universal de processos (13/11/2026)

- Faixa fixa **BATATA QUENTE** entre a prévia e a timeline, sem sobreposição.
- Progresso por trechos/etapas concluídas, percentual, tempo ativo, estimativa
  aproximada quando disponível, etapa corrente e CPU/RAM do editor mais filhos.
- Botões **Pausar/Continuar** e **Cancelar** na mesma faixa para todas as tarefas
  longas: Whisper, Silero, Qwen, Pocket TTS, silencedetect, corte de blocos,
  render de quadro, preview MP4 e exportação MP4.
- Gerenciador de processos `ProcessControl` com psutil para suspender/retomar e
  encerrar **árvores de subprocessos**, inclusive no Windows.
- Suspensão do relógio de tempo ativo e dos limites de timeout durante pausa.
- Exclusividade: somente um trabalho pesado por vez (Batata Quente), sem impor
  limite artificial de RAM/CPU em máquinas mais fortes.
- Checkpoints já finalizados permanecem no cache após cancelar; exportações
  parciais são limpas e não substituem um arquivo final anterior.
- Detalhes recolhíveis e **Copiar relatório** com os tempos por etapa.
- `TESTAR_PROCESSOS.bat` valida pausa/retomada/cancelamento/cache no Windows.
- Novos testes de extração real via subprocesso controlado, cancelamento real, pausa temporal,
  reaproveitamento do cache após interrupção e segurança da exportação.
- Interface Qt e comportamento com modelos reais continuam precisando de
  validação num computador Windows com o programa instalado.
- O diagnóstico de ativação do Pocket TTS agora separa checkpoint ausente no cache sem acesso ao Hub, conexão bloqueada, token inválido, aceite gated pendente, arquivo/revisão incorreta e transferência interrompida.
- A ativação iniciada pelo painel de Narração não abre mais CMD: pede confirmação dos termos e token mascarado no editor, envia o token ao worker local por stdin e não o coloca em argumentos ou logs.

## Operação Qwen Turbo (branch experimental)

- Adicionada rota opcional Qwen3-TTS.cpp Base 0.6B Q4_0 misto para narração rápida, com perfil vocal x-vector preparado pelo próprio encoder nativo e cache local versionado. O backend oficial Python permanece como padrão/fallback; Turbo não é selecionado automaticamente.
- Adicionados benchmark dos estágios oficiais, instalador runtime com verificação e backup antes de substituir, conversor Q4 experimental separado, testes de áudio e seleção do painel. Na primeira etapa o servidor retornava WAV completo; o callback incremental foi conectado ao player de áudio Qt nos commits seguintes desta branch.
- Validação local no Ryzen 7 5700G/16 GB: Q4 mediana RTF 1,047 (3 repetições; pico RSS mediano 1,947 GiB) versus oficial RTF 5,184 (uma medição). É uma comparação experimental com áudio gerado estocástico; WER ASR não substitui escuta/avaliação de qualidade. Detalhes, hashes, procedimento de backup e limites em `docs/QWEN3_TURBO_EXPERIMENT_20261119.md`.
- Adicionado streaming experimental por callback nativo: primeiro PCM em 3,062 s após modelo/perfil prontos (3,849 s desde o início da chamada, incluindo carga), encaminhado ao `QAudioSink` durante a geração; um fluxo real do editor/offscreen escreveu 453.120 bytes PCM16 para 9,44 s de áudio no sink simulado e inseriu o WAV na timeline. Avaliação auditiva da voz continua pendente.
- O transporte de chunks e a conclusão agora são emitidos pela mesma thread Qt; o teste de UI confirmou PCM16 integral para a duração do WAV. O runtime Turbo local foi reconstruído com `stream_file`; o backend oficial não foi modificado.

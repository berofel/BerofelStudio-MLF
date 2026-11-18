> **Versão de testes local 0.10.0-alpha.1:** cabeçalho com o símbolo Berofel Studio enviado pelo usuário, progresso compacto sem stepper redundante e ferramentas da timeline numa faixa vertical junto à Biblioteca, com abreviações visíveis e nomes completos acessíveis. A roda/trackpad e os botões de página percorrem a timeline horizontalmente, inclusive sobre os cabeçalhos de faixa. O Qwen informa o bloco em andamento, limita o tempo por trecho e reaproveita no cache as etapas concluídas; o parser ignora o exemplo ecoado e recupera decisões completas de respostas truncadas. Inclui aprovação em massa, keyframes Bézier, sincronismo de legendas/áudio, recuperação e exportação fragmentada; reprodução longa ainda requer validação manual.

O `ABRIR_BEROFELSTUDIO.bat` dentro desta pasta inicializa o código local, exibe o caminho e a versão detectada, confere os módulos da interface e prioriza esta cópia. No pacote de trabalho, use também o atalho da raiz `C:\Users\Berofel\Desktop\BerofelStudio_codigo_base_alpha\ABRIR_BEROFELSTUDIO.bat`: ele localiza launchers válidos, lê a versão de cada fonte e escolhe a maior, inclusive quando a atualização está em outra pasta de versão. Execute `ABRIR_BEROFELSTUDIO.bat --verificar` para conferir o launcher sem abrir a janela.
>
> **Base funcional 0.9.2 (Windows):** Corrige `WinError 206` e a espera prolongada da prévia após centenas de cortes. Reproduz a timeline em janelas com pré-carregamento da seguinte, reutiliza FFprobe e exporta projetos muito fragmentados por partes. Veja `docs/CORRECAO_092_PREVIA_300_CORTES.md`.

> **Hotfix 0.9.1 (Windows):** veja `docs/CORRECAO_091_WHISPER_QWEN.md` para testar o conserto de `metadata_errors` no Whisper e a busca de releases do llama.cpp para Qwen. Não é preciso reinstalar os modelos já baixados.

# BerofelStudio 0.10.0-alpha.1 — editor multitrilha com IA local

> **Versão de testes local para Windows.** A interface foi reorganizada a partir das referências do editor antigo e conectada ao motor multitrilha atual. A timeline inclui ferramentas verticais ao lado da Biblioteca, rolagem horizontal pela roda/trackpad sobre as faixas e botões de página; barras visíveis ficam restritas à timeline. O Qwen recebe a transcrição em texto/IDs, mantém o modelo carregado entre lotes via `llama-server` local (com fallback para `llama-cli`), devolve IDs a remover e o editor calcula intervalos pelos tempos do Whisper; lotes concluídos são retomados pelo cache. Os cortes aguardam aprovação e são reversíveis. Slip, Roll e Slide também são não destrutivos. A prévia e timeline não mudam de lugar durante o progresso. O EQ ao vivo envia comandos fora do thread Qt e coalesce alterações sucessivas dos controles; integração com FFmpeg ativo confirmou atualização sem bloquear nem reiniciar o processo. O pitch usa Rubber Band com preservação de formantes quando disponível. O painel de voz copia e cola seus parâmetros entre clipes com Undo. Referências longas de voz são limitadas a 30 s durante a extração do estado vocal, sem alterar o arquivo original. O fluxo local Pocket TTS→DSP→WAV/MP4 passou offline com perfil de catálogo; a prévia e o WAV coincidiram amostra a amostra no ensaio sintético. A ativação de clonagem pré-valida os pesos completos para não confundir fallback de catálogo com clone; distingue problema de rede de acesso gated e apresenta o diagnóstico no painel. Os presets Voice-Zero usam IDs precomputados; o worker verifica pesos completos antes de carregar o modelo ao pedir uma voz pessoal. A suíte local tem 300 testes aprovados. Silero/Faster-Whisper, Qwen e Pocket TTS têm execuções offline registradas em `docs/VALIDACAO_IA.md`. Os testes usam mídia sintética e não certificam qualidade editorial em gravações reais; a sessão completa com o projeto original de 80 minutos ainda não foi validada.

## Novidades

- **Clipador Inteligente:** sugere trechos para clipes usando a transcrição salva e medidas reais de RMS/pico/clipping extraídas em PCM por streaming. Mostra evidências e alertas, permite pré-visualizar, ajustar os limites em palavras, marcar eventos acústicos e adicionar os trechos selecionados à timeline sem alterar a fonte. Não inicia Whisper/Qwen, não promete viralização e exige revisão/seleção manual. Veja [como usar e os limites](docs/CLIPADOR_INTELIGENTE.md).
- **Roda sem alterações acidentais:** idioma, voz, propriedades, sliders e spins só mudam pela roda quando estão focados; ao percorrer painéis, a roda continua rolando a área. A clonagem Pocket TTS guarda o estado da amostra no cache local para reutilização; consulte [preparação e execução local](docs/CLONAGEM_LOCAL_POCKET_TTS.md), incluindo a exigência de aceite inicial do checkpoint oficial.
- **Aprovação em massa em um clique:** `✂ Aprovar e aplicar TODOS` inclui também sugestões ocultas pelo filtro; alternativa individual, contador, `Aplicar apenas os marcados`, `Pular cortes`, `Cancelar` e Undo continuam disponíveis.
- **Uma única tela com caixas de seleção** na aba `⚙ Ações IA`: Silero, transcrição, vícios, contexto, legendas, SRT e narração. Selecione uma ou várias ações, use o preset `Edição completa` e clique `▶ APLICAR EDIÇÃO`.
- **Fila priorizada Batata Quente:** Silero → Whisper → Qwen → aplicar cortes aprovados → legendas → SRT → Pocket TTS. Cada IA trabalha isoladamente, reaproveita o cache e libera o modelo ao terminar. Qwen recebe **a transcrição pronta** e não recarrega Whisper.
- **Otimização opcional VAD/Whisper:** se Silero também estiver selecionado, é possível enviar apenas intervalos com fala para Whisper, sem cortar fisicamente a mídia antes da revisão. Pode reduzir minutos de transcrição em gravações com pausas, mas **não há garantia de velocidade ou precisão**; por isso o usuário pode desmarcar essa otimização.
- **Liberdade durante o trabalho:** timeline e preparo da prévia continuam utilizáveis enquanto a IA analisa. A fila serializa trabalhos pesados; o usuário não precisa ficar parado. Se editar um bloco-alvo antes de a análise terminar, o aplicativo não aplica decisões com timestamps obsoletos.
- **Legendas após os cortes:** cria blocos editáveis a partir dos intervalos sobreviventes, respeitando velocidade e tempos absolutos de fonte; não apaga legendas manuais.
- **Ajuste Fino da Voz:** graves, médios, agudos, pitch independente (±4 semitons) e velocidade de narração (0,70×–1,30×), com bypass, presets iniciais e próprios persistentes, Undo/Redo e processamento sem repetir o TTS. EQ ajusta-se durante a reprodução pelo FFmpeg `azmq`; pitch/velocidade e EQ fora de uma sessão de reprodução usam o mesmo grafo de áudio em preview, MP4 e WAV PCM 24-bit. Formantes e crossfade sem interrupção ainda estão pendentes; veja [AJUSTE_FINO_VOZ.md](docs/AJUSTE_FINO_VOZ.md).

Para conferir o estado validado desta versão, consulte `docs/VALIDACAO_010_ALPHA1_LOCAL.md` e `docs/VALIDACAO_IA.md`. O roteiro manual da fila anterior permanece em `docs/TESTE_FILA_09.md`.

**Referência visual:** a organização escura e os acentos laranja vieram do pacote antigo; a marca, o progresso compacto e as ferramentas laterais ficam conectados ao motor multitrilha atual. Componentes e contratos antigos não são carregados como uma segunda engine.

---

# Correção 0.8.1 — Compatibilidade com FFmpeg recente

Se aparecer `Unrecognized option 'filter_complex_script'`, use este pacote. O FFmpeg 9 removeu essa opção; o BerofelStudio agora detecta a versão e utiliza automaticamente a sintaxe apropriada. **Não é um erro da instalação do Whisper.**

Feche o editor, extraia o ZIP em `C:\BerofelStudio` (ou outra pasta sua, sem misturar com a Alpha), mantenha projetos e mídias em local separado, e abra `ABRIR_BEROFELSTUDIO.bat`. Os modelos no `%LOCALAPPDATA%` não precisam ser reinstalados. Rode `TESTAR_CORRECAO_FFMPEG_081.bat` para testes. O ZIP contém o código do editor e os instaladores, não os modelos.

---

# BerofelStudio Studio 0.8 — Ações independentes e alcance livre (Windows)

> **Status:** Alpha para instalar e testar. Novos mecanismos de escopo, independência de IA, transcrição reutilizada e legendas editáveis validados com testes automatizados sem modelos pesados. **GUI PySide6 e inferência real no Windows exigem validação local.** O ZIP traz código, ferramentas e instaladores, não os pesos das IAs.

## Mudanças principais da 0.8

No cabeçalho, abra **⚙ Ações IA** (aba fixa no painel direito). **Escolha primeiro o alcance**: um bloco, vários blocos selecionados (inclusive de faixas diferentes), uma faixa inteira, intervalo In/Out em todas as faixas, intervalo In/Out somente numa faixa, ou projeto inteiro. Antes de executar, confira a **quantidade de blocos e duração** que o painel informa. Nenhuma análise começa quando você importa mídia.

Cada botão executa apenas o necessário:

| Ação | Etapas usadas | Comportamento |
| --- | --- | --- |
| Transcrever | Extração + Faster-Whisper | Armazena palavras com tempo, **sem Silero, Qwen ou cortes** |
| Legendas automáticas | Faster-Whisper se ainda não houve transcrição válida | Gera blocos de **texto editáveis** numa faixa `Legendas`; não faz cortes |
| Detectar silêncios | Extração + Silero VAD/ONNX | Sugere cortes para revisão **sem Whisper/Qwen** |
| Vícios de linguagem | Faster-Whisper + Qwen (ou Qwen se já transcrito) | Identifica candidatos para revisão individual; não corta automaticamente |
| Análise contextual | Faster-Whisper + Qwen (ou só Qwen se transcrito) | **Somente consulta**, relatório sem botão de aplicar corte |
| Exportar SRT do alcance | Sem IA, usando texto existente | Respeita faixa/intervalo e inclui legendas manuais/editadas |
| Usar transcrição na narração | Sem IA, copia texto já transcrito | Abre Pocket TTS; texto livre continua independente |
| Legendas manuais | Sem IA | Escreva texto e adicione ao alcance; pode arrastar, aparar ou editar depois |

**Batata Quente 2.0:** VAD, Whisper, Qwen e Pocket TTS são tarefas independentes e sequenciais, com processos separados, cache persistente, progresso/tempo, pausa, retomada e cancelamento. Dados concluídos sobrevivem ao cancelamento. Nenhuma regra fixa limita a RAM de PCs mais fortes.

**Reutilização de transcrição após divisões:** o projeto salva `ai_coverage` (fonte, tamanho, mtime, modelo, idioma e limites absolutos). Se você transcreveu um bloco e depois dividiu, rearranjou, alterou a velocidade ou selecionou apenas uma parte, o sistema reaproveita as palavras salvas **sem rodar Whisper novamente**, quando há cobertura válida. Áudio e vídeo separados que referenciam a mesma fonte/intervalo compartilham a etapa de processamento. Se o arquivo original for modificado ou o modelo/idioma mudar, a cobertura não é reutilizada.

**Tempos seguros:** In/Out é informado na timeline, convertido para o intervalo correto na fonte antes da análise; sugestões são convertidas de volta ao bloco original para revisão. Isso mantém o comportamento de 2×/10×. Os cortes continuam não destrutivos e precisam da autorização do usuário.

## Instalação em Windows 10/11 x64

1. Extraia em `C:\BerofelStudio` (ou pasta curta equivalente).
2. Execute **`instalar_dependencias.bat`**. O instalador prepara o editor e oferece instalar o Pocket TTS local (PyTorch/CPU, download potencialmente grande); a opção recomendada é `S`. A clonagem pessoal só baixa pesos gated após outra confirmação, e somente se você já aceitou os termos oficiais.
3. Execute **`ABRIR_BEROFELSTUDIO.bat`**. Para Whisper/Silero e Qwen de compatibilidade, execute **`INSTALAR_TODAS_AS_IAS.bat`**; Pocket TTS também pode ser instalado separadamente por `INSTALAR_POCKET_TTS.bat`.
4. Execute **`TESTAR_EDITOR_08.bat`** e **`TESTAR_INTERFACE_ACOES_08.bat`**. Veja **`docs/TESTE_EDITOR_08.md`** para roteiro completo.

Modelos não vêm embutidos no arquivo ZIP; arquivos e transcrições podem continuar no cache `%LOCALAPPDATA%\BFS\cache\ai` caso já use uma versão anterior com o mesmo ambiente. A instalação dos modelos não é obrigatória para abrir o editor ou criar legendas manuais.

---

# BerofelStudio Studio 0.7 — Edição de precisão, motion, IA e Batata Quente (Windows)

> **Status:** Alpha de desenvolvimento. A integração do motor FFmpeg e a persistência do projeto foram validadas com testes automatizados em Linux. A **GUI PySide6, codecs/áudio reais e os instaladores completos no Windows** ainda exigem teste no computador do usuário. Os modelos Whisper, Silero, Qwen e Pocket TTS são downloads opcionais; não estão embutidos no ZIP.

## Novidade 0.7 — editar mais rápido sem sacrificar a fonte original

**Timeline:** encaixe magnético (íman/S), apagar com ripple (Ctrl+Shift+Delete), marcadores (M), zoom por botões e Ctrl+roda, ajustar ao projeto (F), miniaturas dos quadros e ondas do áudio **sob demanda** com cache no disco. Nenhuma IA é executada automaticamente ao importar mídia. Divisão (Ctrl+K ou lâmina B), multisseleção Ctrl+clique, camadas universais, bloqueio e undo/redo permanecem da base anterior.

**Velocidade:** selecione um clipe, abra **Propriedades > Velocidade** e escolha **0,25×, 0,5×, 1×, 2×, 3×, 4×, 10×** ou digite um fator entre 0,25× e 10×. A duração, o ritmo do áudio (filtros FFmpeg atempo), a divisão e as legendas recalculam seus tempos. Não altera os arquivos de origem. Áudio/vídeo agrupados e pareados recebem a mesma velocidade.

**Keyframes:** posicione o cursor sobre o clipe e em **Propriedades > Keyframes** escolha posição X/Y, escala, opacidade, volume ou rotação; defina curva Linear, Ease in, Ease out ou Suave e clique **◆ Adicionar**. São salvos no projeto e avaliados pelo compositor de preview/exportação. Há também modo opcional **auto-keyframe** para propriedades com animação preexistente. O sistema ainda **não** dispõe de editor gráfico de curva Bézier por alças.

**Transições:** escolha dois clipes vizinhos na mesma faixa e use **↔ Dissolvência**, ou a ação de transições no menu/contexto para **dissolve, slide ou zoom**. As sobreposições e fades são aplicados de forma não destrutiva. Para remover a transição, desfaça (Ctrl+Z) ou reajuste manualmente os tempos/fades. Ainda não é um catálogo de centenas de presets.

**Áudio e grupos:** **Separar áudio** cria um bloco de áudio independente em outra faixa sem perder o alinhamento inicial; os blocos ficam vinculados por grupo. Com **Agrupar** (Ctrl+G), blocos podem mover-se juntos; **Desagrupar** usa Ctrl+Shift+G. Fades de entrada e saída, filtro passa-altas/baixas e limpeza opcional (`afftdn`) estão nas propriedades. A limpeza não substitui uma ferramenta profissional de restauração de áudio e pode alterar o timbre.

**Prévia direta e acabamento:** a prévia permite arrastar a camada selecionada para mudar sua posição e ajustar escala com Ctrl+roda. Propriedades incluem posição, escala, rotação, opacidade, brilho, contraste, saturação, recorte de bordas, volume e fades. Keyframes animam os campos suportados. A exportação usa FFmpeg com um grafo de composição compartilhado com a prévia.

**Desempenho:** menu **Proxy leve** gera uma cópia H.264 reduzida de **cada vídeo selecionado** pela área Batata Quente, respeitando pausa/cancelamento e reutilizando o arquivo em cache; somente a prévia substitui a fonte por esse proxy. A **exportação sempre recebe o original**. O proxy é opcional, nunca inicia sozinho. As thumbnails e ondas são geradas apenas para trechos visíveis da timeline, em segundo plano; seus resultados persistem em disco. Proxies com arquivos VFR/codecs especiais ainda precisam de testes de sincronização em hardware real.

**Interface:** biblioteca esquerda · prévia centro · propriedades/narração direita · monitor Batata Quente em faixa própria · timeline inferior. A barra de ferramentas de timeline tem scroll horizontal, em vez de cobrir os outros painéis. IA e render pesado permanecem sequenciais e controlados pelo mesmo painel.

### Instalação e testes

1. Extraia a pasta `BerofelStudio` do ZIP, por exemplo em `C:\BerofelStudio`.
2. Execute **`instalar_dependencias.bat`**. O instalador principal instala Python, ambiente, PySide6 e FFmpeg quando necessário.
3. Execute **`ABRIR_BEROFELSTUDIO.bat`** para abrir o editor.
4. Opcionalmente use **`INSTALAR_TODAS_AS_IAS.bat`** para modelos/infraestrutura de Whisper, Silero, Qwen e Pocket TTS. A instalação pode exigir internet, downloads grandes, e aceitação dos termos do Pocket TTS na Hugging Face.
5. Execute **`TESTAR_EDITOR_07.bat`**, **`VERIFICAR_MOTOR.bat`** e **`TESTAR_PREVIEW_WINDOWS.bat`** para obter diagnósticos objetivos, inclusive teste de prévia Qt no Windows.

**Atenção:** ainda faltam recursos de uma suíte completa: máscaras complexas/chroma key, correção por curvas/LUT, estabilização, presets avançados de legendas, mapa de remapeamento de velocidade variável dentro de um clipe, edição gráfica de curvas e validação extensa de 4K/VFR/GPU. As melhorias 0.7 não garantem que todo projeto seja reproduzido em tempo real; use proxies e 640px na prévia para máquinas modestas.

---

# Histórico: BerofelStudio 0.6 — Multitrilha, IA, Pocket TTS e Monitor Batata Quente (Windows)

> **Status:** Alpha para testes no Windows. Reprodução/exportação multitrilha receberam testes de integração em Linux. O pipeline de IA e o cache têm testes automatizados com modelos simulados, mas a inferência real do Whisper/Silero/Qwen e os instaladores Windows ainda precisam ser testados no próprio PC. Não é uma versão estável de produção.

## Novidade da 0.6 — Painel universal de processos

Entre o preview (biblioteca à esquerda, prévia central e propriedades/narração à direita)
 e a timeline há uma **faixa própria e permanente** chamada **BATATA QUENTE**.
Ela nunca cobre o vídeo nem os blocos na timeline.

Ao transcrever, detectar silêncios, analisar com Qwen, narrar com Pocket TTS,
aplicar cortes ou exportar/renderizar via FFmpeg, a tela mostra:

- O nome da operação e a etapa corrente do processamento.
- **Barra de 0 a 100%** baseada em etapas ou trechos efetivamente concluídos.
  Na análise Qwen, o progresso também avança quando cada lote contextual termina;
  durante a inferência de um lote individual, a porcentagem pode permanecer estável.
- **Tempo decorrido ativo** (pausas não contam) e tempo restante **estimado**
  quando há histórico de etapas concluídas; a estimativa é aproximada.
- RAM e CPU do editor + subprocessos, quantidade de processos e RAM livre do Windows.
- **Ⅱ Pausar / ▶ Continuar**: suspende e retoma as árvores de subprocessos.
- **■ Cancelar**: encerra o trabalho e seus subprocessos; preserva os checkpoints
  já concluídos no cache. Não apaga o projeto nem o vídeo original.
- **Detalhes ▾**: abre registro embutido na própria área, sem sobreposição.
- **Copiar relatório**: copia etapas/tempos/uso de recursos para enviar feedback.

Apenas **uma tarefa pesada por vez** pode ser executada. Pausar não impede que
você continue navegando no programa, mas não inicia uma segunda tarefa de IA.
Para pausar a reprodução do vídeo, use o botão Play/Pause habitual da prévia;
o painel BATATA QUENTE controla operações em lote e exportações, não o play normal.
A geração do Pocket TTS pode durar sem avanço interno preciso. O Qwen informa os
lotes contextuais concluídos; o avanço dentro de cada inferência fica indisponível
até o próximo lote. Uma máquina poderosa não recebe limite fixo de RAM ou CPU.

**Instalação:** execute `instalar_dependencias.bat` novamente se atualizou da 0.5
(para instalar `psutil`), e `TESTAR_PROCESSOS.bat` para testar os botões e o
controle dos subprocessos no seu Windows. Não é necessário baixar novamente
modelos já instalados para adicionar apenas este painel.

## Recursos da 0.5 — Pocket TTS

A aba fixa **🎙 Narração** aceita texto livre, texto dos blocos transcritos,
vozes autorizadas e amostra particular com confirmação de consentimento.
Gera áudio WAV para ouvir ou adicionar na faixa de narração. O Pocket TTS
continua opcional e é instalado por `INSTALAR_POCKET_TTS.bat` ou pelo instalador
de todas as IAs; seu modelo pode exigir autorização no Hugging Face.

## Base da 0.4 — IA Batata Quente 2.0

**Instalação rápida:** rode `instalar_dependencias.bat` (editor). Depois rode `INSTALAR_TODAS_AS_IAS.bat` (Whisper Base, Silero ONNX, Qwen3 GGUF/llama.cpp) ou instale opcionalmente por separado: `INSTALAR_IA_OPCIONAL.bat` e `INSTALAR_QWEN_OPCIONAL.bat`. O instalador de Qwen baixa cerca de 1,3 GB e exige internet, mas seu uso posterior é local. Se não instalar Qwen, o editor e as transcrições com Whisper continuam funcionando.

Após importar, **selecione um ou mais blocos da timeline** e abra o menu ☰ Ferramentas:

- **Transcrever IA:** usa Faster-Whisper Base (CPU, INT8) e guarda palavras com tempos precisos de origem sem cortar nada.
- **Silero + Whisper:** detecta períodos sem fala por Silero VAD/ONNX, mostra transcrição e sugere intervalos para revisão. **As sugestões ficam desmarcadas por padrão.**
- **Qwen Contextual:** só recebe o texto e os IDs das palavras; identifica possíveis hesitações, recomeços e redundâncias, devolve notas/justificativas e propõe cortes desmarcados. Precisão semântica será calibrada com material real.
- **Exportar SRT:** converte tempos **de origem** para tempos **atuais da timeline** depois dos cortes e guarda as legendas externamente.

**Batata Quente:** cada processo trabalha, salva o resultado em `%LOCALAPPDATA%\BFS\cache\ai`, encerra (libera modelo/RAM) e passa o arquivo de cache à próxima IA. O cache depende de caminho/tamanho/mtime da fonte, limites exatos do bloco e configuração do modelo. Repetir uma análise idêntica reaproveita as etapas concluídas. **Não existe teto fixo de RAM de 4 GB**; computadores modestos podem usar modelos menores e mais tempo, e máquinas potentes não ficam artificialmente restritas.

O motor jamais aplica um tempo inventado pelo Qwen: converte **IDs de palavras** válidos em intervalos fornecidos pelo Whisper; checa limites do bloco e palavras protegidas. Ainda assim, a decisão final cabe ao usuário.

Consulte `docs/VALIDACAO_IA.md` e execute `TESTAR_BATATA_QUENTE.bat` para validar os modelos e cache em seu Windows. A referência de processar 80 minutos em 7 minutos ainda **não foi reproduzida nem comprovada** no novo motor.


## O que mudou em relação à Alpha 0.2

O botão **▶ Reproduzir timeline** agora inicia uma **prévia ao vivo da composição multitrilha**, não o arquivo original de um único bloco. A imagem é produzida pelo FFmpeg em memória (pipe BGRA) e desenhada no painel Preview pelo Qt. O áudio de todas as fontes é composto em PCM estéreo e enviado ao `QAudioSink`. Quando existe dispositivo de áudio compatível, a reprodução usa o relógio do áudio para acompanhar os quadros. Tudo isso usa o mesmo grafo de composição do exportador.

O motor **não depende da presença de MLT instalado**: essa versão utiliza FFmpeg, Qt e componentes próprios. Shotcut e Kdenlive foram estudados como referências de arquitetura de timeline/composição; **não copiamos código deles**. MLT continua uma integração futura possível, caso sejam distribuídos e validados seus binários/plugins para Windows.

### Camadas universais

- Biblioteca **à esquerda**, Preview **no centro**, Propriedades **à direita**; timeline independente **embaixo**. Os painéis **não trocam de posição**. Itens internos quebram linha/rolam dentro de cada painel.
- Pode adicionar quantas camadas desejar, renomear, subir, descer, silenciar, ocultar e bloquear.
- Qualquer camada recebe vídeo, imagem, áudio, narração importada ou título. **Não há faixas exclusivas por tipo de conteúdo.**
- Mídias sobrepostas na mesma camada são mostradas em sublinhas. Um bloco pode ser movido entre camadas e no tempo; seu conteúdo de origem não é alterado.
- **Quanto mais acima a camada, mais à frente fica a imagem.** Imagens opacas na frente cobrem as de trás. O áudio de todos os blocos não silenciados é **misturado** independentemente de posição vertical.
- O menu ☰ contém ferramentas em uma faixa horizontal circular. A timeline é **linear**, com scrollbar horizontal e scroll vertical invisível.

## Instalação — computador com Windows 10/11 x64

1. Extraia **a pasta completa** `BerofelStudio` deste ZIP, por exemplo em `C:\BerofelStudio`. Não execute scripts dentro do ZIP.
2. Dê dois cliques em **`instalar_dependencias.bat`**. Ele verifica/instala Python 3.12 x64, Microsoft VC++ Runtime, `PySide6_Addons`, `Pillow`, `imageio-ffmpeg`, FFmpeg/FFprobe. Dependências transitivas são instaladas pelo pip. É preciso internet quando faltarem arquivos.
3. O instalador **executa um autoteste real** criando dois pequenos vídeos de cores diferentes com tons, sobrepondo os quadros e misturando os sons. A instalação só termina com `[OK]` se a composição funcionar com os binários locais.
4. Execute **`ABRIR_BEROFELSTUDIO.bat`**. Nenhuma instalação manual de Python ou uso do comando `python` do Windows é exigida. O ambiente virtual usa `%LOCALAPPDATA%\BFS\venv` para evitar erro de caminho longo.
5. Opcionalmente, execute **`TESTAR_PREVIEW_WINDOWS.bat`**. Este teste abre uma janela real, reproduz dois vídeos de exemplo em camadas e verifica se o widget recebeu quadros. É a validação que **não conseguimos executar no Linux**.

Antes de instalar dependências, FFmpeg ou IAs opcionais, feche o editor e aguarde as tarefas terminarem. Os instaladores detectam processos Python do ambiente do BerofelStudio e param com os respectivos PIDs; eles não encerram esses processos automaticamente. O instalador Qwen baixa para um arquivo candidato, confere o SHA-256 e só então ativa o modelo, preservando um arquivo existente se a verificação falhar.

Se já vinha de um pacote Alpha, não é necessário apagar seu Python instalado; o instalador reutiliza o que estiver correto. Se a instalação parar no FFmpeg, execute `CONTINUAR_INSTALACAO.bat`; o módulo FFmpeg faz tentativas com barra de progresso, timeout e duas fontes verificadas. Para testar só o motor sem abrir a GUI, execute `VERIFICAR_MOTOR.bat`.

Para **IA de transcrição**, execute **`INSTALAR_IA_OPCIONAL.bat`**; ela instala Faster-Whisper, CTranslate2, ONNX Runtime e baixa o modelo Whisper Base uma única vez para uso local. O **Silero VAD/ONNX** acompanha o Faster-Whisper. Para **Qwen contextual**, execute `INSTALAR_QWEN_OPCIONAL.bat`. O Pocket TTS faz parte das versões 0.5 em diante e é instalado separadamente ou pelo pacote de IAs.

## Primeiro vídeo — roteiro de uso

1. Clique **+ Importar arquivos** e escolha um ou mais vídeos, áudios ou imagens.
2. Arraste cada arquivo da biblioteca para a camada e o segundo da timeline que desejar, ou escolha **Inserir em:** e dê duplo clique no arquivo. Para criar mais camadas, clique **+ Camada**. Para título, **+ Texto**.
3. Arraste os blocos na horizontal/vertical para ajustar tempo e camada. Use o botão **↑** de uma camada para trazê-la para frente; **↓** para levá-la para trás.
4. Clique em qualquer trecho da régua da timeline para posicionar o cursor. No Preview, escolha `640px / 24fps` (ideal para máquinas modestas) ou uma qualidade maior.
5. Clique **▶ Reproduzir timeline** ou aperte **Espaço** com a timeline focada. A prévia inclui todos os vídeos, imagens, textos e áudios ativos naquele instante. Clique novamente para pausar. Em caso de problema de backend de áudio/Qt, experimente ☰ → **Prévia MP4 (reserva)** (precisa renderizar a composição temporária antes de reproduzi-la).
6. Para dividir: selecione um ou vários blocos, posicione o cursor e use **Ctrl+K**; ou pressione **B** com foco na timeline e clique no ponto que deseja cortar. Pressione **V** para voltar à ferramenta Selecionar.
7. Para sugestões de silêncio, selecione **apenas os blocos desejados** e acione ☰ → **Silêncios IA**. Nada é analisado automaticamente. Revise os intervalos e aplique somente o que escolher. Os originais continuam intocados. Repetições requerem a IA opcional.
8. Ajuste propriedades individuais no painel direito: volume, opacidade, posição, escala, tempo, texto e ordem dentro da camada.
9. Use **Salvar projeto** para guardar um `.berofel.json` não destrutivo; clique em **Exportar** para gerar o MP4 H.264/AAC. O exportador usa a mesma composição da prévia e apresenta progresso.

## Atalhos

| Ação | Atalho |
|---|---|
| Selecionar | `V` na timeline |
| Lâmina | `B` na timeline |
| Dividir selecionados no cursor | `Ctrl+K` |
| Vários blocos | `Ctrl+clique` |
| Selecionar todos na timeline | `Ctrl+A` |
| Excluir | `Delete` |
| Desfazer / Refazer | `Ctrl+Z` / `Ctrl+Y` |
| Play / Pausar timeline | `Espaço` com foco na timeline |
| Importar | `Ctrl+I` |
| Salvar / Abrir / Novo | `Ctrl+S` / `Ctrl+O` / `Ctrl+N` |
| Zoom | `Ctrl + roda` |

## Arquitetura técnica

```
                 MODELO NÃO DESTRUTIVO (JSON v2)
                      Project -> Tracks[] -> Clips[]
                                   |
            +----------------------+------------------+
            |                      |                  |
      Timeline PySide6        Preview ao vivo     Export MP4
       seleção/arraste        FFmpeg x2 pipes      FFmpeg
       propriedades           BGRA / PCM          filter_complex
            |                      |                  |
            +------------ MESMO COMPOSITOR ----------+
                      overlay / volume / amix
```

- `berofel/core/project.py`: dados independentes da UI; recortes por `start/end` na origem e `timeline_start` na timeline; JSON de projeto; migração de v1; ordem das camadas.
- `berofel/services/export_multitrack.py`: gera filtro de sobreposição em ordem de camadas e áudio misturado; exporta MP4 de modo atômico, bloqueia sobrescrita dos originais e fornece progresso.
- `berofel/services/preview_pipeline.py`: recorta uma janela a partir do cursor em memória, cria comandos FFmpeg para vídeo BGRA e áudio PCM com o mesmo filtro da exportação.
- `berofel/ui/live_preview.py`: gerenciamento de dois processos FFmpeg, buffers limitados e leitor em threads; relógio de áudio via Qt; play/pause/stop e limpeza de recursos.
- `berofel/ui/window.py`: três painéis, prévia, biblioteca, propriedades, ações e seleção da IA por bloco.
- `berofel/ui/process_panel.py`: visualizador universal de processos e relatórios, área fixa.
- `berofel/services/process_control.py`: monitoramento via psutil e pausa/cancelamento de subprocessos.
- `berofel/ui/timeline.py`: timeline linear, faixas universais, sublinhas, régua e controles.
- `scripts/diagnostico_motor.py`: autoteste de composição local; `scripts/testar_interface.py`: smoke test de Qt + streams reais no Windows.

Auditoria de origem, matriz de migração e decisões do motor: `docs/AUDITORIA_INICIAL.md`,
`docs/MATRIZ_MIGRACAO.md` e `docs/DECISOES_ARQUITETURAIS.md`. Resultados locais e
limites de validação: `docs/VALIDACAO_010_ALPHA1_LOCAL.md` e `docs/VALIDACAO_IA.md`.

### Projetos e arquivos originais

Cortes e movimentações alteram apenas referências de origem. Os arquivos brutos continuam no disco. O exportador **bloqueia saída com o mesmo caminho de qualquer arquivo-fonte do projeto**. O MP4 é escrito primeiro em arquivo temporário e só movido ao destino depois de terminado, evitando destruir um export anterior se o FFmpeg falhar.

### Qualidade de prévia x exportação

A prévia tem três escolhas: **640×360/24 fps** (default para projetos 16:9 de 1280×720), 960×540/24 fps, ou 1280×720/30 fps. Em projetos de outra proporção, a altura acompanha essa proporção. A qualidade reduzida afeta **somente o Preview**, não o MP4 exportado. A exportação usa largura/altura/fps registrados no projeto (padrão 1280×720/30). Desde a 0.7 já existem proxies opcionais e cache visual da região visível. Cache avançado de segmentos e suporte especializado a GPU continuam em aberto.

### Limitações que ainda permanecem

- A GUI Qt foi capturada no plugin nativo do Windows e os testes de composição usaram FFmpeg real. Ainda não há validação perceptiva prolongada pela saída física de áudio, em DPI global/per-monitor nem com a gravação original de 80 minutos. Consulte `docs/VALIDACAO_010_ALPHA1_LOCAL.md`.
- O preview usa processos FFmpeg separados para imagem BGRA e áudio PCM por janela; isso pode exigir mais CPU que uma engine com decoder compartilhado. A resolução de preview pode ser reduzida independentemente da exportação.
- Os testes de 300/500 cortes e 80 minutos usam mídia sintética. Não garantem reprodução de qualquer conjunto de dezenas de vídeos 4K, desempenho de GPU ou precisão editorial em fala real.
- A prévia MP4 de reserva renderiza a timeline antes do Play; a prévia principal é streaming por janelas.
- Silero executa VAD/ONNX local. Qwen contextual continua experimental, roda local e suas propostas precisam de aprovação humana.
- O alvo é **Windows 10/11 x64 com Python 3.12**. O carregador de projeto suporta JSON v1/v2, mas uma migração de projeto real deve ser testada com backup antes do uso contínuo.
- Licenças de bibliotecas, binários FFmpeg, modelos e assets precisam ser confirmadas antes de distribuição comercial.

## Referências estudadas, sem copiar código GPL

- Arquitetura Kdenlive: https://github.com/KDE/kdenlive/blob/master/dev-docs/architecture.md — UI/timeline separada do motor MLT.
- Representação das trilhas Kdenlive: https://github.com/KDE/kdenlive/blob/master/dev-docs/fileformat.md — produtor/playlist/tractor.
- MLT e bindings: https://mltframework.org/ e https://mltframework.org/doxygen/group__python__bindings.html — composição avançada; empacotamento Windows a avaliar.
- FFmpeg filter_complex: https://ffmpeg.org/ffmpeg-all.html — sobreposição e mixagem.
- Qt QAudioSink: https://doc.qt.io/qt-6/qaudiosink.html — saída PCM controlada por buffer.

## Relatório e problemas

- `docs/VALIDACAO.md`: comandos e resultados dos testes, limitações e roteiro da validação no Windows.
- `logs/instalacao_*.log` e `logs/continuacao_*.log`: logs do instalador.
- `logs/erro_abertura_*.log`: falhas Python ao iniciar a janela (não captura crashes nativos de drivers).
- Se `TESTAR_PREVIEW_WINDOWS.bat` falhar, envie a saída de texto. Se o editor abrir mas o áudio estiver mudo, confira o dispositivo de áudio padrão e tente a prévia MP4 de reserva.

---

## Studio 0.5 — Ferramenta fixa de narração Pocket TTS

A área **🎙 Narração** fica sempre disponível na aba da direita (ao lado de
Propriedades) e pelo botão fixo no cabeçalho. O editor nunca carrega Pocket TTS
na inicialização. A interface pode ser usada para digitar qualquer texto, mesmo
sem importar ou transcrever vídeos. Também é possível selecionar blocos de vídeo
já transcritos e clicar em **Trazer transcrição dos blocos selecionados**.

### Instalação no Windows 10/11 x64

1. `instalar_dependencias.bat` — estrutura do editor, FFmpeg e oferta para instalar Pocket TTS local; os downloads grandes são informados e confirmados antes de começar.
2. `INSTALAR_TODAS_AS_IAS.bat` — Faster-Whisper, Silero e Qwen de compatibilidade,
   **ou** `INSTALAR_POCKET_TTS.bat` — reparar/instalar somente Pocket TTS.
3. Se você já aceitou os termos e quer clonar a voz durante a instalação, confirme o download dos pesos. Caso contrário, abra
   https://huggingface.co/kyutai/pocket-tts, entre na conta e aceite os termos;
   depois use Narração → **Preparar clonagem local** para autenticar e concluir o cache sem abrir CMD; `AUTORIZAR_POCKET_TTS.bat` segue disponível como alternativa manual.
   **Este passo pessoal não pode ser executado pelo instalador em seu nome.**
4. `TESTAR_POCKET_TTS.bat` — testa geração WAV pela voz pronta. Depois de autorizar os pesos completos, use `TESTAR_POCKET_TTS.bat --clone` para testar clonagem com uma referência sintética, sem selecionar uma gravação pessoal.
5. `ABRIR_BEROFELSTUDIO.bat` — use a aba Narração à direita.

O download dos pacotes e pesos depende de internet na primeira instalação.
Depois de baixar o modelo, é possível gerar offline. Os modelos não estão
embutidos no ZIP. `requirements-pocket-tts.txt` fixa Pocket TTS 4.0.1,
que instala as bibliotecas transitivas, incluindo PyTorch. Instalação no Windows
não foi testada fisicamente neste ambiente; verifique os arquivos de `logs/`.

### Modos de uso

- **Texto livre:** digite um roteiro inteiro ou trecho curto. Não requer Whisper.
- **Voz pronta:** Rafael é o preset oficial português (os termos de uso dependem
  do modelo); Bill, Caro, Peter e Stuart usam IDs de vozes precomputadas do
  Pocket TTS, associados às amostras CC0 da coleção
  `kyutai/tts-voices/voice-zero`. O instalador pré-carrega os estados
  precomputados em português quando a rede permite, sem baixar WAVs de
  referência; outros idiomas podem buscar o estado no primeiro uso.
- **Voz clonada:** aceite primeiro os termos de acesso ao modelo em `huggingface.co/kyutai/pocket-tts` e use Narração → **Preparar clonagem local**; o token é solicitado em campo mascarado e o app confirma se os pesos foram liberados. `AUTORIZAR_POCKET_TTS.bat` segue como alternativa manual. Depois selecione um WAV/MP3/FLAC/OGG/M4A autorizado, confirme a permissão expressa e gere. Formatos comprimidos são convertidos com FFmpeg numa cópia temporária; seu áudio original não é alterado. A qualidade depende da amostra. Não use voz de terceiros
  sem permissão, nem apresente síntese como gravação verdadeira de outra pessoa.
- **Gerar e adicionar:** cria um WAV separado e uma camada `Narração` na timeline,
  na posição do cursor, sem alterar ou substituir o áudio original.
- **Gerar só WAV:** grava uma mídia de áudio reutilizável, sem tocar a timeline.
- **Ouvir:** reproduz o último WAV diretamente no painel.

Os arquivos gerados são armazenados em `<pasta_do_projeto>/<nome>_arquivos/narracoes`
para projetos já salvos; para projetos novos ainda sem caminho, são armazenados
em `Documentos/BerofelStudio/Narracoes`. Não são excluídos pela limpeza do cache.

**Batata Quente:** a operação de narração ocorre em subprocesso independente.
O modelo não permanece na RAM do editor, que continua responsivo. O áudio em
cache é indexado por texto, idioma, voz e opções, com invalidação automática se
uma amostra de voz local for alterada. Não existe teto artificial de RAM/CPU.

**Limitações atuais:** nenhuma substituição automática com sincronização labial,
controle fonético, time-stretch ou legenda palavra a palavra do WAV gerado.
A narração é uma faixa de áudio independente, com início e duração editáveis.

Fontes e licenças: https://github.com/kyutai-labs/pocket-tts e
https://huggingface.co/kyutai/tts-voices (ver `assets/voices/LICENSES.md`).







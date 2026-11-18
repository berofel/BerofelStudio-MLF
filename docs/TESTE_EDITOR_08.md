# Roteiro de validação — BerofelStudio 0.8

## Instalação

1. Extraia **a pasta completa** do ZIP em `C:\BerofelStudio`.
2. Execute `instalar_dependencias.bat` (pode reutilizar `%LOCALAPPDATA%\BFS\venv`).
3. Para os testes de IA real, instale os modelos por `INSTALAR_TODAS_AS_IAS.bat`; isso pode baixar arquivos grandes, exige internet e, no Pocket TTS, autorização no Hugging Face conforme a licença do modelo. A interface de ações e a legenda manual **não** precisam de pesos de IA.
4. Execute `TESTAR_EDITOR_08.bat` e `TESTAR_INTERFACE_ACOES_08.bat`.
5. Abra `ABRIR_BEROFELSTUDIO.bat`.

## Testes manuais de usabilidade

1. **Nada automático**: importe um vídeo e arraste para a timeline. Confirme que não aparece tarefa de IA em execução.
2. **Um bloco**: selecione um clipe e abra `⚙ Ações IA` no cabeçalho. Escolha `Um bloco selecionado`; clique `Transcrever · somente Whisper`. Confira que não executa Silero nem Qwen no monitor.
3. **Vários blocos**: use Ctrl+clique em dois clipes, mesmo em faixas diferentes. Escolha `Vários blocos selecionados`. Confira contagem e duração antes de iniciar.
4. **Faixa inteira**: escolha uma faixa na caixa `Faixa escolhida`, e `Faixa inteira escolhida`. Confirme que somente os clipes dessa faixa entram no relatório.
5. **Intervalos**: posicione o cursor, clique `In = cursor`, avance e clique `Out = cursor`. Selecione `Intervalo In/Out (todas as faixas)` e depois `Intervalo In/Out da faixa escolhida`. Verifique que os tempos de origem fora do alcance nunca são cortados.
6. **Silêncios**: clique `Detectar silêncios · só Silero`. Revise as sugestões — ficam **desmarcadas** por padrão. Não é necessária transcrição.
7. **Legendas automáticas**: selecione os blocos e clique `Legendas automáticas · Whisper`. Os resultados devem virar blocos de texto editáveis numa faixa `Legendas`. Teste fonte/posição/duração, renderização e Ctrl+Z.
8. **Legenda manual**: digite texto no campo manual, selecione um alcance e clique `+ Criar legendas manuais no alcance`. Deve funcionar sem modelos de IA.
9. **Repetição**: execute a mesma ferramenta/alcance novamente. Confira `cache hits` no monitor e ausência de duplicação de legendas automáticas.
10. **Edição posterior**: transcreva o vídeo inteiro, divida um bloco com Ctrl+K, escolha uma parte e gere legendas. O Whisper **não deve ser chamado novamente** se a fonte, modelo e idioma não mudaram.
11. **Contexto vs corte**: `Análise contextual` deve abrir apenas um relatório, sem modificar o vídeo. `Vícios de linguagem` exibe candidatos para aprovação individual e pode aplicar somente os marcados.
12. **Narração**: use `Usar transcrição na narração` para levar o texto da seleção/faixa ao Pocket TTS. Digite texto livre diretamente na aba `🎙 Narração` para gerar fala sem qualquer transcrição.
13. **Processos**: durante um trabalho real, teste `Pausar`, `Continuar`, `Cancelar` e `Copiar relatório`. Verifique que o editor não sobrescreveu o original nem deixou cortes parcialmente aplicados.
14. **Legendas SRT**: exporte somente a faixa/seleção; legendas manuais/alteradas devem aparecer se estiverem naquele alcance. Confira sincronização depois de acelerar para 2× ou 10×.

## Notas honestas de validação

- As rotinas acima foram cobertas por testes de lógica e FFmpeg onde aplicável. **O conjunto completo de modelos reais, a qualidade do português do Qwen e do Pocket TTS e a GUI com PySide6 no Windows ainda precisam de testes no computador de destino**.
- A porcentagem do monitor é baseada em etapas e lotes concluídos. A inferência dentro de um lote pode não emitir progresso contínuo; a previsão de término é aproximada.
- O editor não tem teto fixo de memória e não promete processar qualquer gravação em sete minutos. A referência de 80 minutos → 20 minutos em sete minutos ainda precisa ser reproduzida nesta versão.
- O SRT exportado utiliza a posição **na timeline**, não a posição do trecho isolado.
- Processos são sequenciais pelo Batata Quente; pausas e cancelamentos mantêm os checkpoints já gravados.

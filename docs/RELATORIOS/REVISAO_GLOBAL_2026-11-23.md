# Revisão global — 23/11/2026

## Estado de partida

- Projeto local: `BerofelStudio 1`.
- Branch: `feat/automatic-cleanup-modules`.
- HEAD inicial: `575d31f126555320d44889d499b3085d008c839f`.
- Árvore de trabalho estava limpa antes desta revisão.
- Versão declarada: `0.10.0-alpha.1`.
- Suíte de referência reportada na sessão anterior: 456 testes, 5 ignorados; este resultado é baseline, não valida as mudanças atuais.
- A consulta WMI foi negada, mas uma leitura local sem WMI confirmou Windows, AMD64 Family 25 Model 80, 16 processadores lógicos e 15,4 GiB de RAM visível. O modelo comercial da CPU e a GPU não foram confirmados nesta rodada. Ainda não há benchmark novo dos módulos nesta revisão.

## Achados e alterações desta etapa

### P0 — alvo estável do menu de contexto da timeline

**Causa:** o menu da `TimelineView` emitia somente o ID do clipe e a janela usava seleção global. O clique direito não selecionava o alvo; seleção múltipla e ações como agrupar/copy/transição podiam trabalhar com IDs desatualizados.

**Correção:** clique direito em clipe fora da seleção seleciona-o; clique dentro da seleção preserva a seleção múltipla. O menu captura `clip_id` e `selected_ids` antes de abrir e entrega esse snapshot às ações. O contrato do sinal no `TimelineWidget` foi atualizado para transportar o objeto.

**Validação direcionada:** teste Qt offscreen cobre seleção do alvo, preservação da seleção múltipla e estabilidade do alvo quando a seleção viva muda durante o menu. Passou isoladamente.

### P0 — WAV de narração reutilizável

**Causa:** a geração somente adicionava o WAV à lista persistida de mídias quando solicitada a inserção imediata na timeline.

**Correção:** geração concluída registra o WAV em `project.media` independentemente da inserção. Foi adicionado o botão “Adicionar última narração à timeline”; ele usa o arquivo já existente, valida/obtém a duração, cria um clip e atualiza a biblioteca sem executar o serviço TTS. A reprodução continua sendo somente manual.

**Validação direcionada:** teste Qt cria um WAV local, registra-o na biblioteca, adiciona-o à timeline, verifica que a referência não é duplicada e confirma que o player permanece parado. Passou isoladamente.

### P0 — propriedades de legenda ausentes no painel

**Achado:** o painel ligado ao projeto já editava texto, família/tamanho da fonte, cor do texto, largura do contorno e posição Y. O modelo e o renderizador também aceitam `stroke_color` e `pos_x`, mas o painel dedicado não os expunha.

**Correção:** adicionados controle de cor de contorno com seletor de cor e posição X. Ambos passam pelas ações existentes de edição de propriedade, então atualizam o clipe/projeto e são usados pelo preview e exportador atuais.

**Validação direcionada:** teste Qt da edição no painel verifica tamanho, cor do contorno, posição X e preset existente. Passou; regressão completa pendente.

### P2 — atalhos em campos de texto

**Achado/correção:** atalhos de edição eram QActions globais conectadas diretamente às funções. Foi adicionado um registro central de QActions e um guarda de foco para atalhos de edição quando o foco está em `QLineEdit`, `QTextEdit`, `QPlainTextEdit`, spinbox ou combo. Salvar/importar continuam disponíveis globalmente.

**Validação direcionada:** teste Qt focalizado confirmou que Ctrl+C/V/Z não altera a seleção/clipboard de clipes quando o campo de narração está focado e que Ctrl+C continua copiando clipes com foco na timeline. Passou; regressão completa pendente.

### P0 — progresso Parakeet e pipe de diagnóstico

**Achado:** `StageRunner.run_batch` criava `stderr=PIPE`, mas só consumia o fluxo quando o subprocesso encerrava. Em chamadas longas, um filho que escrevesse bastante em `stderr` poderia preencher o pipe e bloquear; isso é um risco real do contrato de subprocesso, mas não prova que tenha causado o relato específico do Parakeet. O runtime `transcribe.cpp` não fornece callback interno de progresso durante `session.run`; a porcentagem disponível é por trecho persistido, então uma inferência longa pode permanecer entre 50% e 54% até o trecho acabar.

**Correção:** `stderr` do worker em lote agora vai para um arquivo temporário, lido ao fim e limitado aos últimos 8 KiB ao construir o erro. A etapa Parakeet informa explicitamente que não há percentual interno e que o progresso avança por trecho. Métricas CPU/RAM continuam vindo do painel de tarefas.

**Validação direcionada:** teste injeta um subprocesso que falha, confirma ausência do pipe e verifica preservação da mensagem de diagnóstico. Passou. Ainda não repeti uma inferência Parakeet real nesta rodada para afirmar que este era o motivo do atraso observado.

## Checklist de auditoria — ainda em execução

| Área | Situação desta revisão |
|---|---|
| Timeline/menu de contexto | Corrigido; 81 testes de painel/timeline e suíte completa passaram |
| Reutilização de narração WAV | Biblioteca, inserção sem TTS e salvar/reabrir testados; renomear, excluir e exportar WAV avulso ainda não auditados |
| Editor de legendas | Cor do contorno e posição X adicionadas; outros controles avançados e presets extensos ainda faltam |
| Qwen TTS Base | Diagnóstico de integração anterior existe; teste real atual não executado nesta etapa |
| Parakeet CPU/Vulkan | Risco de bloqueio de stderr corrigido e ausência de progresso interno explicada; benchmark anterior existe; inferência longa real ainda pendente |
| Cronômetro universal | Painel de processamento já mede etapas; cobertura de todos os fluxos ainda não auditada |
| Remoção de silêncio/contexto | Melhorias V2/V3 já constam no histórico; precisa de validação end-to-end humana para calibrar cortes |
| Presets profissionais de legenda | Não implementados nesta etapa |
| Biblioteca de transições | Não implementada nesta etapa |
| Atalhos | Guarda de foco implementado para atalhos de edição; janela de consulta/personalização e tooltips completos ainda faltam |
| Build/instalador | Não executado nesta etapa |
| Hardware real | Windows, AMD Family 25 Model 80, 16 CPUs lógicas e 15,4 GiB confirmados sem WMI; GPU/modelo comercial e benchmark físico novo pendentes |

## Próximas etapas

1. Suíte Qt do painel/timeline: **81 testes passaram** antes dos controles adicionais; testes Qt focalizados de legenda e proteção de atalhos passaram.
2. Pipeline ASR após a correção: **39 testes passaram**.
3. Suíte completa no código atual: **460 passaram, 5 ignorados, 0 falhas** (69,529 s). Os skips são gates opcionais para integração real de Qwen/Pure C e dicionário pt-BR. Um teste do parser de benchmark imprime o texto de uso esperado ao rejeitar threads inválidas.
4. Completar controles avançados/presets de legenda sem duplicar lógica de renderização.
5. Completar consulta/tooltip de atalhos e validar prevenção de conflitos.
6. Verificar inferência real do Parakeet em áudio longo e registrar atividade observada.
7. Continuar revisão das demais áreas priorizadas, corrigindo em unidades pequenas e testáveis.
8. Atualizar este relatório com evidências e registrar commits somente após a validação correspondente.

## Limites de evidência

Os WAVs usados nos testes desta etapa são sinais locais de fixture, adequados para validar referências e transporte Qt, não síntese real. A suíte isolada não prova o fluxo end-to-end do motor de voz nem exportação MP4.

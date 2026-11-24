# Revisão global — 23/11/2026

## Estado de partida

- Projeto local: `BerofelStudio 1`.
- Branch: `feat/automatic-cleanup-modules`.
- HEAD inicial: `575d31f126555320d44889d499b3085d008c839f`.
- Árvore de trabalho estava limpa antes desta revisão.
- Versão declarada: `0.10.0-alpha.1`.
- Suíte de referência reportada na sessão anterior: 456 testes, 5 ignorados; este resultado é baseline, não valida as mudanças atuais.
- A leitura de hardware via consultas WMI foi negada pelo ambiente. Ainda não há benchmark novo nem inspeção da máquina física nesta revisão.

## Achados e alterações desta etapa

### P0 — alvo estável do menu de contexto da timeline

**Causa:** o menu da `TimelineView` emitia somente o ID do clipe e a janela usava seleção global. O clique direito não selecionava o alvo; seleção múltipla e ações como agrupar/copy/transição podiam trabalhar com IDs desatualizados.

**Correção:** clique direito em clipe fora da seleção seleciona-o; clique dentro da seleção preserva a seleção múltipla. O menu captura `clip_id` e `selected_ids` antes de abrir e entrega esse snapshot às ações. O contrato do sinal no `TimelineWidget` foi atualizado para transportar o objeto.

**Validação direcionada:** teste Qt offscreen cobre seleção do alvo, preservação da seleção múltipla e estabilidade do alvo quando a seleção viva muda durante o menu. Passou isoladamente.

### P0 — WAV de narração reutilizável

**Causa:** a geração somente adicionava o WAV à lista persistida de mídias quando solicitada a inserção imediata na timeline.

**Correção:** geração concluída registra o WAV em `project.media` independentemente da inserção. Foi adicionado o botão “Adicionar última narração à timeline”; ele usa o arquivo já existente, valida/obtém a duração, cria um clip e atualiza a biblioteca sem executar o serviço TTS. A reprodução continua sendo somente manual.

**Validação direcionada:** teste Qt cria um WAV local, registra-o na biblioteca, adiciona-o à timeline, verifica que a referência não é duplicada e confirma que o player permanece parado. Passou isoladamente.

## Checklist de auditoria — ainda em execução

| Área | Situação desta revisão |
|---|---|
| Timeline/menu de contexto | Corrigido; 81 testes de painel/timeline e suíte completa passaram |
| Reutilização de narração WAV | Implementado parcialmente; teste Qt direcionado e suíte passaram |
| Editor de legendas | Auditado: texto, fonte, tamanho, cor, contorno e posição Y já existem; propriedades avançadas e presets extensos ainda faltam |
| Qwen TTS Base | Diagnóstico de integração anterior existe; teste real atual não executado nesta etapa |
| Parakeet CPU/Vulkan | Benchmarks anteriores existem; investigação da percepção de travamento ainda pendente |
| Cronômetro universal | Painel de processamento já mede etapas; cobertura de todos os fluxos ainda não auditada |
| Remoção de silêncio/contexto | Melhorias V2/V3 já constam no histórico; precisa de validação end-to-end humana para calibrar cortes |
| Presets profissionais de legenda | Não implementados nesta etapa |
| Biblioteca de transições | Não implementada nesta etapa |
| Registro/ajuda de atalhos | Não implementado nesta etapa |
| Build/instalador | Não executado nesta etapa |
| Hardware real | Acesso WMI negado; sem benchmark físico novo |

## Próximas etapas

1. Suíte Qt do painel/timeline: **81 testes passaram**.
2. Suíte completa no estado atual: **458 passaram, 5 ignorados, 0 falhas** (60,555 s). Os skips são gates opcionais para integração real de Qwen/Pure C e dicionário pt-BR. Um teste do parser de benchmark imprime o texto de uso esperado ao rejeitar threads inválidas.
3. Testar a persistência de mídias após salvar e reabrir projeto.
4. Auditar/expandir controles do painel de legendas sem duplicar lógica de renderização.
5. Verificar progresso e heartbeat nos fluxos Qwen/Parakeet.
6. Continuar revisão das demais áreas priorizadas, corrigindo em unidades pequenas e testáveis.
7. Atualizar este relatório com evidências e registrar commits somente após a validação correspondente.

## Limites de evidência

Os WAVs usados nos testes desta etapa são sinais locais de fixture, adequados para validar referências e transporte Qt, não síntese real. A suíte isolada não prova o fluxo end-to-end do motor de voz nem exportação MP4.

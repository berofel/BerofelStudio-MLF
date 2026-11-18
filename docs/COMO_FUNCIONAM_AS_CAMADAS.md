> **Atualização Studio 0.3:** o Preview agora tem motor ao vivo por FFmpeg/Qt e opção de prévia MP4 de reserva. Para estado validado, consulte README.md e docs/VALIDACAO.md. Este arquivo documenta a lógica de camadas, não o estado do motor.

# Camadas universais do BerofelStudio — contrato de interface e comportamento

## Organização fixa da interface

```
┌──────────────────────────────────────────────────────────────────────────┐
│ ☰ BerofelStudio                                  projeto / salvar / exportar│
├───────────────────┬───────────────────────────┬──────────────────────────┤
│ BIBLIOTECA        │ PREVIEW                   │ PROPRIEDADES             │
│ videos            │ reproduzir fonte          │ bloco selecionado        │
│ audios            │ quadro composto           │ posicao, opacidade       │
│ imagens           │                           │ volume, escala, texto    │
├───────────────────┴───────────────────────────┴──────────────────────────┤
│ TIMELINE - quatro camadas universais iniciais; adicione quantas quiser   │
│     Camada 4  [TÍTULO           ]                                        │
│     Camada 3  [NARRAÇÃO] [IMAGEM]   (audio e imagem na MESMA trilha)      │
│     Camada 2  [VÍDEO A         ][VÍDEO B]                                │
│     Camada 1  [BACKGROUND                                           ]   │
└──────────────────────────────────────────────────────────────────────────┘
```

**NUNCA reorganizar a posição da biblioteca, preview e propriedades para outra linha.** O usuário aprovou esses três painéis fixos. Quando faltar espaço, os elementos internos de cada painel se reorganizam em linhas novas, e o painel pode fazer rolagem vertical invisível. No preview, manter proporção da imagem. A timeline é linear, horizontal e NÃO tem carrossel. O carrossel circular é exclusivo da faixa de ferramentas, aberta pelo ☰.

## Regra visual de empilhamento

A lista `project.tracks` é armazenada **da frente para o fundo** (índice 0 mais alto). A exportação inverte a lista e aplica overlays do fundo para frente. Um vídeo opaco cobrindo todo o quadro oculta imagem/texto de trás. Um título acima do vídeo aparece sobre ele. Se o usuário quiser um quadro ou câmera sobreposta em um canto, pode reduzir a escala da imagem, mudar X/Y e a opacidade do bloco de cima.

A mudança de ordem da trilha inteira altera o Z de **todos** os clipes visuais que ela contém. Mudar um clipe de trilha altera somente o Z dele. Não existe restrição de que título seja sempre em cima ou narração embaixo.

## Regra de áudio

Audio não se comporta como pixels. A narração pode estar na mesma faixa e no mesmo tempo do vídeo sem apagar o áudio do vídeo. Todos os itens sonoros habilitados são misturados pelo motor de áudio. Controles atuais: volume por clipe, mute por camada e incluir/retirar áudio embutido de um vídeo. Ducking automático, medidores LUFS, fades e panorâmica permanecem para versões futuras. Um clipe de áudio colocado mais alto visualmente **não ganha volume automaticamente**.

## Uma mesma trilha pode ter dois elementos no mesmo tempo

Ex.: bloco de vídeo das 00:05 até 00:10 e bloco de narração das 00:06 até 00:09, ambos na Camada 2. A timeline desenha **duas sublinhas visuais** da Camada 2. Elas representam a mesma camada lógica; não são faixas tipadas de música e narração. A posição no tempo de nenhum clipe é alterada ao criar sublinhas. Para dois visuais que coincidam na mesma camada, o controle **Ordem dentro da camada** do clipe (propriedades) define qual visual fica acima; ao importar, novos blocos recebem uma ordem maior automaticamente.

## Edição não destrutiva

Cada bloco armazena `source`, `start/end` na **mídia bruta** e `timeline_start` na edição. Pode mover de trilha sem mexer na mídia original. Recorte à esquerda/direita ajusta o intervalo de origem e a posição da borda; se o trecho original existir, arrastar de volta pode recuperar mídia antes removida da borda. Corte dividido cria novas instâncias. Remover silêncio selecionado compacta **somente os sobreviventes do bloco analisado**, mas não desloca blocos não selecionados: se houver diferença de duração, poderá restar um espaço. Ripple profissional para vizinhos será escolha explícita na próxima etapa.

## Análise IA do usuário (NUNCA automática)

1. Arquivo importado à biblioteca: nenhuma análise.
2. Arquivo colocado na timeline: nenhuma análise.
3. Usuário corta o arquivo em três blocos e seleciona o bloco do meio: analisa SOMENTE o intervalo de origem apontado pelo bloco do meio.
4. Usuário seleciona vários blocos com Ctrl+clique: analisa o conjunto, **separadamente por ID de bloco**.
5. Só após clicar em Analisar Silêncios / Falas Repetidas o processamento começa.
6. As sugestões são revistas e aplicadas somente nos blocos selecionados, sem alteração dos arquivos originais. `Ctrl+Z` desfaz.

Silêncio acústico usa FFmpeg `silencedetect`; não confundir com Silero VAD. A análise de repetições com Faster-Whisper usa comparação textual experimental, não entende sempre repetições intencionais.

## Teclas e ferramentas

- `V` seleção e `B` lâmina quando timeline tem foco, para não roubar letras digitadas nas propriedades.
- `Ctrl+K` divide somente selecionados que cruzam cursor.
- Ctrl+arraste bloco entre camadas não é obrigatório: arrastar simples move, `Ctrl+clique` seleciona vários blocos.
- ↑ e ↓ do cabeçalho trocam camadas inteiras; clique direito renomeia ou remove vazia.
- Ocultar `◉` afeta somente imagem; silenciar `♫` afeta somente áudio; bloquear `▣` impede alterar blocos.
- Zoom via `Ctrl+roda` muda escala horizontal, nunca faz timeline circular.

## Tecnologias do estágio 0.2 vs direção futura

| Camada técnica | Alpha 0.2 | Versão posterior |
|---|---|---|
| Interface | PySide6 widgets, QGraphicsView, toolkit original | Refinar visuais com Qt Quick/QML se a performance justificar |
| Preview | Qt Multimedia para reproduzir um arquivo isolado; FFmpeg para um frame composto estático | MLT para reprodução contínua de todas as camadas |
| Exportação | FFmpeg filter_complex (overlays + amix), 720p30 | MLT ou motor unificado com proxy, keyframes, transições, GPU quando possível |
| IA | silencedetect e Faster-Whisper experimental, sob comando | Silero VAD ONNX, transcrição com legenda editável, TTS Pocket testado |
| Projeto | JSON v2 guarda fontes, posição, trilha, duração, opacidade, volume, escala | SQLite/cache por mídia, versões, autosave robusto, multi-usuário futuro |

Uma trilha universal na UI **não obriga o motor interno a usar uma única trilha física**. No futuro adaptaremos cada mídia para streams de áudio/vídeo separados conforme necessidade técnica do MLT; o usuário verá sempre a sua camada universal editável. Essa separação é necessária para mixagem e efeitos com sincronização correta.

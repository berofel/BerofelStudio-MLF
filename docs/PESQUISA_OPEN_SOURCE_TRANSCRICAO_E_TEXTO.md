# Pesquisa open source: transcrição e revisão de texto

## Direção

O Berofel Studio já tem um pipeline local com Faster-Whisper, Silero e regras
Python para limpeza. O melhor ganho de baixo custo é reduzir trabalho repetido
e aproveitar texto realmente confirmado pelo usuário. Não adicionar outro
modelo de fala, servidor de linguagem ou chamada de rede ao fluxo normal.

## Projetos e decisões

| Projeto | O que aproveitamos | Decisão de recursos |
| --- | --- | --- |
| [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) | Transcrição local existente, `hotwords`, timestamps por palavra | Manter como único ASR ativo. Reusar transcrição/cache em vez de retranscrever para cada módulo. |
| [Buzz](https://github.com/chidiwilliams/buzz) | Referência de fluxo de transcrição e revisão incremental | Não copiar “Append and correct” para mídia pronta: o próprio projeto documenta que passos curtos elevam carga e que correção incremental custa mais processamento. |
| [Subtitle Edit](https://github.com/SubtitleEdit/subtitleedit) | Referência de edição de legendas, sincronização visual e escolha explícita de mecanismo ASR | Reaproveitar ideias de revisão e timing; seus vários motores/modelos baixáveis não devem virar dependências simultâneas do Berofel. |
| [whisper.cpp](https://github.com/ggml-org/whisper.cpp) | Alternativa C/C++ CPU com quantização e otimizações de hardware | Candidato a comparação experimental futura; trocar agora duplicaria o ASR e exige avaliar PT-BR, timestamps e qualidade no mesmo áudio. |
| [Vosk](https://github.com/alphacep/vosk-api) | ASR offline com modelos pequenos e vocabulário adaptável em alguns modelos | Alternativa de baixa memória a medir, mas não substitui Faster-Whisper sem teste de qualidade PT-BR, palavras/timestamps e compatibilidade do pipeline. |
| [WordCraft](https://github.com/storytold/wordcraft) | Modelo de produto para localizar dicionários por idioma e explicitar a origem do corretor | Não é motor de transcrição; serve como referência de organização. Manter dados linguísticos separados do código e sem downloads silenciosos. |
| [LibreOffice VERO / dicionários](https://github.com/LibreOffice/dictionaries) | Fonte candidata para dicionário pt-BR Hunspell e vocabulário ortográfico | Ainda não integrado. Conferir licença e atribuição dos arquivos específicos antes de distribuí-los. |
| [Spylls](https://github.com/zverok/spylls) | Port Python quase completo do Hunspell | Avaliar como componente opcional para sugestões ortográficas; não usar para cortes de áudio nem corrigir transcrição automaticamente. |
| Word e Google Docs | Referência documentada para ditado, pontuação e edição por voz | São referências de interação. Seus algoritmos internos não são open source e não são tratados como código ou modelo reutilizável. |

## Alteração implementada

O Faster-Whisper usa hotwords como dicas de reconhecimento, não como verdade.
Por isso, uma palavra isolada reconhecida pelo ASR não deve imediatamente
reforçar o mesmo ASR. O vocabulário dinâmico agora exige repetição em fontes
distintas ou em posições separadas por pelo menos 30 segundos. Frases de
produto ditas pelo usuário em legendas manuais ou legendas automáticas editadas
podem entrar como confirmação. A lista continua limitada por quantidade e
caracteres e é calculada localmente.

Essa proteção só influencia novas transcrições. Não altera transcrições já
salvas, não muda timestamps e não aprova cortes. As legendas automáticas sem
edição não são consideradas confirmação.

## Recursos não adicionados

- Nenhum modelo ASR adicional ou dicionário foi baixado.
- Não adicionamos spaCy, LanguageTool, Hunspell ou Spylls como dependência
  obrigatória. No ambiente auditado não havia esses componentes/dicionários.
- Uma checagem ortográfica futura deve gerar sugestões revisáveis e nunca
  substituir palavras temporizadas silenciosamente; um corretor de texto não
  pode inventar os tempos de fala.
- “Append and correct” em áudio ao vivo pode repetir inferência sobre janelas
  sobrepostas. É inadequado como otimização automática para a edição de vídeo
  sem benchmark local e controle de custo.
- Não instalar um segundo ASR só porque existe uma versão C++: o custo do
  pacote/modelo e eventual duplicação de cache podem superar ganhos. Primeiro
  medir com o mesmo áudio, CPU, idioma, configuração de threads, WER/CER e
  qualidade dos timestamps.

## Medição local da coleta de vocabulário

Microbenchmark sintético com 50.000 palavras de transcrição:

| Implementação | Média da coleta | Pico temporário adicional | Limite de dicas |
| --- | ---: | ---: | ---: |
| Antes desta alteração | mediana 0,1556 s | 19,36 MiB | 296 caracteres |
| Atual | mediana 0,1462 s | 0,035 MiB | 296 caracteres |

O tempo foi medido em nove execuções sem instrumentação; pico temporário foi
medido separadamente com `tracemalloc`. Neste conjunto sintético a coleta ficou
cerca de 6% mais rápida e a alocação temporária caiu aproximadamente 99,8%.
Isso não mede tempo de inferência do Whisper nem precisão em áudio humano. Os
dados não foram enviados para fora do computador.

## Referências

- Faster-Whisper: [API de transcrição](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/transcribe.py)
- [Subtitle Edit: mecanismos de fala para texto](https://github.com/SubtitleEdit/subtitleedit/blob/main/docs/features/speech-to-text.md)
- [whisper.cpp](https://github.com/ggml-org/whisper.cpp), [Vosk](https://github.com/alphacep/vosk-api)
- Buzz: [gravação ao vivo](https://github.com/chidiwilliams/buzz/blob/main/docs/docs/usage/2_live_recording.md), [preferências](https://github.com/chidiwilliams/buzz/blob/main/docs/docs/preferences.md), [FAQ e consumo relativo](https://github.com/chidiwilliams/buzz/blob/main/docs/docs/faq.md)
- WordCraft: [dicionários de ortografia](https://github.com/storytold/wordcraft/blob/main/docs/spelling-dictionaries.md)
- Spylls: [port Python do Hunspell](https://github.com/zverok/spylls)
- LibreOffice: [repositório de dicionários](https://github.com/LibreOffice/dictionaries)
- Ditado: [Microsoft Word](https://support.microsoft.com/en-gb/word/dictate-your-documents-in-word-for-the-web?redirectsourcepath=%2Farticle%2Fdictate-with-your-voice-in-office-d4fd296e-8f15-4168-afec-1f95b13a6408), [Google Docs](https://support.google.com/docs/answer/4492226?hl=en-PE)

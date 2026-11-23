# Limpeza automática local

A área de edição automática oferece três seleções independentes: **Remover
silêncios**, **Vícios de linguagem** e **Contexto**. A fila usa o Silero e o
Faster-Whisper já integrados ao editor; a análise lexical/contextual é feita
com regras Python determinísticas. Nenhuma dessas três opções inicia Qwen,
LLM, API ou download de modelos.

| Seleção | Serviços usados | Resultado |
| --- | --- | --- |
| Silêncios | Silero VAD | Sugestões de pausas; sem transcrição |
| Vícios | Transcrição persistida ou Faster-Whisper se faltar | Hesitações e repetições adjacentes confirmadas |
| Contexto | Silero para âncoras de pausa + transcrição persistida/Whisper | Sugestões conservadoras de reformulação; pausas não são cortadas |
| Combinações | Reutiliza VAD/transcrição da execução e os caches existentes | Plano consolidado, intervalos sobrepostos unificados |

Os tempos do plano são segundos relativos à mídia original. A aplicação continua
passando pela revisão de cortes, preserva o arquivo de origem e usa o sistema
existente de corte não destrutivo, sincronismo de áudio/legendas e Undo. Nenhuma
seleção marcada significa que nenhuma análise é iniciada.

O detector contextual usa proximidade de pausa, agrupamento de palavras,
normalização leve de flexões/PT-BR, alinhamento de sequência, cobertura de
termos informativos e proteções para negação, números e ações opostas. Pausa
longa isolada ou mera sobreposição textual não aprova corte. Casos duvidosos
permanecem preservados.

O comparador também calcula e mantém em cache uma assinatura curta por frase
(tokens normalizados, conceitos, ações, números e negação). Há equivalências
controladas para alguns termos comuns do editor, usadas somente para encontrar
candidatos. Uma lista pequena de vocabulário do produto pode ser passada ao
Faster-Whisper quando a limpeza precisa criar uma transcrição; ela participa da
chave de cache e não reescreve palavras nem seus timestamps. Uma transcrição já
existente continua sendo reutilizada sem executar Whisper.

Essa lista inclui termos frequentes/confiança alta de transcrições já salvas no
projeto, além dos nomes fixos dos motores e recursos do editor. A coleta roda
localmente, ignora palavras comuns e itens de baixa confiança, e tem limite de
quantidade/tamanho. Os termos não são enviados a serviços externos. Como o
Whisper trata hotwords como dicas de decodificação, elas podem favorecer uma
palavra esperada e também enviesar o resultado; por isso não substituem a
revisão nem são usadas como correção ortográfica confirmada.

Autocorreções explícitas como “na verdade”, “quer dizer” e “ou melhor” recebem
tratamento direcional. Uma mudança de número ou negação só pode passar pela
proteção quando a nova oração retém evidência suficiente do mesmo tópico; o
marcador sozinho não autoriza remoção. Ainda assim, essas regras são heurísticas
conservadoras, não uma medida de precisão validada em gravações anotadas.

## Reconhecimento de fala e comandos de voz

Word e Google Docs documentam ditado com pontuação e comandos de edição por
voz. Isso serve como referência de interação: reconhecer corretamente palavras,
pontuação e correções é parte importante de um bom fluxo de ditado. A
documentação pública não descreve os algoritmos internos desses produtos, então
o Berofel não tenta reproduzi-los. Aqui, o Faster-Whisper continua responsável
pela transcrição com timestamps por palavra; as regras locais só propõem
edições e nunca inventam tempos.

Referências:

* [Ditado no Microsoft Word](https://support.microsoft.com/en-gb/word/dictate-your-documents-in-word-for-the-web?redirectsourcepath=%2Farticle%2Fdictate-with-your-voice-in-office-d4fd296e-8f15-4168-afec-1f95b13a6408)
* [Digitação por voz no Google Docs](https://support.google.com/docs/answer/4492226?hl=en-PE)
* [Opções de transcrição do Faster-Whisper](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/transcribe.py)

O fallback linguístico é Python padrão, sem spaCy nem downloads em tempo de uso.
Se `rapidfuzz` já estiver instalado, a razão textual o usa opcionalmente; sem
ele, `SequenceMatcher` permanece funcional. Tempos de VAD, transcrição, cache e
contagem de candidatos aparecem no status ao terminar. Métricas só representam
etapas medidas nesta execução; não são benchmark universal.

## Smoke local deste change

No ambiente Windows do editor, o VAD real do `faster-whisper`/Silero foi
executado sobre um WAV sintético mono de 3 s: uma chamada VAD, zero chamadas
Whisper, 1,26 s para extração+VAD e pico amostrado de 109,93 MiB no processo e
filhos. O Faster-Whisper instalado também processou um WAV sintético silencioso
de 3 s no modo Vícios: uma chamada de transcrição, zero VAD, 9,31 s e pico
amostrado de 398 MiB. Como o sinal era silêncio sintético, esses smokes validam
os caminhos reais dos motores e não medem precisão editorial em voz humana nem
representam benchmark de outra configuração de hardware.

Para validar: abra **Assistente IA**, escolha o alcance, marque qualquer
combinação dos três controles e use **Aplicar edição**. Cada sugestão começa
desmarcada e precisa ser aprovada explicitamente na revisão. Para contexto sem
remoção de silêncio, marque somente **Contexto**.

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

Essa lista também é usada pelas rotas de transcrição e legendas iniciadas pelo
editor, não apenas pela limpeza. Legendas digitadas ou corrigidas pelo usuário
contam como confirmação. Termos que vieram somente do ASR entram apenas quando
reaparecem em fontes distintas ou estão separados por pelo menos 30 segundos,
reduzindo o ciclo em que um erro de transcrição se reforça imediatamente. A
coleta roda localmente, ignora palavras comuns e itens de baixa confiança, e
tem limite de quantidade/tamanho. Os termos não são enviados a serviços
externos. Como o Whisper trata hotwords como dicas de decodificação, ainda
podem enviesar o resultado; não substituem revisão nem são usadas como correção
ortográfica confirmada.

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

Pesquisa adicional de projetos de texto open source, dicionários locais,
decisões de dependências e benchmark da coleta: [Pesquisa open source de
transcrição e texto](PESQUISA_OPEN_SOURCE_TRANSCRICAO_E_TEXTO.md).

## Revisão ortográfica local

No painel direito **Legendas**, selecione uma legenda e use **Revisar
ortografia**. O painel mostra sugestões do Spylls com o dicionário Hunspell
VERO pt-BR. O carregamento e a revisão rodam em segundo plano; a primeira
abertura do dicionário leva alguns segundos, e as próximas usam o cache da
sessão. A revisão funciona sem rede depois da instalação. Selecione uma sugestão e aplique; depois
use **Aplicar texto** para salvar a alteração no clip. O intervalo original da
palavra é validado antes de substituir, então sugestões antigas não sobrescrevem
texto modificado.

Para instalar o dicionário uma vez, execute `scripts/instalar_corretor_pt_br.py`
com o Python do ambiente BFS. O script baixa apenas os dois arquivos VERO da
revisão fixa `1e848fbddd7fd8e03fb696ecc03ee1068fab141c`, verifica os Git blob
SHA-1 antes de instalar em `%LOCALAPPDATA%\BFS\dictionaries`, registra a licença
e instala `spylls==0.1.7` somente se estiver ausente. O fluxo de instalação
opcional da IA também tenta preparar o dicionário; se a rede falhar, a instalação
do Whisper permanece válida e a ortografia pode ser preparada depois. O VERO é
licenciado pelo upstream sob LGPLv3/MPL. A revisão não muda transcrição nem
timestamps e não utiliza modelos generativos.

O fallback linguístico é Python padrão, sem spaCy nem downloads em tempo de uso.
Se `rapidfuzz` já estiver instalado, a razão textual o usa opcionalmente; sem
ele, `SequenceMatcher` permanece funcional. Tempos de VAD, transcrição, cache e
contagem de candidatos aparecem no status ao terminar. Métricas só representam
etapas medidas nesta execução; não são benchmark universal.

O detector de vícios também reconhece inícios literais repetidos, como “eu
vou, eu vou mostrar”, somente quando encontra a mesma abertura, pontuação de
reinício, intervalo curto e continuação depois da segunda ocorrência. Repetir
apenas “muito”, “mais”, “bem” e outros intensificadores conhecidos é preservado
como possível ênfase. Os cortes continuam como sugestões revisáveis.

Em um microbenchmark sintético de 50.000 palavras sem reinícios candidatos,
as regras de vícios levaram 0,108 s de mediana em sete execuções aquecidas. O
pico temporário rastreado por `tracemalloc` foi 4,47 MiB em uma execução; essa
métrica não inclui RSS do processo, áudio, VAD nem Whisper e não é uma garantia
para hardware diferente.

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

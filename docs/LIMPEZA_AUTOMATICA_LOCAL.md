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
| Combinações | Reutiliza VAD/transcrição da execução e os caches existentes | Plano consolidado; sobreposições ficam separadas e conflitantes não podem ser aplicadas juntas |

Os tempos do plano são segundos relativos à mídia original. A aplicação continua
passando pela revisão de cortes, preserva o arquivo de origem e usa o sistema
existente de corte não destrutivo, sincronismo de áudio/legendas e Undo. Nenhuma
seleção marcada significa que nenhuma análise é iniciada.

O detector contextual usa proximidade de pausa e reinícios reconhecíveis sem
pausa, agrupamento de palavras, normalização leve de flexões/PT-BR, alinhamento
de sequência, n-gramas, cobertura direcional de informação e busca de sufixos
em falas anteriores longas. A proposta cobre somente o sufixo correspondente,
preservando informação distintiva anterior. Protege negação, números, condições,
modalidade, referências temporais, entidades, ações opostas, mudanças de
locutor conhecidos, complementos e continuações. Pausa longa isolada ou mera
sobreposição textual não aprova corte. Casos duvidosos permanecem preservados.

O comparador também calcula e mantém em cache uma assinatura curta por frase
(tokens normalizados, conceitos, ações, números, negação, condições, modalidade,
entidades e referências temporais). Há equivalências
controladas para alguns termos comuns do editor, usadas somente para encontrar
candidatos. Uma lista pequena de vocabulário do produto pode ser passada ao
Faster-Whisper quando a limpeza precisa criar uma transcrição; ela participa da
chave de cache e não reescreve palavras nem seus timestamps. Uma transcrição já
existente continua sendo reutilizada sem executar Whisper.

Quando **Contexto** está ativo, palavras desconhecidas também podem receber um
alias de ortografia para a comparação: a função usa o carregador VERO/Hunspell
já existente, com cache de sessão e limite de 512 formas. Só aplica um alias
quando a sugestão é única e muito próxima; termos aprovados, números e palavras
funcionais são preservados. O alias não altera o Faster-Whisper, o texto salvo,
as legendas nem os timestamps. Se VERO estiver ausente, o comparador segue com
as regras determinísticas sem instalar ou baixar nada.

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
marcador sozinho não autoriza remoção. Divergências com marcador de correção
recebem risco de revisão individual e ficam fora de “Selecionar todos” e da
aprovação em massa. Nenhuma sugestão de contexto é automaticamente aplicada.
Ainda assim, essas regras são heurísticas conservadoras, não uma medida de
precisão validada em gravações anotadas.

Sugestões de módulos diferentes nunca são fundidas em um intervalo maior. A
fila preserva cada origem e marca propostas sobrepostas; se duas conflitantes
forem selecionadas para o mesmo bloco, a aplicação inteira é recusada até que
uma delas seja desmarcada. A edição segue pela revisão existente, com origem
intacta e Undo.

O refino de borda por energia RMS do pacote V2 não foi conectado: os relatórios
do pipeline atual não entregam um buffer PCM original em memória ao planejador.
O código não reabre nem renderiza o áudio apenas para refinar um corte; os
limites atuais continuam usando timestamps de palavra e as margens já presentes
na aplicação da timeline.

Como proteção distinta do refino de borda, a etapa VAD agora mede energia RMS
em janelas de 20 ms no PCM que ela já carregou para o Silero. Regiões audíveis
sustentadas (limiar interno inicial -44 dBFS; lacunas até 40 ms agrupadas;
spikes isolados descartados) são adicionadas somente à máscara que protege
candidatos de silêncio. Elas não são chamadas de fala, não viram palavras e não
alteram os tempos do Whisper. Assim, efeitos de jogo/música audíveis podem
dividir uma pausa candidata; o limiar é conservador e pode preservar ruído de
fundo. A versão dos parâmetros mudou na chave do cache para invalidar VAD antigo.
Isso não substitui a revisão humana.

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
texto modificado. Termos técnicos e nomes com maiúsculas internas ou números
reaproveitados de legendas do usuário são tratados como vocabulário aprovado;
auto-legendas inalteradas e palavras comuns não são isentas do corretor.

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

Após adicionar proteção RMS, um smoke real com áudio falado FLEURS PT-BR
(17,76 s, licença CC-BY-4.0) percorreu FFmpeg → Silero/RMS em 0,87 s, com três
regiões de fala, 15,35 s detectados como fala, duas propostas de pausa e dois
misses de cache. A ação chamou somente extração e VAD, sem Faster-Whisper. Este
único clipe verifica integração/caminho de dados, não é corpus de retakes nem
valida precisão editorial; o WAV ficou na pasta temporária e não entrou no Git.

Para validar: abra **Assistente IA**, escolha o alcance, marque qualquer
combinação dos três controles e use **Aplicar edição**. Cada sugestão começa
desmarcada e precisa ser aprovada explicitamente na revisão. Para contexto sem
remoção de silêncio, marque somente **Contexto**.

Os testes determinísticos da integração ficam em
`tests/test_automatic_cleanup.py`. A suíte principal foi executada por um venv
temporário com as dependências declaradas e SciPy auxiliar: 452 passaram e 5
foram ignorados. A suíte independente do ZIP V3 passou com 46/46 testes,
incluindo os testes opcionais de refino RMS, no ambiente temporário com NumPy.

Benchmark sintético, não representativo de voz ou do pipeline completo: 46.000
palavras e 1.999 pausas artificiais foram processadas pelo comparador integrado
em cinco repetições aquecidas, com p50 de 5,627 s e máximo observado (p95
empírico conservador nesta amostra pequena) de 5,631 s; pico RSS amostrado do
processo 38,2 MiB, incluindo o corpus sintético em memória, e pico temporário
Python medido separadamente com `tracemalloc` de 5,42 MiB. O CPU reportou
família AMD 25/modelo 80, 8 núcleos/16 lógicos; a consulta do modelo comercial
exato foi negada, então não atribuímos o resultado especificamente ao Ryzen
7 5700G. Não foram medidos Whisper, Silero, aplicação/exportação, latência de
áudio, p95 estatístico robusto nem precisão/cobertura em fala humana.

Ainda é necessário validar propostas contra um corpus PT-BR anotado e executar
o fluxo visual com mídia real. A integração não declara benchmark end-to-end nem
precisão editorial em áudio humano.

## Retomadas com comandos de regravação — Python V3

O motor contextual existente agora reconhece comandos locais de retomada
(`deixa eu refazer`, `vou falar de novo`, `vamos refazer`, entre outros) como
ponte entre tentativas. O comando não integra o intervalo sugerido para corte.
Quando existe essa ponte, a busca reversa pode alcançar até cinco falas
anteriores e 70 segundos; sem o comando permanecem os limites anteriores de
quatro falas e 35 segundos. A tentativa mais recente é avaliada primeiro.

As assinaturas de comparação também distinguem sujeito e pergunta/resposta,
normalizam algumas quantidades escritas para compará-las com dígitos e protegem
palavras críticas contra aliases ortográficos. São verificações de segurança
heurísticas; toda sugestão de Contexto continua sujeita à revisão.

Teste comparativo sintético no Python do ambiente BFS/Windows, com 17.500
palavras e 2.499 pausas artificiais, três execuções por versão e `tracemalloc`:
HEAD teve 2.499 candidatos, p50 4,319 s, máximo 4,494 s e pico temporário
3,63 MiB; a versão V3 integrada teve 2.499 candidatos, p50 4,817 s, máximo
4,838 s e pico 3,61 MiB. Nesse conjunto comum, a lógica adicional custa cerca
de 12% de tempo e reduz 0,02 MiB de pico rastreado; portanto, não é reportada
como otimização de desempenho. O conjunto repetitivo tampouco mede
precisão/cobertura de fala.
Não foram medidos ASR, VAD, interface ou exportação, nem usada gravação humana
anotada. O modelo exato de CPU deste ambiente não foi confirmado.

## Avaliação do pacote Upgrade Global Python V3

O ZIP foi executado como referência isolada: 46 testes passaram. O benchmark
sintético do pacote processou 17.500 palavras; nesta execução, V2 mediu 1,176 s
e pico Python rastreado de 2,6 MiB, enquanto V3 mediu 1,180 s e 2,0 MiB. Ele
não inclui áudio, ASR, VAD, Qt ou timeline e, portanto, não demonstra ganho no
editor.

A branch já continha as funções principais da proposta V3: busca reversa de
até cinco tentativas, ponte por comandos de regravação, cobertura direcional,
normalização controlada, proteção de dados críticos e revisão não destrutiva.
O protótipo independente não foi instalado como um segundo motor. Na
comparação determinística refeita nesta execução, usei dez pares: três
retomadas/reformulações, uma autocorreção numérica que exige revisão e seis
casos que devem ser preservados. O motor integrado propôs os quatro casos
esperados (autocorreção marcada para aprovação individual) e não propôs os seis
casos protegidos. O `LocalCleanupV3` do ZIP também encontrou os quatro
esperados, mas fez mais dois cortes candidatos indevidos: 50 vs. 150 arquivos e
uma frase com “também” que acrescentava informação. São fixtures textuais
determinísticas, não acurácia em fala humana.

Foram adicionadas duas verificações ao motor integrado: preservar ênfase por
repetição adjacente (por exemplo, “muito, muito importante”) quando uma versão
posterior a reduz, e preservar complementos marcados por palavras aditivas em
qualquer posição da frase. O conjunto direcionado de limpeza passou com 33
testes após essas alterações. A validação completa com gravações PT-BR
anotadas continua pendente; propostas contextuais seguem obrigatoriamente na
fila de revisão.

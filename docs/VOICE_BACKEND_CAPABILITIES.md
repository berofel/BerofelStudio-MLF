# Capacidades vocais locais

O módulo `berofel.services.voice_intelligence.capabilities` consulta os recursos de linha de comando de um executável Pure C usando `--help` e `--caps`. Essa inspeção não carrega modelo. Flags anunciadas são separadas de recursos aceitos por requisição HTTP; não se infere suporte apenas pelo nome de uma flag.

| Recurso | Evidência local consultada | Limite conhecido |
|---|---|---|
| Qwen3-TTS Base 0.6B | Diretório local de pesos, identificador no aplicativo e síntese local | Identificação de build/source do executável desconhecida |
| Pure C Mixed CPU | `--quant-mixed-cpu`: Talker INT8 + Code Predictor INT4 | Não equivale a INT8 uniforme |
| Pure C INT8 | `--int8`: Talker INT8 + Code Predictor INT8; WAV gerado localmente | Uma repetição curta não qualifica desempenho/qualidade geral |
| Clone por x-vector | `--load-voice`, `--xvector-only` | Voz vinculada à inicialização do servidor |
| ICL / `.qvoice` | Flags e extensões anunciadas em `--help` | Arquivo compatível não foi exercitado |
| Campo HTTP `emotion` | Teste local com seed fixo: status 200, mas o WAV resultou byte a byte idêntico ao pedido neutro | O campo não teve efeito observável nesta build do servidor |
| `--emo-ref` / `--emo-ref-text` pela CLI | O binário gerou WAV válido com referência emocional e texto obtido pelo Parakeet | Execução one-shot; efeito perceptivo não foi avaliado e inclui custo de carga do modelo |
| `--emo-ref` / `--emo-ref-text` na inicialização do servidor | Servidor persistente gerou WAV distinto do servidor sem referência, com as mesmas solicitações HTTP | Integração experimental do editor; hash diferente não demonstra melhora emocional nem preservação de identidade |
| ASR de revisão | Parakeet TDT v3 ONNX INT8, CPUExecutionProvider | Não é medida de identidade vocal |

Na verificação do executável local em 25/11/2026, `--help` anunciou `--emo-ref` e `--emo-ref-text` (WAV mono 24 kHz com transcrição), além de `--emotion-strength`. Em teste one-shot, `--emo-ref` produziu WAV válido, mas a execução levou 11,564 s para 4,32 s de áudio; a baseline sem essa opção levou 5,222 s para 4,24 s. Foi uma única repetição por condição e não houve escuta; os tempos incluem inicialização do processo/modelo, portanto são exploratórios.

O servidor persistente foi testado separadamente: duas requisições idênticas, com seed 42, uma neutra e outra com campo HTTP `emotion: joy`, retornaram status 200 e o mesmo SHA-256 de WAV (`2fbcd01b…e825f2ed5`). O campo HTTP não teve efeito observável nesta build. Já `--emo-ref` e `--emo-ref-text` foram testados na inicialização de um servidor persistente, e a solicitação pelo endpoint local produziu outro WAV válido. O editor agora oferece esse caminho apenas como opção experimental: referência emocional é carregada no início do servidor, a transcrição deve ser revisada, e trocar o exemplo reinicia o servidor. Não há controle de intensidade nem seleção de emoção isolada; o efeito perceptivo ainda não foi avaliado. A receita Pure C para 0.6B separa o caminho pequeno da receita do modelo maior ([emotion 0.6B](https://github.com/gabriele-mastrapasqua/qwen3-tts/blob/main/docs/emotion-06b-recipe.md)); a documentação atual da API descreve um campo `emotion` ([serving API](https://github.com/gabriele-mastrapasqua/qwen3-tts/blob/main/docs/serving/api.md)). Essa diferença reforça a necessidade de qualificar cada executável instalado, cujo build/source permanece desconhecido.

O executável pode ser inspecionado com `inspect_purec_capabilities(path)`. O resultado inclui SHA-256 para vincular o diagnóstico ao arquivo concreto. O build local observado retornou identificação de build/source desconhecida; portanto não se atribui a ele um commit upstream específico.

O controle de estilo do painel só aparece quando a build instalada anuncia `--emo-ref` e `--emo-ref-text`, exige transcrição e documenta WAV mono 24 kHz. Essa verificação (`--help`/`--caps`, sem carregar pesos) é cacheada por caminho, tamanho e data de modificação do executável; a chamada de geração repete a guarda lógica. Em builds incompatíveis, o controle fica oculto e a interface explica a indisponibilidade. O argumento HTTP `emotion` continua desativado.


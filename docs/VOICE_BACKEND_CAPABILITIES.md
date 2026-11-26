# Capacidades vocais locais

O módulo `berofel.services.voice_intelligence.capabilities` consulta os recursos de linha de comando de um executável Pure C usando `--help` e `--caps`. Essa inspeção não carrega modelo. Flags anunciadas são separadas de recursos aceitos por requisição HTTP; não se infere suporte apenas pelo nome de uma flag.

| Recurso | Evidência local consultada | Limite conhecido |
|---|---|---|
| Qwen3-TTS Base 0.6B | Diretório local de pesos, identificador no aplicativo e síntese local | Identificação de build/source do executável desconhecida |
| Pure C Mixed CPU | `--quant-mixed-cpu`: Talker INT8 + Code Predictor INT4 | Não equivale a INT8 uniforme |
| Pure C INT8 | `--int8`: Talker INT8 + Code Predictor INT8; WAV gerado localmente | Uma repetição curta não qualifica desempenho/qualidade geral |
| Clone por x-vector | `--load-voice`, `--xvector-only` | Voz vinculada à inicialização do servidor |
| Seed de amostragem no Pure C | Três requisições no serviço canônico: seed 42 repetiu PCM byte a byte; seed 43 mudou o PCM; allowlist SHA-256 3a5f89d923bfdbea29327bd4111ecd651afa3ef448b2643b6ea8ad63dd907d13 | Opcional e ausente por padrão; outras builds falham explicitamente até nova validação |
| ICL / `.qvoice` | Flags e extensões anunciadas em `--help` | Arquivo compatível não foi exercitado |
| Campo HTTP `emotion` | Teste local com seed fixo: status 200, mas o WAV resultou byte a byte idêntico ao pedido neutro | O campo não teve efeito observável nesta build do servidor |
| Direção 0.6B por x-vector (`--emotion joy --emotion-strength`) | Com `dir_joy.bin` upstream em `presets/emovoice`, CLI one-shot e clone x-vector produziram WAV diferente do neutro | Execução fria, sem avaliação auditiva; não é a rota residente do editor |
| Emoção no servidor residente | Campo HTTP, tag `[joy]` e flag global `--emotion joy` retornaram WAV byte a byte idêntico ao neutro | Emoção por chamada, sentença ou global não teve efeito nesta build |
| `--emo-ref` / `--emo-ref-text` pela CLI | O binário gerou WAV válido com referência emocional e texto obtido pelo Parakeet | Execução one-shot; efeito perceptivo não foi avaliado e inclui custo de carga do modelo |
| `--emo-ref` / `--emo-ref-text` na inicialização do servidor | Servidor persistente gerou WAV distinto do servidor sem referência, com as mesmas solicitações HTTP | Integração experimental do editor; hash diferente não demonstra melhora emocional nem preservação de identidade |
| ASR de revisão | Parakeet TDT v3 ONNX INT8, CPUExecutionProvider | Não é medida de identidade vocal |

### Inventário local do ASR BVI

No ambiente medido em 25/11/2026, a rota ativa é `nemo-parakeet-tdt-0.6b-v3`, arquivo ONNX INT8 obtido do repositório `istupakov/parakeet-tdt-0.6b-v3-onnx` na revisão `8f23f0c03c8761650bdb5b40aaf3e40d2c15f1ce`. O instalador exige `onnx-asr==0.12.0`; runtime instalado: ONNX Runtime 1.31.1, provider explicitamente `CPUExecutionProvider`, NumPy 2.5.4. O manifesto local de instalação confirma o modelo/quantização/provider e arquivos:

| Arquivo | Bytes | SHA-256 |
|---|---:|---|
| `encoder-model.int8.onnx` | 652.183.999 | `6139d2fa7e1b086097b277c7149725edbab89cc7c7ae64b23c741be4055aff09` |
| `decoder_joint-model.int8.onnx` | 18.202.004 | `eea7483ee3d1a30375daedc8ed83e3960c91b098812127a0d99d1c8977667a70` |

Silero VAD também usa ONNX Runtime com `CPUExecutionProvider`, normalmente em uma thread. A execução de 1h20 documentada em `VOICE_QUALITY_BENCHMARK.md` usou quatro threads Parakeet e streaming por regiões. Esses identificadores descrevem somente a instalação medida; outra máquina deve validar seu manifesto local e não presumir os mesmos builds.

Na verificação do executável local em 25/11/2026, `--help` anunciou `--emo-ref` e `--emo-ref-text` (WAV mono 24 kHz com transcrição), além de `--emotion-strength`. Em teste one-shot, `--emo-ref` produziu WAV válido, mas a execução levou 11,564 s para 4,32 s de áudio; a baseline sem essa opção levou 5,222 s para 4,24 s. Foi uma única repetição por condição e não houve escuta; os tempos incluem inicialização do processo/modelo, portanto são exploratórios.

O servidor persistente foi testado separadamente: duas requisições idênticas, com seed 42, uma neutra e outra com campo HTTP `emotion: joy`, retornaram status 200 e o mesmo SHA-256 de WAV (`2fbcd01b…e825f2ed5`). O campo HTTP não teve efeito observável nesta build. Já `--emo-ref` e `--emo-ref-text` foram testados na inicialização de um servidor persistente, e a solicitação pelo endpoint local produziu outro WAV válido. O editor agora oferece esse caminho apenas como opção experimental: referência emocional é carregada no início do servidor, a transcrição deve ser revisada, e trocar o exemplo reinicia o servidor. Não há controle de intensidade nem seleção de emoção isolada; o efeito perceptivo ainda não foi avaliado. A receita Pure C para 0.6B separa o caminho pequeno da receita do modelo maior ([emotion 0.6B](https://github.com/gabriele-mastrapasqua/qwen3-tts/blob/main/docs/emotion-06b-recipe.md)); a documentação atual da API descreve um campo `emotion` ([serving API](https://github.com/gabriele-mastrapasqua/qwen3-tts/blob/main/docs/serving/api.md)). Essa diferença reforça a necessidade de qualificar cada executável instalado, cujo build/source permanece desconhecido.

### Revalidação da rota emocional com a build e os assets atuais

O upstream `main` consultado em 25/11/2026 descreve direções ECAPA genéricas para o 0.6B em `presets/emovoice/dir_<emo>.bin`, 1024 floats (4 KB), além de assets por voz. A licença declarada no repositório é MIT. O asset `dir_joy.bin` foi lido pelo conector GitHub (blob `4d7309484e301b2443f3ad4cc28ba3b2e90f74ec`) e usado somente em `%TEMP%`, sem ser incluído no projeto. No executável local (SHA-256 `3a5f89d923bfdbea29327bd4111ecd651afa3ef448b2643b6ea8ad63dd907d13`, build/source desconhecidos), `bin/presets/emovoice` não existe.

Com o arquivo temporário no diretório de trabalho, CLI one-shot INT8/6 threads, x-vector autorizado local, seed 42 e texto PT-BR fixo: neutro gerou 5,28 s em 36,9 s; `--emotion joy --emotion-strength 0.25` gerou 5,44 s em 32,6 s. Os WAVs e medidas RMS/ZCR diferiram. Isso confirma somente que a rota CLI aceitou e alterou a saída; não valida expressão percebida, pronúncia, identidade ou qualidade. No servidor residente, a mesma referência/texto/seed teve o hash `d1e8b429…e099cb` nas quatro condições: neutra, campo JSON `emotion: joy`, texto com `[joy]` e flag global `--emotion joy` na inicialização. O log acusou `inline markup -> per-sentence compose (1 spans)`, sem mudança do WAV. Assim, a receita CLI do upstream não pode ser presumida compatível com a API empacotada. Emoção por sentença permanece indisponível no fluxo normal; nenhum controle correspondente deve ser apresentado como funcional nesta build.

O executável pode ser inspecionado com `inspect_purec_capabilities(path)`. O resultado inclui SHA-256 para vincular o diagnóstico ao arquivo concreto. O manifesto procura automaticamente `dir_*.bin` em `presets/emovoice` relativo ao diretório do executável e valida nome conhecido, exatamente 4096 bytes, floats little-endian finitos e norma não nula; incompatíveis são listados. O build local observado retornou identificação de build/source desconhecida; portanto não se atribui a ele um commit upstream específico.

O controle de estilo do painel só aparece quando a build instalada anuncia `--emo-ref` e `--emo-ref-text`, exige transcrição e documenta WAV mono 24 kHz. Essa verificação (`--help`/`--caps`, sem carregar pesos) é cacheada por caminho, tamanho e data de modificação do executável; a chamada de geração repete a guarda lógica. Em builds incompatíveis, o controle fica oculto e a interface explica a indisponibilidade. O argumento HTTP `emotion` continua desativado.


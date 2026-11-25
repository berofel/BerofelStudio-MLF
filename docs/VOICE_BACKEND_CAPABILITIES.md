# Capacidades vocais locais

O módulo `berofel.services.voice_intelligence.capabilities` consulta os recursos de linha de comando de um executável Pure C usando `--help` e `--caps`. Essa inspeção não carrega modelo. Flags anunciadas são separadas de recursos aceitos por requisição HTTP; não se infere suporte apenas pelo nome de uma flag.

| Recurso | Evidência local consultada | Limite conhecido |
|---|---|---|
| Qwen3-TTS Base 0.6B | Diretório local de pesos e identificador no aplicativo | Síntese não executada nesta sessão |
| Pure C Mixed CPU | `--quant-mixed-cpu`: Talker INT8 + Code Predictor INT4 | Não equivale a INT8 uniforme |
| Pure C INT8 | `--int8`: Talker INT8 + Code Predictor INT8 | Não executado nesta sessão |
| Clone por x-vector | `--load-voice`, `--xvector-only` | Voz vinculada à inicialização do servidor |
| ICL / `.qvoice` | Flags e extensões anunciadas em `--help` | Arquivo compatível não foi exercitado |
| Emoção por requisição | Não validada pelo adaptador HTTP | A flag CLI não comprova integração do servidor |
| ASR de revisão | Parakeet TDT v3 ONNX INT8, CPUExecutionProvider | Não é medida de identidade vocal |

Na verificação do executável local em 25/11/2026, `--help` também anunciou `--emo-ref` e `--emo-ref-text` (referência emocional WAV mono 24 kHz com transcrição), além de `--emotion-strength`. Esses são recursos anunciados pela CLI. O backend do editor inicia um servidor persistente com `--serve` e envia texto, idioma e amostragem em `/v1/tts/stream`; ele não envia essas opções, e a API instalada não foi testada para aceitá-las. O runtime instalado não tem a pasta local `presets/emovoice`, e nenhum vetor emocional foi encontrado pelo manifesto. Portanto, a interface não deve apresentar controle emocional neural como funcional até existir integração HTTP comprovada e teste auditivo no Qwen 0.6B. A receita upstream atual distingue as rotas 0.6B/1.7B e recomenda não usar `--emotion` do 1.7B no 0.6B.

O executável pode ser inspecionado com `inspect_purec_capabilities(path)`. O resultado inclui SHA-256 para vincular o diagnóstico ao arquivo concreto. O build local observado retornou identificação de build/source desconhecida; portanto não se atribui a ele um commit upstream específico.


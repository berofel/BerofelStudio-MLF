# Berofel Voice Intelligence 2.0 — integração inicial

## Escopo implementado nesta etapa

Esta integração melhora a preparação de referências de clonagem e a forma como o texto PT-BR é enviado ao Qwen. O ASR do fluxo local continua sendo **Parakeet TDT v3 ONNX INT8 em CPU**. Faster-Whisper/Whisper não é chamado por esta implementação. A verificação opcional do WAV gerado usa explicitamente Parakeet e nunca reproduz nem regenera o áudio.

O normalizador fica em `berofel/services/voice_intelligence/text_normalizer.py`. Ele cria uma cópia de fala, preservando o texto fonte, e expande regras determinísticas para números, datas, valores, horários, unidades, siglas e abreviações PT-BR. A aplicação não altera transcrições, legendas ou roteiro original. A versão do normalizador entra nas chaves de cache; as chaves multivozes também foram versionadas para evitar reutilizar WAV sintetizado com regras antigas.

O botão **Dicionário de pronúncia PT-BR** permite registrar formas faladas para nomes e termos próprios da referência vocal selecionada. As entradas ficam em JSON local, vinculadas ao SHA-256 do conteúdo da amostra, com gravação atômica; não incluem caminho do arquivo, áudio ou embeddings. As substituições só são aplicadas à cópia textual enviada ao sintetizador. A coluna fonética é armazenada para anotação do usuário, mas IPA não é enviado ao Qwen porque essa rota não declara suporte a entrada fonêmica. A opção de contexto é verificada perto de cada ocorrência e as regras são aplicadas simultaneamente ao texto-fonte, sem substituições em cascata. Textos longos recebem as regras uma vez antes da divisão em trechos. O diretório pode ser redirecionado com `BEROFEL_PRONUNCIATION_DIR`.

A seleção da janela de referência continua limitada ao máximo aceito pelo condicionamento Qwen existente. Primeiro usa as regiões Silero disponíveis e ranqueia candidatos; depois mede PCM somente nos oito candidatos mais promissores com FFmpeg (RMS, clipping e fração quase silenciosa). Se a análise acústica não estiver disponível, volta ao ranking VAD. A pontuação é heurística, não identifica locutor nem mede fidelidade da clonagem. Não remove ruído da fonte nem altera o original.

`acoustic_analyzer.py` acrescenta medições baratas por quadros de 20 ms (RMS, pico, crest factor, clipping, taxa de cruzamento por zero e percentis do nível). A caixa de verificação local mostra esses indicadores junto ao trecho escolhido. Uma estimativa de contraste entre quadros quietos/ativos só é relatada como proxy de baixa confiança; SNR permanece indisponível sem uma referência de ruído confiável. Esses recursos não alteram os pesos do seletor até haver validação em referências rotuladas.

`quality_inspector.py` oferece checagem manual do texto sintetizado usando somente Parakeet TDT v3 ONNX INT8/CPU. WER/CER-like são taxas de edição textual aproximadas para diagnóstico, não MOS, qualidade de pronúncia nem similaridade vocal. Para reduzir divergência de formatação, o cálculo normaliza números/datas/unidades para a forma falada em uma cópia comparativa; o texto reconhecido exibido e o roteiro original não são alterados. Quando word timestamps estão disponíveis, também relata o intervalo entre a última palavra reconhecida e o fim do WAV; um intervalo grande pede escuta manual e não declara truncamento. A checagem requer FFmpeg e Parakeet local e adiciona custo de inferência; permanece sob ação explícita do usuário.

## Capacidades Pure C observadas

O manifesto consulta `--help` e `--caps` sem iniciar o servidor ou carregar pesos. A cópia local consultada em 25/11/2026 tem SHA-256 `3a5f89d923bfdbea29327bd4111ecd651afa3ef448b2643b6ea8ad63dd907d13`, tamanho 2.076.680 bytes e informa build/source desconhecidos. A ajuda confirma `--quant-mixed-cpu` como Talker INT8 + Code Predictor INT4 e `--int8` como INT8 + INT8. A opção `--emotion` é indicada para 1.7B; a ajuda diz que `--emotion-strength` é recurso 0.6B, mas isso não prova que o adaptador HTTP usado pelo editor o aceite.

Não há arquivos `dir_*.bin` no diretório de assets consultado. O adaptador atual carrega um perfil vocal na inicialização do servidor e não valida mudança de voz ou vetor emocional por requisição. Por segurança, esta etapa não expõe sliders de emoção nem promete controle neural inexistente. A documentação Pure C descreve steering por vetor para 0.6B, mas requer assets compatíveis e validação auditiva; não foi ativado.

## Execução e validação

Os testes sem dependências de áudio/UI são executados com:

```powershell
python -m unittest tests.test_voice_intelligence -v
python -m unittest tests.test_qwen3_tts_local.QwenLocalCloneTests.test_reference_window_selection_avoids_leading_silence_and_searches_full_file -v
```

O runtime Python disponível durante esta etapa não contém NumPy, SciPy, PySide6, Pillow, ONNX Runtime ou `onnx-asr`. Portanto não foi possível executar síntese Qwen real, ASR Parakeet real, inspeção acústica PCM com dependências completas, GUI, reprodução ou benchmark de tempo/RAM. Não há resultados auditivos ou RTF novos a declarar. A suíte completa executou 438 testes: 57 erros por dependências ausentes ou módulos dependentes delas e 119 skips; os testes executáveis não indicaram falhas de asserção. Isso não é uma aprovação da suíte completa.

## Limitações e próximos passos de validação

* Instalar o conjunto de dependências já definido pelos manifestos do aplicativo em ambiente de teste; não foi adicionada dependência nesta etapa.
* Rodar `python -m pytest -q` no ambiente de desenvolvimento completo e validar a interface real.
* Sintetizar frases PT-BR com ambos os presets Pure C e inspecionar auditivamente clonagem, sotaque, omissões e final de WAV.
* Comparar janelas selecionadas com amostras autorizadas e rótulos humanos antes de calibrar pesos.
* Validar a checagem Parakeet no WAV, com transcrição de referência e amostras reais. O próprio ASR pode errar e uma boa transcrição não comprova identidade vocal.
* Emotion direction, ICL, grafts, qualidade perceptual, ajustes DSP automáticos e regeneração seletiva permanecem fora do escopo validado desta etapa.


# Berofel Voice Intelligence 2.0 — integração inicial

## Escopo implementado nesta etapa

Esta integração melhora a preparação de referências de clonagem e a forma como o texto PT-BR é enviado ao Qwen. O ASR do fluxo local continua sendo **Parakeet TDT v3 ONNX INT8 em CPU**. Faster-Whisper/Whisper não é chamado por esta implementação. A verificação opcional do WAV gerado usa explicitamente Parakeet e nunca reproduz nem regenera o áudio.

O normalizador fica em `berofel/services/voice_intelligence/text_normalizer.py`. Ele cria uma cópia de fala, preservando o texto fonte, e expande regras determinísticas para números, datas, valores, horários, unidades, siglas e abreviações PT-BR. A aplicação não altera transcrições, legendas ou roteiro original. A versão do normalizador entra nas chaves de cache; as chaves multivozes também foram versionadas para evitar reutilizar WAV sintetizado com regras antigas.

O botão **Dicionário de pronúncia PT-BR** permite registrar formas faladas para nomes e termos próprios da referência vocal selecionada. As entradas ficam em JSON local, vinculadas ao SHA-256 do conteúdo da amostra, com gravação atômica; não incluem caminho do arquivo, áudio ou embeddings. As substituições só são aplicadas à cópia textual enviada ao sintetizador. A coluna fonética é armazenada para anotação do usuário, mas IPA não é enviado ao Qwen porque essa rota não declara suporte a entrada fonêmica. A opção de contexto é verificada perto de cada ocorrência e as regras são aplicadas simultaneamente ao texto-fonte, sem substituições em cascata. Textos longos recebem as regras uma vez antes da divisão em trechos. O diretório pode ser redirecionado com `BEROFEL_PRONUNCIATION_DIR`.

As chaves do perfil Pure C e do backend nativo agora usam SHA-256 incremental em blocos de 1 MiB para áudio de referência e cache; perfis vetoriais pequenos continuam verificáveis da mesma forma sem carregar gravações longas inteiras na memória.

A seleção da janela de referência continua limitada ao máximo aceito pelo condicionamento Qwen existente. Primeiro usa as regiões Silero disponíveis e ranqueia candidatos; depois mede PCM somente nos oito candidatos mais promissores com FFmpeg (RMS, clipping e fração quase silenciosa). Se a análise acústica não estiver disponível, volta ao ranking VAD. A pontuação é heurística, não identifica locutor nem mede fidelidade da clonagem. Não remove ruído da fonte nem altera o original.

`acoustic_analyzer.py` acrescenta medições baratas por quadros de 20 ms (RMS, pico, crest factor, clipping, taxa de cruzamento por zero e percentis do nível). A caixa de verificação local mostra esses indicadores junto ao trecho escolhido. Uma estimativa de contraste entre quadros quietos/ativos só é relatada como proxy de baixa confiança; SNR permanece indisponível sem uma referência de ruído confiável. Esses recursos não alteram os pesos do seletor até haver validação em referências rotuladas.

A mesma verificação agora estima F0 descritiva usando a diferença normalizada cumulativa YIN em no máximo 60 quadros de 40 ms distribuídos pelo trecho condicionado. O relatório mostra mediana, p10–p90, MAD em semitons, confiança mediana e quantidade de quadros aceitos apenas quando há pelo menos três quadros vozeados confiáveis. Quadros abaixo do limiar ou amostras com cobertura insuficiente não viram “0 Hz” nem recebem resumo enganoso. A medida é auxiliar para inspecionar pitch; não identifica locutor, mede emoção ou prova fidelidade do clone, e não é enviada ao Qwen nem altera o ranking/cache. Se NumPy ou a medição falhar, a verificação dos demais indicadores continua.

`quality_inspector.py` oferece checagem manual do texto sintetizado usando somente Parakeet TDT v3 ONNX INT8/CPU. WER/CER-like são taxas de edição textual aproximadas para diagnóstico, não MOS, qualidade de pronúncia nem similaridade vocal. Para reduzir divergência de formatação, o cálculo normaliza números/datas/unidades para a forma falada em uma cópia comparativa; o texto reconhecido exibido e o roteiro original não são alterados. Quando word timestamps estão disponíveis, também relata o intervalo entre a última palavra reconhecida e o fim do WAV; um intervalo grande pede escuta manual e não declara truncamento. A checagem requer FFmpeg e Parakeet local e adiciona custo de inferência; permanece sob ação explícita do usuário.

## Capacidades Pure C observadas

O manifesto consulta `--help` e `--caps` sem iniciar o servidor ou carregar pesos. A cópia local consultada em 25/11/2026 tem SHA-256 `3a5f89d923bfdbea29327bd4111ecd651afa3ef448b2643b6ea8ad63dd907d13`, tamanho 2.076.680 bytes e informa build/source desconhecidos. A ajuda confirma `--quant-mixed-cpu` como Talker INT8 + Code Predictor INT4 e `--int8` como INT8 + INT8. O binário anuncia `--emo-ref`/`--emo-ref-text`, e um teste CLI gerou WAV com esses argumentos. O teste HTTP, porém, produziu saída byte a byte igual com e sem `emotion: joy`; não há controle emocional funcional qualificado no servidor usado pelo editor. Veja medições em `VOICE_QUALITY_BENCHMARK.md`.

Não há arquivos `dir_*.bin` no diretório de assets consultado. O adaptador atual carrega um perfil vocal na inicialização do servidor e não valida mudança de voz ou vetor emocional por requisição. Por segurança, esta etapa não expõe sliders de emoção nem promete controle neural inexistente. A documentação Pure C descreve steering por vetor para 0.6B, mas requer assets compatíveis e validação auditiva; não foi ativado.

## Execução e validação

O ASR desta integração é exclusivamente **Parakeet TDT v3 ONNX INT8 em CPU**. Faster-Whisper não é usado para conferir referência nem narração. Os testes sem dependências de áudio/UI são executados com:

```powershell
python -m unittest tests.test_voice_intelligence -v
python -m unittest tests.test_qwen3_tts_local.QwenLocalCloneTests.test_reference_window_selection_avoids_leading_silence_and_searches_full_file -v
```

O Python reduzido do sistema não contém todas as dependências do app; por isso foi usado o ambiente virtual completo instalado em `%LOCALAPPDATA%\\BFS\\venv`. Na execução mais recente, a suíte `python -m unittest discover -s tests -q` passou em **571 testes e ignorou 5**, em 66,026 s. O ASR real Parakeet TDT v3 ONNX INT8/CPU transcreveu uma referência vocal local curta de 3 s (seis palavras reconhecidas; 7,56 s de execução). Uma geração Pure C real curta foi executada em cada preset de seis threads; detalhes, RTFs exploratórios e limitações estão em `VOICE_QUALITY_BENCHMARK.md`. Também passou o teste de seleção de janela que exercita FFmpeg e PCM.

Essas medições não constituem avaliação auditiva, benchmark estatístico ou validação de fidelidade vocal. GUI, reprodução manual, referência longa e perfil frio/quente repetido ainda precisam de validação. Acesso de escrita do processo sandbox ao cache de perfil padrão foi negado pelo ACL; a inferência foi concluída usando caminhos de cache/log temporários, sem alterar ACLs e sem incluir áudio privado no repositório.

O YIN foi medido separadamente em PCM sintético (tom de 145 Hz, 30 s, 1,92 MB): 60 quadros amostrados, F0 mediana 145 Hz, execução de 0,0332 s no ambiente local. É microbenchmark determinístico, não benchmark de gravação humana, qualidade nem processamento end-to-end.

Na inspeção da referência autorizada local disponível, o arquivo tinha 6,06 s; a janela analisada tinha 3,00 s. A tarefa levou 1,12 s, mas só 1 de 7 quadros amostrados passou pelos critérios de voz/confiança. O sistema corretamente não exibiu F0 agregado. Isso valida o fail-safe em uma amostra real curta; não valida estabilidade de F0 em voz contínua, nem identidade.

## Limitações e próximos passos de validação

* Repetir medições várias vezes em condições controladas e medir RAM/CPU de pico.
* Rodar a validação da interface real.
* Inspecionar auditivamente clonagem, sotaque, omissões e final de WAV, idealmente em avaliação cega.
* Comparar janelas selecionadas com amostras autorizadas e rótulos humanos antes de calibrar pesos.
* Validar a checagem Parakeet no WAV, com transcrição de referência e amostras reais. O próprio ASR pode errar e uma boa transcrição não comprova identidade vocal.
* Emotion direction, ICL, grafts, qualidade perceptual, ajustes DSP automáticos e regeneração seletiva permanecem fora do escopo validado desta etapa.


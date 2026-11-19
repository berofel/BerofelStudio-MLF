# Operação Qwen Turbo — experimento local (19/11/2026)

## Escopo e segurança

Branch isolada: `experiment/qwen3-turbo`. O backend Qwen oficial Python/float32 continua padrão e recuperável. A referência imutável `backup/qwen3-0.6b-stable` aponta para `4e4b820265ae1f38bf3d0ab7ee2b6f87febd1463`.

Backup externo verificado: `C:\Users\Berofel\Desktop\BerofelStudio_QwenTurbo_Backup_20261119-095515`. Inclui bundle Git da referência, manifestos e cópia local de configuração/perfis; os arquivos privados/modelos permanecem fora do Git. Restauração de código em outra pasta: `git clone "C:\Users\Berofel\Desktop\BerofelStudio_QwenTurbo_Backup_20261119-095515\BerofelStudio-stable.bundle" <pasta-destino>` e então `git switch backup/qwen3-0.6b-stable`. O bundle contém `feat/qwen3-base-optimized` no commit `4e4b820265ae1f38bf3d0ab7ee2b6f87febd1463` e a tag de backup. A pasta externa completa deve ser preservada para recuperar também dados locais; os hashes SHA-256 dos artefatos foram conferidos contra `backup_manifest.json`.

O runtime experimental fica em `%LOCALAPPDATA%\BFS\qwen3_tts\native_turbo`. Para instalá-lo de um build local, execute `scripts\install_qwen3_turbo_runtime.ps1` com os caminhos do build, modelo Q4 e tokenizer. O script valida arquivos e hashes, recusa substituir arquivos diferentes sem `-Replace` e cria cópia `.backup-*` antes da substituição.

## Implementação

O editor tem uma rota opcional `qwen3-tts-native-q4` para narração rápida. O modo original permanece selecionado inicialmente; Turbo aparece somente quando o runtime e os pesos locais existem. A interface avisa que a rota é experimental e permite retornar ao motor oficial.

A rota Turbo usa exclusivamente Qwen3-TTS 12Hz 0.6B Base, convertido para GGUF Q4_0 misto, com speaker encoder preservado em F16. A primeira utilização de uma gravação autorizada normaliza a referência e cria um x-vector com o próprio encoder nativo; esse vetor versionado é guardado localmente e reutilizado. O prompt nativo não é intercambiável com o embedding calculado pelo worker PyTorch em todas as precisões: o teste misto encontrou regressão de inteligibilidade com esse embedding, por isso o adaptador usa o encoder compatível do runtime experimental.

O servidor nativo persiste durante a sessão e carrega o modelo uma vez. Para o modo Turbo, o build experimental recebe PCM float32 por callback nativo, o grava em arquivo temporário incremental e o worker encaminha chunks à thread Qt; `QAudioSink` converte para PCM16 mono 24 kHz e toca enquanto a síntese continua. O WAV final completo continua sendo validado e salvo normalmente. O modo Original não abre nem toca o stream Turbo. O callback usa 6 frames (~0,5 s por chunk); chamadas sem callback mantêm o caminho sem streaming. Cache de frase idêntica existe, mas não é contado como ganho para texto novo.

A conversão Q4 é experimental: `scripts/prepare_qwen3_tts_cpp_q4_mixed.py` cria conversor separado e nunca modifica o conversor upstream. Tensor shapes incompatíveis voltam para F16. `scripts/enable_qwen3_tts_cpp_stream_file.py` habilita o arquivo PCM incremental no servidor e mantém um backup do `main.cpp` do checkout nativo. Para reconstruir o servidor experimental, aplique esse script ao checkout separado e execute `cmake --build <diretório-build> --target qwen3-tts-cli`; depois instale o executável pelo instalador verificado. A distribuição oficial do conversor investigado documenta F16/F32/Q8_0 e não declara suporte upstream a K-quants; Q4 e o stream-file são alterações locais e devem ser tratados como tal. O código nativo investigado é MIT; preservar notices do upstream e das bibliotecas de runtime. Nenhum modelo/runtime foi incluído no Git.

## Resultados medidos

Máquina: Windows x64, Ryzen 7 5700G, 16 GB RAM; modelo e referências já em disco; execução CPU offline; 4 threads; mesmas frases de teste em português, mas geração estocástica produz durações diferentes. RTF = tempo de geração / duração de áudio. RSS é pico amostrado do processo/árvore e pode variar conforme método de coleta.

| Backend/configuração | Repetições | Mediana do tempo | Duração mediana | RTF mediano | Pico RSS mediano | WER ASR mediana |
|---|---:|---:|---:|---:|---:|---:|
| Oficial Python F32, referência | 1 | 54,333 s | 10,48 s | 5,184 | 5,674 GiB | 0,9* |
| Nativo Q8_0, perfil x-vector preparado | 3 | 6,099 s | 5,04 s | 1,210 | 2,209 GiB | 0,1 |
| Nativo Q4_0 misto, x-vector preparado | 3 | 4,995 s | 4,88 s | 1,047 | 1,947 GiB | 0,2 |
| Nativo Q4_0, integração do serviço | 1 | 4,634 s | 4,56 s | 1,016 | 2,085 GiB | n/a |
| Nativo Q4_0, callback incremental | 2 | 8,313 s* | 7,20 s* | 1,155* | n/a | n/a |


a) WER é apenas comparação ASR local por Faster-Whisper base/Português/beam 1, não métrica perceptiva. Amostras curtas e estocásticas; não comprova naturalidade nem semelhança biométrica. O áudio oficial de referência teve WER elevado nesta execução, por isso não trate a tabela como superioridade acústica conclusiva. É necessária avaliação auditiva comparativa.

* Mediana das duas medições com callback incremental.

Q4 foi ~13,5% mais rápido em RTF e usou ~12% menos RSS que Q8 nas medianas observadas; em relação ao oficial medido, RTF caiu cerca de 79,8%. A duração de saída variou entre gerações, então RTF é mais informativo que comparar tempo bruto. Modelo nativo frio carregou em ~0,78–0,99 s; reutilização de x-vector custa 0 s no cache. Preparação de novo perfil ficou em ~6,6–7,0 s, separada da síntese.

Sweep exploratório (uma observação por célula, portanto não conclusivo): Q4 em 2/6/8 threads deu RTF 1,677/0,926/0,965; Q8 deu 1,801/1,157/1,225. Recomendação provisória: começar com 4 threads, pois essa é a configuração repetida três vezes e estável em torno de RTF 1,05; repetir o sweep antes de recomendar 6 threads.

Não foram obtidas métricas separadas de prefill/talker/code predictor para o runtime nativo. No oficial, o profiler mediu carga 6,008 s, prompt 0,655 s, prefill 0,413 s, 131 chamadas autoregressivas 47,645 s, das quais code predictor aninhado somou ~35,166 s; geração API 54,333 s, primeiro code frame ~0,7 s (não era áudio tocável). Isso aponta o code predictor como parcela dominante no backend oficial, mas não prova a mesma divisão interna no nativo. O script `scripts/benchmark_qwen3_stages.py` registra estágios oficiais.

## Testes / evidência da integração

- `tests.test_qwen3_native_tts` e testes Turbo do painel: testes focados passaram; teste opcional real passou usando modelo/perfil local.
- Fluxo Qt real em modo offscreen e ambiente offline (`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`): ação Gerar no painel → WAV não silencioso → media source/player em reprodução → clipe inserido na timeline → export WAV e MP4 com streams de áudio/vídeo. WAV: 2.880.102 bytes; MP4: 122.415 bytes; 10 s. Artefatos privados de teste ficaram fora do repositório em `C:\Users\Berofel\Desktop\BerofelStudio_QwenTurbo_Benchmark_20261119`.
- O playback foi iniciado pelo player Qt; o teste foi offscreen e não prova que o som foi ouvido nos alto-falantes.
- Streaming real pelo callback nativo: primeiro chunk PCM em 3,053 s após modelo/perfil prontos; 16 chunks, 698.880 bytes PCM, WAV final 7,28 s. O tempo não inclui eventual preparo inicial de perfil/modelo; retorno da chamada inclui métricas separadas para esses tempos.
- Segunda medição do serviço após a correção de ordenação: geração 8,218 s para 7,12 s de áudio; primeiro chunk 3,062 s depois de modelo/perfil prontos e 3,849 s desde o início da solicitação, incluindo 0,787 s de carga. 15 chunks totalizaram 683.520 bytes, exatamente `frames × 4` do WAV float32 intermediário; a interface recebe PCM16, metade desse tamanho.
- Fluxo real de geração via ação do editor, offscreen e com sink de áudio simulado: 453.120 bytes PCM16 foram escritos para um WAV de 9,44 s (mesma contagem de amostras mono/24 kHz); o clipe foi inserido na timeline. O teste não emitiu gravação nos alto-falantes. Separadamente, o dispositivo Windows reportou suporte a 24 kHz mono e o `QAudioSink` real processou 150 ms de amostras silenciosas. A avaliação auditiva comparativa da voz ainda depende do usuário.
- Avaliação auditiva, comparação subjetiva da voz clonada e teste com firewall de rede continuam pendentes.

## Limitações e restauração

A rota Turbo usa x-vector apenas; clonagem ICL com áudio + texto no backend nativo testado atingiu limite de frames e não foi habilitada. Clonagem detalhada mantém o backend oficial. Q4 pode variar em pronúncia/fidelidade e não deve ser selecionado automaticamente sem ouvir. Sem GPU dedicada, quantização agressiva INT4 e modo Turbo são experimentais. Não foram implementadas otimizações de Code Predictor além da quantização; não houve destilação ou remoção de codebooks.

Para rollback de código: `git switch feat/qwen3-base-optimized` ou checkout de `backup/qwen3-0.6b-stable`. Para rollback integral, restaure a pasta externa; o bundle Git sozinho não contém dados de voz/modelos. O backend original não foi alterado nem removido.

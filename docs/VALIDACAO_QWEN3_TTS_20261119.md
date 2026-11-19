# Validação da diretriz Qwen3-TTS Base único — 19/11/2026

## Fluxo real no Windows

Com internet e downloads desativados pelo ambiente (`HF_HUB_OFFLINE=1`,
`TRANSFORMERS_OFFLINE=1`), o smoke test `scripts/validar_fluxo_qwen3_editor.py`
usou localmente a gravação autorizada e a transcrição já configuradas no
BerofelStudio. Nenhum caminho, texto de referência ou áudio pessoal foi salvo
neste relatório.

| Verificação | Resultado observado |
| --- | --- |
| Modelo e backend | Qwen3-TTS Base 0.6B no worker local CPU |
| Geração acionada pela janela Qt | Passou; WAV mono 24 kHz, 10,96 s, sinal presente |
| Timeline | Bloco de áudio inserido sem alterar a gravação de referência |
| Player | Play, pause e busca confirmados; saída de áudio silenciada no teste automatizado |
| Exportação WAV | Passou, 48 kHz, sinal não silencioso |
| Exportação MP4 | Passou, vídeo e áudio presentes, duração 15,00 s |
| Projeto | Salvo e reaberto com o bloco de narração preservado |
| Tempo total do smoke test | 65,9 s, incluindo geração, UI, player, exportação e reabertura |

O tempo total do smoke test não é latência isolada do TTS. Para tempos de
inferência, RTF e RSS agregada, consulte
[`BENCHMARK_QWEN3_TTS_20261118.md`](BENCHMARK_QWEN3_TTS_20261118.md). O worker
foi encerrado ao fechar a janela; este teste não comprovou reprodução audível
por alto-falantes nem bloqueio da rede no firewall do sistema.

## Testes sintéticos relacionados

`tests.test_qwen3_tts_local` verifica que o pedido chega à API
`create_voice_clone_prompt`/`generate_voice_clone`, que o modelo aquece uma vez,
que o prompt em NPZ sem pickle sobrevive à recriação do worker, que arquivos de
outro motor são rejeitados e que a verificação de referência não altera a
gravação original. Esses testes não substituem a geração real acima.

## Configurações de execução

- Modelo: somente `Qwen/Qwen3-TTS-12Hz-0.6B-Base`.
- Inferência: PyTorch CPU em ambiente isolado; o worker permanece ativo e
  serializa pedidos até o fechamento do editor.
- Padrão de CPU: 4 threads intra-op e 1 inter-op; pode ser ajustado com
  `BEROFEL_QWEN3_CPU_THREADS` para benchmark/diagnóstico.
- Ensaio controlado do mesmo texto: 62,97 s com worker/perfil frios, 53,99 s
  com modelo e perfil aquecidos, 62,46 s após recarregar o modelo e ler o
  perfil persistido. Pico 5,73 GiB; três inferências sem hit de WAV. Uma
  repetição por cenário, portanto os tempos são observações da sessão.
- Precisão mantida no backend validado. INT8, INT4, backend nativo e streaming
  incremental ficam fora do caminho ativo até passarem por clonagem,
  desempenho e comparação de qualidade neste hardware.
- Modelos/caches antigos não são excluídos automaticamente. O usuário pode
  removê-los manualmente depois; nenhuma limpeza é feita pela atualização.

## Aditivo — operação experimental Qwen Turbo (mesma data)

Esta validação registrava o estado antes da etapa experimental do backend nativo. O status foi ampliado em [`QWEN3_TURBO_EXPERIMENT_20261119.md`](QWEN3_TURBO_EXPERIMENT_20261119.md): Q4_0 misto no modelo Base foi integrado como opção Turbo/Equilibrado e gerou offline pelo serviço canônico; a prévia incremental também foi exercitada na interface com sink de áudio simulado. O Oficial Python continua padrão e fallback. Q4 nativo usa x-vector (não ICL); qualidade subjetiva, escuta pelos alto-falantes e bloqueio de rede por firewall seguem sem prova.

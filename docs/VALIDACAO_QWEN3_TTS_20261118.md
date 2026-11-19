# Validação local do Qwen3-TTS — Windows — 18/11/2026

Ambiente: Windows x64, ambiente isolado `%LOCALAPPDATA%\BFS\qwen3_tts`, Qwen3-TTS 0.6B Base, PyTorch CPU. O modelo estava previamente instalado; downloads não foram iniciados nesta validação. Logs abaixo omitem caminhos privados, texto de referência e dados de áudio.

| Teste | Resultado observado |
|---|---|
| Importação do worker/modelo local e API Base | Passou. API oferece `create_voice_clone_prompt` e `generate_voice_clone`; carregamento usa CPU e `local_files_only=True`. |
| Síntese offline com referência sintética | Passou antes do limite de tokens: WAV 3,76 s/24 kHz, sinal RMS 2604,86; 42,5 s, pico de RAM agregado 5,55 GiB. Não valida identidade vocal. |
| Clonagem real backend com referência já configurada + transcrição | Passou após limitar `max_new_tokens`. WAV mono 24 kHz, 10,96 s, RMS 621,66, pico 4637; 72,2 s; pico agregado amostrado 5,76 GiB. Cache miss, inferência executada. |
| Regressão pré-correção com a mesma frase curta | Excedeu 1200 s devido ao default 2048 tokens. O processo foi interrompido; não houve WAV válido. O teste motivou a correção de orçamento de geração. |
| UI Qt real, cache de teste vazio, inferência Qwen nova | Passou offline; 49,2 s. WAV da fala gerada: 6,32 s/24 kHz. O texto e o caminho da referência foram omitidos do log. |
| UI Qt real com worker persistente | Passou com cache de áudio vazio: Qwen gerou no processo persistente, tocou no player Qt, inseriu na timeline, salvou/reabriu o projeto e exportou WAV e MP4 com áudio não silencioso. Fluxo: 70,6 s. |
| Benchmark real de CPU, português curto | Passou em 66,776 s para 10,32 s de áudio; RTF 6,47. Primeira solicitação, condicionamento de voz sem cache; modelo carregado uma vez. |
| Benchmark real de CPU, português longo | Passou em 297,598 s para 51,68 s de áudio; RTF 5,76. Mesmo PID do worker; `model_load_count=1`; cache do prompt de voz reutilizado. Pico agregado RSS amostrado: 6,41 GiB. |
| Comparação curta de threads | 4 threads: 62,530 s para 10,32 s (RTF 6,06, RSS 5,73 GiB); benchmark anterior de 8 threads: 66,776 s (RTF 6,47, RSS 6,41 GiB). Uma medição por perfil; padrão definido em 4 por ser o melhor observado, sem alegação de ótimo universal. |
| Player Qt da narração | Passou: abriu o WAV do bloco, iniciou reprodução, pausou e buscou. Saída física foi silenciada durante o smoke test. |
| Inserção e persistência da timeline | Passou: a UI criou o bloco de áudio, projeto foi salvo e reaberto com a fonte do bloco preservada. |
| Exportação WAV | Passou; WAV estéreo 48 kHz, decodificável e não silencioso. |
| Exportação MP4 | Passou; FFprobe identificou vídeo e áudio, duração 15,00 s; áudio AAC decodificado do MP4 apresentou sinal não silencioso. |
| Testes unitários focados | Passaram 14 testes de Qwen, perfis e UI (incluindo áudio referência obrigatório, remoção do seletor Pocket e perfis reutilizáveis). |

Comandos de validação executados no venv Windows:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& "$env:LOCALAPPDATA\BFS\venv\Scripts\python.exe" -m unittest `
  tests.test_qwen3_tts_local tests.test_voice_profiles `
  tests.test_actions_panel.ActionsUITests.test_custom_voice_panel_selects_qwen_local_clone_only `
  tests.test_actions_panel.ActionsUITests.test_new_custom_voice_uses_qwen_and_requires_reference_audio `
  tests.test_actions_panel.ActionsUITests.test_voice_profile_is_reusable_and_delete_preserves_source_audio

& "$env:LOCALAPPDATA\BFS\venv\Scripts\python.exe" scripts\validar_fluxo_qwen3_editor.py
```

O fluxo de interface usa a gravação já configurada na máquina, mas não salva essa gravação no checkout nem em logs. Para repetir, confirme que o painel Narração tem uma referência autorizada e a transcrição correta. O teste usa cache temporário para forçar inferência nova e remove o projeto/output sintéticos ao terminar.

Não foram comprovados: Qwen 1.7B, INT8/INT4, backend nativo, streaming incremental de áudio, escuta controlada/semelhança biométrica, reprodução audível pelos alto-falantes, teste com firewall bloqueando rede, nem interação física com mouse/microfone. A API Python instalada não tem método específico `generate_voice_clone_streaming`; `non_streaming_mode` não comprova streaming incremental. O benchmark é CPU neste Windows e não mede qualidade subjetiva. O MP4 e o WAV de timeline verificam codecs, fluxo e sinal, não uma sessão de montagem de produção real.


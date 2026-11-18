# Validação das IAs locais — BerofelStudio 0.10.0-alpha.1

Execução original: 16/11/2026; revalidações adicionais: 18/11/2026.  
Ambiente: Windows x64, Python 3.12.10, `%LOCALAPPDATA%\BFS\venv`; testes executados em modo offline depois da instalação dos modelos.

## Resultados locais

| Componente | Resultado | Evidência e limites |
|---|---|---|
| Silero VAD ONNX | PASSOU | `scripts\testar_batata_quente.py` executou o worker real sobre áudio sintético de 8 s. |
| Faster-Whisper Base | PASSOU | Mesmo pipeline carregou o modelo local em processo isolado. `scripts\testar_whisper_real.py` também transcreveu um WAV PCM16 de 2 s offline; esperavam-se zero palavras porque o áudio é um tom, não fala. |
| Cache do pipeline VAD/Whisper | PASSOU | Primeira análise: 3 etapas processadas; segunda análise da mesma fonte/opções: 3/3 resultados reutilizados. Cache do teste ficou no diretório temporário do próprio script. |
| Qwen3 1.7B GGUF + llama.cpp | PASSOU | Revalidação 18/11: com `llama-server`, seed 42 e 12 threads automáticas, 800 palavras passaram em 141,76 s e retornaram 27 propostas; a mesma amostra anteriormente deu 38 propostas a 8 threads e levou 147,88 s. O perfil automático passou com 100 palavras em 22,06 s. O cache de prefixo pode variar logits entre perfis, então saídas continuam sujeitas à revisão humana. Execução offline comprova inicialização/transporte/JSON e desempenho sintético, não precisão editorial em fala real. |
| Pocket TTS em português | PASSOU | Reexecução em 18/11: `scripts\testar_pocket.py --real --offline` gerou WAV real de 3,20 s com a voz de catálogo `rafael` e confirmou cache hit na segunda chamada. Cache e WAVs sintéticos ficaram em pasta temporária. Isso não valida clonagem de voz pessoal. |
| Dependências/modelos base | PASSOU | `scripts\verificar.py --strict --ai` confirmou Python x64, NumPy, Faster-Whisper, CTranslate2, PyAV, ONNX Runtime, FFmpeg, FFprobe, pip check e Whisper Base local. |
| Executáveis/modelos Qwen | PASSOU | `llama-cli.exe --version` respondeu `1.0.0-dev`; `Qwen3-1.7B-Q4_K_M.gguf` existe no caminho padrão do app. |
| Cache Qwen por perfil | PASSOU | Teste alternou contexto 8K→4K: as 3 etapas Whisper/VAD foram reaproveitadas e somente a etapa Qwen foi executada novamente. |
| Teste Pocket TTS no BAT | PASSOU | `TESTAR_POCKET_TTS.bat` chama o teste real com `--offline`, usa WAV temporário e valida também o cache. |

## O que esses testes não comprovam

- O tom sintético não mede acurácia de transcrição em português, qualidade das sugestões Qwen ou qualidade perceptiva da voz. Isso requer mídia falada escolhida pelo usuário e revisão humana.
- Não foi autorizada nem executada qualquer transmissão de mídia do usuário para serviços externos; estes componentes foram exercitados localmente.
- O teste completo da gravação histórica de 80 minutos, incluindo playback humano de ponta a ponta e revisão editorial, permanece pendente.

## Reproduzir no Windows

```powershell
$env:HF_HUB_OFFLINE = '1'
$py = Join-Path $env:LOCALAPPDATA 'BFS\venv\Scripts\python.exe'
& $py scripts\verificar.py --strict --ai
& $py scripts\testar_batata_quente.py
& $py scripts\testar_whisper_real.py
& $py scripts\testar_pocket.py --real --offline
# Após autorizar e baixar os pesos completos, teste a rota de clonagem sem áudio pessoal:
& $py scripts\testar_pocket.py --clone --offline
& $py scripts\testar_qwen_real.py --words 100
# Teste mais longo opcional: padrão de 800 palavras
& $py scripts\testar_qwen_real.py
```

O teste Qwen real usa o modelo e `llama-cli.exe` já instalados e pode levar mais tempo em CPU. O instalador Qwen verifica SHA-256 do modelo antes de habilitar o uso.

# Clip Engine — segmentos e confiança ASR

Data: 26/11/2026
Branch: `feat/clip-engine-cache-shortlist`

## Mudanças

- O adaptador aceita palavras persistidas e documentos com segmentos temporizados em `source_start`/`source_end`.
- Palavras dentro de segmentos só são usadas se cada uma tiver seus próprios timestamps de origem.
- Sem tempos individuais, o segmento é uma unidade indivisível. A UI identifica a precisão reduzida e não divide frase por caracteres ou estimativas.
- `probability`/`confidence` é preservado quando é finito e está no intervalo `[0,1]`. Uma penalidade limitada a 8% do score bruto é ponderada pela cobertura disponível e identificada como não calibrada.
- O Parakeet ativo retorna `probability=None`, então não há mudança de pontuação no fluxo normal.
- `CLIPPER_VERSION` passou de 11 para 12: o cache de ranking antigo é invalidado; transcrição e características acústicas permanecem reutilizáveis.

## Validação

- Clipador: 35 testes aprovados.
- Sinais acústicos e ranking: 26 testes aprovados.
- Adaptador Parakeet: 8 testes aprovados.
- Suíte completa: 689 testes executados, 6 ignorados, zero falhas, 70,502 s.
- `compileall` para os arquivos alterados e `git diff --check`: aprovados.
- Venv consultado: `onnx-asr 0.12.0`, ONNX Runtime `1.31.1`, NumPy `2.5.4`. O código usa `nemo-parakeet-tdt-0.6b-v3`, `quantization="int8"`, `CPUExecutionProvider` e `.with_timestamps()`.
- PySide6 não está instalado neste venv; esta rodada não inclui teste gráfico manual.

## Benchmark sintético

Fixture repetitiva de 80 min e 11.048 palavras, sem mídia, áudio, ASR ou Parakeet. Uma repetição por modo:

| Modo | Parede | CPU | Delta RSS amostrado | Candidatos | Parakeet | Áudio decodificado |
|---|---:|---:|---:|---:|---:|---:|
| Rápido | 4,534 s | 4,531 s | 17,969 MiB | 7 | 0 | 0 s |
| Equilibrado | 4,571 s | 4,578 s | 12,730 MiB | 7 | 0 | 0 s |
| Avançado | 4,695 s | 4,688 s | 7,773 MiB | 7 | 0 | 0 s |

É uma medição sintética, de uma repetição por célula; não estima p50/p95 nem comprova qualidade editorial, tempo ponta a ponta ou desempenho em um hardware específico.

## Limitações

- `D:\Edição CapCut\vídeos` não está disponível no ambiente desta execução; não foi medido vídeo real novo.
- Não há rótulos editoriais humanos, portanto precisão, recall, completude, erro de bordas e preferência seguem sem validação.
- Não foi feita sessão gráfica real nesta rodada.

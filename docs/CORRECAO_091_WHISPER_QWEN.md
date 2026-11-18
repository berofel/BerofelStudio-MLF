# Hotfix 0.9.1 — transcrição e instalação Qwen

## Problema 1 — Whisper / PyAV 19

- Erro observado: `whisper_batch: TypeError: open() got an unexpected keyword argument 'metadata_errors'`.
- Causa: Faster-Whisper 1.2.1 passa `metadata_errors` ao PyAV 19, que não aceita esse argumento.
- Correção: `ai_worker._whisper` recebe o WAV PCM16/16 kHz por `_read_wav` e passa um `numpy.ndarray` diretamente ao motor Faster-Whisper. A interface de transcrição suporta vetores NumPy e pula a decodificação do PyAV.
- A transcrição por lotes e o cache por trecho são mantidos. Não é preciso reinstalar o Whisper ou trocar PyAV.

## Problema 2 — instalação Qwen / llama.cpp

- Em 13/11/2026, `releases/latest` do llama.cpp apontava para v1.0.0 contendo apenas `nightly-tag.txt`, sem o ZIP de CPU Windows.
- Correção: o instalador consulta até 30 releases e escolhe a primeira com ZIP oficial `bin-win-cpu-x64`; se isso falhar, consulta o release oficial `v0.9.0`, que disponibiliza um binário CPU Windows.
- O SHA256 do executável publicado pela release é conferido quando disponibilizado; o modelo GGUF mantém a verificação de hash fixo.
- Se já houver modelos instalados, serão reutilizados. Não é necessário reinstalar todo o editor.

## Instalação / teste

1. Feche o BerofelStudio e faça cópia dos seus projetos.
2. Extraia a versão completa 0.9.1 em pasta NOVA; o ambiente de IA permanece em `%LOCALAPPDATA%\BFS`.
3. Execute `TESTAR_HOTFIX_091.bat` (testes rápidos).
4. Execute `TESTAR_WHISPER_REAL_091.bat` (teste do modelo local usando arquivo sintético).
5. Execute `INSTALAR_QWEN_OPCIONAL.bat` para baixar o llama.cpp e o modelo, se ainda não os tiver.
6. Inicie `ABRIR_BEROFELSTUDIO.bat` e repita a transcrição da gravação. Cache das etapas válidas será reaproveitado.

O Qwen ainda requer internet no primeiro download; a inferência no editor é offline.
A execução final no Windows não pôde ser validada neste ambiente Linux.

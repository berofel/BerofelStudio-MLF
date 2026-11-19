# Decisões arquiteturais

Registros de decisões confirmadas pelo código atual. Uma decisão não substitui os testes descritos em `VALIDACAO_010_ALPHA1_LOCAL.md`.

## ADR-001 — Um único modelo de sequência e conversão de tempo

- **Estado:** Aceita para a linha 0.10.0-alpha.1.
- **Decisão:** `core.project.Project` e seus `Clip` são a sequência canônica. Operações de corte/trim/speed são não destrutivas e registradas como estado do projeto. Tempos Whisper são relativos à fonte; conversões para a timeline usam `timeline_start`, `start` e `speed` no código do editor.
- **Motivo:** cortes de IA, edição manual, legendas e render devem atuar sobre a mesma sequência e manter os originais intactos.
- **Consequências:** Qwen retorna IDs contíguos de palavra; `qwen_removal_interval` valida e associa os timestamps existentes do Whisper; aprovação é uma ação separada.
- **Evidência:** `core/project.py`, `services/ai_pipeline.py`, `services/batch_editing.py`, `services/subtitles.py`; testes `test_ai_pipeline.py`, `test_batch_editing_09.py`, `test_modular_actions.py`.
- **Limite:** ainda falta playback humano de mídia longa real e revisão editorial do Qwen em fala real.

## ADR-002 — Grafo de composição compartilhado por prévia e exportação

- **Estado:** Aceita para a linha 0.10.0-alpha.1.
- **Decisão:** `services/export_multitrack.py::_graph_and_inputs` permanece como fonte do filtergraph. `services/preview_pipeline.py` prepara janelas locais e chama esse grafo; `services/export_multitrack.py::export_project` usa o mesmo grafo para o arquivo final.
- **Motivo:** geometria, camadas, efeitos e mix não devem divergir por manter motores independentes.
- **Consequências:** preview pode reduzir resolução e trabalhar em janelas limitadas, mas conserva a composição. A opção MP4 de reserva usa `export_project`, não outro compositor.
- **Evidência:** imports/calls em `services/preview_pipeline.py`, `services/export_multitrack.py`, `ui/live_preview.py` e `ui/window.py`; testes de preview/export em `test_preview_092_many_cuts.py`.
- **Limite:** o teste de 80 minutos usa sequência e arquivos sintéticos; a gravação real do usuário ainda é necessária para validar sincronismo perceptivo.

## ADR-003 — IA textual não é dona do relógio da timeline

- **Estado:** Aceita para a linha 0.10.0-alpha.1.
- **Decisão:** Faster-Whisper é a fonte dos tempos de palavra. Qwen recebe apenas `{id,text}` e retorna grupos de IDs a remover. O editor calcula intervalos com as palavras Whisper, margens, validação de continuidade e proteções de conteúdo.
- **Motivo:** evitar timestamps inventados pelo modelo e reduzir prompt a texto, com inferência local em lotes/cache.
- **Consequências:** o worker Qwen não recebe mídia nem timestamps; os cortes continuam sugestões desmarcadas até aprovação. O modelo pode analisar contexto com sobreposição sem reprocessar áudio.
- **Evidência:** `services/ai_pipeline.py::qwen_removal_interval`, `services/ai_worker.py::_qwen_prompt`, `docs/FLUXO_QWEN_TEXTO_E_TIMESTAMPS.md`.
- **Limite:** resultado sintético demonstra transporte/JSON e não prova precisão semântica em vídeos reais.

## ADR-004 — Motor único Qwen3-TTS Base local

- **Estado:** Aceita para a diretriz 0.10.0-alpha.1.
- **Decisão:** somente `Qwen/Qwen3-TTS-12Hz-0.6B-Base` gera e clona voz. A implementação oficial Python roda em CPU em um worker persistente por sessão. Perfis rápidos salvam a gravação privada e a transcrição; o condicionamento `create_voice_clone_prompt` usa cache versionado NPZ sem pickle, validado por fingerprint do modelo, áudio e transcrição. Pocket TTS e outros tamanhos/modelos não fazem parte da instalação nem da rota de geração.
- **Motivo:** um único contrato de modelo atende perfis preparados e clonagem detalhada, elimina seleção de backends incompatíveis e permite funcionamento local offline após a preparação.
- **Consequências:** o modelo carrega na primeira preparação/geração e permanece no worker enquanto o editor está aberto; a chamada seguinte reutiliza o prompt persistido. Perfis e áudios originais continuam no computador do usuário e nunca são enviados.
- **Evidência:** `services/narration_service.py`, `services/qwen3_tts_local.py`, `services/qwen3_tts_worker.py`, `services/voice_profiles.py`; benchmarks Windows em `docs/BENCHMARK_QWEN3_TTS_20261118.md` e fluxo Qt em `scripts/validar_fluxo_qwen3_editor.py`.
- **Limites:** INT8/INT4, backend nativo e geração incremental real não foram qualificados. A API oficial documenta que `non_streaming_mode=False` não representa streaming de áudio efetivo. A validação atual mede CPU/RAM e fluxo offline com modelo já instalado; não prova reprodução pelos alto-falantes nem firewall de rede bloqueada.

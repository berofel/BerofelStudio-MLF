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

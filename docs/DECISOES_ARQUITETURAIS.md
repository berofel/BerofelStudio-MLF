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

## ADR-004 — Modelo único Qwen3-TTS Base local com backend experimental opt-in

- **Estado:** Aceita para a diretriz 0.10.0-alpha.1.
- **Decisão:** somente `Qwen/Qwen3-TTS-12Hz-0.6B-Base` gera e clona voz. O backend oficial Python float32 roda em CPU em um worker persistente por sessão e permanece padrão/fallback. Para narração rápida, há um adaptador nativo Q4_0 misto opcional, não incluído na instalação padrão, com perfis experimentais Turbo (6 threads) e Equilibrado (8 threads); ambos usam x-vector cacheado do mesmo modelo Base. Perfis oficiais guardam referência privada e transcrição; `create_voice_clone_prompt` usa cache versionado NPZ sem pickle, validado por fingerprint do modelo, áudio e transcrição. Pocket TTS e outros tamanhos/modelos não fazem parte da rota ativa.
- **Motivo:** um único contrato de modelo atende perfis preparados e clonagem detalhada, elimina seleção de backends incompatíveis e permite funcionamento local offline após a preparação.
- **Consequências:** cada backend carrega o modelo ao ser selecionado e o mantém no processo durante seu uso; o alternador de perfis encerra o processo nativo por EOF para evitar espera inútil. O oficial reutiliza o prompt de clonagem ICL; o nativo reutiliza o x-vector. Perfis e áudios originais continuam no computador do usuário e nunca são enviados.
- **Evidência:** `services/narration_service.py`, `services/qwen3_tts_local.py`, `services/qwen3_tts_worker.py`, `services/qwen3_native_tts.py`, `services/voice_profiles.py`; benchmarks Windows em `docs/BENCHMARK_QWEN3_TTS_20261118.md` e `docs/QWEN3_TURBO_EXPERIMENT_20261119.md`; fluxo Qt em `scripts/validar_fluxo_qwen3_editor.py`; geração real offline pelos dois perfis nativos e oficial.
- **Limites:** Q4 Turbo/Equilibrado são experimentais e a qualidade ainda depende de comparação auditiva. O backend nativo validado usa x-vector sem ICL; clonagem detalhada segue no oficial. A quantização dinâmica INT8 do PyTorch foi medida, mas não é ativada; INT4 dinâmico falhou na API instalada. Streaming incremental está habilitado somente na prévia do nativo. Os testes não comprovam reprodução audível por alto-falantes nem firewall de rede bloqueada.

## ADR-005 — Roteiro multivozes como dados do projeto e síntese por lotes

- **Estado:** Implementado parcialmente na branch `feat/qwen3-multivoice-narration`.
- **Decisão:** Berofel Script V1 é interpretado deterministicamente em Python, cada fala mantém ID independente do número, e seus WAVs/estados ficam em JSON versionado no projeto com checkpoint incremental. A fila é serial e agrupada pelo perfil salvo; os clips são criados na camada do roteiro na ordem numérica. O exportador WAV existente renderiza o roteiro completo.
- **Motivo:** corrigir uma frase não deve invalidar outras; arquivos e dados precisam sobreviver a cancelamento, fechamento e reabertura do projeto.
- **Consequências:** cache separado por texto, referência, backend, threads e identidade dos arquivos de runtime/modelo; arquivos existentes são preservados após regeneração ou remoção de um bloco.
- **Limite técnico:** Pure C fixa o x-vector no servidor durante o startup (`--load-voice`) e não aceita embedding por requisição. A fila reutiliza o processo dentro de cada lote, mas troca de personagem reinicia o servidor/modelo. “Uma carga de modelo para todo o roteiro” continua bloqueado pelo contrato do runtime instalado; múltiplas instâncias simultâneas violariam a meta de RAM do PC de referência.
- **Evidência:** `services/multivoice_narration.py`, `ui/multivoice_panel.py`, `ui/window.py`, `core/project.py`, `docs/NARRACAO_MULTIVOZES.md`. O documento registra uma execução histórica de 100 falas com as V IDs compartilhando a única referência local; isso não mede troca de identidade vocal. Nesta revisão, o smoke Qt reproduzido executou duas falas iguais (uma inferência e um cache hit) nos backends Pure C e Native Q4 e verificou timeline, round-trip e WAV/MP4. Há um teste de orquestração sintético 70/20/10 que gera 100 WAVs e regenera apenas a fala 047. O validador offline agora aceita `--profile-v3` para executar o caso Qwen real de 100 falas, mas esse caso ainda não foi executado porque só há uma gravação autorizada distinta no computador.

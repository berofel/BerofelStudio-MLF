# Auditoria inicial do workspace — 0.10.0-alpha.1

Data: 18/11/2026. Esta auditoria registra o estado encontrado no workspace Windows; não declara release estável.

## Proveniência e acesso

| Item | Evidência | Estado |
|---|---|---|
| Código aberto pelo launcher da raiz | `ABRIR_BEROFELSTUDIO.bat --verificar` selecionou `BerofelStudio\BerofelStudio 1`, carregou `berofel.__version__ = 0.10.0-alpha.1` e passou no diagnóstico. | Confirmado |
| Pacote-base solicitado | Busca em `C:\Users\Berofel\Desktop` não encontrou `BerofelStudio_Studio_0_9_2_Previa_Cortes_Windows.zip`. | Ausente; a proveniência exata da árvore atual em relação ao ZIP não pode ser conferida. Não substituir a árvore atual por uma versão mais antiga. |
| Código legado | `C:\Users\Berofel\Desktop\BerofelStudio_codigo_base_alpha\Berofel-Studio Python.zip` está presente. Há referências visuais extraídas em `legacy_ui_reference\interface_3_1.png` e `interface_3_2.png`. | Disponível como referência |
| Planejamento | `BerofelStudio_Plano_Mestre_Codex\AGENTS.md`, plano mestre, checklist e auditoria de migração foram lidos. | Disponível fora da raiz do app |
| Contrato persistente | `AGENTS.md` foi copiado para esta raiz e seus caminhos foram ajustados para o pacote de planejamento/ZIP legado no diretório pai. | Presente no código atual |
| Configuração do pacote Python | `requirements.txt`, `requirements-core.txt`, `requirements-ai.txt` e `requirements-pocket-tts.txt` existem; `pyproject.toml` não existe. | A instalação usa BAT/venv; não há configuração pyproject para lint/build |
| Repositório local | Git inicializado na pasta do app, branch `codex/consolidacao-berofelstudio-010`, baseline `a7716eb7332885977bb5c9c66bb9c466c0c42750`, árvore limpa; `.gitignore` protege projetos, mídia, credenciais, modelos e runtime. | Histórico local criado como snapshot de `0.10.0-alpha.1`; sem histórico anterior para comparar |
| Repositório remoto oficial | Consulta pelo conector GitHub: `berofel/BerofelStudio-MLF`; `main` contém apenas o commit inicial `3aa2841f0560c4e389186af6f9e8bca81c511e05` com README placeholder, sem código do editor; permissão `pull=true`, `push=false`. `git fetch origin main` falhou por bloqueio de conexão a `github.com:443`. | Conteúdo-fonte não estava no remoto; a branch local ainda não compartilha o ancestral Git do remoto; push/PR indisponíveis |

## Arquitetura observada

- A sequência editável vive em `berofel/core/project.py` (`Project`, `Clip`, tracks e operações reversíveis).
- A timeline Qt é `TimelineView` em `berofel/ui/timeline.py`; não foi encontrado um segundo modelo canônico de sequência na árvore `berofel/`.
- O preview ao vivo usa `berofel/services/preview_pipeline.py::prepare_commands`, que chama `_graph_and_inputs` de `export_multitrack.py`. `LivePreview` lê os pipes FFmpeg e a UI apresenta quadros/áudio.
- Exportação também usa `_graph_and_inputs`. A opção de prévia MP4 de reserva chama `export_project`, portanto reutiliza o grafo de composição e não introduz um segundo compositor.
- A fila IA é sequencial em `services/batch_editing.py`; `StageRunner` executa workers isolados e o monitor `Batata Quente` recebe progresso. Revisão é separada da aplicação das sugestões.
- O Whisper mantém tempos de palavra; o Qwen recebe IDs/texto. A conversão de IDs em cortes ocorre no pipeline e a aplicação não destrutiva ocorre no modelo do projeto.

## Estado de validação e gaps

- Validação local registrada em `VALIDACAO_010_ALPHA1_LOCAL.md`: 245 testes automatizados, `compileall` e fluxo local offline Pocket TTS→DSP→WAV/MP4 passaram no venv Windows; o probe unitário de ativação passou, enquanto a autorização gated real segue não executada.
- `test_preview_092_many_cuts.py` cobre MP4 real sintético com 300 cortes, pipes/comandos com 500 cortes e preparação/decodificação amostral de sequência sintética de 80 minutos e 800 cortes.
- Não foi validada a gravação real de 80 minutos do usuário, a qualidade editorial do Qwen em fala real, nem reprodução humana longa com áudio durante a sequência inteira.
- O checklist Windows ainda contém portões `não executados` para mídia do usuário, DPI global/per-monitor, instalação limpa com downloads e revisão perceptiva.
- O pacote 0.9.2 ausente impede uma comparação forense arquivo a arquivo com a base inicial pedida. O editor local continua sendo a fonte de trabalho porque já contém o código atual e não deve ser rebaixado.

## Próxima evidência necessária

Para auditar a origem da versão inicial, disponibilize o arquivo em:

`C:\Users\Berofel\Desktop\BerofelStudio_codigo_base_alpha\BerofelStudio_Studio_0_9_2_Previa_Cortes_Windows.zip`

O arquivo não é necessário para continuar corrigindo a árvore atual; é necessário para confirmar a importação contra a base específica e preencher a comparação histórica.

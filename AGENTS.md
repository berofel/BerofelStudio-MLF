# BerofelStudio — Contrato persistente de implementação (Codex)

## Missão

Editor de vídeo Windows/PySide6 de qualidade e desempenho comprovados, com timeline multitrilha, edição não destrutiva e IA modular local. **Código e testes são a fonte de verdade; documentos antigos são referências, não evidências de execução.**

## Leia primeiro

- `..\..\BerofelStudio_Plano_Mestre_Codex\PLANO_MESTRE_BEROFELSTUDIO_CODEX.md`
- `..\..\BerofelStudio_Plano_Mestre_Codex\AUDITORIA_LEGADO_E_MIGRACAO.md`
- `..\..\BerofelStudio_Plano_Mestre_Codex\CHECKLIST_VALIDACAO_WINDOWS.md`
- `docs/DECISOES_ARQUITETURAIS.md` e `docs/AUDITORIA_INICIAL.md`, quando criados.

## Restrições inegociáveis

1. Exatamente uma Timeline/Sequence canônica, um motor de tempo e uma composição Preview↔Export. Proibido criar subsistemas paralelos para contornar bugs.
2. UI: biblioteca esquerda, preview centro, inspector direita, timeline embaixo, barra de jobs fora das áreas existentes. Não sobrepor, não recortar controles, não fazer timeline circular.
3. Seleção de ferramenta IA independente e por alcance, checkbox de edição completa e aprovação de 300+ cortes por um clique. Não executar IA ao importar mídia.
4. IAs pesadas sob agendamento Batata Quente, processos isolados com cache e cancelamento. **A UI não espera por lease pesado**.
5. Não fixar 4GB: política adaptativa e segura segundo hardware disponível. Modelos leves opcionais para PC modesto; forte pode usar hardware máximo.
6. Corte não destrutivo, informações de transcrição relativas à origem, conversão determinística dos tempos. Qwen não inventa timestamps nem comandos de FFmpeg.
7. IA nunca apaga mídia/fala fora de escopo; corte de silêncio com safe padding e revisão. Correções manuais e legendas editadas têm prioridade.
8. Não alterar arquivos fonte do usuário, não apagar cache/modelos/saves em atualização. Migração com backup e versão.
9. Tratar compatibilidade Windows: long path/Win206, filtro FFmpeg, PyAV, instalação Qwen, Unicode, logs e subprocessos sem shell arbitrário.
10. Testes em cada PR: unitários, integração e FFmpeg; GUI real em Windows para recursos visuais. Sempre diferenciar `passou`, `falhou`, `não executado`.

## Processo do agente

- Descobrir estado atual → registrar bug/reprodução → implementar mudança pequena → testar → medir → revisar → commit → descrever resultado.
- Mudanças de arquitetura exigem ADR; migrações exigem testes de reopen e compatibilidade.
- Preferir reaproveitar código puro de `..\..\Berofel-Studio Python.zip` com adaptadores; jamais importar `window.py` monolítica sem desmontar suas dependências.
- Usar `git diff`, `pytest`, `ruff`, `python -m compileall`, FFprobe e diagnósticos de ambiente; evitar afirmar sucessos sem execução.
- Release deve ter checksum, changelog, comando de instalação/teste e evidências de MP4 válido com áudio.
- Não instalar software global/baixar modelos gigantes/aceitar licença sem confirmação do proprietário. Não enviar vídeos, áudio ou dados privados para a rede sem consentimento explícito.

## Versionamento e sincronização GitHub

- Toda alteração validada deve ser registrada em commits locais pequenos e descritivos; não deixar trabalho concluído sem checkpoint versionado.
- Antes de publicar, confirmar `git status`, branch, `origin`, `git fetch`/estado remoto, testes da mudança e ausência de credenciais, mídias pessoais, caches, modelos ou binários pesados no índice e no histórico a enviar.
- Sincronizar com o GitHub quando o usuário tiver autorizado a publicação e a conta conectada tiver permissão efetiva de escrita. Verificar a permissão e a rede separadamente; uma falha não autoriza contornar controles.
- Nunca usar `push --force`, sobrescrever `main`, reescrever histórico já compartilhado ou anunciar publicação sem confirmar o commit remoto. Se o acesso estiver bloqueado, preservar commits locais, informar a causa comprovada e preparar bundle/patch quando útil.
- Para releases, seguir a versão declarada em `berofel/__init__.py`, atualizar changelog/documentação, validar instalador/artefatos e então criar tag de versão. Não publicar tag ou pacote sem testes correspondentes.

## Referência de sucesso

A gravação histórica de 80 min processada em ~7 min e reduzida para ~20 min é **benchmark informado pelo usuário** em condições específicas, não garantia universal. A qualidade do conteúdo preservado é mais importante que taxa de redução.

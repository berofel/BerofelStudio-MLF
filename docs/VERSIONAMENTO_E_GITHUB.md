# Versionamento e sincronização com GitHub

Repositório oficial: <https://github.com/berofel/BerofelStudio-MLF>

## Estado desta preparação

- Raiz Git: `BerofelStudio 1`.
- Branch de trabalho: `feat/automatic-cleanup-modules`.
- Versão declarada pelo aplicativo: `0.10.0-alpha.1` (`berofel/__init__.py`).
- O remoto `origin` aponta para o repositório oficial.
- Na auditoria de 2026-11-23, o remoto tinha somente o commit inicial e um README de 19 bytes; seu histórico era independente do histórico local.
- O histórico local foi integrado ao histórico inicial remoto sem force push. A branch `feat/automatic-cleanup-modules` foi publicada e verificada no remoto.
- O pull request [#1](https://github.com/berofel/BerofelStudio-MLF/pull/1) foi aberto para `main` e permanece aguardando revisão; não foi mesclado.
- `gh` não está instalado. O conector GitHub indicava acesso somente de leitura, mas o credential helper Git configurado permitiu testar e efetuar o push autenticado pela linha de comando. A conectividade HTTPS foi restabelecida durante a sessão. Nenhum token foi exibido ou salvo no repositório.

## Preparar ambiente e verificar acesso

No PowerShell, na raiz do repositório:

```powershell
git --version
gh --version
gh auth status
git status --short --branch
git remote -v
git fetch origin
git branch -vv
```

`gh auth status` confirma a sessão CLI, mas não prova permissão de escrita no repositório. Confirme também que a conta conectada tem acesso de escrita (por exemplo, na página **Settings → Collaborators and teams** ou com uma operação de push autorizada). Diagnostique rede e autorização separadamente. Nunca exponha tokens e não desative TLS.

## Publicar uma alteração validada

1. Comece com `git status`; preserve mudanças que não pertencem à tarefa.
2. Confira o diff e os arquivos staged. Não inclua mídias pessoais, projetos de usuário, credenciais, ambientes virtuais, caches, modelos ou binários pesados.
3. Execute os testes pertinentes e registre falhas/limitações.
4. Faça commits locais pequenos e descritivos na branch de trabalho.
5. Atualize `origin` com `git fetch origin`. Integre mudanças remotas explicitamente e resolva conflitos preservando ambos os trabalhos. Não reescreva histórico compartilhado.
6. Publique uma branch de funcionalidade com `git push -u origin <branch>`. Não force push e não envie diretamente para `main` sem autorização específica.
7. Confirme o resultado com `git ls-remote --heads origin <branch>` ou consultando o commit da branch no GitHub. Um commit local não comprova publicação.
8. Abra um Pull Request para `main` e informe a URL somente depois de confirmar que foi criado.

Se a escrita remota estiver indisponível, mantenha os commits locais, registre a causa exata e compartilhe um bundle/patch por canal autorizado. Não contorne controles de acesso.

## Releases

Use a versão definida em `berofel/__init__.py` como fonte de verdade. Antes de publicar uma release, atualize o changelog e a documentação, rode os testes e valide os artefatos instaláveis. `vX.Y.Z` publica estável; `vX.Y.Z-alpha.N`, `-beta.N` e `-rc.N` publicam pré-release. A tag precisa apontar para um commit validado e corresponder exatamente à versão do código.

O workflow Windows roda testes em PRs para `main`, pushes em `main`, `feat/*` e `fix/*`, e tags `v*`. Push em branch gera somente artefato de CI; somente a tag publica uma Release. Cada Release inclui EXE versionado, `BerofelStudio-Setup-x64.exe` e SHA-256 dos dois. O instalador compara a própria versão com a mais nova publicada em seu canal e encaminha para o setup novo depois de validar o checksum. O canal estável ignora pré-releases; builds alpha acompanham alphas/betas/RCs.

Link permanente para distribuição estável: <https://github.com/berofel/BerofelStudio-MLF/releases/latest/download/BerofelStudio-Setup-x64.exe>. A API pública de Releases fornece metadados/assets do updater. O instalador segue online e não é autossuficiente/offline; checksum não substitui assinatura Authenticode para distribuição profissional.

## Política de arquivos

`.gitignore` exclui artefatos locais, dados de usuário, modelos, ambientes, caches, credenciais e binários. Scripts de instalação, código-fonte e manifestos de dependências permanecem versionáveis. Antes de publicar, revise também o histórico alcançado pela branch: ignorar um arquivo hoje não o remove de commits antigos. Nunca use `git filter-branch` ou force push como limpeza rotineira.

# Versionamento, Releases e atualizações do BerofelStudio

Repositório: <https://github.com/berofel/BerofelStudio-MLF>

## Estado publicado em 25/11/2026

- Versão: `0.10.0-alpha.3`, declarada em `berofel/__init__.py`.
- Release de teste: <https://github.com/berofel/BerofelStudio-MLF/releases/tag/v0.10.0-alpha.3>.
- Download direto para testar esta pré-release: <https://github.com/berofel/BerofelStudio-MLF/releases/download/v0.10.0-alpha.3/BerofelStudio-0.10.0-alpha.3-Setup-x64.exe>.
- SHA-256 publicado junto do instalador. O digest oficial do EXE nesta Release é `fb68d7770641e7da22280bf42828eb36b86536600b3b5177ead6d4bf11ff341b`.
- O workflow da tag passou pela suíte Windows, compilação NSIS e instalação limpa core-only: diagnóstico do editor, janela Qt, atalho, preservação de dados do usuário e desinstalação.
- O instalador core passou no runner limpo; a instalação dos modelos opcionais Parakeet/Qwen ainda exige teste em máquina de usuário com internet, espaço e hardware próprios.
- `main` e `feat/windows-self-updating-installer` estavam publicados no commit `ccbf29d931b42496bb74d72e560605c7ba2f3ffe` quando a Release foi criada.

## Como a atualização do instalador funciona

O setup consulta as Releases públicas antes de instalar. Um setup alpha acompanha a Release mais nova do canal de pré-lançamento; um setup estável ignora alphas/betas/RCs. Se encontrar uma versão SemVer mais nova com o EXE e manifesto SHA-256 esperados, baixa ambos, valida origem, tamanho e hash, e inicia o setup novo antes de alterar a instalação existente. O setup em uso não instala código arbitrário de branches nem executa conteúdo recebido da API.

Commits enviados para o GitHub atualizam o código-fonte e acionam CI. Eles **não** substituem automaticamente o instalador publicado: uma tag correspondente à versão aciona novamente testes, build e instalação limpa; somente depois do smoke test o workflow cria a Release. Isso impede que uma instalação receba um commit não versionado ou que ainda falhou na validação.

O canal de teste alpha está disponível pelo link versionado acima. Para um site futuro, prefira apontar para a página de Releases e para o asset estável `BerofelStudio-Setup-x64.exe` apenas depois de haver uma Release estável. O link permanente estável é <https://github.com/berofel/BerofelStudio-MLF/releases/latest/download/BerofelStudio-Setup-x64.exe>; o GitHub não trata pré-releases como `latest` estável.

## Publicar uma versão futura

Na raiz do repositório:

```powershell
git status --short --branch
git fetch origin
# Atualize berofel/__init__.py e CHANGELOG.md; rode os testes pertinentes.
git add <arquivos-validados>
git commit -m "fix: resumo da alteração"
git push origin <branch-de-trabalho>
```

Depois da revisão e integração em `main`, valide que a versão do código, changelog e documentação correspondem. Use `vX.Y.Z` para uma versão estável ou `vX.Y.Z-alpha.N`, `-beta.N` ou `-rc.N` para pré-release. Não reutilize tags existentes.

```powershell
git checkout main
git pull --ff-only origin main
git tag -a vX.Y.Z <commit-validado> -m "BerofelStudio X.Y.Z"
git push origin vX.Y.Z
```

O workflow verifica que a tag corresponde a `berofel.__version__`, roda a suíte no Windows, compila o instalador e o instala em runner limpo. A publicação automática da Release só roda se todas as etapas anteriores passarem e se o commit da tag estiver em `main`. A Release recebe o EXE versionado, o alias `BerofelStudio-Setup-x64.exe` e os dois arquivos `.sha256`. Não usar force push nem mover uma tag já publicada.

## Para sincronizar continuamente o código

Após validar e criar cada commit, publique a branch autorizada e confira o hash remoto:

```powershell
git push origin <branch>
git ls-remote --heads origin <branch>
```

`git push` atualiza o código no GitHub. A Release/instalador só muda após tag validada. O próprio instalador consulta a Release no momento da instalação, mas não publica commits nem atualiza a si mesmo a partir do código-fonte.

### Diagnóstico definitivo de rede, autenticação e proteções (26/11/2026)

Validação feita no checkout Windows durante a investigação:

- `origin` está correto: `https://github.com/berofel/BerofelStudio-MLF.git`. A CLI local autenticou `berofel` com `repo` e `workflow`; a API confirmou `admin: true` e `push: true`. Não há ajuste de acesso do proprietário necessário para publicação pela CLI local.
- Dentro do sandbox, a consulta HTTPS à API falhou com `connectex: Foi feita uma tentativa de acesso a um soquete de uma maneira que é proibida pelas permissões de acesso`. O `gh auth status` naquele contexto também imprimiu `The token in default is invalid`, mas a causa observada foi a conexão bloqueada. Com rede aprovada, a mesma CLI validou a sessão e a API. Portanto, **não fazer logout, apagar ou substituir credenciais em resposta isolada a esse erro de socket**; executar operações GitHub em um contexto com rede aprovado e verificar `gh auth status` novamente.
- O Git usa `gh auth git-credential`, configurado pelo GitHub CLI. Um push real da branch sincronizada retornou `Everything up-to-date`, e `git ls-remote` confirmou `35d91cf151b58c5cc582927ef17b9359854b4f9c` em `feat/clip-engine-cache-shortlist`. Um push de commit novo já havia sido publicado e confirmado em sessão anterior. `--dry-run` não publica refs nem comprova que uma alteração foi aceita; a confirmação é sempre o SHA remoto após o push real de um commit validado.
- O GitHub Connector integrado ao Codex é uma identidade separada: os metadados retornaram `push: false`, e consultar permissões de colaborador retornou `403 Resource not accessible by integration`. Isso **não** limita a conta `berofel` usada pelo `gh` local. Para fazer push/abrir PR por esse Connector, o proprietário deve autorizar a instalação para este repositório com `Contents: read/write` e `Pull requests: read/write`; para editar `.github/workflows/*`, também `Workflows: write`. Se o app não solicitar essas permissões, somente o mantenedor do app poderá adicioná-las. A CLI local continua sendo a rota já validada.
- `main` exige PR, atualização estrita em relação à base e estes checks: `Windows 11 / Python 3.12 tests`, `build` e `Clean Windows install / launch / uninstall`. A regra também se aplica aos administradores; force-push e exclusão estão bloqueados. A branch de trabalho `feat/clip-engine-cache-shortlist` não tem proteção própria. Nenhum ruleset adicional foi encontrado. Assim, enviar direto a `main` é intencionalmente incompatível com a política; publique a branch e abra PR.
- Actions estão habilitadas com ações permitidas; a permissão padrão de `GITHUB_TOKEN` é `read` e não pode aprovar PRs. O workflow do projeto declara `contents: read` para CI/build e `contents: write` apenas no job de publicação de Release, o que é suficiente: o workflow não cria PR. Não ampliar permissões globais do Actions.
- O run do commit `35d91cf151b58c5cc582927ef17b9359854b4f9c` passou nos três checks obrigatórios ([run 45798866912](https://github.com/berofel/BerofelStudio-MLF/actions/runs/45798866912)). Runs anteriores falharam em testes: seletores de motor multivozes ausentes (`Escolha manualmente o motor de narração...`) e testes de seleção de janela acústica incompatíveis com a nova assinatura/subprocesso. Foram seguidos por correções e o run mais recente passou; testes não foram desabilitados.

Links de configuração relevantes para o proprietário:

- [Acesso do repositório](https://github.com/berofel/BerofelStudio-MLF/settings/access)
- [Instalações de aplicativos GitHub](https://github.com/settings/installations)
- [Regras de branches](https://github.com/berofel/BerofelStudio-MLF/settings/branches)
- [Rulesets](https://github.com/berofel/BerofelStudio-MLF/settings/rules)
- [Permissões do GitHub Actions](https://github.com/berofel/BerofelStudio-MLF/settings/actions)

## Segurança e limites de distribuição

- O EXE é um bootstrapper online, não um pacote offline completo: baixa Python, dependências, FFmpeg e os motores selecionados.
- Os pesos do Qwen/Parakeet não são embutidos no Git ou no EXE; são arquivos grandes com licenças e requisitos próprios. Após download, os motores locais funcionam sem API externa conforme cada módulo.
- O smoke automatizado usa `/COREONLY`; ele não baixa vários gigabytes de modelos nem valida inferência TTS/ASR em cada Release.
- O instalador ainda não tem assinatura Authenticode própria. SHA-256 detecta corrupção, mas não substitui assinatura de editor verificado nem remove o aviso SmartScreen.
- Antes de vender amplamente, revisar licenças de dependências/modelos, instalar em PCs de teste distintos, validar downloads opcionais e obter assinatura de código.
- Não incluir gravações, projetos, perfis vocais, tokens, ambientes virtuais, caches ou pesos de IA nos commits ou assets.

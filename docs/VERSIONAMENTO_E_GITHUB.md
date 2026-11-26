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

## Diagnóstico de acesso e fluxo permanente (26/11/2026)

Estado revalidado no checkout Windows em 26/11/2026:

- Raiz correta: `BerofelStudio\BerofelStudio 1`. `origin` aponta para `https://github.com/berofel/BerofelStudio-MLF.git`. O branch `feat/clip-engine-cache-shortlist` estava limpo e no mesmo commit remoto `28bc525c4c768d0211409ffade7833f32e4fa00a`; não havia commits locais pendentes nem conflito de avanço.
- Git `2.56.0.windows.4` e GitHub CLI `2.105.0` estão instalados. Dentro do sandbox, `gh auth status` mostrou `The token in default is invalid.` junto de erro de conexão HTTPS. Repetido fora do sandbox, confirmou `Logged in to github.com account berofel (keyring)`, protocolo HTTPS e escopos `gist`, `read:org`, `repo`, `workflow`; `gh api user --jq .login` retornou `berofel`. Portanto, a primeira mensagem de token inválido foi consequência do teste sem rede, não de credencial revogada.
- O helper GitHub por usuário é `gh auth git-credential`; `GIT_TRACE` confirmou que o Git o chama para `get` e `store`. O Git Credential Manager `2.9.1` existe, mas não está no caminho efetivo para `github.com` devido ao helper específico do `gh`. Não há motivo para trocar o helper que acabou de concluir um push real. Nenhum token foi lido ou gravado em texto.
- No sandbox, `git ls-remote` falha exatamente com `Failed to connect to github.com:443 ... connectex: Foi feita uma tentativa de acesso a um soquete de uma maneira que é proibida pelas permissões de acesso`. Fora do sandbox, o push real do commit `97d423d4cfb1457307b4777610a61cc7d9d67217` concluiu sem erro (`28bc525..97d423d HEAD -> feat/clip-engine-cache-shortlist`); `git ls-remote --heads` confirmou o mesmo SHA no remoto. A causa raiz das falhas intermitentes é o bloqueio de saída HTTPS do sandbox; a autenticação do Git, com rede permitida, funciona.
- A conexão GitHub do Codex continua autenticada como `Befofas-lab`, não como a conta proprietária. O metadata para essa conexão informa `pull: true`, `push: false`, `admin: false`; consultas de permissão de colaborador retornam `403 Resource not accessible by integration`. Essa identidade não pode publicar branches nem abrir PRs. Em contraste, o `gh` local é `berofel`, o repositório informa `viewerPermission: ADMIN`, e o escopo `repo` habilita a CLI a operar no repositório. Nenhum PR foi criado como teste para evitar abrir uma proposta sem escopo de código definido.
- Antes da alteração, todas as branches estavam `protected: false` e os rulesets do repositório retornaram `[]`; a leitura autenticada da proteção de `main` deu `404 Branch not protected`. Não era a causa de rejeição de branches feature. Agora `main` está protegida por PR e checks obrigatórios, sem bloquear pushes em `feat/*` ou `fix/*`.
- Com a conta proprietária, `GET /actions/permissions` retornou `enabled: true`, `allowed_actions: all`; `GET /actions/permissions/workflow` retornou `default_workflow_permissions: read` e `can_approve_pull_request_reviews: false`. Isso é compatível com o YAML: `contents: read` para CI/build e `contents: write` somente no job `publish-release`; o workflow não cria PR. Não elevamos permissões globais do Actions.
- CI do HEAD `28bc525c4c768d0211409ffade7833f32e4fa00a`: run [45796041959](https://github.com/berofel/BerofelStudio-MLF/actions/runs/45796041959) concluído com sucesso. Passaram os jobs `Windows 11 / Python 3.12 tests`, `build` e `Clean Windows install / launch / uninstall`; `Publish validated GitHub Release` foi pulado como esperado num push de branch. Os testes que falharam em execuções anteriores foram corrigidos em commits subsequentes; não desativamos testes.
- O checkout tem `push.default=simple`, `push.autoSetupRemote=true`, `fetch.prune=true` e `pull.ff=only`; `origin` e os upstreams estão corretos. O autor local é `BerofelStudio Codex <codex@localhost>`; isso não impediu os commits remotos observados, mas não atribui autoria ao perfil GitHub nem satisfaz uma eventual política futura de assinatura/verificação. Defina nome e e-mail verificado somente com os dados confirmados pelo proprietário.

### Reautenticar futuramente, se a sessão expirar

Na máquina Windows do usuário, a autenticação atual já foi confirmada. Se ela expirar, reautentique a CLI com uma sessão interativa do proprietário e reinstale-a como helper Git:

```powershell
& 'C:\Program Files\GitHub CLI\gh.exe' auth login --hostname github.com --git-protocol https --web --scopes repo,workflow
& 'C:\Program Files\GitHub CLI\gh.exe' auth status
& 'C:\Program Files\GitHub CLI\gh.exe' auth setup-git
git ls-remote origin HEAD
```

Conclua a autorização no navegador com a conta que tem escrita no repositório. Não cole PAT no terminal, chat, workflow ou arquivo do projeto. Se o token foi revogado/expirou, essa nova autorização substitui a entrada inválida sem expor o token. Se a organização exigir SSO, autorize o token para SSO.

Depois de reautenticar, teste escrita somente enviando um commit validado em uma branch de trabalho e confirme o mesmo SHA com `git ls-remote --heads origin <branch>`. Um `--dry-run` com tudo sincronizado não comprova permissão de escrita.

### Permissões que dependem do proprietário

Para fazer push e PR pela integração GitHub do Codex, ainda é necessário conectar a conta `berofel` ou atualizar a instalação para `Contents: read/write` e `Pull requests: read/write`; para commits que alterem `.github/workflows/*`, também é necessário `Workflows: write`. Hoje, use a CLI autenticada como `berofel` para essas operações. Se o app do Codex não oferecer os escopos, o proprietário precisa solicitar ao fornecedor do app; não é possível conceder localmente uma permissão que o app não solicitou.

Proteção aplicada e verificada em `main`: PR obrigatório, branch atualizada antes de integrar (`strict: true`), administração incluída na regra, zero aprovações obrigatórias para permitir o fluxo solo do proprietário, force-push e exclusão bloqueados. Checks exigidos: `Windows 11 / Python 3.12 tests`, `build` e `Clean Windows install / launch / uninstall`. Branches de feature permanecem sem proteção própria. A configuração não altera permissões do Actions nem desativa testes.

Links diretos do proprietário:

- Acesso e colaboradores: <https://github.com/berofel/BerofelStudio-MLF/settings/access>
- Instalação de aplicativos: <https://github.com/settings/installations>
- Tokens fine-grained: <https://github.com/settings/personal-access-tokens/new>
- Regras de branches: <https://github.com/berofel/BerofelStudio-MLF/settings/branches>
- Rulesets: <https://github.com/berofel/BerofelStudio-MLF/settings/rules>
- Permissões de GitHub Actions: <https://github.com/berofel/BerofelStudio-MLF/settings/actions>

### Uso diário

```powershell
git status --short --branch
git fetch --prune origin
git switch -c feat/<assunto> origin/main
# implemente; rode os testes obrigatórios e revise o diff
git diff --check
git add <arquivos-validados>
git commit -m "feat: resumo objetivo"
git push -u origin HEAD
```

Abra o PR de `<branch>` para `main` após o push e aguarde os checks obrigatórios. Só integre alterações validadas; nunca use `--force`/`--force-with-lease` nem faça push direto em `main`. `pull.ff=only` faz `git pull` parar com erro se houver divergência; nessa situação, examine os dois lados e resolva explicitamente, sem reset.

### Ação necessária do proprietário para PR pela integração Codex

O proprietário deve revisar se a instalação do GitHub App usada pelo Codex inclui este repositório e quais permissões o app solicitou. Se o app oferecer `Contents: write` e `Pull requests: write`, autorizar essa atualização; para editar `.github/workflows/*`, o app também precisa solicitar e receber `Workflows: write`. O dono da instalação não consegue conceder um escopo que o próprio app não solicitou; nesse caso, use a CLI com uma conta que tenha escrita ou peça ao administrador do app/integrador que disponibilize esses escopos. Alternativamente, conecte no Codex uma conta GitHub que já tenha escrita. Links diretos:

- Acesso e colaboradores: <https://github.com/berofel/BerofelStudio-MLF/settings/access>
- Instalação de aplicativos: <https://github.com/settings/installations>
- Regras de branches: <https://github.com/berofel/BerofelStudio-MLF/settings/branches>
- Rulesets: <https://github.com/berofel/BerofelStudio-MLF/settings/rules>
- Permissões de GitHub Actions: <https://github.com/berofel/BerofelStudio-MLF/settings/actions>

Não habilite permissões de escrita amplas para todas as organizações/repositórios se a instalação permitir selecionar somente `BerofelStudio-MLF`. Branch protection pode ser configurada pelo proprietário para exigir PR e os checks reais de CI, mas não é uma correção para a identidade de integração sem `push`.

## Segurança e limites de distribuição

- O EXE é um bootstrapper online, não um pacote offline completo: baixa Python, dependências, FFmpeg e os motores selecionados.
- Os pesos do Qwen/Parakeet não são embutidos no Git ou no EXE; são arquivos grandes com licenças e requisitos próprios. Após download, os motores locais funcionam sem API externa conforme cada módulo.
- O smoke automatizado usa `/COREONLY`; ele não baixa vários gigabytes de modelos nem valida inferência TTS/ASR em cada Release.
- O instalador ainda não tem assinatura Authenticode própria. SHA-256 detecta corrupção, mas não substitui assinatura de editor verificado nem remove o aviso SmartScreen.
- Antes de vender amplamente, revisar licenças de dependências/modelos, instalar em PCs de teste distintos, validar downloads opcionais e obter assinatura de código.
- Não incluir gravações, projetos, perfis vocais, tokens, ambientes virtuais, caches ou pesos de IA nos commits ou assets.

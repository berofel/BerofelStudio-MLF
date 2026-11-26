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

Estado verificado no workspace Windows:

- `origin` aponta para `https://github.com/berofel/BerofelStudio-MLF.git` em fetch e push.
- O Git Credential Manager está configurado como helper (`manager`). O teste autenticado `git push --dry-run` ao branch de trabalho retornou `Everything up-to-date`; pushes reais anteriores desta sessão também foram confirmados no remoto. Nenhum token deve ser copiado para arquivos ou logs.
- O sandbox bloqueia conexões HTTPS ao GitHub (`Failed to connect to github.com:443`). Fora do sandbox, `git fetch --prune origin` e o `push --dry-run` concluíram. Se a mesma mensagem aparecer, a causa é a rede do ambiente, não um conflito Git; não altere o remote nem reescreva histórico para tentar contorná-la.
- A configuração Git global inclui o caminho exato deste checkout em `safe.directory`, corrigindo a rejeição `fatal: detected dubious ownership`. Não marque pastas amplas como seguras.
- A configuração local do repositório é `push.default=simple`, `push.autoSetupRemote=true`, `fetch.prune=true` e `pull.ff=only`. Assim, branches novas passam a rastrear o upstream no primeiro push, branches removidas do remoto são podadas no fetch, e pulls não criam merges implícitos.
- `gh` não está instalado neste ambiente (`gh` não reconhecido), então `gh auth status` e criação de PR via CLI não estão disponíveis. Instalar/autenticar o CLI é opcional; o Git Credential Manager já atende aos pushes Git.
- A integração GitHub conectada ao Codex informa `permissions.push=false`; a consulta de permissão do colaborador falha com `403 Resource not accessible by integration`. Uma tentativa anterior de criar PR foi rejeitada com `422 ... must be collaborator`. Essa identidade do conector é diferente do credential helper que autenticou os pushes Git. Portanto, push Git funcional não implica permissão para abrir PR pela integração do Codex.
- A lista pública de branches reporta `protected=false` e o endpoint de rulesets retorna `[]`. A consulta detalhada da proteção de `main` respondeu `403 Resource not accessible by integration`, portanto a integração não consegue inspecionar regras administrativas; não há evidência de branch protection ativa na lista pública. Não removemos proteções.
- A leitura de `actions/permissions` é recusada pelo conector como endpoint não permitido. O estado administrativo das permissões de Actions não pôde ser confirmado por esta conexão. Os workflows versionados devem continuar executando seus testes; nenhuma permissão ou teste foi alterado nesta configuração.
- O workflow do instalador define `permissions: contents: read` para os testes/build e `contents: write` somente no job de publicação de Releases; não usa token para abrir PR. O endpoint administrativo de permissões do repositório não ficou acessível, portanto não afirmamos conhecer a política global do Actions.
- A execução CI do commit `ff441903600c7a6ae59ffc1343fd0c4c119db678` (run [45790082395](https://github.com/berofel/BerofelStudio-MLF/actions/runs/45790082395)) reportou `4 failed, 677 passed, 8 skipped`. Os quatro testes multivozes chamavam `build_script()` sem selecionar motor, mas a interface exige seleção explícita e corretamente lança `ValueError: Escolha manualmente o motor de narração antes de gerar o roteiro.`. Os fixtures foram corrigidos nesta branch para escolher um motor de teste compatível. A CI Windows do commit de correção `57580c138dbff82d4ca3374ca2ebd4f2523680c2` (run [45792450673](https://github.com/berofel/BerofelStudio-MLF/actions/runs/45792450673)) passou: `681 passed, 8 skipped, 83 subtests`; compilação do instalador e smoke test de instalação limpa também passaram. O ambiente local não tem `pytest` nem `PySide6`, por isso essa validação foi feita pelo runner Windows do repositório.

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

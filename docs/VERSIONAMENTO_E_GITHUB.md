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

## Segurança e limites de distribuição

- O EXE é um bootstrapper online, não um pacote offline completo: baixa Python, dependências, FFmpeg e os motores selecionados.
- Os pesos do Qwen/Parakeet não são embutidos no Git ou no EXE; são arquivos grandes com licenças e requisitos próprios. Após download, os motores locais funcionam sem API externa conforme cada módulo.
- O smoke automatizado usa `/COREONLY`; ele não baixa vários gigabytes de modelos nem valida inferência TTS/ASR em cada Release.
- O instalador ainda não tem assinatura Authenticode própria. SHA-256 detecta corrupção, mas não substitui assinatura de editor verificado nem remove o aviso SmartScreen.
- Antes de vender amplamente, revisar licenças de dependências/modelos, instalar em PCs de teste distintos, validar downloads opcionais e obter assinatura de código.
- Não incluir gravações, projetos, perfis vocais, tokens, ambientes virtuais, caches ou pesos de IA nos commits ou assets.

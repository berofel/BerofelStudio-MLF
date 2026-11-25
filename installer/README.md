# Instalador único do BerofelStudio para Windows

## Baixar para outro computador

Para testar a versão atual, baixe o instalador da pré-release
[BerofelStudio 0.10.0-alpha.3](https://github.com/berofel/BerofelStudio-MLF/releases/download/v0.10.0-alpha.3/BerofelStudio-0.10.0-alpha.3-Setup-x64.exe)
ou abra a [página da Release](https://github.com/berofel/BerofelStudio-MLF/releases/tag/v0.10.0-alpha.3).
Baixe também o `.sha256` exibido na mesma página para conferir manualmente:

```powershell
Get-FileHash .\BerofelStudio-<versão>-Setup-x64.exe -Algorithm SHA256
Get-Content .\BerofelStudio-<versão>-Setup-x64.exe.sha256
```

Os valores SHA-256 precisam ser iguais. Execute o EXE e mantenha selecionados
os componentes Parakeet TDT v3 ONNX INT8/CPU e Qwen3-TTS para instalar os motores de IA junto
com o editor. A opção de atalho da Área de Trabalho fica selecionada por padrão.
O setup instala por usuário, sem copiar projetos, mídias ou perfis vocais do
computador que produziu o instalador.

**Aviso:** o endereço `/releases/latest/download/` só funciona depois que
houver uma Release estável. O GitHub não considera pré-releases alpha como
`latest`; por isso esse endereço retorna HTTP 404 durante esta fase de testes.
Quando publicarmos uma versão estável, o link permanente será
[BerofelStudio-Setup-x64.exe](https://github.com/berofel/BerofelStudio-MLF/releases/latest/download/BerofelStudio-Setup-x64.exe).

Todo setup versionado consulta as Releases públicas antes de alterar o editor.
Se houver uma versão SemVer mais nova no canal daquele setup, ele baixa o EXE e
o checksum, valida a origem esperada, tamanho e SHA-256, e inicia o setup
atualizado. O canal alpha acompanha pré-releases; um setup estável não troca
para alpha/beta. Sem rede, sem release instalável ou diante de checksum inválido,
o arquivo suspeito é recusado e o instalador informa o problema antes de oferecer
continuar com o setup já baixado. `/NOUPDATECHECK` desativa a verificação para
rollback/manual. A atualização não remove projetos, mídia, perfis ou modelos,
que ficam fora da pasta do aplicativo.

## O que significa “instalador único”

É um único EXE que instala o aplicativo e automatiza a preparação das
dependências. A instalação inicial precisa de internet para obter Python,
pacotes, FFmpeg e os componentes de IA selecionados; o usuário não precisa
executar scripts separados. Depois do download dos modelos, os motores locais
funcionam offline. Este artefato **não é um instalador offline autocontido**.

Os pesos do Qwen e outros modelos não estão embutidos. Além de serem grandes e
terem licenças próprias, o Qwen/Torch local ocupa vários GiB; o computador de
desenvolvimento mediu 6,30 GiB na pasta isolada de Qwen e 1,88 GiB nos modelos
locais de análise. Esses números são uma referência desta máquina, não uma
garantia de tamanho para outras versões. GitHub limita cada arquivo de Release
a menos de 2 GiB, por isso o EXE busca os componentes diretamente das fontes
configuradas e verifica os arquivos conforme os instaladores do projeto. O
build também falha se pesos de modelos aparecerem no pacote ou se o EXE chegar
ao limite de tamanho do GitHub.

O setup ainda não é assinado digitalmente pelo Berofel Studio; o Windows pode
mostrar avisos de SmartScreen. Antes de vender ou divulgar como versão pronta
para produção, validar a instalação limpa em outra máquina, revisar as
licenças de Qt/PySide, FFmpeg, bibliotecas e pesos dos modelos, e providenciar
assinatura de código própria.

O artefato publicado será `BerofelStudio-<versão>-Setup-x64.exe`. Ele instala
o código e os recursos da versão, cria atalhos no Menu Iniciar e (marcado por
padrão) na Área de Trabalho, registra a desinstalação por usuário e prepara o
ambiente pelo mesmo bootstrap já usado pelo projeto. A janela principal usa o
ícone vetorial da marca; o instalador e os atalhos usam sua renderização
multirresolução `assets/brand/berofel_studio.ico`.

## Componentes e conexão

O instalador é um único download, mas a instalação inicial precisa de internet:
ele baixa Python 3.12 x64 assinado pela Python Software Foundation, o runtime
Visual C++ assinado pela Microsoft quando necessário, dependências fixadas por
`requirements.txt`, FFmpeg/FFprobe de um distribuidor com SHA-256 verificado,
e executa os autotestes locais.

As duas tarefas de IA vêm marcadas inicialmente e podem ser desmarcadas:

* Parakeet TDT v3 ONNX INT8/CPU, Silero VAD ONNX e dicionário local VERO pt-BR.
* Qwen3-TTS Base 0.6B no ambiente isolado existente (download aproximado de
  2,5 GB).

Os pesos de IA e o Python não são embutidos no EXE publicado: os modelos são
grandes, têm seus próprios termos/licenças e não devem entrar no Git. O EXE é
um bootstrapper verificado pelo SHA-256 que baixa os artefatos de suas fontes
durante a instalação. Portanto, esta versão não é offline nem portátil; após os
downloads, os motores locais funcionam sem API, conforme seus módulos. A
assistente local Qwen 1.7B e runtimes experimentais continuam opcionais e
não são instalados por padrão.

O pacote é montado com NSIS e usa somente o compressor zlib. O código e esse
compressor são distribuídos sob licença zlib/libpng, que permite uso comercial;
veja [a licença oficial do NSIS](https://nsis.sourceforge.io/License). Esta
escolha evita a licença comercial exigida pelo Inno Setup para uso comercial
do compilador.

O caminho de instalação é `%LOCALAPPDATA%\BerofelStudio`; o ambiente Python e
os modelos permanecem em `%LOCALAPPDATA%\BFS`. Desinstalar o editor não apaga
automaticamente perfis de voz, modelos, caches, projetos ou mídias privados.
Para remover esses dados, use os controles próprios do aplicativo depois de
fazer cópias de segurança.

## Compilar localmente

Requer Windows x64, NSIS, Git, a versão do projeto já registrada em
`berofel/__init__.py` e uma árvore Git limpa. No PowerShell, na raiz do repo:

```powershell
& "$env:LOCALAPPDATA\BFS\venv\Scripts\python.exe" scripts\gerar_icone_app.py
git add assets\brand\berofel_studio.ico
git commit -m "build: update Windows application icon"
.\scripts\build_windows_installer.ps1
```

O pacote vem de `git archive HEAD`; a área temporária de build exclui modelos,
mídias, runtimes locais, `.git`, caches, dados de teste e ambientes Python. O
EXE e seu `.sha256` saem em `dist/`, diretório ignorado pelo Git.

## Publicar no GitHub

O workflow `.github/workflows/build-windows-installer.yml` executa a suíte no
Windows antes de compilar. Em pushes nas branches `main`, `feat/*` e `fix/*`,
tags e execuções manuais, instala o pacote em um runner limpo, abre a janela Qt,
confere o atalho, verifica que dados em `%LOCALAPPDATA%\BFS` sobrevivem à
desinstalação e remove o aplicativo. Pull requests para `main` também executam
essa validação. Cria artefatos em PRs para `main` e só publica Release quando
uma tag `v*` for enviada
e corresponder à versão declarada no código. Tags alpha/beta/rc são
pré-releases; tags sem sufixo pré-release são estáveis. Cada release contém o
EXE versionado, um alias estável e seus checksums. Fluxo de publicação:

```powershell
git status --short
git tag v0.10.0 <commit-validado>
git push origin v0.10.0
```

O workflow só cria a Release a partir da tag e não faz push de código, não
altera `main` e não usa force push. Push de código é uma ação separada e deve
seguir `docs/VERSIONAMENTO_E_GITHUB.md`. Antes de uma tag pública, testar o
instalador em Windows limpo (incluindo instalação, inicialização, update e
desinstalação) e confirmar as licenças/redistribuição dos downloads. Não
chamar uma Release de pronta para venda enquanto essa validação não ocorrer.

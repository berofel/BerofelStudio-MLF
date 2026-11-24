# Instalador único do BerofelStudio para Windows

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

* Faster-Whisper Base, Silero/ONNX e dicionário local VERO pt-BR.
* Qwen3-TTS Base 0.6B no ambiente isolado existente (download aproximado de
  2,5 GB).

Os pesos de IA e o Python não são embutidos no EXE publicado: os modelos são
grandes, têm seus próprios termos/licenças e não devem entrar no Git. O EXE é
um bootstrapper verificado pelo SHA-256 que baixa os artefatos de suas fontes
durante a instalação. Portanto, esta versão não é offline nem portátil; após os
downloads, os motores locais funcionam sem API, conforme seus módulos. A
assistente local Qwen 1.7B, Parakeet e runtimes experimentais continuam
opcionais e não são instalados por padrão.

O caminho de instalação é `%LOCALAPPDATA%\BerofelStudio`; o ambiente Python e
os modelos permanecem em `%LOCALAPPDATA%\BFS`. Desinstalar o editor não apaga
automaticamente perfis de voz, modelos, caches, projetos ou mídias privados.
Para remover esses dados, use os controles próprios do aplicativo depois de
fazer cópias de segurança.

## Compilar localmente

Requer Windows x64, Inno Setup 6, Git, a versão do projeto já registrada em
`berofel/__init__.py` e uma árvore Git limpa. No PowerShell, na raiz do repo:

```powershell
& "$env:LOCALAPPDATA\BFS\venv\Scripts\python.exe" scripts\gerar_icone_app.py
git add assets\brand\berofel_studio.ico
git commit -m "build: update Windows application icon"
.\scripts\build_windows_installer.ps1
```

O pacote vem de `git archive HEAD`, não inclui arquivos não rastreados,
modelos, mídias, runtimes locais, `.git`, caches ou ambientes Python. O EXE e
seu arquivo `.sha256` saem em `dist/`, diretório ignorado pelo Git.

## Publicar no GitHub

O workflow `.github/workflows/build-windows-installer.yml` compila no Windows
quando acionado manualmente e publica EXE + checksum em Releases quando uma tag
`v*` for enviada. Fluxo de release:

```powershell
git status --short
git tag v0.10.0-alpha.1 <commit-validado>
git push origin v0.10.0-alpha.1
```

O workflow só cria a Release a partir da tag e não faz push de código, não
altera `main` e não usa force push. Antes de uma tag pública, testar o
instalador em Windows limpo (incluindo instalação, inicialização, update e
desinstalação) e confirmar as licenças/redistribuição dos downloads. Não
chamar uma Release de pronta para venda enquanto essa validação não ocorrer.

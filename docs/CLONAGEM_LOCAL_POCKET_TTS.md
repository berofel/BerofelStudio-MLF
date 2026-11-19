# Clonagem de voz local no BerofelStudio

> **Documento histórico, supersedido pela diretriz Qwen3-TTS Base único.** Pocket TTS não é mais instalado ou executado pelo editor. Modelos, caches, projetos e áudios que já estavam no computador foram preservados.

## Estado confirmado em 18/11/2026

O ambiente `C:\Users\Berofel\AppData\Local\BFS\venv` tem `pocket-tts 4.0.1` e `torch 2.15.0`. A voz de catálogo carrega em CPU. Neste computador, o modelo reportou `has_voice_cloning=False`; o comando `hf auth whoami` retornou “Not logged in” e o acesso ao checkpoint português foi bloqueado com `WinError 10013`. Portanto, a clonagem pessoal ainda não está habilitada nem validada aqui. O botão/fluxo de ativação não pode substituir esse requisito de acesso.

O erro não significa que Pocket TTS dependa de uma API de geração. A inferência, o condicionamento da amostra, a síntese e o WAV são locais. A conexão com Hugging Face serve para obter uma vez o checkpoint autorizado; o aceite é controlado pelo titular da conta. Depois do checkpoint completo e dos demais arquivos necessários no cache local, a síntese pode funcionar sem conexão.

O diagnóstico da preparação separa agora os casos de token inválido/ausente, recusa gated, rede bloqueada, checkpoint ainda fora do cache quando o Hub não pode ser consultado, transferência incompleta e arquivo/revisão inexistente. `LocalEntryNotFoundError` sozinho não prova que o usuário recusou o modelo: significa que o arquivo não pôde ser encontrado localmente e a tentativa remota também não foi concluída.

A ativação iniciada na aba Narração foi integrada ao editor: o usuário confirma que aceitou os termos, informa o token em campo mascarado e acompanha a preparação no próprio painel, sem janela CMD. O token é passado ao processo local via stdin, não aparece na linha de comando nem no log; a autenticação oficial do Hugging Face mantém o token no armazenamento padrão dessa ferramenta. A preparação continua explícita e a inferência posterior permanece offline.

## Evitar downloads escondidos durante geração

O download e a validação do checkpoint completo pertencem ao passo explícito `AUTORIZAR_POCKET_TTS.bat`. A geração agora exige que o checkpoint de clonagem esteja no cache local e configura o worker em modo offline enquanto carrega pesos, codifica a amostra e sintetiza. Se faltar o checkpoint, o editor deve instruir o usuário a concluir a ativação, sem fazer uma busca de rede implícita nem trocar silenciosamente para uma voz de catálogo.

O áudio de referência é normalizado por FFmpeg em arquivo temporário, sem alterar o original. O estado derivado é armazenado no cache privado `%LOCALAPPDATA%\BFS\cache\pocket_tts\voice_states`, com chave por conteúdo, idioma e modelo; o arquivo pessoal não é enviado nem incluído no projeto/repositório.

## Ativar a clonagem pessoal

1. O instalador principal (`instalar_dependencias.bat`) oferece instalar o Pocket TTS local com PyTorch/CPU. Para instalar ou reparar somente esse componente depois, use `INSTALAR_POCKET_TTS.bat`.
2. Acesse [kyutai/pocket-tts no Hugging Face](https://huggingface.co/kyutai/pocket-tts), entre na conta e aceite os termos do modelo.
3. No painel **Narração**, clique **Preparar clonagem local** com internet disponível e informe seu token em campo mascarado. A preparação baixa os pesos e valida o encoder com uma amostra sintética, nunca com o áudio pessoal. `AUTORIZAR_POCKET_TTS.bat` permanece como alternativa manual.
4. No editor, selecione **Minha voz / amostra com autorização**, importe uma gravação autorizada e gere a narração.
5. Confirme que a voz gerada é a desejada. Se houver falha, envie o erro/log apresentado; não é necessário compartilhar a gravação.

Após a ativação, use `TESTAR_POCKET_TTS.bat --clone --offline` para verificar a rota real com referência sintética, se os pesos estiverem presentes. Esse teste não substitui uma comparação auditiva com a voz do usuário.

## O que o editor antigo fazia com Qwen3-TTS

O ZIP `C:\Users\Berofel\Desktop\BerofelStudio_codigo_base_alpha\Berofel-Studio Python.zip` foi lido como arquivo ZIP; `Berofel-Studio-main` é uma pasta interna do ZIP, não um caminho de diretório independente no Windows. A implementação antiga tinha um worker oficial `qwen-tts` que chamava `create_voice_clone_prompt(ref_audio, ref_text)` e depois `generate_voice_clone`. Sem transcrição da gravação, usava `x_vector_only_mode=True`. Também separava o TTS em ambiente, mantinha modelos/processos e caches para reuso e implementava timeout, progresso e retomada.

Além do backend PyTorch, o legado roteava para duas opções externas ao Python: `qwentts.cpp` nativo no Windows (requer executável e modelos fornecidos à parte) e um backend comunitário em WSL2/INT4 que compilava/instalava seu próprio runtime. O ZIP contém código e scripts para essas rotas, mas não contém `qwentts.exe`, pesos `.gguf` ou checkpoints `.safetensors`; portanto, não é uma instalação autônoma pronta para clonar. O código antigo demonstra uma arquitetura de backends e cache, não prova que os modelos estivessem instalados ou que a clonagem funcionasse neste PC.

No checkout atual, o worker Qwen carrega pesos Base em CPU com `local_files_only=True`; sua falha relatada no screenshot era a dependência `imageio_ffmpeg` ausente no ambiente isolado, anterior à inferência. O instalador atual passou a incluir essa dependência. Qwen permanece opcional enquanto a migração para Pocket não tiver clonagem pessoal real validada; não removemos checkpoints, projetos, áudios ou configurações do usuário.

## Pocket TTS nativo/standalone versus integração Python

O projeto oficial publica um binário standalone para Windows x86, além da biblioteca Python. O binário executa em CPU e não exige Python/PyTorch; o upstream indica AVX2 para o build x86 principal (AMD Zen ou mais novo) e documenta clonagem por WAV e perfil de voz exportado. Esse executável continua precisando dos modelos e das permissões correspondentes; “standalone” não significa que o modelo de clonagem esteja embutido nem que haja uma API de inferência remota. O release oficial aponta v4.0.1 como atual e documenta que os binários Rust têm a mesma interface de CLI; não baixamos nem executamos o asset Windows nesta validação, portanto não afirmamos compatibilidade perfeita com o checkpoint português, cancelamento, cache e ciclo de export do editor.

O BerofelStudio atual usa a biblioteca Python `pocket-tts==4.0.1` dentro do ambiente do aplicativo, chamando o worker local por subprocesso. Isso usa o PC e não requer uma API HTTP. O `pocket-tts.exe` encontrado em `BFS\venv\Scripts` é o entry point instalado pelo pacote Python, não é o binário Rust standalone. Mantemos o backend Python por enquanto porque está integrado e a síntese local de catálogo foi executada; o binário standalone continua sendo candidato para reduzir dependências, mas a escolha final precisa de comparação real de tamanho instalado, RAM, tempo de carga/síntese, clonagem portuguesa, cancelamento, cache de perfis e correspondência WAV/MP4. Não o incorporamos sem esses ensaios.

Referências oficiais consultadas:

- [Pocket TTS: execução CPU, clonagem, CLI, biblioteca e binários standalone Windows](https://github.com/kyutai-labs/pocket-tts)
- [Comando oficial export-voice e limite de 30 segundos da amostra](https://github.com/kyutai-labs/pocket-tts/blob/main/docs/CLI%20Commands/export_voice.md)
- [Comportamento do modelo quando os pesos de clonagem não estão disponíveis](https://github.com/kyutai-labs/pocket-tts/blob/main/pocket_tts/models/tts_model.py)

## Limite da validação

Os testes automatizados e a síntese de catálogo não provam clonagem pessoal. Enquanto a conta Hugging Face não autorizar e baixar o checkpoint, uma síntese real com voz de referência permanece pendente. Não declarar a migração concluída nem remover a rota Qwen até validar a amostra sintética offline e uma amostra própria autorizada no Windows, além da saída WAV/MP4 sincronizada.

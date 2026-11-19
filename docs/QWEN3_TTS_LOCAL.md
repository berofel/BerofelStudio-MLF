# Qwen3-TTS local no BerofelStudio

## Motor e fluxo

O motor ativo de narração e clonagem é `Qwen/Qwen3-TTS-12Hz-0.6B-Base`, carregado em um ambiente Python isolado sob `%LOCALAPPDATA%\BFS\qwen3_tts`. A síntese usa CPU, pesos locais e acesso offline. Não há chamada de API de geração de voz. O primeiro preparo precisa de internet e baixa aproximadamente 2,5 GB; o instalador pergunta antes de baixar.

O painel `Narração` exige uma gravação autorizada e o texto exato falado nela. Áudio de referência é normalizado em um arquivo temporário e a fonte não é modificada. Perfis locais guardam cópia privada da referência e sua transcrição. A geração final é um WAV durável adicionado como bloco de áudio na timeline.

O único motor distribuído para narração é `Qwen/Qwen3-TTS-12Hz-0.6B-Base`. O projeto não instala Pocket TTS, Qwen 1.7B ou `CustomVoice` na distribuição padrão. O idioma suportado depende do modelo; a interface oferece apenas idiomas mapeados pelo worker instalado.

## Preparar e usar

1. Rode `INSTALAR_QWEN3_TTS_LOCAL.bat` ou escolha Qwen3-TTS no instalador principal. O script pode retomar arquivos já baixados e não reinstala se o ambiente/modelo estiverem prontos.
2. No editor, abra `Narração`, selecione `Minha voz / amostra com autorização`, escolha WAV/MP3/FLAC/OGG/M4A, marque a autorização e informe a transcrição exata da amostra.
3. Digite uma frase diferente da gravação e escolha `Gerar e adicionar na timeline` ou `Gerar só o WAV`.
4. `Salvar perfil` guarda uma cópia local privada da gravação e o texto de referência, para reutilização. O arquivo original permanece inalterado. Ao salvar, o perfil é preparado em segundo plano.

O worker Qwen fica ativo durante a sessão do editor: o modelo é carregado uma vez, os pedidos de síntese são enviados ao mesmo processo e o condicionamento de voz fica em cache. O prompt de voz também pode ser guardado em arquivo NPZ versionado sem pickle; se a versão do modelo/encoder ou o conteúdo de referência mudar, ele é reconstruído. O processo encerra junto com o editor e libera a memória então.

Não é necessário fazer login no Hugging Face para inferência. A geração não tenta baixar modelos pela rede. As bibliotecas e modelos instalados permanecem no ambiente isolado do app; o pacote externo SoX e FlashAttention podem emitir aviso no startup. No teste Windows, ambos foram não bloqueantes para Qwen 12Hz Base em CPU.

## Diagnóstico das falhas anteriores

- A UI ainda priorizava Pocket TTS e mantinha Qwen como opção de compatibilidade. Novos pedidos podiam seguir para um motor diferente do escolhido para clonagem.
- O ambiente Qwen isolado não incluía `imageio-ffmpeg`, usado na normalização da amostra. O instalador passou a incluí-lo e verificar a importação.
- A API oficial do Qwen usa `max_new_tokens=2048` como padrão. Sem orçamento por texto, frases curtas podiam continuar gerando até estourar o timeout de uma hora em CPU. O worker agora limita a saída usando uma estimativa proporcional ao texto, com margem e teto oficial de 2048 tokens.
- No ambiente instalado, `qwen-tts==0.1.1`, `transformers==4.57.3` e PyTorch CPU importaram corretamente. Apesar do aviso do SoX e da ausência de FlashAttention, o worker fez inferência local real; esses avisos não causaram a falha reproduzida.

## Validação local

O histórico resumido e as instruções para repetir os testes estão em [`VALIDACAO_QWEN3_TTS_20261118.md`](VALIDACAO_QWEN3_TTS_20261118.md). Os testes de geração real usam uma referência autorizada já configurada localmente e não registram caminho, transcrição ou áudio.

## Limitações conhecidas

- O modelo 1.7B não foi baixado nem medido no Ryzen 7 5700G/16 GB.
- A identidade vocal não foi comparada com métricas biométricas nem avaliada por escuta humana controlada. O teste confirma geração condicionada pela API Base com gravação e texto, não uma nota de similaridade.
- Teste offline significa pesos instalados e variáveis de acesso remoto desativadas. O Windows não teve firewall/rede externa bloqueados durante o teste.
- A saída de áudio do teste de interface foi silenciada para não tocar a narração nos alto-falantes do usuário; player Qt, play, pause e busca foram exercitados.
- Perfis preexistentes `.safetensors` Pocket permanecem em disco, mas não são compatíveis com Qwen Base; importe uma gravação de referência em formato de áudio.
- O worker mantém o modelo em memória até o editor fechar; em 16 GB isso reduz espaço livre enquanto o editor está aberto. O benchmark observou pico agregado de RSS de 6,41 GiB.
- No benchmark de CPU deste computador, o worker persistente reduziu os carregamentos a um por sessão e reaproveitou o prompt após a primeira geração. A latência, porém, ficou acima da duração do áudio; consulte [`BENCHMARK_QWEN3_TTS_20261118.md`](BENCHMARK_QWEN3_TTS_20261118.md). Não é geração em tempo real.
- A versão Python instalada (`qwen-tts==0.1.1`) não expõe um método `generate_voice_clone_streaming`; o argumento `non_streaming_mode` da API não significa que áudio incremental esteja disponível. INT8/INT4 e backend nativo ainda não foram medidos/qualificados para o fluxo Windows com clonagem. Não os ativamos por padrão.

## Motor legado Pocket

Pocket TTS não aparece como opção no painel e não é instalado pelo fluxo principal ou por `INSTALAR_TODAS_AS_IAS.bat`. Seu código e arquivos locais não foram removidos automaticamente para preservar dados e permitir migração reversível. O backend legado só responde a uma requisição de código explicitamente marcada com `engine='pocket-tts'`; o app atual cria pedidos Qwen por padrão.


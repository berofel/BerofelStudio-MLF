# Qwen3-TTS local no BerofelStudio

## Motor e fluxo

O motor ativo de narração e clonagem é `Qwen/Qwen3-TTS-12Hz-0.6B-Base`, carregado em um ambiente Python isolado sob `%LOCALAPPDATA%\BFS\qwen3_tts`. A síntese usa CPU, pesos locais e acesso offline. Não há chamada de API de geração de voz. O primeiro preparo precisa de internet e baixa aproximadamente 2,5 GB; o instalador pergunta antes de baixar.

O painel `Narração` usa uma gravação autorizada. Para clonagem detalhada no backend Original, preencha o texto exato falado nela: com `ref_text`, o worker prepara o prompt oficial com áudio e transcrição juntos; sem ele, cai no modo somente x-vector. A fonte não é modificada. Perfis locais guardam cópia privada da referência e sua transcrição. A geração final é um WAV durável adicionado como bloco de áudio na timeline.

O único modelo de narração é `Qwen/Qwen3-TTS-12Hz-0.6B-Base`. Quando instalado, a interface recomenda inicialmente Equilibrado — Pure C INT8; esse e os backends nativos Q4 usam somente x-vector e não enviam a transcrição da referência. Original Qwen3-TTS Base continua disponível para clonagem detalhada e usa áudio mais transcrição quando o texto exato é preenchido. Os modos Pure C e Q4 são experimentais e opcionais; não vêm nos instaladores padrão e só aparecem quando o runtime está instalado. O projeto não instala Pocket TTS, Qwen 1.7B ou `CustomVoice` na distribuição padrão.

O idioma PT-BR seleciona o token de idioma `Portuguese`; Qwen3-TTS Base não fornece token distinto para português brasileiro versus europeu. O sotaque regional é condicionado principalmente pela própria gravação. Para uma saída brasileira, use uma referência limpa gravada em PT-BR. A interface mostra essa limitação e recomenda Original quando o objetivo for maximizar fidelidade. A verificação da referência também exibe quanto sinal passa do piso de silêncio e alerta sobre gravações com pausas excessivas, pouco nível ou clipping.

## Preparar e usar

1. Rode `INSTALAR_QWEN3_TTS_LOCAL.bat` ou escolha Qwen3-TTS no instalador principal. O script pode retomar arquivos já baixados e não reinstala se o ambiente/modelo estiverem prontos.
2. No editor, abra `Narração`, selecione `Minha voz / amostra com autorização`, escolha WAV/MP3/FLAC/OGG/M4A, marque a autorização e informe a transcrição exata da amostra.
3. Digite uma frase diferente da gravação e escolha `Gerar e adicionar na timeline` ou `Gerar só o WAV`.
4. `Salvar perfil` guarda uma cópia local privada da gravação e o texto de referência, para reutilização. O arquivo original permanece inalterado. Ao salvar, o perfil é preparado em segundo plano.

O worker Qwen fica ativo durante a sessão do editor: o modelo é carregado uma vez, os pedidos de síntese são enviados ao mesmo processo e o condicionamento de voz fica em cache. O prompt de voz também pode ser guardado em arquivo NPZ versionado sem pickle; se a versão do modelo/encoder ou o conteúdo de referência mudar, ele é reconstruído. O processo encerra junto com o editor e libera a memória então.

### Referências longas e silêncio no início

O Qwen3-TTS Base não treina nem aprende os pesos com a gravação do usuário. Ele cria um condicionamento a partir de um trecho de referência; o código oficial aceita referências curtas e a rota do Berofel limita esse trecho a no máximo 30 segundos. Portanto, um arquivo de uma hora não é enviado inteiro ao modelo como uma hora de condicionamento.

Para evitar que silêncio no começo seja usado como identidade vocal, a aplicação varre o áudio completo antes de preparar o prompt. Quando disponível, reutiliza o Silero/VAD instalado e analisa em blocos de 30 segundos; sem esse runtime, usa o filtro local `silencedetect` do FFmpeg como aproximação acústica. A seleção procura uma janela de até 30 segundos com fala/atividade e pode escolher um trecho menor se houver pouca fala. O Qwen recebe o mesmo intervalo identificado pela verificação. O arquivo original não é editado. A interface de verificação informa duração da fonte, início e duração da janela escolhida.

O texto `ref_text` do modo Original deve corresponder ao trecho escolhido, não à transcrição de uma hora inteira. Confira o horário exibido e forneça o texto falado nessa janela. O botão **Transcrever referência (Whisper local)** cria um rascunho offline dessa janela para você revisar; a transcrição não é salva nem usada sem sua confirmação no campo. Para PT-BR, a geração fica bloqueada enquanto o texto estiver vazio ou enquanto estiver selecionado um backend rápido somente x-vector. Isso evita cair silenciosamente no condicionamento mais fraco. Para outros idiomas, os modos x-vector continuam disponíveis.

Em resumo: um áudio longo é examinado por inteiro para encontrar uma janela vocal adequada, mas o Qwen não aprende nem recebe uma hora inteira. Ele recebe até 30 segundos selecionados (ou menos, quando o arquivo contém menos atividade). O perfil é um condicionamento/prompt de inferência, não um treinamento persistente do modelo. A transcrição também precisa ser somente dessa janela; texto de outra parte pode desalinhar a clonagem. A varredura identifica fala por Silero quando disponível; o fallback `silencedetect` só distingue silêncio acústico de atividade e pode confundir música/ruído com fala.

Não é necessário fazer login no Hugging Face para inferência. A geração não tenta baixar modelos pela rede. As bibliotecas e modelos instalados permanecem no ambiente isolado do app. O wrapper Python `sox==1.5.0` testa o executável `sox` no import e imprime um aviso quando ele não está no `PATH`; o executável não está instalado neste PC. O Qwen 12Hz Base ainda gerou WAV válido em testes reais sem ele (o código que chama `sox.Transformer()` está no tokenizer 25Hz, não no caminho Base 12Hz testado). FlashAttention também não está instalado e o Qwen usou o caminho PyTorch manual. Não fazemos instalação global silenciosa dessas ferramentas.

## Diagnóstico das falhas anteriores

- A UI ainda priorizava Pocket TTS e mantinha Qwen como opção de compatibilidade. Novos pedidos podiam seguir para um motor diferente do escolhido para clonagem.
- O ambiente Qwen isolado não incluía `imageio-ffmpeg`, usado na normalização da amostra. O instalador passou a incluí-lo e verificar a importação.
- A API oficial do Qwen usa `max_new_tokens=2048` como padrão. Sem orçamento por texto, frases curtas podiam continuar gerando até estourar o timeout de uma hora em CPU. O worker agora limita a saída usando uma estimativa proporcional ao texto, com margem e teto oficial de 2048 tokens.
- No ambiente instalado, `qwen-tts==0.1.1`, `transformers==4.57.3` e PyTorch CPU importaram corretamente. Apesar do aviso do SoX e da ausência de FlashAttention, o worker fez inferência local real; esses avisos não causaram a falha reproduzida.
- Em 19/11/2026, o benchmark pareado float32/INT8 foi repetido pelo script versionado; ambos os modos geraram áudio finito e não silencioso offline. O SoX ausente continuou sendo apenas aviso nesse caminho; `imageio-ffmpeg` estava instalado no venv isolado.

## Validação local

O histórico resumido e as instruções para repetir os testes estão em [`VALIDACAO_QWEN3_TTS_20261118.md`](VALIDACAO_QWEN3_TTS_20261118.md) e [`VALIDACAO_QWEN3_TTS_20261119.md`](VALIDACAO_QWEN3_TTS_20261119.md). A validação do backend nativo, benchmarks e limitações estão em [`QWEN3_TURBO_EXPERIMENT_20261119.md`](QWEN3_TURBO_EXPERIMENT_20261119.md). Os testes de geração real usam uma referência autorizada já configurada localmente e não registram caminho, transcrição ou áudio.

## Limitações conhecidas

- O modelo 1.7B não foi baixado nem medido no Ryzen 7 5700G/16 GB.
- A identidade vocal não foi comparada com métricas biométricas nem avaliada por escuta humana controlada. O teste confirma geração condicionada pela API Base com gravação e texto, não uma nota de similaridade.
- Teste offline significa pesos instalados e variáveis de acesso remoto desativadas. O Windows não teve firewall/rede externa bloqueados durante o teste.
- A saída de áudio do teste de interface foi silenciada para não tocar a narração nos alto-falantes do usuário; player Qt, play, pause e busca foram exercitados.
- Perfis preexistentes `.safetensors` Pocket permanecem em disco, mas não são compatíveis com Qwen Base; importe uma gravação de referência em formato de áudio.
- O worker mantém o modelo em memória até o editor fechar; em 16 GB isso reduz espaço livre enquanto o editor está aberto. O benchmark observou pico agregado de RSS de 6,41 GiB.
- No benchmark de CPU deste computador, o worker persistente reduziu os carregamentos a um por sessão e reaproveitou o prompt após a primeira geração. A latência, porém, ficou acima da duração do áudio; consulte [`BENCHMARK_QWEN3_TTS_20261118.md`](BENCHMARK_QWEN3_TTS_20261118.md). Não é geração em tempo real.
- A versão Python instalada (`qwen-tts==0.1.1`) não expõe um método `generate_voice_clone_streaming`; o argumento `non_streaming_mode` da API não significa que áudio incremental esteja disponível. O caminho Q4 nativo tem streaming experimental de prévia e benchmark no Ryzen 7 5700G, mas não substitui o backend oficial: usa x-vector sem ICL, e a qualidade perceptiva da voz ainda precisa de avaliação humana. A quantização dinâmica INT8 do PyTorch mostrou ganho pequeno e maior RSS neste hardware; não é ativada. INT4 dinâmico do PyTorch falhou por dtype não suportado. Q4 nativo é um formato separado e permanece opt-in.

## Motor legado Pocket

Pocket TTS não aparece como opção no painel e não é instalado pelo fluxo principal ou por `INSTALAR_TODAS_AS_IAS.bat`. Seu código e arquivos locais não foram removidos automaticamente para preservar dados e permitir migração reversível. O backend legado só responde a uma requisição de código explicitamente marcada com `engine='pocket-tts'`; o app atual cria pedidos Qwen por padrão.


# Clonagem local de voz: Pocket TTS e Qwen3-TTS

## Opção sem login: Qwen3-TTS local

Na aba **Narração**, selecione **Minha voz / amostra com autorização**, mantenha **Qwen3-TTS local** como motor, escolha uma gravação e marque a confirmação de autorização. Para melhor semelhança, informe no campo de texto a transcrição exata do áudio de referência. A primeira preparação pede confirmação, cria um ambiente Python isolado e baixa os pesos públicos Qwen3-TTS Base 0.6B (cerca de 2,5 GB, além das dependências) pelo botão **Preparar Qwen3 local**. Não é necessário entrar no Hugging Face nem aceitar um gate. Após a preparação, a clonagem e a síntese usam CPU e arquivos locais; o áudio de referência nunca é enviado. Se o texto de referência ficar vazio, o motor usa apenas o vetor de falante, que pode reduzir a qualidade.

O serviço preserva a gravação, usa cache privado por conteúdo da amostra/texto/idioma/modelo e copia cada WAV gerado para a pasta durável do projeto. A inferência real não foi executada nesta sessão porque o modelo de 2,5 GB não foi baixado. Portanto, a integração foi validada com worker e sinais sintéticos; velocidade, qualidade de clonagem e consumo em CPU ainda precisam ser medidos nesta máquina após a instalação.

O instalador usa Python 3.12 de 64 bits em um `venv` isolado, PyTorch CPU e `qwen-tts==0.1.1` (pacote Apache-2.0). Os modelos do projeto Qwen3-TTS e o checkpoint Base 0.6B declaram Apache-2.0. Os artefatos ficam em `%LOCALAPPDATA%\BFS\qwen3_tts`, fora do repositório e do ambiente principal do editor. A instalação usa rede apenas para pacotes/pesos; o worker do editor aponta para o diretório local e usa `local_files_only=True`.

## O que roda localmente

O BerofelStudio envia o texto e a referência ao worker local do Pocket TTS. O áudio é normalizado por FFmpeg no PC; o encoder extrai o estado de voz e o TTS gera WAV no PC. A gravação de referência não é enviada a um serviço de síntese. O estado derivado da voz é salvo em `%LOCALAPPDATA%\BFS\cache\pocket_tts\voice_states`, separado dos projetos e logs, para reutilização; a chave usa o conteúdo da amostra, idioma, versão do pacote e checkpoint. Se a amostra ou o checkpoint mudar, o estado é reconstruído. O WAV de origem não é alterado.

## Preparação inicial e requisito do modelo

O caminho de clonagem do checkpoint oficial requer o modelo completo. O pacote Pocket TTS instalado pode cair para pesos sem clonagem quando os pesos completos não estão disponíveis; nesse modo, apenas as vozes predefinidas funcionam. O repositório oficial exige que o usuário aceite as condições da página gated do modelo. Portanto, o aplicativo não tenta contornar o gate nem afirmar que clonagem funciona com o modelo de catálogo.

Depois de autorizado e baixado, `TTSModel` carrega os pesos do cache local e a inferência é executada localmente. Para a primeira instalação/ativação, a rede e o aceite são necessários. Se esses pesos não estiverem disponíveis, escolha explicitamente o motor Qwen3 local acima; Qwen3 não substitui a voz Rafael de catálogo do Pocket TTS e sua velocidade no CPU ainda não está medida.

## Como usar

1. Na narração, escolha **Minha voz / amostra com autorização** e selecione um WAV/MP3/FLAC/OGG/M4A.
2. Marque a autorização expressa, use **Preparar clonagem local…** uma vez e conclua o aceite/obtenção dos pesos oficiais quando solicitado.
3. Quando o painel confirmar o encoder com uma amostra sintética, gere a narração. Somente a primeira vez para cada amostra/idioma/checkpoint será calculado e guardado o estado vocal; as próximas execuções reaproveitam o arquivo `.safetensors` local.
4. Depois que o checkpoint estiver no cache, a geração pode operar sem rede. Os perfis derivados ficam no cache do usuário e não são versionados.

O estado de voz é dado biométrico sensível: mantenha acesso à sua conta Windows e apague os arquivos em `voice_states` se quiser remover os perfis derivados. Não apague o arquivo de referência por meio do editor.

## Proteção do wheel mouse

Combos, spins e sliders dos módulos de interface só recebem alteração por roda quando estão com foco (selecionados). Sem foco, a roda é encaminhada ao painel rolável ancestral. Para alterar um valor, clique/focalize o controle; para percorrer o painel, mantenha o ponteiro sobre os controles e role sem selecioná-los.

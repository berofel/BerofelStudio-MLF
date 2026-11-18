# Clonagem local com Pocket TTS

## O que roda localmente

O BerofelStudio envia o texto e a referência ao worker local do Pocket TTS. O áudio é normalizado por FFmpeg no PC; o encoder extrai o estado de voz e o TTS gera WAV no PC. A gravação de referência não é enviada a um serviço de síntese. O estado derivado da voz é salvo em `%LOCALAPPDATA%\BFS\cache\pocket_tts\voice_states`, separado dos projetos e logs, para reutilização; a chave usa o conteúdo da amostra, idioma, versão do pacote e checkpoint. Se a amostra ou o checkpoint mudar, o estado é reconstruído. O WAV de origem não é alterado.

## Preparação inicial e requisito do modelo

O caminho de clonagem do checkpoint oficial requer o modelo completo. O pacote Pocket TTS instalado pode cair para pesos sem clonagem quando os pesos completos não estão disponíveis; nesse modo, apenas as vozes predefinidas funcionam. O repositório oficial exige que o usuário aceite as condições da página gated do modelo. Portanto, o aplicativo não tenta contornar o gate nem afirmar que clonagem funciona com o modelo de catálogo.

Depois de autorizado e baixado, `TTSModel` carrega os pesos do cache local e a inferência é executada localmente. Para primeira instalação/ativação, a rede e o aceite são necessários. A rede bloqueada ou o checkpoint ausente impedem a clonagem oficial; este ambiente não tem uma rota de pesos substituta verificada/licenciada que preserve a velocidade e qualidade do Pocket TTS em português. Não foram baixados pesos nem aceitos termos automaticamente.

## Como usar

1. Na narração, escolha **Minha voz / amostra com autorização** e selecione um WAV/MP3/FLAC/OGG/M4A.
2. Marque a autorização expressa, use **Preparar clonagem local…** uma vez e conclua o aceite/obtenção dos pesos oficiais quando solicitado.
3. Quando o painel confirmar o encoder com uma amostra sintética, gere a narração. Somente a primeira vez para cada amostra/idioma/checkpoint será calculado e guardado o estado vocal; as próximas execuções reaproveitam o arquivo `.safetensors` local.
4. Depois que o checkpoint estiver no cache, a geração pode operar sem rede. Os perfis derivados ficam no cache do usuário e não são versionados.

O estado de voz é dado biométrico sensível: mantenha acesso à sua conta Windows e apague os arquivos em `voice_states` se quiser remover os perfis derivados. Não apague o arquivo de referência por meio do editor.

## Proteção do wheel mouse

Combos, spins e sliders dos módulos de interface só recebem alteração por roda quando estão com foco (selecionados). Sem foco, a roda é encaminhada ao painel rolável ancestral. Para alterar um valor, clique/focalize o controle; para percorrer o painel, mantenha o ponteiro sobre os controles e role sem selecioná-los.

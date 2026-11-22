# Narração Uma voz / Várias vozes

## Usar Várias vozes

1. Abra **Narração → Várias vozes**.
2. Confirme em **Uma voz** que cada perfil local foi criado e autorizado. Os perfis aparecem nas caixas V1–V10; a tabela de falas permite escolher qualquer personagem configurado, mesmo se ele não aparecia no texto importado. Perfis configurados mas não usados não são carregados nem bloqueiam a geração.
3. Selecione **Equilibrado — Pure C INT8 · 6 threads** ou **Turbo — Pure C Mixer · 6 threads**. O nome técnico do perfil Turbo no código instalado é `qwen3-tts-purec-mixed`, ativado por `--quant-mixed-cpu` (Talker INT8 + Code Predictor INT4). O Equilibrado é `qwen3-tts-purec-int8`, ativado por `--int8`.
4. Cole ou importe um arquivo UTF-8 no formato `Berofel Script V1`, associe somente as vozes utilizadas e clique **Validar e visualizar**.
5. Clique **Gerar roteiro e inserir na timeline**. Se o projeto ainda não tiver caminho, salve-o quando solicitado. Os WAVs são criados um por fala, primeiro agrupados pelo perfil vocal e depois posicionados na ordem numerada com a pausa configurada (200 ms por padrão).
6. Selecione um bloco da timeline para abrir a fala na tabela. Edite apenas a coluna Texto e use **Regenerar somente esta fala**. O WAV aprovado permanece até a nova geração validar; os outros arquivos ficam intactos. As setas reordenam; **+ Fala** e **Remover** editam a sequência.
7. **Salvar WAV desta fala** copia o WAV individual. **Exportar WAV completo do roteiro** usa o mesmo grafo de áudio do exportador do editor. MP4 continua disponível pela exportação normal da timeline.

Exemplo:

```text
Berofel Script V1
[001 | V1 | João]
Você ouviu aquele barulho?
[002 | V2 | Ana]
Ouvi sim! Parece que veio da floresta.
```

Cabeçalhos repetidos, número duplicado, voz fora de V1–V10, texto sem cabeçalho e falas vazias são rejeitados antes de iniciar a IA. IDs das falas são independentes da numeração e persistem ao reorganizar. O parser foi exercitado com mais de 100 mil caracteres, 1.000 falas e 10 vozes. Uma fala muito longa é dividida em segmentos de até 800 caracteres nos limites de sentença/palavra e remontada em um WAV lógico; sem um espaço seguro para dividir, a fala falha explicitamente em vez de cortar uma palavra.

Ao substituir uma fala por outra de duração diferente, somente as falas seguintes do mesmo roteiro são deslocadas. Música, clipes independentes e outros roteiros na mesma camada não se movem. Se o clipe ou uma fala seguinte estiver numa camada bloqueada, a regeneração é recusada antes da síntese; o estado é verificado novamente ao concluir para proteger alterações feitas enquanto o Qwen trabalha. Edição, remoção ou reordenação do roteiro também é recusada quando uma camada dele estiver bloqueada, e a tabela volta ao último estado salvo.

## Persistência e retomada

O projeto guarda os metadados do roteiro em JSON versionado. Áudios e checkpoint incremental ficam junto dos arquivos do projeto, em `*_arquivos/narracoes/roteiros/<id>/`. Em cancelamento, os WAVs já concluídos ficam preservados; se a regeneração individual for cancelada, o áudio aprovado anteriormente continua byte a byte intacto e associado à fala pendente. Ao reabrir o projeto, use **Retomar roteiro salvo**. O cache de cada fala considera texto, hash da referência autorizada, perfil, backend, threads e fingerprint do runtime/modelo; mudar só a posição não sintetiza novamente. A origem da voz permanece na pasta privada local de perfis.

## Limite técnico conhecido do Pure C

Os perfis Pure C em uso fixam um x-vector com `--load-voice` no início do servidor. A [API HTTP](https://github.com/gabriele-mastrapasqua/qwen3-tts/blob/main/docs/serving/api.md) diz que a clonagem é definida na inicialização e não há campo de clonagem por requisição. A documentação upstream mais recente de [CPU request batching](https://github.com/gabriele-mastrapasqua/qwen3-tts/blob/main/docs/serving/cpu-batching.md) confirma que cada slot aceita voz preset, mas uma voz customizada carregada é por servidor, compartilhada entre slots e não pode ser trocada por slot. A inspeção do [parser HTTP em `qwen_tts_server.c`](https://github.com/gabriele-mastrapasqua/qwen3-tts/blob/main/qwen_tts_server.c) confirma que o corpo só oferece `speaker`/`voice` como seletores e não aceita `ref_audio`, `xvector` ou `speaker_embedding`; a [estrutura de contexto em `qwen_tts.h`](https://github.com/gabriele-mastrapasqua/qwen3-tts/blob/main/qwen_tts.h) mantém um ponteiro `speaker_embedding` no contexto do servidor. Portanto a fila mantém uma única instância ativa, sintetiza falas consecutivas do mesmo perfil em lote e reinicia o servidor ao mudar para outro perfil. Isso evita recarregar por frase e evita duas cópias pesadas simultâneas, mas **ainda recarrega o modelo entre personagens com perfis diferentes**. Ligar `--batch-size` não resolve o condicionamento de várias vozes clonadas. O painel mostra esse aviso quando os personagens usam perfis diferentes. Essa limitação impede marcar o requisito de “modelo carregado uma única vez entre todas as vozes” como concluído; seria preciso ampliar o contrato e o estado por requisição no motor e compilar/testar um executável próprio para Windows.

Verificação do runtime Windows instalado em 2026-11-22: `qwen_tts.exe` (2.076.680 bytes; SHA-256 `3A5F89D923BFDBEA29327BD4111ECD651AFA3EF448B2643B6EA8AD63DD907D13`) mostra no `--help` um único `--load-voice <path>` para fixar o perfil ao iniciar; não há opção para fornecer ou selecionar o x-vector por solicitação HTTP. O binário continua sendo o runtime aprovado para síntese. Nesta máquina não foram encontrados `cl`, `gcc`, `clang`, `cmake` ou `ninja` disponíveis para compilar e validar uma extensão do servidor, portanto a troca de embedding sem recarga segue como trabalho do runtime, fora do adaptador Python atual.

Uma referência sem x-vector no cache exige uma execução curta do motor para extrair o embedding. Essa extração agora é serializada sob o mesmo lock do servidor e encerra primeiro qualquer sessão Pure C residente. Assim uma troca para perfil ainda não preparado não mantém o servidor anterior e o extrator carregados ao mesmo tempo. Depois da extração, o servidor do perfil selecionado volta a ser iniciado e reutilizado nas falas seguintes. Teste unitário verifica a ordem `parar servidor → extrair → iniciar servidor`; cache hit continua sem extração.

Teste de runtime offline desta alteração: comecei com o servidor INT8 aquecido usando o perfil autorizado já preparado; em seguida forcei um cache de x-vector vazio em diretório temporário para a mesma referência. O servidor antigo foi substituído, todos os quatro processos auxiliares observados iniciaram sem servidor residente, a extração levou 2,376 s e a carga do servidor final 2,953 s. O servidor terminou pronto; cache temporário removido. Isso valida a exclusão mútua e a sequência, mas não mede troca de identidade vocal.

Para um roteiro com perfis diferentes sem recarga entre personagens, o perfil **Original — Qwen3 Base** mantém o worker PyTorch e seus prompts de voz em memória (limite LRU atual de 64 prompts por sessão). É a alternativa de menor recarga, embora a inferência seja mais lenta que Pure C. O painel explica essa diferença quando Original está selecionado. A lógica está confirmada no código do worker persistente, mas a síntese real de várias identidades ainda precisa ser repetida quando houver perfis autorizados distintos.

Antes da camada de compatibilidade de áudio, uma tentativa real adicional do worker Original em duas IDs de perfil (mesma amostra autorizada, sem alegação de timbres distintos) não gerou a primeira fala após vários minutos e foi interrompida para liberar o CPU. A repetição após a correção está registrada abaixo.

Na repetição diagnóstica, o worker reportou que PyTorch foi importado, mas não saiu da importação de `qwen_tts` em 90 segundos; nenhum WAV foi gerado. Os módulos Python `torch`, `torchaudio`, `qwen_tts` e `imageio_ffmpeg` estão presentes. O `stderr` mostrou também que o executável `sox` não está no PATH, mas não houve evidência de que esse aviso seja a causa da demora. O worker agora envia as fases de importação/carga para o painel e encaminha exceções de inicialização, permitindo distinguir importação lenta, leitura dos pesos e erro explícito.

O import do pacote foi então repetido com uma camada local compatível com a API efetivamente usada pelo Qwen: caiu de mais de 90 s sem progresso para 6,42 s, e a matriz mel foi idêntica (`max_abs_diff=0`) à implementação `librosa` instalada para os quatro formatos de 80/128 bandas usados pelos encoders. Um smoke test offline pela interface, usando o perfil salvo e **Equilibrado — Pure C INT8**, gerou áudio de 4,32 s em 6,29 s do clique à inserção (RTF observado do fluxo da interface: 1,456), reproduziu/buscou no player e exportou WAV não silencioso e MP4 com áudio/vídeo. Esse ensaio isolado comprova o perfil Pure C INT8, não o Original; o teste completo do Original está registrado abaixo.

#### Backend Original Qwen após a correção do import

Também executei o caminho completo na interface com `qwen3-tts-local`, em uma sessão nova/offline, usando o único perfil pessoal autorizado já salvo. O worker carregou o Qwen Base 0.6B e o prompt vocal persistido (`prompt_cache_hit=true`, `model_load_count=1`); o WAV mono 24 kHz teve 10,80 s e sinal não silencioso. Do clique à inserção na timeline foram 62,83 s (RTF frio do fluxo UI 5,817, incluindo inicialização/carga do modelo). Player, busca, exportação WAV 48 kHz, MP4 com vídeo/áudio e salvar/reabrir o projeto passaram. Esse resultado valida o Original dentro do editor como fallback, mas não é uma otimização de velocidade: o Pure C INT8 permanece a rota recomendada para narração rápida. A medição é uma execução, feita em `QT_QPA_PLATFORM=offscreen`, sem avaliação por alto-falantes.

#### Reuso do Original entre lotes de perfil

Reexecutei `scripts/validar_multivoice_original_real.py` offline, em um processo novo, com duas IDs de perfil apontando para a mesma referência autorizada. As duas falas geraram WAVs válidos (8,32 s e 8,16 s), usaram o mesmo PID de worker, reportaram `model_load_count=1`, e a segunda fala atingiu o cache persistente do prompt (`false`/`true` para miss/hit). O carregamento inicial mediu 6,46 s; inferência das falas, 42,63 s e 41,86 s (RTF 5,12 e 5,13). Áudios e caches temporários foram removidos. Isso comprova o reaproveitamento de uma sessão Original entre grupos, mas **não** comprova identidades vocais diferentes: ainda falta um segundo perfil autorizado com gravação distinta.

### Validar duas referências autorizadas diferentes

Quando houver pelo menos dois perfis locais autorizados, liste os IDs com `python scripts/validar_multivoice_distinct_profiles.py --list-profiles` e execute o smoke de backend offline:

```powershell
python scripts/validar_multivoice_distinct_profiles.py `
  --confirm-own-or-authorized-voice `
  --profile-v1 ID_DO_PERFIL_V1 `
  --profile-v2 ID_DO_PERFIL_V2 `
  --engine qwen3-tts-purec-int8
```

Use `qwen3-tts-purec-mixed` para o Turbo Pure C Mixer ou `qwen3-tts-local` para o Original. O script rejeita IDs iguais, referências duplicadas ou perfis sem autorização; mantém WAVs e caches em diretório temporário e retorna métricas sem nomes ou caminhos pessoais. `tests/test_multivoice_distinct_validation.py` cobre a seleção segura sem carregar o modelo. Uma gravação diferente não prova, sozinha, que a pessoa que fala é diferente; escolha perfis de locutores distintos e autorizados e avalie as saídas por escuta. O smoke real ainda aguarda a gravação do segundo perfil autorizado.

### Diagnosticar troca Pure C sem usar gravações pessoais

O smoke `scripts/validar_troca_perfil_multivozes_sintetico.py` cria duas referências artificiais localmente, gera uma fala por personagem, troca o perfil entre lotes e apaga WAVs/caches temporários. Ele mede a implementação do servidor, não a qualidade da clonagem. Foi executado uma vez por perfil nesta sessão, em seis threads, sem downloads:

| Perfil | Tempo total | Duração WAV V1/V2 | Preparação V1/V2 | Carga servidor V1/V2 | Geração V1/V2 | Primeiro áudio V1/V2 |
|---|---:|---:|---:|---:|---:|---:|
| Pure C INT8 | 15,588 s | 4,56 / 4,96 s | 1,456 / 1,559 s | 2,460 / 2,061 s | 3,725 / 4,042 s | 0,493 / 0,487 s |
| Pure C Mixer | 14,464 s | 4,48 / 4,80 s | 1,456 / 1,559 s | 2,150 / 1,969 s | 3,389 / 3,663 s | 0,462 / 0,490 s |

Os dois WAVs passaram pela validação de sinal não silencioso e a fila processou V1 antes de V2. As medições mostram que o servidor Pure C é reiniciado/recarregado ao mudar de perfil; o tempo total inclui esse custo. Uma execução curta e sintética não permite concluir fidelidade, naturalidade, português falado com qualidade nem desempenho no Ryzen 7 5700G. Para validar identidade vocal, use o smoke de duas referências autorizadas acima.

Reprodução:

```powershell
python scripts/validar_troca_perfil_multivozes_sintetico.py --engine qwen3-tts-purec-int8
python scripts/validar_troca_perfil_multivozes_sintetico.py --engine qwen3-tts-purec-mixed
```

## Validação

O fluxo real pela janela do editor foi executado em roteiro de 100 falas no Windows, separadamente com `qwen3-tts-purec-int8` e `qwen3-tts-purec-mixed`, seis threads, saída WAV independente, inserção na timeline, salvamento/reabertura do projeto e exportação WAV. A exportação MP4 também foi validada no projeto de 100 falas Mixed. Os textos de benchmark foram `Fala NNN.` e as V1/V2/V3 foram associadas ao mesmo perfil vocal local autorizado disponível no computador de teste. Por isso, as execuções validam síntese em lote, arquivos, ordem, projeto e exportação, mas **não validam identidade de três vozes diferentes nem troca/reload do modelo entre perfis**. O computador não permitiu ler o modelo da CPU via CIM; os valores abaixo não são atribuídos ao Ryzen 7 5700G.

| Perfil real | Falas/WAVs/clips | Áudio total | Tempo de fila | Tempo de inferência somado | RTF inferência | Primeiro WAV | RSS máximo editor+servidor | RAM usada no sistema | Exportações |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Pure C INT8, 6 threads | 100/100/100 | 281,0 s | 254,4 s | 246,6 s | 0,878 | 7,4 s | 3,66 GiB | 9,22 GiB | WAV 86.642.022 bytes |
| Pure C Mixed, 6 threads | 100/100/100 | 286,1 s | 241,0 s | 235,0 s | 0,821 | 5,3 s | 3,63 GiB | 9,09 GiB | WAV 88.093.542 bytes; MP4 6.488.768 bytes |

RTF é o tempo de inferência somado dividido pela duração de áudio; menor que 1 significa que, nesta execução, o motor gerou mais áudio do que o tempo gasto em inferência. O tempo até o primeiro WAV inclui a carga/preparação inicial observada pela aplicação. Esses resultados curtos e repetidos não garantem a mesma velocidade para outros textos, perfis ou computadores. Amostras e projetos temporários foram removidos após validação; nenhum áudio pessoal foi incluído no repositório.

Também foram executados pela interface: três falas reais em cada perfil, exportação WAV nos dois e MP4 no Mixed; edição/regeneração de uma fala com preservação de hashes dos outros dois WAVs, preservação do antigo até validar o novo, e Undo/Redo. Os testes automatizados cobrem fila agrupada com dois perfis simulados, cache, checkpoint, parser de 100.000+ caracteres/1.000 falas, edição individual, WAV segmentado e integração Qt. A simulação testa a lógica da alternância; não substitui a medição de troca real entre perfis. Para certificar vozes distintas, repetir quando houver ao menos três perfis autorizados locais disponíveis e, para cumprir o requisito de manter uma única carga entre personagens, será necessário um runtime com condicionamento por requisição ou troca de x-vector em memória.

## Backup e restauração

Antes da implementação foi criado o tag imutável `backup/qwen3-turbo-pre-multivoice-20261122`. O bundle de recuperação da base está em `C:\Users\Berofel\Desktop\BerofelStudio_codigo_base_alpha\BerofelStudio_Qwen3Turbo_PreMultivoice_20261122.bundle`; o bundle com esta implementação e o tag original está em `C:\Users\Berofel\Desktop\BerofelStudio_codigo_base_alpha\BerofelStudio_Qwen3MultiVoice_20261122.bundle`. Ambos são verificáveis com `git bundle verify <caminho>`. Para abrir uma cópia da implementação, execute `git clone --branch feat/qwen3-multivoice-narration <caminho-do-bundle> <pasta-nova>`. Para inspecionar a base anterior, na cópia execute `git switch --detach backup/qwen3-turbo-pre-multivoice-20261122`. Perfis, gravações, modelos e configurações do usuário estão fora da árvore Git; não foram editados nem copiados para esses bundles.

Bundle atualizado após o diagnóstico de troca de perfil: `C:\Users\Berofel\Desktop\BerofelStudio_codigo_base_alpha\BerofelStudio_Qwen3MultiVoice_20261122_after_profile_switch.bundle`. O arquivo inclui o HEAD da branch e a referência de backup acima; pode ser validado com `git bundle verify` e sua integridade confirmada pelo SHA-256 reportado na entrega.

### Diagnóstico offline reproduzível com trechos da voz autorizada

Para medir a troca real do servidor sem aguardar uma segunda gravação, `scripts/validar_troca_perfis_trechos_voz_autorizada.py` cria dois perfis efêmeros a partir de janelas diferentes de uma referência autorizada. Ele exige confirmação explícita, trabalha offline, valida WAV não silencioso, registra PID/carga/preparação/geração e remove os perfis, arquivos e caches temporários ao terminar. Repetição:

```powershell
& "$env:LOCALAPPDATA\BFS\venv\Scripts\python.exe" `
  scripts/validar_troca_perfis_trechos_voz_autorizada.py `
  --confirm-own-or-authorized-voice `
  --engine qwen3-tts-purec-int8 `
  --engine qwen3-tts-purec-mixed
```

Execução offline nesta máquina: INT8 terminou em 14,489 s e Mixer em 10,566 s, com dois WAVs válidos por backend. Os PIDs diferiram entre V1 e V2 e houve cerca de 2,4–2,7 s de carga do servidor em cada lote: a troca Pure C reinicia/recarrega o modelo, mesmo com prompt-cache hit no Mixer. A geração medida foi 3,137/3,589 s no INT8 e 2,738/2,460 s no Mixed. Os dois condicionamentos são trechos diferentes do **mesmo locutor** (`speaker_identity_distinct=false`); isso valida o caminho operacional de troca e recarga, não diferenciação de identidade, fidelidade a duas pessoas ou qualidade subjetiva. A validação com o segundo perfil vocal autorizado que o usuário está preparando continua pendente. Foram adicionados testes de seleção dos segmentos, cobrindo recusa de silêncio e gravação curta.

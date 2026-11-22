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

## Persistência e retomada

O projeto guarda os metadados do roteiro em JSON versionado. Áudios e checkpoint incremental ficam junto dos arquivos do projeto, em `*_arquivos/narracoes/roteiros/<id>/`. Em cancelamento, os WAVs já concluídos ficam preservados; ao reabrir o projeto, use **Retomar roteiro salvo**. O cache de cada fala considera texto, hash da referência autorizada, perfil, backend, threads e fingerprint do runtime/modelo; mudar só a posição não sintetiza novamente. A origem da voz permanece na pasta privada local de perfis.

## Limite técnico conhecido do Pure C

Os perfis Pure C em uso fixam um x-vector com `--load-voice` no início do servidor. A [API HTTP](https://github.com/gabriele-mastrapasqua/qwen3-tts/blob/main/docs/serving/api.md) diz que a clonagem é definida na inicialização e não há campo de clonagem por requisição. A documentação upstream mais recente de [CPU request batching](https://github.com/gabriele-mastrapasqua/qwen3-tts/blob/main/docs/serving/cpu-batching.md) confirma que cada slot aceita voz preset, mas uma voz customizada carregada é por servidor, compartilhada entre slots e não pode ser trocada por slot. Portanto a fila mantém uma única instância ativa, sintetiza falas consecutivas do mesmo perfil em lote e reinicia o servidor ao mudar para outro perfil. Isso evita recarregar por frase e evita duas cópias pesadas simultâneas, mas **ainda recarrega o modelo entre personagens com perfis diferentes**. Ligar `--batch-size` não resolve o condicionamento de várias vozes clonadas. O painel mostra esse aviso quando os personagens usam perfis diferentes. Essa limitação impede marcar o requisito de “modelo carregado uma única vez entre todas as vozes” como concluído; seria preciso implementar e validar suporte a x-vector por requisição no motor, o que não existe no executável Pure C instalado.

Para um roteiro com perfis diferentes sem recarga entre personagens, o perfil **Original — Qwen3 Base** mantém o worker PyTorch e seus prompts de voz em memória (limite LRU atual de 64 prompts por sessão). É a alternativa de menor recarga, embora a inferência seja mais lenta que Pure C. O painel explica essa diferença quando Original está selecionado. A lógica está confirmada no código do worker persistente, mas a síntese real de várias identidades ainda precisa ser repetida quando houver perfis autorizados distintos.

Uma tentativa real adicional do worker Original em duas IDs de perfil (mesma amostra autorizada, portanto sem alegação de timbres distintos) não gerou a primeira fala após vários minutos e foi interrompida para liberar o CPU. Ela não conta como teste de geração concluído. O script `scripts/validar_multivoice_original_real.py` reproduz essa verificação offline com timeout máximo de 10 minutos; o fluxo Original deve ser tratado como não validado para produção multivozes até terminar e produzir WAVs nesse ambiente.

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

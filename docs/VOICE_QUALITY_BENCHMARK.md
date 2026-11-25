# Qualidade e benchmark vocal — estado da etapa

O ASR usado no fluxo BVI é **Parakeet TDT v3 ONNX INT8 em CPU**, junto ao Silero VAD local. Faster-Whisper não faz parte desta rota e não foi usado nos resultados abaixo.

## Execução exploratória real — 25/11/2026

Ambiente Windows do aplicativo, Ryzen 7 5700G (8C/16T), 16 GB RAM, execução CPU local; referência vocal autorizada local de 3 s; síntese Pure C 0.6B, seis threads; um único texto PT-BR curto por backend. Foram usadas saídas WAV novas, sem cache de áudio. A checagem textual dos WAVs foi feita pelo Parakeet TDT v3 ONNX INT8/CPU já instalado. Os arquivos temporários foram removidos após a análise.

| Backend | Tempo total | Duração WAV | RTF total | Inicialização/modelo | Resultado Parakeet |
|---|---:|---:|---:|---:|---|
| Turbo Mixed CPU (`qwen3-tts-purec-mixed`) | 13,07 s | 9,28 s | 1,408 | 2,682 s | WER-like 0,056; CER-like 0,021; lacuna final 0,0 s |
| Equilibrado INT8 (`qwen3-tts-purec-int8`) | 10,94 s | 9,04 s | 1,210 | 2,773 s | WER-like 0,056; CER-like 0,021; lacuna final 0,0 s |

Cada configuração foi executada uma vez, em sequência; a segunda reutilizou o cache do perfil, mas reiniciou o servidor ao trocar precisão. É uma medição exploratória de uma frase curta, não comparação científica nem p50/p95. WER/CER-like vieram do mesmo ASR local e não são ground truth; ambos os resultados exigem revisão auditiva. Não houve avaliação auditiva cega, pontuação de identidade, medição de RAM de pico, nem teste de narração longa. Logo, esses números não demonstram superioridade geral de INT8 sobre Mixed.

Também foi concluída uma chamada real de transcrição de referência via Parakeet CPU + Silero + FFmpeg: trecho selecionado de 3 s, seis palavras reconhecidas, 7,56 s de execução. A interface do adaptador não expõe confiança nessa chamada. Esse teste curto confirma o caminho de execução, não a precisão do ASR em conteúdo geral.

### Investigação de expressividade no Pure C local

Com a mesma referência local autorizada, mesmo texto-alvo, Qwen 0.6B Base, INT8 e seis threads, o binário foi exercitado em duas rotas. A transcrição da janela de referência foi obtida pelo Parakeet TDT v3 ONNX INT8/CPU. O modo CLI `--emo-ref` + `--emo-ref-text` aceitou os argumentos e gravou WAV mono 24 kHz de 4,32 s em 11,564 s (RTF total exploratório 2,677). A baseline CLI sem esses argumentos gravou WAV válido de 4,24 s em 5,222 s (RTF total 1,231). Uma execução por condição, sem escuta; não prova que a interpretação emocional melhorou. O custo sugere carga/condicionamento one-shot e não justifica substituir a rota persistente normal.

Separadamente, duas requisições ao servidor residente usaram seed 42; a segunda incluía `emotion: joy`. Ambas tiveram status HTTP 200, duração 3,76 s e o mesmo SHA-256 (`2fbcd01b5c85a62f…e825f2ed5`). Nesta build instalada o campo não alterou a saída. Não se deve expor emoção neural via API nesta versão como se tivesse efeito. Upstream pode ter evoluído depois da build local; o SHA executável e a incompatibilidade estão registrados em `VOICE_BACKEND_CAPABILITIES.md`.

### Integração experimental do estilo por exemplo — serviço real do editor

Em 25/11/2026, duas chamadas sequenciais ao serviço canônico de narração do editor usaram o perfil vocal autorizado local, o mesmo texto PT-BR, Pure C INT8 e seis threads. A primeira usou a rota padrão; a segunda reiniciou o servidor com `--emo-ref` e `--emo-ref-text`, usando a transcrição já revisada obtida com Parakeet TDT v3 ONNX INT8/CPU. Não houve reprodução automática. Os dois WAVs foram válidos, novos e tiveram hashes diferentes.

| Rota | Tempo de parede | Carga/reinício reportado | Duração WAV | Cache do x-vector |
|---|---:|---:|---:|---|
| Padrão | 8,60 s | 3,222 s | 3,44 s | miss |
| Estilo por exemplo | 19,927 s | 9,670 s | 6,48 s | hit |

É uma única comparação exploratória; o servidor carregado com o exemplo quase dobrou o tempo de parede e gerou WAV mais longo. O hash diferente prova apenas que a configuração alterou a saída. Não prova emoção identificável, naturalidade superior ou identidade preservada. Não houve escuta ou medição de RAM. Por isso, a caixa é opcional, fica desligada por padrão e sua seleção pode tornar a geração substancialmente mais lenta. O encerramento do worker foi feito antes de remover o diretório temporário de cache/log.

O fluxo foi ainda executado pela interface Qt real do editor, em modo offscreen, com um perfil autorizado, INT8 e seis threads. Na repetição mais recente, o WAV final tinha 6,88 s e o teste levou 24,692 s; o painel concluiu sem erros, `server_status()` confirmou `emotion_by_example=true`, e os players de timeline e narração permaneceram parados. Este teste comprova integração funcional e silêncio automático, não a qualidade perceptiva do estilo.

O cache padrão de perfil sob `%LOCALAPPDATA%\\BFS` não era gravável pelo processo Codex sandbox nesta sessão. Para concluir a inferência sem alterar ACLs, os testes apontaram `BEROFEL_QWEN3_PUREC_PROFILE_CACHE` e logs para uma pasta temporária gravável. Isso é uma restrição do processo sandbox, não uma falha observada do aplicativo executado normalmente pelo usuário.

## Procedimento reproduzível para benchmark comparativo

## Procedimento reproduzível pendente

1. Usar o mesmo texto, perfil autorizado, configuração de seis threads, máquina sem carga concorrente e WAV sem cache.
2. Medir separadamente inicialização do worker, preparação do condicionamento, inferência e finalização do WAV com relógio monotônico.
3. Calcular `RTF = tempo total / duração real do WAV`; reportar RTF inferência e RTF completo.
4. Repetir Turbo Mixed CPU e Equilibrado INT8 em ordem alternada; registrar mediana e p95, RAM máxima e tamanho/duração WAV.
5. Para texto, usar Parakeet local para rascunho comparativo, corrigir manualmente a referência e reportar WER/CER. Transcrição automática isolada não é ground truth.
6. Para identidade e naturalidade, comparar clipes com loudness alinhado em teste auditivo cego. Não substituir avaliação humana por similaridade de x-vector.

Os testes unitários do pacote não comprovam qualidade acústica. Após integrar a detecção de capacidade, a suíte completa foi executada no ambiente virtual instalado do app com `python -m unittest discover -s tests -q`: **580 testes passaram e 6 foram ignorados**, em 66,503 s. Os seis skips permanecem skips e não são contados como aprovados. `pytest` não está instalado no ambiente virtual, então não foi executado nem instalado; o projeto usa a suíte unittest existente. A integração Qt real de estilo foi ativada separadamente via `BEROFEL_RUN_PUREC_GUI_INTEGRATION=1` e passou em 24,692 s.


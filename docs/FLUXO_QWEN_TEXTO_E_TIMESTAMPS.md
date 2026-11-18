# Fluxo textual de edição com Qwen

## Papel de cada etapa

1. **Faster-Whisper** transcreve o áudio e registra cada palavra com ID e tempos de início/fim na mídia de origem.
2. **Qwen** recebe somente pares `{id, text}` da transcrição selecionada. Não recebe vídeo, áudio, caminhos da mídia nem timestamps. Para respeitar o limite de contexto do modelo, o texto completo é enviado em lotes ordenados com sobreposição nas bordas.
3. **Qwen** identifica vícios claros, falsos começos e repetições imediatamente redundantes. Preserva negações, números, nomes, ênfase e informação nova. Não reescreve o roteiro e não decide timestamps.
4. **O editor** valida os IDs e localiza as palavras nos tempos do Whisper. Ele cria sugestões para revisão; nenhuma alteração é aplicada à timeline até a aprovação do usuário.
5. **O motor de timeline** aplica os intervalos aprovados como cortes não destrutivos e reversíveis. Não é necessária outra IA para editar a timeline.

## Fórmula de tempo

Para as palavras removidas `w₁…wₙ`, o Whisper fornece início/fim em segundos absolutos da fonte. O pipeline já normaliza esses valores para segundos relativos ao início de fonte do clipe:

```text
a = max(0, início(w₁) relativo ao clipe − 0,025 s)
b = min(duração da fonte do clipe, fim(wₙ) relativo ao clipe + 0,025 s)
```

O editor só aceita IDs existentes e contínuos, um intervalo entre 0,04 e 6 segundos, e rejeita candidatos que incluam negações ou números protegidos. Os limites de 25 ms evitam sobras de fonema sem cortar pausas longas.

Os valores `a` e `b` ficam no relógio relativo da fonte. Ao aplicar o corte, o motor converte para o relógio de reprodução pela velocidade do clipe (`a/speed`, `b/speed`) e mapeia novamente para a fonte. Assim a posição permanece correta em clipes acelerados ou lentos, sem mover o arquivo original.

## Execução eficiente e retomada

- O Qwen inicia uma vez por clipe em vez de uma vez por lote de áudio do Whisper; quando `llama-server` está instalado, o modelo fica carregado enquanto todos os lotes textuais são processados. O servidor escuta apenas em `127.0.0.1`, usa uma chave temporária e a instalação antiga continua com fallback para `llama-cli`.
- As requisições usam temperatura 0 e seed 42 nos dois transportes. O `llama-server` também reaproveita o prefixo comum. A documentação do llama.cpp alerta que `cache_prompt` pode produzir resultados não idênticos por diferenças no tamanho de lote; por isso propostas da IA sempre exigem revisão humana, mesmo com seed fixa.
- Dentro do worker, o texto é dividido pelo contexto e preserva sobreposição para analisar frases nas bordas.
- Cada lote Qwen concluído é salvo no cache do estágio. Se uma chamada posterior falhar ou expirar, a próxima execução reutiliza os lotes prontos.
- O prompt pede até oito grupos por lote, com saída JSON curta e 320 tokens máximos. A transcrição e as decisões Silero/Whisper já concluídas permanecem disponíveis mesmo se o Qwen falhar.
- Silero continua mais rápido por ser uma detecção acústica de fala/silêncio. Qwen faz inferência linguística local; lotes, cache, contexto reutilizado e saída curta reduzem trabalho, mas não tornam inferência semântica equivalente em custo ao VAD.

O prompt versionado está em `berofel/services/ai_worker.py`; o mapeamento e cache estão em `berofel/services/ai_pipeline.py`. O servidor local segue os endpoints `/health` e `/completion` documentados pelo [projeto oficial llama.cpp](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).

# Clipador Inteligente

O Clipador é uma ferramenta opcional de descoberta e revisão de trechos. Ele combina a transcrição Faster-Whisper já salva no projeto com medidas acústicas calculadas a partir da mídia-fonte. As sugestões são não destrutivas: nada é cortado ou inserido sem a seleção explícita do usuário.

## Usar

1. Importe o vídeo/áudio e obtenha sua transcrição pela aba **Ações IA**. O Clipador não inicia uma transcrição nova.
2. Selecione os blocos desejados e abra **Ações IA → Clipador Inteligente**.
3. Configure duração mínima/máxima, quantidade de sugestões e sensibilidade para eventos de energia; clique **Analisar**.
4. Revise texto, evidências e alertas. Use **Prévia** para ouvir no monitor do editor. Os limites de entrada/saída podem ser ajustados para bordas de palavras transcritas.
5. Marque manualmente os candidatos e use **Adicionar marcados à timeline**. Cada trecho vira um bloco ligado à mídia-fonte; a fonte não é modificada e a inserção pode ser desfeita com Undo.
6. **Marcar eventos de áudio** cria marcadores na timeline para inspeção; também é uma ação explícita e reversível.

## Sinais, timestamps e custo

- O serviço recebe as palavras/timestamps existentes e usa pistas textuais simples de começo/fim de frase, perguntas e frases de gancho. Não reexecuta Whisper nem Qwen. A versão atual não infere semântica, diarização, emoções ou potencial de viralização; a pontuação é um ranking editorial heurístico de 0–100, não uma probabilidade.
- A forma de onda visual existente guarda picos por pixel/intervalo para desenhar a timeline, não RMS adequado para comparação de loudness. Por isso, quando há áudio, o Clipador decodifica a faixa de áudio da fonte em mono float PCM 16 kHz, frames de 20 ms, em streaming e com FFmpeg limitado a uma thread. Calcula RMS, pico e fração de clipping; alinha eventos de energia com os intervalos de fala já transcritos. Não renderiza vídeo nem mantém todo o áudio na memória.
- Os tempos dos candidatos e eventos são segundos absolutos na mídia-fonte. A prévia converte para o intervalo local do clipe selecionado; os marcadores convertem para tempo de timeline considerando velocidade. Trechos e marcadores não alteram os timestamps da fonte.
- Se não houver áudio decodificável, ainda pode apresentar candidatos baseados em texto, com aviso e sem pontuação acústica. Sem transcrição salva, não decodifica a mídia e informa que a transcrição deve ser criada primeiro.
- Cache de características PCM e resultados fica em `%LOCALAPPDATA%\BFS\cache\clipper` (ou `BEROFEL_CLIPPER_CACHE`). Chaves incorporam identidade da fonte, in/out, palavras, opções e versão do algoritmo. A poda periódica limita os `.npz` gerados ao padrão de 512 MiB configurável por `BEROFEL_CLIPPER_CACHE_MAX_MB`; apenas artefatos identificados do cache podem ser removidos. Apagar o cache só causa recálculo.
- O trabalho usa a fila de processamento existente, oferece cancelamento e mantém a timeline acessível. O resultado informa tempo decorrido, cache, duração decodificada e RSS do processo quando `psutil` está disponível; isso não é uma medição de CPU dedicada.

## Limites e segurança

A referência ZIP fornecida inclui especificação e código de extração/ranking acústico, reutilizados com testes. A interface antiga não é um motor de corte automático. As decisões de seleção seguem manuais; não há promessa de qualidade semântica em linguagem natural nem classificação Qwen neste primeiro incremento. Fontes sem palavras, faixas de áudio ausentes e falhas do FFmpeg recebem estado/alerta, não alteram arquivos do usuário. A extração opera na primeira faixa de áudio (`0:a:0`); seleção manual de idioma/faixa não está implementada.

O conjunto atual de evidências inclui testes com áudio sintético e fontes temporárias. Uma gravação longa/real, precisão editorial e desempenho em computadores de especificações variadas ainda precisam de validação prática.

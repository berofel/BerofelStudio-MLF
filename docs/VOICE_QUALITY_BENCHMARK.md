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

O cache padrão de perfil sob `%LOCALAPPDATA%\\BFS` não era gravável pelo processo Codex sandbox nesta sessão. Para concluir a inferência sem alterar ACLs, os testes apontaram `BEROFEL_QWEN3_PUREC_PROFILE_CACHE` e logs para uma pasta temporária gravável. Isso é uma restrição do processo sandbox, não uma falha observada do aplicativo executado normalmente pelo usuário.

## Procedimento reproduzível para benchmark comparativo

## Procedimento reproduzível pendente

1. Usar o mesmo texto, perfil autorizado, configuração de seis threads, máquina sem carga concorrente e WAV sem cache.
2. Medir separadamente inicialização do worker, preparação do condicionamento, inferência e finalização do WAV com relógio monotônico.
3. Calcular `RTF = tempo total / duração real do WAV`; reportar RTF inferência e RTF completo.
4. Repetir Turbo Mixed CPU e Equilibrado INT8 em ordem alternada; registrar mediana e p95, RAM máxima e tamanho/duração WAV.
5. Para texto, usar Parakeet local para rascunho comparativo, corrigir manualmente a referência e reportar WER/CER. Transcrição automática isolada não é ground truth.
6. Para identidade e naturalidade, comparar clipes com loudness alinhado em teste auditivo cego. Não substituir avaliação humana por similaridade de x-vector.

Os testes unitários do pacote não comprovam qualidade acústica. A suíte completa foi executada no ambiente virtual instalado do app com `python -m unittest discover -s tests -q`: **571 testes passaram e 5 foram ignorados**, em 66,026 s. Os cinco skips permanecem skips e não são contados como aprovados. A correção do ranqueamento acústico e o estimador YIN passaram também nos testes direcionados.


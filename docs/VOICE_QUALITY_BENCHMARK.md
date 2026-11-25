# Qualidade e benchmark vocal — estado da etapa

Nenhum benchmark end-to-end foi produzido nesta sessão. O ambiente não possui as dependências Python necessárias para ONNX/Parakeet, processamento NumPy/SciPy ou GUI, e não foi iniciada síntese real. Não declarar tempo, RTF, RAM, WER, similaridade de locutor ou preferência auditiva como medidos.

## Procedimento reproduzível pendente

1. Usar o mesmo texto, perfil autorizado, configuração de seis threads, máquina sem carga concorrente e WAV sem cache.
2. Medir separadamente inicialização do worker, preparação do condicionamento, inferência e finalização do WAV com relógio monotônico.
3. Calcular `RTF = tempo total / duração real do WAV`; reportar RTF inferência e RTF completo.
4. Repetir Turbo Mixed CPU e Equilibrado INT8 em ordem alternada; registrar mediana e p95, RAM máxima e tamanho/duração WAV.
5. Para texto, usar Parakeet local para rascunho comparativo, corrigir manualmente a referência e reportar WER/CER. Transcrição automática isolada não é ground truth.
6. Para identidade e naturalidade, comparar clipes com loudness alinhado em teste auditivo cego. Não substituir avaliação humana por similaridade de x-vector.

Os 11 testes do novo pacote são unitários/offline; a qualidade acústica não foi testada por eles. A suíte do editor executou 438 testes nesta sessão, com 58 erros relacionados a dependências ausentes e 119 testes ignorados. Consulte `VOICE_INTELLIGENCE_2_0.md` para o inventário ambiental.


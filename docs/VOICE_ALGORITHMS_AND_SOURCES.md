# Algoritmos, fontes e procedência — Voice Intelligence

Referências consultadas em 25/11/2026. Branches `main` são mutáveis; o binário Pure C instalado não expõe seu commit-fonte, então a documentação upstream atual não é presumida idêntica ao runtime local.

| Técnica / componente | Fonte e versão | Licença observada | Uso local e evidência |
|---|---|---|---|
| Normalização textual PT-BR | Regras locais, versão `NORMALIZER_VERSION=2` | Código do projeto | `text_normalizer.py`; testes determinísticos; sem modelo |
| Seleção acústica de referência | Regras locais; VAD existente e FFmpeg instalado | Código do projeto / FFmpeg distribuído separadamente | `audio_reference.py`; shortlist VAD + PCM; ainda sem benchmark humano |
| ASR de verificação | NVIDIA Parakeet TDT 0.6B v3 e export ONNX INT8 do repositório `istupakov/parakeet-tdt-0.6b-v3-onnx`, revisão `8f23f0c03c8761650bdb5b40aaf3e40d2c15f1ce` | NVIDIA indica CC-BY-4.0; preservar atribuição/termos do modelo | Adaptador existente `parakeet_asr.py`; CPUExecutionProvider; não foi feita inferência nesta sessão |
| Pesos Qwen3-TTS 0.6B Base | Model card oficial Qwen | Apache-2.0 conforme model card | Peso local existente; não incluso no Git; síntese não executada |
| Runtime Qwen3-TTS Pure C | `gabriele-mastrapasqua/qwen3-tts`, branch main, consultada em 25/11/2026 | MIT no LICENSE do repositório | Código local não foi copiado nesta etapa; executável local identificado por hash e capacidade CLI |
| Avaliação textual | Distância de edição Levenshtein local | Código do projeto | WER/CER-like diagnóstico; sem pretensão de MOS/percepção |

Referências oficiais consultadas: [Qwen Pure C — receita de emoção 0.6B](https://github.com/gabriele-mastrapasqua/qwen3-tts/blob/main/docs/emotion-06b-recipe.md), [Qwen Pure C — clonagem](https://github.com/gabriele-mastrapasqua/qwen3-tts/blob/main/docs/voice-cloning.md), [licença MIT do runtime Pure C](https://github.com/gabriele-mastrapasqua/qwen3-tts/blob/main/LICENSE), [Qwen3-TTS 0.6B Base](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base), [NVIDIA Parakeet TDT v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3), [export ONNX INT8 e revisão](https://huggingface.co/potgieterdl/parakeet-tdt-0.6b-v3-onnx-int8).

Não foram copiados trechos desses repositórios para o novo módulo. Este inventário não substitui uma auditoria jurídica completa das dependências/binários de distribuição comercial; consultar `THIRD_PARTY_NOTICES.md` e os termos vigentes antes de publicar modelos ou instalador.


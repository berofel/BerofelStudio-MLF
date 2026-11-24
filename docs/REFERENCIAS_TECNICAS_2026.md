# Referências técnicas consultadas

Pesquisa de engenharia usada para orientar correções locais. Nenhum código externo foi copiado ou instalado nesta etapa.

## Clipador e edição automática

- **ClipsAI** segmenta com base na transcrição e em timestamps por palavra via WhisperX. A função de reenquadramento documentada depende de diarização Pyannote e token Hugging Face; por isso não foi introduzida como dependência obrigatória no fluxo local. Licença MIT. [README](https://github.com/ClipsAI/clipsai), [licença](https://github.com/ClipsAI/clipsai/blob/main/LICENSE).
- **AutoClip** oferece uma cadeia local de ingestão, seleção, reenquadramento e exportação, mas usa LLM como seletor opcional e não foi trazido como dependência. O projeto declara MIT; fontes Anton/Inter têm OFL e exigiriam notices se incorporadas. [README e licença](https://github.com/artbyjazi/autoclip).
- **VideoHighlighter** expõe razões e sinais de cena/áudio/transcrição para cada candidato, uma boa referência de depuração. O projeto é AGPL-3.0 (também oferece licença comercial); não copiamos código nem dependemos dele. [README/licença](https://github.com/Aseiel/VideoHighlighter).
- **Auto-Editor** separa segmentos ativos/inativos e permite combinar sinais de áudio, vídeo e texto. O repositório indica Unlicense; esta atualização não copiou código. [Licença](https://github.com/WyattBlue/auto-editor/blob/master/LICENSE).
- **PySceneDetect** oferece detectores de conteúdo/adaptativos, cache de estatísticas e amostragem de quadros configurável. O `frame_skip` acelera com perda de precisão e não pode ser combinado com `StatsManager`; não foi ativado automaticamente. Projeto BSD-3-Clause. [Documentação do SceneManager](https://www.scenedetect.com/docs/latest/api/scene_manager.html), [licença](https://github.com/Breakthrough/PySceneDetect/blob/main/LICENSE).
- O Clipador do Berofel já propõe janelas a partir de frases/timestamps, reutiliza palavras do projeto e guarda features acústicas em cache. Sua pontuação é heurística editorial, não previsão de viralização. Sem mídia humana anotada nesta sessão, não calibramos pesos nem afirmamos ganho de relevância.

## Timeline e estilos

- A documentação do Kdenlive trata projeto como ativos, timeline, cortes, composições, transições e marcadores persistidos em conjunto. Essa separação orienta manter o formato do projeto do Berofel e modificar somente `width/height` para proporção. Kdenlive/MLT é GPL; nenhum código foi copiado. [Formato do projeto](https://github.com/KDE/kdenlive/blob/master/dev-docs/fileformat.md).
- OpenCut anuncia MIT e elementos de legenda organizados junto à timeline; foi consultado somente como referência de UX. [Projeto](https://github.com/OpenCut-app/OpenCut).

## Narração Qwen3-TTS

- A API oficial do Qwen3-TTS Base aceita `ref_audio` e `ref_text`, ou um prompt retornado por `create_voice_clone_prompt`, reutilizado com `generate_voice_clone`. `x_vector_only_mode=True` não usa a transcrição/códigos de referência e, portanto, constitui caminho de condicionamento diferente. A documentação também esclarece que `non_streaming_mode=False` não significa streaming de geração real. [Implementação oficial](https://github.com/QwenLM/Qwen3-TTS/blob/main/qwen_tts/inference/qwen3_tts_model.py), [README](https://github.com/QwenLM/Qwen3-TTS).
- O backend oficial Python do Berofel constrói e cacheia `voice_clone_prompt` a partir do hash do áudio, texto, modelo e modo. O Pure C converte a referência em x-vector `.bin` via `--xvector-only`, com cache ligado ao hash/modelo. Nenhuma amostra autorizada foi sintetizada nesta rodada, então a divergência de gênero relatada ainda requer reprodução auditiva no computador do usuário.
- Verificação local em 24/11/2026: artefato `config.json` declara arquitetura `Qwen3TTSForConditionalGeneration`; os dois runtimes reportaram modelo presente e backend pronto. Ambiente oficial isolado reportou `qwen-tts 0.1.1`, `torch 2.15.0+cpu`, `transformers 4.57.3`, `numpy 2.5.5`, `soundfile 0.14.0`. O venv geral não contém `qwen-tts`/Transformers, como esperado, pois a IA reside em `BFS\qwen3_tts\venv`. Pure C oferece IDs `qwen3-tts-purec-mixed` e `qwen3-tts-purec-int8`, threads padrão 6, e também estava pronto. Não executamos geração real nem inspecionamos/alteramos as gravações pessoais.

## Limites do que foi alterado

Os 24 presets visuais são configurações locais dos campos que o renderer atual efetivamente serializa: família, tamanho, cores e contorno. Isso não implementa ainda fundo, sombra, alinhamento avançado ou animação por palavra. A biblioteca de transições expõe apenas os três estilos já suportados pelo motor (`dissolve`, `slide`, `zoom`); não apresenta os outros 29 como disponíveis.

# Auditoria da clonagem vocal — 24/11/2026

## Estado verificado

- O editor aponta para `Qwen/Qwen3-TTS-12Hz-0.6B-Base`; os pesos locais estão presentes.
- O ambiente isolado informa `qwen-tts 0.1.1`, `torch 2.15.0+cpu` e `transformers 4.57.3`.
- O worker prepara o perfil com `create_voice_clone_prompt(ref_audio, ref_text, x_vector_only_mode=False)` quando existe uma transcrição e chama `generate_voice_clone(..., voice_clone_prompt=prompt, language="Portuguese")`.
- Os perfis Pure C/native usam apenas x-vector. A interface bloqueia esses caminhos para PT-BR, pois não recebem o condicionamento texto+áudio.
- O Qwen recebe o áudio de referência e o texto da janela selecionada; não treina nem aprende permanentemente com a gravação.

## Achado no perfil salvo

O único perfil local autorizado analisado tem 6,06 s. A leitura Silero registrou fala entre 0,584–2,008 s e 3,624–5,816 s; o sinal ficou quase silencioso em 54,88% da duração. A janela selecionada foi o arquivo completo, com atividade vocal estimada em 60,27%. Por isso o editor apresentou aviso de amostra com muito silêncio.

O texto já salvo no perfil diverge do rascunho produzido pelo Faster-Whisper Base local para a janela exata. Como esse rascunho tem nomes próprios potencialmente mal reconhecidos, ele não é tomado como transcrição correta: o usuário precisa conferir o que foi realmente dito. O perfil permaneceu sem a marca de revisão, e a nova implementação bloqueia a síntese PT-BR até essa revisão.

## Limite da validação anterior

Um WAV de diagnóstico anterior foi gerado no modo `audio+transcript`, mas o fingerprint da referência usada não corresponde ao fingerprint do perfil atualmente salvo. Portanto, esse arquivo não comprova a clonagem da voz do perfil atual nem pode ser usado para declarar fidelidade, gênero percebido ou sotaque brasileiro.

## Comportamento do modelo e janela de referência

O serviço percorre a gravação toda em blocos para detectar atividade e selecionar uma janela de no máximo 30 s; não entrega uma gravação de uma hora inteira ao modelo como treino. Neste perfil curto, a política escolheu os 6,06 s completos porque eles contêm mais segundos totais de fala do que qualquer janela menor candidata. Isso preserva as duas regiões faladas e a transcrição integral, mas também mantém o intervalo quase silencioso entre elas.

A API oficial do Qwen confirma que `x_vector_only_mode=True` usa somente embedding de locutor e ignora texto/códigos de fala; em `False`, o modo ICL usa texto e códigos do áudio e exige `ref_text`. O README do projeto apresenta clonagem Base rápida a partir de amostra de 3 s; isso é suporte mínimo anunciado, não garantia de fidelidade para uma amostra ruidosa ou transcrição incorreta.

Referências oficiais:

- https://github.com/QwenLM/Qwen3-TTS/blob/main/qwen_tts/inference/qwen3_tts_model.py
- https://github.com/QwenLM/Qwen3-TTS

## Correções registradas

- A revisão do texto de referência agora é vinculada ao texto e ao arquivo selecionados. Editar qualquer um invalida a confirmação.
- O serviço canônico e a fila multivozes validam a revisão antes de chamar o backend ou iniciar a fila.
- A ordem dos sinais Qt foi corrigida para a atualização do painel não apagar imediatamente a confirmação recém-marcada.

Commit local: `567ec62496c4a4f332c090504807019f1a4039a7` (`fix: validate reviewed PT-BR voice clone references`).

## Validação automatizada e pendências

- Suíte completa: 497 executados, 492 aprovados, 5 ignorados.
- `compileall` e `git diff --check`: aprovados.
- Testes reais anteriores confirmaram geração de WAV com áudio no backend, porém não usaram o fingerprint do perfil que está atualmente salvo.
- A interface visível não estava disponível à automação gráfica desta sessão; os testes Qt foram offscreen.
- Falta confirmar humanamente a transcrição da janela e ouvir uma geração nova feita com esse perfil. Sem isso, não se declara clonagem fiel nem sotaque PT-BR validado.

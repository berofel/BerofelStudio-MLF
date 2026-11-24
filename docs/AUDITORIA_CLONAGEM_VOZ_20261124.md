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

## Limitação conhecida no upstream

O repositório oficial Qwen3-TTS contém o issue [#80 — Base model voice clone sometimes change speaker](https://github.com/QwenLM/Qwen3-TTS/issues/80). Relatos descrevem substituição ocasional da identidade, inclusive mudança do gênero percebido, mesmo usando clonagem Base. Um relato menciona 2 falhas em 10 tentativas no 1.7B Base; outro observa o mesmo tipo de problema em espanhol. Isso não prova que o 0.6B deste perfil necessariamente falhará, mas confirma que a síntese Base pode variar mesmo quando a integração envia corretamente o condicionamento.

O issue foi encerrado sem correção oficial. Há uma proposta em um projeto de terceiros que fixa seeds e escolhe nova geração pela frequência fundamental; ela não prova identidade vocal e pode rejeitar uma interpretação legítima com pitch diferente. Não foi copiada nem adotada. O próprio Qwen também tem issue [#341 sobre eco da cauda da referência no modo ICL](https://github.com/QwenLM/Qwen3-TTS/issues/341), outra razão para avaliar o áudio final auditivamente em vez de confiar só na presença de `ref_audio`/`ref_text` ou em embeddings não calibrados.

Referências oficiais:

- https://github.com/QwenLM/Qwen3-TTS/blob/main/qwen_tts/inference/qwen3_tts_model.py
- https://github.com/QwenLM/Qwen3-TTS
- https://github.com/QwenLM/Qwen3-TTS/issues/80
- https://github.com/QwenLM/Qwen3-TTS/issues/341

## Correções registradas

- A revisão do texto de referência agora é vinculada ao texto e ao arquivo selecionados. Editar qualquer um invalida a confirmação.
- O serviço canônico e a fila multivozes validam a revisão antes de chamar o backend ou iniciar a fila.
- A ordem dos sinais Qt foi corrigida para a atualização do painel não apagar imediatamente a confirmação recém-marcada.
- O padrão persistido do painel era Pure C INT8, que só carrega x-vector, incompatível com o condicionamento detalhado PT-BR. O padrão agora é Qwen3 Base Original; ao selecionar Português, a interface encaminha para esse backend e mantém os modos rápidos disponíveis para idiomas onde são aceitos.
- O worker agora valida que o prompt contém vetor de locutor, códigos do áudio, ICL ativo e o mesmo texto revisado. Se faltar qualquer parte, cancela em vez de produzir com uma voz substituta.
- A conversão da referência remove somente silêncio nas bordas da cópia temporária. O corte é aplicado ao áudio invertido para o fim do arquivo; a pausa entre frases permanece. A origem nunca é alterada e os caches antigos foram invalidados por versão.
- Foi reproduzido um defeito no primeiro filtro experimental de borda: `stop_periods=1` encerrava na primeira pausa interna e entregava apenas 1,23 s de uma referência de 6 s, descartando a segunda fala embora seu texto continuasse no `ref_text`. O filtro foi substituído por remoção simétrica das bordas com margem de 120 ms. Um teste com FFmpeg real agora verifica as duas falas e a pausa preservadas.

## Revalidação real após a correção

- O perfil salvo foi atualizado com a transcrição fornecida pelo usuário e permaneceu autorizado. O arquivo original não foi editado.
- Geração offline real com Qwen3 Base 0.6B, `audio+transcript`, ICL verificado: carregamento 6,53 s; preparação 0,43 s; síntese 45,98 s; áudio final 8,96 s, mono/24 kHz, sinal não silencioso.
- A janela original de 6 s foi condicionada a partir de uma cópia de 5,30 s após retirar somente as bordas silenciosas; as duas regiões de fala continuaram presentes.
- Faster-Whisper Base local detectou idioma `pt` e reconheceu integralmente a frase de teste. Isso verifica idioma/conteúdo, mas não distingue sotaque brasileiro de português europeu.
- O encoder de locutor do próprio Qwen calculou similaridade cosseno 0,9829 entre referência e geração corrigida. Gerações diagnósticas anteriores ficaram entre 0,9814 e 0,9832. Não há limiar calibrado neste projeto; esses valores não provam gênero percebido nem fidelidade auditiva e não devem ser usados como aprovação automática.
- Qwen3 Base aceita somente o idioma genérico `Portuguese`, sem um token PT-BR/PT-PT. Para obter pronúncia brasileira, o caminho atual usa ICL com gravação e transcrição brasileiras; o modelo não oferece garantia absoluta de sotaque. A UI informa essa limitação e não faz fallback para voz predefinida.

Commit local: `567ec62496c4a4f332c090504807019f1a4039a7` (`fix: validate reviewed PT-BR voice clone references`).

## Validação automatizada e pendências

- Testes direcionados após a correção: 29 do worker/referência, 14 de UI de narração e 7 de condicionamento/transcrição aprovados, incluindo FFmpeg real para duas frases separadas por pausa.
- A suíte completa e `compileall`/`git diff --check` ainda precisam ser executados após estes últimos ajustes.
- A interface visível não estava disponível à automação gráfica desta sessão; os testes Qt foram offscreen.
- O áudio atual foi gerado com o perfil e a transcrição revisados, e o backend confirmou o condicionamento completo. Falta avaliação auditiva humana para julgar semelhança percebida, identidade masculina e sotaque. Sem audição, não se declara fidelidade vocal ou sotaque PT-BR validados.

## Aplicativo em execução

Na inspeção de 24/11/2026, a janela visível estava executando pelo runtime empacotado em `%LOCALAPPDATA%/BerofelStudio/Python312/pythonw.exe`, iniciada às 09:50 (horário local). Os commits de correção desta branch foram criados depois, entre 10:19 e 10:32; portanto essa instância aberta não carregou as alterações atuais. O lançador de desenvolvimento `ABRIR_BEROFELSTUDIO.vbs` define `PYTHONPATH` para a pasta do workspace e chama `%LOCALAPPDATA%/BFS/venv/Scripts/pythonw.exe` com `scripts/abrir_com_log.py`, que encaminha para o código-fonte local.

Para testar a correção no código atual, feche o aplicativo antigo e abra `ABRIR_BEROFELSTUDIO.bat` na raiz deste workspace. Isso testa a fonte local, não a distribuição instalada. A janela anterior não foi encerrada pela auditoria.

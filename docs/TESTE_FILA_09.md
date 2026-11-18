# BerofelStudio 0.9 — roteiro de validação no Windows

## Importante sobre a referência antiga

O arquivo `Berofel_Studio_5_0_Coletor_Fontes_Fase1.zip` recebido contém **somente um coletor de código-fonte e configuração**, não contém os arquivos da interface antiga. Portanto, **a aparência do sistema antigo ainda não foi copiada**. Para uma adaptação fiel, execute nele `!_01_COLETAR_FONTES_BEROFEL.bat` no Windows e envie o ZIP `Berofel_Fontes_Fase1_*.zip` que aparecer na Área de Trabalho. Revise o material antes de compartilhar para não enviar segredos.

## Instalar e abrir

1. Faça backup dos seus `.berofel.json` e mídias e feche o editor.
2. Extraia **o pacote completo 0.9** em uma pasta nova, por exemplo `C:\BerofelStudio09`, sem misturá-lo com a Alpha.
3. Execute `instalar_dependencias.bat` se ainda faltar o ambiente; se já instalou as IAs, **não é necessário baixá-las novamente** enquanto o cache `%LOCALAPPDATA%` continuar preservado.
4. Execute `TESTAR_FILA_09.bat` e guarde a saída do terminal.
5. Execute `ABRIR_BEROFELSTUDIO.bat`.

## Teste rápido da edição combinada

1. Adicione vídeo à timeline e abra a aba fixa **⚙ Ações IA**.
2. Escolha `Um bloco`, `Vários`, `Faixa`, `Intervalo` ou `Projeto`, conforme desejado.
3. Clique no botão **Edição completa**; ele marca Silero, Whisper, Qwen e legendas. Você pode desmarcar qualquer uma ou selecionar livremente outras ações.
4. Verifique a mensagem **Fila automática** antes de clicar **▶ APLICAR EDIÇÃO**.
5. Confira a ordem no painel Batata Quente: **Silero → Whisper → Qwen**, com cache persistente; no modo de economia de áudio, o Whisper recebe apenas janelas de fala detectada, não um vídeo fisicamente recortado.
6. Ao abrir o diálogo de cortes, clique **✓ Selecionar TODOS** e confira o contador; depois use **Aplicar apenas os marcados**, **Pular cortes** ou **Cancelar**.
7. Se marcou legendas, confirme que aparecem como clipes editáveis **depois** dos cortes, com sincronização. Teste `Ctrl+Z`.
8. Enquanto o Whisper trabalha, tente arrastar/selecionar/aparar outros blocos e reproduzir a prévia. Não deve travar a UI. Se mudar o próprio bloco-alvo, o resultado desse job não será aplicado à edição alterada (o cache fica salvo).
9. Repita a ação sobre o mesmo trecho e observe o reaproveitamento do cache.
10. Marque **Narração** com texto livre já digitado na aba Pocket TTS e confirme que a etapa de síntese inicia depois das etapas anteriores.

## Limitações / segurança

- Cortes continuam **dependendo de aprovação**. `Selecionar TODOS` apenas marca; a aplicação é outro clique.
- Se a detecção de voz não for suficiente para seu conteúdo (música/gameplay), desmarque **Usar Silero para poupar tempo do Whisper** para transcrever tudo, mesmo mantendo cortes de silêncio disponíveis para revisão.
- A compactação ocorre dentro de cada bloco cortado. Ela **não faz ripple global automático entre todas as faixas**; isso evita deslocar narração, trilha sonora ou títulos que o usuário não selecionou.
- O cancelamento de uma fila interrompe o processo pesado, mas mantém o cache válido já concluído.
- O modo `Narração` em lote usa o texto livre do painel Pocket TTS, ou preenche a partir da transcrição quando o texto estiver vazio. Confirme a autorização para amostras de voz próprias.
- **Teste de interface em Windows e testes de IA real estão pendentes**. Os testes automáticos desta entrega usam modelos simulados para o fluxo, além dos testes FFmpeg dos módulos anteriores.
- O ZIP contém o código e os instaladores; os modelos e as dependências pesadas continuam sendo baixados durante a instalação.

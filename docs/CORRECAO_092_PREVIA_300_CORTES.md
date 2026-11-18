# BerofelStudio 0.9.2 — Prévia de muitos cortes / Windows 206

## Sintoma

Após a IA aprovar centenas de cortes, o botão **▶ Reproduzir timeline**
permanece em **Preparando prévia** ou mostra:

```
FileNotFoundError: [WinError 206] O nome do arquivo ou a extensão é muito grande
```

O arquivo do usuário não precisa ter nome grande: o problema surge quando o
programa passa centenas de entradas `-i` e respectivos caminhos de origem a
um único processo FFmpeg, ultrapassando o limite da linha de comando do Windows.
O grafo de filtros já era salvo num arquivo, mas **a lista de entradas continuava
no comando**. A geração repetida dos metadados também fazia o preparo demorar.

## Mudanças

- Prévia usa a janela atual da timeline (até ~30 s), ajustada ao número real
  de clipes sobrepostos e ao limite de caracteres; não recompõe tudo ao tocar.
- Próxima janela é preparada antecipadamente, com decodificadores em pipes.
  **Não gera um MP4 inteiro antes de reproduzir**; mantém o cursor absoluto.
- Se a próxima janela demorar, o último quadro permanece visível até o início
  do próximo trecho. Uma mensagem e um timeout impedem espera infinita.
- Um vídeo usado em centenas de blocos tem metadados consultados só uma vez
  por versão de arquivo, evitando centenas de FFprobe redundantes.
- Exportação de projetos extensos também é dividida em janelas, usando o mesmo
  motor FFmpeg da timeline; concatena MP4s sem segunda codificação de vídeo.
- IA, cache, transcrição, seleção de sugestões e edições permanecem intactos.

## Testar no Windows

1. Feche o editor, preserve os projetos e extraia o pacote 0.9.2 em uma **pasta
   nova** (por exemplo, `C:\BerofelStudio092`), para não misturar versões.
2. Se já possui `%LOCALAPPDATA%\BFS\venv`, não reinstale os modelos. Execute
   `instalar_dependencias.bat` somente caso o verificador indique dependências
   faltantes.
3. Execute `TESTAR_PREVIA_092.bat`. Ele gera mídia sintética temporária e testa
   300 cortes, áudio/vídeo, exportação de 65 cortes e cache de metadados.
4. Inicie o editor. Abra o projeto com os cortes aprovados e clique
   **▶ Reproduzir timeline**. Teste início, meio, passagem de 30 s, pausa e seek.
5. Repita em **Prévia leve · 640px / 24fps** se seu computador ficar sobrecarregado.
6. Tente exportar o mesmo projeto e confira áudio, imagem e duração.

## Limitações e próximos testes

- Ainda **não houve teste da interface em Windows real**. A passagem automática
  entre janelas pré-carregadas pode provocar uma curta pausa ou descontinuidade,
  especialmente em computadores lentos, se o próximo trecho ainda não estiver
  decodificado. O teste prático de som e imagem é necessário.
- Uma regressão sintética de export fragmentado com 40 cortes e 20 s confirma
  duração do contêiner dentro de 60 ms e ausência de queda de nível PCM na emenda
  de 10 s. Fades/transições e sincronismo em gravação real ainda exigem teste.
- Se o preview ficar parado ou vier outra mensagem, envie o log de
  `scripts/abrir_com_log.py` e a hora aproximada da falha.
- Nenhum arquivo de vídeo original é alterado.

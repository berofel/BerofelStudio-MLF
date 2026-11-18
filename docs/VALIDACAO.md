# Registro histórico de validação — BerofelStudio Studio 0.3

> Este relatório é histórico e não descreve a versão atual. Para resultados recentes, consulte [VALIDACAO_010_ALPHA1_LOCAL.md](VALIDACAO_010_ALPHA1_LOCAL.md) e [VALIDACAO_IA.md](VALIDACAO_IA.md).

**Data do código:** 13 de novembro de 2026. **Ambiente de testes disponível nesta conversa:** contêiner Linux x86-64 com Python 3.13 e FFmpeg. Não há PySide6 instalada nem máquina Windows para execução remota, portanto **não declaramos a GUI/instalador Windows como previamente validados**.

## O que foi executado

Comando:

```bash
python -m unittest discover -s tests -v
```

Resultado: **14 testes passaram**. Escopos cobertos:

1. Projeto JSON v2 salva/carrega e migra JSON v1.
2. Ordenação das camadas universais e tipos arbitrários.
3. Seleção e corte de apenas um bloco intermediário.
4. Split preserva camada, posição na timeline e tempos de origem.
5. Recuperação de bordas (trim não destrutivo).
6. Render MP4 H.264/AAC com vídeo, título, imagem e áudios simultâneos.
7. Crop/seek a partir do meio de um arquivo (sem analisar vídeo todo).
8. Prévia por pipe FFmpeg entrega quadros BGRA do vídeo composto.
9. Prévia por pipe FFmpeg entrega áudio PCM mixado com 3 frequências verificadas.
10. Faixa superior cobre a inferior; mudar a ordem inverte a cor exibida.
11. Imagem sem som reproduz PCM silencioso, não quebra o motor.
12. Ocultar camada superior muda o vídeo composto.
13. Exportação emite progresso e entrega arquivo MP4 sem arquivo temporário sobrando.
14. Exportação impede sobrescrever arquivos-fonte originais.

Autoteste de integração separado:

```bash
python scripts/diagnostico_motor.py
```

Saída obtida:

```text
[OK] Dois vídeos em camadas simultâneas (azul sobre vermelho)
[OK] Áudio da composição recebido: 134400 bytes; pico 6055
[OK] Quadros BGRA recebidos: 9
```

Este autoteste roda também **no Windows durante a instalação** usando o FFmpeg que acabou de ser instalado. Assim evita que instalador marque sucesso apenas porque as bibliotecas estão presentes, sem conseguir compor duas fontes.

## O que NÃO foi testado/garantido aqui

- Janela PySide6 renderizada e responsiva num Windows 10/11 com a escala de DPI real do usuário.
- `QAudioSink` no dispositivo físico do computador do usuário e sincronização audiovisual medida por hardware.
- PowerShell 5.1 e downloads/arquivos assinados ao executar o instalador revisado no Windows.
- Playback em tempo real sustentável com diversos clipes 4K, vídeo VFR ou projeto de uma hora.
- Ampla variedade de codecs, formatos cor, legendas incorporadas, proxies, efeitos avançados.
- Distribuição comercial e auditoria integral de licenças.

Para validar o GUI no próprio Windows:

1. Extraia a pasta completa e rode `instalar_dependencias.bat`.
2. Verifique que o diagnóstico do compositor termina com três linhas `[OK]`.
3. Rode `TESTAR_PREVIEW_WINDOWS.bat`: uma janela de teste será aberta; duas fontes de vídeo de 2 segundos serão posicionadas em camadas e o motor deverá emitir pelo menos 3 quadros. A janela fecha ao término do teste.
4. Rode `ABRIR_BEROFELSTUDIO.bat`, importe 2 vídeos com áudio, sobreponha-os em camadas diferentes e clique `▶ Reproduzir timeline`; confirme áudio e imagem sincronizados. Depois altere ordem/ocultar/mudo e compare com o MP4 exportado.
5. Se a GUI falhar, envie saída de `TESTAR_PREVIEW_WINDOWS.bat` ou `logs/erro_abertura_*.log`; se travar sem traceback, envie detalhes e o codec do arquivo.

A conclusão da etapa 3 comprova que o streaming FFmpeg está chegando ao Qt; **não substitui** o teste auditivo/visual da etapa 4.


## Atualização 0.6 — Monitor e controle universal (13/11/2026)

- Novo `ProcessControl` usa `psutil` para suspender, retomar e encerrar processos
  registrados e seus filhos. O cancelamento em execução foi testado usando
  subprocessos Python REAIS em Linux, sem depender de downloads dos modelos.
- Teste de pausa: arquivo escrito por subprocesso para de mudar, o tempo ativo
  não avança durante pausa e o arquivo volta a mudar após Continuar.
- Teste de cancelamento: chamada bloqueada retorna como `ProcessCancelled`;
  não deixa o processo principal pendente.
- Teste de cache: cancelamento após a primeira etapa preserva extração concluída;
  segunda tentativa pula extração e executa apenas Silero/Whisper simulados.
- Teste de exportação: cancelamento não confirma MP4 parcial nem apaga fonte.
- São **30 testes aprovados** e **1 teste GUI não executado** porque o PySide6
  não está disponível neste ambiente Linux de desenvolvimento.
- O teste visual GUI e o controle real de processos no **Windows** ainda exigem
  validação do usuário com `TESTAR_PROCESSOS.bat`.
- As medições de CPU/RAM no painel são editor + processos-filhos (não só IA).
  Percentagem CPU pode exceder 100% em computadores com vários núcleos.
- A porcentagem de progresso é por etapas concluídas, NÃO a porcentagem de
  segundos da tarefa. Pocket TTS e Qwen podem ficar numa mesma porcentagem
  por vários minutos; a estimativa de tempo restante é apenas indicativa.


## 0.7 — Velocidade, keyframes, ripple, proxies e timeline

Executar `TESTAR_EDITOR_07.bat` no Windows. No ambiente de desenvolvimento, os
novos testes exercitam `setpts`+`atempo`, keyframes com alfa animado, fades,
camadas visuais, exportação H.264/AAC, filtros de áudio, rotação, crop,
persistência do projeto, velocidade das legendas, split pareado, ripple,
waveform/thumbnail por cache e geração/reuso de proxy H.264 não destrutivo.

Além dos testes automáticos, validar manualmente com vídeo real de 80 minutos:
- FPS variável, formatos diferentes e segmentos com faixas de áudio extras.
- Prévia 640px, proxies opcionais e exportação de 1080p/4K dos originais.
- Keyframes e velocidade em vídeo com áudio, legendas e divisões posteriores.
- Undo/redo de ripple, grupo, transições e edição de cor.
- Pausar/cancelar proxy via monitor e reiniciar sem corromper arquivo.
- CPU/RAM e tempo por etapa. Não há teto artificial de 4 GB.
- DPI 100/125/150%, dimensões pequenas e painéis sem sobreposição no Windows.

**Não confundir sucesso dos testes do motor no Linux com homologação visual ou
desempenho garantido no Windows.**

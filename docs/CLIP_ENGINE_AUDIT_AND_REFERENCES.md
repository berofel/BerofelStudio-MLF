# Berofel Clip Engine — auditoria e referências

Data da revisão: 26/11/2026

## Estado encontrado no repositório

O clipador não precisava ser reconstruído. A branch de trabalho já continha uma implementação local e determinística em `berofel/services/clipper.py`, ligada à interface `berofel/ui/clipper_dialog.py` e à janela principal. Ela recebe palavras persistidas no projeto, reutiliza cache da waveform/miniaturas, pode medir PCM por um pipe FFmpeg limitado e devolve candidatos revisáveis com timestamps absolutos da mídia de origem.

O Parakeet ativo está definido em `berofel/services/parakeet_asr.py` como NVIDIA `nemo-parakeet-tdt-0.6b-v3`, quantização INT8, `onnx-asr`, provedor `CPUExecutionProvider`, com timestamps via `.with_timestamps()`. A adaptação normaliza tokens em palavras e guarda `source_start`/`source_end`; confiança não fornecida fica ausente/`None`. O clipador não instancia nem invoca o ASR durante `analyze_clips`. A UI oferece, separadamente e sob ação explícita, transcrição Parakeet somente para blocos sem palavras persistidas.

Também já existem perguntas/respostas heurísticas, TextTiling lexical aproximado, papéis discursivos, janelas inteiras de palavras, pausas, perfis editoriais, cobertura de evidências, penalidades, títulos extrativos, TextRank local no modo avançado, sinais acústicos relativos, eventos visuais obtidos apenas de miniaturas em cache e deduplicação temporal/lexical por MMR.

## Mudança desta revisão

O máximo de candidatos é uma escolha da etapa de shortlist global; não altera os candidatos-base nem seus atributos por bloco. Antes, ele participava da chave do cache por bloco e uma alteração de quantidade refazia a análise local, embora as características PCM tivessem cache próprio. A nova chave omite `max_candidates`, mantendo o shortlist local de até 50 (limite da UI) e reaplicando a quantidade pedida somente na seleção final. A interface agora separa visualmente acertos de cache de ranking e de sinais.

O cache continua invalidando por mídia, intervalo, transcript normalizado, perfil, modo, pesos, sensibilidade e demais parâmetros que mudam efetivamente a análise. O filtro de nota mínima já era aplicado depois do cache.

## Pipeline e limites conhecidos

1. A UI delimita a seleção da timeline e carrega palavras já persistidas para as fontes selecionadas.
2. Sem transcrição, a análise pode usar apenas sinais medidos e rotula os candidatos como cues para revisão; não afirma que um pico ou uma mudança de miniatura seja semanticamente importante.
3. Modo rápido tenta usar somente waveform em cache. Sem essa waveform, não faz decodificação PCM silenciosa.
4. Equilibrado e avançado leem áudio por blocos FFmpeg e armazenam RMS, pico, clipping, fluxo espectral e ZCR em arrays compactos no cache.
5. Miniaturas são consultadas com `request=False`; o clipador não dispara extração de quadros.
6. O resultado permanece não destrutivo; prévia, ajuste por palavra e inserção na timeline são ações separadas.

Limitações observadas: não há leitura semântica de imagem; movimento de gameplay não é identificado como luta/caminhada; energia alta é apenas uma mudança acústica e não uma reação comprovada; precisão temporal depende de timestamps por palavra do Parakeet. Os pesos e rótulos são heurísticas editoriais, sem calibração humana ou validação de viralidade. O modo equilibrado pode decodificar o intervalo inteiro de cada bloco selecionado quando o cache PCM ainda não existe.

## Referências consultadas

Referências são engenharia e literatura, não prova de qualidade do Berofel. Nenhum código externo foi copiado nesta revisão.

| Referência | Ideia útil | Licença/decisão |
|---|---|---|
| [Auto-Editor](https://github.com/WyattBlue/auto-editor) | Máscaras temporais por condição, limiar de áudio/movimento e margem explícita para suavizar cortes. Útil para separar detecção de atividade da ação de edição. | O repositório declara Unlicense para seu código; binários e dependências podem ter licenças próprias. Nenhum código importado. |
| [PySceneDetect](https://github.com/Breakthrough/PySceneDetect) | Detector adaptativo compara mudanças entre frames com uma referência temporal local para reduzir cortes falsos por movimento de câmera; também documenta conteúdo HSV, histogramas e hash perceptual. | BSD-3-Clause verificada no repositório. Não adicionada como dependência; nosso clipador só reutiliza miniaturas já cacheadas. |
| [TextTiling, Hearst 1997](https://aclanthology.org/J97-1003/) | Coesão lexical e vales de similaridade para aproximar fronteiras de subassuntos. A versão local é uma heurística de janela/turnos e não uma implementação integral nem equivalente a avaliação humana do artigo. | Página ACL informa material pré-2016 sob CC BY-NC-SA 3.0. Não copiar texto nem código; somente conceito acadêmico. |
| [TextRank, Mihalcea e Tarau 2004](https://web.eecs.umich.edu/~mihalcea/papers/mihalcea.emnlp04.pdf) | Ranking gráfico recursivo de frases/termos; o modo avançado usa uma passagem pequena e localizada para saliência, não para prever viralidade. | Fórmula acadêmica estudada; não houve cópia de implementação. |
| [MomentClip / Yuu-yu09/clipper](https://github.com/Yuu-yu09/clipper) | Exibe justificativas e admite explicitamente limites de entendimento visual; exemplo de transparência e separação de pistas observáveis. | README declara MIT. Projeto inclui recursos multimodais/LLM opcionais, que não foram integrados nem são necessários ao Berofel. |
| [ClipsAI](https://github.com/ClipsAI/clipsai) | Organização de seleção por transcrição e transformação de trechos de fala em limites de clipe; a documentação lista integrações ASR próprias. | MIT verificada. A dependência WhisperX/ASR e arquitetura de clipping não foram importadas; o Berofel conserva Parakeet e seus timestamps. |
| [AutoClip / zhouxiaoka](https://github.com/zhouxiaoka/autoclip) | Referência de organização do fluxo e ferramentas de produção de clipes. | MIT declarado pelo projeto. Nenhum código ou modelo foi incorporado. |
| [AI Video Clipping Studio](https://github.com/osemeedeoghon/AI-Video-Clipping-Studio) | Documenta candidates com pontuação explicável, começo/fim por frases e limites naturais; bom exemplo de declarar que score não é previsão de viralidade. | MIT declarado. Projeto beta menciona Faster-Whisper e OpenCV, incompatíveis com a restrição do Berofel; nenhuma dependência foi incorporada. |
| [Claggeta/clipper](https://github.com/Claggeta/clipper) | Pipeline de análise e revisão de drafts, com comparação temporal contra trechos rotulados; seus próprios documentos alertam que resultados pequenos não provam qualidade. | Licença “To be decided”; não reutilizar código. |
| [st1fo/stream-clipper](https://github.com/st1fo/stream-clipper) | Filas de trabalho e associação de sinais de chat/evento em lives; demonstra que sinais externos devem ser associados temporalmente antes da seleção. | Licença não confirmada na página consultada; nenhuma reutilização de código. Seu LLM/ASR não é apropriado para este requisito. |
| [TextRank no ACL Anthology](https://aclanthology.org/O14-1.pdf) | Registro bibliográfico alternativo para o artigo EMNLP 2004 e uso em extração de frases/palavras-chave. | Referência acadêmica, sem código copiado. |

As marcas OpusClip, Klap e Vizard servem somente como referência de experiência editorial: escolha de duração, revisão, limites/contexto, títulos e diversidade. Os algoritmos proprietários não foram presumidos ou reproduzidos.

## Validação executada nesta revisão

- `unittest discover -s tests -p 'test_cl*.py'`: 67 testes passaram.
- `unittest discover -s tests -p 'test_parakeet_asr.py'`: 8 testes passaram. São testes de adaptador com doubles; não são uma nova inferência real do modelo.
- `unittest discover -s tests -v`: 674 testes passaram, 6 foram pulados, zero falharam (69,505 s). Inclui testes automatizados de UI e exportação, mas não substitui abrir e validar manualmente a janela do aplicativo.
- O interpretador Python global e `pytest` não estavam disponíveis com as dependências necessárias. Os comandos foram executados pelo ambiente já instalado em `%LOCALAPPDATA%\BFS\venv`; nenhum pacote ou modelo foi instalado.
- O benchmark de escala sintético mede apenas texto/ranking e não comprova tempo fim a fim, qualidade editorial, desempenho em 80 minutos ou custo do Parakeet.
- A janela gráfica não foi exercitada manualmente; o vídeo real abaixo foi usado somente para medir o ramo de sinais e cache, sem julgamento editorial dos candidatos.

### Escala sintética (80 minutos)

Execução: cinco repetições por modo, 11.048 palavras determinísticas repetidas, sem áudio/vídeo, ASR ou evidências editoriais rotuladas. A medição mede somente análise de texto/ranking; não é desempenho ponta a ponta nem qualidade humana.

| Modo | p50 | p95 estimado (5 amostras) | pico de delta RSS amostrado | candidatos |
|---|---:|---:|---:|---:|
| Rápido | 4,468 s | 4,515 s | 17,11 MiB | 7 |
| Equilibrado | 4,453 s | 4,460 s | 4,44 MiB | 7 |
| Avançado | 4,631 s | 4,718 s | 4,35 MiB | 7 |

Com cinco pontos, p95 é uma estimativa interpolada e não estatística estável. O primeiro pico RSS inclui importação/runtime e é especialmente sensível à amostragem curta.

### Vídeo local real, sem transcrição

Foi executado o pipeline Equilibrado sobre um vídeo local de gameplay de 4.837,9 s, sem projeto/transcrição Parakeet associado. Portanto nenhum ASR foi chamado. O motor leu PCM de forma incremental, produziu 241.893 frames de características, observou 1.330 eventos acústicos relativos e apresentou 8 candidatos para revisão, em 5,975 s de parede, 3,656 s de CPU e +15,52 MiB de pico RSS amostrado (RSS final 44,05 MiB). Uma segunda chamada, na mesma execução com cache temporário, levou 0,0169 s, indicou 1 acerto de cache de ranking, 0 s decodificados e os mesmos intervalos candidatos. É uma medição fim a fim do ramo de sinais sem ASR, não uma avaliação de precisão dos clipes; candidatos baseados em evento sem palavras são deliberadamente heurísticos e precisam de confirmação. Hardware informado pelo ambiente: AMD Family 25 Model 80, 16 processadores lógicos; consulta WMI do nome comercial/RAM foi negada, então não afirmo que esta rodada comprova o modelo exato Ryzen 7 5700G nem RAM física instalada.

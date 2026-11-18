# Amostras de voz CC0: informação histórica

Os quatro presets Voice-Zero do painel agora usam os IDs de estados de voz
precomputados pelo Pocket TTS; o instalador pré-carrega esses estados no cache
do Hugging Face para português quando há rede, sem baixar os WAVs separados.
Outros idiomas podem buscar estados ao primeiro uso. Arquivos WAV que já
existam nesta pasta não são apagados nem alterados.

Origem/licença das amostras de referência: [coleção kyutai/tts-voices/voice-zero](https://huggingface.co/kyutai/tts-voices/tree/main/voice-zero), identificada como CC0 pela Kyutai. O pré-cache dos estados é uma operação do instalador, não inclui WAVs no repositório.

**Importante:** a licença CC0 das amostras de referência não altera os termos
dos pesos do modelo Pocket TTS. Vozes personalizadas continuam exigindo acesso
ao checkpoint de clonagem e autorização expressa do titular da gravação. A voz
`rafael` é um preset oficial para português; não é uma amostra CC0 distribuída
pelo BerofelStudio.

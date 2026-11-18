# Avisos de dependências relevantes

Este inventário cobre dependências usadas pelo ajuste fino de voz e pela prévia ao vivo. Antes de distribuir os binários, inclua os textos integrais de licença exigidos junto ao instalador.

| Componente | Uso | Licença/condição identificada | Ação para distribuição |
|---|---|---|---|
| PyZMQ 27.x | Envia comandos locais ao filtro FFmpeg `azmq` para alterar EQ durante a reprodução | BSD 3-Clause | Incluir o aviso BSD no pacote de avisos de terceiros |
| libzmq (incluída nos wheels recentes de PyZMQ) | Transporte ZMTP para a comunicação local `127.0.0.1` | MPL 2.0 | Incluir o texto/aviso MPL correspondente ao wheel redistribuído |
| FFmpeg do pacote | Preview, filtros DSP e exportação | Build local informa `--enable-gpl` | Acompanhar o binário com as fontes e avisos requeridos pela licença do build |
| Rubber Band via FFmpeg | Pitch shifting com preservação de formantes e alteração de velocidade com pitch preservado | FFmpeg requer build com `--enable-librubberband`; Rubber Band oferece GPL v2+ ou licença comercial | Confirmar a licença apropriada ao modelo de distribuição antes de distribuir versão proprietária |

O FFmpeg local foi inspecionado com `-buildconf`, `-filters` e `-h filter=rubberband`. O filtro `azmq` foi testado com troca de ganho em um processo FFmpeg ativo. PyZMQ é uma dependência pequena do núcleo; quando `azmq`/PyZMQ não estiver disponível, o controlador ao vivo é omitido e a prévia usa a reconstrução anterior.

Referências oficiais: [PyZMQ BSD](https://github.com/zeromq/pyzmq/blob/main/LICENSE.md), [libzmq MPL 2.0](https://github.com/zeromq/libzmq/blob/master/LICENSE), [filtro FFmpeg Rubber Band](https://ffmpeg.org/ffmpeg-filters.html), [licença Rubber Band](https://breakfastquay.com/rubberband/license.html).

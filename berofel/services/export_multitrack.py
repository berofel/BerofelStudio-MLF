"""Composição multitrilha FFmpeg compartilhada entre exportação e reprodução ao vivo."""
from __future__ import annotations
from pathlib import Path
import tempfile
import subprocess
import os
from uuid import uuid4

from berofel.services.ffmpeg import ffmpeg_path, media_info, filter_complex_file_args, supports_filter
from berofel.services.voice_dsp import (clip_voice_eq, voice_eq_filters,
    voice_pitch_filters, combined_rubberband_filter)
from berofel.core.motion import ff_expr, value_at
from berofel.services.performance import current_profile


def _escape_path(path: str) -> str:
    return str(path)


def _make_title_png(c, filepath, width, height):
    # Textos exportados como PNG transparente, evitando dependencias do
    # filtro drawtext/fontconfig do FFmpeg em Windows recem formatado.
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new('RGBA',(width,height),(0,0,0,0))
    draw = ImageDraw.Draw(im)
    try:
        font_name=(getattr(c,'font_family','Arial') or 'Arial').casefold()
        font_file={'arial':'arialbd.ttf','calibri':'calibrib.ttf','segoe ui':'segoeuib.ttf',
                   'verdana':'verdanab.ttf'}.get(font_name,'arialbd.ttf')
        fontpath = (f'C:/Windows/Fonts/{font_file}' if os.name=='nt'
                    else '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')
        font = ImageFont.truetype(fontpath,max(12,int(c.font_size)))
    except OSError:
        font = ImageFont.load_default()
    text = (c.text or c.title or 'Titulo').strip()
    max_width = int(width*.86)
    wrapped=[]
    for paragraph in text.splitlines():
        line=''
        for word in paragraph.split(' '):
            candidate = (line+' '+word).strip()
            if line and draw.textbbox((0,0),candidate,font=font)[2]>max_width:
                wrapped.append(line)
                line=word
            else:
                line=candidate
        wrapped.append(line)
    line_height=int(c.font_size*1.3)
    base_y=(height-line_height*len(wrapped))//2
    def rgba(value,alpha):
        raw=str(value or '#FFFFFF').lstrip('#')
        if len(raw)==3:raw=''.join(ch*2 for ch in raw)
        try:rgb=bytes.fromhex(raw)
        except ValueError:rgb=b'\xff\xff\xff'
        if len(rgb)!=3:rgb=b'\xff\xff\xff'
        return (*rgb,alpha)
    fill=rgba(getattr(c,'font_color','#FFFFFF'),255)
    stroke=rgba(getattr(c,'stroke_color','#000000'),210)
    for j,line in enumerate(wrapped):
        # stroke cria contorno legivel sobre clipes claros
        draw.text((width//2,base_y+j*line_height),line,font=font,
                  anchor='mt',fill=fill,stroke_width=max(0,min(12,int(getattr(c,'stroke_width',3)))),
                  stroke_fill=stroke)
    im.save(filepath)


def _graph_and_inputs(project, tempdir, include_audio=True, include_video=True,
                      total_duration=None,voice_control_address=None,
                      voice_targets_out=None,voice_initial_out=None,
                      voice_control_clip_ids=None):
    """Retorna args de entrada e grafo; nao executa FFmpeg aqui.

    Ordem dos tracks armazenados: indice 0 = mais alto na interface.
    Para compor corretamente, processa de baixo para cima.
    """
    duration = max(.1, project.duration if total_duration is None else float(total_duration))
    width,height,fps=project.width,project.height,project.fps
    inputs=[]
    filters=[]
    visual=None
    if include_video:
        inputs=['-f','lavfi','-i',f'color=c=#0b101a:s={width}x{height}:r={fps}:d={duration:.6f}']
        filters=['[0:v]format=rgba[base0]']
        visual = 'base0'
    audio_labels=[]
    solo_tracks = {t.id for t in project.tracks if t.solo}
    idx=1 if include_video else 0
    # lista em ordem de fundo -> frente. Na mesma camada, ultimo inserido acima.
    tracks=list(reversed(project.tracks))
    for track in tracks:
        # ordem crescente de Z: os valores maiores sao desenhados por ultimo
        ordered = sorted((c for c in project.clips if c.track_id == track.id),
                         key=lambda c:(c.stack_order,project.clips.index(c)))
        for c in ordered:
            # Preserve short but valid clips: high-speed captions can be <80 ms.
            if c.duration<=.001:
                continue
            visual_on = (include_video and not track.hidden and c.kind in ('video','image','text'))
            audio_on = (include_audio and not track.muted
                        and (not solo_tracks or track.id in solo_tracks)
                        and c.kind in ('audio','video') and c.include_audio)
            if not visual_on and not audio_on:
                continue
            if c.kind=='text':
                Path(tempdir).mkdir(parents=True, exist_ok=True)
                title=Path(tempdir)/f'title_{idx}.png'
                _make_title_png(c,str(title),width,height)
                inputs += ['-loop','1','-framerate',str(fps),'-t',f'{c.duration:.6f}','-i',str(title)]
                has_audio=False
            elif c.kind=='image':
                if not Path(c.source).is_file():
                    raise FileNotFoundError(c.source)
                inputs += ['-loop','1','-framerate',str(fps),'-t',f'{c.duration:.6f}','-i',c.source]
                has_audio=False
            else:
                if not Path(c.source).is_file():
                    raise FileNotFoundError(c.source)
                inputs += ['-ss',f'{c.start:.6f}','-t',f'{c.end-c.start:.6f}','-i',c.source]
                _,has_video,has_audio=media_info(c.source)
                if c.kind=='video' and not has_video:
                    raise ValueError(f'Arquivo sem video: {c.source}')
            if c.kind=='video' and not has_video:
                visual_on=False
            if visual_on:
                out=f'v{idx}'
                # Curvas interpoladas avaliadas no tempo local do bloco. O FPS
                # e normalizado DEPOIS de alterar o PTS, para incluir 2×-10×.
                scale=ff_expr(c,'scale',var='t')
                w=f'trunc(max(16,{width}*({scale}))/2)*2'
                h=f'trunc(max(16,{height}*({scale}))/2)*2'
                opacity=max(0.,min(1.,c.opacity))
                if c.keyframes.get('opacity'):
                    # sendcmd altera o coeficiente de opacidade por intervalo.
                    # Evita filtros por PIXEL (geq/blend), que custariam mais CPU.
                    start=min(float(p['t']) for p in c.keyframes['opacity'])
                    stop=max(float(p['t']) for p in c.keyframes['opacity'])
                    step=max(1/max(1,fps), (stop-start)/3000)
                    checkpoints=[0.,*([start+i*step for i in range(int((stop-start)/step)+1)]
                                  if stop>start else [start]),stop]
                    times=sorted(set(round(max(0.,min(c.duration,x)),6) for x in checkpoints))
                    commands=';'.join(f'{t:.6f} colorchannelmixer@opacity{idx} aa '
                                      f'{max(0.,min(1.,value_at(c,"opacity",t))):.6f}'
                                      for t in times)
                    alpha_filter=f"format=rgba,sendcmd=c='{commands}'," \
                                 f'colorchannelmixer@opacity{idx}=aa={max(0.,min(1.,value_at(c,"opacity",0))):.5f}'
                else:
                    alpha_filter=f'format=rgba,colorchannelmixer=aa={opacity:.4f}'
                start_offset=max(0.,c.timeline_start)
                effects=''
                if c.kind in ('image','video'):
                    if any((c.crop_left,c.crop_right,c.crop_top,c.crop_bottom)):
                        left=max(0.,min(.45,c.crop_left))
                        right=max(0.,min(.45,c.crop_right))
                        top=max(0.,min(.45,c.crop_top))
                        bottom=max(0.,min(.45,c.crop_bottom))
                        effects+=f'crop=w=iw*{1-left-right:.6f}:h=ih*{1-top-bottom:.6f}:'
                        effects+=f'x=iw*{left:.6f}:y=ih*{top:.6f},'
                    if (abs(c.brightness)>1e-5 or abs(c.contrast-1)>1e-5 or
                        abs(c.saturation-1)>1e-5):
                        effects+=(f'eq=brightness={max(-1,min(1,c.brightness)):.4f}:'
                                  f'contrast={max(0,min(2,c.contrast)):.4f}:'
                                  f'saturation={max(0,min(3,c.saturation)):.4f},')
                fmt=(effects+f'scale=w=\'{w}\':h=\'{h}\':eval=frame:'
                     f'force_original_aspect_ratio=decrease,')
                if abs(c.rotation)>1e-5 or c.keyframes.get('rotation'):
                    angle=ff_expr(c,'rotation',var='t')
                    diagonal='ceil(sqrt(iw*iw+ih*ih)/2)*2'
                    fmt+=(f"format=rgba,rotate=a='{angle}*PI/180':"
                          f"ow='{diagonal}':oh='{diagonal}':c=none,")
                fmt+=alpha_filter
                fade=''
                if c.fade_in > .001:
                    fade+=f',fade=t=in:st=0:d={min(c.fade_in,c.duration):.5f}:alpha=1'
                if c.fade_out > .001:
                    fade+=f',fade=t=out:st={max(0.,c.duration-c.fade_out):.5f}:'
                    fade+=f'd={min(c.fade_out,c.duration):.5f}:alpha=1'
                origin_duration=c.end-c.start if c.kind=='video' else c.duration
                speed=c.speed if c.kind=='video' else 1.
                filters.append(
                    f'[{idx}:v]trim=duration={origin_duration:.6f},'
                    f'setpts=(PTS-STARTPTS)/{speed:.8f},fps={fps},'
                    f'{fmt}{fade},setpts=PTS+{start_offset:.6f}/TB[{out}]')
                next_base=f'base{idx}'
                local_time=f'(t-{start_offset:.6f})'
                px=ff_expr(c,'pos_x',var=local_time)
                py=ff_expr(c,'pos_y',var=local_time)
                ox=f'(W-w)/2+({px})'
                oy=f'(H-h)/2+({py})'
                filters.append(
                    f'[{visual}][{out}]overlay=x=\'{ox}\':y=\'{oy}\':'
                    f'eval=frame:eof_action=pass:repeatlast=0:shortest=0:'
                    f"enable='between(t,{c.timeline_start:.6f},{max(c.timeline_start,c.timeline_end-.0005):.6f})'"
                    f'[{next_base}]')
                visual=next_base
            if audio_on and has_audio:
                al=f'a{idx}'
                delay_ms=max(0,round(c.timeline_start*1000))
                speed=c.speed if c.kind in ('video','audio') else 1.
                # atempo encadeado entre 0,5 e 2 para builds antigos de FFmpeg.
                factors=[];remaining=speed
                while remaining>2.0+1e-8:
                    factors.append(2.0);remaining/=2.0
                while remaining<.5-1e-8:
                    factors.append(.5);remaining/=.5
                factors.append(remaining)
                atempo=','.join(f'atempo={f:.6f}' for f in factors)
                rubberband_available=supports_filter('rubberband')
                volume=ff_expr(c,'volume',var='t')
                equalizers=''
                if c.audio_highpass and c.audio_highpass>=20:
                    equalizers+=f'highpass=f={min(20000,int(c.audio_highpass))},'
                if c.audio_lowpass and c.audio_lowpass>=200:
                    equalizers+=f'lowpass=f={min(20000,int(c.audio_lowpass))},'
                if c.audio_denoise:
                    equalizers+='afftdn=nf=-25,'
                voice_filters=voice_eq_filters(clip_voice_eq(c))
                pitch_value=0.0 if c.voice_dsp_bypass else c.voice_pitch_semitones
                live_voice_control=bool(voice_control_address and
                    (voice_control_clip_ids is None or c.id in voice_control_clip_ids))
                pitch_target=(f'rubberband@voice_{idx}_pitch'
                              if live_voice_control and rubberband_available else '')
                if (c.preserve_pitch and rubberband_available and
                        abs(speed-1.)>1e-6 and
                        (abs(pitch_value)>.005 or bool(pitch_target))):
                    # Apply tempo and pitch in one phase-vocoder pass. Naming
                    # the filter also permits low-latency pitch commands while
                    # this preview graph is running.
                    combined=combined_rubberband_filter(speed,pitch_value)
                    time_stretch=(combined.replace('rubberband=',pitch_target+'=',1)
                                  if pitch_target else combined)
                    pitch_filters=[]
                elif pitch_target:
                    ratio=2.0**(pitch_value/12.0)
                    pitch_filters=[
                        f'{pitch_target}=tempo=1.0:pitch={ratio:.8f}:'
                        'formant=preserved:pitchq=quality']
                    time_stretch=atempo
                else:
                    time_stretch=(f'rubberband=tempo={speed:.6f}:pitch=1.0'
                                  if c.preserve_pitch and abs(speed-1.)>1e-6 and
                                  rubberband_available else atempo)
                    pitch_filters=voice_pitch_filters(
                        pitch_value,rubberband_available=rubberband_available)
                voice_limiter=''
                if live_voice_control:
                    voice_eq=clip_voice_eq(c)
                    prefix=f'voice_{idx}'
                    targets={
                        'bass_db':f'bass@{prefix}_bass',
                        'mids_db':f'equalizer@{prefix}_mids',
                        'treble_db':f'treble@{prefix}_treble',
                    }
                    if voice_targets_out is not None:
                        voice_targets_out[str(c.id)]=targets
                    gains=(0.,0.,0.) if voice_eq.bypass else (
                        voice_eq.bass_db,voice_eq.mids_db,voice_eq.treble_db)
                    if voice_initial_out is not None:
                        voice_initial_out[str(c.id)]={
                            'bass_db':gains[0],'mids_db':gains[1],'treble_db':gains[2],
                            'pitch_semitones':pitch_value}
                    if pitch_target and voice_targets_out is not None:
                        voice_targets_out[str(c.id)]['pitch_semitones']=pitch_target
                    voice_filters=[
                        f"bass@{prefix}_bass=f=120:width_type=q:width=0.707:gain={gains[0]:.2f}",
                        f"equalizer@{prefix}_mids=f=1200:t=q:w=1.000:g={gains[1]:.2f}",
                        f"treble@{prefix}_treble=f=5000:width_type=q:width=0.707:gain={gains[2]:.2f}",
                    ]
                    # Dynamic controls may boost bands after the graph starts,
                    # so protect the live signal even if its initial EQ is flat.
                    voice_limiter=',alimiter=limit=0.95:level=disabled'
                elif voice_filters and voice_filters[-1].startswith('alimiter='):
                    voice_limiter=','+voice_filters.pop()
                elif pitch_filters or abs(pitch_value)>.005:
                    # Pitch shift can create inter-sample peaks even with neutral EQ.
                    voice_limiter=',alimiter=limit=0.95:level=disabled'
                if voice_filters:
                    equalizers+=','.join(voice_filters)+','
                track_volume=max(0.,min(4.,float(track.volume)))
                pan=max(-1.,min(1.,float(track.pan)))
                left_gain=track_volume*(1. if pan<=0 else 1.-pan)
                right_gain=track_volume*(1. if pan>=0 else 1.+pan)
                track_mix=(f'pan=stereo|c0={left_gain:.6f}*FL|'
                           f'c1={right_gain:.6f}*FR,')
                afades=''
                if c.audio_fade_in>.001:
                    afades+=f',afade=t=in:st=0:d={min(c.audio_fade_in,c.duration):.5f}'
                if c.audio_fade_out>.001:
                    afades+=f',afade=t=out:st={max(0,c.duration-c.audio_fade_out):.5f}:'
                    afades+=f'd={min(c.audio_fade_out,c.duration):.5f}'
                filters.append(f'[{idx}:a]atrim=duration={c.end-c.start:.6f},'
                               # atempo pode emitir timestamps com deslocamento; zera
                               # novamente antes do delay da camada para manter áudio,
                               # vídeo e timeline na mesma origem temporal.
                               f'asetpts=PTS-STARTPTS,{time_stretch},asetpts=PTS-STARTPTS,'
                               f'atrim=duration={c.duration:.6f},'
                               f'aresample=48000,aformat=channel_layouts=stereo,'
                               f'{",".join(pitch_filters)+"," if pitch_filters else ""}'
                               f'{track_mix}{equalizers}volume=\'{volume}\':eval=frame{afades}'
                               f'{voice_limiter},'
                               f'adelay={delay_ms}:all=1,asetpts=PTS-STARTPTS[{al}]')
                audio_labels.append(al)
            idx+=1
    if include_video:
        filters.append(f'[{visual}]format=yuv420p[vout]')
    if not include_audio:
        return inputs,';\n'.join(filters),duration
    if audio_labels:
        if len(audio_labels)==1:
            filters.append(f'[{audio_labels[0]}]apad=pad_dur={duration:.6f},'
                           f'atrim=duration={duration:.6f}'
                           + (f",azmq=bind_address='tcp\\://{voice_control_address.removeprefix('tcp://').replace(':','\\:')}'"
                              if voice_control_address else '')+'[aout]')
        else:
            ins=''.join(f'[{n}]' for n in audio_labels)
            filters.append(f'{ins}amix=inputs={len(audio_labels)}:duration=longest:'
                           f'normalize=0:dropout_transition=0,'
                           f'alimiter=limit=0.95,apad=pad_dur={duration:.6f},'
                           f'atrim=duration={duration:.6f}'
                           + (f",azmq=bind_address='tcp\\://{voice_control_address.removeprefix('tcp://').replace(':','\\:')}'"
                              if voice_control_address else '')+'[aout]')
    else:
        filters.append(f'anullsrc=r=48000:cl=stereo,atrim=duration={duration:.6f}[aout]')
    return inputs,';\n'.join(filters),duration


def _call_ffmpeg(args, control=None):
    cmd=[ffmpeg_path(),'-hide_banner','-nostdin','-y',*args]
    kw=dict(stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,errors='replace',
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    proc=control.run(cmd,**kw) if control else subprocess.run(cmd,**kw)
    if proc.returncode:
        raise RuntimeError('FFmpeg retornou erro:\n'+proc.stderr[-2400:])


def _needs_segmented_export(project) -> bool:
    """Windows CreateProcess possui limite de tamanho da linha de comando.

    Um -i por corte transforma 300 cortes aprovados em um comando enorme.
    Também funciona em Linux para que projetos tenham comportamento portátil.
    """
    usable=[c for c in project.clips if c.duration >= .08]
    return (len(usable) > 36 or
            sum(len(str(c.source))*2 + 150 for c in usable) > 15000)


def _render_blank_segment(project, path, seconds, control=None):
    """Preserva lacunas reais na timeline quando uma janela não contém clipes."""
    profile=current_profile()
    cmd=[ffmpeg_path(),'-hide_banner','-loglevel','error','-nostdin','-y',
         '-f','lavfi','-i',f'color=c=#0b101a:s={project.width}x{project.height}:r={project.fps}',
         '-f','lavfi','-i','anullsrc=r=48000:cl=stereo',
         '-t',f'{seconds:.6f}','-threads',str(profile.export_threads),
         '-c:v','libx264','-preset','veryfast','-crf','22',
         '-pix_fmt','yuv420p','-r',str(project.fps),'-c:a','aac',
         '-b:a','160k',str(path)]
    kw=dict(stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,errors='replace',
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    result=control.run(cmd,**kw) if control else subprocess.run(cmd,**kw)
    if result.returncode:
        raise RuntimeError('FFmpeg não conseguiu criar intervalo vazio: '+result.stderr[-1200:])


def _export_large_project(project, destination, on_progress=None, control=None, stage=None):
    """Exporta em janelas pequenas e concatena sem recodificar o resultado.

    Cada janela é formada pelos mesmos filtros de composição do editor.
    Não passa a timeline inteira como argumentos ao FFmpeg no Windows.
    """
    from berofel.services.preview_pipeline import crop_project, _window_length
    destination=Path(destination).resolve()
    sources={Path(c.source).resolve() for c in project.clips if c.source}
    if destination in sources:
        raise ValueError('Exportação bloqueada: não sobrescreva a mídia original.')
    total=project.duration
    if total <= 0:
        raise ValueError('Não há tempo de vídeo para exportar.')
    units=max(1,round(total*100))
    if on_progress:on_progress(0,units)
    output=destination.with_name('.'+destination.stem+'.bfs_'+uuid4().hex+'.mp4')
    try:
        with tempfile.TemporaryDirectory(prefix='bfs_export_cortes_') as folder:
            folder=Path(folder)
            segments=[]
            at=0.0
            while at < total-0.00001:
                if control:control.checkpoint()
                length=_window_length(project,at,min(30.,total-at))
                portion, span=crop_project(project,at,length)
                piece=folder/f'part_{len(segments):05d}.mp4'
                if stage:
                    stage(f'FFmpeg · exportando trechos {len(segments)+1} · '
                          f'{at:.1f}/{total:.1f}s')
                if portion.clips:
                    def child_progress(done,den,at=at,span=span):
                        if on_progress:
                            on_progress(min(units,round((at+span*done/max(1,den))*100)),units)
                    export_project(portion,piece,on_progress=child_progress,
                                   control=control,stage=None,_allow_segments=False)
                else:
                    _render_blank_segment(portion,piece,span,control)
                segments.append(piece)
                at+=span
                if on_progress:on_progress(min(units,round(at*100)),units)
            manifest=folder/'partes.ffconcat'
            def escape(path):
                return path.as_posix().replace("'", "'\\''")
            manifest.write_text('ffconcat version 1.0\n'+''.join(
                "file '"+escape(p)+"'\n" for p in segments),encoding='utf-8')
            if stage:stage('FFmpeg · juntando trechos sem recodificar o vídeo')
            command=[ffmpeg_path(),'-hide_banner','-nostdin','-loglevel','error','-y',
                     '-f','concat','-safe','0','-i',str(manifest),
                     '-c','copy','-movflags','+faststart',str(output)]
            kwargs=dict(stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,errors='replace',
                        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            proc=control.run(command,**kwargs) if control else subprocess.run(command,**kwargs)
            if proc.returncode:
                raise RuntimeError('Falha juntando trechos da exportação: '+proc.stderr[-2000:])
            if control:control.checkpoint()
            os.replace(output,destination)
            if on_progress:on_progress(units,units)
    finally:
        if output.exists():
            try:output.unlink()
            except OSError:pass


def export_project(project, destination, on_progress=None, control=None, stage=None, _allow_segments=True):
    """Exporta MP4 H.264/AAC, com progresso verdadeiro e camadas arbitrárias.

    A composição é a MESMA fonte de filtros do player. Processamento em
    processo separado pelo Task da UI; usa stderr para ler -progress sem
    bloquear indefinidamente em buffers de output.
    """
    if control:control.checkpoint()
    if stage:stage('FFmpeg • preparando composição das camadas')
    if not project.clips:
        raise ValueError('Nao ha blocos para exportar.')
    if _allow_segments and _needs_segmented_export(project):
        return _export_large_project(project,destination,on_progress,control,stage)
    output=Path(destination).resolve()
    inputs_original={Path(c.source).resolve() for c in project.clips if c.source}
    if output in inputs_original:
        raise ValueError('Exportação bloqueada: escolha outro nome para preservar o arquivo original.')
    temporary=output.with_name('.'+output.stem+'.bfs_'+uuid4().hex+'.mp4')
    with tempfile.TemporaryDirectory(prefix='bfs_export_') as folder:
        profile=current_profile()
        inputs, graph, duration = _graph_and_inputs(project,folder)
        graphfile=Path(folder)/'filtros.txt'
        graphfile.write_text(graph,encoding='utf-8')
        units=max(1,round(duration*100))
        if on_progress: on_progress(0,units)
        command=[ffmpeg_path(),'-hide_banner','-nostdin','-y','-loglevel','error',
                 '-filter_complex_threads',str(profile.preview_threads),
                 '-progress','pipe:2','-stats_period','0.5',*inputs,
                 *filter_complex_file_args(graphfile),'-map','[vout]',
                 '-map','[aout]','-t',f'{duration:.6f}',
                 '-c:v','libx264','-preset','veryfast','-crf','22',
                 '-threads',str(profile.export_threads),
                 '-pix_fmt','yuv420p','-r',str(project.fps),
                 '-c:a','aac','-b:a','160k','-movflags','+faststart',str(temporary)]
        if len(subprocess.list2cmdline(command)) > 24000:
            if _allow_segments:
                return _export_large_project(project,destination,on_progress,control,stage)
            raise ValueError('Trecho possui entradas simultâneas com caminhos longos demais para o Windows.')
        if stage:stage('FFmpeg • codificando vídeo e mixando áudio')
        launcher=control.popen if control else subprocess.Popen
        proc=launcher(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                      stderr=subprocess.PIPE,text=True,errors='replace',
                      creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        errors=[]
        try:
            assert proc.stderr is not None
            for line in proc.stderr:
                if control:control.checkpoint()
                line=line.strip()
                if line.startswith('out_time_ms='):
                    try:
                        seconds=int(line.split('=',1)[1])/1_000_000
                        if on_progress: on_progress(min(units,round(seconds*100)),units)
                    except ValueError: pass
                elif not line.startswith(('frame=','fps=','stream_','bitrate=',
                                          'total_size=','out_time=','dup_frames=',
                                          'drop_frames=','speed=','progress=')):
                    if line: errors.append(line)
                    if len(errors)>30: errors.pop(0)
            code=proc.wait()
            if control:control.checkpoint()
            if code:
                raise RuntimeError('FFmpeg retornou erro (codigo '+str(code)+'):\n'+
                                   '\n'.join(errors)[-3000:])
            if control:control.checkpoint()
            os.replace(temporary, output)
            if on_progress: on_progress(units,units)
        finally:
            if temporary.exists():
                try: temporary.unlink()
                except OSError: pass
            if proc.stderr is not None: proc.stderr.close()
            if proc.poll() is None:
                if control:control._kill(proc)
                else:proc.kill()
                proc.wait()
            if control:control.release(proc)


def export_audio_wav(project, destination, *, sample_rate=48000, pcm='pcm_s24le',
                     control=None, stage=None):
    """Render the timeline mix to lossless WAV through the preview/export audio graph."""
    if control:control.checkpoint()
    if not project.clips:
        raise ValueError('Não há blocos para exportar.')
    if int(sample_rate) not in (44100,48000,96000):
        raise ValueError('Taxa WAV aceita: 44100, 48000 ou 96000 Hz.')
    if pcm not in ('pcm_s16le','pcm_s24le','pcm_s32le','pcm_f32le'):
        raise ValueError('Profundidade PCM não suportada.')
    output=Path(destination).resolve()
    sources={Path(c.source).resolve() for c in project.clips if c.source}
    if output in sources:
        raise ValueError('Exportação bloqueada: escolha outro nome para preservar o arquivo original.')
    if not output.parent.exists():
        output.parent.mkdir(parents=True,exist_ok=True)
    temporary=output.with_name('.'+output.stem+'.bfs_'+uuid4().hex+'.wav')
    try:
        with tempfile.TemporaryDirectory(prefix='bfs_audio_export_') as folder:
            if stage:stage('FFmpeg • preparando mixagem WAV')
            inputs,graph,duration=_graph_and_inputs(project,folder,include_video=False)
            graphfile=Path(folder)/'audio-filtros.txt'
            graphfile.write_text(graph,encoding='utf-8')
            command=[*inputs,*filter_complex_file_args(graphfile),'-map','[aout]',
                     '-t',f'{duration:.6f}','-ar',str(int(sample_rate)),'-ac','2',
                     '-c:a',pcm,'-f','wav',str(temporary)]
            if len(subprocess.list2cmdline([ffmpeg_path(),*command]))>24000:
                raise ValueError('Muitos cortes simultâneos para exportar WAV no Windows. Exporte em blocos menores.')
            if stage:stage('FFmpeg • renderizando WAV sem perdas')
            _call_ffmpeg(command,control=control)
        if control:control.checkpoint()
        os.replace(temporary,output)
        return str(output)
    finally:
        if temporary.exists():
            try:temporary.unlink()
            except OSError:pass


def render_frame(project, second, destination, control=None):
    """Frame em tempo absoluto; recorta ANTES de filtrar para scrub eficiente."""
    from berofel.services.preview_pipeline import crop_project
    if control:control.checkpoint()
    with tempfile.TemporaryDirectory(prefix='bfs_frame_') as folder:
        duration=max(project.duration, 0.)
        if duration <= 0:
            raise ValueError('Não há conteúdo para gerar quadro.')
        # Um instante antes do final garante um frame existente e evita
        # decodificar todos os minutos anteriores à posição solicitada.
        at=min(max(0.,float(second)),max(0.,duration-1/max(1,project.fps)))
        portion, span=crop_project(project,at,length=max(0.10,2/max(1,project.fps)))
        inputs,graph,_=_graph_and_inputs(portion,folder,include_audio=False,
                                         total_duration=span)
        graphfile=Path(folder)/'filtros.txt'
        graphfile.write_text(graph,encoding='utf-8')
        _call_ffmpeg([*inputs,*filter_complex_file_args(graphfile),
                      '-map','[vout]','-frames:v','1','-update','1',
                      '-f','image2',destination],control=control)

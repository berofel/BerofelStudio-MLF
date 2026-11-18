"""Composição da prévia a partir do MESMO filtergraph da exportação.

Arquitetura: Projeto -> intervalo de timeline -> FFmpeg filter_complex ->
  vídeo BGRA (pipe) e áudio PCM s16le (pipe) -> UI Qt.

Os dois processos são independentes para usar pipes portáteis no Windows;
ambos partem do mesmo projeto e dos mesmos tempos de origem. Não utiliza
MoviePy, nuvem ou uma dependência nativa MLT não empacotada.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
from pathlib import Path
import copy
import importlib.util
import os
import socket
import subprocess

from berofel.core.project import Project
from berofel.core.motion import slice_keyframes
from berofel.services.export_multitrack import _graph_and_inputs
from berofel.services.proxies import find_proxy
from berofel.services.ffmpeg import ffmpeg_path, filter_complex_file_args, supports_filter
from berofel.services.performance import current_profile

# Cada janela é composta diretamente das referências originais, sem renderizar MP4.
# Nunca enviar centenas de -i ao CreateProcess do Windows (WinError 206).
PREVIEW_WINDOW_SECONDS = 30.0
PREVIEW_MAX_CLIPS = 28
PREVIEW_MAX_CMD_CHARS = 20000
PREVIEW_MIN_WINDOW = 0.125


@dataclass
class PreviewCommands:
    video: list[str]
    audio: list[str]
    duration: float
    width: int
    height: int
    fps: int
    source_time: float
    voice_control_address: str | None = None
    voice_eq_targets: dict[str,dict[str,str]] | None = None
    voice_eq_initial: dict[str,dict[str,float]] | None = None


def _voice_control_endpoint():
    """Use runtime EQ control only when both FFmpeg and PyZMQ support it."""
    if not importlib.util.find_spec('zmq') or not supports_filter('azmq'):
        return None
    probe=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    try:
        probe.bind(('127.0.0.1',0))
        return f'tcp://127.0.0.1:{probe.getsockname()[1]}'
    finally:probe.close()


def crop_project(project: Project, position: float, length: float | None = None,
                 preview_width: int | None = None) -> tuple[Project, float]:
    """Corta as REFERÊNCIAS, sem cortar/regravar arquivo original.

    O intervalo é [position, position + length], ou até o fim quando length=None.
    Clipes que começam antes e terminam dentro têm source IN corrigido; os
    que atravessam o fim também são truncados. Preserva camada, opacidade,
    volume e ordenação. Os timestamps passam a ser relativos ao início.
    """
    start = max(0.0, float(position))
    end = project.duration if length is None else min(project.duration, start + float(length))
    if not 0 <= start < end:
        raise ValueError('Não há conteúdo para reproduzir nesse tempo.')
    result = Project(name=project.name, markers=copy.deepcopy(project.markers), width=project.width,
                     height=project.height, fps=project.fps,
                     media=list(project.media), tracks=copy.deepcopy(project.tracks), clips=[])
    for clip in project.clips:
        left = max(start, clip.timeline_start)
        right = min(end, clip.timeline_end)
        if right - left <= 0.0001:
            continue
        delta = left - clip.timeline_start
        result.clips.append(replace(clip, start=clip.start + delta*clip.speed,
                                    end=clip.start + (delta+right-left)*clip.speed,
                                    keyframes=slice_keyframes(clip.keyframes,delta,delta+right-left),
                                    fade_in=max(0,clip.fade_in-delta),
                                    fade_out=max(0,clip.fade_out-(clip.timeline_end-right)),
                                    audio_fade_in=max(0,clip.audio_fade_in-delta),
                                    audio_fade_out=max(0,clip.audio_fade_out-(clip.timeline_end-right)),
                                    timeline_start=left-start))
    if preview_width:
        preview_width = max(160, int(preview_width))
        ratio = preview_width / max(1, project.width)
        result.width = preview_width
        result.height = max(2, 2 * round(project.height * ratio / 2))
        for clip in result.clips:
            clip.pos_x = round(clip.pos_x * ratio)
            clip.pos_y = round(clip.pos_y * ratio)
            for field in ('pos_x','pos_y'):
                if field in clip.keyframes:
                    clip.keyframes[field]=[{**k,'value':k['value']*ratio}
                                           for k in clip.keyframes[field]]
            clip.font_size = max(8, round(clip.font_size * ratio))
    return result, end - start


def _overlapping_clips(project: Project, start: float, stop: float):
    """Conta apenas blocos com algum fluxo visível/audível na prévia."""
    visible = {t.id for t in project.tracks if not t.hidden}
    solo_tracks = {t.id for t in project.tracks if t.solo}
    audible = {t.id for t in project.tracks
               if not t.muted and (not solo_tracks or t.id in solo_tracks)}
    return [c for c in project.clips
            if c.timeline_start < stop and c.timeline_end > start
            and ((c.kind in ('video', 'image', 'text') and c.track_id in visible)
                 or (c.kind in ('video', 'audio') and c.include_audio and c.track_id in audible))]


def _window_length(project: Project, position: float, preferred: float) -> float:
    """Limita densidade de clipes, não duração de projeto ou quantidade total."""
    remaining = float(project.duration) - position
    length = min(remaining, preferred)
    # Quando possível, terminar em um corte já existente para não criar uma
    # descontinuidade artificial dentro de uma fala longa.
    if length > 12:
        lower = position + length * .65
        upper = position + length
        ends = [c.timeline_end for c in project.clips
                if lower <= c.timeline_end <= upper and math.isfinite(c.timeline_end)]
        if ends:
            length = max(PREVIEW_MIN_WINDOW, max(ends) - position)
    while length > PREVIEW_MIN_WINDOW and len(_overlapping_clips(project, position, position+length)) > PREVIEW_MAX_CLIPS:
        length /= 2
    if len(_overlapping_clips(project, position, position+length)) > PREVIEW_MAX_CLIPS:
        raise ValueError('Existem clipes simultâneos demais neste instante para a prévia. '
                         'O editor não modificou seus cortes; experimente reduzir as camadas simultâneas.')
    return max(PREVIEW_MIN_WINDOW, min(remaining, length))


def prepare_commands(project: Project, position: float, tempdir: str | Path,
                     preview_width: int = 640, fps: int = 24,
                     window: float | None = None,
                     voice_control_clip_id: str | None = None) -> PreviewCommands:
    """Compõe SOMENTE a próxima janela. Suporta milhares de cortes em sequência.

    A versão anterior gerava um -i por clipe de TODA a timeline, excedendo
    o máximo de caracteres do CreateProcess no Windows (WinError 206).
    A janela é preparada sob demanda; a UI pré-carrega a seguinte em paralelo.
    """
    tempdir = Path(tempdir)
    tempdir.mkdir(parents=True, exist_ok=True)
    position = max(0.0, float(position))
    fps = max(10, min(60, int(fps)))
    preferred = min(PREVIEW_WINDOW_SECONDS, float(window) if window is not None else PREVIEW_WINDOW_SECONDS)
    length = _window_length(project, position, preferred)
    profile = current_profile()
    base = [ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-nostdin',
            '-threads', str(profile.preview_threads),
            '-filter_complex_threads', str(profile.preview_threads)]
    voice_control_address=(_voice_control_endpoint()
                           if voice_control_clip_id else None)
    for attempt in range(12):
        window_project, duration = crop_project(project, position, length, preview_width)
        window_project.fps = fps
        # Proxies somente na prévia, sem afetar exportação original.
        for clip in window_project.clips:
            if clip.kind == 'video':
                lightweight = find_proxy(clip.source)
                if lightweight: clip.source = lightweight
        vi, vf, _ = _graph_and_inputs(window_project, str(tempdir / 'video'),
                                       include_audio=False, total_duration=duration)
        (tempdir / 'video').mkdir(parents=True, exist_ok=True)
        graph_v = tempdir / 'video_filters.txt'
        graph_v.write_text(vf, encoding='utf-8')
        video = [*base, *vi, *filter_complex_file_args(graph_v), '-map', '[vout]',
                 '-an', '-pix_fmt', 'bgra', '-f', 'rawvideo', 'pipe:1']
        voice_eq_targets={};voice_eq_initial={}
        ai, af, _ = _graph_and_inputs(window_project, str(tempdir / 'audio'),
                                       include_audio=True, include_video=False,
                                       total_duration=duration,
                                       voice_control_address=voice_control_address,
                                       voice_targets_out=voice_eq_targets,
                                       voice_initial_out=voice_eq_initial,
                                       voice_control_clip_ids=({voice_control_clip_id}
                                           if voice_control_clip_id else set()))
        graph_a = tempdir / 'audio_filters.txt'
        graph_a.write_text(af, encoding='utf-8')
        audio = [*base, *ai, *filter_complex_file_args(graph_a), '-map', '[aout]',
                 '-vn', '-ar', '48000', '-ac', '2', '-sample_fmt', 's16',
                 '-f', 's16le', 'pipe:1']
        if max(len(subprocess.list2cmdline(cmd)) for cmd in (video, audio)) <= PREVIEW_MAX_CMD_CHARS:
            return PreviewCommands(video=video, audio=audio, duration=duration,
                                   width=window_project.width, height=window_project.height,
                                   fps=fps, source_time=position,
                                   voice_control_address=(voice_control_address
                                       if voice_eq_targets else None),
                                   voice_eq_targets=voice_eq_targets,
                                   voice_eq_initial=voice_eq_initial)
        length /= 2
        if length < PREVIEW_MIN_WINDOW:
            break
    raise ValueError('A prévia possui entradas simultâneas com caminhos longos demais. '
                     'Tente mover o projeto para uma pasta de caminho mais curto.')


def start_ffmpeg(command: list[str]) -> subprocess.Popen:
    return subprocess.Popen(command, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            bufsize=0,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

"""Offline end-to-end smoke test: Pocket TTS -> DSP -> WAV/MP4 export.

Uses a short synthetic script and black video in a temporary project directory.
It reads the locally installed Pocket TTS model but forces offline mode and
does not alter user recordings, projects, or the model cache.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))

from berofel.core.project import Clip,Project
from berofel.services.export_multitrack import export_audio_wav,export_project
from berofel.services.ffmpeg import ffmpeg_path,ffprobe_path,supports_filter
from berofel.services.pocket_tts_service import NarrationRequest,generate_narration
from berofel.services.preview_pipeline import prepare_commands
from berofel.services.voice_dsp import (voice_pitch_filters,
    combined_rubberband_filter)


def main():
    old_cache=os.environ.get('BEROFEL_AI_CACHE')
    old_hf=os.environ.get('HF_HUB_OFFLINE')
    old_transformers=os.environ.get('TRANSFORMERS_OFFLINE')
    try:
        with tempfile.TemporaryDirectory(prefix='bfs_voice_e2e_') as folder:
            root=Path(folder)
            os.environ['BEROFEL_AI_CACHE']=str(root/'cache'/'ai')
            os.environ['HF_HUB_OFFLINE']='1'
            os.environ['TRANSFORMERS_OFFLINE']='1'
            project_file=root/'temporary_project.bfs'
            project_file.write_text('{}',encoding='utf-8')
            narration=generate_narration(NarrationRequest(
                text='Esta é uma validação local da narração com ajuste fino de voz.',
                voice='rafael',language='portuguese',project_path=str(project_file),
                title='TesteDSP'))
            duration=float(narration['duration'])
            frame_count=max(1,math.ceil(duration*24))
            video=root/'synthetic_video.mp4'
            subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y',
                '-f','lavfi','-i',f'color=c=black:s=320x180:r=24:d={duration:.6f}',
                '-frames:v',str(frame_count),'-an','-c:v','libx264','-pix_fmt',
                'yuv420p','-movflags','+faststart',str(video)],check=True,
                capture_output=True,timeout=45,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            project=Project(name='Teste temporário de ajuste fino',width=320,height=180,fps=24)
            project.add_clip(Clip(str(video),0,duration,kind='video',
                track_id=project.tracks[0].id,include_audio=False,title='Vídeo sintético'))
            voice=project.add_clip(Clip(str(narration['path']),0,duration,kind='audio',
                track_id=project.tracks[-1].id,title='Narração Pocket TTS',
                voice_eq_bass_db=1.5,voice_eq_mids_db=.5,
                voice_eq_treble_db=-1.,voice_pitch_semitones=-1.,
                voice_dsp_preset='Teste local',speed=1.15,preserve_pitch=True))
            wav=root/'narration_dsp.wav'
            mp4=root/'narration_dsp.mp4'
            export_audio_wav(project,wav)
            preview_commands=prepare_commands(project,0,root/'preview',
                preview_width=320,fps=24,window=duration)
            graph_option=next(option for option in ('-filter_complex_script','-/filter_complex')
                              if option in preview_commands.audio)
            preview_graph=Path(preview_commands.audio[
                preview_commands.audio.index(graph_option)+1]).read_text(encoding='utf-8')
            combined_passes=preview_graph.count('rubberband=')
            if supports_filter('rubberband') and combined_passes!=1:
                raise RuntimeError('Pitch e velocidade não foram combinados em um único Rubber Band.')
            preview_audio=subprocess.run(preview_commands.audio,check=True,
                capture_output=True,timeout=60,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).stdout
            exported_pcm16=subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel',
                'error','-i',str(wav),'-ac','2','-ar','48000','-f','s16le','pipe:1'],
                check=True,capture_output=True,timeout=30,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).stdout
            preview_samples=np.frombuffer(preview_audio,dtype='<i2').astype(np.float64)
            export_samples=np.frombuffer(exported_pcm16,dtype='<i2').astype(np.float64)
            if preview_samples.shape!=export_samples.shape or not preview_samples.size:
                raise RuntimeError('A duração ou quantidade de amostras da prévia difere do WAV exportado.')
            correlation=float(np.corrcoef(preview_samples,export_samples)[0,1])
            if not np.isfinite(correlation) or correlation<.995:
                raise RuntimeError(f'Prévia e WAV divergiram (correlação {correlation:.6f}).')
            export_project(project,mp4)
            probe=ffprobe_path()
            details=json.loads(subprocess.run([probe,'-v','error','-show_streams',
                '-show_format','-of','json',str(mp4)],check=True,capture_output=True,
                text=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).stdout)
            stream_types={stream.get('codec_type') for stream in details['streams']}
            if not {'video','audio'}.issubset(stream_types):
                raise RuntimeError(f'MP4 sem os streams esperados: {stream_types}')
            audio_stream=next(stream for stream in details['streams']
                              if stream.get('codec_type')=='audio')
            video_stream=next(stream for stream in details['streams']
                              if stream.get('codec_type')=='video')
            audio_duration=float(audio_stream['duration'])
            video_duration=float(video_stream['duration'])
            av_duration_delta=abs(audio_duration-video_duration)
            if av_duration_delta>1/24+.002:
                raise RuntimeError(f'Áudio e vídeo divergiram {av_duration_delta:.4f} s.')
            wav_probe=json.loads(subprocess.run([probe,'-v','error','-show_streams',
                '-of','json',str(wav)],check=True,capture_output=True,text=True,timeout=30,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).stdout)
            wav_stream=wav_probe['streams'][0]
            subprocess.run([ffmpeg_path(),'-hide_banner','-v','error','-i',str(mp4),
                '-f','null','NUL'],check=True,capture_output=True,timeout=60,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            print(json.dumps({
                'status':'PASS',
                'voice_profile':narration['voice'],
                'tts_cache_hit':narration['cache_hit'],
                'tts_duration_seconds':round(duration,3),
                'dsp':{'bass_db':voice.voice_eq_bass_db,'mids_db':voice.voice_eq_mids_db,
                       'treble_db':voice.voice_eq_treble_db,
                       'pitch_semitones':voice.voice_pitch_semitones,
                       'speed':voice.speed,'preserve_pitch':voice.preserve_pitch,
                       'rubberband_passes':combined_passes,
                       'pitch_filter':(combined_rubberband_filter(voice.speed,
                           voice.voice_pitch_semitones) if supports_filter('rubberband')
                           else voice_pitch_filters(voice.voice_pitch_semitones))},
                'wav':{'codec':wav_stream.get('codec_name'),
                       'sample_rate':wav_stream.get('sample_rate'),
                       'channels':wav_stream.get('channels'),
                       'bits_per_sample':wav_stream.get('bits_per_sample'),
                       'preview_correlation':round(correlation,6),
                       'preview_wav_same_sample_count':True},
                'mp4':{'streams':sorted(stream_types),
                       'audio_codec':audio_stream.get('codec_name'),
                       'duration':details.get('format',{}).get('duration'),
                       'audio_video_duration_delta_seconds':round(av_duration_delta,6),
                       'decode':'PASS'},
                'user_assets_modified':False,
                'offline_mode':True,
            },ensure_ascii=False,indent=2))
    finally:
        for key,value in (('BEROFEL_AI_CACHE',old_cache),('HF_HUB_OFFLINE',old_hf),
                          ('TRANSFORMERS_OFFLINE',old_transformers)):
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value


if __name__=='__main__':main()

"""Measure local EQ command latency and FFmpeg CPU/RAM on a synthetic voice tone."""
from __future__ import annotations

import json
import statistics
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np
import psutil

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))

from berofel.core.project import Clip,Project
from berofel.services.ffmpeg import supports_filter
from berofel.services.preview_pipeline import prepare_commands
from berofel.services.voice_preview_controller import VoicePreviewController


def main():
    import importlib.util
    if not importlib.util.find_spec('zmq') or not supports_filter('azmq'):
        raise SystemExit('Medição ao vivo requer PyZMQ e o filtro FFmpeg azmq.')
    with tempfile.TemporaryDirectory(prefix='bfs_eq_benchmark_') as folder:
        root=Path(folder);source=root/'benchmark_voice.wav';rate=48000
        t=np.arange(rate*30,dtype=np.float64)/rate
        pcm=(.12*np.sin(2*np.pi*180*t)+.08*np.sin(2*np.pi*1200*t)+
             .04*np.sin(2*np.pi*5000*t))
        with wave.open(str(source),'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate)
            wav.writeframes(np.clip(pcm*32767,-32768,32767).astype('<i2').tobytes())
        project=Project(width=160,height=90,fps=12)
        clip=project.add_clip(Clip(str(source),0,30,kind='audio',
            track_id=project.tracks[-1].id))
        commands=prepare_commands(project,0,root/'preview',preview_width=160,
                                  fps=12,window=30,voice_control_clip_id=clip.id)
        command=list(commands.audio)
        command.insert(command.index('-ss'),'-re')
        process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        controller=None
        try:
            controller=VoicePreviewController(commands.voice_control_address,
                commands.voice_eq_targets,commands.voice_eq_initial,timeout_ms=500)
            time.sleep(.3)  # let the audio filtergraph bind its localhost endpoint
            child=psutil.Process(process.pid)
            cpu_before=child.cpu_times()
            wall_before=time.perf_counter()
            latencies=[]
            for index in range(30):
                gain=(index%13)-6
                started=time.perf_counter()
                if not controller.set_eq(clip.id,{'bass_db':gain,'mids_db':0.,
                    'treble_db':0.}):
                    raise RuntimeError('FFmpeg rejeitou um comando dinâmico de EQ.')
                latencies.append((time.perf_counter()-started)*1000)
                time.sleep(.1)  # allow Windows process CPU counters to accumulate
            wall_elapsed=time.perf_counter()-wall_before
            cpu_after=child.cpu_times()
            cpu_ms=1000*((cpu_after.user+cpu_after.system)-
                         (cpu_before.user+cpu_before.system))
            rss=child.memory_info().rss/(1024*1024)
            ordered=sorted(latencies)
            # Windows process CPU counters are often quantized coarsely for a
            # short child process. Report the raw CPU time and suppress a
            # misleading 0.0% when the observed delta is below timer resolution.
            cpu_pct=(round(cpu_ms/(wall_elapsed*10),2) if cpu_ms >= 10 else None)
            print(json.dumps({'sample_count':len(ordered),
                'latency_ms_median':round(statistics.median(ordered),2),
                'latency_ms_p95':round(ordered[int(.95*(len(ordered)-1))],2),
                'ffmpeg_cpu_ms_for_samples':round(cpu_ms,3),
                'ffmpeg_cpu_percent_single_core':cpu_pct,
                'ffmpeg_cpu_measurement_note':(
                    'unavailable: CPU delta below 10 ms timer resolution'
                    if cpu_pct is None else 'single-core percentage over sample window'),
                'ffmpeg_rss_mib_sampled':round(rss,1)},ensure_ascii=False,indent=2))
        finally:
            if controller:controller.close()
            if process.poll() is None:process.terminate()
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)


if __name__=='__main__':main()

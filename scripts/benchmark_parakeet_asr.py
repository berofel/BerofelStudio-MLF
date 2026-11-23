"""Benchmark Parakeet Ultra on local PT-BR WAVs with references.

Example:
  python scripts/benchmark_parakeet_asr.py --audio-dir C:\\test\\pt_br \\
      --references C:\\test\\pt_br.trans.txt --backend vulkan --runs 3

The script never downloads samples or sends audio over the network.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys
import threading
import time
import unicodedata

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from berofel.services.model_paths import parakeet_model_path
from berofel.services.parakeet_asr import load_binding, read_pcm16_mono_16k


def _normalize(text: str) -> list[str]:
    text=unicodedata.normalize('NFKD',text.casefold())
    text=''.join(ch for ch in text if not unicodedata.combining(ch))
    return re.findall(r"[a-z0-9]+",text)


def _wer(reference: str, hypothesis: str) -> float:
    ref,hyp=_normalize(reference),_normalize(hypothesis)
    if not ref:return 0.0 if not hyp else 1.0
    previous=list(range(len(hyp)+1))
    for i,left in enumerate(ref,1):
        current=[i]
        for j,right in enumerate(hyp,1):
            current.append(min(current[-1]+1,previous[j]+1,
                               previous[j-1]+(left!=right)))
        previous=current
    return previous[-1]/len(ref)


def _peak_rss_mib() -> tuple[threading.Event, list[int], threading.Thread]:
    stop=threading.Event();peak=[0];ready=threading.Event()
    def poll():
        if os.name=='nt':
            import ctypes
            from ctypes import wintypes
            class Counters(ctypes.Structure):
                _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD),
                          ('PeakWorkingSetSize',ctypes.c_size_t),('WorkingSetSize',ctypes.c_size_t),
                          ('QuotaPeakPagedPoolUsage',ctypes.c_size_t),('QuotaPagedPoolUsage',ctypes.c_size_t),
                          ('QuotaPeakNonPagedPoolUsage',ctypes.c_size_t),('QuotaNonPagedPoolUsage',ctypes.c_size_t),
                          ('PagefileUsage',ctypes.c_size_t),('PeakPagefileUsage',ctypes.c_size_t),
                          ('PrivateUsage',ctypes.c_size_t)]
            handle=ctypes.windll.kernel32.GetCurrentProcess()
            api=ctypes.windll.psapi.GetProcessMemoryInfo
            api.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
            api.restype=wintypes.BOOL
            while not stop.is_set():
                counters=Counters();counters.cb=ctypes.sizeof(counters)
                if api(handle,ctypes.byref(counters),counters.cb):
                    peak[0]=max(peak[0],int(counters.WorkingSetSize))
                ready.set()
                stop.wait(.05)
        else:
            try:
                import psutil
                process=psutil.Process()
                while not stop.is_set():
                    peak[0]=max(peak[0],process.memory_info().rss)
                    ready.set()
                    stop.wait(.05)
            except ImportError:
                pass
        ready.set()
    thread=threading.Thread(target=poll,daemon=True);thread.start();ready.wait(.5)
    return stop,peak,thread


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument('--audio-dir',type=Path,required=True)
    parser.add_argument('--references',type=Path,required=True)
    parser.add_argument('--backend',choices=('cpu','vulkan'),default='cpu')
    parser.add_argument('--threads',type=int,default=6)
    parser.add_argument('--runs',type=int,default=3)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    refs={}
    for line in args.references.read_text(encoding='utf-8').splitlines():
        key,_,text=line.partition(' ')
        refs[key]=text.strip()
    files=sorted(args.audio_dir.glob('pt_br_*.wav'))
    if not files:raise SystemExit(f'No pt_br_*.wav files in {args.audio_dir}')
    missing=[path.stem for path in files if path.stem not in refs]
    if missing:raise SystemExit('Reference missing: '+', '.join(missing))
    model_path=parakeet_model_path()
    if not model_path.is_file():raise SystemExit(f'Model not installed: {model_path}')
    binding=load_binding()
    stop,peak,monitor=_peak_rss_mib()
    load_started=time.perf_counter()
    model=binding.Model(str(model_path),backend=args.backend)
    load_seconds=time.perf_counter()-load_started
    latencies=[];rters=[];wer=[];rows=[];cpu_seconds=wall_seconds=0.0
    try:
        session=model.session(n_threads=max(1,args.threads))
        with session:
            for path in files:
                pcm,duration=read_pcm16_mono_16k(path)
                for run in range(args.runs):
                    wall=time.perf_counter();cpu=time.process_time()
                    result=session.run(pcm,language='pt',timestamps='word')
                    elapsed=time.perf_counter()-wall
                    cpu_elapsed=time.process_time()-cpu
                    cpu_seconds+=cpu_elapsed;wall_seconds+=elapsed
                    latency=elapsed
                    latencies.append(latency);rters.append(elapsed/duration)
                    error=_wer(refs[path.stem],result.text)
                    wer.append(error)
                    rows.append({'file':path.name,'duration_s':round(duration,4),
                                 'run':run+1,'latency_s':round(elapsed,4),
                                 'rtf':round(elapsed/duration,5),'wer':round(error,5),
                                 'word_timestamps':len(result.words),
                                 'timestamp_kind':result.timestamp_kind,
                                 'model_timings_ms':{'mel':result.timings.mel_ms,
                                    'encode':result.timings.encode_ms,
                                    'decode':result.timings.decode_ms}})
    finally:
        model.close();stop.set();monitor.join(timeout=1)
    def p95(values):
        values=sorted(values)
        return values[min(len(values)-1,max(0,math.ceil(.95*len(values))-1))]
    report={'engine':'Parakeet Ultra Q8_0','runtime':binding.native_version(),
            'backend':args.backend,'threads':args.threads,'model_bytes':model_path.stat().st_size,
            'model_load_s':round(load_seconds,4),'audio_files':len(files),'runs_per_file':args.runs,
            'inference_count':len(rows),'latency_s':{'p50':round(statistics.median(latencies),4),
                                                       'p95':round(p95(latencies),4)},
            'rtf':{'p50':round(statistics.median(rters),5),'p95':round(p95(rters),5)},
            'wer_mean':round(statistics.mean(wer),5),
            'wer_by_file':{row['file']:row['wer'] for row in rows if row['run']==1},
            'aggregate_cpu_percent':round(100*cpu_seconds/wall_seconds,2) if wall_seconds else None,
            'peak_working_set_mib':round(peak[0]/(1024**2),2) if peak[0] else None,
            'samples':rows}
    encoded=json.dumps(report,ensure_ascii=False,indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(encoded,encoding='utf-8')
    print(encoded)
    return 0


if __name__=='__main__':
    raise SystemExit(main())

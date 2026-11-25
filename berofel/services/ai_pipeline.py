"""Local pipeline: extract -> Silero/ONNX -> Parakeet TDT v3 INT8 -> Qwen/GGUF.

Um subprocesso por etapa. Cada etapa usa JSON em cache e só então passa o
resultado à seguinte. Nenhum modelo permanece carregado na memória do editor.
"""
from __future__ import annotations
from dataclasses import dataclass
import os
import math
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Callable

from .ai_cache import CacheStore, CACHE_SCHEMA, digest, read_json, write_json
from .process_control import ProcessControl
from .model_paths import parakeet_tdt_model_dir, silero_vad_model_dir
from .performance import current_profile, qwen_limits, qwen_threads

ROOT = Path(__file__).resolve().parents[2]


def qwen_stage_timeout(word_items: list[dict], prompt_max_chars: int) -> int:
    """Timeout por transcrição/clipe Qwen, dimensionado pelos lotes de contexto."""
    prompt_size=480+sum(len(json.dumps({'id':w.get('id',''),'text':w.get('text','')},
                                       ensure_ascii=False,separators=(',',':')))+1
                         for w in word_items)
    batch_capacity=max(1024,int(prompt_max_chars)-800)
    batches=max(1,math.ceil(prompt_size/batch_capacity))
    # Cada chamada llama-cli tem timeout interno de 300 s. Reserva 120 s por
    # inicialização/escrita por lote, com teto de 18 min para o worker completo.
    return min(1080,300*batches+120)


def qwen_removal_interval(word_ids: list[str], words: list[dict], clip_duration: float,
                          padding: float = .025, max_cut_seconds: float = 6.) -> tuple[float,float] | None:
    """Map a continuous Parakeet word-ID span to source-relative clip seconds.

    Qwen never predicts timecodes. The editor uses Parakeet's word timestamps:
    start = first_word.start - padding; end = last_word.end + padding.
    Both values are relative to the source interval of the clip, before speed
    mapping in ``apply_reviewed_cuts``.
    """
    if (not isinstance(word_ids,list) or not word_ids or
            any(not isinstance(word_id,str) for word_id in word_ids)):
        return None
    by_id={word.get('id'): (index,word) for index,word in enumerate(words)}
    if len(by_id)!=len(words):
        return None
    selected=[by_id.get(word_id) for word_id in word_ids]
    if any(item is None for item in selected):
        return None
    indexes=[item[0] for item in selected]
    if indexes!=list(range(indexes[0],indexes[0]+len(indexes))):
        return None
    first,last=selected[0][1],selected[-1][1]
    try:
        duration=float(clip_duration)
        start=float(first['start'])-padding
        end=float(last['end'])+padding
    except (KeyError,TypeError,ValueError):
        return None
    if not all(math.isfinite(value) for value in (duration,start,end)):
        return None
    start=max(0.,start);end=min(duration,end)
    if end-start<.04 or end-start>max_cut_seconds:
        return None
    return round(start,4),round(end,4)


def default_llama_cli() -> Path:
    env = os.environ.get('BEROFEL_LLAMA_CLI')
    if env: return Path(env)
    base = Path(os.environ.get('LOCALAPPDATA') or (Path.home() / '.berofelstudio'))
    return base / 'BFS' / 'tools' / 'llama' / ('llama-cli.exe' if os.name == 'nt' else 'llama-cli')


def default_qwen_model() -> Path:
    env=os.environ.get('BEROFEL_QWEN_MODEL')
    if env: return Path(env)
    base=Path(os.environ.get('LOCALAPPDATA') or (Path.home() / '.berofelstudio'))
    return base / 'BFS' / 'models' / 'Qwen3-1.7B-Q4_K_M.gguf'


@dataclass
class AIOptions:
    asr_model_path: str = ''
    vad_model_path: str = ''
    language: str = 'pt'
    device: str = 'cpu'
    chunk_seconds: int = 120
    min_silence: float = 0.65
    silence_padding: float = 0.12
    enable_qwen: bool = False
    cpu_threads: int = 6
    # Local benchmark: 4 intra-op threads beat 6/8 on VAD-bounded Parakeet
    # utterances. Keep cpu_threads=6 unchanged for Qwen stages.
    asr_threads: int = 4
    qwen_model: str = ''
    llama_cli: str = ''
    offline_only: bool = True


def transcript_model_identity(options: AIOptions) -> str:
    """Stable project-coverage identity; never reuse transcript across ASRs."""
    model=Path(options.asr_model_path) if options.asr_model_path else parakeet_tdt_model_dir()
    vad=Path(options.vad_model_path) if options.vad_model_path else silero_vad_model_dir()
    def fingerprint(directory):
        files=[]
        if directory.is_dir():
            for path in sorted(directory.rglob('*')):
                if path.is_file() and '.cache' not in path.parts:
                    stat=path.stat()
                    files.append(f'{path.relative_to(directory).as_posix()}:{stat.st_size}:{stat.st_mtime_ns}')
        return digest(files)
    return 'parakeet-tdt-v3-int8/onnx-asr-cpu/threads={}/model={}/vad={}'.format(
        max(1,int(options.asr_threads)),fingerprint(model),fingerprint(vad))


def _windows_flags():
    return getattr(subprocess, 'CREATE_NO_WINDOW', 0)


class StageRunner:
    """Injetável nos testes para verificar cache, retomada e sequência."""
    def __call__(self, stage: str, payload: dict, output: Path, timeout: int = 2400,
                 control=None, on_progress=None):
        request = output.with_suffix('.request.json')
        progress_file=output.with_suffix('.progress.json')
        if stage=='qwen' and on_progress:
            payload={**payload,'progress_file':str(progress_file)}
        # A retry after timeout must not display the previous attempt's batch
        # as if it were live progress. Both files belong only to this request.
        progress_file.unlink(missing_ok=True)
        write_json(request, {'schema': CACHE_SCHEMA, **payload})
        env=os.environ.copy()
        env['PYTHONPATH']=str(ROOT) + os.pathsep + env.get('PYTHONPATH', '')
        command=[sys.executable, '-m', 'berofel.services.ai_worker',stage,str(request),str(output)]
        latest_progress=None
        def poll_progress():
            nonlocal latest_progress
            event=read_json(progress_file)
            if (event is not None and event.get('stage')=='qwen_progress' and
                    event!=latest_progress):
                latest_progress=event
                try:on_progress(event)
                except Exception:pass  # progress display cannot invalidate cached AI output
        try:
            progress_control=control or (ProcessControl() if on_progress else None)
            if progress_control:
                proc=progress_control.run(command, cwd=str(ROOT), env=env, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, errors='replace',timeout=timeout,
                                 on_poll=poll_progress if on_progress else None,
                                 creationflags=_windows_flags())
            else:
                proc=subprocess.run(command,cwd=str(ROOT),env=env,capture_output=True,
                                    text=True,errors='replace',timeout=timeout,
                                    creationflags=_windows_flags())
            if proc.returncode:
                raise RuntimeError(f'Etapa {stage} falhou: ' + (proc.stderr or proc.stdout)[-600:])
            data=read_json(output)
            if data is None or data.get('stage') != stage:
                raise RuntimeError(f'Etapa {stage} não gerou resultado válido.')
            if on_progress:poll_progress()
            return data['result']
        finally:
            request.unlink(missing_ok=True)
            progress_file.unlink(missing_ok=True)


    def run_batch(self, stage: str, jobs: list[dict], on_completed=None, timeout: int = 7200, control=None):
        """Um único processo/modelo para N trechos; checkpoint JSON por trecho.

        O callback avança quando cada arquivo é persistido, sem esperar a
        conclusão completa. Se houver falha, etapas concluídas ficam no cache.
        """
        if not jobs:return
        if stage not in ('vad','parakeet'):
            raise ValueError('Apenas VAD e os motores ASR possuem processamento em lote.')
        with tempfile.TemporaryDirectory(prefix='bfs_ai_batch_') as folder:
            folder=Path(folder)
            request=folder/'jobs.json'
            answer=folder/'batch.json'
            stderr_path=folder/'worker.stderr.log'
            stderr_log=stderr_path.open('wb')
            write_json(request,{'schema':CACHE_SCHEMA,'jobs':jobs})
            env=os.environ.copy()
            env['PYTHONPATH']=str(ROOT)+os.pathsep+env.get('PYTHONPATH','')
            command=[sys.executable,'-m','berofel.services.ai_worker',
                     stage+'_batch',str(request),str(answer)]
            launcher=control.popen if control else subprocess.Popen
            try:
                proc=launcher(command,cwd=str(ROOT),env=env,stdout=subprocess.DEVNULL,
                              # A file avoids a child blocking on a full stderr
                              # pipe while a long CPU/Vulkan inference runs.
                              stderr=stderr_log,creationflags=_windows_flags())
            except Exception:
                stderr_log.close()
                raise
            completed=set()
            started=control.elapsed() if control else time.monotonic()
            try:
                while proc.poll() is None:
                    if control:control.checkpoint()
                    for job in jobs:
                        output=str(job['output'])
                        if output not in completed and read_json(Path(output)) is not None:
                            completed.add(output)
                            if on_completed:on_completed()
                    if (control.elapsed() if control else time.monotonic())-started>timeout:
                        proc.kill()
                        raise TimeoutError(f'Etapa {stage} ultrapassou o tempo máximo do trabalho.')
                    time.sleep(.2)
                if control:control.checkpoint()
                stderr_log.flush()
                with stderr_path.open('rb') as saved_log:
                    saved_log.seek(max(0,stderr_path.stat().st_size-8192))
                    error=saved_log.read().decode('utf-8','replace')
                for job in jobs:
                    output=str(job['output'])
                    if output not in completed and read_json(Path(output)) is not None:
                        completed.add(output)
                        if on_completed:on_completed()
                if proc.returncode or len(completed)!=len(jobs):
                    raise RuntimeError(f'Etapa {stage} em lote incompleta ({len(completed)}/{len(jobs)}): '+error[-700:])
            finally:
                if proc.poll() is None:
                    if control:control._kill(proc)
                    else:proc.kill()
                proc.wait()
                if control:control.release(proc)
                stderr_log.close()



class Pipeline:
    def __init__(self, cache: CacheStore | None = None, runner=None, control=None, stage_callback=None):
        self.cache=cache or CacheStore()
        self.runner=runner or StageRunner()
        self.cache_hits=0
        self.cache_misses=0
        self.stages=[]
        self.control=control
        self.stage_callback=stage_callback

    def _notify(self, label):
        if self.control:self.control.checkpoint()
        if self.stage_callback:self.stage_callback(label)

    def _stage(self, stage, source, start, end, options, payload, on_progress=None, **kwargs):
        if self.control:self.control.checkpoint()
        directory=self.cache.directory(source, start, end, {'step': stage, 'parameters': options})
        target=directory / (stage + '.json')
        previous=read_json(target)
        if previous is not None and previous.get('stage') == stage:
            if stage != 'extract' or Path(previous.get('result', {}).get('audio_path', '')).is_file():
                self.cache_hits += 1
                self.stages.append((stage, 'cache'))
                return previous['result']
        directory.mkdir(parents=True, exist_ok=True)
        if stage=='extract': payload={**payload, 'audio_path': str(directory/'audio.wav')}
        elif stage=='qwen':
            # O worker grava cada lote contextual concluído; se uma inferência
            # posterior falhar, a próxima tentativa retoma do último lote salvo.
            payload={**payload,'checkpoint_dir':str(directory/'qwen_batches')}
            if on_progress is not None:
                kwargs['on_progress']=on_progress
        self.cache_misses+=1
        # A etapa executa em outro processo; seu encerramento libera modelo/RAM.
        if self.control and isinstance(self.runner, StageRunner):
            kwargs['control']=self.control
        result=self.runner(stage, payload, target, **kwargs)
        if not target.is_file():
            write_json(target, {'schema': CACHE_SCHEMA, 'stage': stage, 'result': result})
        self.stages.append((stage, 'executado'))
        return result

    @staticmethod
    def _build_gaps(speech: list, duration: float, minimum: float, padding: float) -> list:
        normalized=[]
        for seg in sorted(speech, key=lambda x: x['start']):
            a=max(0., min(duration, float(seg['start'])))
            b=max(a, min(duration, float(seg['end'])))
            if normalized and a<=normalized[-1][1]:
                normalized[-1]=(normalized[-1][0],max(normalized[-1][1],b))
            else:
                normalized.append((a,b))
        gaps=[];cursor=0.
        for a,b in normalized+[(duration,duration)]:
            if a-cursor >= minimum:
                lo=cursor+padding;hi=a-padding
                if hi-lo>=.12:
                    gaps.append((round(lo,4),round(hi,4)))
            cursor=max(cursor,b)
        return gaps

    @staticmethod
    def _active_audio_duration(start: float, end: float, activity: list) -> float:
        intervals=[]
        for span in activity:
            a=max(float(start),float(span.get('start',0)))
            b=min(float(end),float(span.get('end',0)))
            if b>a:intervals.append((a,b))
        merged=[]
        for a,b in sorted(intervals):
            if merged and a<=merged[-1][1]:merged[-1]=(merged[-1][0],max(merged[-1][1],b))
            else:merged.append((a,b))
        return sum(b-a for a,b in merged)

    @classmethod
    def _classify_voice_free_gaps(cls, speech: list, transcript_words: list,
                                  activity: list, duration: float,
                                  minimum: float, padding: float,
                                  speedup_minimum: float = 1.2) -> list[dict]:
        """Cut truly quiet pauses; offer 2x for longer audible, voice-free play.

        Every transcript word augments the Silero protection intervals. Energy
        is used only to distinguish audible gameplay from actual quiet; it is
        never treated as evidence of voice or as permission to cross speech.
        """
        protected=list(speech)
        for word in transcript_words:
            try:a=float(word.get('start',0));b=float(word.get('end',0))
            except (TypeError,ValueError):continue
            if math.isfinite(a) and math.isfinite(b) and b>a:
                protected.append({'start':a,'end':b})
        findings=[]
        for start,end in cls._build_gaps(protected,duration,minimum,padding):
            span=end-start
            active=cls._active_audio_duration(start,end,activity)
            audible_gameplay=(span>=speedup_minimum and active>=.35 and active/span>=.20)
            if audible_gameplay:
                findings.append({'a':start,'b':end,'type':'speedup','speed':2.0,
                    'score':100,'note':('Sem fala detectada por Silero; há atividade de áudio '
                        'neste intervalo. Sugestão revisável: acelerar para 2×.'),
                    'checked':False})
            else:
                findings.append({'a':start,'b':end,'type':'silencio','score':100,
                    'note':'Sem fala e sem atividade de áudio relevante; revisar antes de cortar.',
                    'checked':False})
        return findings

    def _batch_stage(self, chunks, stage, build, on_step=None):
        """Recupera cache por trecho e processa faltantes com o modelo carregado uma vez."""
        jobs=[]
        unique_jobs={}
        for ch in chunks:
            if self.control:self.control.checkpoint()
            config,payload=build(ch)
            directory=self.cache.directory(ch['clip'].source,ch['a'],ch['b'],
                                           {'step':stage,'parameters':config})
            target=directory/(stage+'.json')
            cached=read_json(target)
            if cached is not None and cached.get('stage')==stage:
                ch[stage]=cached['result']
                self.cache_hits+=1
                self.stages.append((stage,'cache'))
                if on_step:on_step()
            else:
                target.parent.mkdir(parents=True,exist_ok=True)
                # Vídeo e áudio separados podem apontar para a mesma fonte.
                # Processa cada (fonte, intervalo, opções) uma única vez.
                key=str(target)
                if key in unique_jobs:
                    unique_jobs[key]['chunks'].append(ch)
                else:
                    entry={'payload':payload,'output':key,'chunks':[ch]}
                    jobs.append(entry)
                    unique_jobs[key]=entry
        if not jobs:return
        self.cache_misses+=len(jobs)
        emitted=0
        def mark_done():
            nonlocal emitted
            if emitted>=len(jobs):return
            job=jobs[emitted]
            emitted+=1
            if on_step:
                for _ in job['chunks']:on_step()
        if hasattr(self.runner,'run_batch'):
            kwargs={'on_completed':mark_done}
            if self.control and isinstance(self.runner, StageRunner):
                kwargs['control']=self.control
            self.runner.run_batch(stage,[{'payload':j['payload'],'output':j['output']} for j in jobs],
                                  **kwargs)
        else:
            # Permite motores simulados nos testes e drivers alternativos.
            for j in jobs:
                self.runner(stage,j['payload'],Path(j['output']))
                mark_done()
        for j in jobs:
            data=read_json(Path(j['output']))
            if data is None or data.get('stage') != stage:
                raise RuntimeError(f'Etapa {stage} nao persistiu resultado do bloco.')
            for ch in j['chunks']:
                ch[stage]=data['result']
                self.stages.append((stage,'executado'))
        while emitted<len(jobs):mark_done()

    def analyze(self, clips, options: AIOptions | None = None, progress: Callable | None = None, mode: str = 'combined', known_words: dict | None = None) -> dict:
        opts=options or AIOptions()
        known_words=known_words or {}  # palavras já verificadas contra fingerprint da fonte
        actions = {
            'combined': (True, True, bool(opts.enable_qwen)),
            'transcribe': (False, True, False),
            'subtitles': (False, True, False),
            'silence': (True, False, False),
            'fillers': (False, True, True),
            'context': (True, True, True),
        }
        if mode not in actions:
            raise ValueError('Ação de IA desconhecida: '+str(mode))
        needs_vad, needs_asr, needs_qwen = actions[mode]
        if not 15 <= opts.chunk_seconds <= 1800:
            raise ValueError('Tamanho de lote inválido (15 a 1800 segundos).')
        if needs_qwen:
            cli=Path(opts.llama_cli) if opts.llama_cli else default_llama_cli()
            model=Path(opts.qwen_model) if opts.qwen_model else default_qwen_model()
            if not cli.is_file() or not model.is_file():
                raise FileNotFoundError('Qwen solicitado, mas llama-cli ou o modelo GGUF não foram encontrados. '
                                        'Execute INSTALAR_QWEN_OPCIONAL.bat ou configure os caminhos.')
        items=[c for c in clips if getattr(c,'kind','video') in ('audio','video') and c.duration>.05]
        # TDT needs short speech windows, so Silero is a prerequisite only if
        # there is actually uncovered text to transcribe. Existing project
        # coverage avoids both VAD and ASR unless the selected action analyzes
        # pauses (silence/context/combined).
        needs_vad = needs_vad or (needs_asr and any(c.id not in known_words for c in items))
        include_silence_suggestions = mode in ('combined','silence')
        chunks=[]
        for clip in items:
            index=0
            source_seconds = clip.end - clip.start
            while index*opts.chunk_seconds < source_seconds-.001:
                relative=index*opts.chunk_seconds
                a=clip.start+relative;b=min(clip.end,a+opts.chunk_seconds)
                chunks.append({'clip':clip,'index':index,'relative':relative,'a':a,'b':b,'duration':b-a})
                index+=1
        total=max(1,len(chunks)*(1 + int(needs_vad) + int(needs_asr)) +
                  (len(items) if needs_qwen else 0))
        count=0
        def step():
            nonlocal count
            count+=1
            if progress:progress(count,total)

        self._notify(f'Preparando áudio e cobertura do cache • {len(chunks)} trecho(s)')
        # A transcrição já validada no projeto dispensa extração/ASR para
        # qualquer subset, mesmo após split/corte ou se a faixa foi selecionada.
        # Silero independente ainda precisa extrair o sinal de áudio.
        for ch in chunks:
            if ch['clip'].id not in known_words or needs_vad:
                ch['extract']=self._stage('extract',ch['clip'].source,ch['a'],ch['b'],
                                          {'rate':16000,'mono':True,'format':'wav_pcm16'},
                                          {'source':ch['clip'].source,'start':ch['a'],'duration':ch['duration']})
            step()

        # Etapa 2: uma única instância Silero ONNX para todos os lotes não armazenados.
        def vad_payload(ch):
            vad_path=Path(opts.vad_model_path) if opts.vad_model_path else silero_vad_model_dir()
            params={'threshold':.5,'min_silence_ms':350,'speech_pad_ms':100,
                    'engine':'onnx-asr-0.12.0-silero-v6',
                    'model':[(f.name,f.stat().st_size,f.stat().st_mtime_ns)
                             for f in sorted(vad_path.rglob('*.onnx'))],
                    'audio_activity':{'frame_ms':100,'threshold_dbfs':-55.0,
                                      'min_active_ms':250,'bridge_ms':200}}
            return params,{'audio_path':ch['extract']['audio_path'],
                           'vad_model_path':str(vad_path),**params}
        if needs_vad:
            self._notify(f'Silero VAD • verificando {len(chunks)} trecho(s)')
            self._batch_stage(chunks,'vad',vad_payload,on_step=step)

        transcript_stage='parakeet'
        def parakeet_payload(ch):
            model_path=Path(opts.asr_model_path) if opts.asr_model_path else parakeet_tdt_model_dir()
            vad_path=Path(opts.vad_model_path) if opts.vad_model_path else silero_vad_model_dir()
            files=sorted(model_path.rglob('*.onnx')) if model_path.is_dir() else []
            if not files or not any('int8' in f.name.casefold() for f in files):
                raise FileNotFoundError(
                    f'Parakeet TDT v3 ONNX INT8 não instalado: {model_path}. '
                    'Execute scripts\\instalar_parakeet_tdt_v3.ps1.')
            if not vad_path.is_dir() or not any(vad_path.rglob('*.onnx')):
                raise FileNotFoundError(
                    f'Silero VAD ONNX não instalado: {vad_path}. '
                    'Execute scripts\\instalar_parakeet_tdt_v3.ps1.')
            model_fingerprint=[(f.name,f.stat().st_size,f.stat().st_mtime_ns) for f in files]
            speech=(ch.get('vad') or {}).get('speech',[])
            threads=max(1,min(16,int(opts.asr_threads or 4)))
            params={'engine':'parakeet-tdt-0.6b-v3','quantization':'int8',
                    'provider':'CPUExecutionProvider','model':model_fingerprint,
                    'onnx_asr':'0.12.0','language_mode':'multilingual-auto','threads':threads,
                    'speech_spans':speech,'timestamps':'token-frame',
                    'vad_model':[(f.name,f.stat().st_size,f.stat().st_mtime_ns)
                                 for f in sorted(vad_path.rglob('*.onnx'))]}
            return params,{'audio_path':ch['extract']['audio_path'],
                           'model_path':str(model_path),'vad_model_path':str(vad_path),
                           'speech_spans':speech,
                           'threads':threads}
        if needs_asr:
            pending=[ch for ch in chunks if ch['clip'].id not in known_words]
            asr_stage=f'Parakeet TDT v3 · ONNX INT8/CPU · {len(pending)} trecho(s) sem cobertura válida'
            if pending:
                asr_stage+=' · inferência por regiões de fala (Silero), sem fallback'
            self._notify(asr_stage)
            for ch in chunks:
                if ch['clip'].id in known_words:
                    step()  # checkpoint equivalente a um hit de transcrição prévia
            self._batch_stage(pending,transcript_stage,parakeet_payload,on_step=step)

        # Etapa 4: análise contextual recebe uma transcrição completa por clipe, apenas com
        # texto e IDs. Isso evita reiniciar o ASR por cada lote de áudio.
        # O worker divide texto longo em lotes do contexto, com sobreposição.
        # Timestamps e cortes são calculados localmente a partir do Parakeet.
        self._notify('Qwen • análise contextual dos textos' if needs_qwen else 'Preparando resultados solicitados')
        results=[]
        for clip_index,clip in enumerate(items,1):
            all_speech=[];all_audio_activity=[];all_words=[];all_segments=[];suggestions=[]
            belonging=[ch for ch in chunks if ch['clip'].id==clip.id]
            for ch in belonging:
                relative=ch['relative'];a=ch['a'];length=ch['duration'];index=ch['index']
                for span in ch.get('vad', {}).get('speech',[]):
                    all_speech.append({'start':relative+span['start'],
                                       'end':relative+span['end']})
                for span in ch.get('vad', {}).get('audio_activity',[]):
                    all_audio_activity.append({'start':relative+float(span['start']),
                                               'end':relative+float(span['end'])})
                tr=ch.get(transcript_stage, {'words': [], 'segments': []});normalized=[]
                if clip.id in known_words:
                    for word in known_words[clip.id]:
                        ws=float(word['source_start']);we=float(word['source_end'])
                        if ws < a-.005 or we > ch['b']+.005:continue
                        rec=dict(word)
                        rec.update({'start':round(ws-clip.start,4),
                                    'end':round(we-clip.start,4),
                                    'clip_id':clip.id})
                        normalized.append(rec)
                else:
                    for wi,w in enumerate(tr.get('words',[])):
                        local_s=max(0.,float(w['start']));local_e=min(length,float(w['end']))
                        if local_e-local_s<.01:continue
                        word_id=f'{clip.id[:8]}_c{index}_w{wi}'
                        normalized.append({'id':word_id,'start':round(relative+local_s,4),
                                           'end':round(relative+local_e,4),
                                           'source_start':round(a+local_s,4),
                                           'source_end':round(a+local_e,4),
                                           'source':str(Path(clip.source).resolve()),
                                           'clip_id':clip.id,'text':str(w['text']).strip(),
                                           # Parakeet TDT does not expose word
                                           # confidence in this adapter. Keep it
                                           # unknown instead of fabricating 0/1.
                                           'probability':w.get('probability')})
                all_words.extend(normalized)
                for seg in tr.get('segments',[]):
                    all_segments.append({'start':round(relative+float(seg['start']),3),
                                         'end':round(relative+float(seg['end']),3),
                                         'text':seg['text']})
            if needs_qwen:
                if all_words:
                    words=[{'id':w['id'],'text':w['text']} for w in all_words]
                    qwen_context,qwen_prompt_chars=qwen_limits()
                    qwen_timeout=qwen_stage_timeout(words,qwen_prompt_chars)
                    self._notify(f'Qwen • clipe {clip_index}/{len(items)} · '
                                 f'{len(words)} palavras · carregando lotes de texto')
                    def report_qwen_progress(event):
                        batch_total=max(1,int(event.get('total_batches',1)))
                        batch_done=max(0,min(batch_total,int(event.get('completed_batches',0))))
                        active=max(1,min(batch_total,int(event.get('active_batch',batch_done+1))))
                        detail=f'Qwen • clipe {clip_index}/{len(items)} · lote {active}/{batch_total}'
                        status=str(event.get('status') or '').strip()
                        if status:detail+=' · '+status
                        self._notify(detail)
                        if progress:
                            progress(min(total,count+batch_done/batch_total),total)
                    model_stat=model.stat()
                    cli_stat=cli.stat()
                    server_path=cli.with_name('llama-server.exe' if os.name=='nt' else 'llama-server')
                    try:
                        server_stat=server_path.stat()
                        server_fingerprint={'path':str(server_path.resolve()),
                                            'size':server_stat.st_size,
                                            'mtime_ns':server_stat.st_mtime_ns}
                    except OSError:
                        server_fingerprint={'path':str(server_path.resolve())}
                    qwen_params={'model_path':str(model.resolve()),'size':model_stat.st_size,
                                 'mtime_ns':model_stat.st_mtime_ns,
                                 'word_digest':digest(words),'prompt_version':6,
                                 'context_size':qwen_context,
                                 'prompt_max_chars':qwen_prompt_chars,
                                 'cli_path':str(cli.resolve()),'cli_size':cli_stat.st_size,
                                 'cli_mtime_ns':cli_stat.st_mtime_ns,
                                 'server':server_fingerprint,'action':mode,
                                 'max_tokens':320}
                    runtime_threads=opts.cpu_threads or qwen_threads(current_profile())
                    qwen=self._stage('qwen',clip.source,clip.start,clip.end,qwen_params,
                                     {'words':words,'qwen_model':str(model),'llama_cli':str(cli),
                                      'action':mode,'threads':runtime_threads,
                                      'context_size':qwen_context,
                                      'prompt_max_chars':qwen_prompt_chars,
                                      'max_tokens':320,'timeout':300,'prompt_version':6},
                                     timeout=qwen_timeout,on_progress=report_qwen_progress)
                    for proposal in qwen.get('removals',[]):
                        interval=qwen_removal_interval(proposal.get('word_ids'),all_words,
                                                       clip.end-clip.start)
                        if interval is None:continue
                        chosen=[word for word in all_words if word['id'] in proposal['word_ids']]
                        # Protege negações e quantidades independentemente da IA.
                        if any(w['text'].strip(' .,;?!').lower() in
                               ('não','nunca','jamais','sem','nenhum','nenhuma','nem') or
                               any(c.isdigit() for c in w['text']) for w in chosen):
                            continue
                        suggestions.append({'clip_id':clip.id,'title':clip.title,
                                            'a':interval[0],'b':interval[1],
                                            'type':'contexto','score':round(float(proposal['confidence'])*100),
                                            'note':'Qwen: '+str(proposal.get('reason','candidato'))[:140],
                                            'checked':False,'word_ids':proposal['word_ids']})
                step()
            if include_silence_suggestions:
                transcript_spans=[{'start':float(word['start']),'end':float(word['end'])}
                    for word in all_words if float(word.get('end',0))>float(word.get('start',0))]
                for finding in self._classify_voice_free_gaps(
                        all_speech,transcript_spans,all_audio_activity,
                        clip.end-clip.start,opts.min_silence,opts.silence_padding):
                    suggestions.append({'clip_id':clip.id,'title':clip.title,**finding})
            suggestions.sort(key=lambda f:(f['a'],f['b']))
            results.append({'clip_id':clip.id,'title':clip.title,
                            'source':str(Path(clip.source).resolve()),
                            'start':clip.start,'end':clip.end,'duration':clip.end-clip.start,
                            'words':all_words,'segments':all_segments,
                            'speech':all_speech,'audio_activity':all_audio_activity,
                            'suggestions':suggestions})
        return {'reports':results,'suggestions':[f for r in results for f in r['suggestions']],
                'cache_hits':self.cache_hits,'cache_misses':self.cache_misses,
                'stages':self.stages,'mode':mode}


def run_analysis(clips, options: AIOptions | None = None, progress=None, control=None, stage=None, mode='combined', known_words=None):
    return Pipeline(control=control,stage_callback=stage).analyze(clips, options=options,progress=progress,mode=mode,known_words=known_words)

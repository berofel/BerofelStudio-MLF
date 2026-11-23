"""Batata Quente 2.0: extrair -> Silero/ONNX -> Whisper/INT8 -> Qwen/GGUF.

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
from .model_paths import (whisper_model_dir, parakeet_model_path,
                          transcribe_binding_wheel, transcribe_runtime_dir)
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
    """Map a continuous Whisper word-ID span to source-relative clip seconds.

    Qwen never predicts timecodes. The editor uses Whisper's word timestamps:
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
    whisper_model: str = 'base'
    # Parakeet is opt-in. Faster-Whisper remains the stable default until a
    # user's own recordings and complete editor flow validate the alternative.
    asr_backend: str = 'faster-whisper'
    asr_device: str = 'cpu'
    asr_model_path: str = ''
    asr_binding_wheel: str = ''
    asr_library: str = ''
    language: str = 'pt'
    device: str = 'cpu'
    compute_type: str = 'int8'
    # Optional local domain hints passed to Faster-Whisper. Empty by default,
    # so existing transcription behavior and cache keys remain unchanged.
    whisper_hotwords: str = ''
    chunk_seconds: int = 120
    min_silence: float = 0.65
    silence_padding: float = 0.12
    enable_qwen: bool = False
    cpu_threads: int = 0           # 0 = escolha automática do motor; sem teto de RAM
    qwen_model: str = ''
    llama_cli: str = ''
    offline_only: bool = True


def transcript_model_identity(options: AIOptions) -> str:
    """Stable project-coverage identity; never reuse transcript across ASRs."""
    backend=str(getattr(options,'asr_backend','faster-whisper')).strip().lower()
    if backend=='parakeet-ultra':
        model=Path(options.asr_model_path) if options.asr_model_path else parakeet_model_path()
        library=Path(options.asr_library) if options.asr_library else transcribe_runtime_dir()/'transcribe.dll'
        wheel=Path(options.asr_binding_wheel) if options.asr_binding_wheel else transcribe_binding_wheel()
        def fingerprint(path):
            try:
                stat=path.stat()
                return f'{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}'
            except OSError:
                return str(path)
        revision='/'.join((fingerprint(model),fingerprint(library),fingerprint(wheel)))
        return f'parakeet-ultra-Q8_0/transcribe.cpp-0.4.2/{options.asr_device}/{revision}'
    return str(options.whisper_model)


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
        if stage not in ('vad','whisper','parakeet'):
            raise ValueError('Apenas VAD e os motores ASR possuem processamento em lote.')
        with tempfile.TemporaryDirectory(prefix='bfs_ai_batch_') as folder:
            folder=Path(folder)
            request=folder/'jobs.json'
            answer=folder/'batch.json'
            write_json(request,{'schema':CACHE_SCHEMA,'jobs':jobs})
            env=os.environ.copy()
            env['PYTHONPATH']=str(ROOT)+os.pathsep+env.get('PYTHONPATH','')
            command=[sys.executable,'-m','berofel.services.ai_worker',
                     stage+'_batch',str(request),str(answer)]
            launcher=control.popen if control else subprocess.Popen
            proc=launcher(command,cwd=str(ROOT),env=env,stdout=subprocess.DEVNULL,
                          stderr=subprocess.PIPE,creationflags=_windows_flags())
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
                error=proc.stderr.read().decode('utf-8','replace') if proc.stderr else ''
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
                if proc.stderr:proc.stderr.close()



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
            'context': (False, True, True),
        }
        if mode not in actions:
            raise ValueError('Ação de IA desconhecida: '+str(mode))
        needs_vad, needs_whisper, needs_qwen = actions[mode]
        if not 15 <= opts.chunk_seconds <= 1800:
            raise ValueError('Tamanho de lote inválido (15 a 1800 segundos).')
        if needs_qwen:
            cli=Path(opts.llama_cli) if opts.llama_cli else default_llama_cli()
            model=Path(opts.qwen_model) if opts.qwen_model else default_qwen_model()
            if not cli.is_file() or not model.is_file():
                raise FileNotFoundError('Qwen solicitado, mas llama-cli ou o modelo GGUF não foram encontrados. '
                                        'Execute INSTALAR_QWEN_OPCIONAL.bat ou configure os caminhos.')
        items=[c for c in clips if getattr(c,'kind','video') in ('audio','video') and c.duration>.05]
        chunks=[]
        for clip in items:
            index=0
            source_seconds = clip.end - clip.start
            while index*opts.chunk_seconds < source_seconds-.001:
                relative=index*opts.chunk_seconds
                a=clip.start+relative;b=min(clip.end,a+opts.chunk_seconds)
                chunks.append({'clip':clip,'index':index,'relative':relative,'a':a,'b':b,'duration':b-a})
                index+=1
        total=max(1,len(chunks)*(1 + int(needs_vad) + int(needs_whisper)) +
                  (len(items) if needs_qwen else 0))
        count=0
        def step():
            nonlocal count
            count+=1
            if progress:progress(count,total)

        self._notify(f'Preparando áudio e cobertura do cache • {len(chunks)} trecho(s)')
        # A transcrição já validada no projeto dispensa EXTRAIR/WHISPER para
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
            params={'threshold':.5,'min_silence_ms':350,'speech_pad_ms':100,'engine':'silero-onnx-v6'}
            return params,{'audio_path':ch['extract']['audio_path'],**params}
        if needs_vad:
            self._notify(f'Silero VAD • verificando {len(chunks)} trecho(s)')
            self._batch_stage(chunks,'vad',vad_payload,on_step=step)

        # Etapa 3: mantém um ASR selecionado durante todos os lotes pendentes.
        # Faster-Whisper segue como padrão; Parakeet é opt-in e tem cache/modelo
        # isolados para não contaminar cobertura nem resultados anteriores.
        asr_backend=str(getattr(opts,'asr_backend','faster-whisper')).strip().lower()
        if asr_backend not in ('faster-whisper','parakeet-ultra'):
            raise ValueError('Motor ASR inválido. Use faster-whisper ou parakeet-ultra.')
        transcript_stage='parakeet' if asr_backend=='parakeet-ultra' else 'whisper'
        model_fingerprint=None
        if asr_backend=='faster-whisper' and opts.whisper_model == 'base':
            model_file=whisper_model_dir()/'model.bin'
            if model_file.is_file():
                stat=model_file.stat()
                model_fingerprint=(stat.st_size,stat.st_mtime_ns)
        def whisper_payload(ch):
            runtime_threads=opts.cpu_threads or (6 if asr_backend=='parakeet-ultra'
                                                  else current_profile().ai_threads)
            if asr_backend=='parakeet-ultra':
                model_path=Path(opts.asr_model_path) if opts.asr_model_path else parakeet_model_path()
                wheel=Path(opts.asr_binding_wheel) if opts.asr_binding_wheel else transcribe_binding_wheel()
                library=Path(opts.asr_library) if opts.asr_library else transcribe_runtime_dir()/'transcribe.dll'
                if not model_path.is_file():
                    raise FileNotFoundError(f'Modelo Parakeet Ultra não instalado: {model_path}')
                if not wheel.is_file() or not library.is_file():
                    raise FileNotFoundError('Runtime Parakeet ausente. Execute scripts/install_parakeet_ultra.ps1.')
                model_stat=model_path.stat();library_stat=library.stat();wheel_stat=wheel.stat()
                params={'engine':'parakeet-ultra','model':'Q8_0',
                        'model_path':str(model_path.resolve()),
                        'model_fingerprint':(model_stat.st_size,model_stat.st_mtime_ns),
                        'runtime':'transcribe.cpp-0.4.2','library_size':library_stat.st_size,
                        'library_mtime_ns':library_stat.st_mtime_ns,
                        'binding_size':wheel_stat.st_size,'binding_mtime_ns':wheel_stat.st_mtime_ns,
                        'backend':opts.asr_device,'language':opts.language,
                        'threads':runtime_threads,'word_timestamps':True}
                payload={'audio_path':ch['extract']['audio_path'],'model_path':str(model_path),
                         'binding_wheel':str(wheel),'library':str(library),
                         'backend':opts.asr_device,'language':opts.language,
                         'threads':runtime_threads}
                return params,payload
            params={'model_revision':model_fingerprint,'model':opts.whisper_model,'lang':opts.language,
                    'compute':opts.compute_type,'device':opts.device,'threads':opts.cpu_threads,
                    'word_timestamps':True}
            payload={'audio_path':ch['extract']['audio_path'],
                           'model':opts.whisper_model,'language':opts.language,
                           'compute_type':opts.compute_type,'device':opts.device,
                           'cpu_threads':runtime_threads,'offline_only':opts.offline_only}
            hotwords=str(getattr(opts,'whisper_hotwords','') or '').strip()
            if hotwords:
                params['hotwords']=hotwords
                payload['hotwords']=hotwords
            return params,payload
        if needs_whisper:
            pending=[ch for ch in chunks if ch['clip'].id not in known_words]
            asr_name='Parakeet Ultra Q8' if asr_backend=='parakeet-ultra' else 'Faster-Whisper'
            self._notify(f'{asr_name} • {len(pending)} trecho(s) sem cobertura válida')
            for ch in chunks:
                if ch['clip'].id in known_words:
                    step()  # checkpoint equivalente a um hit de transcrição prévia
            self._batch_stage(pending,transcript_stage,whisper_payload,on_step=step)

        # Etapa 4: Qwen recebe uma transcrição completa por clipe, apenas com
        # texto e IDs. Isso evita reiniciar a IA por cada lote de áudio Whisper.
        # O worker divide texto longo em lotes do contexto, com sobreposição.
        # Timestamps e cortes são calculados localmente a partir do Whisper.
        self._notify('Qwen • análise contextual dos textos' if needs_qwen else 'Preparando resultados solicitados')
        results=[]
        for clip_index,clip in enumerate(items,1):
            all_speech=[];all_words=[];all_segments=[];suggestions=[]
            belonging=[ch for ch in chunks if ch['clip'].id==clip.id]
            for ch in belonging:
                relative=ch['relative'];a=ch['a'];length=ch['duration'];index=ch['index']
                for span in ch.get('vad', {}).get('speech',[]):
                    all_speech.append({'start':relative+span['start'],
                                       'end':relative+span['end']})
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
                                           'probability':float(w.get('probability') or 0.)})
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
            if needs_vad:
                # Silence means time without voice. Game ambience/effects do
                # not suppress a long candidate when Silero found no speech.
                for sa,sb in self._build_gaps(all_speech,clip.end-clip.start,
                                               opts.min_silence,opts.silence_padding):
                    suggestions.append({'clip_id':clip.id,'title':clip.title,
                                        'a':sa,'b':sb,'type':'silencio','score':100,
                                        'note':'Silero VAD: ausencia de voz (revise gameplay/musica)',
                                        'checked':False})
            suggestions.sort(key=lambda f:(f['a'],f['b']))
            results.append({'clip_id':clip.id,'title':clip.title,
                            'source':str(Path(clip.source).resolve()),
                            'start':clip.start,'end':clip.end,'duration':clip.end-clip.start,
                            'words':all_words,'segments':all_segments,
                            'speech':all_speech,'suggestions':suggestions})
        return {'reports':results,'suggestions':[f for r in results for f in r['suggestions']],
                'cache_hits':self.cache_hits,'cache_misses':self.cache_misses,
                'stages':self.stages,'mode':mode}


def run_analysis(clips, options: AIOptions | None = None, progress=None, control=None, stage=None, mode='combined', known_words=None):
    return Pipeline(control=control,stage_callback=stage).analyze(clips, options=options,progress=progress,mode=mode,known_words=known_words)

"""Testes de lógica e cache independentes de downloads de modelos (fakes explícitos)."""
import tempfile
from pathlib import Path
from types import SimpleNamespace
import json
import unittest
import wave
import os
import subprocess
from unittest.mock import patch

from berofel.core.project import Project, Clip
from berofel.services.ai_cache import CacheStore, CACHE_SCHEMA, write_json
from berofel.services.ai_pipeline import (AIOptions, Pipeline, StageRunner,
                                          qwen_stage_timeout, qwen_removal_interval,
                                          transcript_model_identity)
from berofel.services.subtitles import export_srt, merge_reports, build_cues, timeline_words
from berofel.services.ai_worker import (_parse_model_json, _qwen, _qwen_prompt_batches,
                                        _qwen_temp_directory, _qwen_server_completion, _vad)


class FakeStages:
    def __init__(self):
        self.calls=[]
        self.call_details=[]
        self.audio_activity=[]
    def __call__(self, stage, payload, output, **kw):
        self.calls.append(stage)
        self.call_details.append((stage,payload,kw))
        if stage == 'extract':
            target=Path(payload['audio_path']);target.parent.mkdir(parents=True,exist_ok=True)
            with wave.open(str(target),'wb') as file:
                file.setnchannels(1);file.setsampwidth(2);file.setframerate(16000)
                file.writeframes(b'\0\0'*100)
            result={'audio_path':str(target),'duration':payload['duration']}
        elif stage == 'vad':
            result={'speech':[{'start':.0,'end':5.0},{'start':7.0,'end':min(15.,payload.get('duration',15.))}],
                    'audio_activity':list(self.audio_activity),'duration':15.}
        elif stage == 'whisper':
            result={'words':[{'id':'w0_0','text':'Olá','start':.2,'end':.5},
                             {'id':'w0_1','text':'pessoal','start':.6,'end':1.1},
                             {'id':'w0_2','text':'é','start':1.3,'end':1.5}],
                    'segments':[{'start':0.,'end':1.6,'text':'Olá pessoal é'}],
                    'language':'pt','duration':15.}
        elif stage == 'parakeet':
            result={'words':[{'id':'p0_0','text':'Olá','start':.2,'end':.5,
                              'probability':0.}],
                    'segments':[{'start':.2,'end':.5,'text':'Olá','word_ids':['p0_0']}],
                    'language':'pt','model':'parakeet-ultra-Q8_0','duration':15.,
                    'timestamp_kind':'word','runtime':'0.4.2','backend':payload.get('backend')}
        elif stage == 'qwen':
            on_progress=kw.get('on_progress')
            if on_progress:
                on_progress({'completed_batches':1,'total_batches':2,
                             'active_batch':2,'status':'lote concluído'})
            result={'removals':[{'word_ids':[payload['words'][2]['id']],
                                 'reason':'muleta','confidence':.89}], 'engine':'fake Qwen'}
        else:raise ValueError(stage)
        write_json(Path(output),{'schema':CACHE_SCHEMA,'stage':stage,'result':result})
        return result


class AITest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source=Path(self.temp.name)/'original.mp4'
        self.source.write_bytes(b'original fixture')
        self.prj=Project()
        self.clip=Clip(source=str(self.source),start=20.,end=35.,title='Meio',
                       track_id=self.prj.tracks[1].id,timeline_start=4.)
        self.prj.add_clip(self.clip)
        self.other=Clip(source=str(self.source),start=0,end=10,title='Nao selecionado',
                        track_id=self.prj.tracks[1].id,timeline_start=40.)
        self.prj.add_clip(self.other)
        self.cache=CacheStore(Path(self.temp.name)/'cache')
        self.fake=FakeStages()

    def test_stage_runner_discards_stale_qwen_progress_before_retry(self):
        output=Path(self.temp.name)/'cache'/'qwen.json'
        output.parent.mkdir(parents=True)
        progress=output.with_suffix('.progress.json')
        write_json(progress,{'stage':'qwen_progress','completed_batches':4,
                             'total_batches':4,'active_batch':4,'status':'lote concluído'})
        events=[]
        class Control:
            def run(_self,command,**kwargs):
                request=json.loads(Path(command[-2]).read_text(encoding='utf-8'))
                self.assertFalse(progress.exists())
                self.assertEqual(request['progress_file'],str(progress))
                write_json(progress,{'schema':CACHE_SCHEMA,'stage':'qwen_progress','completed_batches':0,
                    'total_batches':1,'active_batch':1,'status':'processando lote'})
                write_json(Path(command[-1]),{'schema':CACHE_SCHEMA,'stage':'qwen',
                                               'result':{'removals':[]}})
                return SimpleNamespace(returncode=0,stdout='',stderr='')
        result=StageRunner()('qwen',{'words':[]},output,control=Control(),
                             on_progress=events.append)
        self.assertEqual(result,{'removals':[]})
        self.assertEqual([event['status'] for event in events],['processando lote'])
        self.assertFalse(progress.exists())
        self.assertFalse(output.with_suffix('.request.json').exists())

    def test_stage_runner_cleans_qwen_progress_when_worker_times_out(self):
        output=Path(self.temp.name)/'cache'/'qwen.json'
        output.parent.mkdir(parents=True)
        progress=output.with_suffix('.progress.json')
        class Control:
            def run(_self,command,**kwargs):
                request=json.loads(Path(command[-2]).read_text(encoding='utf-8'))
                write_json(Path(request['progress_file']),{'schema':CACHE_SCHEMA,'stage':'qwen_progress',
                    'completed_batches':1,'total_batches':3,'active_batch':2,
                    'status':'processando lote'})
                raise subprocess.TimeoutExpired(command,300)
        with self.assertRaises(subprocess.TimeoutExpired):
            StageRunner()('qwen',{'words':[]},output,control=Control(),
                          on_progress=lambda _event:None)
        self.assertFalse(progress.exists())
        self.assertFalse(output.with_suffix('.request.json').exists())

    def test_selection_and_batata_quente_cache(self):
        pipe=Pipeline(self.cache,self.fake)
        res=pipe.analyze([self.clip],AIOptions())
        self.assertEqual([x for x in self.fake.calls], ['extract','vad','whisper'])
        self.assertEqual(res['cache_misses'],3)
        self.assertEqual(res['cache_hits'],0)
        self.assertEqual(len(res['reports']),1)
        self.assertEqual(res['reports'][0]['clip_id'],self.clip.id)
        self.assertEqual(res['reports'][0]['words'][0]['source_start'],20.2)
        self.assertTrue(all(s['clip_id']==self.clip.id for s in res['suggestions']))
        assert any(s['type']=='silencio' for s in res['suggestions'])
        reread=Pipeline(self.cache,self.fake).analyze([self.clip],AIOptions())
        self.assertEqual(reread['cache_hits'],3)
        self.assertEqual(len(self.fake.calls),3)
        self.assertEqual(reread['reports'],res['reports'])

    def test_cache_invalidated_when_original_changes(self):
        Pipeline(self.cache,self.fake).analyze([self.clip],AIOptions())
        self.source.write_bytes(b'alterado!')
        p=Pipeline(self.cache,self.fake).analyze([self.clip],AIOptions())
        self.assertEqual(p['cache_misses'],3)

    def test_cleanup_hotwords_reach_whisper_and_only_invalidate_transcript_cache(self):
        base=Pipeline(self.cache,self.fake).analyze([self.clip],AIOptions(enable_qwen=False))
        self.assertEqual(base['cache_misses'],3)
        hinted=Pipeline(self.cache,self.fake).analyze([self.clip],AIOptions(
            enable_qwen=False,whisper_hotwords='Berofel Studio, timeline'))
        self.assertEqual(hinted['cache_misses'],1)
        call=[details for details in self.fake.call_details if details[0]=='whisper'][-1]
        self.assertEqual(call[1]['hotwords'],'Berofel Studio, timeline')

    def test_default_whisper_cache_key_remains_compatible_without_hotwords(self):
        base=Pipeline(self.cache,self.fake).analyze([self.clip],AIOptions(enable_qwen=False))
        again=Pipeline(self.cache,self.fake).analyze([self.clip],AIOptions(enable_qwen=False))
        self.assertEqual(base['cache_misses'],3)
        self.assertEqual(again['cache_misses'],0)
        self.assertEqual(len(self.fake.calls),3)

    def test_parakeet_is_opt_in_has_own_cache_and_uses_six_threads(self):
        model=Path(self.temp.name)/'parakeet.gguf';model.write_bytes(b'model')
        wheel=Path(self.temp.name)/'binding.whl';wheel.write_bytes(b'binding')
        library=Path(self.temp.name)/'transcribe.dll';library.write_bytes(b'runtime')
        opts=AIOptions(asr_backend='parakeet-ultra',asr_device='vulkan',
                       asr_model_path=str(model),asr_binding_wheel=str(wheel),
                       asr_library=str(library))
        result=Pipeline(self.cache,self.fake).analyze([self.clip],opts,mode='transcribe')
        self.assertEqual(self.fake.calls,['extract','parakeet'])
        call=next(item for item in self.fake.call_details if item[0]=='parakeet')
        self.assertEqual(call[1]['backend'],'vulkan')
        self.assertEqual(call[1]['threads'],6)
        self.assertEqual(result['reports'][0]['words'][0]['text'],'Olá')
        cached=Pipeline(self.cache,self.fake).analyze([self.clip],opts,mode='transcribe')
        self.assertEqual(cached['cache_misses'],0)
        self.assertEqual(cached['reports'],result['reports'])
        # A later default run must not reuse the Parakeet transcript.
        default=Pipeline(self.cache,self.fake).analyze([self.clip],AIOptions(),mode='transcribe')
        self.assertEqual(default['cache_misses'],1)
        self.assertEqual(self.fake.calls,['extract','parakeet','whisper'])

    def test_parakeet_coverage_identity_invalidates_when_native_runtime_changes(self):
        model=Path(self.temp.name)/'parakeet.gguf';model.write_bytes(b'model')
        wheel=Path(self.temp.name)/'binding.whl';wheel.write_bytes(b'binding')
        library=Path(self.temp.name)/'transcribe.dll';library.write_bytes(b'runtime-v1')
        opts=AIOptions(asr_backend='parakeet-ultra',asr_device='vulkan',
                       asr_model_path=str(model),asr_binding_wheel=str(wheel),
                       asr_library=str(library))
        first=transcript_model_identity(opts)
        library.write_bytes(b'runtime-v2-changed')
        self.assertNotEqual(first,transcript_model_identity(opts))

    def test_qwen_option_only_executes_when_model_available_and_after_whisper(self):
        cli=Path(self.temp.name)/'llama-cli.exe';cli.write_bytes(b'fake')
        model=Path(self.temp.name)/'model.gguf';model.write_bytes(b'fake')
        opts=AIOptions(enable_qwen=True,llama_cli=str(cli),qwen_model=str(model))
        stages=[]
        res=Pipeline(self.cache,self.fake,stage_callback=stages.append).analyze([self.clip],opts)
        self.assertEqual(self.fake.calls,['extract','vad','whisper','qwen'])
        _,qwen_payload,qwen_options=next(item for item in self.fake.call_details if item[0]=='qwen')
        self.assertEqual(qwen_options['timeout'],420)
        self.assertEqual(qwen_payload['timeout'],300)
        self.assertEqual(qwen_payload['max_tokens'],320)
        self.assertTrue(any('Qwen • clipe 1/1 ·' in label and 'lote' in label for label in stages))
        contextual=[f for f in res['suggestions'] if f['type']=='contexto']
        self.assertEqual(len(contextual),1)
        self.assertFalse(contextual[0]['checked'])
        self.assertIn('muleta',contextual[0]['note'])
        self.assertAlmostEqual(contextual[0]['a'],1.275)

    def test_qwen_batch_progress_advances_inside_the_inference_stage(self):
        cli=Path(self.temp.name)/'llama-cli.exe';cli.write_bytes(b'fake')
        model=Path(self.temp.name)/'model.gguf';model.write_bytes(b'fake')
        opts=AIOptions(enable_qwen=True,llama_cli=str(cli),qwen_model=str(model))
        progress=[];stages=[]
        Pipeline(self.cache,self.fake,stage_callback=stages.append).analyze(
            [self.clip],opts,progress=lambda done,total:progress.append((done,total)))
        self.assertIn((3.5,4),progress)
        self.assertIn((4,4),progress)
        self.assertTrue(any('lote 2/2' in label for label in stages))

    def test_qwen_receives_text_ids_for_whole_clip_and_maps_words_to_cut_time(self):
        cli=Path(self.temp.name)/'llama-cli.exe';cli.write_bytes(b'fake')
        model=Path(self.temp.name)/'model.gguf';model.write_bytes(b'fake')
        long_clip=Clip(source=str(self.source),start=0.,end=45.,title='Completo',
                       track_id=self.clip.track_id,timeline_start=0.)
        opts=AIOptions(enable_qwen=True,llama_cli=str(cli),qwen_model=str(model),chunk_seconds=15)
        result=Pipeline(self.cache,self.fake).analyze([long_clip],opts)
        qwen_calls=[detail for detail in self.fake.call_details if detail[0]=='qwen']
        self.assertEqual(len(qwen_calls),1)
        _,payload,kwargs=qwen_calls[0]
        self.assertEqual(set(payload['words'][0]),{'id','text'})
        self.assertEqual(len(payload['words']),9)
        self.assertNotIn('audio_path',payload)
        self.assertEqual(kwargs['timeout'],420)
        self.assertEqual(len([f for f in result['suggestions'] if f['type']=='contexto']),1)
        self.assertEqual(result['suggestions'][0]['word_ids'],[payload['words'][2]['id']])
        self.assertEqual(result['cache_misses'],10)

    def test_qwen_interval_formula_requires_contiguous_whisper_word_ids(self):
        words=[{'id':'a','start':1.0,'end':1.2},
               {'id':'b','start':1.25,'end':1.5},
               {'id':'c','start':2.0,'end':2.2}]
        self.assertEqual(qwen_removal_interval(['a','b'],words,10.),(.975,1.525))
        self.assertIsNone(qwen_removal_interval(['a','c'],words,10.))
        self.assertIsNone(qwen_removal_interval(['unknown'],words,10.))

    def test_silero_suggestions_keep_safety_padding_and_skip_short_pauses(self):
        gaps=Pipeline._build_gaps([
            {'start':1.,'end':2.},
            {'start':2.55,'end':3.},  # pausa curta: mantém para não acelerar a fala
            {'start':4.,'end':5.},
        ],duration=6.,minimum=.65,padding=.12)
        self.assertEqual(gaps,[(.12,.88),(3.12,3.88),(5.12,5.88)])

        overlapped=Pipeline._build_gaps([
            {'start':1.3,'end':2.4}, {'start':1.,'end':1.5},
            {'start':2.35,'end':2.8},
        ],duration=4.,minimum=.65,padding=.12)
        self.assertEqual(overlapped,[(.12,.88),(2.92,3.88)])

    def test_silence_removal_protects_audible_gameplay_activity_without_calling_it_speech(self):
        self.fake.audio_activity=[{'start':5.4,'end':6.6}]
        result=Pipeline(self.cache,self.fake).analyze(
            [self.clip],AIOptions(enable_qwen=False),mode='silence')
        report=result['reports'][0]
        self.assertEqual(self.fake.calls,['extract','vad'])
        # The activity is not mislabeled as voice, but it splits the candidate
        # silence into two short intervals that are below the cut threshold.
        self.assertEqual(report['speech'],[
            {'start':0.,'end':5.}, {'start':7.,'end':15.}])
        self.assertFalse([item for item in report['suggestions']
                          if item['type']=='silencio'])

    def test_vad_worker_detects_non_speech_rms_activity_once_with_speech(self):
        import math
        import struct
        from unittest.mock import patch
        audio=Path(self.temp.name)/'activity.wav'
        frames=[]
        for index in range(16000):
            # 0.45-0.80 s: audible game-like tone between Silero speech spans.
            sample=.025*math.sin(2*math.pi*440*index/16000) if 7200<=index<12800 else 0.
            frames.append(struct.pack('<h',round(sample*32767)))
        with wave.open(str(audio),'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000)
            wav.writeframes(b''.join(frames))
        with patch('faster_whisper.vad.get_speech_timestamps',return_value=[
                {'start':0,'end':6400},{'start':13600,'end':16000}]) as silero:
            result=_vad({'audio_path':str(audio)})
        self.assertEqual(silero.call_count,1)
        self.assertEqual(result['speech'],[{'start':0.0,'end':0.4},
                                           {'start':0.85,'end':1.0}])
        self.assertTrue(result['audio_activity'])
        interval=result['audio_activity'][0]
        self.assertLessEqual(interval['start'],.45)
        self.assertGreaterEqual(interval['end'],.80)

    def test_qwen_cache_invalidates_when_adaptive_context_changes(self):
        cli=Path(self.temp.name)/'llama-cli.exe';cli.write_bytes(b'fake')
        model=Path(self.temp.name)/'model.gguf';model.write_bytes(b'fake')
        opts=AIOptions(enable_qwen=True,llama_cli=str(cli),qwen_model=str(model))
        with patch('berofel.services.ai_pipeline.qwen_limits',return_value=(8192,16384)):
            first=Pipeline(self.cache,self.fake).analyze([self.clip],opts)
        self.assertEqual(first['cache_misses'],4)
        with patch('berofel.services.ai_pipeline.qwen_limits',return_value=(4096,8192)):
            second=Pipeline(self.cache,self.fake).analyze([self.clip],opts)
        self.assertEqual(second['cache_hits'],3)
        self.assertEqual(second['cache_misses'],1)
        self.assertEqual(self.fake.calls,['extract','vad','whisper','qwen','qwen'])

    def test_srt_after_removing_speech_and_saving_project(self):
        result=Pipeline(self.cache,self.fake).analyze([self.clip],AIOptions())
        merge_reports(self.prj,result['reports'])
        before=timeline_words(self.prj)
        self.assertEqual(len(before),3)
        self.assertAlmostEqual(before[0]['start'],4.2)
        # Corta a primeira palavra: as seguintes passam para 4.0, sem novo Whisper.
        self.prj.cut_intervals(self.clip.id,[(0.,.5)])
        after=timeline_words(self.prj)
        self.assertEqual(len(after),2)
        self.assertAlmostEqual(after[0]['start'],4.1)
        out=Path(self.temp.name)/'sub.srt'
        self.assertGreater(export_srt(self.prj,out),0)
        text=out.read_text(encoding='utf-8-sig')
        self.assertIn('00:00:04,100',text)
        self.assertNotIn('Olá',text)
        saved=Path(self.temp.name)/'project.berofel.json'
        self.prj.save(str(saved))
        reloaded=Project.load(str(saved))
        self.assertEqual(len(reloaded.transcripts),3)
        self.assertEqual(build_cues(reloaded),build_cues(self.prj))

    def test_large_selection_uses_one_model_process_for_multiple_batches(self):
        class FakeBatch(FakeStages):
            def __init__(self):
                super().__init__()
                self.batch_calls=[]
            def run_batch(self, stage, jobs, on_completed=None):
                self.batch_calls.append((stage,len(jobs)))
                for job in jobs:
                    self(stage,job['payload'],Path(job['output']))
                    if on_completed:on_completed()
        fake=FakeBatch()
        long=Clip(source=str(self.source),start=0,end=35,title='longa',
                  track_id=self.prj.tracks[0].id)
        opts=AIOptions(chunk_seconds=15)
        events=[]
        first=Pipeline(self.cache,fake).analyze([long],opts,
                                                  progress=lambda cur,total:events.append((cur,total)))
        self.assertEqual(fake.batch_calls,[('vad',3),('whisper',3)])
        self.assertEqual(first['cache_misses'],9)
        self.assertEqual(events[-1],(9,9))
        second=Pipeline(self.cache,fake).analyze([long],opts)
        self.assertEqual(second['cache_hits'],9)
        self.assertEqual(len(fake.calls),9)
        self.assertTrue(any(w['start']>=15 for w in first['reports'][0]['words']))

    def test_qwen_parser_safely_rejects_non_json(self):
        out=_parse_model_json('<think>pensando...</think>```json\n{"removals": []}\n```')
        self.assertEqual(out,{'removals':[]})
        with self.assertRaises(ValueError):_parse_model_json('sem estrutura')

    def test_qwen_parser_accepts_common_alternate_decision_keys_and_empty_array(self):
        self.assertEqual(_parse_model_json('Final: {"cuts":[{"ids":["w1"]}]}'),
                         {'removals':[{'ids':['w1']}]})
        self.assertEqual(_parse_model_json('[]'),{'removals':[]})

    def test_qwen_retries_one_malformed_response_with_stricter_json_prompt(self):
        cli=Path(self.temp.name)/'llama-cli.exe';cli.write_bytes(b'fake')
        model=Path(self.temp.name)/'model.gguf';model.write_bytes(b'fake')
        calls=[]
        def fake_run(command,**kwargs):
            prompt=Path(command[command.index('-f')+1]).read_text(encoding='utf-8')
            calls.append(prompt)
            content='Não há cortes.' if len(calls)==1 else (
                '{"removals":[{"word_ids":["w1","w2"],"reason":"repetição",'
                '"confidence":0.91}]}')
            return SimpleNamespace(returncode=0,stdout=content,stderr='')
        with patch('berofel.services.ai_worker.subprocess.run',side_effect=fake_run):
            result=_qwen({'llama_cli':str(cli),'qwen_model':str(model),
                'words':[{'id':'w1','text':'muito'},{'id':'w2','text':'muito'}],
                'threads':1,'context_size':4096,'prompt_max_chars':8192})
        self.assertEqual(len(calls),2)
        self.assertIn('Responda somente com um objeto JSON válido',calls[1])
        self.assertEqual(result['removals'][0]['word_ids'],['w1','w2'])

    def test_qwen_reports_bounded_failure_after_retry_without_echoing_transcript(self):
        cli=Path(self.temp.name)/'llama-cli.exe';cli.write_bytes(b'fake')
        model=Path(self.temp.name)/'model.gguf';model.write_bytes(b'fake')
        calls=[]
        def fake_run(command,**kwargs):
            calls.append(command)
            return SimpleNamespace(returncode=0,stdout='texto secreto sem JSON',stderr='')
        with patch('berofel.services.ai_worker.subprocess.run',side_effect=fake_run):
            with self.assertRaisesRegex(ValueError,'mesmo após uma retentativa') as error:
                _qwen({'llama_cli':str(cli),'qwen_model':str(model),
                    'words':[{'id':'w1','text':'texto secreto'}],
                    'threads':1,'context_size':4096,'prompt_max_chars':8192})
        self.assertEqual(len(calls),2)
        self.assertIn('lote 1/1',str(error.exception))
        self.assertNotIn('texto secreto',str(error.exception))

    def test_qwen_parser_prefers_final_answer_over_echoed_prompt_example(self):
        echoed='Prompt: {"removals":[{"word_ids":["w0_1"],"reason":"...","confidence":0.8}]}\n'
        answer='{"removals":[{"word_ids":["actual1","actual2"],"confidence":0.9}]}'
        self.assertEqual(_parse_model_json(echoed+answer),{
            'removals':[{'word_ids':['actual1','actual2'],'confidence':0.9}]})

    def test_qwen_parser_recovers_complete_items_from_truncated_final_json(self):
        echoed='Prompt: {"removals":[{"word_ids":["w0_1"],"reason":"...","confidence":0.8}]}\n'
        partial='{"removals":[{"word_ids":["safe1","safe2"],"confidence":0.91},'
        partial+='{"word_ids":["cutoff1"],"confidence":'
        self.assertEqual(_parse_model_json(echoed+partial),{
            'removals':[{'word_ids':['safe1','safe2'],'confidence':0.91}]})

    def test_qwen_parser_keeps_complete_decisions_before_token_limit_truncation(self):
        partial='{"removals":[{"word_ids":["w1","w2"],"confidence":0.91},'
        partial+='{"word_ids":["w3","w4"],"confidence":'
        self.assertEqual(_parse_model_json(partial),{
            'removals':[{'word_ids':['w1','w2'],'confidence':0.91}]})

    def test_qwen_long_transcript_uses_short_command_and_bounded_prompt_files(self):
        cli=Path(self.temp.name)/'llama-cli.exe';cli.write_bytes(b'fake')
        model=Path(self.temp.name)/'model.gguf';model.write_bytes(b'fake')
        words=[{'id':f'w{i:04d}','text':('transcrição muito longa para validar envio robusto ' * 2)}
               for i in range(800)]
        prompts=[];commands=[]
        def fake_run(command,**kwargs):
            commands.append(command)
            self.assertIn('-f',command)
            self.assertNotIn('-p',command)
            prompts.append(Path(command[command.index('-f')+1]).read_text(encoding='utf-8'))
            return SimpleNamespace(returncode=0,stdout='{"removals":[]}',stderr='')
        with patch('berofel.services.ai_worker.subprocess.run',side_effect=fake_run):
            result=_qwen({'llama_cli':str(cli),'qwen_model':str(model),'words':words,'threads':2,
                          'context_size':8192,'prompt_max_chars':20000})
        self.assertGreater(len(commands),1)
        self.assertTrue(all(sum(len(arg) for arg in command)<2000 for command in commands))
        self.assertTrue(all(len(prompt)<=20000 for prompt in prompts))
        self.assertTrue(all(command[command.index('-c')+1]=='8192' for command in commands))
        self.assertTrue(all(command[command.index('-n')+1]=='320' for command in commands))
        seen_ids=[]
        for prompt in prompts:
            payload=json.loads(prompt.rpartition('Texto:\n')[2])
            seen_ids.extend(word['id'] for word in payload)
        self.assertEqual(set(seen_ids),{word['id'] for word in words})
        self.assertGreater(len(seen_ids),len(words))  # sobreposição para contexto nas bordas
        self.assertEqual(result['removals'],[])

    def test_qwen_resumes_completed_prompt_batches_from_persistent_cache(self):
        cli=Path(self.temp.name)/'llama-cli.exe';cli.write_bytes(b'fake')
        model=Path(self.temp.name)/'model.gguf';model.write_bytes(b'fake')
        checkpoint_dir=Path(self.temp.name)/'qwen_batches'
        progress_file=Path(self.temp.name)/'qwen_progress.json'
        words=[{'id':f'w{i}','text':f'palavra{i}'} for i in range(6)]
        batches=[words[:2],words[2:4],words[4:]]
        calls=[]
        def fake_run(command,**kwargs):
            calls.append(command)
            if len(calls)==2:
                raise RuntimeError('falha simulada no segundo lote')
            return SimpleNamespace(returncode=0,stdout='{"removals":[]}',stderr='')
        payload={'llama_cli':str(cli),'qwen_model':str(model),'words':words,'threads':1,
                 'context_size':4096,'prompt_max_chars':8192,
                 'checkpoint_dir':str(checkpoint_dir),'progress_file':str(progress_file)}
        with patch('berofel.services.ai_worker._qwen_prompt_batches',return_value=batches), \
             patch('berofel.services.ai_worker.subprocess.run',side_effect=fake_run):
            with self.assertRaisesRegex(RuntimeError,'falha simulada'):
                _qwen(payload)
            self.assertTrue((checkpoint_dir/'batch_00000.json').is_file())
            result=_qwen(payload)
        self.assertEqual(len(calls),4)  # a primeira resposta concluída não é calculada de novo
        self.assertEqual(result['removals'],[])
        progress=json.loads(progress_file.read_text(encoding='utf-8'))
        self.assertEqual(progress['stage'],'qwen_progress')
        self.assertEqual(progress['completed_batches'],3)
        self.assertEqual(progress['total_batches'],3)

    def test_qwen_checkpoint_is_invalidated_when_text_changes_but_ids_stay_equal(self):
        cli=Path(self.temp.name)/'llama-cli.exe';cli.write_bytes(b'fake')
        model=Path(self.temp.name)/'model.gguf';model.write_bytes(b'fake')
        checkpoint_dir=Path(self.temp.name)/'qwen_batches'
        calls=[]
        def fake_run(command,**kwargs):
            calls.append(command)
            return SimpleNamespace(returncode=0,stdout='{"removals":[]}',stderr='')
        base={'llama_cli':str(cli),'qwen_model':str(model),'threads':1,
              'context_size':4096,'prompt_max_chars':8192,
              'checkpoint_dir':str(checkpoint_dir)}
        with patch('berofel.services.ai_worker.subprocess.run',side_effect=fake_run):
            _qwen({**base,'words':[{'id':'stable-id','text':'texto original'}]})
            _qwen({**base,'words':[{'id':'stable-id','text':'texto revisado'}]})
        self.assertEqual(len(calls),2)

    def test_qwen_checkpoint_is_invalidated_when_backend_binary_changes(self):
        cli=Path(self.temp.name)/'llama-cli.exe';cli.write_bytes(b'fake')
        model=Path(self.temp.name)/'model.gguf';model.write_bytes(b'fake')
        checkpoint_dir=Path(self.temp.name)/'qwen_batches'
        calls=[]
        def fake_run(command,**kwargs):
            calls.append(command)
            return SimpleNamespace(returncode=0,stdout='{"removals":[]}',stderr='')
        payload={'llama_cli':str(cli),'qwen_model':str(model),'threads':1,
                 'context_size':4096,'prompt_max_chars':8192,
                 'checkpoint_dir':str(checkpoint_dir),
                 'words':[{'id':'stable-id','text':'mesmo texto'}]}
        with patch('berofel.services.ai_worker.subprocess.run',side_effect=fake_run):
            _qwen(payload)
            cli.write_bytes(b'new binary build')
            _qwen(payload)
        self.assertEqual(len(calls),2)

    def test_qwen_reuses_one_local_server_for_context_batches(self):
        cli=Path(self.temp.name)/'llama-cli.exe';cli.write_bytes(b'fake')
        server=cli.with_name('llama-server.exe');server.write_bytes(b'fake')
        model=Path(self.temp.name)/'model.gguf';model.write_bytes(b'fake')
        progress_file=Path(self.temp.name)/'qwen_progress.json'
        words=[{'id':'w0','text':'fala'}]
        with patch('berofel.services.ai_worker._start_qwen_server',
                   return_value=('server-process','http://127.0.0.1:45678','temporary-key')) as start, \
             patch('berofel.services.ai_worker._qwen_server_completion',
                   return_value='{"removals":[]}') as complete, \
             patch('berofel.services.ai_worker._stop_qwen_server') as stop, \
             patch('berofel.services.ai_worker.subprocess.run') as cli_run:
            result=_qwen({'llama_cli':str(cli),'qwen_model':str(model),'words':words,
                          'threads':2,'context_size':4096,'prompt_max_chars':8192,
                          'progress_file':str(progress_file)})
        start.assert_called_once()
        complete.assert_called_once()
        stop.assert_called_once_with('server-process')
        cli_run.assert_not_called()
        self.assertEqual(result['transport'],'llama-server')
        progress=json.loads(progress_file.read_text(encoding='utf-8'))
        self.assertIsInstance(progress['model_load_seconds'],float)
        self.assertEqual(len(progress['completed_batch_seconds']),1)
        self.assertGreaterEqual(progress['completed_batch_seconds'][0],0.)

    def test_qwen_server_reuses_common_prompt_prefix(self):
        captured={}
        class Response:
            def __enter__(self):return self
            def __exit__(self,*_args):return False
            def read(self):return b'{"content":"{\\"removals\\":[]}"}'
        def fake_open(request,timeout):
            captured['body']=json.loads(request.data)
            captured['timeout']=timeout
            return Response()
        with patch('urllib.request.urlopen',side_effect=fake_open):
            output=_qwen_server_completion('http://127.0.0.1:1234','test-key',
                                           'fixed prefix + batch',320,300)
        self.assertEqual(output,'{"removals":[]}')
        self.assertTrue(captured['body']['cache_prompt'])
        self.assertEqual(captured['body']['temperature'],0)
        self.assertEqual(captured['body']['seed'],42)
        self.assertEqual(captured['timeout'],300)

    def test_qwen_long_job_timeout_scales_by_prompt_batches_and_is_capped(self):
        one=[{'id':f'w{i}','text':'fala curta'} for i in range(100)]
        many=[{'id':f'w{i}','text':'palavra transcrita com algum contexto'} for i in range(12000)]
        one_timeout=qwen_stage_timeout(one,16384)
        many_timeout=qwen_stage_timeout(many,4096)
        self.assertEqual(one_timeout,420)
        self.assertGreater(many_timeout,one_timeout)
        self.assertLessEqual(many_timeout,1080)

    def test_qwen_prompt_uses_short_local_appdata_temp_root(self):
        cli=Path(self.temp.name)/'llama-cli.exe';cli.write_bytes(b'fake')
        model=Path(self.temp.name)/'model.gguf';model.write_bytes(b'fake')
        profile=Path(self.temp.name)/'perfil'
        prompt_paths=[]
        commands=[]
        def fake_run(command,**kwargs):
            commands.append(command)
            prompt_paths.append(Path(command[command.index('-f')+1]))
            return SimpleNamespace(returncode=0,stdout='{"removals":[]}',stderr='')
        with patch.dict(os.environ,{'LOCALAPPDATA':str(profile)}), \
             patch('berofel.services.ai_worker.subprocess.run',side_effect=fake_run):
            _qwen({'llama_cli':str(cli),'qwen_model':str(model),
                   'words':[{'id':'w0','text':'teste'}],'threads':1})
        self.assertEqual(len(prompt_paths),1)
        self.assertEqual(commands[0][commands[0].index('--seed')+1],'42')
        self.assertEqual(prompt_paths[0].parent.parent.name.casefold(),'tmp')
        self.assertTrue(os.path.samefile(prompt_paths[0].parent.parent,profile/'BFS'/'tmp'))

    def test_qwen_temp_path_falls_back_when_local_appdata_is_not_writable(self):
        with tempfile.TemporaryDirectory() as profile:
            blocked=Path(profile)/'BFS'/'tmp'
            original_mkdir=Path.mkdir
            def controlled_mkdir(path,*args,**kwargs):
                if path==blocked:
                    raise PermissionError('perfil protegido')
                return original_mkdir(path,*args,**kwargs)
            with patch.dict(os.environ,{'LOCALAPPDATA':profile}), \
                 patch.object(Path,'mkdir',new=controlled_mkdir):
                with _qwen_temp_directory() as folder:
                    self.assertEqual(Path(folder).parent,Path(tempfile.gettempdir()))
                    self.assertTrue(Path(folder).is_dir())
            self.assertFalse(Path(folder).exists())

    def test_qwen_reports_windows_206_with_component_path_lengths(self):
        cli=Path(self.temp.name)/'llama-cli.exe';cli.write_bytes(b'fake')
        model=Path(self.temp.name)/'model.gguf';model.write_bytes(b'fake')
        error=OSError('nome do arquivo muito grande')
        error.winerror=206
        words=[{'id':'w0','text':'teste'}]
        with patch('berofel.services.ai_worker.subprocess.run',side_effect=error):
            with self.assertRaisesRegex(RuntimeError,'WinError 206.*llama-cli=.*modelo GGUF=.*prompt='):
                _qwen({'llama_cli':str(cli),'qwen_model':str(model),'words':words,'threads':1})

    def test_qwen_short_path_is_identity_off_windows(self):
        from berofel.services.ai_worker import _windows_short_path
        with patch('berofel.services.ai_worker.os.name','posix'):
            self.assertEqual(_windows_short_path(r'C:\pasta longa\modelo.gguf'),
                             r'C:\pasta longa\modelo.gguf')

    def test_qwen_prompt_batches_preserve_single_oversized_word(self):
        words=[{'id':'first','text':'normal'}, {'id':'long','text':'x'*20000},
               {'id':'last','text':'normal'}]
        batches=_qwen_prompt_batches(words,max_chars=500,overlap=1)
        self.assertEqual([word['id'] for batch in batches for word in batch],
                         ['first','long','last'])

    def test_qwen_discards_malformed_or_out_of_order_word_ids(self):
        cli=Path(self.temp.name)/'llama-cli.exe';cli.write_bytes(b'fake')
        model=Path(self.temp.name)/'model.gguf';model.write_bytes(b'fake')
        words=[{'id':f'w{i}','text':text} for i,text in enumerate(('uma','frase','de','teste'))]
        stdout=json.dumps({'removals':[
            {'word_ids':['w1','w0'],'reason':'fora de ordem','confidence':.99},
            {'word_ids':[{'id':'w1'}],'reason':'tipo inválido','confidence':.99},
            {'word_ids':['w1'],'reason':'confiança inválida','confidence':'alta'},
            {'word_ids':['w2'],'reason':'válida','confidence':.8},
        ]},ensure_ascii=False)
        with patch('berofel.services.ai_worker.subprocess.run',
                   return_value=SimpleNamespace(returncode=0,stdout=stdout,stderr='')):
            result=_qwen({'llama_cli':str(cli),'qwen_model':str(model),'words':words,'threads':1})
        self.assertEqual(result['removals'],[{'word_ids':['w2'],'reason':'válida','confidence':.8}])

    def test_cache_does_not_mix_two_source_intervals(self):
        Pipeline(self.cache,self.fake).analyze([self.clip],AIOptions())
        clone=Clip(source=str(self.source),start=21.,end=29.,track_id=self.prj.tracks[0].id)
        p=Pipeline(self.cache,self.fake).analyze([clone],AIOptions())
        self.assertEqual(p['cache_misses'],3)


if __name__ == '__main__': unittest.main()

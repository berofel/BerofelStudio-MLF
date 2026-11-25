"""0.8: integração do alcance, dependências isoladas e legendas no modelo."""
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
import wave

from berofel.core.project import Project, Clip
from berofel.services.action_scope import (ScopeSpec,resolve_scope,scope_summary,
    local_to_original_proposal,scope_is_still_valid,selected_proposals_conflict)
from berofel.services.ai_cache import CacheStore,CACHE_SCHEMA,write_json
from berofel.services.ai_pipeline import Pipeline, AIOptions
from berofel.services.caption_actions import (create_manual_caption,create_auto_captions,
    scoped_cues,export_scoped_srt)
from berofel.services.subtitles import merge_reports


class FakeModels:
    def __init__(self):self.calls=[]
    def __call__(self,stage,payload,output,**kwargs):
        self.calls.append(stage)
        if stage=='extract':
            target=Path(payload['audio_path'])
            target.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(target),'wb') as wav:
                wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000)
                wav.writeframes(b'\0\0'*160)
            result={'audio_path':str(target),'duration':payload['duration']}
        elif stage=='vad':
            result={'speech':[{'start':1.0,'end':4.0}],
                    'duration':float(payload.get('duration',6))}
        elif stage=='parakeet':
            result={'words':[{'id':'a','start':1.0,'end':1.5,'text':'Olá'},
                             {'id':'b','start':2.0,'end':2.3,'text':'amigos'}],
                    'segments':[],'language':'pt','duration':6.0}
        elif stage=='qwen':
            result={'removals':[{'word_ids':[payload['words'][-1]['id']],
                                 'reason':'teste','confidence':.93}]}
        else:raise AssertionError(stage)
        write_json(Path(output),{'schema':CACHE_SCHEMA,'stage':stage,'result':result})
        return result


class ModularActionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.file=Path(self.tmp.name)/'video.mp4';self.file.write_bytes(b'midia para cache')
        self.prj=Project()
        self.a=Clip(source=str(self.file),start=10,end=30,title='A',
                    track_id=self.prj.tracks[0].id,timeline_start=2,speed=2)
        self.b=Clip(source=str(self.file),start=40,end=55,title='B',
                    track_id=self.prj.tracks[0].id,timeline_start=17)
        self.c=Clip(source=str(self.file),start=60,end=69,title='C',
                    track_id=self.prj.tracks[1].id,timeline_start=5)
        for c in (self.a,self.b,self.c):self.prj.add_clip(c)
        self.fake=FakeModels();self.cache=CacheStore(Path(self.tmp.name)/'cache')
        self.model_dir=Path(self.tmp.name)/'parakeet'
        self.model_dir.mkdir();(self.model_dir/'model.int8.onnx').write_bytes(b'model')
        self.vad_dir=Path(self.tmp.name)/'silero'
        self.vad_dir.mkdir();(self.vad_dir/'silero.onnx').write_bytes(b'vad')
        for target,value in (
            ('berofel.services.ai_pipeline.parakeet_tdt_model_dir',self.model_dir),
            ('berofel.services.ai_pipeline.silero_vad_model_dir',self.vad_dir),
        ):
            mocked=patch(target,return_value=value)
            mocked.start();self.addCleanup(mocked.stop)

    def test_conflicting_review_cuts_are_detected_per_clip(self):
        self.assertTrue(selected_proposals_conflict([
            {'clip_id':'same','a':1.,'b':2.}, {'clip_id':'same','a':1.5,'b':2.5}]))
        self.assertFalse(selected_proposals_conflict([
            {'clip_id':'one','a':1.,'b':2.}, {'clip_id':'two','a':1.5,'b':2.5}]))
        self.assertFalse(selected_proposals_conflict([
            {'clip_id':'same','a':1.,'b':2.}, {'clip_id':'same','a':2.,'b':3.}]))

    def test_one_selected_and_multiple_across_tracks(self):
        clips,targets=resolve_scope(self.prj,ScopeSpec('one',(self.a.id,)))
        self.assertEqual([c.id for c in clips],[self.a.id])
        with self.assertRaises(ValueError):
            resolve_scope(self.prj,ScopeSpec('one',(self.a.id,self.c.id)))
        clips,_=resolve_scope(self.prj,ScopeSpec('selected',(self.a.id,self.c.id)))
        self.assertEqual({c.id for c in clips},{self.a.id,self.c.id})

    def test_scope_analyzes_a_linked_av_pair_once_but_respects_audio_only_selection(self):
        self.a.group_id='linked_scope'
        audio=self.prj.add_clip(Clip(source=self.a.source,start=self.a.start,end=self.a.end,
            track_id=self.prj.tracks[1].id,kind='audio',timeline_start=self.a.timeline_start,
            speed=self.a.speed,group_id=self.a.group_id))

        clips,targets=resolve_scope(self.prj,ScopeSpec('selected',(self.a.id,audio.id)))
        self.assertEqual(len(clips),1)
        self.assertEqual(len(targets),1)

        audio_only,_=resolve_scope(self.prj,ScopeSpec('selected',(audio.id,)))
        self.assertEqual([clip.id for clip in audio_only],[audio.id])

    def test_entire_track_and_project(self):
        clips,_=resolve_scope(self.prj,ScopeSpec('track',track_id=self.prj.tracks[0].id))
        self.assertEqual({c.id for c in clips},{self.a.id,self.b.id})
        clips,_=resolve_scope(self.prj,ScopeSpec('project'))
        self.assertEqual(len(clips),3)

    def test_interval_in_selected_track_only(self):
        clips,targets=resolve_scope(self.prj,ScopeSpec('track_interval',
            track_id=self.prj.tracks[0].id,in_time=5,out_time=8))
        self.assertEqual([c.id for c in clips],[self.a.id])
        self.assertEqual((clips[0].start,clips[0].end),(16,22))
        self.assertEqual(len(targets),1)

    def test_interval_does_not_touch_outside_or_modify_original(self):
        originals=[(c.id,c.start,c.end,c.timeline_start) for c in self.prj.clips]
        clips,targets=resolve_scope(self.prj,ScopeSpec('interval',in_time=5,out_time=8))
        self.assertEqual({c.id for c in clips},{self.a.id,self.c.id})
        cut_a=next(c for c in clips if c.id==self.a.id)
        self.assertEqual((cut_a.start,cut_a.end,cut_a.timeline_start),(16,22,5))
        self.assertEqual([(c.id,c.start,c.end,c.timeline_start) for c in self.prj.clips],originals)
        target=next(t for t in targets if t.original_id==self.a.id)
        converted=local_to_original_proposal({'clip_id':self.a.id,'a':.5,'b':2.0},target,self.a)
        self.assertAlmostEqual(converted['a'],6.5)
        self.assertAlmostEqual(converted['b'],8.)
        # revisão do editor transforma segundos de fonte em segundos de playback:
        self.assertAlmostEqual(converted['a']/self.a.speed,3.25)
        original_snapshot={self.a.id:replace(self.a)}
        self.assertTrue(scope_is_still_valid(self.prj,original_snapshot,[target]))
        self.a.speed=3
        self.assertFalse(scope_is_still_valid(self.prj,original_snapshot,[target]))

    def test_silero_only_and_parakeet_only_with_shared_cache(self):
        selected,_=resolve_scope(self.prj,ScopeSpec('one',(self.a.id,)))
        opts=AIOptions(chunk_seconds=20)
        first=Pipeline(self.cache,self.fake).analyze(selected,opts,mode='silence')
        self.assertEqual(self.fake.calls,['extract','vad'])
        self.assertEqual(first['reports'][0]['words'],[])
        self.assertTrue(first['suggestions'])
        transcribe=Pipeline(self.cache,self.fake).analyze(selected,opts,mode='transcribe')
        self.assertEqual(self.fake.calls,['extract','vad','parakeet'])
        self.assertEqual(transcribe['cache_hits'],2)
        self.assertEqual(transcribe['cache_misses'],1)
        self.assertFalse(transcribe['suggestions'])
        self.assertEqual(transcribe['reports'][0]['words'][0]['source_start'],11.)
        subtitles=Pipeline(self.cache,self.fake).analyze(selected,opts,mode='subtitles')
        self.assertEqual(subtitles['cache_hits'],3)
        self.assertEqual(subtitles['cache_misses'],0)

    def test_qwen_without_vad_for_fillers_and_context_readonly(self):
        cli=Path(self.tmp.name)/'llama.exe';cli.write_bytes(b'cli')
        model=Path(self.tmp.name)/'model.gguf';model.write_bytes(b'model')
        opts=AIOptions(chunk_seconds=20,qwen_model=str(model),llama_cli=str(cli))
        selected,_=resolve_scope(self.prj,ScopeSpec('one',(self.a.id,)))
        first=Pipeline(self.cache,self.fake).analyze(selected,opts,mode='fillers')
        self.assertEqual(self.fake.calls,['extract','vad','parakeet','qwen'])
        self.assertEqual(len(first['suggestions']),1)
        second=Pipeline(self.cache,self.fake).analyze(selected,opts,mode='context')
        self.assertEqual(self.fake.calls,['extract','vad','parakeet','qwen','qwen'])
        self.assertEqual(second['cache_hits'],3)

    def test_linked_video_audio_shares_same_batch_stage_and_progress(self):
        audio=replace(self.a,id='linked_audio',kind='audio',track_id=self.prj.tracks[1].id)
        counts=[]
        result=Pipeline(self.cache,self.fake).analyze([self.a,audio],
            AIOptions(chunk_seconds=20),mode='transcribe',
            progress=lambda done,total:counts.append((done,total)))
        self.assertEqual(len(result['reports']),2)
        self.assertEqual(self.fake.calls.count('extract'),1)
        self.assertEqual(self.fake.calls.count('parakeet'),1)
        self.assertEqual(counts[-1],(6,6))
        self.assertEqual(result['cache_misses'],3)

    def test_source_duration_in_speed_10x_clip_is_fully_covered(self):
        speed=replace(self.a,speed=10,start=0,end=60)
        p=Pipeline(self.cache,self.fake).analyze([speed],AIOptions(chunk_seconds=15),mode='transcribe')
        self.assertEqual(p['cache_misses'],12)
        self.assertEqual(p['cache_hits'],0)
        self.assertEqual(sum(s=='parakeet' for s in self.fake.calls),4)
        self.assertEqual(p['reports'][0]['words'][-2]['source_start'],46.)

    def test_auto_captions_scoped_and_idempotent(self):
        clipped,targets=resolve_scope(self.prj,ScopeSpec('interval',in_time=5,out_time=8))
        result=Pipeline(self.cache,self.fake).analyze(clipped,AIOptions(chunk_seconds=15),mode='subtitles')
        merge_reports(self.prj,result['reports'])
        cues=scoped_cues(self.prj,targets)
        self.assertTrue(cues)
        self.assertTrue(all(5<=a<b<=8 for a,b,_ in cues))
        previous_count=len(self.prj.clips)
        added=create_auto_captions(self.prj,targets)
        self.assertEqual(len(self.prj.clips),previous_count+len(added))
        self.assertTrue(all(c.kind=='text' and c.generated_by=='auto_caption' for c in added))
        self.assertEqual(create_auto_captions(self.prj,targets),[])
        manual=create_manual_caption(self.prj,'Texto livre',7.0,7.8)
        self.assertEqual(manual.generated_by,'manual_caption')
        srt=Path(self.tmp.name)/'selecao.srt'
        n=export_scoped_srt(self.prj,targets,srt)
        self.assertGreater(n,0)
        self.assertIn('00:00:05',srt.read_text(encoding='utf-8-sig'))
        saved=Path(self.tmp.name)/'saved.berofel.json'
        self.prj.save(str(saved))
        loaded=Project.load(str(saved))
        self.assertEqual(len(loaded.clips),len(self.prj.clips))
        self.assertTrue(any(c.generated_by=='manual_caption' for c in loaded.clips))

    def test_manual_caption_exports_as_real_mp4(self):
        from berofel.services.export_multitrack import export_project
        project=Project(width=320,height=180,fps=15)
        create_manual_caption(project,'Olá! Legenda livre.',0.,1.0)
        dest=Path(self.tmp.name)/'subtitle_test.mp4'
        export_project(project,str(dest))
        self.assertTrue(dest.is_file())
        self.assertGreater(dest.stat().st_size,2500)

    def test_manual_captions_have_no_ai_requirement(self):
        before=len(self.prj.clips)
        clip=create_manual_caption(self.prj,'Olá, pessoal!',1.,3.)
        self.assertEqual(len(self.prj.clips),before+1)
        self.assertEqual(clip.kind,'text')
        self.assertEqual(self.fake.calls,[])
        with self.assertRaises(ValueError):create_manual_caption(self.prj,' ',1.,3.)

    def test_auto_captions_follow_speed_move_and_surviving_cut(self):
        project=Project()
        video=project.add_clip(Clip(source=str(self.file),start=10,end=30,
            kind='video',track_id=project.tracks[0].id,timeline_start=2,speed=2))
        project.transcripts=[{'source':str(self.file.resolve()),'source_start':12.,
                              'source_end':13.,'text':'Sincronizada'}]
        _clips,targets=resolve_scope(project,ScopeSpec('one',(video.id,)))
        caption=create_auto_captions(project,targets)[0]
        manual=create_manual_caption(project,'Manual',3.,3.5)
        self.assertEqual(caption.caption_anchor_clip_id,video.id)
        self.assertEqual((caption.caption_source_start,caption.caption_source_end),(12.,13.))
        self.assertAlmostEqual(caption.timeline_start,3.)
        self.assertAlmostEqual(caption.duration,.5)

        project.set_speed(video.id,4)
        self.assertAlmostEqual(caption.timeline_start,2.5)
        self.assertAlmostEqual(caption.duration,.25)
        self.assertEqual((manual.timeline_start,manual.duration),(3.,.5))

        project.move_clip(video.id,video.track_id,10.)
        self.assertAlmostEqual(caption.timeline_start,10.5)
        project.cut_intervals(video.id,[(0.,.5)])
        survivor=next(c for c in project.clips if c.kind=='video')
        self.assertEqual(caption.caption_anchor_clip_id,survivor.id)
        self.assertAlmostEqual(caption.timeline_start,10.)
        project.set_speed(survivor.id,2)
        self.assertAlmostEqual(caption.timeline_start,10.)
        self.assertAlmostEqual(caption.duration,.5)

        saved=Path(self.tmp.name)/'caption_anchor.berofel.json'
        project.save(str(saved))
        loaded=Project.load(str(saved))
        restored=next(c for c in loaded.clips if c.generated_by=='auto_caption')
        self.assertEqual(restored.caption_anchor_clip_id,survivor.id)
        self.assertAlmostEqual(restored.timeline_start,10.)

    def test_auto_caption_crossing_cut_splits_at_preserved_words(self):
        project=Project()
        video=project.add_clip(Clip(source=str(self.file),start=10,end=30,
            kind='video',track_id=project.tracks[0].id,timeline_start=2,speed=2))
        project.transcripts=[
            {'source':str(self.file.resolve()),'source_start':12.,'source_end':12.5,
             'text':'Olá'},
            {'source':str(self.file.resolve()),'source_start':13.,'source_end':13.5,
             'text':'amigos'},
        ]
        _clips,targets=resolve_scope(project,ScopeSpec('one',(video.id,)))
        captions=create_auto_captions(project,targets)
        self.assertEqual(len(captions),1)
        self.assertEqual(captions[0].text,'Olá amigos')

        # Retira somente a pausa entre as duas palavras (tempo de playback).
        project.cut_intervals(video.id,[(1.25,1.5)])
        fragments=sorted((c for c in project.clips if c.generated_by=='auto_caption'),
                         key=lambda c:c.timeline_start)
        self.assertEqual([c.text for c in fragments],['Olá','amigos'])
        self.assertEqual([c.caption_anchor_clip_id for c in fragments],
                         [c.id for c in sorted((c for c in project.clips if c.kind=='video'),
                                               key=lambda c:c.timeline_start)])
        self.assertAlmostEqual(fragments[0].timeline_start,3.)
        self.assertAlmostEqual(fragments[1].timeline_start,3.25)
        self.assertAlmostEqual(fragments[0].duration,.25)
        self.assertAlmostEqual(fragments[1].duration,.25)

    def test_auto_caption_trim_keeps_only_words_that_remain_in_source(self):
        project=Project()
        video=project.add_clip(Clip(source=str(self.file),start=0,end=4,
            kind='video',track_id=project.tracks[0].id,timeline_start=0))
        caption=project.add_clip(Clip('',0,1.5,track_id=project.tracks[2].id,
            timeline_start=1,kind='text',text='Olá amigos',generated_by='auto_caption',
            caption_anchor_clip_id=video.id,caption_source_start=1,
            caption_source_end=2.5,caption_words=[
                {'source_start':1.,'source_end':1.3,'text':'Olá'},
                {'source_start':2.,'source_end':2.5,'text':'amigos'}],
            caption_generated_text='Olá amigos'))

        self.assertTrue(project.trim_clip(video.id,'right',1.5))
        self.assertEqual(caption.text,'Olá')
        self.assertEqual(caption.caption_words,[
            {'source_start':1.,'source_end':1.3,'text':'Olá'}])
        self.assertAlmostEqual(caption.timeline_start,1.)
        self.assertAlmostEqual(caption.duration,.3)

        self.assertTrue(project.trim_clip(video.id,'left',1.4))
        self.assertNotIn(caption,project.clips)

    def test_trim_detaches_a_user_revised_caption_instead_of_deleting_it(self):
        project=Project()
        video=project.add_clip(Clip(source=str(self.file),start=0,end=4,
            kind='video',track_id=project.tracks[0].id,timeline_start=0))
        caption=project.add_clip(Clip('',0,1.,track_id=project.tracks[2].id,
            timeline_start=1,kind='text',text='Texto revisado',generated_by='auto_caption',
            caption_anchor_clip_id=video.id,caption_source_start=1,
            caption_source_end=2,caption_words=[
                {'source_start':1.,'source_end':2.,'text':'Original'}],
            caption_generated_text='Original'))

        self.assertTrue(project.trim_clip(video.id,'left',2.5))
        self.assertIn(caption,project.clips)
        self.assertEqual(caption.text,'Texto revisado')
        self.assertEqual(caption.generated_by,'manual_caption')
        self.assertEqual(caption.caption_anchor_clip_id,'')

    def test_user_revised_caption_crossing_cut_is_preserved_without_stale_anchor(self):
        project=Project()
        video=project.add_clip(Clip(source=str(self.file),start=0,end=4,
            kind='video',track_id=project.tracks[0].id,timeline_start=0))
        caption=project.add_clip(Clip('',0,2,track_id=project.tracks[2].id,
            timeline_start=1,kind='text',text='Texto revisado',generated_by='auto_caption',
            caption_anchor_clip_id=video.id,caption_source_start=1,
            caption_source_end=3,caption_words=[
                {'source_start':1.,'source_end':3.,'text':'Original'}],
            caption_generated_text='Original'))

        project.cut_intervals(video.id,[(1.5,2.5)])
        self.assertIn(caption,project.clips)
        self.assertEqual(caption.text,'Texto revisado')
        self.assertEqual(caption.generated_by,'manual_caption')
        self.assertEqual(caption.caption_anchor_clip_id,'')
        self.assertIsNone(caption.caption_source_start)
        self.assertEqual(caption.caption_words,[])

if __name__=='__main__':unittest.main()


class CoverageReuseTests(unittest.TestCase):
    """Desempenho 0.8: transcrições completas são válidas após dividir um bloco."""
    def setUp(self):
        from unittest.mock import patch
        self.model_tmp=tempfile.TemporaryDirectory();self.addCleanup(self.model_tmp.cleanup)
        root=Path(self.model_tmp.name)
        self.model_dir=root/'parakeet';self.model_dir.mkdir()
        (self.model_dir/'model.int8.onnx').write_bytes(b'model')
        self.vad_dir=root/'silero';self.vad_dir.mkdir()
        (self.vad_dir/'silero.onnx').write_bytes(b'vad')
        for target,value in (
            ('berofel.services.ai_pipeline.parakeet_tdt_model_dir',self.model_dir),
            ('berofel.services.ai_pipeline.silero_vad_model_dir',self.vad_dir),
        ):
            mocked=patch(target,return_value=value)
            mocked.start();self.addCleanup(mocked.stop)
    def test_reuses_words_without_parakeet_after_split(self):
        from berofel.services.transcript_coverage import (record_coverage,has_coverage,
            words_in_clip)
        from berofel.services.subtitles import merge_reports
        with tempfile.TemporaryDirectory() as folder, \
             patch('berofel.services.ai_pipeline.parakeet_tdt_model_dir',
                   return_value=self.model_dir), \
             patch('berofel.services.ai_pipeline.silero_vad_model_dir',
                   return_value=self.vad_dir):
            source=Path(folder)/'source.mov';source.write_bytes(b'source')
            project=Project()
            original=Clip(source=str(source),start=10,end=40,speed=2,
                          track_id=project.tracks[0].id,timeline_start=5)
            project.add_clip(original)
            fake=FakeModels();cache=CacheStore(Path(folder)/'cache')
            long=Pipeline(cache,fake).analyze([original],AIOptions(chunk_seconds=15),mode='transcribe')
            merge_reports(project,long['reports'])
            record_coverage(project,long['reports'])
            self.assertTrue(has_coverage(project,original))
            project.split(original.id, 3.5)  # relativo à timeline (3.5 * 2 = 7s fonte)
            parts=[c for c in project.clips if c.source==original.source]
            self.assertEqual(len(parts),2)
            mid=parts[1]
            self.assertTrue(has_coverage(project,mid))
            self.assertTrue(words_in_clip(project,mid))
            before=len(fake.calls)
            reused=Pipeline(cache,fake).analyze([mid],AIOptions(chunk_seconds=15),
                mode='subtitles',known_words={mid.id:words_in_clip(project,mid)})
            self.assertEqual(len(fake.calls),before)
            self.assertEqual(reused['cache_misses'],0)
            saved=Path(folder)/'p.berofel.json';project.save(str(saved))
            loaded=Project.load(str(saved))
            self.assertTrue(has_coverage(loaded,mid))
            source.write_bytes(b'changed source!')
            self.assertFalse(has_coverage(loaded,mid))

    def test_cached_covered_text_only_launches_qwen(self):
        from berofel.services.transcript_coverage import record_coverage,words_in_clip
        with tempfile.TemporaryDirectory() as folder, \
             patch('berofel.services.ai_pipeline.parakeet_tdt_model_dir',
                   return_value=self.model_dir), \
             patch('berofel.services.ai_pipeline.silero_vad_model_dir',
                   return_value=self.vad_dir):
            source=Path(folder)/'source.mov';source.write_bytes(b'source')
            clip=Clip(source=str(source),start=0,end=20)
            project=Project();project.add_clip(replace(clip,track_id=project.tracks[0].id))
            fake=FakeModels();cache=CacheStore(Path(folder)/'cache')
            opts=AIOptions(chunk_seconds=20)
            trans=Pipeline(cache,fake).analyze([clip],opts,mode='transcribe')
            merge_reports(project,trans['reports']);record_coverage(project,trans['reports'])
            cli=Path(folder)/'cli';cli.write_bytes(b'x')
            model=Path(folder)/'model';model.write_bytes(b'x')
            opts.llama_cli=str(cli);opts.qwen_model=str(model)
            calls_before=len(fake.calls)
            result=Pipeline(cache,fake).analyze([clip],opts,mode='fillers',
                known_words={clip.id:words_in_clip(project,clip)})
            self.assertEqual(fake.calls[calls_before:],['qwen'])
            self.assertTrue(result['suggestions'])

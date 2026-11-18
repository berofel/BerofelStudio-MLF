"""0.9: fila configurável, VAD antes de ASR, revisão coletiva e remapeamento."""
import copy
import tempfile
import unittest
from pathlib import Path
from berofel.core.project import Project,Clip
from berofel.services.action_scope import ScopeSpec,resolve_scope
from berofel.services.batch_editing import (
    plan_actions,spoken_clips,run_edit_queue,apply_reviewed_cuts)
from berofel.services.subtitles import merge_reports
from berofel.services.caption_actions import create_auto_captions,scoped_cues


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.project=Project()
        self.original=Clip(source='source.mp4',start=0,end=100,kind='video',
                           track_id=self.project.tracks[0].id,speed=2,timeline_start=10)
        self.project.add_clip(self.original)
        self.clips,self.targets=resolve_scope(self.project,ScopeSpec(mode='one',selected_ids=(self.original.id,)))

    def test_plan_order_dedup_and_empty(self):
        plan=plan_actions(['subtitles','fillers','silence','transcribe','context'])
        self.assertEqual(plan.phases,('silence','whisper','qwen','subtitles'))
        self.assertTrue(plan.use_vad_for_asr)
        self.assertEqual(plan_actions(['subtitles']).phases,('whisper','subtitles'))
        self.assertEqual(plan_actions(['silence']).phases,('silence',))
        self.assertFalse(plan_actions(['silence','subtitles'],False).use_vad_for_asr)
        self.assertEqual(plan_actions(['narration']).phases,('narration',))
        with self.assertRaises(ValueError):plan_actions([])
        with self.assertRaises(ValueError):plan_actions(['unknown'])

    def test_vad_filters_source_without_modifying_timeline(self):
        before=copy.deepcopy(self.original)
        clips,seconds=spoken_clips(self.clips,[{
            'clip_id':self.original.id,
            'speech':[{'start':20,'end':25},{'start':27,'end':32},
                      {'start':80,'end':90}]}])
        self.assertEqual(len(clips),3)
        self.assertGreater(seconds,20.)
        self.assertLess(seconds,25.)
        self.assertAlmostEqual(clips[0].start,19.82)
        self.assertAlmostEqual(clips[0].timeline_start,19.91)
        self.assertEqual(self.original,before)
        self.assertEqual(self.project.clips,[self.original])

    def test_pipeline_runs_vad_first_and_whisper_qwen_once(self):
        calls=[];progress=[];qwen_words=[]
        def fake(clips,options,known_words,progress,control,stage,mode):
            if mode=='fillers':
                qwen_words.extend(w['text'] for arr in known_words.values() for w in arr)
            calls.append((mode,[(c.start,c.end) for c in clips]))
            progress(1,1)
            if mode=='silence':
                return {'reports':[{'clip_id':c.id,
                    'speech':[{'start':10,'end':40},{'start':60,'end':80}]} for c in clips],
                    'suggestions':[{'clip_id':c.id,'a':40,'b':60,'type':'silencio','title':'teste'}
                                   for c in clips], 'cache_hits':0,'cache_misses':2,'stages':[]}
            return {'reports':[{'clip_id':c.id,'start':c.start,'end':c.end,
                    'words':[{'id':'w','text':'errado','source':'source.mp4',
                              'source_start':c.start+2,'source_end':c.start+2.5}],
                    'suggestions':[{'clip_id':c.id,'a':2,'b':2.5,'type':'contexto',
                                    'title':'teste','note':'repetição'}]}
                    for c in clips], 'cache_hits':1,'cache_misses':2,'stages':[]}
        data=run_edit_queue(self.clips,('silence','fillers','subtitles','transcribe','context'),
                            progress=lambda a,b:progress.append((a,b)),analyze=fake)
        self.assertEqual(len(calls),3)
        self.assertEqual([entry[0] for entry in calls],['silence','transcribe','fillers'])
        self.assertLess(sum(b-a for a,b in calls[1][1]),
                        sum(b-a for a,b in calls[2][1]))
        self.assertLess(data['asr_seconds'],data['source_seconds'])
        self.assertIn('errado',qwen_words)  # Qwen usa a transcrição já pronta
        self.assertEqual(data['plan'].phases,('silence','whisper','qwen','subtitles'))
        self.assertEqual(len(data['suggestions']),2)
        self.assertTrue(all(0<=f['a']<f['b']<=100 for f in data['suggestions']))
        self.assertEqual(progress[-1],(300,300))
        self.assertEqual(data['cache_hits'],2)
        self.assertEqual(self.original.end,100)  # não cortou sem aprovação

    def test_no_spoken_words_skips_whisper(self):
        calls=[]
        def fake(clips,options,known_words,progress,control,stage,mode):
            calls.append(mode)
            return {'reports':[{'clip_id':c.id,'speech':[]} for c in clips],
                    'suggestions':[], 'stages':[]}
        data=run_edit_queue(self.clips,('silence','transcribe'),analyze=fake)
        self.assertEqual(calls,['silence'])
        self.assertEqual(data['asr_seconds'],0)

    def test_qwen_failure_does_not_discard_transcription_or_subtitle_phase(self):
        calls=[]
        def fake(clips,options,known_words,progress,control,stage,mode):
            calls.append(mode)
            if mode=='fillers':raise OSError('[WinError 206] caminho muito longo')
            return {'reports':[{'clip_id':c.id,'start':c.start,'end':c.end,
                    'words':[{'id':'w','text':'Olá','source':'source.mp4',
                              'source_start':1.,'source_end':1.5}],
                    'speech':[{'start':1.,'end':2.}]} for c in clips],
                    'suggestions':[], 'stages':[]}
        data=run_edit_queue(self.clips,('transcribe','fillers','subtitles'),analyze=fake)
        self.assertEqual(calls,['transcribe','fillers'])
        self.assertEqual(len(data['reports']),1)
        self.assertEqual(data['qwen_errors'],['[WinError 206] caminho muito longo'])
        self.assertIn('subtitles',data['plan'].phases)

    def test_cut_then_captions_use_new_times_and_undo_possible(self):
        word={'id':'w','source':str(__import__('pathlib').Path('source.mp4').resolve()),'source_start':70.,'source_end':71.,'text':'Olá'}
        merge_reports(self.project,[{'words':[word]}])
        before=copy.deepcopy(self.project)
        new_targets=apply_reviewed_cuts(self.project,self.targets,[
            {'clip_id':self.original.id,'a':20.,'b':60.}])
        self.assertEqual(len(new_targets),2)
        cues=scoped_cues(self.project,new_targets)
        self.assertEqual(len(cues),1)
        # 40 s de fonte removidos -> 20 s menos em velocidade 2x.
        self.assertAlmostEqual(cues[0][0],25.)
        new=create_auto_captions(self.project,new_targets)
        self.assertEqual(len(new),1)
        self.assertAlmostEqual(new[0].timeline_start,25.)
        self.assertEqual(len(before.clips),1)
        self.assertEqual(before.clips[0].start,0)

    def test_ai_approved_video_cut_also_cuts_its_linked_audio(self):
        self.original.group_id='ai_linked_av'
        audio=self.project.add_clip(Clip(source=self.original.source,start=0,end=100,
            kind='audio',track_id=self.project.tracks[1].id,speed=2,
            timeline_start=10,group_id=self.original.group_id))

        new_targets=apply_reviewed_cuts(self.project,self.targets,[
            {'clip_id':self.original.id,'a':20.,'b':60.}])

        videos=sorted((clip for clip in self.project.clips if clip.kind=='video'),
                      key=lambda clip:clip.timeline_start)
        audios=sorted((clip for clip in self.project.clips if clip.kind=='audio'),
                      key=lambda clip:clip.timeline_start)
        self.assertEqual(len(videos),2)
        self.assertEqual(len(audios),2)
        for video,audio_piece in zip(videos,audios):
            self.assertEqual((video.start,video.end,video.timeline_start,video.duration),
                             (audio_piece.start,audio_piece.end,
                              audio_piece.timeline_start,audio_piece.duration))
            self.assertEqual(video.group_id,audio_piece.group_id)
        self.assertNotEqual(videos[0].group_id,videos[1].group_id)
        self.assertNotIn(audio.id,[piece.id for piece in audios])
        self.assertEqual(len(new_targets),2)

    def test_ai_cut_av_and_captions_survive_project_save_and_reopen(self):
        self.original.group_id='ai_roundtrip_av'
        audio=self.project.add_clip(Clip(source=self.original.source,start=0,end=100,
            kind='audio',track_id=self.project.tracks[1].id,speed=2,
            timeline_start=10,group_id=self.original.group_id))
        merge_reports(self.project,[{'words':[{
            'id':'word-after-cut','source':str(Path(self.original.source).resolve()),
            'source_start':70.,'source_end':71.,'text':'sobrevive'}]}])
        targets=apply_reviewed_cuts(self.project,self.targets,[
            {'clip_id':self.original.id,'a':20.,'b':60.}])
        create_auto_captions(self.project,targets)
        expected=sorted((c.id,c.source,c.start,c.end,c.timeline_start,c.kind,c.group_id)
                        for c in self.project.clips)
        expected_cues=scoped_cues(self.project,targets)
        self.assertNotIn(audio.id,[c.id for c in self.project.clips])
        self.assertEqual(len(expected),5)  # dois pares AV sobreviventes + legenda

        with tempfile.TemporaryDirectory(prefix='bfs_ai_cut_roundtrip_') as folder:
            saved=Path(folder)/'edited.berofel.json'
            self.project.save(str(saved))
            restored=Project.load(str(saved))

        actual=sorted((c.id,c.source,c.start,c.end,c.timeline_start,c.kind,c.group_id)
                      for c in restored.clips)
        self.assertEqual(actual,expected)
        restored_targets=[target for target in targets
                          if restored.clip(target.original_id) is not None]
        self.assertEqual(scoped_cues(restored,restored_targets),expected_cues)
        video=sorted((c for c in restored.clips if c.kind=='video'),
                     key=lambda c:c.timeline_start)
        audios=sorted((c for c in restored.clips if c.kind=='audio'),
                      key=lambda c:c.timeline_start)
        self.assertEqual(len(video),2);self.assertEqual(len(audios),2)
        for image,sound in zip(video,audios):
            self.assertEqual((image.start,image.end,image.timeline_start,image.group_id),
                             (sound.start,sound.end,sound.timeline_start,sound.group_id))
        self.assertEqual(len([c for c in restored.clips if c.generated_by=='auto_caption']),1)

    def test_ai_cut_skips_entire_linked_pair_when_audio_track_is_locked(self):
        self.original.group_id='ai_locked_av'
        audio=self.project.add_clip(Clip(source=self.original.source,start=0,end=100,
            kind='audio',track_id=self.project.tracks[1].id,speed=2,
            timeline_start=10,group_id=self.original.group_id))
        self.project.track(audio.track_id).locked=True
        before=copy.deepcopy(self.project.clips)

        new_targets=apply_reviewed_cuts(self.project,self.targets,[
            {'clip_id':self.original.id,'a':20.,'b':60.}])

        self.assertEqual(self.project.clips,before)
        self.assertEqual(len(new_targets),1)
        self.assertEqual(new_targets[0].original_id,self.original.id)

    def test_cuts_only_targeted_track(self):
        other=Clip(source='another.mp4',start=0,end=100,kind='video',
                   track_id=self.project.tracks[1].id,timeline_start=10)
        self.project.add_clip(other)
        apply_reviewed_cuts(self.project,self.targets,[
            {'clip_id':self.original.id,'a':5,'b':20}])
        self.assertIsNotNone(self.project.clip(other.id))
        self.assertEqual(self.project.clip(other.id).timeline_start,10)

    def test_skip_cuts_preserves_original_clip_id(self):
        remapped=apply_reviewed_cuts(self.project,self.targets,[])
        self.assertEqual([t.original_id for t in remapped],[self.original.id])
        self.assertEqual(len(self.project.clips),1)

if __name__=='__main__': unittest.main()

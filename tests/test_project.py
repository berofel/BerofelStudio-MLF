import json
import tempfile
import unittest
from pathlib import Path
from berofel.core.project import Clip,Project,Track

class ProjectTests(unittest.TestCase):
    def make_project(self):
        p=Project()
        t=p.tracks[1].id
        clips=[Clip('x.mp4',0,10,track_id=t,timeline_start=0,source_length=30),
               Clip('x.mp4',10,20,track_id=t,timeline_start=10,source_length=30),
               Clip('x.mp4',20,30,track_id=t,timeline_start=20,source_length=30)]
        p.clips.extend(clips)
        return p

    def test_middle_selected_only(self):
        p=self.make_project()
        l,m,r=(c.id for c in p.clips)
        p.cut_intervals(m,[(2,5)])
        self.assertEqual([(c.start,c.end) for c in p.clips],
                        [(0,10),(10,12),(15,20),(20,30)])
        self.assertEqual([(c.timeline_start,c.timeline_end) for c in p.clips],
                         [(0,10),(10,12),(12,17),(20,30)])
        self.assertEqual(p.clips[0].id,l)
        self.assertEqual(p.clips[-1].id,r)

    def test_layer_order_and_arbitrary_types(self):
        p=Project()
        one,two=p.tracks[0].id,p.tracks[1].id
        v=Clip('v.mp4',0,5,track_id=two,kind='video')
        a=Clip('voice.wav',0,3,track_id=two,kind='audio')
        t=Clip('',0,4,track_id=two,kind='text',text='Oi')
        p.clips.extend([v,a,t])
        self.assertEqual([c.track_id for c in p.clips],[two]*3)
        self.assertTrue(p.move_track(two,-1))
        self.assertEqual(p.tracks[0].id,two)
        self.assertTrue(p.move_clip(t.id,one,2))
        self.assertEqual(p.clip(t.id).timeline_start,2)

    def test_split_preserves_track_and_timeline_position(self):
        p=self.make_project();c=p.clips[1]
        self.assertTrue(p.split(c.id,3))
        self.assertEqual([(x.start,x.end,x.timeline_start) for x in p.clips[1:3]],
                         [(10,13,10),(13,20,13)])
        self.assertTrue(all(x.track_id==c.track_id for x in p.clips[1:3]))

    def test_split_keeps_locked_linked_audio_video_group_atomic(self):
        p=Project();video_track=p.tracks[0];audio_track=p.tracks[1]
        video=p.add_clip(Clip('source.mp4',0,4,track_id=video_track.id,
                              source_length=4,group_id='av'))
        audio=p.add_clip(Clip('source.mp4',0,4,track_id=audio_track.id,
                              source_length=4,kind='audio',group_id='av'))
        audio_track.locked=True
        self.assertEqual(p.split_at_timeline({video.id},2),[])
        self.assertEqual(len(p.clips),2)
        self.assertEqual((video.start,video.end,video.timeline_start), (0,4,0))
        self.assertEqual((audio.start,audio.end,audio.timeline_start), (0,4,0))
        self.assertEqual(video.group_id,audio.group_id)

    def test_split_skips_locked_group_but_still_splits_independent_selection(self):
        p=Project();video_track=p.tracks[0];audio_track=p.tracks[1]
        video=p.add_clip(Clip('source.mp4',0,4,track_id=video_track.id,
                              source_length=4,group_id='av'))
        audio=p.add_clip(Clip('source.mp4',0,4,track_id=audio_track.id,
                              source_length=4,kind='audio',group_id='av'))
        solo=p.add_clip(Clip('solo.wav',0,4,track_id=p.tracks[2].id,
                             source_length=4,kind='audio'))
        audio_track.locked=True
        changed=p.split_at_timeline({video.id,solo.id},2)
        self.assertEqual(changed,[solo.id])
        self.assertEqual(len(p.clips),4)
        self.assertEqual((video.start,video.end),(0,4))
        self.assertEqual((audio.start,audio.end),(0,4))
        self.assertEqual(len([c for c in p.clips if c.group_id=='av']),2)

    def test_trim_extension(self):
        p=self.make_project();c=p.clips[1]
        self.assertTrue(p.trim_clip(c.id,'left',8))
        self.assertEqual((c.start,c.timeline_start),(8,8))
        self.assertTrue(p.trim_clip(c.id,'right',22))
        self.assertEqual(c.end,22)

    def test_roll_edit_preserves_pair_duration_speed_and_linked_audio(self):
        p=Project();video_track,audio_track=p.tracks[0].id,p.tracks[1].id
        left_group,right_group='left_pair','right_pair'
        left=p.add_clip(Clip('left.mp4',2,8,track_id=video_track,timeline_start=0,
            source_length=12,speed=2,group_id=left_group))
        right=p.add_clip(Clip('right.mp4',4,12,track_id=video_track,timeline_start=3,
            source_length=20,speed=2,group_id=right_group))
        left_audio=p.add_clip(Clip('left.mp4',2,8,track_id=audio_track,timeline_start=0,
            source_length=12,speed=2,kind='audio',group_id=left_group))
        right_audio=p.add_clip(Clip('right.mp4',4,12,track_id=audio_track,timeline_start=3,
            source_length=20,speed=2,kind='audio',group_id=right_group))
        caption=p.add_clip(Clip('',0,1,track_id=p.tracks[2].id,timeline_start=3.5,
            kind='text',text='legenda',generated_by='auto_caption',
            caption_anchor_clip_id=right.id,caption_source_start=5,
            caption_source_end=7,caption_generated_text='legenda'))

        self.assertEqual(set(p.roll_edit(left.id,right.id,.5)),
                         {left.id,right.id,left_audio.id,right_audio.id})
        self.assertEqual((left.start,left.end,left.timeline_start,left.timeline_end),
                         (2,9,0,3.5))
        self.assertEqual((right.start,right.end,right.timeline_start,right.timeline_end),
                         (5,12,3.5,7.0))
        self.assertEqual((left_audio.end,right_audio.start),(9,5))
        self.assertAlmostEqual(p.duration,7.)
        self.assertAlmostEqual(caption.timeline_start,3.5)

        self.assertEqual(set(p.roll_edit(left.id,right.id,-.5)),
                         {left.id,right.id,left_audio.id,right_audio.id})
        self.assertEqual((left.end,right.start,right.timeline_start),(8,4,3))

    def test_roll_edit_rejects_gaps_locked_tracks_and_source_edges_atomically(self):
        p=Project();track=p.tracks[0]
        left=p.add_clip(Clip('a',0,2,track_id=track.id,timeline_start=0,source_length=2))
        right=p.add_clip(Clip('b',0,2,track_id=track.id,timeline_start=2,source_length=2))
        self.assertEqual(p.roll_edit(left.id,right.id,.5),[])
        self.assertEqual((left.end,right.start,right.timeline_start),(2,0,2))
        right.timeline_start=2.1
        self.assertEqual(p.roll_edit(left.id,right.id,-.2),[])
        right.timeline_start=2
        track.locked=True
        self.assertEqual(p.roll_edit(left.id,right.id,-.2),[])
        self.assertEqual((left.end,right.start,right.timeline_start),(2,0,2))

    def test_slide_edit_moves_clip_and_preserves_sequence_edges_at_mixed_speeds(self):
        p=Project();track=p.tracks[0]
        left=p.add_clip(Clip('left.mp4',2,8,track_id=track.id,timeline_start=0,
                             source_length=12,speed=2))
        middle=p.add_clip(Clip('middle.mp4',4,10,track_id=track.id,timeline_start=3,
                               source_length=12,speed=2))
        right=p.add_clip(Clip('right.mp4',1,7,track_id=track.id,timeline_start=6,
                              source_length=12,speed=1.5))
        middle.keyframes={'scale':[{'t':0.,'value':1.},{'t':3.,'value':2.}]}
        original_end=p.duration

        changed=p.slide_clip(middle.id,.5)

        self.assertEqual(set(changed),{left.id,middle.id,right.id})
        self.assertAlmostEqual(left.timeline_start,0.)
        self.assertAlmostEqual(left.timeline_end,middle.timeline_start)
        self.assertAlmostEqual(middle.timeline_end,right.timeline_start)
        self.assertAlmostEqual(right.timeline_end,original_end)
        self.assertAlmostEqual(middle.timeline_start,3.5)
        self.assertEqual((middle.start,middle.end), (4,10))
        self.assertEqual((left.end,right.start),(9,1.75))
        self.assertEqual(middle.keyframes['scale'],[{'t':0.,'value':1.},{'t':3.,'value':2.}])

    def test_slide_edit_moves_linked_av_and_captions_atomically(self):
        p=Project();video_track,audio_track=p.tracks[0].id,p.tracks[1].id
        groups=('left','middle','right')
        members=[]
        for index,(group,source,kind,track) in enumerate((
                (groups[0],'left.mp4','video',video_track),(groups[1],'mid.mp4','video',video_track),
                (groups[2],'right.mp4','video',video_track),(groups[0],'left.mp4','audio',audio_track),
                (groups[1],'mid.mp4','audio',audio_track),(groups[2],'right.mp4','audio',audio_track))):
            if group=='left':start,end,at=0,2,0
            elif group=='middle':start,end,at=0,1,2
            else:start,end,at=1,3,3
            members.append(p.add_clip(Clip(source,start,end,track_id=track,timeline_start=at,
                source_length=5,kind=kind,group_id=group)))
        left_video,middle_video,right_video,left_audio,middle_audio,right_audio=members
        caption=p.add_clip(Clip('',0,.5,track_id=p.tracks[2].id,timeline_start=2.25,
            kind='text',text='fala',generated_by='auto_caption',
            caption_anchor_clip_id=middle_video.id,caption_source_start=.25,
            caption_source_end=.75,caption_generated_text='fala'))

        changed=p.slide_clip(middle_video.id,.5)

        self.assertEqual(set(changed),{left_video.id,middle_video.id,right_video.id,
                                      left_audio.id,middle_audio.id,right_audio.id})
        self.assertAlmostEqual(middle_video.timeline_start,middle_audio.timeline_start)
        self.assertAlmostEqual(middle_video.timeline_start,2.5)
        self.assertAlmostEqual(caption.timeline_start,2.75)
        self.assertAlmostEqual(left_video.timeline_end,left_audio.timeline_end)
        self.assertAlmostEqual(right_video.timeline_start,right_audio.timeline_start)

        before=[(clip.start,clip.end,clip.timeline_start) for clip in members]
        p.track(audio_track).locked=True
        self.assertEqual(p.slide_clip(middle_video.id,-.25),[])
        self.assertEqual([(clip.start,clip.end,clip.timeline_start) for clip in members],before)

    def test_slide_refuses_gaps_and_source_edges_without_partial_changes(self):
        p=Project();track=p.tracks[0]
        left=p.add_clip(Clip('left.mp4',0,4,track_id=track.id,timeline_start=0,source_length=4))
        middle=p.add_clip(Clip('mid.mp4',0,2,track_id=track.id,timeline_start=4,source_length=4))
        right=p.add_clip(Clip('right.mp4',0,2,track_id=track.id,timeline_start=6,source_length=4))
        before=[(clip.start,clip.end,clip.timeline_start) for clip in (left,middle,right)]
        self.assertEqual(p.slide_clip(middle.id,.5),[],'Previous source is already at its end.')
        self.assertEqual([(clip.start,clip.end,clip.timeline_start) for clip in (left,middle,right)],before)
        self.assertEqual(p.slide_clip(middle.id,-.5),[],'Next source cannot extend before zero.')
        self.assertEqual([(clip.start,clip.end,clip.timeline_start) for clip in (left,middle,right)],before)
        right.timeline_start+=.1
        self.assertEqual(p.slide_clip(middle.id,.2),[],'A gap is not an adjacent edit point.')
        self.assertEqual([(clip.start,clip.end,clip.timeline_start) for clip in (left,middle,right)],
                         [*before[:2],(right.start,right.end,right.timeline_start)])

    def test_slip_preserves_timeline_and_linked_audio_and_respects_source_edges(self):
        p=Project()
        group='linked_av'
        video=p.add_clip(Clip('source.mp4',10,20,track_id=p.tracks[0].id,
            timeline_start=5,source_length=30,speed=2,group_id=group))
        audio=p.add_clip(Clip('source.mp4',10,20,track_id=p.tracks[1].id,
            timeline_start=5,source_length=30,speed=2,kind='audio',group_id=group))
        generated=p.add_clip(Clip('',0,1,track_id=p.tracks[2].id,
            timeline_start=5.5,kind='text',text='Fala original',generated_by='auto_caption',
            caption_anchor_clip_id=video.id,caption_source_start=11,caption_source_end=13,
            caption_words=[{'text':'Fala','source_start':11,'source_end':12}],
            caption_generated_text='Fala original'))
        manual=p.add_clip(Clip('',0,1,track_id=p.tracks[2].id,
            timeline_start=6.5,kind='text',text='Texto revisado',generated_by='auto_caption',
            caption_anchor_clip_id=video.id,caption_source_start=13,caption_source_end=15,
            caption_words=[{'text':'revisado','source_start':13,'source_end':15}],
            caption_generated_text='Texto original'))
        before=[(c.timeline_start,c.duration) for c in (video,audio)]

        changed=p.slip_clip(video.id,50)

        self.assertEqual(changed,[video.id,audio.id])
        self.assertEqual([(c.start,c.end) for c in (video,audio)],[(20,30),(20,30)])
        self.assertEqual([(c.timeline_start,c.duration) for c in (video,audio)],before)
        self.assertNotIn(generated,p.clips,'Legenda gerada para a janela antiga deve sair.')
        self.assertIn(manual,p.clips,'Texto revisado pelo usuário precisa ser preservado.')
        self.assertEqual(manual.text,'Texto revisado')
        self.assertEqual(manual.timeline_start,6.5)
        self.assertEqual(manual.caption_anchor_clip_id,'')
        self.assertEqual(manual.caption_words,[])
        self.assertEqual(p.slip_clip(video.id,1),[],'Não pode ultrapassar o fim da fonte.')
        self.assertEqual(p.slip_clip(video.id,-40),[video.id,audio.id])
        self.assertEqual([(c.start,c.end) for c in (video,audio)],[(0,10),(0,10)])

    def test_cut_intervals_keep_audio_fades_only_at_original_edges(self):
        p=Project()
        clip=p.add_clip(Clip('voice.wav',0,10,track_id=p.tracks[0].id,
                             kind='audio',audio_fade_in=.4,audio_fade_out=.6,
                             fade_in=.3,fade_out=.5))
        p.cut_intervals(clip.id,[(4,6)])
        self.assertEqual(len(p.clips),2)
        first,last=sorted(p.clips,key=lambda c:c.timeline_start)
        self.assertEqual((first.audio_fade_in,first.audio_fade_out),(.4,0))
        self.assertEqual((last.audio_fade_in,last.audio_fade_out),(0,.6))
        self.assertEqual((first.fade_in,first.fade_out),(.3,0))
        self.assertEqual((last.fade_in,last.fade_out),(0,.5))

        beginning=Project()
        start_clip=beginning.add_clip(Clip('voice.wav',0,10,
            track_id=beginning.tracks[0].id,kind='audio',
            audio_fade_in=.4,audio_fade_out=.6))
        beginning.cut_intervals(start_clip.id,[(0,2)])
        self.assertEqual(len(beginning.clips),1)
        self.assertEqual(beginning.clips[0].audio_fade_in,0)
        self.assertEqual(beginning.clips[0].audio_fade_out,.6)

        end=Project()
        end_clip=end.add_clip(Clip('voice.wav',0,10,
            track_id=end.tracks[0].id,kind='audio',
            audio_fade_in=.4,audio_fade_out=.6))
        end.cut_intervals(end_clip.id,[(8,10)])
        self.assertEqual(len(end.clips),1)
        self.assertEqual(end.clips[0].audio_fade_in,.4)
        self.assertEqual(end.clips[0].audio_fade_out,0)

    def test_cut_intervals_keep_separated_linked_audio_in_sync(self):
        p=Project();group='linked_pair'
        video=p.add_clip(Clip('source.mp4',10,20,track_id=p.tracks[0].id,
            timeline_start=5,speed=2,source_length=30,kind='video',group_id=group))
        audio=p.add_clip(Clip('source.mp4',10,20,track_id=p.tracks[1].id,
            timeline_start=5,speed=2,source_length=30,kind='audio',group_id=group,
            audio_fade_in=.3,audio_fade_out=.4))

        p.cut_intervals(video.id,[(1.,2.)])

        videos=sorted((clip for clip in p.clips if clip.kind=='video'),
                      key=lambda clip:clip.timeline_start)
        audios=sorted((clip for clip in p.clips if clip.kind=='audio'),
                      key=lambda clip:clip.timeline_start)
        self.assertEqual(len(videos),2)
        self.assertEqual(len(audios),2)
        for v,a in zip(videos,audios):
            self.assertEqual((v.start,v.end,v.timeline_start,v.duration),
                             (a.start,a.end,a.timeline_start,a.duration))
            self.assertEqual(v.group_id,a.group_id)
        self.assertNotEqual(videos[0].group_id,videos[1].group_id)
        self.assertAlmostEqual(videos[1].timeline_start,6.)
        self.assertEqual((audios[0].audio_fade_in,audios[0].audio_fade_out),(.3,0))
        self.assertEqual((audios[1].audio_fade_in,audios[1].audio_fade_out),(0,.4))

    def test_cut_intervals_do_not_partially_cut_a_locked_linked_pair(self):
        p=Project();group='locked_pair'
        video=p.add_clip(Clip('source.mp4',0,10,track_id=p.tracks[0].id,
            source_length=10,kind='video',group_id=group))
        audio=p.add_clip(Clip('source.mp4',0,10,track_id=p.tracks[1].id,
            source_length=10,kind='audio',group_id=group))
        self.assertTrue(p.can_edit_linked_av(video.id))
        p.track(audio.track_id).locked=True
        self.assertFalse(p.can_edit_linked_av(video.id))
        before=[(c.id,c.start,c.end,c.timeline_start,c.group_id) for c in p.clips]

        p.cut_intervals(video.id,[(2.,4.)])

        self.assertEqual([(c.id,c.start,c.end,c.timeline_start,c.group_id)
                          for c in p.clips],before)

    def test_manual_trim_and_speed_keep_linked_av_together(self):
        p=Project();group='manual_linked_pair'
        video=p.add_clip(Clip('source.mp4',0,10,track_id=p.tracks[0].id,
            timeline_start=1,speed=2,source_length=12,kind='video',group_id=group))
        audio=p.add_clip(Clip('source.mp4',0,10,track_id=p.tracks[1].id,
            timeline_start=1,speed=2,source_length=12,kind='audio',group_id=group))

        self.assertTrue(p.trim_clip(video.id,'right',4.))
        self.assertEqual((video.start,video.end,video.timeline_start,video.duration),
                         (audio.start,audio.end,audio.timeline_start,audio.duration))
        self.assertEqual((video.start,video.end,video.timeline_start),(0,6,1))
        self.assertTrue(p.set_speed(video.id,3.))
        self.assertEqual((video.speed,video.start,video.end,video.timeline_start),
                         (audio.speed,audio.start,audio.end,audio.timeline_start))

        p.track(audio.track_id).locked=True
        before=(video.speed,video.start,video.end,video.timeline_start,
                audio.speed,audio.start,audio.end,audio.timeline_start)
        self.assertFalse(p.set_speed(video.id,4.))
        self.assertFalse(p.trim_clip(video.id,'left',1.5))
        self.assertEqual((video.speed,video.start,video.end,video.timeline_start,
                          audio.speed,audio.start,audio.end,audio.timeline_start),before)

    def test_save_load_v2(self):
        p=self.make_project()
        p.review_queue=[{'clip_id':'1','title':'Pausa','a':1.25,'b':2.5,
                         'type':'silencio','note':'Revisar','checked':True}]
        p.review_title='Revisão de silêncios'
        p.tracks[0].name='Texto e audio misturados'
        p.tracks[0].volume=.65;p.tracks[0].pan=-.35
        p.tracks[0].solo=True
        with tempfile.TemporaryDirectory() as d:
            f=str(Path(d)/'a.json');p.save(f);q=Project.load(f)
            self.assertEqual(len(q.tracks),4)
            self.assertEqual(q.tracks[0].name,'Texto e audio misturados')
            self.assertAlmostEqual(q.tracks[0].volume,.65)
            self.assertAlmostEqual(q.tracks[0].pan,-.35)
            self.assertTrue(q.tracks[0].solo)
            self.assertEqual(q.review_queue,p.review_queue)
            self.assertEqual(q.review_title,p.review_title)
            self.assertEqual(q.clips[1].timeline_start,10)

    def test_v3_persists_multivoice_scripts_and_reads_v2_without_them(self):
        project=self.make_project()
        project.narration_scripts=[{'schema_version':1,'id':'script-1',
                                    'lines':[{'id':'line-1','voice_id':'V1'}]}]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'dialogue.berofel.json'
            project.save(str(path))
            payload=json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(payload['version'],3)
            loaded=Project.load(str(path))
            self.assertEqual(loaded.narration_scripts,project.narration_scripts)
            payload['version']=2
            payload.pop('narration_scripts')
            path.write_text(json.dumps(payload),encoding='utf-8')
            migrated=Project.load(str(path))
            self.assertEqual(migrated.narration_scripts,[])

    def test_load_v2_without_review_fields_keeps_backward_compatibility(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'legacy.json'
            self.make_project().save(str(path))
            data=json.loads(path.read_text(encoding='utf-8'))
            data.pop('review_queue',None);data.pop('review_title',None)
            path.write_text(json.dumps(data),encoding='utf-8')
            loaded=Project.load(str(path))
        self.assertEqual(loaded.review_queue,[])
        self.assertEqual(loaded.review_title,'')

    def test_migration_v1(self):
        data=dict(version=1,name='Antigo',media=['x.mp4'],
                  clips=[dict(source='x.mp4',start=3,end=5,title='a',id='1'),
                         dict(source='x.mp4',start=11,end=13,title='b',id='2')])
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'old.json';f.write_text(json.dumps(data),encoding='utf-8')
            q=Project.load(str(f))
            self.assertEqual([c.timeline_start for c in q.clips],[0,2])
            self.assertEqual([c.id for c in q.clips],['1','2'])

    def test_relink_updates_clips_transcripts_and_invalidates_old_coverage(self):
        with tempfile.TemporaryDirectory() as folder:
            old=str(Path(folder)/'moved'/'source.mp4')
            new=Path(folder)/'restored'/'source.mp4'
            new.parent.mkdir();new.write_bytes(b'relinked media')
            project=Project(media=[old])
            clip=project.add_clip(Clip(old,0,2,track_id=project.tracks[0].id))
            project.transcripts=[{'source':old,'source_start':.2,
                                  'source_end':.5,'text':'Olá'}]
            project.ai_coverage=[{'source':{'path':str(Path(old).resolve()),
                                      'size':10,'mtime_ns':1},
                                  'start':0,'end':2,'model':'base','language':'pt'}]
            project.relink_media(old,str(new))
            self.assertEqual(clip.source,str(new.resolve()))
            self.assertEqual(project.media,[str(new.resolve())])
            self.assertEqual(project.transcripts[0]['source'],str(new.resolve()))
            self.assertEqual(project.ai_coverage,[])

if __name__=='__main__':unittest.main()

"""Edição de precisão: persistência, réguas, sincronização, FFmpeg real."""
import tempfile
import subprocess
import unittest
from pathlib import Path

from berofel.core.project import Project, Clip
from berofel.core.motion import put_keyframe, value_at, slice_keyframes, ff_expr
from berofel.core.editing import snap_time
from berofel.services.preview_pipeline import crop_project, prepare_commands
from berofel.services.subtitles import timeline_words
from berofel.services.ffmpeg import ffmpeg_path,media_info
from berofel.services.export_multitrack import export_project


class PrecisionTests(unittest.TestCase):
    def test_bezier_keyframe_curve_matches_ffmpeg_expression(self):
        import numpy as np
        from berofel.core.motion import interpolate
        points=[{'t':0.,'value':0.,'easing':'bezier','bezier_c1':0.,'bezier_c2':1.},
                {'t':1.,'value':100.,'easing':'linear'}]
        self.assertAlmostEqual(interpolate(points,.25,0.),15.625)
        expression=ff_expr(Clip('',0,1,keyframes={'pos_x':points}),'pos_x')
        result=subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error',
            '-f','lavfi','-i',f"aevalsrc='{expression}':s=4:d=0.5",
            '-f','f64le','-ac','1','pipe:1'],capture_output=True,check=True,timeout=15)
        samples=np.frombuffer(result.stdout,dtype='<f8')
        self.assertEqual(len(samples),2)
        self.assertAlmostEqual(samples[0],0.,places=5)
        self.assertAlmostEqual(samples[1],15.625,places=3)

    def test_speed_split_trim(self):
        p=Project();t=p.tracks[0].id
        c=p.add_clip(Clip('video.mp4',0,10,track_id=t,speed=2))
        self.assertAlmostEqual(c.duration,5)
        self.assertTrue(p.trim_clip(c.id,'left',1))
        self.assertAlmostEqual(c.start,2)
        self.assertAlmostEqual(c.duration,4)
        self.assertTrue(p.split(c.id,2))
        a,b=p.clips
        self.assertAlmostEqual(a.end,6)
        self.assertAlmostEqual(b.start,6)
        self.assertAlmostEqual(b.timeline_start,3)
        self.assertAlmostEqual(p.duration,5)

    def test_speed_change_resamples_keyframes_and_preserves_source(self):
        p=Project();c=p.add_clip(Clip('foo.wav',1,9,track_id=p.tracks[0].id,kind='audio'))
        put_keyframe(c,'volume',0,0)
        put_keyframe(c,'volume',4,1)
        self.assertTrue(p.set_speed(c.id,4))
        self.assertEqual((c.start,c.end),(1,9))
        self.assertAlmostEqual(c.duration,2)
        self.assertAlmostEqual(c.keyframes['volume'][1]['t'],1)

    def test_retime_labels_and_transcription(self):
        p=Project();c=p.add_clip(Clip('foo.wav',10,14,kind='audio',track_id=p.tracks[0].id,
                                    speed=2,timeline_start=9))
        from pathlib import Path
        p.transcripts=[dict(source=str(Path('foo.wav').resolve()),source_start=11,source_end=11.4,text='teste')]
        words=timeline_words(p)
        self.assertEqual(len(words),1)
        self.assertAlmostEqual(words[0]['start'],9.5)
        self.assertAlmostEqual(words[0]['end'],9.7)

    def test_crop_preview_uses_source_speed_and_keyframe_slice(self):
        p=Project();c=p.add_clip(Clip('v.mp4',10,18,track_id=p.tracks[0].id,
                                    speed=2,timeline_start=25))
        put_keyframe(c,'pos_x',0,0);put_keyframe(c,'pos_x',4,160)
        crop,length=crop_project(p,28,1,preview_width=640)
        q=crop.clips[0]
        self.assertEqual(length,1)
        self.assertAlmostEqual(q.start,16)
        self.assertAlmostEqual(q.end,18)
        self.assertAlmostEqual(q.timeline_start,0)
        self.assertAlmostEqual(q.duration,1)
        self.assertAlmostEqual(value_at(q,'pos_x',0),60) # 120px source resized 640/1280
        self.assertAlmostEqual(value_at(q,'pos_x',1),80)

    def test_ripple_deletes_only_affected_tracks(self):
        p=Project();t=p.tracks[0].id;other=p.tracks[1].id
        a=p.add_clip(Clip('a',0,2,track_id=t,timeline_start=0))
        b=p.add_clip(Clip('b',0,3,track_id=t,timeline_start=2))
        c=p.add_clip(Clip('c',0,2,track_id=t,timeline_start=5))
        d=p.add_clip(Clip('d',0,2,track_id=other,timeline_start=5))
        self.assertEqual(p.ripple_delete({b.id}),1)
        self.assertIsNone(p.clip(b.id))
        self.assertAlmostEqual(c.timeline_start,2)
        self.assertAlmostEqual(d.timeline_start,5)

    def test_snapping_and_markers(self):
        p=Project();t=p.tracks[0].id
        a=p.add_clip(Clip('a',0,2,track_id=t,timeline_start=3))
        p.add_marker(11.0,'Ponto importante')
        self.assertAlmostEqual(snap_time(p,10.88,threshold=.15),11)
        self.assertAlmostEqual(snap_time(p,8.92,threshold=.15,also_end=2),9)
        self.assertAlmostEqual(snap_time(p,4.91,threshold=.2),5)
        self.assertAlmostEqual(snap_time(p,4.91,a.id,threshold=.2),4.91)

    def test_curve_smooth_and_segment(self):
        p=Project();c=p.add_clip(Clip('',0,4,track_id=p.tracks[0].id,kind='text'))
        put_keyframe(c,'scale',0,1,'smooth')
        put_keyframe(c,'scale',4,3)
        self.assertAlmostEqual(value_at(c,'scale',2),2)
        segments=slice_keyframes(c.keyframes,1,3)
        self.assertAlmostEqual(segments['scale'][0]['value'],1.3125)
        self.assertAlmostEqual(segments['scale'][-1]['value'],2.6875)
        self.assertIn('if(lt(',ff_expr(c,'scale'))

    def test_transitions_preserve_media_and_audio(self):
        for style in ('dissolve','slide','zoom'):
            p=Project();t=p.tracks[0].id;audio_track=p.tracks[1].id
            a=p.add_clip(Clip('left.mp4',0,3,track_id=t,kind='video',group_id='left'))
            b=p.add_clip(Clip('right.mp4',0,3,track_id=t,kind='video',timeline_start=3,
                              group_id='right'))
            left_audio=p.add_clip(Clip('left.mp4',0,3,track_id=audio_track,kind='audio',
                                       group_id='left'))
            right_audio=p.add_clip(Clip('right.mp4',0,3,track_id=audio_track,kind='audio',
                                        timeline_start=3,group_id='right'))
            self.assertTrue(p.transition_overlap(a.id,b.id,.5,style))
            self.assertAlmostEqual(b.timeline_start,2.5)
            self.assertAlmostEqual(a.audio_fade_out,.5)
            self.assertAlmostEqual(b.audio_fade_in,.5)
            self.assertAlmostEqual(left_audio.audio_fade_out,.5)
            self.assertAlmostEqual(right_audio.audio_fade_in,.5)
            self.assertAlmostEqual(right_audio.timeline_start,b.timeline_start)
            self.assertAlmostEqual(b.fade_in,0 if style=='slide' else .5)
            self.assertEqual((b.start,b.end),(0,3))

    def test_invalid_transition_style_does_not_move_right_clip(self):
        p=Project();track=p.tracks[0].id
        left=p.add_clip(Clip('left.mp4',0,3,track_id=track,kind='video'))
        right=p.add_clip(Clip('right.mp4',0,3,track_id=track,kind='video',timeline_start=3))
        with self.assertRaises(ValueError):
            p.transition_overlap(left.id,right.id,.5,'unknown')
        self.assertEqual(right.timeline_start,3)

    def test_transition_with_locked_separated_audio_is_atomic(self):
        from copy import deepcopy
        project=Project();video_track=project.tracks[0];audio_track=project.tracks[1]
        left=project.add_clip(Clip('left.mp4',0,3,track_id=video_track.id,
            kind='video',include_audio=False,group_id='left'))
        right=project.add_clip(Clip('right.mp4',0,3,track_id=video_track.id,
            kind='video',include_audio=False,timeline_start=3,group_id='right'))
        project.add_clip(Clip('left.mp4',0,3,track_id=audio_track.id,
            kind='audio',group_id='left'))
        project.add_clip(Clip('right.mp4',0,3,track_id=audio_track.id,
            kind='audio',timeline_start=3,group_id='right'))
        audio_track.locked=True
        before=[clip.as_dict() for clip in deepcopy(project.clips)]
        self.assertFalse(project.transition_overlap(left.id,right.id,.5))
        self.assertEqual([clip.as_dict() for clip in project.clips],before)

    def test_save_load_new_props_and_v2_compat(self):
        with tempfile.TemporaryDirectory() as d:
            p=Project();c=p.add_clip(Clip('',0,3,track_id=p.tracks[0].id,kind='text',
                                          preserve_pitch=True))
            put_keyframe(c,'pos_x',1,24)
            p.add_marker(2,'Rever corte')
            path=str(Path(d)/'new.bfs')
            p.save(path)
            q=Project.load(path)
            self.assertEqual(q.markers[0]['label'],'Rever corte')
            self.assertEqual(q.clips[0].keyframes['pos_x'][0]['value'],24)
            self.assertAlmostEqual(q.clips[0].speed,1)
            self.assertTrue(q.clips[0].preserve_pitch)


class FFmpegPrecisionTests(unittest.TestCase):
    def test_speed_retimes_auto_subtitle_in_live_preview_and_export(self):
        import numpy as np
        with tempfile.TemporaryDirectory(prefix='bfs_caption_sync_') as temp:
            root=Path(temp);source=root/'source.mp4';tone=root/'tone.wav'
            subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y',
                '-f','lavfi','-i','anullsrc=r=48000:cl=mono:d=1',
                '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=0.5',
                '-f','lavfi','-i','anullsrc=r=48000:cl=mono:d=0.5',
                '-filter_complex','[0:a][1:a][2:a]concat=n=3:v=0:a=1[a]',
                '-map','[a]','-c:a','pcm_s16le',str(tone)],
                check=True,capture_output=True,timeout=20)
            subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y',
                '-f','lavfi','-i','color=c=gray:s=160x90:r=12:d=2',
                '-i',str(tone),
                '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p',
                '-c:a','aac','-shortest',str(source)],check=True,capture_output=True,timeout=30)
            project=Project(width=160,height=90,fps=12)
            video=project.add_clip(Clip(str(source),0,2,track_id=project.tracks[-1].id,
                kind='video',include_audio=True,source_length=2))
            caption=project.add_clip(Clip('',0,.5,track_id=project.tracks[0].id,
                timeline_start=1,kind='text',text='SINCRONIA',font_size=24,
                generated_by='auto_caption',caption_anchor_clip_id=video.id,
                caption_source_start=1,caption_source_end=1.5,
                caption_generated_text='SINCRONIA'))
            self.assertTrue(project.set_speed(video.id,2.))
            self.assertAlmostEqual(caption.timeline_start,.5)
            self.assertAlmostEqual(caption.duration,.25)

            def live_bundle(at):
                command=prepare_commands(project,at,root/f'preview_{at}',160,12,window=.1)
                decoded=subprocess.run(command.video,capture_output=True,check=True,timeout=20)
                frame_bytes=command.width*command.height*4
                self.assertGreaterEqual(len(decoded.stdout),frame_bytes)
                frame=np.frombuffer(decoded.stdout[:frame_bytes],dtype=np.uint8).reshape(
                    (command.height,command.width,4))
                audio=subprocess.run(command.audio,capture_output=True,check=True,timeout=20)
                return frame,audio.stdout

            preview_captioned,preview_voice=live_bundle(.6)
            preview_before,preview_silence_before=live_bundle(.3)
            preview_clear,preview_silence_after=live_bundle(.9)
            self.assertGreater(np.count_nonzero(
                np.max(np.abs(preview_captioned[:,:,:3].astype(np.int16)-
                              preview_clear[:,:,:3].astype(np.int16)),axis=2)>35),20)
            def rms(pcm):
                samples=np.frombuffer(pcm,dtype='<i2').astype(np.float32)
                return float(np.sqrt(np.mean(samples*samples))) if len(samples) else 0.
            self.assertGreater(rms(preview_voice),500.)
            self.assertLess(rms(preview_silence_before),100.)
            self.assertLess(rms(preview_silence_after),100.)

            destination=root/'captioned.mp4'
            export_project(project,str(destination))
            def export_frame(at):
                decoded=subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error',
                    '-ss',f'{at:.3f}','-i',str(destination),'-frames:v','1',
                    '-f','rawvideo','-pix_fmt','rgb24','pipe:1'],
                    capture_output=True,check=True,timeout=20)
                return np.frombuffer(decoded.stdout,dtype=np.uint8).reshape((90,160,3))
            export_captioned=export_frame(.6)
            export_clear=export_frame(.9)
            self.assertGreater(np.count_nonzero(
                np.max(np.abs(export_captioned.astype(np.int16)-
                              export_clear.astype(np.int16)),axis=2)>35),20)
            def export_audio(at):
                decoded=subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error',
                    '-ss',f'{at:.3f}','-i',str(destination),'-t','0.1','-map','0:a:0',
                    '-f','s16le','-ac','2','-ar','48000','pipe:1'],
                    capture_output=True,check=True,timeout=20)
                return decoded.stdout
            self.assertGreater(rms(export_audio(.6)),300.)
            self.assertLess(rms(export_audio(.3)),120.)
            self.assertLess(rms(export_audio(.9)),120.)

    def test_3x_4x_10x_keep_caption_and_audio_synced_in_preview_and_export(self):
        import copy
        import numpy as np
        with tempfile.TemporaryDirectory(prefix='bfs_high_speed_sync_') as temp:
            root=Path(temp);tone=root/'tone.wav';source=root/'source.mp4'
            subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y',
                '-f','lavfi','-i','anullsrc=r=48000:cl=mono:d=1',
                '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=0.5',
                '-f','lavfi','-i','anullsrc=r=48000:cl=mono:d=0.5',
                '-filter_complex','[0:a][1:a][2:a]concat=n=3:v=0:a=1[a]',
                '-map','[a]','-c:a','pcm_s16le',str(tone)],check=True,capture_output=True,timeout=20)
            subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y',
                '-f','lavfi','-i','color=c=gray:s=160x90:r=12:d=2','-i',str(tone),
                '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p',
                '-c:a','aac','-shortest',str(source)],check=True,capture_output=True,timeout=30)
            def rms(pcm):
                samples=np.frombuffer(pcm,dtype='<i2').astype(np.float32)
                return float(np.sqrt(np.mean(samples*samples))) if len(samples) else 0.
            def preview_frame(model,at,label):
                command=prepare_commands(model,at,root/f'preview_{label}_{at:.5f}',
                                         160,60,window=.1)
                decoded=subprocess.run(command.video,capture_output=True,check=True,timeout=20)
                frame_bytes=command.width*command.height*4
                self.assertGreaterEqual(len(decoded.stdout),frame_bytes)
                return np.frombuffer(decoded.stdout[:frame_bytes],dtype=np.uint8).reshape(
                    (command.height,command.width,4)),command
            def export_frame(path,at):
                decoded=subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error',
                    '-ss',f'{at:.5f}','-i',str(path),'-frames:v','1','-f','rawvideo',
                    '-pix_fmt','rgb24','pipe:1'],capture_output=True,check=True,timeout=20)
                return np.frombuffer(decoded.stdout,dtype=np.uint8).reshape((90,160,3))
            def export_audio(path,at):
                decoded=subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error',
                    '-ss',f'{at:.5f}','-i',str(path),'-t','0.02','-map','0:a:0',
                    '-f','s16le','-ac','2','-ar','48000','pipe:1'],
                    capture_output=True,check=True,timeout=20)
                return decoded.stdout
            for speed in (3.,4.,10.):
                with self.subTest(speed=speed):
                    project=Project(width=160,height=90,fps=60)
                    video=project.add_clip(Clip(str(source),0,2,track_id=project.tracks[-1].id,
                        kind='video',include_audio=True,source_length=2))
                    caption=project.add_clip(Clip('',0,.5,track_id=project.tracks[0].id,
                        timeline_start=1,kind='text',text='SINCRONIA',font_size=24,
                        generated_by='auto_caption',caption_anchor_clip_id=video.id,
                        caption_source_start=1,caption_source_end=1.5,
                        caption_generated_text='SINCRONIA'))
                    self.assertTrue(project.set_speed(video.id,speed))
                    self.assertAlmostEqual(caption.timeline_start,1/speed,delta=1e-4)
                    self.assertAlmostEqual(caption.duration,.5/speed,delta=1e-4)
                    baseline=copy.deepcopy(project)
                    baseline.clips=[clip for clip in baseline.clips if clip.kind!='text']
                    active_at=1.25/speed
                    quiet_at=.25/speed
                    frame,preview=preview_frame(project,active_at,f'caption_{speed}')
                    plain_frame,_=preview_frame(baseline,active_at,f'plain_{speed}')
                    self.assertGreater(np.count_nonzero(np.max(np.abs(
                        frame[:,:,:3].astype(np.int16)-plain_frame[:,:,:3].astype(np.int16)),
                        axis=2)>35),5)
                    audio=subprocess.run(preview.audio,capture_output=True,check=True,timeout=20).stdout
                    quiet_command=prepare_commands(project,quiet_at,
                        root/f'preview_quiet_{speed}',160,60,window=.1)
                    quiet=subprocess.run(quiet_command.audio,capture_output=True,
                                         check=True,timeout=20).stdout
                    self.assertGreater(rms(audio),400.)
                    self.assertLess(rms(quiet[:3840]),100.)
                    destination=root/f'{speed:g}x_caption.mp4'
                    plain=root/f'{speed:g}x_plain.mp4'
                    export_project(project,str(destination));export_project(baseline,str(plain))
                    at=1.1/speed
                    exported=export_frame(destination,at);exported_plain=export_frame(plain,at)
                    self.assertGreater(np.count_nonzero(np.max(np.abs(
                        exported.astype(np.int16)-exported_plain.astype(np.int16)),axis=2)>35),5)
                    self.assertGreater(rms(export_audio(destination,at)),250.)
                    self.assertLess(rms(export_audio(destination,quiet_at)),120.)

    def test_video_audio_speed_and_dynamic_keyframes(self):
        import numpy as np
        from PIL import Image
        with tempfile.TemporaryDirectory(prefix='bfs07_') as d:
            folder=Path(d);red=folder/'red.mp4';blue=folder/'blue.png'
            subprocess.run([ffmpeg_path(),'-loglevel','error','-y',
                '-f','lavfi','-i','color=c=red:s=160x90:r=24:d=2',
                '-f','lavfi','-i','sine=frequency=400:duration=2',
                '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(red)],check=True)
            Image.new('RGB',(160,90),'blue').save(blue)
            p=Project(width=160,height=90,fps=12)
            r=p.add_clip(Clip(str(red),0,2,track_id=p.tracks[-1].id,kind='video',speed=2))
            b=p.add_clip(Clip(str(blue),0,1,track_id=p.tracks[0].id,kind='image'))
            put_keyframe(b,'opacity',0,0)
            put_keyframe(b,'opacity',1,1)
            put_keyframe(b,'pos_x',0,-10)
            put_keyframe(b,'pos_x',1,0)
            put_keyframe(r,'volume',0,.2)
            put_keyframe(r,'volume',1,1)
            cmd=prepare_commands(p,0,folder/'live',160,12)
            v=subprocess.run(cmd.video,capture_output=True,timeout=30)
            a=subprocess.run(cmd.audio,capture_output=True,timeout=30)
            self.assertEqual(v.returncode,0,v.stderr.decode(errors='replace'))
            self.assertEqual(a.returncode,0,a.stderr.decode(errors='replace'))
            self.assertGreater(len(a.stdout),48000*4*.85)
            data=np.frombuffer(v.stdout,dtype=np.uint8).reshape((-1,90,160,4))
            self.assertGreater(data.shape[0],10)
            self.assertGreater(int(data[1,45,80,2]),int(data[1,45,80,0])) # vermelho no início
            self.assertGreater(int(data[-2,45,80,0]),int(data[-2,45,80,2])) # azul no final
            output=str(folder/'result.mp4')
            export_project(p,output)
            duration,video,audio=media_info(output)
            self.assertTrue(video and audio)
            self.assertTrue(.95<=duration<=1.3,duration)


if __name__ == '__main__':unittest.main()

class AdditionalEditingTests(unittest.TestCase):
    def test_transition_crossfades_separated_audio_in_preview_and_export(self):
        import numpy as np
        with tempfile.TemporaryDirectory(prefix='bfs_transition_av_') as temp:
            root=Path(temp);left_source=root/'left.mp4';right_source=root/'right.mp4'
            for source,color,frequency in ((left_source,'red',440),(right_source,'blue',880)):
                subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y',
                    '-f','lavfi','-i',f'color=c={color}:s=160x90:r=12:d=3',
                    '-f','lavfi','-i',f'sine=frequency={frequency}:duration=3',
                    '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(source)],
                    check=True,capture_output=True,timeout=30)
            project=Project(width=160,height=90,fps=12)
            vtrack,atrack=project.tracks[0].id,project.tracks[1].id
            left=project.add_clip(Clip(str(left_source),0,3,track_id=vtrack,kind='video',
                                       include_audio=False,group_id='left'))
            right=project.add_clip(Clip(str(right_source),0,3,track_id=vtrack,kind='video',
                                        timeline_start=3,include_audio=False,group_id='right'))
            left_audio=project.add_clip(Clip(str(left_source),0,3,track_id=atrack,kind='audio',
                                             group_id='left'))
            right_audio=project.add_clip(Clip(str(right_source),0,3,track_id=atrack,kind='audio',
                                              timeline_start=3,group_id='right'))
            self.assertTrue(project.transition_overlap(left.id,right.id,.5))
            self.assertAlmostEqual(right_audio.timeline_start,2.5)
            self.assertAlmostEqual(left_audio.audio_fade_out,.5)
            self.assertAlmostEqual(right_audio.audio_fade_in,.5)

            preview=prepare_commands(project,2.5,root/'preview',160,12,window=.5)
            video=subprocess.run(preview.video,capture_output=True,timeout=30)
            audio=subprocess.run(preview.audio,capture_output=True,timeout=30)
            self.assertEqual(video.returncode,0,video.stderr.decode(errors='replace'))
            self.assertEqual(audio.returncode,0,audio.stderr.decode(errors='replace'))
            samples=np.frombuffer(audio.stdout,dtype='<i2').reshape((-1,2)).astype(np.float32)
            self.assertGreater(len(samples),16000)
            self.assertGreater(float(np.sqrt(np.mean(samples**2))),100.)

            output=root/'transition.mp4'
            export_project(project,str(output))
            duration,has_video,has_audio=media_info(str(output))
            self.assertTrue(has_video and has_audio)
            self.assertAlmostEqual(duration,5.5,delta=.2)

    def test_split_linked_audio_video_into_independent_pairs(self):
        p=Project();group='linked001';source='movie.mp4'
        video=p.add_clip(Clip(source,0,8,track_id=p.tracks[0].id,kind='video',group_id=group))
        audio=p.add_clip(Clip(source,0,8,track_id=p.tracks[1].id,kind='audio',group_id=group))
        self.assertTrue(p.set_speed(video.id,2))
        self.assertEqual(p.clip(audio.id).speed,2)
        self.assertEqual(len(p.split_at_timeline({video.id,audio.id},2)),2)
        self.assertEqual(len(p.clips),4)
        left={c.group_id for c in p.clips if c.timeline_end<=2.001}
        right={c.group_id for c in p.clips if c.timeline_start>=1.999}
        self.assertEqual(len(left),1)
        self.assertEqual(len(right),1)
        self.assertNotEqual(left,right)

    def test_audio_filters_and_crop_rotate_export(self):
        from PIL import Image
        with tempfile.TemporaryDirectory(prefix='bfs07_fx_') as d:
            root=Path(d);video=root/'in.mp4'
            subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y',
                 '-f','lavfi','-i','color=c=green:s=160x90:r=12:d=1',
                 '-f','lavfi','-i','sine=frequency=440:duration=1',
                 '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(video)],check=True)
            p=Project(width=160,height=90,fps=12)
            c=p.add_clip(Clip(str(video),0,1,track_id=p.tracks[0].id,kind='video',
                 crop_left=.1,brightness=.15,saturation=1.3,contrast=1.2,
                 rotation=20,audio_highpass=80,audio_lowpass=8000,audio_denoise=True))
            put_keyframe(c,'rotation',0,0)
            put_keyframe(c,'rotation',1,30)
            dest=root/'out.mp4'
            export_project(p,str(dest))
            length,has_v,has_a=media_info(str(dest))
            self.assertTrue(has_v and has_a)
            self.assertGreater(length,.9)

    def test_background_thumbnail_waveform_and_cache(self):
        from PIL import Image
        from berofel.services.timeline_visuals import TimelineVisualCache
        with tempfile.TemporaryDirectory(prefix='bfs07_cache_') as d:
            root=Path(d);picture=root/'pic.png';wav=root/'voice.wav'
            Image.new('RGB',(240,140),'yellow').save(picture)
            subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y',
                 '-f','lavfi','-i','sine=frequency=560:duration=0.6',str(wav)],check=True)
            c=TimelineVisualCache(root/'cache',start_worker=False)
            thumb=c.thumbnail_path(str(picture),0)
            c._thumbnail(str(picture),0,thumb)
            self.assertTrue(thumb.is_file())
            self.assertGreater(thumb.stat().st_size,100)
            wavepath=c.waveform_path(str(wav),0)
            c._waveform(str(wav),0,wavepath)
            self.assertTrue(wavepath.is_file())
            wave=c.get_wave(str(wav),request=False)
            self.assertTrue(wave['peaks'])
            self.assertEqual(wave['offset'],0)
            self.assertLessEqual(len(wave['peaks']),8)
            c.close()


class ProxyTests(unittest.TestCase):
    def test_proxy_on_demand_preserves_resolution_and_origin(self):
        from unittest.mock import patch
        from berofel.services.proxies import create_proxy,find_proxy,remove_proxy
        with tempfile.TemporaryDirectory(prefix='bfs07_proxy_') as d:
            folder=Path(d);source=folder/'original.mp4';cache=folder/'cache'
            subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y',
                '-f','lavfi','-i','testsrc2=s=160x90:r=12:d=0.8',
                '-f','lavfi','-i','sine=frequency=330:duration=0.8',
                '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)],check=True)
            before=source.read_bytes()
            stats=[]
            proxy=create_proxy(source,folder=cache,max_width=960,
                               on_progress=lambda v,t:stats.append((v,t)))
            self.assertTrue(Path(proxy).is_file())
            self.assertEqual(proxy,find_proxy(source,cache))
            self.assertEqual(stats[-1],(stats[-1][1],stats[-1][1]))
            self.assertEqual(before,source.read_bytes())
            probe=subprocess.run([ffmpeg_path(),'-hide_banner','-i',proxy,'-f','null','-'],
                                  capture_output=True,timeout=25)
            self.assertEqual(probe.returncode,0)
            self.assertIn(b'160x90',probe.stderr) # nada de upscale desnecessario
            self.assertEqual(create_proxy(source,folder=cache,max_width=960),proxy)
            project=Project(width=160,height=90,fps=12)
            project.add_clip(Clip(str(source),0,.8,track_id=project.tracks[0].id,kind='video'))
            with patch('berofel.services.preview_pipeline.find_proxy',return_value=proxy):
                cmds=prepare_commands(project,0,folder/'view',160,12)
            self.assertIn(proxy,cmds.video)
            self.assertIn(proxy,cmds.audio)
            self.assertEqual(project.clips[0].source,str(source))
            self.assertTrue(remove_proxy(source,cache))
            self.assertIsNone(find_proxy(source,cache))


"""Cache visual de waveform: saída real do FFmpeg e encerramento em timeout."""
from pathlib import Path
import os
import json
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGraphicsScene
from berofel.core.project import Clip, Project
from berofel.services.ffmpeg import ffmpeg_path
from berofel.services.timeline_visuals import TimelineVisualCache
import berofel.services.timeline_visuals as timeline_visuals
from berofel.ui.timeline import (ClipGraphics, TimelineView, audio_fade_envelope_points,
                                 audio_fade_handle_points, keyframe_marker_points,
                                 volume_envelope_points)


class TimelineVisualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_volume_keyframes_map_to_visible_envelope_with_speed(self):
        clip=Clip('voice.wav',0,4,kind='audio',speed=2,volume=.5,
                  keyframes={'volume':[{'t':1.5,'value':2.},
                                       {'t':.5,'value':0.},
                                       {'t':3.,'value':4.}]})
        points=volume_envelope_points(clip,40,80,44)
        self.assertEqual(len(points),2)
        self.assertAlmostEqual(points[0][0],20.)
        self.assertAlmostEqual(points[1][0],60.)
        self.assertAlmostEqual(points[0][1],44*.27)
        self.assertAlmostEqual(points[1][1],44*.27-(44*.22)/2)
        self.assertEqual(volume_envelope_points(Clip('video.mp4',0,2),40,80,44),[])

    def test_slide_mode_drag_emits_snapped_delta_without_mutating_project(self):
        project=Project();track=project.tracks[0]
        project.add_clip(Clip('left.mp4',0,1,track_id=track.id,timeline_start=0,source_length=4))
        middle=project.add_clip(Clip('middle.mp4',0,1,track_id=track.id,timeline_start=1,source_length=4))
        project.add_clip(Clip('right.mp4',0,1,track_id=track.id,timeline_start=2,source_length=4))
        view=TimelineView();view.resize(600,360);view.pps=40
        view.set_project(project,[middle.id]);view.slide_mode=True;view.show();self.app.processEvents()
        emitted=[];view.slide_requested.connect(lambda *args:emitted.append(args))
        item=view.items_by_id[middle.id]
        left=project.clips[0];right=project.clips[2]
        left_item=view.items_by_id[left.id];right_item=view.items_by_id[right.id]
        old_middle_x=item.scenePos().x();old_right_x=right_item.scenePos().x()
        old_left_width=left_item.rect().width();old_right_width=right_item.rect().width()
        old_right_end=right_item.scenePos().x()+old_right_width
        start=view.mapFromScene(item.scenePos()+QPointF(20,22))
        end=type(start)(start.x()+20,start.y())
        QTest.mousePress(view.viewport(),Qt.MouseButton.LeftButton,pos=start)
        QTest.mouseMove(view.viewport(),end,delay=20)
        self.assertAlmostEqual(left_item.rect().width(),old_left_width+20.,delta=1.)
        self.assertAlmostEqual(item.scenePos().x(),old_middle_x+20.,delta=1.)
        self.assertAlmostEqual(right_item.scenePos().x(),old_right_x+20.,delta=1.)
        self.assertAlmostEqual(right_item.rect().width(),old_right_width-20.,delta=1.)
        self.assertAlmostEqual(right_item.scenePos().x()+right_item.rect().width(),old_right_end,delta=1.)
        QTest.mouseRelease(view.viewport(),Qt.MouseButton.LeftButton,pos=end)
        self.app.processEvents()
        self.assertEqual(len(emitted),1)
        self.assertEqual(emitted[0][0],middle.id)
        self.assertAlmostEqual(emitted[0][1],.5,delta=.03)
        self.assertEqual(middle.timeline_start,1.)  # commit remains an undoable UI command
        view.close()

    def test_volume_envelope_is_painted_inside_audio_clip(self):
        clip=Clip('voice.wav',0,2,kind='audio',
                  keyframes={'volume':[{'t':0.,'value':0.},
                                       {'t':2.,'value':4.}]})
        scene=QGraphicsScene();scene.setSceneRect(QRectF(0,0,80,44))
        scene.addItem(ClipGraphics(clip,0,0,80,44,40))
        image=QImage(160,88,QImage.Format.Format_ARGB32)
        image.fill(0)
        painter=QPainter(image);scene.render(painter);painter.end()
        gold_pixels=0
        for y in range(image.height()):
            for x in range(image.width()):
                color=image.pixelColor(x,y)
                if color.red()>245 and 200<color.green()<245 and 100<color.blue()<190:
                    gold_pixels+=1
        self.assertGreater(gold_pixels,10)

    def test_audio_fades_have_visible_envelope_at_playback_speed(self):
        clip=Clip('voice.wav',0,4,kind='audio',speed=2,volume=2.,
                  audio_fade_in=.5,audio_fade_out=.5)
        points=audio_fade_envelope_points(clip,40,80,44)
        self.assertEqual(len(points),18)
        self.assertAlmostEqual(points[0][0],2.)
        self.assertAlmostEqual(points[0][1],44*.27)
        self.assertAlmostEqual(points[8][0],20.)
        self.assertAlmostEqual(points[8][1],44*.27-(44*.22)/2)
        self.assertAlmostEqual(points[-1][0],78.)
        self.assertAlmostEqual(points[-1][1],44*.27)

    def test_audio_fade_envelope_is_painted_in_clip(self):
        clip=Clip('voice.wav',0,2,kind='audio',audio_fade_in=.5,audio_fade_out=.5)
        scene=QGraphicsScene();scene.setSceneRect(QRectF(0,0,80,44))
        scene.addItem(ClipGraphics(clip,0,0,80,44,40))
        image=QImage(160,88,QImage.Format.Format_ARGB32);image.fill(0)
        painter=QPainter(image);scene.render(painter);painter.end()
        green_pixels=0
        for y in range(image.height()):
            for x in range(image.width()):
                color=image.pixelColor(x,y)
                if color.green()>245 and color.red()>160 and color.blue()>190:
                    green_pixels+=1
        self.assertGreater(green_pixels,4)

    def test_dragging_audio_fade_handle_emits_duration_without_mutating_model(self):
        project=Project()
        clip=project.add_clip(Clip('voice.wav',0,2,kind='audio',audio_fade_in=.5,
            track_id=project.tracks[1].id))
        view=TimelineView();view.resize(600,360);view.pps=40
        view.set_project(project,[clip.id]);view.show();self.app.processEvents()
        emitted=[];view.audio_fade_changed.connect(lambda *args:emitted.append(args))
        item=view.items_by_id[clip.id]
        field,x,y=audio_fade_handle_points(clip,view.pps,item.rect().width(),item.rect().height())[0]
        self.assertEqual(field,'audio_fade_in')
        start=view.mapFromScene(item.scenePos()+QPointF(x,y))
        end=type(start)(start.x()+8,start.y())
        QTest.mousePress(view.viewport(),Qt.MouseButton.LeftButton,pos=start)
        QTest.mouseMove(view.viewport(),end,delay=20)
        QTest.mouseRelease(view.viewport(),Qt.MouseButton.LeftButton,pos=end)
        self.app.processEvents()
        self.assertEqual(len(emitted),1)
        self.assertEqual(emitted[0][0],clip.id)
        self.assertEqual(emitted[0][1],'audio_fade_in')
        self.assertAlmostEqual(emitted[0][2],.7,delta=.03)
        self.assertEqual(clip.audio_fade_in,.5)
        view.close()

    def test_volume_and_fade_handle_times_use_timeline_snap_targets(self):
        project=Project()
        clip=project.add_clip(Clip('',0,4,kind='audio',timeline_start=1.,
            track_id=project.tracks[0].id,audio_fade_in=.5,
            keyframes={'volume':[{'t':.5,'value':1.}]}))
        project.add_clip(Clip('',0,2,kind='audio',timeline_start=2.2,
            track_id=project.tracks[1].id))
        view=TimelineView();view.pps=40;view.set_project(project,[clip.id])
        self.assertAlmostEqual(view._snap_clip_local_time(clip,1.05),1.2)
        view.cursor_time=2.0
        self.assertAlmostEqual(view._snap_clip_local_time(clip,1.05),1.0)
        view.snapping=False
        self.assertAlmostEqual(view._snap_clip_local_time(clip,1.05),1.05)
        view.close()

    def test_animated_property_markers_are_separated_by_field(self):
        clip=Clip('',0,2,keyframes={'pos_x':[{'t':.5,'value':10}],
                                    'scale':[{'t':.5,'value':1.2}],
                                    'opacity':[{'t':.5,'value':.5}]})
        markers=keyframe_marker_points(clip,40,80,44)
        self.assertEqual([marker[0] for marker in markers],['pos_x','scale','opacity'])
        self.assertEqual(len({round(marker[3],2) for marker in markers}),3)
        self.assertTrue(all(marker[2]==20. for marker in markers))

    def test_dragging_non_volume_keyframe_retimes_marker_and_emits_signal(self):
        project=Project();clip=project.add_clip(Clip('',0,2,track_id=project.tracks[0].id,
            keyframes={'scale':[{'t':.5,'value':1.2,'easing':'smooth'}]}))
        view=TimelineView();view.resize(600,360);view.pps=40
        view.set_project(project,[clip.id]);view.show();self.app.processEvents()
        emitted=[];view.keyframe_time_changed.connect(lambda *args:emitted.append(args))
        item=view.items_by_id[clip.id]
        _field,_key,x,y=next(marker for marker in keyframe_marker_points(
            clip,view.pps,item.rect().width(),item.rect().height()) if marker[0]=='scale')
        start=view.mapFromScene(item.scenePos()+QPointF(x,y))
        end=type(start)(start.x()+12,start.y())
        QTest.mousePress(view.viewport(),Qt.MouseButton.LeftButton,pos=start)
        QTest.mouseMove(view.viewport(),end,delay=20)
        QTest.mouseRelease(view.viewport(),Qt.MouseButton.LeftButton,pos=end)
        self.app.processEvents()
        self.assertEqual(len(emitted),1)
        self.assertEqual(emitted[0][:2],(clip.id,'scale'))
        self.assertAlmostEqual(emitted[0][2],.5)
        self.assertAlmostEqual(emitted[0][3],.8,delta=.02)
        self.assertEqual(clip.keyframes['scale'][0]['t'],.5)
        view.close()

    def test_dragging_volume_node_emits_retimed_keyframe(self):
        project=Project()
        clip=project.add_clip(Clip('voice.wav',0,2,kind='audio',
            track_id=project.tracks[1].id,
            keyframes={'volume':[{'t':.5,'value':2.,'easing':'linear'},
                                 {'t':1.5,'value':1.,'easing':'linear'}]}))
        view=TimelineView();view.resize(600,360);view.pps=40
        view.set_project(project,[clip.id]);view.show();self.app.processEvents()
        emitted=[];view.volume_keyframe_changed.connect(lambda *args:emitted.append(args))
        item=view.items_by_id[clip.id]
        node=volume_envelope_points(clip,view.pps,item.rect().width(),item.rect().height())[0]
        start=view.mapFromScene(item.scenePos()+QPointF(*node))
        end=type(start)(start.x()+16,start.y()+2)
        QTest.mousePress(view.viewport(),Qt.MouseButton.LeftButton,pos=start)
        QTest.mouseMove(view.viewport(),end,delay=20)
        QTest.mouseRelease(view.viewport(),Qt.MouseButton.LeftButton,pos=end)
        self.app.processEvents()
        self.assertEqual(len(emitted),1)
        self.assertEqual(emitted[0][0],clip.id)
        self.assertAlmostEqual(emitted[0][1],.5)
        self.assertAlmostEqual(emitted[0][2],.9,delta=.03)
        self.assertAlmostEqual(emitted[0][3],1.19,delta=.05)
        self.assertEqual(clip.keyframes['volume'][0]['t'],.5)  # model waits for undoable slot
        view.close()

    def test_waveform_generates_ten_peaks_per_second(self):
        with tempfile.TemporaryDirectory(prefix='bfs_waveform_') as folder:
            root=Path(folder);source=root/'tone.wav'
            subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y',
                '-f','lavfi','-i','sine=frequency=440:duration=1',str(source)],check=True)
            cache=TimelineVisualCache(root/'cache',start_worker=False)
            target=cache.waveform_path(str(source),0)
            cache._waveform(str(source),0,target)
            data=cache.get_wave(str(source),0,request=False)
            self.assertEqual(data['step'],.1)
            self.assertEqual(data['offset'],0)
            self.assertEqual(len(data['peaks']),10)
            self.assertTrue(all(.05 < peak < .2 for peak in data['peaks']))

    def test_waveform_timeout_kills_blocked_decoder_without_cache_file(self):
        processes=[]
        class HangingProcess:
            def __init__(self,*args,**kwargs):
                self.stdout=type('Pipe',(),{'close':lambda self:None})()
                self.returncode=None;self.killed=False
                processes.append(self)
            def communicate(self,timeout):
                raise subprocess.TimeoutExpired('ffmpeg',timeout)
            def poll(self):return self.returncode
            def kill(self):self.killed=True;self.returncode=-9
            def wait(self):return self.returncode

        with tempfile.TemporaryDirectory(prefix='bfs_waveform_timeout_') as folder:
            root=Path(folder);source=root/'source.wav';source.write_bytes(b'fixture')
            cache=TimelineVisualCache(root/'cache',start_worker=False)
            target=cache.waveform_path(str(source),0)
            with patch('berofel.services.timeline_visuals.subprocess.Popen',HangingProcess):
                with self.assertRaises(subprocess.TimeoutExpired):
                    cache._waveform(str(source),0,target)
            process=processes[0]
            self.assertTrue(process.killed)
            self.assertFalse(target.exists())
            self.assertFalse(list(target.parent.glob('*.tmp')))

    def test_waveform_memory_cache_evicts_least_recent_tiles(self):
        with tempfile.TemporaryDirectory(prefix='bfs_wave_lru_') as folder:
            root=Path(folder);source=root/'source.wav';source.write_bytes(b'fixture')
            cache=TimelineVisualCache(root/'cache',start_worker=False)
            for at in (0,60,120):
                cache.waveform_path(str(source),at).write_text(
                    json.dumps({'offset':at,'peaks':[.5]}),encoding='utf-8')
            with patch.object(timeline_visuals,'MAX_MEMORY_WAVE_TILES',2):
                first=cache.get_wave(str(source),0,request=False)
                cache.get_wave(str(source),60,request=False)
                self.assertIs(cache.get_wave(str(source),0,request=False),first)
                cache.get_wave(str(source),120,request=False)
            self.assertEqual(len(cache.memory),2)
            self.assertIn(str(cache.waveform_path(str(source),0)),cache.memory)
            self.assertNotIn(str(cache.waveform_path(str(source),60)),cache.memory)
            self.assertIn(str(cache.waveform_path(str(source),120)),cache.memory)

    def test_visual_cache_pruning_is_bounded_and_preserves_unknown_files(self):
        with tempfile.TemporaryDirectory(prefix='bfs_visual_prune_') as folder:
            cache=TimelineVisualCache(Path(folder)/'cache',start_worker=False)
            entries=[]
            for index in range(3):
                path=cache.folder/f'{index:020x}_{index}s.jpg';path.write_bytes(bytes([index])*10)
                os.utime(path,(index+1,index+1));entries.append(path)
            unrelated=cache.folder/'cover.jpg';unrelated.write_bytes(b'user data')
            temporary=cache.folder/'partial.tmp';temporary.write_bytes(b'preserve')
            cache.prune(max_megabytes=15/(1024*1024))
            self.assertFalse(entries[0].exists())
            self.assertFalse(entries[1].exists())
            self.assertTrue(entries[2].exists())
            self.assertTrue(unrelated.exists())
            self.assertTrue(temporary.exists())

    def test_closing_visual_cache_kills_decoder_and_joins_worker(self):
        started=threading.Event();processes=[]
        class BlockingProcess:
            def __init__(self,*args,**kwargs):
                self.stdout=type('Pipe',(),{'close':lambda self:None})()
                self.returncode=None;self.killed=False;self.finished=threading.Event()
                processes.append(self)
            def communicate(self,timeout):
                started.set()
                if not self.finished.wait(timeout):
                    raise subprocess.TimeoutExpired('ffmpeg',timeout)
                return b'',b''
            def poll(self):return self.returncode
            def kill(self):
                self.killed=True;self.returncode=-9;self.finished.set()
            def wait(self):return self.returncode

        with tempfile.TemporaryDirectory(prefix='bfs_visual_close_') as folder:
            root=Path(folder);source=root/'source.wav';source.write_bytes(b'fixture')
            cache=TimelineVisualCache(root/'cache',start_worker=True)
            target=cache.waveform_path(str(source),0)
            with patch('berofel.services.timeline_visuals.subprocess.Popen',BlockingProcess):
                cache._enqueue(10,'wave',str(source),0,target)
                self.assertTrue(started.wait(2.))
                worker=cache.thread
                cache.close()
                self.assertFalse(worker.is_alive())
                self.assertTrue(processes[0].killed)
                self.assertFalse(target.exists())
                self.assertFalse(list(target.parent.glob('*.tmp')))


if __name__=='__main__':unittest.main()

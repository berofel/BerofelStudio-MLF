"""DSP de voz: filtros reais no mesmo grafo usado pela prévia e exportação."""
import json
import math
from pathlib import Path
import subprocess
import tempfile
import unittest
import wave

import numpy as np

from berofel.core.project import Clip, Project
from berofel.services.ffmpeg import ffmpeg_path, supports_filter
from berofel.services.export_multitrack import export_audio_wav, export_project
from berofel.services.preview_pipeline import prepare_commands
from berofel.services.voice_dsp import (VoiceEQ, clip_voice_eq, voice_eq_filters,
    voice_pitch_filters, combined_rubberband_filter)


class VoiceDSPTests(unittest.TestCase):
    def test_neutral_bypass_and_ranges(self):
        self.assertEqual(voice_eq_filters(), [])
        self.assertEqual(voice_pitch_filters(0), [])
        self.assertEqual(voice_eq_filters(VoiceEQ(8,-4,5,bypass=True)), [])
        self.assertEqual(voice_eq_filters(VoiceEQ(6,3,-2)), [
            'bass=f=120:width_type=q:width=0.707:gain=6.00',
            'equalizer=f=1200:t=q:w=1.000:g=3.00',
            'treble=f=5000:width_type=q:width=0.707:gain=-2.00',
            'alimiter=limit=0.95:level=disabled'])
        with self.assertRaises(ValueError):
            voice_eq_filters(VoiceEQ(bass_db=12.1))
        with self.assertRaises(ValueError):
            voice_pitch_filters(4.1)

    def test_pitch_filter_uses_formant_preserving_backend_when_available(self):
        filters=voice_pitch_filters(4.,rubberband_available=True)
        self.assertEqual(len(filters),1)
        self.assertIn('pitch=1.25992105',filters[0])
        self.assertIn('formant=preserved',filters[0])
        self.assertIn('tempo=1.0',filters[0])
        fallback=voice_pitch_filters(4.)
        self.assertTrue(fallback[0].startswith('asetrate='))

    def test_combined_speed_and_pitch_use_one_rubberband_pass(self):
        graph=combined_rubberband_filter(1.15,-1.)
        self.assertIn('tempo=1.150000',graph)
        self.assertIn('pitch=0.94387431',graph)
        self.assertIn('formant=preserved',graph)
        self.assertEqual(graph.count('rubberband='),1)
        with self.assertRaises(ValueError):combined_rubberband_filter(0.,0.)
        with self.assertRaises(ValueError):combined_rubberband_filter(1.15,-4.1)

    def test_pitch_shift_changes_frequency_without_changing_duration(self):
        with tempfile.TemporaryDirectory(prefix='bfs_voice_pitch_') as folder:
            root=Path(folder);source=root/'source.wav';rate=48000
            subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y',
                '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=1',
                '-c:a','pcm_s16le',str(source)],check=True,capture_output=True,timeout=20)
            project=Project(width=160,height=90,fps=12)
            clip=project.add_clip(Clip(str(source),0,1,kind='audio',
                track_id=project.tracks[-1].id))

            def render():
                command=prepare_commands(project,0,root/'preview',preview_width=160,
                    fps=12,window=1).audio
                result=subprocess.run(command,capture_output=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
                samples=np.frombuffer(result.stdout,dtype='<i2').reshape(-1,2).mean(axis=1)
                return result.stdout,samples

            def dominant(samples):
                samples=samples[int(.1*rate):int(.9*rate)]
                frequencies=np.fft.rfftfreq(len(samples),1/rate)
                spectrum=np.abs(np.fft.rfft(samples*np.hanning(len(samples))))
                return frequencies[int(np.argmax(spectrum))]

            original_raw,original=render()
            self.assertAlmostEqual(dominant(original),440.,delta=2.)
            for semitones in (-4.,4.):
                clip.voice_pitch_semitones=semitones
                rendered_raw,rendered=render()
                self.assertEqual(len(rendered_raw),len(original_raw))
                actual=dominant(rendered)
                expected=440*2**(semitones/12)
                self.assertAlmostEqual(actual,expected,delta=3.)
            final=root/'pitch_export.mp4'
            export_project(project,str(final))
            decoded=subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y',
                '-i',str(final),'-map','0:a:0','-ac','2','-ar',str(rate),'-f','s16le','pipe:1'],
                capture_output=True,timeout=30)
            self.assertEqual(decoded.returncode,0,decoded.stderr.decode(errors='replace'))
            exported=np.frombuffer(decoded.stdout,dtype='<i2').reshape(-1,2).mean(axis=1)
            self.assertAlmostEqual(dominant(exported),440*2**(4/12),delta=5.)
            clip.voice_dsp_bypass=True
            raw_bypass,bypass=render()
            self.assertEqual(raw_bypass,original_raw)

    def test_narration_speed_preserves_pitch_when_rubberband_is_available(self):
        if not supports_filter('rubberband'):
            self.skipTest('FFmpeg distribuído não inclui o filtro Rubber Band.')
        with tempfile.TemporaryDirectory(prefix='bfs_voice_speed_') as folder:
            root=Path(folder);source=root/'source.wav';rate=48000
            subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y',
                '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=2',
                '-c:a','pcm_s16le',str(source)],check=True,capture_output=True,timeout=20)
            project=Project(width=160,height=90,fps=12)
            clip=project.add_clip(Clip(str(source),0,2,kind='audio',speed=1.25,
                preserve_pitch=True,voice_pitch_semitones=-1.,
                track_id=project.tracks[-1].id))
            commands=prepare_commands(project,0,root/'preview',preview_width=160,
                fps=12,window=project.duration)
            graph_option=next(option for option in ('-filter_complex_script','-/filter_complex')
                              if option in commands.audio)
            graph=Path(commands.audio[commands.audio.index(graph_option)+1]).read_text(
                encoding='utf-8')
            self.assertEqual(graph.count('rubberband='),1,
                             'Pitch e velocidade devem compartilhar um passe Rubber Band.')
            result=subprocess.run(commands.audio,capture_output=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
            samples=np.frombuffer(result.stdout,dtype='<i2').reshape(-1,2).mean(axis=1)
            self.assertAlmostEqual(len(samples)/rate,clip.duration,delta=.02)
            region=samples[int(rate*.15):int(len(samples)-rate*.15)]
            spectrum=np.abs(np.fft.rfft(region*np.hanning(len(region))))
            bins=np.fft.rfftfreq(len(region),1/rate)
            pitch=bins[int(np.argmax(spectrum))]
            self.assertAlmostEqual(pitch,440*2**(-1/12),delta=4.)
            wav_path=root/'speed.wav'
            export_audio_wav(project,wav_path)
            with wave.open(str(wav_path),'rb') as rendered:
                self.assertAlmostEqual(rendered.getnframes()/rate,clip.duration,delta=.02)

    def test_pitch_only_processing_limits_clipping(self):
        with tempfile.TemporaryDirectory(prefix='bfs_voice_limiter_') as folder:
            root=Path(folder);source=root/'loud.wav'
            subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y',
                '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=1',
                '-af','volume=4','-c:a','pcm_s16le',str(source)],check=True,
                capture_output=True,timeout=20)
            project=Project(width=160,height=90,fps=12)
            clip=project.add_clip(Clip(str(source),0,1,kind='audio',
                voice_pitch_semitones=4,track_id=project.tracks[-1].id))
            command=prepare_commands(project,0,root/'preview',preview_width=160,
                                     fps=12,window=1).audio
            result=subprocess.run(command,capture_output=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
            samples=np.frombuffer(result.stdout,dtype='<i2')
            self.assertLessEqual(np.max(np.abs(samples.astype(np.int32))),31500)

    def test_clip_eq_is_persisted_and_old_projects_default_to_neutral(self):
        with tempfile.TemporaryDirectory(prefix='bfs_voice_dsp_project_') as folder:
            path=Path(folder)/'voice.bfs'
            project=Project()
            clip=project.add_clip(Clip('voice.wav',0,1,kind='audio',
                track_id=project.tracks[-1].id,voice_eq_bass_db=3.5,
                voice_eq_mids_db=-2.,voice_eq_treble_db=1.,
                voice_pitch_semitones=1.5,voice_dsp_bypass=True,
                voice_dsp_preset='Voz encorpada'))
            project.save(str(path))
            loaded=Project.load(str(path)).clip(clip.id)
            self.assertEqual(clip_voice_eq(loaded),VoiceEQ(3.5,-2.,1.,True))
            self.assertEqual(loaded.voice_pitch_semitones,1.5)
            data=json.loads(path.read_text(encoding='utf-8'))
            for key in ('voice_eq_bass_db','voice_eq_mids_db','voice_eq_treble_db',
                        'voice_pitch_semitones','voice_dsp_bypass','voice_dsp_preset'):
                data['clips'][0].pop(key)
            path.write_text(json.dumps(data),encoding='utf-8')
            old=Project.load(str(path)).clip(clip.id)
            self.assertEqual(clip_voice_eq(old),VoiceEQ())
            self.assertEqual(old.voice_pitch_semitones,0.)

    def test_eq_bands_change_expected_spectrum_in_the_live_preview_graph(self):
        with tempfile.TemporaryDirectory(prefix='bfs_voice_eq_preview_') as folder:
            root=Path(folder);source=root/'voice.wav';rate=48000;duration=1.5
            times=np.arange(int(rate*duration),dtype=np.float64)/rate
            samples=sum(.04*np.sin(2*math.pi*frequency*times)
                        for frequency in (120,1200,5000))
            pcm=np.clip(samples*32767,-32768,32767).astype('<i2')
            with wave.open(str(source),'wb') as output:
                output.setnchannels(1);output.setsampwidth(2);output.setframerate(rate)
                output.writeframes(pcm.tobytes())
            project=Project(width=160,height=90,fps=12)
            clip=project.add_clip(Clip(str(source),0,duration,kind='audio',
                track_id=project.tracks[-1].id))

            def measure_levels(raw):
                samples_out=np.frombuffer(raw,dtype='<i2').reshape(-1,2).mean(axis=1)
                samples_out=samples_out[int(rate*.3):int(rate*1.2)]
                spectrum=np.abs(np.fft.rfft(samples_out*np.hanning(len(samples_out))))
                bins=np.fft.rfftfreq(len(samples_out),1/rate)
                return {frequency:float(spectrum[np.argmin(abs(bins-frequency))])
                        for frequency in (120,1200,5000)}

            def render_levels():
                commands=prepare_commands(project,0,root/'preview',preview_width=160,
                                          fps=12,window=duration)
                result=subprocess.run(commands.audio,capture_output=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
                return measure_levels(result.stdout)

            baseline=render_levels()
            clip.voice_eq_bass_db=6.
            bass=render_levels()
            self.assertGreater(bass[120]/baseline[120],1.3)
            self.assertLess(bass[1200]/baseline[1200],1.25)
            final=root/'eq_export.mp4'
            export_project(project,str(final))
            decoded=subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y',
                '-i',str(final),'-map','0:a:0','-ac','2','-ar',str(rate),'-f','s16le','pipe:1'],
                capture_output=True,timeout=30)
            self.assertEqual(decoded.returncode,0,decoded.stderr.decode(errors='replace'))
            exported=measure_levels(decoded.stdout)
            self.assertGreater(exported[120]/baseline[120],1.2)
            wav_path=root/'voice_mix.wav'
            export_audio_wav(project,wav_path)
            with wave.open(str(wav_path),'rb') as wav_file:
                self.assertEqual(wav_file.getframerate(),48000)
                self.assertEqual(wav_file.getnchannels(),2)
                self.assertEqual(wav_file.getsampwidth(),3)
                self.assertEqual(wav_file.getcomptype(),'NONE')
                wav_payload=wav_file.readframes(wav_file.getnframes())
            triplets=np.frombuffer(wav_payload,dtype=np.uint8).reshape(-1,3)
            packed=(triplets[:,0].astype(np.int32) |
                    (triplets[:,1].astype(np.int32)<<8) |
                    (triplets[:,2].astype(np.int32)<<16))
            wav_samples=((packed ^ 0x800000)-0x800000).astype(np.float64)
            wav_samples=wav_samples.reshape(-1,2).mean(axis=1)
            wav_samples=wav_samples[int(rate*.3):int(rate*1.2)]
            wav_spec=np.abs(np.fft.rfft(wav_samples*np.hanning(len(wav_samples))))
            wav_bins=np.fft.rfftfreq(len(wav_samples),1/rate)
            wav_bass=wav_spec[np.argmin(abs(wav_bins-120))]
            self.assertGreater(wav_bass/baseline[120],1.2)
            clip.voice_eq_bass_db=0.
            clip.voice_eq_mids_db=6.
            mids=render_levels()
            self.assertGreater(mids[1200]/baseline[1200],1.5)
            clip.voice_eq_mids_db=0.
            clip.voice_eq_treble_db=6.
            treble=render_levels()
            self.assertGreater(treble[5000]/baseline[5000],1.3)
            clip.voice_pitch_semitones=4.
            clip.voice_dsp_bypass=True
            bypass=render_levels()
            for frequency in baseline:
                self.assertAlmostEqual(bypass[frequency]/baseline[frequency],1.,delta=.002)


if __name__=='__main__':unittest.main()

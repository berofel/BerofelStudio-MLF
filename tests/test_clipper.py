"""Testes sintéticos do ranking do Clipador, cache e decodificação PCM."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from berofel.core.project import Clip
from berofel.services.clip_audio_signals import extract_frames_from_chunks
from berofel.services.clipper import (ClipperOptions, _candidate_spans,
    _dialogue_context_bounds, _local_textrank_salience, _normalise_words,
    analyze_clips, audio_features)


def transcript(source, count=180, start=0., step=.2):
    words=[]
    vocabulary=('Hoje', 'eu', 'descobri', 'por', 'que', 'isso', 'mudou', 'tudo',
                'e', 'o', 'resultado', 'foi', 'surpreendente.', 'Depois',
                'explico', 'como', 'funciona.')
    for index in range(count):
        at=start+index*step
        text=vocabulary[index%len(vocabulary)]
        if index%48==47 and not text.endswith(('.', '?', '!')):text+='.'
        words.append({'id':f'w{index}','source':str(Path(source).resolve()),
            'source_start':at,'source_end':at+.14,'text':text,
            'probability':.94})
    return words


class ClipperTests(unittest.TestCase):
    def test_dialogue_boundary_keeps_nearby_question_and_answer_together(self):
        words=[]
        at=0.
        for text in ('Como isso funciona?', 'Porque o editor mantém contexto.'):
            for token in text.split():
                words.append({'id':f'w{len(words)}','start_ms':round(at*1000),
                    'end_ms':round((at+.22)*1000),'text':token,
                    'speaker_id':'speaker-a' if len(words)<3 else 'speaker-b'})
                at+=.3
            at+=.4
        start,end,expanded_start,expanded_end=_dialogue_context_bounds(
            words,0,2,5000.)
        self.assertEqual(start,0)
        self.assertEqual(end,len(words)-1)
        self.assertFalse(expanded_start)
        self.assertTrue(expanded_end)

    def test_dialogue_boundary_never_exceeds_configured_candidate_duration(self):
        words=[]
        at=0.
        for text in ('Como isso funciona?', 'Porque o editor mantém contexto.'):
            for token in text.split():
                words.append({'id':f'w{len(words)}','start_ms':round(at*1000),
                    'end_ms':round((at+.22)*1000),'text':token,
                    'speaker_id':'speaker-a' if len(words)<3 else 'speaker-b'})
                at+=.3
            at+=.4
        start,end,_,expanded_end=_dialogue_context_bounds(words,0,2,1800.)
        self.assertEqual(start,0)
        self.assertEqual(end,2)
        self.assertFalse(expanded_end)

    def test_dependent_answer_candidate_can_include_its_nearby_question(self):
        words=[]
        at=0.
        for text in ('Como isso funciona?', 'Porque o editor mantém contexto.'):
            for token in text.split():
                words.append({'id':f'w{len(words)}','start_ms':round(at*1000),
                    'end_ms':round((at+.22)*1000),'text':token,
                    'speaker_id':'speaker-a' if len(words)<3 else 'speaker-b'})
                at+=.3
            at+=.4
        start,end,expanded_start,_=_dialogue_context_bounds(
            words,3,len(words)-1,5000.)
        self.assertEqual(start,0)
        self.assertEqual(end,len(words)-1)
        self.assertTrue(expanded_start)

    def test_dialogue_turn_index_is_built_once_for_all_candidate_windows(self):
        from berofel.services import clipper as clipper_service
        source=str(Path('fixture.wav').resolve())
        clip=Clip(source,0.,40.,kind='audio')
        words=_normalise_words(clip,transcript(source,count=220,step=.12))
        with patch.object(clipper_service,'_utterances',
                          wraps=clipper_service._utterances) as utterances:
            _candidate_spans(words,ClipperOptions(4.,8.,8,6.))
        self.assertEqual(utterances.call_count,1)

    def test_candidate_edges_snap_to_whole_transcribed_words_and_duration(self):
        with tempfile.TemporaryDirectory(prefix='bfs_clipper_words_') as folder:
            words=transcript(Path(folder)/'voice.wav',count=150,step=.12)
            clip=Clip(str(Path(folder)/'voice.wav'),0.,20.,kind='audio')
            candidates=_candidate_spans(
                __import__('berofel.services.clipper',fromlist=['_normalise_words'])
                    ._normalise_words(clip,words),
                ClipperOptions(4.,8.,8,6.))
        self.assertTrue(candidates)
        for item in candidates:
            self.assertGreaterEqual(item['end_ms']-item['start_ms'],4000)
            self.assertLessEqual(item['end_ms']-item['start_ms'],8000)
            self.assertEqual(item['start_ms'],item['words'][0]['start_ms'])
            self.assertEqual(item['end_ms'],item['words'][-1]['end_ms'])

    def test_candidate_exposes_heuristic_irony_context_without_claiming_certainty(self):
        with tempfile.TemporaryDirectory(prefix='bfs_clipper_irony_') as folder:
            source=Path(folder)/'source.wav';source.write_bytes(b'synthetic placeholder')
            clip=Clip(str(source),0.,40.,kind='audio')
            texts=(
                'O editor travou cinco vezes durante a instalação.',
                'Perfeito: o editor travou cinco vezes de novo durante a instalação.',
                'A timeline mostra as faixas de áudio e vídeo com clareza.',
                'A biblioteca organiza os arquivos importados do projeto.',
            )
            words=[]; at=0.
            for text in texts:
                for token in text.split():
                    words.append({'id':f'w{len(words)}','source':str(source.resolve()),
                        'source_start':at,'source_end':at+.16,'text':token,'probability':.98})
                    at+=.24
                at+=.55
            with patch('berofel.services.clipper.audio_features',return_value=(None,False)):
                result=analyze_clips([clip],words,ClipperOptions(4.,12.,8,6.),
                    cache_dir=Path(folder)/'cache')
        candidates=result['candidates']
        self.assertTrue(candidates)
        marked=[candidate for candidate in candidates if candidate['irony_suspected']]
        self.assertTrue(marked)
        self.assertTrue(any('Possíveis sinais de ironia' in reason
                            for candidate in marked for reason in candidate['reasons']))
        self.assertTrue(all('discourse_score' in candidate for candidate in candidates))
        self.assertTrue(any(candidate['discourse_cues'] for candidate in candidates))
        self.assertIn('irony_candidates',result['stats'])

    def test_candidate_metadata_includes_text_tiling_topic_boundaries(self):
        with tempfile.TemporaryDirectory(prefix='bfs_clipper_topics_') as folder:
            source=Path(folder)/'source.wav';source.write_bytes(b'synthetic placeholder')
            clip=Clip(str(source),0.,48.,kind='audio')
            texts=(
                'O editor importa vídeos e organiza a biblioteca de mídia.',
                'A timeline mostra os cortes e as faixas de áudio.',
                'As legendas acompanham cada palavra da transcrição.',
                'Mudando de assunto, ontem choveu muito no bairro.',
                'A rua alagou e os ônibus atrasaram durante a tarde.',
                'Os moradores pediram uma solução para a drenagem.',
            )
            words=[]; at=0.
            for text in texts:
                for token in text.split():
                    words.append({'id':f'w{len(words)}','source':str(source.resolve()),
                        'source_start':at,'source_end':at+.18,'text':token,'probability':.99})
                    at+=.25
                at+=.45
            with patch('berofel.services.clipper.audio_features',return_value=(None,False)):
                result=analyze_clips([clip],words,ClipperOptions(6.,18.,8,6.),
                    cache_dir=Path(folder)/'cache')
        self.assertTrue(result['candidates'])
        self.assertTrue(any(candidate['topic_shift_before'] >= .52 or
                            candidate['topic_shift_after'] >= .52 or
                            candidate['topic_shift_internal'] >= .52
                            for candidate in result['candidates']))

    def test_text_only_mode_keeps_candidates_and_labels_audio_unavailable(self):
        with tempfile.TemporaryDirectory(prefix='bfs_clipper_text_') as folder:
            source=Path(folder)/'source.mov';source.write_bytes(b'synthetic placeholder')
            clip=Clip(str(source),0.,36.,kind='video')
            words=transcript(source,count=180,step=.2)
            with patch('berofel.services.clipper.audio_features',return_value=(None,False)):
                result=analyze_clips([clip],words,ClipperOptions(8.,16.,5,6.),
                                     cache_dir=Path(folder)/'cache')
        self.assertTrue(result['candidates'])
        self.assertTrue(all(not item['audio_available'] for item in result['candidates']))
        self.assertTrue(any('faixa de áudio' in warning
                            for item in result['candidates'] for warning in item['warnings']))
        self.assertTrue(any(item['audio_score'] is None for item in result['candidates']))

    def test_source_timestamps_are_not_rebased_after_a_nonzero_clip_inpoint(self):
        with tempfile.TemporaryDirectory(prefix='bfs_clipper_inpoint_') as folder:
            source=Path(folder)/'source.mov';source.write_bytes(b'synthetic placeholder')
            clip=Clip(str(source),10.,46.,kind='video')
            words=transcript(source,count=180,start=10.,step=.2)
            with patch('berofel.services.clipper.audio_features',return_value=(None,False)):
                result=analyze_clips([clip],words,ClipperOptions(8.,16.,5,6.),
                                     cache_dir=Path(folder)/'cache')
        self.assertTrue(result['candidates'])
        self.assertGreaterEqual(result['candidates'][0]['source_start'],10.)
        self.assertLessEqual(result['candidates'][0]['source_end'],46.)

    def test_identical_source_range_reuses_rank_cache_across_clip_ids(self):
        with tempfile.TemporaryDirectory(prefix='bfs_clipper_range_cache_') as folder:
            source=Path(folder)/'source.wav';source.write_bytes(b'synthetic placeholder')
            first_clip=Clip(str(source),0.,36.,kind='audio',title='Original')
            second_clip=Clip(str(source),0.,36.,kind='audio',title='Cópia')
            words=transcript(source,count=180,step=.2)
            cache=Path(folder)/'cache'
            with patch('berofel.services.clipper.audio_features',return_value=(None,False)) as audio:
                analyze_clips([first_clip],words,ClipperOptions(8.,16.,5,6.),cache_dir=cache)
                second=analyze_clips([second_clip],words,ClipperOptions(8.,16.,5,6.),cache_dir=cache)
        self.assertEqual(audio.call_count,1)
        self.assertEqual(second['stats']['cache_hits'],1)
        self.assertTrue(all(item['clip_id']==second_clip.id for item in second['candidates']))
        self.assertTrue(all(event['clip_id']==second_clip.id for event in second['events']))

    def test_missing_transcript_returns_actionable_state_without_running_audio_decode(self):
        with tempfile.TemporaryDirectory(prefix='bfs_clipper_no_words_') as folder:
            source=Path(folder)/'source.wav';source.write_bytes(b'placeholder')
            clip=Clip(str(source),0.,20.,kind='audio')
            with patch('berofel.services.clipper.audio_features') as audio:
                result=analyze_clips([clip],[],cache_dir=Path(folder)/'cache')
        audio.assert_not_called()
        self.assertEqual(result['clips'][0]['status'],'missing_transcript')
        self.assertIn('Transcreva',result['clips'][0]['warnings'][0])

    def test_result_cache_is_invalidated_by_transcript_text_and_options(self):
        with tempfile.TemporaryDirectory(prefix='bfs_clipper_cache_') as folder:
            source=Path(folder)/'source.wav';source.write_bytes(b'synthetic placeholder')
            clip=Clip(str(source),0.,36.,kind='audio')
            words=transcript(source,count=180,step=.2)
            cache=Path(folder)/'cache'
            fake_frames=extract_frames_from_chunks([],16000)
            with patch('berofel.services.clipper.audio_features',return_value=(fake_frames,False)) as audio:
                first=analyze_clips([clip],words,ClipperOptions(8.,16.,5,6.),cache_dir=cache)
                second=analyze_clips([clip],words,ClipperOptions(8.,16.,5,6.),cache_dir=cache)
                changed=[dict(word) for word in words]
                changed[2]['text']='alterado'
                third=analyze_clips([clip],changed,ClipperOptions(8.,16.,5,6.),cache_dir=cache)
                fourth=analyze_clips([clip],changed,ClipperOptions(8.,16.,6,6.),cache_dir=cache)
        self.assertEqual(audio.call_count,3)
        self.assertEqual(second['stats']['cache_hits'],1)
        self.assertEqual(first['candidates'],second['candidates'])
        self.assertNotEqual(first['candidates'][0]['text'],third['candidates'][0]['text'])
        self.assertTrue(fourth['candidates'])

    def test_ffmpeg_decodes_audio_in_small_stream_and_persists_reusable_rms_frames(self):
        import wave
        with tempfile.TemporaryDirectory(prefix='bfs_clipper_ffmpeg_') as folder:
            source=Path(folder)/'tone.wav'
            rate=16000
            samples=(.12*np.sin(2*np.pi*220*np.arange(rate*2)/rate)).astype('<f4')
            pcm=np.clip(samples*32767,-32768,32767).astype('<i2')
            with wave.open(str(source),'wb') as audio:
                audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(rate)
                audio.writeframes(pcm.tobytes())
            cache=Path(folder)/'cache'
            frames,hit=audio_features(str(source),0.,2.,cache_dir=cache)
            self.assertFalse(hit)
            self.assertIsNotNone(frames)
            self.assertAlmostEqual(float(np.median(frames.rms_dbfs)),
                                   20*np.log10(.12/np.sqrt(2)),delta=1.2)
            frames2,hit2=audio_features(str(source),0.,2.,cache_dir=cache)
        self.assertTrue(hit2)
        np.testing.assert_allclose(frames.rms_dbfs,frames2.rms_dbfs)
        np.testing.assert_allclose(frames.peak_dbfs,frames2.peak_dbfs)

    def test_relative_audio_surge_is_linked_to_existing_transcript_words(self):
        rate=16000
        signal=np.full(rate*12,.02,dtype=np.float32)
        signal[rate*6:rate*7]=.35
        frames=extract_frames_from_chunks([signal],rate)
        from berofel.services.clip_audio_signals import detect_energy_events
        events=detect_energy_events(frames,[(0,11000)],relative_rise_db=6,
                                    min_duration_ms=80)
        self.assertTrue(any(5900<=event['start_ms']<=6100 and
                            event['speech_verified'] for event in events),events)
        self.assertFalse(any(event['start_ms']>=11000 for event in events))

    def test_quick_audio_mode_reuses_cached_timeline_waveform_without_decoding(self):
        class CachedWaveform:
            def get_wave(self, source, at, request=False):
                self.request=request
                return {'offset':0.,'step':.1,'peaks':[.1,.2,.3,.4,.5,
                    .4,.3,.2,.1,.08,.1,.12,.14,.16,.18,.2,.22,.24,.26,.28]}
        with tempfile.TemporaryDirectory(prefix='bfs_clipper_cached_wave_') as folder:
            source=Path(folder)/'source.wav';source.write_bytes(b'fixture')
            provider=CachedWaveform()
            with patch('berofel.services.clipper._audio_pcm_chunks') as decode:
                frames,hit=audio_features(str(source),0.,2.,cache_dir=Path(folder)/'cache',
                    waveform_provider=provider,waveform_only=True)
        decode.assert_not_called()
        self.assertTrue(hit)
        self.assertIsNotNone(frames)
        self.assertEqual(frames.level_kind,'waveform_peak_proxy')
        self.assertAlmostEqual(frames.frame_ms,100.)
        self.assertFalse(provider.request)

    def test_quick_audio_mode_without_complete_waveform_does_not_decode(self):
        class MissingWaveform:
            def get_wave(self, source, at, request=False):
                return None
        with tempfile.TemporaryDirectory(prefix='bfs_clipper_missing_wave_') as folder:
            source=Path(folder)/'source.wav';source.write_bytes(b'fixture')
            with patch('berofel.services.clipper._audio_pcm_chunks') as decode:
                frames,hit=audio_features(str(source),0.,2.,cache_dir=Path(folder)/'cache',
                    waveform_provider=MissingWaveform(),waveform_only=True)
        decode.assert_not_called()
        self.assertIsNone(frames)
        self.assertFalse(hit)

    def test_advanced_text_rank_is_local_deterministic_and_bounded(self):
        texts=('O editor organiza os cortes da timeline e as legendas do vídeo.',
               'A timeline mostra os cortes e a duração de cada clipe.',
               'As legendas acompanham o áudio e a transcrição do vídeo.')
        words=[];at=0.
        for text in texts:
            for token in text.split():
                words.append({'start_ms':at,'end_ms':at+100,'text':token})
                at+=120
            words[-1]['text']=words[-1]['text'].rstrip('.')+'.'
            at+=400
        first=_local_textrank_salience(words)
        second=_local_textrank_salience(words)
        self.assertIsNotNone(first)
        self.assertEqual(first,second)
        self.assertGreaterEqual(first,0.)
        self.assertLessEqual(first,1.)


if __name__=='__main__':
    unittest.main()

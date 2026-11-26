"""Testes sintéticos do ranking do Clipador, cache e decodificação PCM."""
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from berofel.core.project import Clip
from berofel.services.clip_audio_signals import FrameFeatures, extract_frames_from_chunks
from berofel.services.clipper import (ClipperOptions, _candidate_spans,
    _dialogue_context_bounds, _local_textrank_salience, _normalise_words,
    _utterances,
    analyze_clips, audio_features, suggest_title)


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

    def test_question_links_to_answer_by_local_topic_overlap_without_speaker_ids(self):
        words=[]
        at=0.
        for text in ('Como o editor mantém a transcrição?',
                     'O editor mantém as palavras salvas no projeto.'):
            for token in text.split():
                words.append({'id':f'w{len(words)}','start_ms':round(at*1000),
                    'end_ms':round((at+.22)*1000),'text':token})
                at+=.3
            at+=.4
        question_end=next(i for i,word in enumerate(words)
                          if word['text'].endswith('?'))
        start,end,_,expanded_end=_dialogue_context_bounds(
            words,0,question_end,5000.)
        self.assertEqual(start,0)
        self.assertEqual(end,len(words)-1)
        self.assertTrue(expanded_end)

        answer_start=question_end+1
        start,end,expanded_start,_=_dialogue_context_bounds(
            words,answer_start,len(words)-1,5000.)
        self.assertEqual(start,0)
        self.assertEqual(end,len(words)-1)
        self.assertTrue(expanded_start)

    def test_question_does_not_absorb_unrelated_turn_on_one_shared_word(self):
        words=[]
        at=0.
        for text in ('Quem venceu a corrida?',
                     'A corrida é um esporte muito popular.'):
            for token in text.split():
                words.append({'id':f'w{len(words)}','start_ms':round(at*1000),
                    'end_ms':round((at+.22)*1000),'text':token})
                at+=.3
            at+=.4
        question_end=next(i for i,word in enumerate(words)
                          if word['text'].endswith('?'))
        start,end,_,expanded_end=_dialogue_context_bounds(
            words,0,question_end,5000.)
        self.assertEqual(start,0)
        self.assertEqual(end,question_end)
        self.assertFalse(expanded_end)

    def test_question_links_to_explicit_answer_without_lexical_overlap(self):
        words=[]
        at=0.
        for text in ('Por que a transmissão parou?',
                     'A resposta é que faltou energia.'):
            for token in text.split():
                words.append({'id':f'w{len(words)}','start_ms':round(at*1000),
                    'end_ms':round((at+.22)*1000),'text':token})
                at+=.3
            at+=.4
        question_end=next(i for i,word in enumerate(words)
                          if word['text'].endswith('?'))
        _start,end,_,expanded_end=_dialogue_context_bounds(
            words,0,question_end,5000.)
        self.assertEqual(end,len(words)-1)
        self.assertTrue(expanded_end)

    def test_parakeet_question_without_punctuation_splits_at_a_natural_pause(self):
        words=[]
        at=0.
        for turn_index,text in enumerate((
                'Você sabia que o editor guarda a transcrição',
                'O editor guarda a transcrição em arquivos locais.')):
            for token in text.split():
                words.append({'id':f'w{len(words)}','start_ms':round(at*1000),
                    'end_ms':round((at+.22)*1000),'text':token})
                at+=.3
            at+=.8 if turn_index==0 else 0.
        turns=_utterances(words)
        self.assertEqual(len(turns),2)
        start,end,_,expanded_end=_dialogue_context_bounds(
            words,0,len(turns[0]['words'])-1,6000.)
        self.assertEqual(start,0)
        self.assertEqual(end,len(words)-1)
        self.assertTrue(expanded_end)

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
            with patch('berofel.services.clipper.audio_features',
                       return_value=(None,False)) as audio:
                result=analyze_clips([clip],[],ClipperOptions(8.,16.,5,6.,
                    mode='Rápido'),cache_dir=Path(folder)/'cache')
        audio.assert_called_once()
        self.assertTrue(audio.call_args.kwargs['waveform_only'])
        self.assertEqual(result['clips'][0]['status'],'no_candidates')
        self.assertTrue(any('Sem transcrição' in warning
                            for warning in result['clips'][0]['warnings']))

    def test_audio_event_can_propose_review_clip_without_transcript_or_asr(self):
        with tempfile.TemporaryDirectory(prefix='bfs_clipper_event_only_') as folder:
            source=Path(folder)/'source.wav';source.write_bytes(b'placeholder')
            clip=Clip(str(source),0.,30.,kind='audio')
            times=np.arange(1500,dtype=np.float64)*20.
            rms=np.full(1500,-35.,dtype=np.float32)
            peak=rms.copy()
            # A sustained relative burst is an observable cue, not a semantic
            # claim about what happened in the recording.
            rms[500:750]=-15.;peak[500:750]=-12.
            frames=FrameFeatures(times,rms,peak,
                np.zeros(1500,dtype=np.float32),20.,16000)
            options=ClipperOptions(8.,18.,5,6.,mode='Equilibrado')
            with patch('berofel.services.clipper.audio_features',
                       return_value=(frames,False)), \
                 patch('berofel.services.parakeet_asr.transcribe_file') as parakeet:
                result=analyze_clips([clip],[],options,cache_dir=Path(folder)/'cache')
        parakeet.assert_not_called()
        self.assertTrue(result['candidates'])
        candidate=result['candidates'][0]
        self.assertFalse(candidate['transcript_available'])
        self.assertEqual(candidate['text'],'')
        self.assertEqual(candidate['audio_level_source'],'pcm_rms')
        self.assertTrue(any('Sem transcrição' in warning
                            for warning in candidate['warnings']))
        self.assertTrue(any('não identificam ação' in reason
                            for reason in candidate['reasons']))

    def test_saved_parakeet_transcript_is_ranked_without_invoking_any_asr(self):
        with tempfile.TemporaryDirectory(prefix='bfs_clipper_no_asr_') as folder:
            source=Path(folder)/'source.wav';source.write_bytes(b'fixture')
            clip=Clip(str(source),0.,36.,kind='audio')
            words=transcript(source,count=180,step=.2)
            options=ClipperOptions(8.,16.,5,6.,mode='Rápido')
            with patch('berofel.services.clipper.audio_features',return_value=(None,False)), \
                 patch('berofel.services.parakeet_asr.transcribe_file') as parakeet:
                first=analyze_clips([clip],words,options,cache_dir=Path(folder)/'cache')
                changed=ClipperOptions(8.,16.,5,6.,profile='Gameplay',mode='Rápido')
                second=analyze_clips([clip],words,changed,cache_dir=Path(folder)/'cache')
        parakeet.assert_not_called()
        self.assertTrue(first['candidates'])
        self.assertTrue(second['candidates'])
        self.assertEqual(first['stats']['decoded_seconds'],0.)
        self.assertEqual(second['stats']['decoded_seconds'],0.)

    def test_minimum_score_filters_cached_rank_without_reanalysis(self):
        with tempfile.TemporaryDirectory(prefix='bfs_clipper_min_score_') as folder:
            source=Path(folder)/'source.wav';source.write_bytes(b'fixture')
            clip=Clip(str(source),0.,36.,kind='audio')
            words=transcript(source,count=180,step=.2)
            cache=Path(folder)/'cache'
            with patch('berofel.services.clipper.audio_features',
                       return_value=(None,False)) as audio:
                ranked=analyze_clips([clip],words,
                    ClipperOptions(8.,16.,5,6.),cache_dir=cache)
                filtered=analyze_clips([clip],words,
                    ClipperOptions(8.,16.,5,6.,min_score=100.),cache_dir=cache)
        self.assertTrue(ranked['candidates'])
        self.assertGreater(ranked['stats']['candidate_count_before_min_score'],0)
        self.assertEqual(filtered['candidates'],[])
        self.assertEqual(filtered['clips'][0]['status'],'below_minimum_score')
        self.assertEqual(filtered['stats']['candidate_count'],0)
        self.assertEqual(filtered['stats']['candidate_count_before_min_score'],
                         ranked['stats']['candidate_count_before_min_score'])
        self.assertGreaterEqual(filtered['stats']['cache_hits'],1)
        audio.assert_called_once()

    def test_result_limit_and_deduplication_apply_to_entire_selected_scope(self):
        with tempfile.TemporaryDirectory(prefix='bfs_clipper_global_rank_') as folder:
            source=Path(folder)/'source.wav';source.write_bytes(b'fixture')
            first=Clip(str(source),0.,36.,kind='audio',title='Primeiro recorte')
            second=Clip(str(source),0.,36.,kind='audio',title='Recorte duplicado')
            words=transcript(source,count=180,step=.2)
            with patch('berofel.services.clipper.audio_features',return_value=(None,False)):
                result=analyze_clips([first,second],words,
                    ClipperOptions(8.,16.,1,6.,mode='Rápido'),
                    cache_dir=Path(folder)/'cache')
        self.assertEqual(len(result['clips']),2)
        self.assertTrue(all(item['candidates'] for item in result['clips']))
        self.assertEqual(len(result['candidates']),1)
        self.assertEqual(result['stats']['candidate_count'],1)

    def test_minimum_score_rejects_nonfinite_and_out_of_range_values(self):
        for value in (-.1,100.1,float('nan'),float('inf')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ClipperOptions(min_score=value)

    def test_visual_event_in_long_transcript_gap_becomes_review_candidate(self):
        with tempfile.TemporaryDirectory(prefix='bfs_clipper_transcript_gap_') as folder:
            source=Path(folder)/'gameplay.mp4';source.write_bytes(b'fixture')
            clip=Clip(str(source),0.,60.,kind='video')
            words=[
                {'id':'w1','source':str(source.resolve()),'source_start':1.,
                 'source_end':1.2,'text':'Começou.'},
                {'id':'w2','source':str(source.resolve()),'source_start':50.,
                 'source_end':50.2,'text':'Acabou.'},
            ]
            frames=FrameFeatures(np.empty(0,dtype=np.float64),
                np.empty(0,dtype=np.float32),np.empty(0,dtype=np.float32),
                np.empty(0,dtype=np.float32),20.,16000)
            visual_event={'kind':'cached_thumbnail_change','start_ms':25000,
                'end_ms':26000,'strength':.9,'source':'cached_thumbnail_proxy',
                'meaning':'visual change only'}
            audio_event={'kind':'relative_energy_surge','start_ms':25000,
                'end_ms':26000,'strength':.8,'rise_db':12.,
                'meaning':'energy change only'}
            options=ClipperOptions(10.,20.,5,6.,'Gameplay','Rápido',True)
            with patch('berofel.services.clipper.audio_features',
                       return_value=(frames,True)), \
                 patch('berofel.services.clipper.read_cached_visual_signals',
                       return_value=SimpleNamespace(frame_count=60,cache_hit=True)), \
                 patch('berofel.services.clipper.detect_cached_visual_events',
                       return_value=[visual_event]), \
                 patch('berofel.services.clipper.detect_energy_events',
                       side_effect=lambda _frames, speech, **_kwargs:
                           [] if speech is not None else [audio_event]), \
                 patch('berofel.services.clipper.score_cached_visual_interval',
                       return_value={'score':None,'coverage':0.,'frames':0,
                                     'reason':'fixture'}), \
                 patch('berofel.services.parakeet_asr.transcribe_file') as parakeet:
                result=analyze_clips([clip],words,options,
                    cache_dir=Path(folder)/'cache',visual_provider=object())
            parakeet.assert_not_called()

        candidates=[item for item in result['candidates']
                    if not item['transcript_available']]
        self.assertTrue(candidates)
        candidate=candidates[0]
        self.assertTrue(candidate['transcript_present'])
        self.assertGreaterEqual(candidate['start_ms'],1550)
        self.assertLessEqual(candidate['end_ms'],49650)
        self.assertIn('cached_thumbnail_change',
                      {event['kind'] for event in candidate['events']})
        self.assertIn('relative_energy_surge',
                      {event['kind'] for event in candidate['events']})
        self.assertTrue(any('não comprova ausência de fala' in warning
                            for warning in candidate['warnings']))
        self.assertEqual(result['stats']['transcript_gap_candidates'],
                         len(candidates))

    def test_event_trim_choices_stay_inside_the_transcript_gap(self):
        from berofel.services.clipper import _event_boundary_choices
        clip=Clip('fixture.mp4',0.,60.,kind='video')
        candidate={'start_ms':20000,'end_ms':35000,
                   'allowed_start_ms':1550,'allowed_end_ms':49650}
        starts,ends=_event_boundary_choices(clip,candidate,
            ClipperOptions(10.,20.,5,6.))
        self.assertTrue(starts and ends)
        self.assertTrue(all(candidate['allowed_start_ms']<=item['ms']<candidate['end_ms']
                            for item in starts))
        self.assertTrue(all(candidate['start_ms']<item['ms']<=candidate['allowed_end_ms']
                            for item in ends))

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

    def test_profile_change_reuses_acoustic_feature_cache_without_pcm_decode(self):
        import wave
        with tempfile.TemporaryDirectory(prefix='bfs_clipper_profile_cache_') as folder:
            source=Path(folder)/'talk.wav'
            rate=16000
            samples=(.04*np.sin(2*np.pi*180*np.arange(rate*4)/rate)).astype('<f4')
            pcm=np.clip(samples*32767,-32768,32767).astype('<i2')
            with wave.open(str(source),'wb') as audio:
                audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(rate)
                audio.writeframes(pcm.tobytes())
            clip=Clip(str(source),0.,4.,kind='audio')
            words=transcript(source,count=19,step=.2)
            cache=Path(folder)/'cache'
            with patch('berofel.services.clipper._audio_pcm_chunks',
                       wraps=__import__('berofel.services.clipper',fromlist=['_audio_pcm_chunks'])._audio_pcm_chunks) as decode:
                first=analyze_clips([clip],words,ClipperOptions(3.,4.,5,6.,'Geral'),
                                    cache_dir=cache)
                second=analyze_clips([clip],words,ClipperOptions(3.,4.,5,6.,'Gameplay'),
                                     cache_dir=cache)
                third=analyze_clips([clip],words,ClipperOptions(3.,4.,5,6.,'Gameplay',
                    score_weights={'hook':.5,'context':.15,'audio':.1,
                        'value':.1,'payoff':.1,'rhythm':.05,'visual':0.}),
                    cache_dir=cache)
        self.assertEqual(decode.call_count,1)
        self.assertTrue(first['candidates'])
        self.assertTrue(second['candidates'])
        self.assertTrue(third['candidates'])
        self.assertGreaterEqual(second['stats']['cache_hits'],1)
        self.assertGreaterEqual(third['stats']['cache_hits'],1)

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
        np.testing.assert_allclose(frames.spectral_flux,frames2.spectral_flux)
        np.testing.assert_allclose(frames.zero_crossing_rate,frames2.zero_crossing_rate)

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

    def test_result_cache_invalidates_when_timeline_waveform_arrives_later(self):
        class ChangingWaveform:
            peaks=None
            def get_wave(self,source,at,request=False):
                if self.peaks is None:return None
                return {'offset':0.,'step':.1,'peaks':self.peaks}
        with tempfile.TemporaryDirectory(prefix='bfs_clipper_waveform_refresh_') as folder:
            source=Path(folder)/'source.wav';source.write_bytes(b'fixture')
            clip=Clip(str(source),0.,36.,kind='audio')
            words=transcript(source,count=180,step=.2)
            provider=ChangingWaveform();cache=Path(folder)/'cache'
            options=ClipperOptions(8.,16.,5,6.,mode='Rápido')
            missing=analyze_clips([clip],words,options,cache_dir=cache,
                                  waveform_provider=provider)
            self.assertFalse(missing['clips'][0]['audio_available'])
            provider.peaks=[.08+.02*(index%7) for index in range(360)]
            refreshed=analyze_clips([clip],words,options,cache_dir=cache,
                                    waveform_provider=provider)
        self.assertTrue(refreshed['clips'][0]['audio_available'])
        self.assertEqual(refreshed['stats']['cache_misses'],1)
        self.assertGreaterEqual(refreshed['stats']['cache_hits'],1)

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

    def test_suggested_title_is_extractive_deterministic_and_length_bounded(self):
        sentence='O resultado mudou tudo e ninguém esperava essa revelação'
        transcript_text=('Hoje gravamos uma conversa sobre o editor. '+sentence+
                         '. Depois explicamos como o projeto funciona.')
        title=suggest_title(transcript_text)
        self.assertEqual(title,suggest_title(transcript_text))
        self.assertIn(title,sentence)
        self.assertLessEqual(len(suggest_title(transcript_text,24)),24)


if __name__=='__main__':
    unittest.main()

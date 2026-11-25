import unittest
from unittest.mock import patch
import numpy as np
from berofel.services.clip_audio_signals import (
    FrameFeatures, extract_frames_from_chunks,
    detect_energy_events, align_events_to_conversation, score_clip, select_diverse_clips,
)


class ClipAudioTests(unittest.TestCase):
    def test_frame_stream_equivalent_to_whole(self):
        rng = np.random.default_rng(44)
        pcm = (rng.normal(size=16000 * 3) * 0.06).astype(np.float32)
        a = extract_frames_from_chunks([pcm], 16000)
        b = extract_frames_from_chunks([pcm[:1001], pcm[1001:17481], pcm[17481:]], 16000)
        np.testing.assert_allclose(a.rms_dbfs, b.rms_dbfs)
        np.testing.assert_allclose(a.peak_dbfs, b.peak_dbfs)

    def test_surge_matches_speech_and_timing(self):
        rng = np.random.default_rng(2)
        pcm = (rng.normal(size=16000 * 15) * 0.015).astype(np.float32)
        pcm[16000 * 7:16000 * 8] *= 12
        pcm[16000 * 11:16000 * 12] *= 12  # loud background event outside speech
        frames = extract_frames_from_chunks([pcm], 16000)
        events = detect_energy_events(frames, [(0, 10500)], min_duration_ms=120)
        self.assertTrue(any(6950 <= e['start_ms'] <= 7100 for e in events), events)
        self.assertTrue(all(e['start_ms'] < 10500 for e in events))

    def test_quiet_good_content_not_penalized_if_audio_unavailable(self):
        c = dict(start_ms=0, end_ms=10000, context_score=.95, hook_score=.9,
                 boundary_score=.9)
        result = score_clip(c, [])
        self.assertGreater(result['score'], 85)
        self.assertIsNone(result['audio_score'])

    def test_discourse_signal_is_small_and_reported_in_editorial_ranking(self):
        base = dict(start_ms=0, end_ms=10000, context_score=.7,
                    hook_score=.6, boundary_score=.8, figurative_score=0.)
        plain = score_clip(base, [])
        enriched = score_clip(dict(base, discourse_score=.8), [])
        self.assertGreater(enriched['score'], plain['score'])
        self.assertLess(enriched['score'] - plain['score'], 6.)
        self.assertEqual(enriched['discourse_score'], .8)
        self.assertTrue(any('Sinais discursivos' in item for item in enriched['reasons']))

    def test_clipping_flag(self):
        frames = extract_frames_from_chunks([np.ones(16000, dtype=np.float32)], 16000)
        self.assertGreater(float(frames.clip_fraction.mean()), .99)
        c = dict(start_ms=0, end_ms=1000, context_score=.9, hook_score=.9,
                 boundary_score=.9)
        result = score_clip(c, [], frames)
        self.assertTrue(result['warnings'])

    def test_context_gate(self):
        c = dict(start_ms=0, end_ms=10000, context_score=.3,
                 hook_score=.95, boundary_score=.9)
        e = dict(start_ms=200, end_ms=600, speech_verified=True, strength=1.0)
        self.assertLessEqual(score_clip(c, [e])['score'], 59)

    def test_nonoverlap(self):
        ranked = [dict(start_ms=s, end_ms=e, score=p) for s,e,p in
                  [(0,10000,91),(1000,9000,88),(14000,25000,79)]]
        out = select_diverse_clips(ranked)
        self.assertEqual(len(out), 2)

    def test_nonoverlapping_repeated_transcript_does_not_fill_two_slots(self):
        ranked = [
            dict(start_ms=0, end_ms=10000, score=91,
                 text='O programa gera legendas automáticas, remove o silêncio e cria cortes contextuais para o vídeo.'),
            dict(start_ms=20000, end_ms=30000, score=84,
                 text='Esse programa gera legendas automáticas, remove o silêncio e cria cortes contextuais para o vídeo.'),
            dict(start_ms=40000, end_ms=50000, score=79,
                 text='A gravação mostra como configurar o microfone antes de iniciar a narração.'),
        ]
        out = select_diverse_clips(ranked, max_clips=3)
        self.assertEqual([item['score'] for item in out], [91, 79])

    def test_candidate_with_substantial_new_information_is_preserved(self):
        ranked = [
            dict(start_ms=0, end_ms=10000, score=91,
                 text='O programa gera legendas automáticas, remove o silêncio e cria cortes contextuais para o vídeo.'),
            dict(start_ms=20000, end_ms=35000, score=84,
                 text='O programa gera legendas automáticas, remove o silêncio e cria cortes contextuais para o vídeo, com revisão manual, ajuste de fonte, tamanho e cor.'),
        ]
        out = select_diverse_clips(ranked, max_clips=2)
        self.assertEqual(len(out), 2)

    def test_diversity_terms_are_extracted_once_per_candidate(self):
        from berofel.services import clip_audio_signals as signals
        ranked = [dict(start_ms=i*20000, end_ms=i*20000+10000, score=90-i,
                       text=f'Este trecho apresenta conteúdo diferente número índice {i} sobre edição tema {i}.')
                  for i in range(6)]
        with patch.object(signals, '_diversity_terms',
                           wraps=signals._diversity_terms) as terms:
            select_diverse_clips(ranked, max_clips=6)
        self.assertEqual(terms.call_count, len(ranked))

    def test_align_event_to_answer(self):
        e = [{"start_ms": 2400, "end_ms": 2700, "strength": .7,
              "speech_verified": True}]
        turns = [{"start_ms": 0, "end_ms": 1700, "role": "question"},
                 {"start_ms": 1800, "end_ms": 3300, "role": "answer", "speaker_id": "B"}]
        linked = align_events_to_conversation(e, turns)
        self.assertEqual(linked[0]["conversation_role"], "answer")
        self.assertEqual(linked[0]["speaker_id"], "B")

    def test_empty_audio(self):
        frames = extract_frames_from_chunks([], 16000)
        self.assertFalse(detect_energy_events(frames, None))


if __name__ == '__main__':
    unittest.main()

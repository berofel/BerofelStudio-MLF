"""Deterministic tests for the non-generative cleanup decision engine."""
from types import SimpleNamespace
import unittest

from berofel.services.automatic_cleanup import (
    EditOptions, analyze_automatic_cleanup, _context_candidates,
    _filler_candidates, _sentences, _tokens, _phrase_signature,
)


def clip(start=0., end=60.):
    return SimpleNamespace(id='clip-1', title='Fixture', start=start, end=end,
                           duration=end-start, kind='video')


def words(text, start, step=.35):
    output=[]
    for token in text.split():
        clean=token.strip()
        output.append({'text':clean,'source_start':start,'source_end':start+.22,
                       'probability':.99})
        start+=step
    return output


class AutomaticCleanupTests(unittest.TestCase):
    def setUp(self):
        self.clip=clip()

    def test_empty_selection_does_not_start_any_model(self):
        def forbidden(*args,**kwargs): raise AssertionError('análise não devia iniciar')
        plan=analyze_automatic_cleanup([self.clip],EditOptions(),analyze=forbidden)
        self.assertTrue(plan.stats['empty_selection'])

    def test_all_seven_combinations_call_only_required_existing_routes_once(self):
        for bits in range(1,8):
            opts=EditOptions(bool(bits&1),bool(bits&2),bool(bits&4))
            calls=[]
            def fake(clips,**kwargs):
                calls.append((kwargs['mode'],tuple(c.id for c in clips)))
                reports=[{'clip_id':c.id,'title':c.title,'source':'x','start':c.start,
                    'end':c.end,'speech':[{'start':1.,'end':3.},{'start':4.,'end':6.}],
                    'words':[],'suggestions':[{'clip_id':c.id,'a':3.,'b':4.,
                        'type':'silencio','note':'Silero'}] if kwargs['mode']=='silence' else []}
                    for c in clips]
                return {'reports':reports,'suggestions':[s for r in reports for s in r['suggestions']],
                        'cache_hits':0,'cache_misses':0,'stages':[]}
            plan=analyze_automatic_cleanup([self.clip],opts,analyze=fake)
            expected=[]
            if opts.remove_silences or opts.analyze_context: expected.append('silence')
            if opts.remove_fillers or opts.analyze_context: expected.append('transcribe')
            # Context and filler need transcription if no persisted words.
            self.assertEqual([call[0] for call in calls],expected)
            if opts.analyze_context and not opts.remove_silences:
                self.assertFalse(any(c.source_module=='silence' for c in plan.candidates))

    def test_context_rewrite_with_changed_grammar_is_candidate_only_at_vad_pause(self):
        first=words('Hoje nós iremos fazer tal e tal coisa.',1.)
        second=words('No vídeo de hoje nós faremos tal e tal coisa.',8.)
        report={'words':first+second}
        clip_item=clip()
        candidates,_=_context_candidates(clip_item,report,[(3.8,7.7)])
        self.assertEqual(len(candidates),1)
        self.assertLess(candidates[0].start,candidates[0].end)
        self.assertIn('posterior',candidates[0].reason)
        self.assertEqual(_context_candidates(clip_item,report,[])[0],[])

    def test_incomplete_start_then_complete_reformulation_is_detected(self):
        phrase=words('Eu vou mostrar como…',2.)+words('Eu vou mostrar como funciona o editor.',8.)
        candidates,_=_context_candidates(clip(),{'words':phrase},[(3.6,7.8)])
        self.assertEqual(len(candidates),1)

    def test_ellipsis_stays_attached_to_repair_unless_vad_marks_a_pause(self):
        transcript=words('O programa demora cinco minutos… não, na verdade, seis minutos.',1.)
        grouped=_sentences(transcript,0.,[])
        self.assertEqual(len(grouped),1)
        for index,item in enumerate(transcript[5:]):
            item['source_start']=4.+index*.35
            item['source_end']=item['source_start']+.22
        paused=_sentences(transcript,0.,[(2.7,3.9)])
        self.assertEqual(len(paused),2)

    def test_explicit_number_self_repair_can_replace_a_prior_complete_attempt(self):
        first=words('O programa demora cinco minutos para processar.',1.)
        second=words('Na verdade, o programa demora seis minutos para processar.',8.)
        candidates,protected=_context_candidates(clip(),{'words':first+second},[(3.5,7.8)])
        self.assertEqual(len(candidates),1,protected)
        self.assertIn('Autocorreção explícita',candidates[0].reason)
        self.assertTrue(any('marcador de correção' in evidence for evidence in candidates[0].evidence))

    def test_explicit_negation_repair_is_recognized_only_when_suffix_covers_topic(self):
        first=words('O programa não funciona no Windows.',1.)
        second=words('Na verdade, o programa funciona no Windows.',8.)
        candidates,_=_context_candidates(clip(),{'words':first+second},[(3.5,7.8)])
        self.assertEqual(len(candidates),1)
        unrelated=words('Na verdade, o filme funciona muito bem.',8.)
        candidates,_=_context_candidates(clip(),{'words':first+unrelated},[(3.5,7.8)])
        self.assertEqual(candidates,[])

    def test_controlled_action_equivalence_does_not_merge_distinct_actions(self):
        first=words('Vou ensinar vocês a editar vídeos no programa.',1.)
        second=words('Vou mostrar como editar vídeos no aplicativo.',8.)
        candidates,_=_context_candidates(clip(),{'words':first+second},[(4.5,7.8)])
        self.assertEqual(len(candidates),1)
        distinct=words('Vou configurar o editor para exportar o projeto.',8.)
        candidates,_=_context_candidates(clip(),{'words':first+distinct},[(4.5,7.8)])
        self.assertEqual(candidates,[])

    def test_small_word_gap_without_vad_or_sentence_boundary_does_not_split(self):
        first=words('Quando terminar de instalar o programa',1.)
        second=words('vai aparecer uma janela pedindo reinício.',4.)
        # The gap from the previous token is deliberately short and there is
        # no VAD pause; continuity must remain one phrase.
        second[0]['source_start']=first[-1]['source_end']+.4
        second[0]['source_end']=second[0]['source_start']+.22
        spans=_sentences(first+second,0.,[])
        self.assertEqual(len(spans),1)

    def test_spoken_and_unaccented_variants_normalize_for_matching_only(self):
        accented='Você não viu três legendas.'
        casual='Voce nao viu tres subtitulos.'
        left=_phrase_signature(accented)
        right=_phrase_signature(casual)
        self.assertTrue(left.negation and right.negation)
        self.assertEqual(left.concepts,right.concepts)
        self.assertIn('não',_tokens(casual))
        self.assertIn('não',accented.casefold())

    def test_negation_numbers_opposite_actions_and_continuations_are_protected(self):
        cases=[('Não pode fazer isso.','Pode fazer isso.'),
               ('Vou instalar cinco arquivos agora.','Vou instalar seis arquivos agora.'),
               ('Vou instalar o programa agora.','Vou desinstalar o programa agora.'),
               ('Hoje vamos preparar o projeto.','E depois vamos exportar o projeto.')]
        for first_text,second_text in cases:
            sequence=words(first_text,1.)+words(second_text,8.)
            candidates,_=_context_candidates(clip(),{'words':sequence},[(4.,7.8)])
            self.assertEqual(candidates,[],(first_text,second_text))

    def test_exact_complete_repetition_is_preserved_as_potentially_intentional(self):
        sentence='Repita esta instrução com bastante atenção.'
        sequence=words(sentence,1.)+words(sentence,8.)
        candidates,protected=_context_candidates(clip(),{'words':sequence},[(4.,7.8)])
        self.assertEqual(candidates,[])
        self.assertIn('repetição integral pode ser intencional',protected)

    def test_filler_detector_keeps_semantic_words_and_only_cuts_confirmed_repeat(self):
        clip_item=clip()
        data={'words':words('Eu eu eu vou mostrar, tipo de coisa, não é isso, né?',1.)}
        found=_filler_candidates(clip_item,data)
        self.assertTrue(any('Repetição adjacente' in c.reason for c in found))
        self.assertFalse(any(c.evidence[0].lower() in {'tipo','não','é','né'} for c in found))

    def test_partial_known_transcript_avoids_transcription_when_covered(self):
        item=clip(); known=[{'text':'Olá','source_start':1.,'source_end':1.3,'source':'x'}]
        calls=[]
        def fake(clips,**kwargs):
            calls.append(kwargs['mode'])
            return {'reports':[{'clip_id':c.id,'title':c.title,'source':'x','start':c.start,
                'end':c.end,'speech':[{'start':0.,'end':2.}],'words':known,
                'suggestions':[]} for c in clips], 'suggestions':[],'cache_hits':1,'cache_misses':0,'stages':[]}
        plan=analyze_automatic_cleanup([item],EditOptions(analyze_context=True),
                                      known_words={item.id:known},analyze=fake)
        self.assertEqual(calls,['silence'])
        self.assertEqual(plan.stats['transcription_calls'],0)

    def test_candidates_merge_overlaps_once_and_keep_original_clip_relative_bounds(self):
        item=clip(10,20)
        def fake(clips,**kwargs):
            return {'reports':[{'clip_id':item.id,'title':item.title,'source':'x','start':10.,'end':20.,
                'speech':[],'words':[],'suggestions':[{'clip_id':item.id,'a':2.,'b':4.,'note':'pause'}]}],
                'suggestions':[{'clip_id':item.id,'a':2.,'b':4.,'note':'pause'}],
                'cache_hits':0,'cache_misses':0,'stages':[]}
        plan=analyze_automatic_cleanup([item],EditOptions(remove_silences=True),analyze=fake)
        self.assertEqual((plan.candidates[0].start,plan.candidates[0].end),(2.,4.))
        self.assertGreaterEqual(plan.candidates[0].start,0)
        self.assertLess(plan.candidates[0].end,item.end-item.start)


if __name__=='__main__': unittest.main()

"""Deterministic tests for the non-generative cleanup decision engine."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from berofel.services.automatic_cleanup import (
    EditOptions, analyze_automatic_cleanup, _context_candidates,
    _filler_candidates, _sentences, _tokens, _phrase_signature, _merge_candidates,
    CutCandidate,
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
        self.assertTrue(candidates[0].requires_individual_review)
        self.assertIn('aprovação individual',candidates[0].reason)
        self.assertIn('marcador de correção explícita',candidates[0].risk_flags)
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

    def test_context_does_not_erase_repeated_emphasis_from_an_earlier_take(self):
        first=words('Esse recurso é muito, muito importante.',1.)
        second=words('Esse recurso é muito importante.',8.)
        candidates,protected=_context_candidates(
            clip(),{'words':first+second},[(4.,7.8)])
        self.assertEqual(candidates,[])
        self.assertIn('ênfase repetida preservada',protected)

    def test_written_number_forms_do_not_hide_quantity_changes(self):
        first=words('O editor processa cinquenta arquivos.',1.)
        second=words('O editor processa cento e cinquenta arquivos.',8.)
        candidates,_=_context_candidates(
            clip(),{'words':first+second},[(4.,7.8)])
        self.assertEqual(candidates,[])

    def test_long_complete_repetition_is_not_cut_via_a_shorter_suffix(self):
        sentence='Hoje nós vamos mostrar como configurar o programa e adicionar legendas automaticamente no vídeo.'
        sequence=words(sentence,1.)+words(sentence,8.)
        candidates,protected=_context_candidates(clip(),{'words':sequence},[(4.,7.8)])
        self.assertEqual(candidates,[])
        self.assertTrue(any('repetição integral' in reason for reason in protected))

    def test_filler_detector_keeps_semantic_words_and_only_cuts_confirmed_repeat(self):
        clip_item=clip()
        data={'words':words('Eu eu eu vou mostrar, tipo de coisa, não é isso, né?',1.)}
        found=_filler_candidates(clip_item,data)
        self.assertTrue(any('Repetição adjacente' in c.reason for c in found))
        self.assertFalse(any(c.evidence[0].lower() in {'tipo','não','é','né'} for c in found))

    def test_filler_detector_finds_restarted_phrase_without_cutting_emphasis(self):
        restarted=words('Eu vou, eu vou mostrar a timeline.',1.)
        found=_filler_candidates(clip(),{'words':restarted})
        phrase_cuts=[candidate for candidate in found if candidate.id.startswith('restart:')]
        self.assertEqual(len(phrase_cuts),1)
        self.assertEqual((phrase_cuts[0].start,phrase_cuts[0].end),(1.,1.57))

        emphasis=words('Muito muito importante para todos.',1.)
        found=_filler_candidates(clip(),{'words':emphasis})
        self.assertFalse(any(candidate.evidence[0].lower()=='muito'
                             for candidate in found))

        no_continuation=words('Eu vou, eu vou.',1.)
        found=_filler_candidates(clip(),{'words':no_continuation})
        self.assertFalse(any(candidate.id.startswith('restart:') for candidate in found))

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

    def test_silence_candidate_keeps_clip_relative_bounds(self):
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

    def test_context_finds_long_attempt_suffix_without_cutting_unique_prefix(self):
        first=words('O editor tem uma seção de configuração, hoje iremos fazer uma demonstração do programa.',1.)
        second=words('No vídeo de hoje faremos uma demonstração do programa.',13.)
        candidates,_=_context_candidates(clip(),{'words':first+second},[(5.5,12.7)])
        self.assertTrue(candidates)
        self.assertGreater(candidates[0].start,first[0]['source_start'])
        self.assertTrue(any('sufixo' in evidence for evidence in candidates[0].evidence))

    def test_no_pause_restart_is_detected_only_after_repeated_starter(self):
        sequence=words('Eu vou ensinar como instalar o editor, Eu vou mostrar como instalar o editor.',1.,step=.4)
        # Restart cue after a comma, with only a small word gap and no VAD pause.
        candidates,_=_context_candidates(clip(),{'words':sequence},[])
        self.assertTrue(candidates)

    def test_critical_conditions_modality_and_entities_are_preserved(self):
        cases=[('Se você puder abrir o projeto no Windows.','Você pode abrir o projeto no Linux.'),
               ('O editor deve exportar cinco arquivos no Windows.','O editor pode exportar seis arquivos no Windows.'),
               ('Hoje vamos abrir o projeto no Windows.','Amanhã vamos abrir o projeto no Windows.')]
        for left,right in cases:
            candidates,_=_context_candidates(clip(),{'words':words(left,1.)+words(right,9.)},[(4.,8.8)])
            self.assertEqual(candidates,[],(left,right))

    def test_speaker_change_blocks_context_candidate(self):
        left=words('Hoje nós iremos fazer uma demonstração completa.',1.)
        right=words('No vídeo de hoje faremos uma demonstração completa.',8.)
        for item in left:item['speaker_id']='speaker-1'
        for item in right:item['speaker_id']='speaker-2'
        candidates,protected=_context_candidates(clip(),{'words':left+right},[(3.5,7.8)])
        self.assertEqual(candidates,[])
        self.assertIn('locutor diferente',protected)

    def test_complement_and_continuation_are_not_context_cuts(self):
        cases=[('Hoje vamos preparar o projeto.','Também vamos exportar o projeto.'),
               ('Quando você terminar de instalar o editor','vai aparecer uma janela para reiniciar.')]
        for left,right in cases:
            words_all=words(left,1.)+words(right,8.)
            candidates,_=_context_candidates(clip(),{'words':words_all},[(4.,7.8)])
            self.assertEqual(candidates,[],(left,right))

    def test_additive_detail_inside_a_later_phrase_is_preserved(self):
        first=words('Hoje vamos editar o vídeo no Berofel Studio.',1.)
        second=words('Hoje também vamos editar as legendas no Berofel Studio.',8.)
        candidates,protected=_context_candidates(
            clip(),{'words':first+second},[(4.,7.8)])
        self.assertEqual(candidates,[])
        self.assertIn('continuidade ou complemento da fala',protected)

    def test_context_aliases_are_comparison_only_and_transcript_untouched(self):
        raw='Hoje iremos instalar o programa no computador.'
        transcript=words(raw,1.)
        before=[dict(item) for item in transcript]
        with patch('berofel.services.automatic_cleanup._analysis_alias',
                   side_effect=lambda token: {'instalarr':'instalar'}.get(token,token)):
            _phrase_signature('Hoje iremos instalarr o programa no computador.')
        self.assertEqual(transcript,before)
        self.assertEqual(' '.join(item['text'] for item in transcript),raw)

    def test_retake_commands_bridge_attempts_but_are_never_cut_content(self):
        original=words('Hoje iremos instalar o editor no Windows.',1.)
        command=words('Deixa eu refazer.',9.)
        final=words('Hoje nós vamos instalar o editor no Windows.',12.)
        candidates,protected=_context_candidates(
            clip(),{'words':original+command+final},[(3.,8.5),(11.,11.8)])
        self.assertTrue(candidates,protected)
        self.assertLess(candidates[0].start,command[0]['source_start'])
        self.assertGreater(candidates[0].end,original[0]['source_start'])
        self.assertIn('comando de regravação entre tentativas',candidates[0].evidence)
        # The command-only span itself is never proposed as a cut.
        self.assertFalse(candidates[0].start <= command[0]['source_start'] < candidates[0].end)

    def test_retake_bridge_extends_search_for_long_attempts_without_cutting_command(self):
        original=words('No vídeo de hoje vamos mostrar como instalar o editor.',1.)
        command=words('Vou falar de novo.',30.)
        final=words('Hoje nós vamos mostrar como instalar o editor.',44.)
        candidates,_=_context_candidates(
            clip(end=70.),{'words':original+command+final},[(5.,29.)])
        self.assertTrue(candidates)
        self.assertLess(candidates[0].end,command[0]['source_start'])

    def test_number_forms_normalize_but_different_quantities_remain_distinct(self):
        spelled=_phrase_signature('O editor processa cinquenta arquivos.')
        digits=_phrase_signature('O editor processa 50 arquivos.')
        changed=_phrase_signature('O editor processa 150 arquivos.')
        self.assertEqual(spelled.numbers,digits.numbers)
        self.assertNotEqual(digits.numbers,changed.numbers)

    def test_question_answer_and_different_subject_are_protected(self):
        cases=[('Você consegue abrir o projeto no Windows?',
                'Eu consigo abrir o projeto no Windows.')]
        for left,right in cases:
            result,protected=_context_candidates(
                clip(),{'words':words(left,1.)+words(right,9.)},[(4.,8.8)])
            self.assertFalse(result,(left,right))
            self.assertTrue(any('sujeito' in reason or 'pergunta/resposta' in reason
                                for reason in protected))

    def test_context_fails_safe_on_overlapping_word_timestamps(self):
        first=words('Hoje nós iremos fazer uma demonstração completa.',1.)
        second=words('No vídeo de hoje faremos uma demonstração completa.',9.)
        first[2]['source_start']=first[1]['source_start']
        candidates,protected=_context_candidates(
            clip(),{'words':first+second},[(4.,8.8)])
        self.assertFalse(candidates)
        self.assertIn('timestamps de palavras sobrepostos ou fora de ordem',protected)

    def test_context_alias_cannot_rewrite_into_critical_safety_token(self):
        class Dictionary:
            def lookup(self,word):return word not in {'condicaoo'}
            def suggest(self,word):return ['condição']
        with patch('berofel.services.transcript_proofing.load_pt_br_dictionary',
                   return_value=Dictionary()):
            from berofel.services.automatic_cleanup import _analysis_alias
            _analysis_alias.cache_clear()
            self.assertEqual(_analysis_alias('condicaoo'),'condicaoo')
            _analysis_alias.cache_clear()

    def test_overlapping_candidates_remain_separate_and_are_flagged(self):
        first=CutCandidate('clip-1',1.,2.,'Silêncio',(),90,'silence','s1')
        second=CutCandidate('clip-1',1.5,2.5,'Vício',(),80,'filler','f1')
        result,conflicts=_merge_candidates([first,second])
        self.assertEqual(len(result),2)
        self.assertEqual(conflicts,1)
        self.assertTrue(all('overlaps another module suggestion' in c.risk_flags for c in result))


if __name__=='__main__': unittest.main()

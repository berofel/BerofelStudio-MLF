import unittest

from berofel.services.discourse_features import (
    _polarity, analyze_discourse, analyze_irony, discourse_role,
    normalize_tokens, text_tiling_boundaries,
)


class DiscourseFeatureTests(unittest.TestCase):
    def test_possible_irony_uses_text_and_neighboring_context(self):
        result = analyze_irony(
            'Perfeito: o editor travou cinco vezes de novo.',
            previous='A instalação falhou três vezes e apagou meu projeto.')
        self.assertTrue(result['suspected'])
        self.assertGreaterEqual(result['score'], .55)
        self.assertIn('polaridade da fala contrasta com o contexto vizinho',
                      result['evidence'])
        self.assertIn('sinais heurísticos', result['note'])

    def test_explicit_irony_marker_is_detected_but_plain_positive_is_not(self):
        self.assertTrue(analyze_irony('Funcionou, só que não.')['suspected'])
        self.assertFalse(analyze_irony('O recurso ficou excelente.')['suspected'])

    def test_mentions_or_denials_of_irony_are_not_mistaken_for_ironic_intent(self):
        for text in ('Não foi sarcasmo, estou falando sério.',
                     'A ironia do texto é fácil de identificar.'):
            with self.subTest(text=text):
                self.assertFalse(analyze_irony(text)['suspected'])

    def test_explicit_self_description_as_irony_is_detected(self):
        self.assertTrue(analyze_irony('Isso foi uma ironia.')['suspected'])

    def test_positive_then_negative_without_punctuation_can_be_a_cue(self):
        result = analyze_irony('Perfeito o aplicativo travou outra vez')
        self.assertTrue(result['suspected'], result)
        self.assertIn('elogio antecede evento adverso, sem depender da pontuação',
                      result['evidence'])

    def test_polarity_respects_local_negation(self):
        # A negated failure is not treated as the same adverse context as a failure.
        result = analyze_irony('Perfeito, não travou dessa vez.')
        self.assertFalse(result['suspected'], result)
        # Do not carry a negation across an explicit adversative clause.
        self.assertEqual(_polarity(normalize_tokens(
            'Não falhou, mas ficou excelente.')), 1)

    def test_discourse_flags_reactions_humor_questions_and_repairs(self):
        self.assertGreater(analyze_discourse('Nossa, olha isso!')['reaction_score'], 0)
        self.assertTrue(analyze_discourse('Quem nunca passou por isso?')['rhetorical_question'])
        self.assertTrue(analyze_discourse('Foi uma brincadeira, kkk')['humor_marker'])
        self.assertTrue(analyze_discourse('Não, corrigindo: são seis.')['repair_marker'])

    def test_known_speaker_change_excludes_neighbor_context(self):
        text = 'O recurso está ótimo.'
        mismatched = analyze_discourse(text, previous='O programa travou e falhou.',
            speaker_id='a', previous_speaker='b')
        matched = analyze_discourse(text, previous='O programa travou e falhou.',
            speaker_id='a', previous_speaker='a')
        self.assertIn('anterior', mismatched['speaker_context_excluded'])
        self.assertNotIn('polaridade da fala contrasta com o contexto vizinho',
                         mismatched['irony']['evidence'])
        self.assertIn('polaridade da fala contrasta com o contexto vizinho',
                      matched['irony']['evidence'])

    def test_sincere_resolution_reduces_contextual_irony_signal(self):
        result = analyze_irony('Perfeito, finalmente funcionou!',
                               previous='O recurso falhou na primeira tentativa.')
        self.assertFalse(result['suspected'], result)
        self.assertTrue(any('marcador de' in item for item in result['evidence']))

    def test_role_cues_cover_question_answer_reveal_and_conclusion(self):
        cases = [('Como isso aconteceu?', 'question'),
                 ('Porque o arquivo estava corrompido.', 'answer'),
                 ('A resposta é que o cache já existia.', 'answer'),
                 ('A corrida foi no domingo.', 'unspecified'),
                 ('Descobri a causa do problema.', 'reveal'),
                 ('Concluindo, o projeto foi salvo.', 'conclusion')]
        for text, expected in cases:
            self.assertEqual(discourse_role(text), expected)

    def test_text_tiling_style_boundary_responds_to_topic_transition(self):
        turns = [
            {'text': 'O editor importa vídeos e organiza a biblioteca de mídia.'},
            {'text': 'A timeline mostra os cortes e as faixas de áudio.'},
            {'text': 'As legendas acompanham cada palavra da transcrição.'},
            {'text': 'Mudando de assunto, ontem choveu muito no bairro.'},
            {'text': 'A rua alagou e os ônibus atrasaram durante a tarde.'},
            {'text': 'Os moradores pediram uma solução para a drenagem.'},
        ]
        shifts = text_tiling_boundaries(turns, radius=2)
        self.assertIn(3, shifts)
        self.assertGreaterEqual(shifts[3], .52)
        self.assertGreater(shifts[3], shifts.get(1, 0.))

    def test_short_or_empty_turns_do_not_invent_boundaries(self):
        self.assertEqual(text_tiling_boundaries([{'text':'sim'}, {'text':'não'}]), {})


if __name__ == '__main__':
    unittest.main()

import unittest

from berofel.services.discourse_features import (
    analyze_irony, discourse_role, text_tiling_boundaries,
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

    def test_sincere_resolution_reduces_contextual_irony_signal(self):
        result = analyze_irony('Perfeito, finalmente funcionou!',
                               previous='O recurso falhou na primeira tentativa.')
        self.assertFalse(result['suspected'], result)
        self.assertTrue(any('marcador de' in item for item in result['evidence']))

    def test_role_cues_cover_question_answer_reveal_and_conclusion(self):
        cases = [('Como isso aconteceu?', 'question'),
                 ('Porque o arquivo estava corrompido.', 'answer'),
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

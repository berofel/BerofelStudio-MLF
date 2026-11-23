import unittest

from types import SimpleNamespace

from berofel.services.asr_vocabulary import (BASE_HOTWORDS, confirmed_caption_texts,
                                             project_hotwords)


def item(text,start,probability=.95,source='source-a'):
    return {'text':text,'source_start':start,'source_end':start+.2,
            'probability':probability,'source':source}


class ASRVocabularyTests(unittest.TestCase):
    def test_repeated_project_terms_and_adjacent_brand_name_are_hints(self):
        transcript=[
            item('Usamos',0.),item('Projeto',.22),item('Lima',.44),
            item('para',.66),item('editar',.88),item('vídeos.',1.1),
            item('marcador',3.,source='source-a'),
            item('marcador',3.22,source='source-b'),
            item('Projeto',4.,source='source-b'),item('Lima',4.22,source='source-b'),
            item('Projeto',40.,source='source-c'),item('Lima',40.22,source='source-c'),
        ]
        hints=project_hotwords(transcript)
        self.assertTrue(hints.startswith(', '.join(BASE_HOTWORDS)))
        self.assertIn('Projeto Lima',hints)
        self.assertIn('marcador',hints)

    def test_low_confidence_and_common_words_are_not_added(self):
        transcript=[item('software',0.,.3),item('para',.22,.99),
                    item('sistema',.44,.55)]
        hints=project_hotwords(transcript)
        self.assertEqual(hints,', '.join(BASE_HOTWORDS))

    def test_dynamic_vocabulary_respects_size_and_count_limits(self):
        transcript=[]
        for number in range(200):
            transcript.append(item(f'Produto{number}',number*2,.99,
                                   source=f'source-{number}'))
            transcript.append(item(f'produto{number}',number*2+1,.99,
                                   source=f'confirmation-{number}'))
        hints=project_hotwords(transcript,max_terms=4,max_dynamic_chars=40)
        dynamic=hints[len(', '.join(BASE_HOTWORDS)):]
        self.assertLessEqual(len(dynamic),42)
        self.assertLessEqual(len(dynamic.split(',')),5)

    def test_asr_mistakes_need_independent_recurrence(self):
        transcript=[item('Transcrição',0.),item('Inventada',.22),
                    item('Transcrição',1.),item('Inventada',1.22)]
        hints=project_hotwords(transcript)
        self.assertNotIn('Inventada',hints)

    def test_confirmed_caption_text_is_included_immediately(self):
        hints=project_hotwords([],confirmed_texts=('Usamos BerofelStudio localmente',))
        self.assertIn('BerofelStudio',hints)

    def test_only_manual_or_user_edited_captions_are_trusted(self):
        project=SimpleNamespace(clips=[
            SimpleNamespace(kind='text',text='Minha legenda',generated_by='manual_caption'),
            SimpleNamespace(kind='text',text='Texto corrigido',generated_by='auto_caption',
                             caption_generated_text='Texto reconhecido'),
            SimpleNamespace(kind='text',text='Texto original',generated_by='auto_caption',
                             caption_generated_text='Texto original'),
            SimpleNamespace(kind='video',text='Ignorar',generated_by='manual_caption'),
        ])
        self.assertEqual(confirmed_caption_texts(project),
                         ('Minha legenda','Texto corrigido'))

    def test_duplicate_base_entries_are_removed(self):
        self.assertEqual(project_hotwords([],base=('Berofel Studio','berofel studio')),
                         'Berofel Studio')


if __name__=='__main__':
    unittest.main()

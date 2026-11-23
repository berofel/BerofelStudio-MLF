import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from berofel.services.transcript_proofing import (SpellingSuggestion, apply_suggestion,
    find_pt_br_dictionary, load_pt_br_dictionary, project_approved_words,
    spelling_suggestions)


class FakeDictionary:
    def lookup(self, word):
        return word.casefold() in {'a', 'revisão', 'ortográfica', 'do', 'editor', 'correta'}

    def suggest(self, word):
        return {'transcricão': ['transcrição', 'transcrição'],
                'BerofelStudo': ['BerofelStudio']}.get(word.casefold(), [])


class TranscriptProofingTests(unittest.TestCase):
    def test_suggestions_preserve_original_offsets_and_remove_duplicates(self):
        text = 'A transcricão do editor.'
        suggestions = spelling_suggestions(text, dictionary=FakeDictionary())
        self.assertEqual(len(suggestions), 1)
        issue = suggestions[0]
        self.assertEqual(text[issue.start:issue.end], 'transcricão')
        self.assertEqual(issue.suggestions, ('transcrição',))

    def test_reviewed_suggestion_replaces_only_its_span(self):
        text = 'A transcricão do editor.'
        issue = spelling_suggestions(text, dictionary=FakeDictionary())[0]
        self.assertEqual(apply_suggestion(text, issue, 'transcrição'),
                         'A transcrição do editor.')

    def test_stale_or_unlisted_replacement_is_rejected(self):
        issue = SpellingSuggestion(2, 7, 'errdo', ('errado',))
        with self.assertRaises(ValueError):
            apply_suggestion('xx erro', issue, 'errado')
        with self.assertRaises(ValueError):
            apply_suggestion('xx errdo', issue, 'texto')

    def test_approved_terms_and_limits_avoid_unbounded_review(self):
        issues = spelling_suggestions('BerofelStudo x BerofelStudo',
            dictionary=FakeDictionary(), approved_words=('BerofelStudo',))
        self.assertEqual(issues, ())
        issues = spelling_suggestions('transcricão transcricão',
            dictionary=FakeDictionary(), max_issues=1)
        self.assertEqual(len(issues), 1)

    def test_project_terms_protect_technical_names_not_sentence_prose(self):
        project = SimpleNamespace(clips=[
            SimpleNamespace(kind='text', text='BerofelStudio usa Qwen3-TTS',
                generated_by='manual_caption', caption_generated_text=''),
            SimpleNamespace(kind='text', text='Faster-Whisper está correto',
                generated_by='auto_caption', caption_generated_text='transcrição original'),
            SimpleNamespace(kind='text', text='Legenda automática',
                generated_by='auto_caption', caption_generated_text='Legenda automática'),
        ])
        approved = project_approved_words(project)
        self.assertIn('berofelstudio', approved)
        self.assertIn('qwen3-tts', approved)
        self.assertIn('faster-whisper', approved)
        self.assertNotIn('legenda', approved)
        self.assertNotIn('correto', approved)

    def test_discovery_uses_explicit_local_hunspell_prefix(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder) / 'pt_BR'
            base.with_suffix('.aff').write_text('SET UTF-8', encoding='utf-8')
            base.with_suffix('.dic').write_text('1\npalavra', encoding='utf-8')
            with patch.dict(os.environ, {'BFS_HUNSPELL_PT_BR': str(base)}):
                self.assertEqual(find_pt_br_dictionary(), base)

    def test_discovery_finds_installer_versioned_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'BFS' / 'dictionaries'
            base = root / 'pt_BR-12345678' / 'pt_BR'
            base.parent.mkdir(parents=True)
            base.with_suffix('.aff').write_text('SET UTF-8', encoding='utf-8')
            base.with_suffix('.dic').write_text('1\npalavra', encoding='utf-8')
            with patch.dict(os.environ, {'LOCALAPPDATA': folder}, clear=False):
                with patch.dict(os.environ, {'BFS_HUNSPELL_PT_BR': ''}):
                    self.assertEqual(find_pt_br_dictionary(), base)

    def test_git_blob_checksum_matches_known_object(self):
        from scripts.instalar_corretor_pt_br import _git_blob_sha1
        self.assertEqual(_git_blob_sha1(b'abc'),
                         'f2ba8f84ab5c1bce84a7b441cb1959cfc7093b7f')

    def test_installed_vero_suggests_portuguese_spelling(self):
        dictionary = load_pt_br_dictionary()
        if dictionary is None:
            self.skipTest('VERO/Spylls locais não instalados')
        issues = spelling_suggestions('A transcricão do editor.', dictionary=dictionary)
        self.assertTrue(any('transcrição' in issue.suggestions for issue in issues))


try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from berofel.core.project import Clip, Project
    from berofel.ui.caption_panel import CaptionPanel
except ImportError:
    QApplication = None


@unittest.skipUnless(QApplication is not None, 'PySide6 não instalado')
class CaptionProofingUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        cls.app = QApplication.instance() or QApplication([])

    def test_caption_proofing_applies_only_after_user_selects_suggestion(self):
        panel = CaptionPanel()
        clip = Clip(source='', start=0, end=2, kind='text', text='A transcricão do editor.')
        project = Project(clips=[clip])
        panel.set_context(project, [clip.id])
        with patch('berofel.ui.caption_panel.load_pt_br_dictionary', return_value=FakeDictionary()):
            panel.proofread_button.click()
            for _ in range(500):
                self.app.processEvents()
                if panel.proofread_button.isEnabled():
                    break
                QTest.qWait(10)
            self.assertEqual(panel.text_edit.toPlainText(), 'A transcricão do editor.')
            self.assertGreater(panel.spelling_list.count(), 0)
            panel.spelling_list.setCurrentRow(0)
            panel.apply_spelling_button.click()
        self.assertEqual(panel.text_edit.toPlainText(), 'A transcrição do editor.')
        self.assertEqual(clip.text, 'A transcricão do editor.')


if __name__ == '__main__':
    unittest.main()

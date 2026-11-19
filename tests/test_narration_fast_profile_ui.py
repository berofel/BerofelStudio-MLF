"""Fast narration selects an already authorized local voice profile."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

try:
    from PySide6.QtWidgets import QApplication
    from berofel.services.voice_profiles import VoiceProfileManager
    from berofel.ui.narration_panel import NarrationPanel
except ImportError:
    QApplication=None


@unittest.skipUnless(QApplication is not None,'PySide6 indisponível neste ambiente')
class FastNarrationProfileUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_pre_authorized_profile_generates_without_reconfirming(self):
        with tempfile.TemporaryDirectory(prefix='bfs_fast_voice_ui_') as folder:
            root=Path(folder);store=root/'voices';sample=root/'reference.wav'
            sample.write_bytes(b'RIFF'+b'a'*300)
            with patch.dict(os.environ,{'BEROFEL_VOICE_PROFILE_DIR':str(store)}):
                profile=VoiceProfileManager().create('Voz de teste',sample,
                    'portuguese','texto exato da referência',authorized=True)
                panel=NarrationPanel()
                try:
                    index=panel.voice.findData(f'voice-profile:{profile["id"]}')
                    self.assertGreaterEqual(index,0)
                    panel.voice.setCurrentIndex(index)
                    panel.set_text('Uma frase nova para narrar rapidamente.')
                    self.assertTrue(panel.authorized.isChecked())
                    self.assertFalse(panel.authorized.isEnabled())
                    captured=[]
                    panel.on_generate=lambda request,insert:captured.append((request,insert))
                    panel._generate(True)
                    self.assertEqual(len(captured),1)
                    request,insert=captured[0]
                    self.assertTrue(insert)
                    self.assertTrue(request.consent)
                    self.assertEqual(request.engine,'qwen3-tts-local')
                    self.assertEqual(Path(request.voice).read_bytes(),sample.read_bytes())
                finally:
                    panel.close()


if __name__=='__main__':unittest.main()

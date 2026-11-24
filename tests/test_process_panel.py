"""Teste visual leve da área dedicada, sem modelos pesados."""
import os
import unittest

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QMessageBox, QPushButton
    from berofel.ui.process_panel import (ProcessPanel, explain_processing_error,
                                          make_processing_error_dialog)
except ImportError:
    QApplication = None


@unittest.skipUnless(QApplication is not None, 'PySide6 indisponível neste ambiente')
class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        cls.app = QApplication.instance() or QApplication([])

    def test_panel_occupies_layout_and_controls_job(self):
        from berofel.services.process_control import ProcessControl
        root = QWidget()
        layout = QVBoxLayout(root)
        panel = ProcessPanel(root)
        layout.addWidget(panel)
        root.resize(800,300)
        root.show()
        self.app.processEvents()
        self.assertGreater(panel.geometry().height(),0)
        self.assertLess(panel.geometry().height(),60)  # ocioso não ocupa a altura de um job
        control=ProcessControl()
        panel.begin('Faster-Whisper',control)
        self.app.processEvents()
        self.assertGreater(panel.geometry().height(),80)
        panel.set_stage('Transcrição • 3 trechos')
        panel.set_progress(1,3)
        self.assertEqual(panel.percent.text(),'33%')
        panel.set_progress(1.5,3)
        self.assertEqual(panel.percent.text(),'50%')
        panel.toggle_pause()
        self.assertTrue(control.paused)
        panel.toggle_pause()
        self.assertFalse(control.paused)
        panel.cancel()
        self.assertTrue(control.cancelled)
        panel.finish('cancelado')
        self.assertFalse(panel.cancel_btn.isEnabled())
        root.close()

    def test_compact_header_progress_centers_percent_and_keeps_stage_below(self):
        from PySide6.QtTest import QTest
        from berofel.services.process_control import ProcessControl
        root=QWidget();layout=QVBoxLayout(root)
        panel=ProcessPanel(root,compact=True);layout.addWidget(panel)
        root.resize(800,100);root.show();self.app.processEvents()
        control=ProcessControl();panel.begin('Qwen',control)
        panel.set_stage('Analisando lote 3 de 12')
        panel.set_progress(3,12);self.app.processEvents()
        elapsed_before=panel.compact_time.text()
        QTest.qWait(1100)
        self.app.processEvents()
        self.assertEqual(panel.bar.value(),25,'Progresso deve continuar estável no teste do cronômetro.')
        self.assertNotEqual(panel.compact_time.text(),elapsed_before,
                            'O cronômetro deve atualizar mesmo quando a porcentagem não muda.')
        self.assertEqual(panel.bar.format(),'%p%')
        self.assertEqual(panel.bar.text(),'25%')
        self.assertTrue(panel.percent.isHidden(),
                        'A porcentagem deve ficar dentro da barra, sem rótulo lateral.')
        self.assertEqual(panel.step_label.text(),'Analisando lote 3 de 12')
        self.assertIn('font-size:9px',panel.step_label.styleSheet())
        self.assertLessEqual(panel.height(),53)
        panel.finish('cancelado');root.close()

    def test_compact_completion_keeps_final_elapsed_visible(self):
        from berofel.services.process_control import ProcessControl
        root=QWidget();layout=QVBoxLayout(root)
        panel=ProcessPanel(root,compact=True);layout.addWidget(panel)
        root.show();self.app.processEvents()
        panel.begin('Tarefa concluída',ProcessControl())
        panel.finish('concluido')
        self.app.processEvents()
        self.assertTrue(panel.isVisible())
        self.assertTrue(panel.compact_time.isVisible())
        self.assertEqual(panel.compact_time.text(),panel.time_label.text().replace('Duração: ',''))
        root.close()

    def test_qwen_winerror_206_gets_actionable_ui_copy_and_keeps_detail(self):
        message='Etapa qwen falhou: FileNotFoundError: [WinError 206] O nome do arquivo é muito grande'
        title,body,help_text=explain_processing_error(message)
        self.assertEqual(title,'Não foi possível iniciar o Qwen')
        self.assertIn('WinError 206',body)
        self.assertIn('ABRIR_BEROFELSTUDIO.bat',help_text)
        self.assertIn('%LOCALAPPDATA%\\BFS\\tmp',help_text)
        # O chamador mantém `message` no painel e usa-o no bloco de detalhes do diálogo.
        self.assertIn('FileNotFoundError',message)

    def test_other_failures_keep_the_original_error_text(self):
        message='FFmpeg falhou ao exportar'
        title,body,help_text=explain_processing_error(message)
        self.assertEqual(title,'Falha no processamento')
        self.assertEqual(body,message)
        self.assertEqual(help_text,'')

    def test_missing_qwen_tts_model_gets_install_instructions(self):
        title,body,help_text=explain_processing_error(
            'O modelo Qwen3-TTS Base não está instalado.')
        self.assertIn('Qwen3-TTS Base',title)
        self.assertIn('não está pronto',body)
        self.assertIn('Preparar Qwen3 local',help_text)

    def test_qwen_timeout_gets_retry_and_cache_guidance(self):
        title,body,help_text=explain_processing_error(
            'Etapa qwen falhou: TimeoutExpired: command timed out after 3600 seconds')
        self.assertIn('Qwen',title)
        self.assertIn('cache',body)
        self.assertIn('intervalo menor',help_text)

    def test_qwen_error_dialog_is_non_modal_and_keeps_expandable_detail(self):
        message='Etapa qwen falhou: FileNotFoundError: [WinError 206] nome muito grande'
        dialog=make_processing_error_dialog(None,message)
        self.assertEqual(dialog.windowModality(),Qt.WindowModality.NonModal)
        self.assertIn('Não foi possível iniciar o Qwen',dialog.windowTitle())
        self.assertEqual(dialog.detailedText(),message)
        self.assertEqual(dialog.button(QMessageBox.StandardButton.Ok).text(),'Entendi')
        details=next((button for button in dialog.findChildren(QPushButton)
                      if button is not dialog.button(QMessageBox.StandardButton.Ok)),None)
        self.assertIsNotNone(details)
        self.assertEqual(details.text(),'Mostrar detalhes')
        self.assertGreaterEqual(details.minimumWidth(),details.sizeHint().width())
        dialog.close()


if __name__ == '__main__':
    unittest.main()

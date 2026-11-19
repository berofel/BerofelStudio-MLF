"""Contrato de eventos da barra de transporte do monitor."""
import os
import unittest

try:
    from PySide6.QtWidgets import QApplication
    from berofel.ui.preview_transport import PreviewTransport
except ImportError:
    QApplication=None


@unittest.skipUnless(QApplication is not None,'PySide6 não instalado neste ambiente')
class PreviewTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        cls.app=QApplication.instance() or QApplication([])

    def test_controls_emit_navigation_frame_steps_quality_and_volume(self):
        bar=PreviewTransport();seeks=[];plays=[];volumes=[];qualities=[];steps=[]
        bar.seek_requested.connect(seeks.append)
        bar.play_requested.connect(lambda:plays.append(True))
        bar.volume_changed.connect(volumes.append)
        bar.quality_changed.connect(qualities.append)
        bar.frame_step_requested.connect(steps.append)
        bar.begin_button.click();bar.back_button.click();bar.play_button.click()
        bar.previous_frame_button.click();bar.next_frame_button.click()
        bar.forward_button.click();bar.end_button.click()
        bar.volume.setValue(40);bar.quality.setCurrentIndex(2)
        self.assertEqual(seeks,[0.,-5.,5.,float('inf')])
        self.assertEqual(steps,[-1,1])
        self.assertEqual(plays,[True])
        self.assertAlmostEqual(volumes[-1],.4)
        self.assertEqual(qualities[-1],(1280,30))
        bar.set_time(73.5,600.)
        self.assertEqual(bar.time_label.text(),'01:13:15 / 10:00:00')
        self.assertIn('00:01:13:15 / 00:10:00:00',bar.time_label.toolTip())
        bar.set_time(.5,600.,24)
        self.assertEqual(bar.time_label.text(),'00:00:12 / 10:00:00')
        self.assertIn('24 fps',bar.time_label.toolTip())
        bar.set_preparing();self.assertEqual(bar.play_button.text(),'…')
        bar.set_playing(True);self.assertEqual(bar.play_button.text(),'Ⅱ')
        bar.close()


if __name__=='__main__':unittest.main()

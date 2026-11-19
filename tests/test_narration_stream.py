import unittest

import numpy as np
from PySide6.QtCore import QCoreApplication
from PySide6.QtMultimedia import QAudio

from berofel.ui.narration_stream import NarrationStreamPlayer, float32_mono_to_pcm16


class _FakeDevice:
    def __init__(self): self.data=bytearray()
    def write(self,data): self.data.extend(data);return len(data)


class _FakeSink:
    def __init__(self):self.output=_FakeDevice()
    def bytesFree(self):return 1_000_000
    def state(self):return QAudio.State.ActiveState
    def stop(self):pass
    def deleteLater(self):pass


class NarrationStreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QCoreApplication.instance() or QCoreApplication([])

    def test_stream_pcm_conversion_clips_and_keeps_duration_sample_count(self):
        source=np.array([-2.0,-1.0,0.0,.5,1.0,2.0,np.nan],dtype='<f4').tobytes()
        result=np.frombuffer(float32_mono_to_pcm16(source),dtype='<i2')
        self.assertEqual(result.size,7)
        self.assertEqual(result[0],-32767)
        self.assertEqual(result[2],0)
        self.assertEqual(result[3],16383)
        self.assertEqual(result[4],32767)
        self.assertEqual(result[5],32767)
        self.assertEqual(result[6],0)

    def test_player_pushes_stream_pcm_to_output_device(self):
        player=NarrationStreamPlayer(on_status=lambda _message:None)
        sink=_FakeSink()
        def start_fake():
            player._sink=sink;player._device=sink.output;player._timer.start();return True
        player._start=start_fake
        player.begin()
        source=np.array([-.5,0,.5],dtype='<f4').tobytes()
        player.push(source)
        self.assertEqual(bytes(sink.output.data),float32_mono_to_pcm16(source))
        self.assertIsNotNone(player.first_chunk_latency_seconds)
        player.stop()


if __name__=='__main__':unittest.main()

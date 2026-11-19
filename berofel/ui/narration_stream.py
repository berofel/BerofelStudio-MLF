"""Low-latency PCM sink for optional native Qwen streaming previews."""
from __future__ import annotations

import numpy as np
import time

from PySide6.QtCore import QObject, QTimer
from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices


def float32_mono_to_pcm16(data: bytes) -> bytes:
    """Convert native 24 kHz float PCM to clipped signed 16-bit PCM."""
    samples=np.frombuffer(data,dtype='<f4')
    if not samples.size:return b''
    clean=np.nan_to_num(samples,nan=0.0,posinf=1.0,neginf=-1.0)
    return (np.clip(clean,-1.0,1.0)*32767.0).astype('<i2').tobytes()


class NarrationStreamPlayer(QObject):
    """Queue generated PCM to Qt's audio device; only call methods on GUI thread."""
    def __init__(self,parent=None,on_status=None):
        super().__init__(parent)
        self._status=on_status or (lambda _message:None)
        self._sink=None;self._device=None;self._pending=bytearray()
        self._complete=False;self._failed=False
        self.first_chunk_latency_seconds=None;self._started_at=None
        self._timer=QTimer(self);self._timer.setInterval(10)
        self._timer.timeout.connect(self._drain)

    def begin(self):
        self.stop()
        self._complete=False;self._failed=False
        self.first_chunk_latency_seconds=None;self._started_at=time.perf_counter()

    def push(self,data:bytes):
        if self._complete or self._failed:return
        pcm=float32_mono_to_pcm16(data)
        if not pcm:return
        if self.first_chunk_latency_seconds is None and self._started_at is not None:
            self.first_chunk_latency_seconds=time.perf_counter()-self._started_at
        if self._sink is None and not self._start():return
        self._pending.extend(pcm)
        # A delayed device must not build an unbounded queue or stall inference.
        if len(self._pending)>24_000*2*3:
            self._failed=True;self.stop()
            self._status('Prévia incremental interrompida: a saída de áudio não acompanhou a geração. O WAV será preservado.')
            return
        self._drain()

    def _start(self)->bool:
        device=QMediaDevices.defaultAudioOutput()
        fmt=QAudioFormat();fmt.setSampleRate(24000);fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if device.isNull() or not device.isFormatSupported(fmt):
            self._failed=True
            self._status('Saída de áudio não suporta 24 kHz mono; a narração continuará e o WAV ficará disponível após gerar.')
            return False
        sink=QAudioSink(device,fmt,self);sink.setVolume(.85);sink.setBufferSize(24_000*2)
        output=sink.start()
        if output is None or sink.isNull():
            sink.stop();sink.deleteLater();self._failed=True
            self._status('Não foi possível iniciar a prévia incremental. O WAV será preservado.')
            return False
        self._sink=sink;self._device=output;self._timer.start()
        self._status('Qwen Turbo · reproduzindo áudio conforme os blocos ficam prontos.')
        return True

    def _drain(self):
        if self._sink is None or self._device is None:return
        if self._pending:
            if self._sink.state()==QAudio.State.IdleState:
                self._device=self._sink.start()
                if self._device is None:return
            free=max(0,int(self._sink.bytesFree()))
            count=min(free,len(self._pending));count-=count%2
            if count:
                written=self._device.write(bytes(self._pending[:count]))
                if written>0:del self._pending[:written]
        elif self._complete and self._sink.state()==QAudio.State.IdleState:
            self.stop()

    def finish(self):
        self._complete=True
        if self._sink is None:self._timer.stop()
        elif not self._pending:
            QTimer.singleShot(1500,self._finish_if_drained)

    def _finish_if_drained(self):
        if self._complete and not self._pending:self.stop()

    def stop(self):
        self._timer.stop();self._pending.clear()
        if self._sink is not None:
            self._sink.stop();self._sink.deleteLater()
        self._sink=None;self._device=None

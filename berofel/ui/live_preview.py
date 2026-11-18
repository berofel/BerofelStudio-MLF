"""Prévia multitrilha por FFmpeg em pipes + Qt (Windows/Linux).

Os dois decoders recebem exatamente o mesmo projeto recortado. O Qt apresenta
quadros em tempo de áudio (quando há dispositivo) ou relógio monotônico.
Nenhum arquivo MP4 temporário precisa ser gerado antes de apertar Play.

Cuidados: leituras em threads de IO; GUI e QAudioSink só no thread Qt; fila
limitada; fechamento/seek mata os subprocessos; dados obsoletos descartados.
"""
from __future__ import annotations

import queue
import subprocess
import tempfile
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices

from berofel.services.preview_pipeline import PreviewCommands, start_ffmpeg
from berofel.services.voice_preview_controller import AsyncVoicePreviewController

PREVIEW_AUDIO_QUEUE_CHUNKS=3  # 256 ms max backlog at 48 kHz stereo/4096 frames


class _PipeReader(threading.Thread):
    """Thread do pipe: nunca chama widgets Qt nem mantém quadros ilimitados."""
    def __init__(self, command: list[str], chunk_bytes: int, capacity: int):
        super().__init__(daemon=True)
        self.command = command
        self.chunk_bytes = chunk_bytes
        self.output = queue.Queue(maxsize=capacity)
        self.ended = threading.Event()
        self.stopping = threading.Event()
        self.message = ''
        self.process: subprocess.Popen | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stderr_tail = bytearray()
        self._stderr_lock = threading.Lock()

    def _drain_stderr(self, stream):
        """Drena erros durante a decodificação para o pipe nunca bloquear FFmpeg."""
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    return
                with self._stderr_lock:
                    self._stderr_tail.extend(chunk)
                    if len(self._stderr_tail) > 16_384:
                        del self._stderr_tail[:-16_384]
        except (OSError, ValueError):
            # stop() pode fechar o processo enquanto a thread está lendo.
            return

    def stop(self):
        self.stopping.set()
        if self.process is not None and self.process.poll() is None:
            try: self.process.kill()
            except OSError: pass

    def run(self):
        try:
            if self.stopping.is_set(): return
            self.process = start_ffmpeg(self.command)
            proc = self.process
            if proc.stderr is not None:
                self._stderr_thread = threading.Thread(
                    target=self._drain_stderr, args=(proc.stderr,), daemon=True,
                )
                self._stderr_thread.start()
            if self.stopping.is_set():
                self.stop(); return
            assert proc.stdout is not None
            while not self.stopping.is_set():
                # BufferedReader.read(n) bloqueia até receber n bytes ou EOF.
                data = bytearray()
                while len(data) < self.chunk_bytes and not self.stopping.is_set():
                    part = proc.stdout.read(self.chunk_bytes - len(data))
                    if not part: break
                    data.extend(part)
                if len(data) < self.chunk_bytes:
                    # O último lote de áudio pode ser menor que chunk_bytes.
                    if data:
                        while not self.stopping.is_set():
                            try:
                                self.output.put(bytes(data), timeout=.1); break
                            except queue.Full: pass
                    break
                while not self.stopping.is_set():
                    try:
                        self.output.put(bytes(data), timeout=.1)
                        break
                    except queue.Full: pass
            if not self.stopping.is_set():
                returncode = proc.wait(timeout=5)
                if returncode:
                    if self._stderr_thread is not None:
                        self._stderr_thread.join(timeout=1)
                    with self._stderr_lock:
                        err = bytes(self._stderr_tail)
                    self.message = err.decode('utf-8', errors='replace')[-1000:] or f'FFmpeg retornou {returncode}'
        except Exception as exc:
            if not self.stopping.is_set():
                self.message = f'{type(exc).__name__}: {exc}'
        finally:
            if self.process is not None:
                if self.process.poll() is None:
                    try: self.process.kill()
                    except OSError: pass
                try: self.process.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired): pass
                for stream in (self.process.stdout, self.process.stderr):
                    if stream is not None:
                        try: stream.close()
                        except (OSError, ValueError): pass
                if self._stderr_thread is not None and self._stderr_thread is not threading.current_thread():
                    self._stderr_thread.join(timeout=1)
            self.ended.set()


class LivePreview(QObject):
    """Motor: play/pause/stop/seek com composição simultânea de todas as camadas.

    Sinais são consumidos somente na GUI. O engine não altera a timeline.
    """
    frame_ready = Signal(QImage)
    position_changed = Signal(float)
    playing_changed = Signal(bool)
    status_changed = Signal(str)
    failed = Signal(str)
    voice_control_failed = Signal(str)
    reached_end = Signal()
    next_requested = Signal(float)  # inicio absoluto da próxima janela

    def __init__(self, parent=None):
        super().__init__(parent)
        self.timer = QTimer(self)
        self.timer.setInterval(15)
        self.timer.timeout.connect(self._tick)
        self.active = False
        self.paused = False
        self._ready = False
        self._video: _PipeReader | None = None
        self._audio: _PipeReader | None = None
        self._tmp: tempfile.TemporaryDirectory | None = None
        self._commands: PreviewCommands | None = None
        self._device = None
        self._sink: QAudioSink | None = None
        self._audio_out = None
        self._audio_pending = bytearray()
        self._next_frame: bytes | None = None
        self._last_frame: bytes | None = None
        self._last_frame_idx = -1
        self._next_frame_idx = 0
        self._displayed_idx = -1
        self._time0 = 0.0
        self._paused_since = 0.0
        self._paused_total = 0.0
        self._started_waiting = 0.0
        self._last_progress = 0.0
        self._volume = .85
        self._project_end = 0.0
        self._next_requested = False
        self._prefetch = None
        self._waiting_next = False
        self._waiting_since = 0.0
        self._audio_clock_offset = 0.0
        self._voice_control: AsyncVoicePreviewController | None = None

    def set_volume(self, value: float):
        self._volume = max(0.0, min(1.0, value))
        if self._sink is not None:
            self._sink.setVolume(self._volume)

    def start(self, commands: PreviewCommands, tmp: tempfile.TemporaryDirectory,
              project_end: float | None = None):
        self.stop()
        self._commands = commands
        self._activate_voice_control(commands)
        self._tmp = tmp
        self._project_end = float(project_end if project_end is not None
                                  else commands.source_time + commands.duration)
        self._next_requested = False
        self._waiting_next = False
        self._audio_clock_offset = 0.0
        self._video = _PipeReader(commands.video, commands.width * commands.height * 4, 5)
        # Audio: each chunk is ~85ms; keep the live-control backlog bounded.
        self._audio = _PipeReader(commands.audio, 4096*4, PREVIEW_AUDIO_QUEUE_CHUNKS)
        self._audio_pending.clear()
        self._next_frame = None
        self._last_frame = None
        self._last_frame_idx = -1
        self._next_frame_idx = 0
        self._displayed_idx = -1
        self._last_progress = 0.0
        self._paused_total = 0.0
        self._ready = False
        self.active = True
        self.paused = False
        self._started_waiting = time.monotonic()
        self._video.start()
        self._audio.start()
        self.timer.start()
        self.playing_changed.emit(True)
        self.status_changed.emit(f'Carregando composição de {commands.width}×{commands.height}...')

    def pause(self):
        if not self.active or self.paused: return
        self.paused = True
        self._paused_since = time.monotonic()
        if self._sink is not None:
            self._sink.suspend()
        self.playing_changed.emit(False)
        self.status_changed.emit('Prévia pausada. A timeline mantém a posição.')

    def resume(self):
        if not self.active or not self.paused: return
        self._paused_total += time.monotonic()-self._paused_since
        self.paused = False
        if self._sink is not None and not self._waiting_next:
            self._sink.resume()
        self.playing_changed.emit(True)

    def _activate_voice_control(self,commands):
        if self._voice_control is not None:
            self._voice_control.close();self._voice_control=None
        if commands.voice_control_address and commands.voice_eq_targets:
            try:
                self._voice_control=AsyncVoicePreviewController(
                    commands.voice_control_address,commands.voice_eq_targets,
                    commands.voice_eq_initial,
                    on_error=self.voice_control_failed.emit)
            except Exception:
                self._voice_control=None

    def update_voice_eq(self,clip_id,values,bypass=False):
        if self._voice_control is None:return False
        return self._voice_control.set_eq(clip_id,values,bypass)

    def discard_prefetch(self):
        """Cancel a preloaded old graph after changing live DSP parameters."""
        if self._prefetch is not None:
            _cmd,tmp,video,audio=self._prefetch
            self._prefetch=None
            self._cleanup_workers([video,audio],[tmp])
        self._next_requested=False
        if self._waiting_next:
            self._waiting_next=False
            if self._sink is not None and not self.paused:self._sink.resume()

    def stop(self, wait_for_cleanup: bool = False):
        self.timer.stop()
        was_active = self.active
        self.active = False
        self.paused = False
        self._ready = False
        old_workers = [w for w in (self._video,self._audio) if w is not None]
        cleanup_workers=list(old_workers)
        tempdirs=[]
        if self._prefetch:
            _cmd, pre_tmp, pre_video, pre_audio = self._prefetch
            cleanup_workers.extend([pre_video,pre_audio])
            tempdirs.append(pre_tmp)
            self._prefetch = None
        for worker in old_workers: worker.stop()
        self._video = None
        self._audio = None
        if self._sink is not None:
            self._sink.stop()
            self._sink.deleteLater()
        self._sink = None
        self._audio_out = None
        self._audio_pending.clear()
        self._commands = None
        if self._voice_control is not None:
            self._voice_control.close();self._voice_control=None
        self._next_requested = False
        self._waiting_next = False
        # Em Windows, espere os pipes liberarem filtros e PNGs antes de apagar.
        # Na reprodução e no seek, a limpeza é assíncrona; no fechamento pode
        # ser aguardada para não deixar pastas temporárias órfãs.
        old_tmp, self._tmp = self._tmp, None
        if old_tmp is not None:tempdirs.append(old_tmp)
        if cleanup_workers or tempdirs:
            self._cleanup_workers(cleanup_workers,tempdirs,wait=wait_for_cleanup)
        if was_active: self.playing_changed.emit(False)

    @staticmethod
    def _cleanup_workers(workers, tempdirs, wait=False):
        for worker in workers:
            worker.stop()
        def finish():
            deadline=time.monotonic()+5
            for worker in workers:
                if worker.ident is not None:
                    worker.join(timeout=max(0,deadline-time.monotonic()))
            for tempdir in tempdirs:
                if tempdir is not None:
                    try: tempdir.cleanup()
                    except OSError: pass
        if wait:finish()
        else:threading.Thread(target=finish, daemon=True).start()

    def prefetch(self, commands: PreviewCommands, tmp: tempfile.TemporaryDirectory):
        """Decodifica previamente a próxima janela, sem interromper a atual."""
        if not self.active or self._commands is None or self._prefetch is not None:
            tmp.cleanup()
            return
        expected = self._commands.source_time + self._commands.duration
        if abs(commands.source_time - expected) > .02:
            tmp.cleanup()
            return
        nxt_video = _PipeReader(commands.video, commands.width*commands.height*4, 5)
        nxt_audio = _PipeReader(commands.audio, 4096*4, PREVIEW_AUDIO_QUEUE_CHUNKS)
        self._prefetch = (commands, tmp, nxt_video, nxt_audio)
        nxt_video.start()
        nxt_audio.start()

    def _switch_to_prefetched(self):
        if self._prefetch is None:
            return False
        cmd, tmp, video, audio = self._prefetch
        if video.output.empty() or (audio.output.empty() and not audio.ended.is_set()):
            return False
        old_video, old_audio, old_tmp = self._video, self._audio, self._tmp
        self._video, self._audio, self._tmp, self._commands = video, audio, tmp, cmd
        self._activate_voice_control(cmd)
        self._prefetch = None
        self._cleanup_workers([w for w in (old_video,old_audio) if w], [old_tmp])
        self._next_frame = self._last_frame = None
        self._next_frame_idx = 0
        self._displayed_idx = self._last_frame_idx = -1
        self._last_progress = 0.0
        self._audio_pending.clear()
        self._next_requested = False
        self._ready = True
        self._time0 = time.monotonic()
        self._paused_total = 0.0
        self._audio_clock_offset = (self._sink.processedUSecs()/1_000_000
                                    if self._sink is not None else 0.0)
        if self._waiting_next and self._sink is not None:
            self._sink.resume()
        self._waiting_next = False
        self.status_changed.emit('Prévia contínua · avançando pelos cortes sem renderizar MP4.')
        return True

    def _start_clock(self):
        try:
            device = QMediaDevices.defaultAudioOutput()
            fmt = QAudioFormat()
            fmt.setSampleRate(48000)
            fmt.setChannelCount(2)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            if not device.isNull() and device.isFormatSupported(fmt):
                self._sink = QAudioSink(device, fmt, self)
                self._sink.setBufferSize(48000 * 4 // 5) # ~200 ms
                self._sink.setVolume(self._volume)
                self._audio_out = self._sink.start()
                if self._audio_out is None or self._sink.isNull():
                    self._sink.stop(); self._sink.deleteLater()
                    self._sink = None
        except Exception as exc:
            self._sink = None
            self.status_changed.emit(f'Sem saída de áudio compatível: {exc}. Mostrando vídeo.')
        audio_available = self._sink is not None
        self._ready = True
        self._time0 = time.monotonic()
        self._paused_total = 0.0
        self._audio_clock_offset = (self._sink.processedUSecs()/1_000_000
                                    if self._sink is not None else 0.0)
        self.status_changed.emit('Reproduzindo composição multitrilha (FFmpeg ao vivo)'
                                 + ('.' if audio_available else ' — sem saída de som disponível.'))

    def _clock(self) -> float:
        if self._sink is not None:
            # Relógio de som é o mestre. Nunca salte entre dois relógios.
            return max(0.0,self._sink.processedUSecs()/1_000_000 - self._audio_clock_offset)
        now = self._paused_since if self.paused else time.monotonic()
        return max(0.0, now - self._time0 - self._paused_total)

    def _fill_audio(self):
        if self._sink is None or self._audio_out is None or self._audio is None:
            return
        for _ in range(30):
            free = int(self._sink.bytesFree())
            if free < 4: return
            if not self._audio_pending:
                try: self._audio_pending.extend(self._audio.output.get_nowait())
                except queue.Empty: return
            count = min(free - free % 4, len(self._audio_pending))
            if count < 4: return
            written = self._audio_out.write(bytes(self._audio_pending[:count]))
            if written is None or written <= 0: return
            del self._audio_pending[:written]

    def _tick(self):
        if not self.active or self._commands is None or self._video is None: return
        for worker in (self._video,self._audio):
            if worker is not None and worker.message:
                self.failed.emit(worker.message)
                self.stop()
                return
        if not self._ready:
            # Aguarda pelo menos 1 quadro e 1 pacote de áudio antes de ligar o relógio.
            if (self._video.output.qsize() > 0 and self._audio is not None
                    and (self._audio.output.qsize() > 0 or self._audio.ended.is_set())):
                self._start_clock()
            elif time.monotonic() - self._started_waiting > 18.0:
                self.failed.emit('Tempo esgotado preparando prévia. Verifique vídeo/codec e FFmpeg.')
                self.stop()
            return
        if self.paused: return
        if self._prefetch:
            for worker in self._prefetch[2:]:
                if worker.message:
                    self.failed.emit('Falha no próximo trecho da prévia: '+worker.message)
                    self.stop()
                    return
        if self._waiting_next:
            if self._switch_to_prefetched():
                return
            if time.monotonic() - self._waiting_since > 18.0:
                self.failed.emit('Tempo esgotado preparando o próximo trecho da prévia. '
                                 'Os cortes permanecem salvos; tente a prévia leve.')
                self.stop()
            # Mantém o último quadro enquanto a próxima janela é decodificada.
            return
        self._fill_audio()
        elapsed = min(self._commands.duration, self._clock())
        frame_target = int(elapsed * self._commands.fps)
        # Consome todos os quadros atrasados, exibindo apenas o mais recente.
        # Nunca bloqueia a GUI esperando decodificação.
        for _ in range(12):
            if self._next_frame is None:
                try: self._next_frame = self._video.output.get_nowait()
                except queue.Empty: break
            if self._next_frame_idx > frame_target: break
            self._last_frame = self._next_frame
            self._last_frame_idx = self._next_frame_idx
            self._next_frame_idx += 1
            self._next_frame = None
        if self._last_frame is not None and self._last_frame_idx >= 0:
            if self._last_frame_idx != getattr(self, '_displayed_idx', -1):
                frame = QImage(self._last_frame, self._commands.width,
                               self._commands.height, self._commands.width*4,
                               QImage.Format.Format_ARGB32).copy()
                self.frame_ready.emit(frame)
                self._displayed_idx = self._last_frame_idx
        if elapsed - self._last_progress > .04:
            self.position_changed.emit(self._commands.source_time + elapsed)
            self._last_progress = elapsed
        next_at = self._commands.source_time + self._commands.duration
        if not self._next_requested and next_at < self._project_end-.02 \
                and elapsed >= max(0, self._commands.duration-6.0):
            self._next_requested = True
            self.next_requested.emit(next_at)
        if elapsed >= self._commands.duration - .015:
            if next_at >= self._project_end-.02:
                self.stop()
                self.position_changed.emit(next_at)
                self.reached_end.emit()
            elif not self._switch_to_prefetched():
                self._waiting_next = True
                self._waiting_since = time.monotonic()
                if self._sink is not None:
                    self._sink.suspend()
                self.status_changed.emit('Prévia · aguardando o próximo trecho (cortes preservados)...')

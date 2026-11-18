"""Low-latency live EQ commands for the FFmpeg azmq preview graph."""
from __future__ import annotations

import threading
from typing import Mapping


class VoicePreviewController:
    """Send bounded, coalesced EQ updates to one running FFmpeg audio graph."""
    def __init__(self,endpoint: str,targets: Mapping[str,Mapping[str,str]],
                 initial_values: Mapping[str,Mapping[str,float]] | None=None,
                 timeout_ms=180):
        import zmq
        self._zmq=zmq
        self.endpoint=str(endpoint)
        self.targets={str(key):dict(value) for key,value in targets.items()}
        self._last_values={str(key):{name:float(value) for name,value in values.items()}
                           for key,values in (initial_values or {}).items()}
        self.timeout_ms=max(20,int(timeout_ms))
        self._socket=None
        self._connect()

    def _connect(self):
        socket=self._zmq.Context.instance().socket(self._zmq.REQ)
        socket.setsockopt(self._zmq.LINGER,0)
        socket.setsockopt(self._zmq.SNDTIMEO,self.timeout_ms)
        socket.setsockopt(self._zmq.RCVTIMEO,self.timeout_ms)
        socket.connect(self.endpoint)
        self._socket=socket

    def close(self):
        if self._socket is not None:
            self._socket.close(linger=0)
            self._socket=None

    def set_eq(self,clip_id: str,values: Mapping[str,float],bypass=False) -> bool:
        target=self.targets.get(str(clip_id))
        if not target or self._socket is None:return False
        gains={
            'bass_db':0. if bypass else float(values.get('bass_db',0.)),
            'mids_db':0. if bypass else float(values.get('mids_db',0.)),
            'treble_db':0. if bypass else float(values.get('treble_db',0.)),
            'pitch_semitones':0. if bypass else float(values.get('pitch_semitones',0.)),
        }
        previous=self._last_values.setdefault(str(clip_id),{})
        previous.setdefault('pitch_semitones',0.)
        if ('pitch_semitones' not in target and
                abs(previous['pitch_semitones']-gains['pitch_semitones'])>=.005):
            # The caller can restart the graph for pitch when this build does
            # not expose Rubber Band through the live command endpoint.
            return False
        pending={key:value for key,value in gains.items()
                 if key in target and (key not in previous or
                    abs(previous[key]-value)>=.005)}
        if not pending:return True
        try:
            for key,gain in pending.items():
                if key=='pitch_semitones':
                    import math
                    command='pitch'
                    value=f'{math.pow(2.,gain/12.):.8f}'
                else:
                    command='gain'
                    value=f'{gain:.2f}'
                self._socket.send_string(f'{target[key]} {command} {value}')
                reply=self._socket.recv_string()
                if not reply.startswith('0 '):
                    self.close();self._connect();return False
                previous[key]=gain
            self._last_values[str(clip_id)]=previous
            return True
        except (self._zmq.Again,self._zmq.ZMQError,ValueError):
            self.close()
            try:self._connect()
            except self._zmq.ZMQError:return False
            return False


class AsyncVoicePreviewController:
    """Coalesce slider changes and keep ZeroMQ round trips off the UI thread.

    A dedicated thread owns the REQ socket because ZeroMQ sockets are not
    thread-safe. During rapid edits only the newest parameter set per clip is
    retained; completed commands are delivered in order by that worker.
    """
    def __init__(self,endpoint: str,targets: Mapping[str,Mapping[str,str]],
                 initial_values: Mapping[str,Mapping[str,float]] | None=None,
                 timeout_ms=180,on_error=None):
        self.endpoint=str(endpoint)
        self.targets={str(key):dict(value) for key,value in targets.items()}
        self.initial_values=initial_values or {}
        self.timeout_ms=max(20,int(timeout_ms))
        self.on_error=on_error
        self._condition=threading.Condition()
        self._pending={}
        self._active=False
        self._closed=False
        self._ready=threading.Event()
        self._available=None
        self._thread=threading.Thread(target=self._run,name='BFSVoiceEQ',daemon=True)
        self._thread.start()

    def _run(self):
        controller=None
        try:
            controller=VoicePreviewController(self.endpoint,self.targets,
                self.initial_values,self.timeout_ms)
            self._available=True
        except Exception:
            self._available=False
        finally:
            self._ready.set()
        while True:
            with self._condition:
                while not self._closed and not self._pending:
                    self._condition.wait()
                if self._closed and not self._pending:
                    break
                # Give the UI a short coalescing window while the user drags.
                self._condition.wait(timeout=.016)
                pending=self._pending
                self._pending={}
                self._active=True
            for clip_id,(values,bypass) in pending.items():
                if controller is None or not controller.set_eq(clip_id,values,bypass):
                    if self.on_error:
                        try:self.on_error(clip_id)
                        except Exception:pass
            with self._condition:
                self._active=False
                self._condition.notify_all()
        if controller is not None:
            controller.close()

    def set_eq(self,clip_id: str,values: Mapping[str,float],bypass=False) -> bool:
        clip_id=str(clip_id)
        if clip_id not in self.targets:return False
        if self._ready.is_set() and not self._available:return False
        with self._condition:
            if self._closed:return False
            self._pending[clip_id]=(dict(values),bool(bypass))
            self._condition.notify()
        return True

    def flush(self,timeout=2.) -> bool:
        """Wait for queued controls; intended for deterministic tests/shutdown."""
        import time
        stop=time.monotonic()+max(0.,float(timeout))
        with self._condition:
            while self._pending or self._active:
                remaining=stop-time.monotonic()
                if remaining<=0:return False
                self._condition.wait(remaining)
        return True

    def close(self):
        with self._condition:
            self._closed=True
            self._pending.clear()
            self._condition.notify_all()
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=.05)

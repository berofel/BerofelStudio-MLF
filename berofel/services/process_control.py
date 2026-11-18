"""Controle cooperativo de tarefas e suspensão/encerramento de subprocessos.

Pausar detém o trabalho pesado (e seus filhos) sem interromper a UI. Cancelar
encerra a árvore de processos e não descarta checkpoints já gravados em cache.
Não depende de Qt: pode ser usado por qualquer motor de processamento.
"""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time

try:
    import psutil
except ImportError:  # instalação principal inclui psutil; fallback só para cancelamento
    psutil = None


class ProcessCancelled(Exception):
    """Cancelamento solicitado pelo usuário: não é uma falha de inferência."""


class ProcessControl:
    def __init__(self):
        self._lock = threading.RLock()
        self._active = {}
        self._cancelled = False
        self._paused = False
        self._started = time.monotonic()
        self._pause_started = None
        self._pause_total = 0.0
        self._last_cpu_sample = ({}, time.monotonic())

    @property
    def cancelled(self):
        with self._lock:
            return self._cancelled

    @property
    def paused(self):
        with self._lock:
            return self._paused

    def elapsed(self):
        with self._lock:
            now = time.monotonic()
            paused = self._pause_total + (now - self._pause_started if self._pause_started is not None else 0)
            return max(0., now - self._started - paused)

    def checkpoint(self):
        """Bloqueia tarefas cooperativas enquanto pausadas; aborta se canceladas."""
        while True:
            with self._lock:
                if self._cancelled:
                    raise ProcessCancelled('Processamento cancelado pelo usuário.')
                if not self._paused:
                    return
            time.sleep(.08)

    @staticmethod
    def _tree(proc):
        if psutil is None:
            return []
        try:
            parent = psutil.Process(proc.pid)
            return parent.children(recursive=True) + [parent]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return []

    def _suspend(self, proc):
        if proc.poll() is not None:
            return
        if psutil is not None:
            for child in self._tree(proc):
                try: child.suspend()
                except (psutil.NoSuchProcess, psutil.AccessDenied): pass
        elif os.name != 'nt':
            try: os.killpg(proc.pid, signal.SIGSTOP)
            except ProcessLookupError: pass
        else:
            raise RuntimeError('Instale psutil para pausar subprocessos no Windows.')

    def _resume(self, proc):
        if proc.poll() is not None:
            return
        if psutil is not None:
            for child in reversed(self._tree(proc)):
                try: child.resume()
                except (psutil.NoSuchProcess, psutil.AccessDenied): pass
        elif os.name != 'nt':
            try: os.killpg(proc.pid, signal.SIGCONT)
            except ProcessLookupError: pass

    def _kill(self, proc):
        # Mesmo um filho que esteja suspenso deve ser encerrado. Os filhos do
        # Python worker podem incluir FFmpeg, llama-cli e outros processos.
        if psutil is not None:
            for child in self._tree(proc):
                try: child.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied): pass
        elif os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        else:
            try: os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        try:
            if proc.poll() is None:
                proc.kill()
        except (OSError, ProcessLookupError):
            pass

    def pause(self):
        with self._lock:
            if self._cancelled or self._paused:
                return False
            if psutil is None and os.name == 'nt':
                raise RuntimeError('Não foi possível pausar: psutil não está instalado.')
            self._paused = True
            self._pause_started = time.monotonic()
            for proc in list(self._active.values()):
                self._suspend(proc)
            return True

    def resume(self):
        with self._lock:
            if not self._paused or self._cancelled:
                return False
            self._pause_total += time.monotonic() - self._pause_started
            self._pause_started = None
            for proc in list(self._active.values()):
                self._resume(proc)
            self._paused = False
            return True

    def cancel(self):
        with self._lock:
            if self._cancelled:
                return False
            self._cancelled = True
            if self._pause_started is not None:
                self._pause_total += time.monotonic() - self._pause_started
                self._pause_started = None
            self._paused = False
            for proc in list(self._active.values()):
                self._kill(proc)
            return True

    def popen(self, cmd, **kwargs):
        self.checkpoint()
        with self._lock:
            if self._cancelled:
                raise ProcessCancelled('Processamento cancelado pelo usuário.')
            kwargs.setdefault('stdin', subprocess.DEVNULL)
            if os.name == 'nt':
                kwargs['creationflags'] = kwargs.get('creationflags', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
            else:
                kwargs.setdefault('start_new_session', True)
            proc = subprocess.Popen(cmd, **kwargs)
            self._active[proc.pid] = proc
            if self._paused:
                self._suspend(proc)
            if self._cancelled:
                self._kill(proc)
                raise ProcessCancelled('Processamento cancelado pelo usuário.')
            return proc

    def release(self, proc):
        with self._lock:
            self._active.pop(proc.pid, None)

    def run(self, cmd, *, timeout=None, on_poll=None, **kwargs):
        proc = self.popen(cmd, **kwargs)
        initial_elapsed = self.elapsed()
        try:
            # Interrogações curtas permitem pausar sem consumir o timeout.
            # communicate() preserva pipes entre tentativas com TimeoutExpired.
            while True:
                try:
                    stdout, stderr = proc.communicate(timeout=.25)
                    break
                except subprocess.TimeoutExpired:
                    self.checkpoint()
                    if on_poll:
                        try:on_poll()
                        except Exception:pass  # status polling must never fail the child task
                    if timeout is not None and self.elapsed() - initial_elapsed > timeout:
                        self._kill(proc)
                        proc.communicate()
                        raise subprocess.TimeoutExpired(cmd, timeout)
            self.checkpoint()
            return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
        finally:
            self.release(proc)

    def resources(self):
        """Métricas do editor inteiro (incluindo filhos), para diagnóstico."""
        if psutil is None:
            return None
        try:
            main = psutil.Process(os.getpid())
            processes = [main, *main.children(recursive=True)]
            memory = 0
            live = 0
            cpu_now = {}
            for process in processes:
                try:
                    memory += process.memory_info().rss
                    times = process.cpu_times()
                    cpu_now[process.pid] = times.user + times.system
                    live += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            now = time.monotonic()
            with self._lock:
                old, when = self._last_cpu_sample
                cpu_seconds = sum(max(0., current - old[pid])
                                  for pid, current in cpu_now.items() if pid in old)
                cpu = 100 * cpu_seconds / max(.01, now - when)
                self._last_cpu_sample = (cpu_now, now)
            vm = psutil.virtual_memory()
            return {'memory_mb': memory / (1024 ** 2), 'cpu_percent': cpu,
                    'process_count': live, 'system_available_mb': vm.available / (1024 ** 2)}
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

"""Execução de funções de edição sem bloquear a thread Qt."""
import inspect
import tempfile

from PySide6.QtCore import QObject, QRunnable, Signal, Slot
from .process_control import ProcessControl, ProcessCancelled


class TaskSignals(QObject):
    success = Signal(object)
    error = Signal(str)
    progress = Signal(float, int)
    stage = Signal(str)
    cancelled = Signal()
    finished = Signal()


class Task(QRunnable):
    def __init__(self, function, *args, **kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = function, args, kwargs
        self.signals = TaskSignals()
        self.control = ProcessControl()

    @Slot()
    def run(self):
        try:
            params = inspect.signature(self.fn).parameters
            options = dict(self.kwargs)
            if 'progress' in params:
                options['progress'] = lambda a, b: self.signals.progress.emit(float(a), int(b))
            if 'control' in params:
                options['control'] = self.control
            if 'stage' in params:
                options['stage'] = lambda message: self.signals.stage.emit(str(message))
            self.control.checkpoint()
            result = self.fn(*self.args, **options)
            try:
                self.control.checkpoint()
            except ProcessCancelled:
                _cleanup_temporary_results(result)
                raise
            self.signals.success.emit(result)
        except ProcessCancelled:
            self.signals.cancelled.emit()
        except Exception as exc:
            if self.control.cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.error.emit(str(exc))
        finally:
            self.signals.finished.emit()


def _cleanup_temporary_results(value):
    """Remove temporary directories returned by work cancelled before delivery."""
    if isinstance(value, tempfile.TemporaryDirectory):
        value.cleanup()
    elif isinstance(value, dict):
        for item in value.values():
            _cleanup_temporary_results(item)
    elif isinstance(value, (tuple, list, set)):
        for item in value:
            _cleanup_temporary_results(item)

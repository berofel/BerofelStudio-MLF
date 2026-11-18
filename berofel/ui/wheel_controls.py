"""Input widgets que só alteram valores pela roda depois de selecionados.

Ao ignorar o evento sem foco, Qt pode propagá-lo para o QScrollArea pai em vez
de mudar inadvertidamente o idioma, a voz ou uma propriedade numérica.
"""
from PySide6.QtCore import QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (QAbstractScrollArea, QApplication, QComboBox,
    QDoubleSpinBox, QSlider, QSpinBox)


class _FocusWheelMixin:
    def wheelEvent(self, event):
        if not self.hasFocus():
            parent=self.parentWidget()
            while parent is not None and not isinstance(parent,QAbstractScrollArea):
                parent=parent.parentWidget()
            if parent is None:
                event.accept()
                return
            position=QPointF(parent.viewport().mapFromGlobal(
                event.globalPosition().toPoint()))
            forwarded=QWheelEvent(position,event.globalPosition(),event.pixelDelta(),
                event.angleDelta(),event.buttons(),event.modifiers(),event.phase(),
                event.inverted(),event.source())
            QApplication.sendEvent(parent.viewport(),forwarded)
            event.accept()
            return
        super().wheelEvent(event)


class WheelGuardComboBox(_FocusWheelMixin, QComboBox):
    pass


class WheelGuardSpinBox(_FocusWheelMixin, QSpinBox):
    pass


class WheelGuardDoubleSpinBox(_FocusWheelMixin, QDoubleSpinBox):
    pass


class WheelGuardSlider(_FocusWheelMixin, QSlider):
    pass

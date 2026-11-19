"""Controls that never change their value from mouse-wheel scrolling.

Wheel events are forwarded to the nearest scroll area so page navigation keeps
working while the pointer is over a combo, numeric field, or slider.
"""
from PySide6.QtCore import QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (QAbstractScrollArea, QApplication, QComboBox,
    QDoubleSpinBox, QSlider, QSpinBox)


class _ScrollThroughWheelMixin:
    def wheelEvent(self, event):
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


class WheelGuardComboBox(_ScrollThroughWheelMixin, QComboBox):
    pass


class WheelGuardSpinBox(_ScrollThroughWheelMixin, QSpinBox):
    pass


class WheelGuardDoubleSpinBox(_ScrollThroughWheelMixin, QDoubleSpinBox):
    pass


class WheelGuardSlider(_ScrollThroughWheelMixin, QSlider):
    pass

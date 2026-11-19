"""Cabeçalho compacto: marca, progresso da tarefa e ações principais."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMenu, QPushButton, QToolButton, QVBoxLayout, QWidget,
)


class StudioHeader(QWidget):
    project_action = Signal(str)
    stage_requested = Signal(str)

    def __init__(self, version: str, parent=None):
        super().__init__(parent)
        self._compact=None
        self.setObjectName('studioHeader')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        root=QHBoxLayout(self)
        root.setContentsMargins(10,4,10,4)
        root.setSpacing(8)

        mark=QLabel();mark.setObjectName('brandMark');mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setAccessibleName('Logo Berofel Studio')
        mark.setFixedSize(42,42)
        logo=Path(__file__).resolve().parents[2]/'assets'/'brand'/'berofel_studio_mark.svg'
        renderer=QSvgRenderer(str(logo))
        if renderer.isValid():
            pixmap=QPixmap(40,40);pixmap.fill(Qt.GlobalColor.transparent)
            painter=QPainter(pixmap);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            renderer.render(painter);painter.end()
            mark.setPixmap(pixmap)
        else:
            mark.setText('▶')
        root.addWidget(mark)
        branding=QVBoxLayout();branding.setSpacing(0)
        self.brand_name=QLabel('BEROFEL');self.brand_name.setObjectName('brandName')
        release=QLabel(f'STUDIO  {version}');release.setObjectName('brandVersion')
        branding.addWidget(self.brand_name);branding.addWidget(release);root.addLayout(branding)

        self.project_name=QLabel('Sem título');self.project_name.setObjectName('projectName')
        self.project_name.setMinimumWidth(50);self.project_name.setMaximumWidth(190)
        self.project_name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.project_name)

        self.task_slot=QWidget();self.task_slot.setObjectName('taskProgressSlot')
        self.task_slot.setMinimumWidth(110);self.task_slot.setMaximumHeight(54)
        self.task_layout=QHBoxLayout(self.task_slot)
        self.task_layout.setContentsMargins(0,0,0,0);self.task_layout.setSpacing(0)
        root.addWidget(self.task_slot,1)

        self.local_status=QLabel('● IA LOCAL');self.local_status.setObjectName('localStatus')
        self.local_status.setToolTip('Silero, Faster-Whisper e Qwen3-TTS Base funcionam localmente quando instalados.')
        root.addWidget(self.local_status)

        self.project_menu_button=QToolButton();self.project_menu_button.setText('Projeto ▾')
        self.project_menu_button.setObjectName('projectMenu')
        menu=QMenu(self.project_menu_button)
        for label,key in (('Novo projeto','new'),('Abrir projeto…','open'),
                          ('Salvar projeto','save'),('Restaurar layout padrão','reset_layout')):
            action=menu.addAction(label)
            action.triggered.connect(lambda checked=False,value=key:self.project_action.emit(value))
        self.project_menu_button.setMenu(menu)
        self.project_menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        root.addWidget(self.project_menu_button)

        self.save_button=QPushButton('Salvar');self.save_button.setObjectName('quietAction')
        self.save_button.clicked.connect(lambda:self.project_action.emit('save'))
        root.addWidget(self.save_button)
        self.export_button=QPushButton('Exportar');self.export_button.setObjectName('primaryAction')
        self.export_button.clicked.connect(lambda:self.stage_requested.emit('export'))
        root.addWidget(self.export_button)

        self.setMinimumHeight(58);self.setMaximumHeight(62)
        self._apply_compact(self.width()<1180)

    def set_task_widget(self,widget):
        if widget is not None and self.task_layout.indexOf(widget)<0:
            self.task_layout.addWidget(widget,1)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self._apply_compact(event.size().width()<1180)

    def _apply_compact(self,compact: bool):
        if self._compact==compact:return
        self._compact=compact
        self.local_status.setVisible(not compact)
        self.project_name.setMinimumWidth(42 if compact else 70)
        self.project_name.setMaximumWidth(100 if compact else 190)
        self.project_menu_button.setText('Proj.' if compact else 'Projeto ▾')
        self.save_button.setText('💾' if compact else 'Salvar')
        self.save_button.setAccessibleName('Salvar projeto')

    def set_project_name(self,name: str):
        self.project_name.setText(name or 'Sem título')
        self.project_name.setToolTip(name or 'Sem título')

    def set_stage(self,key: str):
        """Compatibilidade com o encaminhador; o stepper redundante foi removido."""
        return None

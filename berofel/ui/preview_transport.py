"""Transporte compacto de monitor; delega reprodução ao motor único LivePreview."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPushButton, QSlider, QWidget,
)


def format_frame_time(seconds,fps,compact=False):
    """Formata pelo índice de quadro do projeto, sem arredondar décimos."""
    rate=max(1,int(fps))
    frame=max(0,int(round(float(seconds)*rate)))
    frames=frame%rate
    total_seconds=frame//rate
    secs=total_seconds%60
    total_minutes=total_seconds//60
    mins=total_minutes%60
    hours=total_minutes//60
    if compact:
        return f'{total_minutes:02d}:{secs:02d}:{frames:02d}'
    return f'{hours:02d}:{mins:02d}:{secs:02d}:{frames:02d}'


class PreviewTransport(QWidget):
    play_requested = Signal()
    seek_requested = Signal(float)
    final_frame_requested = Signal()
    quality_changed = Signal(object)
    volume_changed = Signal(float)
    frame_step_requested = Signal(int)

    def __init__(self,parent=None):
        super().__init__(parent)
        self._compact=None
        self.setObjectName('previewTransport')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True)
        row=QHBoxLayout(self);row.setContentsMargins(7,4,7,4);row.setSpacing(4)

        self.begin_button=QPushButton('|◀');self.begin_button.setObjectName('transportButton')
        self.begin_button.setToolTip('Ir ao início da timeline')
        self.begin_button.clicked.connect(lambda:self.seek_requested.emit(0.))
        row.addWidget(self.begin_button)
        self.back_button=QPushButton('−5 s');self.back_button.setObjectName('transportButton')
        self.back_button.setToolTip('Voltar cinco segundos')
        self.back_button.clicked.connect(lambda:self.seek_requested.emit(-5.))
        row.addWidget(self.back_button)
        self.previous_frame_button=QPushButton('◂|');self.previous_frame_button.setObjectName('transportButton')
        self.previous_frame_button.setAccessibleName('Voltar um quadro')
        self.previous_frame_button.setToolTip('Voltar um quadro do projeto  ·  atalho ,')
        self.previous_frame_button.clicked.connect(lambda:self.frame_step_requested.emit(-1))
        row.addWidget(self.previous_frame_button)
        self.play_button=QPushButton('▶');self.play_button.setObjectName('playPrimary')
        self.play_button.setFixedWidth(42);self.play_button.setToolTip('Reproduzir ou pausar a timeline')
        self.play_button.clicked.connect(self.play_requested)
        row.addWidget(self.play_button)
        self.next_frame_button=QPushButton('|▸');self.next_frame_button.setObjectName('transportButton')
        self.next_frame_button.setAccessibleName('Avançar um quadro')
        self.next_frame_button.setToolTip('Avançar um quadro do projeto  ·  atalho .')
        self.next_frame_button.clicked.connect(lambda:self.frame_step_requested.emit(1))
        row.addWidget(self.next_frame_button)
        self.forward_button=QPushButton('+5 s');self.forward_button.setObjectName('transportButton')
        self.forward_button.setToolTip('Avançar cinco segundos')
        self.forward_button.clicked.connect(lambda:self.seek_requested.emit(5.))
        row.addWidget(self.forward_button)
        self.end_button=QPushButton('▶|');self.end_button.setObjectName('transportButton')
        self.end_button.setToolTip('Ir ao fim da timeline')
        self.end_button.clicked.connect(lambda:self.seek_requested.emit(float('inf')))
        row.addWidget(self.end_button)

        self.time_label=QLabel('00:00 / 00:00');self.time_label.setObjectName('transportTime')
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setMinimumWidth(190);self.time_label.setToolTip('Timecode por quadro do projeto')
        row.addWidget(self.time_label,1)

        self.quality=QComboBox();self.quality.setObjectName('previewQuality')
        self.quality.addItem('Leve · 640px', (640,24))
        self.quality.addItem('Média · 960px', (960,24))
        self.quality.addItem('Alta · 1280px', (1280,30))
        self._quality_labels=('Leve · 640px','Média · 960px','Alta · 1280px')
        self._compact_quality_labels=('640 px','960 px','1280 px')
        self.quality.setToolTip('Qualidade temporária da prévia; a exportação usa a resolução do projeto.')
        self.quality.currentIndexChanged.connect(lambda index:self.quality_changed.emit(self.quality.itemData(index)))
        row.addWidget(self.quality)

        self.volume_label=QLabel('VOL');self.volume_label.setObjectName('volumeLabel');row.addWidget(self.volume_label)
        self.volume=QSlider(Qt.Orientation.Horizontal);self.volume.setObjectName('previewVolume')
        self.volume.setRange(0,100);self.volume.setValue(85);self.volume.setFixedWidth(76)
        self.volume.setToolTip('Volume da prévia, sem alterar o ganho gravado nos clipes.')
        self.volume.setAccessibleName('Volume da prévia')
        self.volume.valueChanged.connect(lambda value:self.volume_changed.emit(value/100.))
        row.addWidget(self.volume)

        self.final_frame_button=QPushButton('▣ Quadro');self.final_frame_button.setObjectName('transportButton')
        self.final_frame_button.setToolTip('Renderizar um quadro composto na resolução do projeto')
        self.final_frame_button.clicked.connect(self.final_frame_requested)
        row.addWidget(self.final_frame_button)
        self._apply_compact(self.width()<450)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self._apply_compact(event.size().width()<450)
        self._apply_density(event.size().width())

    def _apply_compact(self,compact: bool):
        if self._compact==compact:
            self._apply_density(self.width())
            return
        self._compact=compact
        for widget in (self.begin_button,self.end_button,self.volume_label,self.final_frame_button):
            widget.setVisible(not compact)
        if compact:
            self.setToolTip('Controles compactos da prévia; início, quadro final e volume detalhado permanecem disponíveis em janelas maiores.')
            self.layout().setContentsMargins(4,2,4,2)
            self.layout().setSpacing(2)
            self.back_button.setFixedWidth(40);self.forward_button.setFixedWidth(40)
            self.previous_frame_button.setFixedWidth(30);self.next_frame_button.setFixedWidth(30)
            self.play_button.setFixedWidth(38)
            self.time_label.setFixedWidth(112)
            self.quality.setMinimumWidth(72);self.quality.setMaximumWidth(80)
            self.volume.setFixedWidth(50)
            labels=self._compact_quality_labels
        else:
            self.setToolTip('')
            self.layout().setContentsMargins(7,4,7,4)
            self.layout().setSpacing(4)
            self.back_button.setMaximumWidth(16777215);self.forward_button.setMaximumWidth(16777215)
            self.previous_frame_button.setMaximumWidth(16777215)
            self.next_frame_button.setMaximumWidth(16777215)
            self.play_button.setFixedWidth(42)
            self.time_label.setMinimumWidth(190);self.time_label.setMaximumWidth(16777215)
            self.quality.setMinimumWidth(0);self.quality.setMaximumWidth(16777215)
            self.volume.setFixedWidth(76)
            labels=self._quality_labels
        for index,label in enumerate(labels):self.quality.setItemText(index,label)
        self._apply_density(self.width())

    def _apply_density(self,width):
        narrow=self._compact and width<450
        ultra_narrow=self._compact and width<300
        self.back_button.setVisible(not narrow)
        self.forward_button.setVisible(not narrow)
        # A faixa vertical de ferramentas reduz o espaço disponível em janelas
        # pequenas. Preserve os controles de reprodução sem sobrepor qualidade
        # e volume; ambos continuam configuráveis em larguras maiores.
        self.quality.setVisible(not ultra_narrow)
        self.volume.setVisible(not ultra_narrow)
        if narrow:
            self.previous_frame_button.setFixedWidth(26)
            self.next_frame_button.setFixedWidth(26)
            self.time_label.setFixedWidth(100)
            self.quality.setMinimumWidth(58);self.quality.setMaximumWidth(62)
            self.volume.setFixedWidth(36)
            self.time_label.setFixedWidth(88 if ultra_narrow else 100)
        elif self._compact:
            self.previous_frame_button.setFixedWidth(30)
            self.next_frame_button.setFixedWidth(30)
            self.time_label.setFixedWidth(112)
            self.quality.setMinimumWidth(72);self.quality.setMaximumWidth(80)
            self.volume.setFixedWidth(50)

    def set_quality(self,value):
        for index in range(self.quality.count()):
            if self.quality.itemData(index)==value:
                self.quality.setCurrentIndex(index);return

    def set_playing(self,playing):
        self.play_button.setText('Ⅱ' if playing else '▶')

    def set_preparing(self):
        self.play_button.setText('…')

    def set_time(self,current,total,fps=30):
        current_code=format_frame_time(current,fps,self._compact)
        total_code=format_frame_time(total,fps,self._compact)
        self.time_label.setText(f'{current_code} / {total_code}')
        self.time_label.setToolTip(
            f'Timecode por quadro · {format_frame_time(current,fps)} / '
            f'{format_frame_time(total,fps)} · {int(fps)} fps')

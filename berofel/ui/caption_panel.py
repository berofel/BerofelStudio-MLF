"""Inspector de legendas editáveis da timeline."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSignalBlocker
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from .wheel_controls import WheelGuardSpinBox as QSpinBox
from .wheel_controls import WheelGuardComboBox
from PySide6.QtWidgets import QTextEdit


class CaptionPanel(QWidget):
    """Lista e formata legendas sem abrir diálogos modais."""

    caption_selected = Signal(str)
    add_requested = Signal(str)
    apply_text_requested = Signal(str, str)
    property_changed = Signal(str, str, object)
    preview_text_changed = Signal(str, str)
    preset_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project = None
        self._current_id = ''
        self.setObjectName('captionPanel')
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 9, 10, 9)
        root.setSpacing(7)

        heading = QLabel('LEGENDAS')
        heading.setObjectName('captionPanelHeading')
        root.addWidget(heading)
        hint = QLabel('Selecione uma legenda para editar. As alterações são aplicadas ao bloco da timeline.')
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.caption_list = QListWidget()
        self.caption_list.setObjectName('captionClipList')
        self.caption_list.setAccessibleName('Legendas do projeto')
        self.caption_list.currentItemChanged.connect(self._on_current_changed)
        root.addWidget(self.caption_list, 1)

        self.text_edit = QTextEdit()
        self.text_edit.setObjectName('captionTextEditor')
        self.text_edit.setPlaceholderText('Selecione uma legenda ou escreva uma nova…')
        self.text_edit.setMinimumHeight(76)
        self.text_edit.textChanged.connect(self._preview_text)
        root.addWidget(self.text_edit)

        actions = QHBoxLayout()
        self.add_button = QPushButton('＋ Adicionar no playhead')
        self.add_button.setObjectName('addCaptionButton')
        self.add_button.clicked.connect(lambda: self.add_requested.emit(self.text_edit.toPlainText()))
        actions.addWidget(self.add_button)
        self.apply_button = QPushButton('Aplicar texto')
        self.apply_button.setObjectName('applyCaptionTextButton')
        self.apply_button.clicked.connect(self._apply_text)
        actions.addWidget(self.apply_button)
        root.addLayout(actions)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(divider)
        style_heading = QLabel('ESTILO DA LEGENDA')
        style_heading.setObjectName('captionStyleHeading')
        root.addWidget(style_heading)

        self.preset = WheelGuardComboBox()
        self.preset.setObjectName('captionPreset')
        self.preset.addItems(['Presets de legenda', 'Clássica', 'Compacta',
                              'Destaque', 'Discreta'])
        self.preset.activated.connect(self._apply_preset)
        root.addWidget(self.preset)

        self.font_family = WheelGuardComboBox()
        self.font_family.setObjectName('captionFontFamily')
        self.font_family.addItems(['Arial', 'Calibri', 'Segoe UI', 'Verdana', 'Georgia'])
        self.font_family.currentTextChanged.connect(
            lambda value: self._change('font_family', value))
        root.addWidget(self._labeled('Fonte', self.font_family))

        self.font_size = QSpinBox()
        self.font_size.setObjectName('captionFontSize')
        self.font_size.setRange(12, 200)
        self.font_size.setSuffix(' px')
        self.font_size.editingFinished.connect(
            lambda: self._change('font_size', self.font_size.value()))
        root.addWidget(self._labeled('Tamanho', self.font_size))

        color_row = QHBoxLayout()
        self.font_color = QLineEdit()
        self.font_color.setObjectName('captionFontColor')
        self.font_color.setMaxLength(7)
        self.font_color.setPlaceholderText('#FFFFFF')
        self.font_color.editingFinished.connect(
            lambda: self._change('font_color', self.font_color.text()))
        color_row.addWidget(self.font_color, 1)
        self.color_button = QPushButton('Escolher cor')
        self.color_button.clicked.connect(self._choose_color)
        color_row.addWidget(self.color_button)
        color_holder = QWidget(); color_holder.setLayout(color_row)
        root.addWidget(self._labeled('Cor do texto', color_holder))

        self.stroke_width = QSpinBox()
        self.stroke_width.setObjectName('captionStrokeWidth')
        self.stroke_width.setRange(0, 12)
        self.stroke_width.valueChanged.connect(
            lambda value: self._change('stroke_width', value))
        root.addWidget(self._labeled('Contorno', self.stroke_width))

        self.pos_y = QSpinBox()
        self.pos_y.setObjectName('captionPositionY')
        self.pos_y.setRange(-4000, 4000)
        self.pos_y.setSuffix(' px')
        self.pos_y.editingFinished.connect(lambda: self._change('pos_y', self.pos_y.value()))
        root.addWidget(self._labeled('Posição vertical', self.pos_y))

        self.state_label = QLabel('Nenhuma legenda selecionada.')
        self.state_label.setWordWrap(True)
        self.state_label.setObjectName('captionPanelState')
        root.addWidget(self.state_label)
        self._set_controls_enabled(False)

    @staticmethod
    def _labeled(label, widget):
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        title = QLabel(label)
        layout.addWidget(title)
        layout.addWidget(widget)
        return holder

    def _on_current_changed(self, current, _previous):
        clip_id = str(current.data(Qt.ItemDataRole.UserRole)) if current else ''
        if clip_id:
            self.caption_selected.emit(clip_id)
        self._load_clip(clip_id)

    def _load_clip(self, clip_id):
        self._current_id = str(clip_id or '')
        clip = self._project.clip(self._current_id) if self._project and self._current_id else None
        self._set_controls_enabled(bool(clip and clip.kind == 'text'))
        with QSignalBlocker(self.text_edit):
            self.text_edit.setPlainText(clip.text if clip else '')
        if clip:
            for widget, value in ((self.font_family, clip.font_family),
                                  (self.font_size, clip.font_size),
                                  (self.font_color, clip.font_color),
                                  (self.stroke_width, clip.stroke_width),
                                  (self.pos_y, clip.pos_y)):
                with QSignalBlocker(widget):
                    if isinstance(widget, QLineEdit):
                        widget.setText(str(value))
                    elif isinstance(widget, QComboBox):
                        widget.setCurrentText(str(value))
                    else:
                        widget.setValue(int(value))
            self.state_label.setText(
                f'{clip.title} · {clip.timeline_start:.2f}–{clip.timeline_end:.2f} s')
        else:
            self.state_label.setText('Selecione uma legenda ou escreva uma nova.')

    def _set_controls_enabled(self, enabled):
        for widget in (self.apply_button, self.preset, self.font_family, self.font_size,
                       self.font_color, self.color_button, self.stroke_width, self.pos_y):
            widget.setEnabled(bool(enabled))

    def _change(self, field, value):
        if self._current_id:
            self.property_changed.emit(self._current_id, field, value)

    def _preview_text(self):
        if self._current_id:
            self.preview_text_changed.emit(self._current_id, self.text_edit.toPlainText())

    def _apply_text(self):
        if self._current_id:
            self.apply_text_requested.emit(self._current_id, self.text_edit.toPlainText())

    def _apply_preset(self, index):
        if index:
            self.preset_requested.emit(int(index))
            with QSignalBlocker(self.preset):
                self.preset.setCurrentIndex(0)

    def _choose_color(self):
        color = QColorDialog.getColor(QColor(self.font_color.text() or '#FFFFFF'), self,
                                      'Cor da legenda')
        if color.isValid():
            self.font_color.setText(color.name().upper())
            self._change('font_color', color.name().upper())

    def set_context(self, project, selected_ids=()):
        self._project = project
        captions = sorted((clip for clip in project.clips if clip.kind == 'text'),
                          key=lambda clip: (clip.timeline_start, clip.id))
        desired = next((str(cid) for cid in selected_ids
                        if (clip := project.clip(cid)) and clip.kind == 'text'), '')
        ids = {clip.id for clip in captions}
        if not desired and self._current_id in ids:
            desired = self._current_id
        blocker = QSignalBlocker(self.caption_list)
        self.caption_list.clear()
        for clip in captions:
            preview = ' '.join(clip.text.split())
            if len(preview) > 52:
                preview = preview[:49] + '…'
            item = QListWidgetItem(f'{clip.timeline_start:06.2f}  ·  {preview or "(sem texto)"}')
            item.setData(Qt.ItemDataRole.UserRole, clip.id)
            item.setToolTip(f'{clip.title}\n{clip.timeline_start:.3f}–{clip.timeline_end:.3f} s\n{clip.text}')
            self.caption_list.addItem(item)
            if clip.id == desired:
                self.caption_list.setCurrentItem(item)
        del blocker
        self._load_clip(desired if desired in ids else '')
        self.state_label.setText(
            f'{len(captions)} legenda(s) no projeto.' if not desired and captions else
            self.state_label.text())

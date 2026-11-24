"""Inspector de legendas editáveis da timeline."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSignalBlocker, QThreadPool
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from .wheel_controls import WheelGuardSpinBox as QSpinBox
from .wheel_controls import WheelGuardComboBox
from PySide6.QtWidgets import QTextEdit

from berofel.services.transcript_proofing import (apply_suggestion,
    load_pt_br_dictionary, project_approved_words, spelling_suggestions)
from berofel.services.tasks import Task


def _proofread_text(text, approved_words=()):
    dictionary = load_pt_br_dictionary()
    if dictionary is None:
        return text, None
    return text, spelling_suggestions(text, dictionary=dictionary,
                                      approved_words=approved_words)


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

        self.proofread_button = QPushButton('Revisar ortografia')
        self.proofread_button.setObjectName('proofreadCaptionButton')
        self.proofread_button.clicked.connect(self._proofread)
        root.addWidget(self.proofread_button)
        self.spelling_list = QListWidget()
        self.spelling_list.setObjectName('captionSpellingSuggestions')
        self.spelling_list.setMaximumHeight(112)
        self.spelling_list.setToolTip('Sugestões locais. Confira antes de aplicar.')
        root.addWidget(self.spelling_list)
        self.apply_spelling_button = QPushButton('Aplicar sugestão selecionada')
        self.apply_spelling_button.setObjectName('applySpellingSuggestionButton')
        self.apply_spelling_button.clicked.connect(self._apply_spelling_suggestion)
        self.apply_spelling_button.setEnabled(False)
        self.spelling_list.currentRowChanged.connect(
            lambda row: self.apply_spelling_button.setEnabled(row >= 0))
        root.addWidget(self.apply_spelling_button)
        self._spelling_issues = ()
        self._proofread_task = None
        self._proofread_request = 0
        self._proofread_pending = None

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

        stroke_color_row=QHBoxLayout()
        self.stroke_color=QLineEdit();self.stroke_color.setObjectName('captionStrokeColor')
        self.stroke_color.setMaxLength(7);self.stroke_color.setPlaceholderText('#000000')
        self.stroke_color.editingFinished.connect(
            lambda:self._change('stroke_color',self.stroke_color.text()))
        stroke_color_row.addWidget(self.stroke_color,1)
        self.stroke_color_button=QPushButton('Escolher')
        self.stroke_color_button.clicked.connect(self._choose_stroke_color)
        stroke_color_row.addWidget(self.stroke_color_button)
        stroke_color_holder=QWidget();stroke_color_holder.setLayout(stroke_color_row)
        root.addWidget(self._labeled('Cor do contorno',stroke_color_holder))

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

        self.pos_x = QSpinBox()
        self.pos_x.setObjectName('captionPositionX')
        self.pos_x.setRange(-4000,4000)
        self.pos_x.setSuffix(' px')
        self.pos_x.editingFinished.connect(lambda:self._change('pos_x',self.pos_x.value()))
        root.addWidget(self._labeled('Posição horizontal',self.pos_x))

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
        self._proofread_request += 1
        self._current_id = str(clip_id or '')
        clip = self._project.clip(self._current_id) if self._project and self._current_id else None
        self._set_controls_enabled(bool(clip and clip.kind == 'text'))
        self.spelling_list.clear()
        self._spelling_issues = ()
        self.apply_spelling_button.setEnabled(False)
        with QSignalBlocker(self.text_edit):
            self.text_edit.setPlainText(clip.text if clip else '')
        if clip:
            for widget, value in ((self.font_family, clip.font_family),
                                  (self.font_size, clip.font_size),
                                  (self.font_color, clip.font_color),
                                  (self.stroke_color,clip.stroke_color),
                                  (self.stroke_width, clip.stroke_width),
                                  (self.pos_y, clip.pos_y),
                                  (self.pos_x, clip.pos_x)):
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
                       self.font_color, self.color_button, self.stroke_color,
                       self.stroke_color_button,self.stroke_width,self.pos_y,self.pos_x):
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

    def _proofread(self):
        self.spelling_list.clear()
        self._spelling_issues = ()
        if not self._current_id:
            self.state_label.setText('Selecione uma legenda antes da revisão ortográfica.')
            return
        if self._proofread_task is not None:
            return
        text = self.text_edit.toPlainText()
        self._proofread_request += 1
        request = self._proofread_request
        clip_id = self._current_id
        self._proofread_pending = (request, clip_id, text)
        self.proofread_button.setEnabled(False)
        self.state_label.setText('Verificando ortografia localmente…')
        approved_words = project_approved_words(self._project)
        task = Task(_proofread_text, text, approved_words)
        self._proofread_task = task
        task.signals.success.connect(self._proofread_success)
        task.signals.error.connect(self._proofread_error)
        task.signals.finished.connect(self._proofread_finished)
        QThreadPool.globalInstance().start(task)

    def _proofread_finished(self):
        self._proofread_task = None
        self._proofread_pending = None
        self.proofread_button.setEnabled(bool(self._current_id))

    def _proofread_success(self, result):
        if self._proofread_pending is None:
            return
        request, clip_id, _text = self._proofread_pending
        self._proofread_complete(request, clip_id, result)

    def _proofread_error(self, error):
        if self._proofread_pending is None:
            return
        request, clip_id, text = self._proofread_pending
        self._proofread_complete(request, clip_id, (text, RuntimeError(error)))

    def _proofread_complete(self, request, clip_id, result):
        if request != self._proofread_request or clip_id != self._current_id:
            return
        text, issues = result
        if isinstance(issues, Exception):
            self.state_label.setText(f'Falha na revisão ortográfica local: {issues}')
            return
        if issues is None:
            self.state_label.setText(
                'Dicionário pt-BR indisponível. Configure VERO/Hunspell e Spylls; '
                'a revisão funciona localmente e só sugere alterações.')
            return
        if self.text_edit.toPlainText() != text:
            self.state_label.setText('O texto mudou durante a revisão. Revise novamente.')
            return
        self._spelling_issues = issues
        if not self._spelling_issues:
            self.state_label.setText('Nenhum possível erro ortográfico encontrado.')
            return
        for issue_index, issue in enumerate(self._spelling_issues):
            for suggestion in issue.suggestions:
                item = QListWidgetItem(
                    f'{issue.word} → {suggestion}  ·  posição {issue.start + 1}')
                item.setData(Qt.ItemDataRole.UserRole, (issue_index, suggestion))
                self.spelling_list.addItem(item)
        self.state_label.setText(
            f'{len(self._spelling_issues)} palavra(s) para conferir. '
            'Selecione uma sugestão e aplique; o texto só é salvo ao usar Aplicar texto.')

    def _apply_spelling_suggestion(self):
        row = self.spelling_list.currentItem()
        if not row:
            return
        issue_index, replacement = row.data(Qt.ItemDataRole.UserRole)
        if not 0 <= int(issue_index) < len(self._spelling_issues):
            return
        try:
            corrected = apply_suggestion(self.text_edit.toPlainText(),
                                         self._spelling_issues[int(issue_index)],
                                         str(replacement))
        except ValueError as exc:
            self.state_label.setText(str(exc) + ' Execute a revisão novamente.')
            return
        self.text_edit.setPlainText(corrected)
        self._proofread()

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

    def _choose_stroke_color(self):
        color=QColorDialog.getColor(QColor(self.stroke_color.text() or '#000000'),self,
                                    'Cor do contorno')
        if color.isValid():
            self.stroke_color.setText(color.name().upper())
            self._change('stroke_color',color.name().upper())

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

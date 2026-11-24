"""User interface for deterministic Berofel Script V1 narration."""
from __future__ import annotations

from pathlib import Path
import shutil

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
                               QPushButton, QComboBox, QSpinBox, QTableWidget,
                               QTableWidgetItem, QFileDialog, QMessageBox, QGroupBox,
                               QHeaderView, QAbstractItemView, QDialog,
                               QDialogButtonBox)
from PySide6.QtCore import Qt

from berofel.services.voice_profiles import VoiceProfileManager
from berofel.services.multivoice_narration import (
    SCRIPT_FORMAT, ScriptValidationError, DialogueLine, create_script,
    parse_berofel_script, reorder_lines,
)
from berofel.core.project import new_id


class MultiVoicePanel(QWidget):
    """Parse and submit a multi-character script using saved local profiles."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.on_generate = None
        self.on_regenerate = None
        self.on_script_changed = None
        self.on_export = None
        self.active_script = None
        self.voice_profiles = VoiceProfileManager()
        self._profile_sha256: dict[str, str] = {}
        self._profiles_by_id: dict[str, dict] = {}
        self._forcing_ptbr_backend = False
        self._ptbr_backend_notice = False
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
        heading = QLabel('VÁRIAS VOZES · QWEN3-TTS 0.6B')
        heading.setStyleSheet('color:#9cc7ff;font-weight:800;font-size:13px;')
        root.addWidget(heading)
        root.addWidget(QLabel('Cada fala é sintetizada separadamente e agrupada por perfil vocal.'))

        engine_box = QGroupBox('Perfil de desempenho')
        engine_row = QHBoxLayout(engine_box)
        self.engine = QComboBox()
        try:
            from berofel.services.qwen3_purec_tts import is_ready
            purec_ready = is_ready()
        except (ImportError, OSError, ValueError):
            purec_ready = False
        self._recommended_ids = set()
        if purec_ready:
            self.engine.addItem('Equilibrado — Pure C INT8 · 6 threads', 'qwen3-tts-purec-int8')
            self.engine.addItem('Turbo — Pure C Mixer · 6 threads', 'qwen3-tts-purec-mixed')
            self._recommended_ids = {'qwen3-tts-purec-int8', 'qwen3-tts-purec-mixed'}
            self.engine.setItemData(1, 'API instalada: qwen3-tts-purec-mixed (variante mista)',
                                    Qt.ItemDataRole.ToolTipRole)
        self.engine.insertSeparator(self.engine.count())
        for engine_id, label, ready_fn in (
            ('qwen3-tts-local', 'Outros perfis · Original — Qwen3 Base', None),
            ('qwen3-tts-native-q4', 'Outros perfis · Turbo Q4 · 6 threads', 'native'),
            ('qwen3-tts-native-q4-balanced', 'Outros perfis · Equilibrado Q4 · 8 threads', 'native'),
        ):
            available = True
            if ready_fn == 'native':
                try:
                    from berofel.services.qwen3_native_tts import is_ready as native_ready
                    available = native_ready()
                except (ImportError, OSError, ValueError):
                    available = False
            if available:
                self.engine.addItem(label, engine_id)
        saved_engine = self._settings().value('narration/multivoice_engine',
                                               'qwen3-tts-local')
        idx = self.engine.findData(saved_engine)
        self.engine.setCurrentIndex(idx if idx >= 0 else (0 if purec_ready else self.engine.count()-1))
        self.engine.currentIndexChanged.connect(self._save_engine)
        engine_row.addWidget(self.engine, 1)
        root.addWidget(engine_box)
        self.engine_note = QLabel()
        self.engine_note.setWordWrap(True)
        self.engine_note.setStyleSheet('color:#e8b86a;font-size:11px;')
        root.addWidget(self.engine_note)
        self.engine.currentIndexChanged.connect(self._update_engine_note)
        self.engine.currentIndexChanged.connect(self._ensure_ptbr_engine)

        self.pause = QSpinBox()
        self.pause.setRange(0, 60_000)
        try:
            pause_ms = int(self._settings().value('narration/multivoice_pause_ms', 200))
        except (TypeError, ValueError):
            pause_ms = 200
        self.pause.setValue(max(0, min(60_000, pause_ms)))
        self.pause.setSuffix(' ms entre falas')
        self.pause.valueChanged.connect(
            lambda value: self._settings().setValue('narration/multivoice_pause_ms', int(value)))
        root.addWidget(self.pause)

        self.assignments: dict[str, QComboBox] = {}
        self.voice_box = QGroupBox('Personagens e perfis salvos')
        self.voice_layout = QVBoxLayout(self.voice_box)
        self.refresh_profiles()
        root.addWidget(self.voice_box)

        source_row = QHBoxLayout()
        self.import_button = QPushButton('Importar roteiro…')
        self.import_button.clicked.connect(self.import_script)
        source_row.addWidget(self.import_button)
        self.validate_button = QPushButton('Validar e visualizar')
        self.validate_button.clicked.connect(self.preview_script)
        source_row.addWidget(self.validate_button)
        root.addLayout(source_row)
        self.script_text = QTextEdit()
        self.script_text.setAcceptRichText(False)
        self.script_text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.script_text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.script_text.setPlaceholderText(
            f'{SCRIPT_FORMAT}\n[001 | V1]\nPrimeira fala.\n[002 | V2]\nSegunda fala.')
        self.script_text.setMinimumHeight(170)
        root.addWidget(self.script_text, 2)
        self.script_text.textChanged.connect(self._update_engine_note)
        self.script_text.textChanged.connect(self._ensure_ptbr_engine)
        self.lines = QTableWidget(0, 4)
        self.lines.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lines.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lines.setHorizontalHeaderLabels(['Nº', 'Voz', 'Texto', 'Estado'])
        self.lines.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.lines.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked |
                                   QAbstractItemView.EditTrigger.EditKeyPressed)
        self.lines.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.lines.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.lines.itemSelectionChanged.connect(self._selection_state)
        root.addWidget(self.lines, 2)
        structure_actions = QHBoxLayout()
        self.add_line_button = QPushButton('+ Fala')
        self.add_line_button.clicked.connect(self.add_dialogue_line)
        structure_actions.addWidget(self.add_line_button)
        self.remove_line_button = QPushButton('Remover')
        self.remove_line_button.clicked.connect(self.remove_dialogue_line)
        structure_actions.addWidget(self.remove_line_button)
        self.move_up_button = QPushButton('↑')
        self.move_up_button.setToolTip('Mover fala para cima')
        self.move_up_button.clicked.connect(lambda: self.move_dialogue_line(-1))
        structure_actions.addWidget(self.move_up_button)
        self.move_down_button = QPushButton('↓')
        self.move_down_button.setToolTip('Mover fala para baixo')
        self.move_down_button.clicked.connect(lambda: self.move_dialogue_line(1))
        structure_actions.addWidget(self.move_down_button)
        root.addLayout(structure_actions)
        line_actions = QHBoxLayout()
        self.play_line = QPushButton('▶ Ouvir fala selecionada')
        self.play_line.clicked.connect(self.play_selected_line)
        self.play_line.setEnabled(False)
        line_actions.addWidget(self.play_line)
        self.regenerate_line = QPushButton('Regenerar somente esta fala')
        self.regenerate_line.clicked.connect(self.regenerate_selected_line)
        self.regenerate_line.setEnabled(False)
        line_actions.addWidget(self.regenerate_line)
        self.save_line = QPushButton('Salvar WAV desta fala…')
        self.save_line.clicked.connect(self.save_selected_wav)
        self.save_line.setEnabled(False)
        line_actions.addWidget(self.save_line)
        root.addLayout(line_actions)
        self.summary = QLabel('Cole um roteiro e valide para conferir as falas antes de gerar.')
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        self.generate_button = QPushButton('Gerar roteiro e inserir na timeline')
        self.generate_button.clicked.connect(self.generate)
        root.addWidget(self.generate_button)
        self.resume_button = QPushButton('Retomar roteiro salvo')
        self.resume_button.clicked.connect(self.resume_script)
        self.resume_button.setEnabled(False)
        root.addWidget(self.resume_button)
        self.export_script_button = QPushButton('Exportar WAV completo do roteiro…')
        self.export_script_button.clicked.connect(
            lambda: self.on_export(self.active_script) if self.active_script and self.on_export else None)
        self.export_script_button.setEnabled(False)
        root.addWidget(self.export_script_button)
        self.status = QLabel('Os WAVs são criados individualmente; a ordem narrativa é mantida na timeline.')
        self.status.setWordWrap(True)
        root.addWidget(self.status)

    @staticmethod
    def _settings():
        from PySide6.QtCore import QSettings
        return QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                         'Berofel', 'BerofelStudio')

    def _save_engine(self, *_):
        self._settings().setValue('narration/multivoice_engine', self.engine.currentData())

    def refresh_profiles(self):
        selected = {voice_id: combo.currentData()
                    for voice_id, combo in getattr(self, 'assignments', {}).items()}
        while self.voice_layout.count():
            item = self.voice_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.assignments.clear()
        try:
            profiles = self.voice_profiles.list_profiles()
        except (OSError, ValueError) as exc:
            profiles = []
            error = str(exc)
        else:
            error = ''
        self._profile_sha256 = {
            str(profile['id']): str(profile.get('sample_sha256', ''))
            for profile in profiles if profile.get('authorized') and
            profile.get('sample_sha256')}
        self._profiles_by_id = {str(profile['id']): profile for profile in profiles}
        names = {f'V{i}' for i in range(1, 11)}
        for voice_id in sorted(names, key=lambda key: int(key[1:])):
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(QLabel(voice_id))
            combo = QComboBox()
            combo.addItem('Selecione perfil autorizado…', '')
            for profile in profiles:
                if profile.get('authorized'):
                    combo.addItem(profile['name'], profile['id'])
            old_profile = selected.get(voice_id)
            old_index = combo.findData(old_profile)
            if old_index >= 0:
                combo.setCurrentIndex(old_index)
            layout.addWidget(combo, 1)
            self.assignments[voice_id] = combo
            combo.currentIndexChanged.connect(self._update_engine_note)
            combo.currentIndexChanged.connect(self._ensure_ptbr_engine)
            self.voice_layout.addWidget(row)
        self.profile_error = error
        if error and hasattr(self, 'status'):
            self.status.setText(f'Não foi possível carregar os perfis: {error}')
        elif hasattr(self, 'status') and not any(combo.count() > 1 for combo in self.assignments.values()):
            self.status.setText('Crie e autorize pelo menos um perfil em Uma voz antes de montar o roteiro.')
        if hasattr(self, 'engine_note'):
            self._ensure_ptbr_engine()
            self._update_engine_note()

    def _ptbr_profile_selected(self) -> bool:
        # refresh_profiles() runs while the widget tree is still being built;
        # the script editor is created immediately after the profile selectors.
        if not hasattr(self, 'script_text'):
            return False
        if self.active_script:
            voice_ids = {line.voice_id for line in self.active_script.lines}
            profile_ids = {str(self.active_script.voices[voice_id].get('profile_id', ''))
                           for voice_id in voice_ids
                           if voice_id in self.active_script.voices}
        else:
            try:
                voice_ids = {line.voice_id for line in
                             parse_berofel_script(self.script_text.toPlainText())}
            except ScriptValidationError:
                voice_ids = set()
            profile_ids = ({str(self.assignments[voice_id].currentData() or '')
                            for voice_id in voice_ids if voice_id in self.assignments}
                           if voice_ids else
                           {str(combo.currentData() or '')
                            for combo in self.assignments.values()})
        return any(
            profile_id and str(self._profiles_by_id.get(profile_id, {}).get(
                'language', 'portuguese')).casefold() == 'portuguese'
            for profile_id in profile_ids)

    def _ensure_ptbr_engine(self, *_):
        """PT-BR cloning requires Base ICL with both reference audio and text."""
        if self._forcing_ptbr_backend or not self._ptbr_profile_selected():
            return
        if self.engine.currentData() == 'qwen3-tts-local':
            return
        index = self.engine.findData('qwen3-tts-local')
        if index < 0:
            return
        self._forcing_ptbr_backend = True
        try:
            self._ptbr_backend_notice = True
            self.engine.setCurrentIndex(index)
            self.status.setText(
                'Perfis PT-BR usam o Qwen3 Base Original com áudio e transcrição. '
                'Pure C e Q4 não recebem a transcrição de referência neste fluxo.')
        finally:
            self._forcing_ptbr_backend = False

    def _update_engine_note(self, *_):
        if not hasattr(self, 'engine_note'):
            return
        if self.active_script:
            used_voices = {line.voice_id for line in self.active_script.lines}
            profile_by_voice = {
                voice_id: str(self.active_script.voices[voice_id].get('profile_id', ''))
                for voice_id in used_voices
                if voice_id in self.active_script.voices and
                self.active_script.voices[voice_id].get('profile_id')}
        else:
            try:
                used_voices = ({line.voice_id for line in
                                parse_berofel_script(self.script_text.toPlainText())}
                               if hasattr(self, 'script_text') else set())
            except ScriptValidationError:
                used_voices = set()
            profile_by_voice = {
                voice_id: str(self.assignments[voice_id].currentData() or '')
                for voice_id in used_voices
                if voice_id in self.assignments and
                self.assignments[voice_id].currentData()}
        selected_profiles = set(profile_by_voice.values())
        voices_by_profile: dict[str, list[str]] = {}
        for voice_id, profile_id in profile_by_voice.items():
            voices_by_profile.setdefault(profile_id, []).append(voice_id)
        repeated_voice_ids = next((sorted(voice_ids,
            key=lambda voice: int(voice[1:]))
            for voice_ids in voices_by_profile.values() if len(voice_ids) > 1), [])
        notes = []
        if self._ptbr_backend_notice and self._ptbr_profile_selected():
            notes.append(
                'PT-BR: Original Qwen3 Base selecionado para condicionar a clonagem '
                'com a gravação e a transcrição de cada perfil.')
        if repeated_voice_ids:
            notes.append('Os personagens ' + ', '.join(repeated_voice_ids) +
                ' usam o mesmo perfil vocal e terão a mesma identidade de voz. ' +
                'Associe perfis diferentes se quiser vozes distintas.')
        elif len(selected_profiles) > 1:
            voices_by_reference: dict[str, list[str]] = {}
            for voice_id, profile_id in profile_by_voice.items():
                fingerprint = self._profile_sha256.get(profile_id, '')
                if fingerprint:
                    voices_by_reference.setdefault(fingerprint, []).append(voice_id)
            duplicated_reference_voices = next((sorted(voice_ids,
                key=lambda voice: int(voice[1:]))
                for voice_ids in voices_by_reference.values() if len(voice_ids) > 1), [])
            if duplicated_reference_voices:
                notes.append('Os personagens ' + ', '.join(duplicated_reference_voices) +
                    ' usam perfis diferentes, mas a mesma gravação de referência; ' +
                    'a identidade vocal tende a ser a mesma. Escolha gravações distintas ' +
                    'para personagens com vozes diferentes.')
        engine_id = str(self.engine.currentData() or '')
        if engine_id in ('qwen3-tts-purec-mixed', 'qwen3-tts-purec-int8') and len(selected_profiles) > 1:
            notes.append(
                'Atenção: o Pure C fixa uma voz clonada por servidor. Ao trocar entre perfis '
                'diferentes, o Qwen reinicia e recarrega o modelo em cada lote de voz.')
        elif engine_id in ('qwen3-tts-native-q4', 'qwen3-tts-native-q4-balanced') and len(selected_profiles) > 1:
            notes.append(
                'Qwen Turbo Q4 mantém um único worker/modelo carregado e recebe o embedding '
                'de cada personagem por fala. Perfis ainda não preparados podem exigir '
                'preparação vocal inicial; os embeddings ficam em cache local.')
        elif engine_id == 'qwen3-tts-local' and len(selected_profiles) > 1:
            notes.append(
                'Original mantém um único Qwen carregado e reutiliza o condicionamento de cada '
                'perfil durante a sessão. A geração pode ser mais lenta que nos perfis Pure C.')
        elif engine_id in ('qwen3-tts-purec-mixed', 'qwen3-tts-purec-int8'):
            notes.append(
                'Pure C agrupa as falas pelo perfil e mantém o servidor aquecido enquanto usa '
                'a mesma voz. Perfis clonados diferentes exigem recarga entre lotes.')
        self.engine_note.setText('\n'.join(notes))

    def import_script(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Importar Berofel Script', '', 'Roteiros (*.txt *.bfs-script);;Todos os arquivos (*)')
        if not path:
            return
        try:
            text = Path(path).read_text(encoding='utf-8-sig')
        except (OSError, UnicodeError) as exc:
            QMessageBox.warning(self, 'Importar roteiro', str(exc))
            return
        self.script_text.setPlainText(text)
        self.preview_script()

    def preview_script(self):
        try:
            lines = parse_berofel_script(self.script_text.toPlainText())
        except ScriptValidationError as exc:
            self.summary.setText(str(exc))
            self.lines.setRowCount(0)
            return
        self.lines.setRowCount(len(lines))
        voice_totals: dict[str, int] = {}
        for row, line in enumerate(sorted(lines, key=lambda item: item.number)):
            voice_totals[line.voice_id] = voice_totals.get(line.voice_id, 0) + 1
            for col, value in enumerate((f'{line.number:03d}',
                                         line.character_name or line.voice_id,
                                         line.text, 'Pendente')):
                self.lines.setItem(row, col, QTableWidgetItem(value))
        self.summary.setText(f'{len(lines)} falas · {len(voice_totals)} personagem(ns) · '
                             + ' · '.join(f'{voice}: {count}' for voice, count in
                                          sorted(voice_totals.items(), key=lambda item: int(item[0][1:]))))

    def build_script(self, title: str = 'Roteiro multivozes', timeline_start: float = 0.0):
        assignments = {}
        for voice_id, combo in self.assignments.items():
            profile_id = combo.currentData()
            if not profile_id:
                continue
            profile = self.voice_profiles.get(profile_id)
            assignments[voice_id] = {'profile_id': profile_id, 'display_name': profile['name']}
        return create_script(self.script_text.toPlainText(), assignments,
                             str(self.engine.currentData()), title=title,
                             pause_ms=self.pause.value(), timeline_start=timeline_start)

    def generate(self):
        try:
            script = self.build_script()
        except (ScriptValidationError, OSError, ValueError, KeyError) as exc:
            self.summary.setText(str(exc))
            return
        self.set_active_script(script)
        if self.on_generate:
            self.on_generate(script)

    def set_busy(self, busy: bool):
        self.generate_button.setDisabled(busy)
        self.validate_button.setDisabled(busy)
        self.import_button.setDisabled(busy)
        self.lines.setDisabled(busy)
        for button in (self.add_line_button, self.remove_line_button,
                       self.move_up_button, self.move_down_button):
            button.setDisabled(busy or self.active_script is None)
        self.regenerate_line.setDisabled(busy or self.active_script is None)
        self.resume_button.setDisabled(busy or self.active_script is None)
        self.export_script_button.setDisabled(busy or not self._script_audio_complete())

    def resume_script(self):
        if self.active_script and self.on_generate:
            self.on_generate(self.active_script)

    def _selected_row(self):
        rows = self.lines.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def _commit_script_structure(self, selected_id=''):
        script = self.active_script
        if script is None:
            return
        for row in range(self.lines.rowCount()):
            text_item = self.lines.item(row, 2)
            if text_item is None:
                continue
            line_id = text_item.data(Qt.ItemDataRole.UserRole)
            line = next((entry for entry in script.lines if entry.id == line_id), None)
            text = text_item.text().strip()
            if line and text != line.text:
                if text:
                    line.text = text
                    line.status = 'pending'
                    line.error = ''
        if self.on_script_changed:
            self.on_script_changed(script)
        self.set_active_script(script, selected_id)

    def change_line_voice(self, line_id: str, voice_id: str):
        if not self.active_script:
            return
        self._capture_edited_texts()
        line = next((entry for entry in self.active_script.lines if entry.id == line_id), None)
        if line is None or voice_id not in self.active_script.voices or line.voice_id == voice_id:
            return
        line.voice_id = voice_id
        line.status = 'pending'
        line.error = ''
        if self.on_script_changed:
            self.on_script_changed(self.active_script)
        self._ensure_ptbr_engine()
        self._update_engine_note()

    def _capture_edited_texts(self):
        if not self.active_script:
            return
        for row in range(self.lines.rowCount()):
            item = self.lines.item(row, 2)
            if item is None:
                continue
            line_id = item.data(Qt.ItemDataRole.UserRole)
            line = next((entry for entry in self.active_script.lines if entry.id == line_id), None)
            text = item.text().strip()
            if line and text and text != line.text:
                line.text = text
                line.status = 'pending'
                line.error = ''

    def add_dialogue_line(self):
        if not self.active_script:
            return
        voices = sorted(self.active_script.voices, key=lambda item: int(item[1:]))
        if not voices:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Adicionar fala')
        layout = QVBoxLayout(dialog)
        voice = QComboBox(dialog)
        for voice_id in voices:
            voice_name = self.active_script.voices[voice_id].get('display_name') or voice_id
            voice.addItem(f'{voice_id} · {voice_name}', voice_id)
        layout.addWidget(voice)
        text = QTextEdit(dialog)
        text.setPlaceholderText('Texto da nova fala')
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel, parent=dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        spoken = text.toPlainText().strip()
        if not spoken:
            self.status.setText('Digite o texto da nova fala.')
            return
        line = DialogueLine(id=new_id(), number=len(self.active_script.lines)+1,
                            voice_id=str(voice.currentData()), text=spoken)
        row = self._selected_row()
        at = row + 1 if row >= 0 else len(self.active_script.lines)
        self.active_script.lines.insert(at, line)
        reorder_lines(self.active_script, [entry.id for entry in self.active_script.lines])
        self._commit_script_structure(line.id)

    def remove_dialogue_line(self):
        if not self.active_script:
            return
        row = self._selected_row()
        if row < 0:
            return
        item = self.lines.item(row, 2)
        line_id = item.data(Qt.ItemDataRole.UserRole) if item else ''
        self.active_script.lines = [line for line in self.active_script.lines if line.id != line_id]
        if not self.active_script.lines:
            empty_script = self.active_script
            if self.on_script_changed:
                self.on_script_changed(empty_script)
            self.active_script = None
            self.lines.setRowCount(0)
            self.regenerate_line.setEnabled(False)
            self.play_line.setEnabled(False)
            self.resume_button.setEnabled(False)
            return
        reorder_lines(self.active_script, [entry.id for entry in self.active_script.lines])
        self._commit_script_structure()

    def move_dialogue_line(self, direction: int):
        if not self.active_script:
            return
        row = self._selected_row()
        target = row + int(direction)
        if row < 0 or not 0 <= target < self.lines.rowCount():
            return
        ids = [entry.id for entry in sorted(self.active_script.lines,
                                             key=lambda item: item.number)]
        ids[row], ids[target] = ids[target], ids[row]
        reorder_lines(self.active_script, ids)
        self._commit_script_structure(ids[target])

    def set_active_script(self, script, selected_line_id: str = ''):
        self.active_script = script
        self.lines.setRowCount(len(script.lines))
        for row, line in enumerate(sorted(script.lines, key=lambda item: item.number)):
            status = (f'Pronta · {line.duration:.2f}s' if line.status == 'generated'
                      else 'Pendente · áudio anterior mantido' if line.audio_path
                      else line.status.title())
            values = (f'{line.number:03d}', line.character_name or line.voice_id,
                      line.text, status)
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if col == 2:
                    cell.setData(Qt.ItemDataRole.UserRole, line.id)
                elif col != 1:
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.lines.setItem(row, col, cell)
            voice_combo = QComboBox(self.lines)
            for voice_id in sorted(script.voices, key=lambda item: int(item[1:])):
                voice_name = script.voices[voice_id].get('display_name') or voice_id
                voice_combo.addItem(f'{voice_id} · {voice_name}', voice_id)
            selected_voice = voice_combo.findData(line.voice_id)
            if selected_voice >= 0:
                voice_combo.setCurrentIndex(selected_voice)
            voice_combo.currentIndexChanged.connect(
                lambda _index, lid=line.id, combo=voice_combo:
                    self.change_line_voice(lid, str(combo.currentData())))
            self.lines.setCellWidget(row, 1, voice_combo)
            if line.id == selected_line_id:
                self.lines.selectRow(row)
        self.regenerate_line.setEnabled(True)
        self.play_line.setEnabled(any(line.audio_path for line in script.lines))
        can_resume = not script.track_id
        self.resume_button.setEnabled(can_resume)
        self.export_script_button.setEnabled(self._script_audio_complete())
        self._selection_state()
        self._ensure_ptbr_engine()
        self._update_engine_note()
        for button in (self.add_line_button, self.remove_line_button,
                       self.move_up_button, self.move_down_button):
            button.setEnabled(True)
        self.summary.setText(f'{len(script.lines)} falas · roteiro {script.id[:8]} · '
                             f'{script.engine_id}')

    def restore_project_scripts(self, scripts, project_path: str):
        from berofel.services.multivoice_narration import load_script_checkpoint, MultiVoiceScript
        for data in reversed(list(scripts or [])):
            try:
                script = MultiVoiceScript.from_dict(data)
                checkpoint = (load_script_checkpoint(project_path, script.id,
                                                     expected_script=script)
                              if project_path else None)
                self.set_active_script(checkpoint or script)
                return
            except (OSError, ValueError, TypeError, KeyError):
                continue

    def select_line(self, line_id: str):
        for row in range(self.lines.rowCount()):
            item = self.lines.item(row, 2)
            if item and item.data(Qt.ItemDataRole.UserRole) == line_id:
                self.lines.selectRow(row)
                return

    def _selected_line(self):
        if not self.active_script or not self.lines.selectionModel().selectedRows():
            return None, ''
        row = self.lines.selectionModel().selectedRows()[0].row()
        item = self.lines.item(row, 2)
        line_id = item.data(Qt.ItemDataRole.UserRole) if item else ''
        line = next((entry for entry in self.active_script.lines if entry.id == line_id), None)
        return line, item.text() if item else ''

    def _selection_state(self):
        line, _text = self._selected_line() if self.active_script else (None, '')
        available = bool(line and line.audio_path and Path(line.audio_path).is_file())
        self.play_line.setEnabled(available)
        self.save_line.setEnabled(available)

    def _script_audio_complete(self):
        return bool(self.active_script and self.active_script.lines and
                    all(line.status == 'generated' and line.audio_path and
                        Path(line.audio_path).is_file() for line in self.active_script.lines))

    def regenerate_selected_line(self):
        line, text = self._selected_line()
        if line is None:
            self.status.setText('Selecione uma fala gerada na lista ou na timeline.')
            return
        if not text.strip():
            self.status.setText('A fala não pode ficar vazia.')
            return
        if self.on_regenerate:
            self.on_regenerate(self.active_script, line.id, text)

    def play_selected_line(self):
        line, _text = self._selected_line()
        if line and line.audio_path and Path(line.audio_path).is_file():
            from PySide6.QtCore import QUrl
            from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
            if not hasattr(self, '_line_player'):
                self._line_player = QMediaPlayer(self)
                self._line_audio = QAudioOutput(self)
                self._line_player.setAudioOutput(self._line_audio)
            self._line_player.stop()
            self._line_player.setSource(QUrl.fromLocalFile(line.audio_path))
            self._line_player.play()

    def save_selected_wav(self):
        line, _text = self._selected_line()
        if not line or not line.audio_path or not Path(line.audio_path).is_file():
            return
        target, _ = QFileDialog.getSaveFileName(
            self, 'Salvar WAV da fala', f'{line.number:03d}_{line.voice_id}.wav', 'WAV (*.wav)')
        if not target:
            return
        if not target.lower().endswith('.wav'):
            target += '.wav'
        try:
            shutil.copy2(line.audio_path, target)
            self.status.setText(f'WAV da fala {line.number:03d} salvo: {target}')
        except OSError as exc:
            QMessageBox.warning(self, 'Salvar fala', str(exc))

    def show_progress(self, done: int, total: int, stage: str = ''):
        self.status.setText(f'{stage} · {done}/{total} falas concluídas' if stage else
                            f'{done}/{total} falas concluídas')

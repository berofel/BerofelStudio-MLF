"""Painel fixo de narração do BerofelStudio: sempre acessível à direita."""
from __future__ import annotations
import os
from pathlib import Path
import subprocess

from PySide6.QtCore import QUrl, QTimer, QSettings, Qt
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QTextEdit,
                               QPushButton, QCheckBox, QFileDialog, QLineEdit, QHBoxLayout,
                               QMessageBox, QScrollArea, QInputDialog,
                               QGroupBox)
from .wheel_controls import (WheelGuardComboBox as QComboBox,
    WheelGuardDoubleSpinBox as QDoubleSpinBox, WheelGuardSlider as QSlider)

from berofel.services.pocket_tts_service import LANGUAGES, VOICE_PRESETS, NarrationRequest, preset_voice
from berofel.services.voice_dsp import VOICE_EQ_PRESETS, clip_voice_eq
from berofel.services.voice_presets import VoicePresetManager


class NarrationPanel(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.on_generate = None
        self.on_use_transcript = None
        self.last_audio = ''
        self.setWidgetResizable(True)
        self.setVerticalScrollBarPolicy(self.verticalScrollBarPolicy())
        self.setHorizontalScrollBarPolicy(self.horizontalScrollBarPolicy())
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(9)
        label = QLabel('🎙 NARRAÇÃO · VOZ LOCAL')
        label.setStyleSheet('color:#9cc7ff;font-weight:800;font-size:13px;')
        layout.addWidget(label)
        note = QLabel('Escreva qualquer texto — não precisa existir na transcrição. '
                      'A voz é gerada localmente e o WAV pode entrar em qualquer camada.')
        note.setWordWrap(True)
        layout.addWidget(note)

        layout.addWidget(QLabel('Texto para narrar'))
        self.text = QTextEdit()
        self.text.setPlaceholderText('Digite sua narração, um roteiro, uma correção de fala...')
        self.text.setMinimumHeight(145)
        layout.addWidget(self.text)
        fill = QPushButton('↳ Trazer transcrição dos blocos selecionados')
        fill.clicked.connect(lambda: self.on_use_transcript() if self.on_use_transcript else None)
        layout.addWidget(fill)

        layout.addWidget(QLabel('Idioma da narração'))
        self.language = QComboBox()
        for name, code in LANGUAGES:
            self.language.addItem(name, code)
        layout.addWidget(self.language)

        layout.addWidget(QLabel('Voz (catálogo ou clonagem autorizada)'))
        self.voice = QComboBox()
        self.voice.addItem('Rafael · voz oficial em português', 'rafael')
        for preset in VOICE_PRESETS:
            self.voice.addItem(preset['name'], preset['id'])
        self.voice.addItem('Minha voz / amostra com autorização', '__custom__')
        self.voice.currentIndexChanged.connect(self._update_custom)
        layout.addWidget(self.voice)

        self.sample_path = QLineEdit()
        self.sample_path.setPlaceholderText('Selecione uma amostra de voz autorizada...')
        self.sample_path.setReadOnly(True)
        layout.addWidget(self.sample_path)
        choose = QPushButton('📁 Escolher amostra (WAV, MP3, FLAC...)')
        choose.clicked.connect(self._choose_sample)
        layout.addWidget(choose)
        self.choose_sample = choose
        self.authorized = QCheckBox('Confirmo autorização expressa para clonar esta voz.')
        layout.addWidget(self.authorized)
        self.activate_cloning = QPushButton('🔐 Preparar clonagem local…')
        self.activate_cloning.clicked.connect(self._activate_cloning)
        layout.addWidget(self.activate_cloning)
        layout.addWidget(QLabel('Motor para voz personalizada'))
        self.clone_engine = QComboBox()
        self.clone_engine.addItem('Qwen3-TTS local · CPU · baixar uma vez', 'qwen3-tts-local')
        self.clone_engine.addItem('Pocket TTS · precisa de pesos autorizados', 'pocket-tts')
        self.clone_engine.currentIndexChanged.connect(self._update_custom)
        layout.addWidget(self.clone_engine)
        self.reference_text = QLineEdit()
        self.reference_text.setPlaceholderText('Texto falado na amostra (melhora a clonagem Qwen)')
        layout.addWidget(self.reference_text)
        self.install_qwen = QPushButton('⬇ Preparar Qwen3 local (download explícito)')
        self.install_qwen.clicked.connect(self._install_qwen)
        layout.addWidget(self.install_qwen)
        self.qwen_status = QLabel('')
        self.qwen_status.setWordWrap(True)
        self.qwen_status.setStyleSheet('color:#8b9db3;font-size:11px;')
        layout.addWidget(self.qwen_status)
        self.clone_status = QLabel('')
        self.clone_status.setWordWrap(True)
        self.clone_status.setStyleSheet('color:#8b9db3;font-size:11px;')
        self.clone_status.setObjectName('voiceCloneStatus')
        layout.addWidget(self.clone_status)
        self._clone_activation_process = None
        self._clone_watch_timer = QTimer(self)
        self._clone_watch_timer.setInterval(500)
        self._clone_watch_timer.timeout.connect(self._poll_clone_activation)
        self.license_note = QLabel('Voz oficial Kyutai. Para redistribuição/licenças, consulte os termos do modelo.')
        self.license_note.setWordWrap(True)
        self.license_note.setStyleSheet('color:#8b9db3;font-size:11px;')
        self.license_note.setOpenExternalLinks(True)
        layout.addWidget(self.license_note)

        eq_title=QLabel('Ajuste Fino da Voz · EQ')
        eq_title.setStyleSheet('color:#ff9c42;font-weight:800;font-size:13px;')
        layout.addWidget(eq_title)
        self.eq_status=QLabel('Selecione um clipe de áudio ou vídeo com áudio na timeline.')
        self.eq_status.setWordWrap(True)
        layout.addWidget(self.eq_status)
        self.eq_preset=QComboBox()
        self.voice_presets=VoicePresetManager()
        self._custom_voice_presets=set()
        self._refresh_voice_presets()
        self.eq_preset.addItem('Personalizado')
        layout.addWidget(self.eq_preset)
        preset_actions=QHBoxLayout()
        self.save_voice_preset=QPushButton('Salvar preset')
        self.rename_voice_preset=QPushButton('Renomear')
        self.delete_voice_preset=QPushButton('Excluir')
        self.save_voice_preset.clicked.connect(self._save_voice_preset)
        self.rename_voice_preset.clicked.connect(self._rename_voice_preset)
        self.delete_voice_preset.clicked.connect(self._delete_voice_preset)
        preset_actions.addWidget(self.save_voice_preset)
        preset_actions.addWidget(self.rename_voice_preset)
        preset_actions.addWidget(self.delete_voice_preset)
        layout.addLayout(preset_actions)
        self.eq_sliders={};self.eq_readouts={}
        for key,label in (('bass_db','Graves'),('mids_db','Médios'),('treble_db','Agudos')):
            row=QWidget();row_layout=QHBoxLayout(row)
            row_layout.setContentsMargins(0,0,0,0);row_layout.setSpacing(4)
            name=QLabel(label);name.setMinimumWidth(48)
            slider=QSlider(Qt.Orientation.Horizontal);slider.setRange(-120,120);slider.setPageStep(10)
            value=QDoubleSpinBox();value.setRange(-12.,12.);value.setDecimals(1)
            value.setSingleStep(.1);value.setSuffix(' dB');value.setFixedWidth(78)
            reset=QPushButton('↺');reset.setFixedWidth(30);reset.setToolTip(f'Restaurar {label.lower()} para 0 dB')
            reset.clicked.connect(lambda _checked=False,k=key:self._reset_eq_band(k))
            slider.valueChanged.connect(lambda number,k=key,out=value:self._show_eq_value(k,number,out))
            value.valueChanged.connect(lambda number,target=slider:target.setValue(round(number*10)))
            slider.sliderPressed.connect(self._start_eq_drag)
            slider.sliderReleased.connect(self._finish_eq_drag)
            row_layout.addWidget(name);row_layout.addWidget(slider,1);row_layout.addWidget(value);row_layout.addWidget(reset)
            layout.addWidget(row)
            self.eq_sliders[key]=slider;self.eq_readouts[key]=value
        pitch_row=QWidget();pitch_layout=QHBoxLayout(pitch_row)
        pitch_layout.setContentsMargins(0,0,0,0);pitch_layout.setSpacing(4)
        pitch_layout.addWidget(QLabel('Pitch'))
        self.pitch_slider=QSlider(Qt.Orientation.Horizontal)
        self.pitch_slider.setRange(-40,40);self.pitch_slider.setPageStep(10)
        self.pitch_readout=QDoubleSpinBox();self.pitch_readout.setRange(-4.,4.)
        self.pitch_readout.setDecimals(1);self.pitch_readout.setSingleStep(.1)
        self.pitch_readout.setSuffix(' st');self.pitch_readout.setFixedWidth(78)
        self.pitch_reset=QPushButton('↺');self.pitch_reset.setFixedWidth(30)
        self.pitch_reset.setToolTip('Restaurar pitch para 0 semitons')
        self.pitch_reset.clicked.connect(self._reset_pitch)
        self.pitch_slider.valueChanged.connect(self._show_pitch_value)
        self.pitch_slider.sliderPressed.connect(self._start_eq_drag)
        self.pitch_slider.sliderReleased.connect(self._finish_eq_drag)
        self.pitch_readout.valueChanged.connect(lambda value:self.pitch_slider.setValue(round(value*10)))
        pitch_layout.addWidget(self.pitch_slider,1)
        pitch_layout.addWidget(self.pitch_readout)
        pitch_layout.addWidget(self.pitch_reset)
        layout.addWidget(pitch_row)
        self.formant_group=QGroupBox('Ressonância Vocal · indisponível')
        self.formant_group.setObjectName('voiceFormantUnavailable')
        formant_layout=QVBoxLayout(self.formant_group)
        self.formant_explanation=QLabel(
            'O FFmpeg instalado só oferece formantes preservados ou deslocados junto com o pitch. '
            'Não há ajuste independente de ressonância nesta versão.')
        self.formant_explanation.setWordWrap(True)
        self.formant_explanation.setToolTip(self.formant_explanation.text())
        formant_layout.addWidget(self.formant_explanation)
        self.formant_group.setEnabled(False)
        layout.addWidget(self.formant_group)
        speed_row=QWidget();speed_layout=QHBoxLayout(speed_row)
        speed_layout.setContentsMargins(0,0,0,0);speed_layout.setSpacing(4)
        speed_layout.addWidget(QLabel('Velocidade'))
        self.speed_slider=QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(70,130);self.speed_slider.setSingleStep(5);self.speed_slider.setPageStep(5)
        self.speed_readout=QDoubleSpinBox();self.speed_readout.setRange(.70,1.30)
        self.speed_readout.setDecimals(2);self.speed_readout.setSingleStep(.05)
        self.speed_readout.setSuffix('×');self.speed_readout.setFixedWidth(78)
        speed_layout.addWidget(self.speed_slider,1);speed_layout.addWidget(self.speed_readout)
        layout.addWidget(speed_row)
        self.speed_status=QLabel('A velocidade recalcula a duração deste clipe e segue o Undo da timeline.')
        self.speed_status.setWordWrap(True);self.speed_status.setStyleSheet('color:#8b9db3;font-size:11px;')
        layout.addWidget(self.speed_status)
        self.speed_slider.valueChanged.connect(self._show_speed_value)
        self.speed_slider.sliderReleased.connect(self._commit_speed)
        self.speed_readout.valueChanged.connect(lambda value:self.speed_slider.setValue(round(value*100)))
        self.speed_readout.editingFinished.connect(self._commit_speed)
        self.eq_bypass=QCheckBox('Bypass · comparar EQ + pitch')
        self.eq_bypass.toggled.connect(self._toggle_eq_bypass)
        layout.addWidget(self.eq_bypass)
        self.eq_reset=QPushButton('Restaurar todas as bandas')
        self.eq_reset.clicked.connect(self._reset_eq)
        layout.addWidget(self.eq_reset)
        voice_actions=QHBoxLayout()
        self.copy_voice_adjustments=QPushButton('Copiar ajustes')
        self.paste_voice_adjustments=QPushButton('Colar ajustes')
        self.copy_voice_adjustments.clicked.connect(
            lambda:self.on_copy_voice_adjustments(self._eq_clip_id)
            if self.on_copy_voice_adjustments and self._eq_clip_id else None)
        self.paste_voice_adjustments.clicked.connect(
            lambda:self.on_paste_voice_adjustments(self._eq_clip_id)
            if self.on_paste_voice_adjustments and self._eq_clip_id else None)
        voice_actions.addWidget(self.copy_voice_adjustments)
        voice_actions.addWidget(self.paste_voice_adjustments)
        layout.addLayout(voice_actions)
        self.eq_help=QLabel('EQ e pitch não repetem o TTS. Pitch de -4 a +4 semitons preserva aproximadamente a duração; prévia e exportação usam o mesmo processamento.')
        self.eq_help.setWordWrap(True)
        self.eq_help.setStyleSheet('color:#8b9db3;font-size:11px;')
        layout.addWidget(self.eq_help)

        self.quantize = QCheckBox('Economizar memória (quantização INT8)')
        self.quantize.setChecked(False)
        layout.addWidget(self.quantize)
        self.name = QLineEdit('Narração')
        layout.addWidget(QLabel('Nome do clipe gerado'))
        layout.addWidget(self.name)
        self.insert = QPushButton('▶ Gerar e adicionar na timeline')
        self.insert.clicked.connect(lambda: self._generate(True))
        layout.addWidget(self.insert)
        self.generate_file = QPushButton('♬ Gerar só o WAV')
        self.generate_file.clicked.connect(lambda: self._generate(False))
        layout.addWidget(self.generate_file)
        self.listen = QPushButton('♫ Ouvir última narração')
        self.listen.setEnabled(False)
        self.listen.clicked.connect(self._listen)
        layout.addWidget(self.listen)
        self.status = QLabel('O modelo é carregado apenas durante a geração (Batata Quente).')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch()
        self.setWidget(page)
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._audio.setVolume(0.85)
        self.on_voice_eq_begin=None
        self.on_voice_eq_change=None
        self.on_voice_speed_change=None
        self.on_copy_voice_adjustments=None
        self.on_paste_voice_adjustments=None
        self._eq_clip_id='';self._eq_editable=False;self._updating_eq=False
        self._eq_transaction=False;self._eq_dragging=False
        self._eq_timer=QTimer(self);self._eq_timer.setSingleShot(True);self._eq_timer.setInterval(180)
        self._eq_timer.timeout.connect(self._commit_eq)
        self.eq_preset.currentTextChanged.connect(self._apply_eq_preset)
        self._settings=QSettings(QSettings.Format.IniFormat,QSettings.Scope.UserScope,
                                 'Berofel','BerofelStudio')
        self._restore_preferences()
        self._preferences_timer=QTimer(self)
        self._preferences_timer.setSingleShot(True)
        self._preferences_timer.setInterval(450)
        self._preferences_timer.timeout.connect(self.save_preferences)
        self.text.textChanged.connect(self._schedule_preferences_save)
        self.language.currentIndexChanged.connect(self._schedule_preferences_save)
        self.voice.currentIndexChanged.connect(self._schedule_preferences_save)
        self.sample_path.textChanged.connect(self._schedule_preferences_save)
        self.clone_engine.currentIndexChanged.connect(self._schedule_preferences_save)
        self.reference_text.textChanged.connect(self._schedule_preferences_save)
        from berofel.services.qwen3_tts_local import is_ready as qwen_local_ready
        if qwen_local_ready():
            self.qwen_status.setText('Qwen3-TTS local pronto. As referências e gerações ficam no PC.')
        self.quantize.toggled.connect(self._schedule_preferences_save)
        self.name.textChanged.connect(self._schedule_preferences_save)
        self._update_custom()
        self.set_clip(None)

    def set_clip(self,clip,editable=True):
        """Load per-clip DSP values without triggering a write or TTS call."""
        self._eq_timer.stop()
        self._eq_transaction=False;self._eq_dragging=False
        usable=bool(clip and clip.kind in ('audio','video') and clip.include_audio)
        self._eq_clip_id=clip.id if usable else ''
        self._eq_editable=bool(usable and editable)
        self._updating_eq=True
        try:
            eq=clip_voice_eq(clip) if usable else clip_voice_eq(None)
            for key,slider in self.eq_sliders.items():
                value=round(getattr(eq,key)*10)
                slider.setValue(value)
                self.eq_readouts[key].setValue(value/10)
                slider.setEnabled(self._eq_editable)
                self.eq_readouts[key].setEnabled(self._eq_editable)
            self.eq_bypass.setChecked(eq.bypass)
            self.eq_bypass.setEnabled(self._eq_editable)
            preset=(clip.voice_dsp_preset if usable else 'Natural')
            index=self.eq_preset.findText(preset)
            self.eq_preset.setCurrentIndex(index if index>=0 else 0)
            self.eq_preset.setEnabled(self._eq_editable)
            self.save_voice_preset.setEnabled(self._eq_editable)
            custom=(preset in self._custom_voice_presets)
            self.rename_voice_preset.setEnabled(self._eq_editable and custom)
            self.delete_voice_preset.setEnabled(self._eq_editable and custom)
            self.eq_reset.setEnabled(self._eq_editable)
            self.copy_voice_adjustments.setEnabled(self._eq_editable)
            self.paste_voice_adjustments.setEnabled(self._eq_editable)
            pitch=round(float(clip.voice_pitch_semitones),1) if usable else 0.
            self.pitch_slider.setValue(round(pitch*10))
            self.pitch_readout.setValue(pitch)
            self.pitch_slider.setEnabled(self._eq_editable)
            self.pitch_readout.setEnabled(self._eq_editable)
            self.pitch_reset.setEnabled(self._eq_editable)
            clip_speed=float(clip.speed) if usable else 1.
            speed_in_range=.70<=clip_speed<=1.30
            shown_speed=min(1.30,max(.70,clip_speed))
            self.speed_slider.setValue(round(shown_speed*100))
            self.speed_readout.setValue(shown_speed)
            speed_enabled=bool(self._eq_editable and speed_in_range)
            self.speed_slider.setEnabled(speed_enabled)
            self.speed_readout.setEnabled(speed_enabled)
            self.speed_status.setText(
                'Velocidade altera apenas este clipe, preserva o pitch quando Rubber Band está disponível, atualiza a duração e não repete o TTS.'
                if speed_in_range else
                f'Este clipe está em {clip_speed:g}×; ajuste a velocidade em Propriedades para entrar no intervalo 0,70×–1,30×.')
            if not usable:
                message='Selecione um clipe de áudio ou vídeo com áudio na timeline.'
            elif not editable:
                message='A faixa está bloqueada. Desbloqueie-a para editar o EQ.'
            else:
                message=f'Clipping protegido · {clip.title or "Narração"} · EQ salvo no projeto.'
            self.eq_status.setText(message)
        finally:
            self._updating_eq=False

    def _show_eq_value(self,key,value,label):
        label.blockSignals(True);label.setValue(int(value)/10);label.blockSignals(False)
        if self._updating_eq or not self._eq_clip_id:return
        self.eq_preset.blockSignals(True)
        self.eq_preset.setCurrentText('Personalizado')
        self.eq_preset.blockSignals(False)
        self._begin_eq_transaction()
        if not self._eq_dragging:self._eq_timer.start()

    def _begin_eq_transaction(self):
        if self._eq_transaction:return
        if self.on_voice_eq_begin:self.on_voice_eq_begin(self._eq_clip_id)
        self._eq_transaction=True

    def _show_pitch_value(self,value):
        self.pitch_readout.blockSignals(True)
        self.pitch_readout.setValue(int(value)/10)
        self.pitch_readout.blockSignals(False)
        if self._updating_eq or not self._eq_clip_id:return
        self._begin_eq_transaction()
        if not self._eq_dragging:self._eq_timer.start()

    def _show_speed_value(self,value):
        snapped=max(70,min(130,int(round(value/5)*5)))
        if self.speed_slider.value()!=snapped:
            self.speed_slider.setValue(snapped)
            return
        self.speed_readout.blockSignals(True)
        self.speed_readout.setValue(snapped/100)
        self.speed_readout.blockSignals(False)

    def _commit_speed(self):
        if (not self._eq_clip_id or not self._eq_editable or
                not self.speed_slider.isEnabled()):return
        if self.on_voice_speed_change:
            self.on_voice_speed_change(self._eq_clip_id,self.speed_slider.value()/100)

    def _start_eq_drag(self):
        if not self._eq_clip_id or not self._eq_editable:return
        self._eq_dragging=True
        self._begin_eq_transaction()

    def _finish_eq_drag(self):
        self._eq_dragging=False
        self._commit_eq()

    def _eq_values(self):
        values={key:slider.value()/10 for key,slider in self.eq_sliders.items()}
        values['pitch_semitones']=self.pitch_slider.value()/10
        return values

    def _commit_eq(self):
        self._eq_timer.stop()
        if self._updating_eq or not self._eq_clip_id or not self._eq_editable:return
        if not self._eq_transaction:return
        if self.on_voice_eq_change:
            self.on_voice_eq_change(self._eq_clip_id,self._eq_values(),
                                    self.eq_bypass.isChecked(),self.eq_preset.currentText())
        if not self._eq_dragging:self._eq_transaction=False

    def _reset_eq_band(self,key):
        slider=self.eq_sliders[key]
        if slider.value()==0:return
        slider.setValue(0)
        self._commit_eq()

    def _reset_eq(self):
        target=VOICE_EQ_PRESETS['Natural']
        current=tuple(self.eq_sliders[key].value()/10 for key in ('bass_db','mids_db','treble_db'))
        if current==target and not self.eq_bypass.isChecked() and self.eq_preset.currentText()=='Natural':return
        self._begin_eq_transaction()
        self._updating_eq=True
        try:
            for slider in self.eq_sliders.values():slider.setValue(0)
            self.eq_bypass.setChecked(False)
            self.eq_preset.setCurrentText('Natural')
        finally:self._updating_eq=False
        self._commit_eq()

    def _reset_pitch(self):
        if self.pitch_slider.value()==0:return
        self.pitch_slider.setValue(0)
        self._commit_eq()

    def _toggle_eq_bypass(self,_enabled):
        if self._updating_eq or not self._eq_clip_id:return
        self._begin_eq_transaction()
        self._commit_eq()

    def _apply_eq_preset(self,name):
        if self._updating_eq or not self._eq_clip_id:return
        preset=VOICE_EQ_PRESETS.get(name)
        pitch=None
        if preset is None and name in self._custom_voice_presets:
            try:
                values=self.voice_presets.get(name)
                preset=tuple(values[key] for key in ('bass_db','mids_db','treble_db'))
                pitch=values['pitch_semitones']
            except (KeyError,ValueError) as exc:
                QMessageBox.warning(self,'Preset de voz',str(exc));return
        if preset is None:return
        self._updating_eq=True
        try:
            for key,value in zip(('bass_db','mids_db','treble_db'),preset):
                self.eq_sliders[key].setValue(round(value*10))
            if pitch is not None:self.pitch_slider.setValue(round(pitch*10))
            self.eq_bypass.setChecked(False)
        finally:self._updating_eq=False
        self._begin_eq_transaction()
        self._commit_eq()

    def _refresh_voice_presets(self,select=None):
        try:
            self._custom_voice_presets=set(self.voice_presets.names())
        except ValueError as exc:
            self._custom_voice_presets=set()
            if hasattr(self,'status'):self.status.setText(str(exc))
        self.eq_preset.blockSignals(True)
        self.eq_preset.clear()
        self.eq_preset.addItems([*VOICE_EQ_PRESETS,*sorted(self._custom_voice_presets,key=str.casefold)])
        self.eq_preset.addItem('Personalizado')
        if select:
            index=self.eq_preset.findText(select)
            if index>=0:self.eq_preset.setCurrentIndex(index)
        self.eq_preset.blockSignals(False)

    def _voice_preset_values(self):
        return {key:slider.value()/10 for key,slider in self.eq_sliders.items()} | {
            'pitch_semitones':self.pitch_slider.value()/10}

    def _save_voice_preset(self):
        name,ok=QInputDialog.getText(self,'Salvar preset de voz','Nome do preset:')
        if not ok:return
        try:
            self.voice_presets.save(name,self._voice_preset_values())
            clean=' '.join(name.strip().split())
            self._refresh_voice_presets(clean)
            self.status.setText(f'Preset “{clean}” salvo localmente.')
        except (OSError,ValueError) as exc:
            QMessageBox.warning(self,'Preset de voz',str(exc))

    def _rename_voice_preset(self):
        old=self.eq_preset.currentText()
        if old not in self._custom_voice_presets:return
        name,ok=QInputDialog.getText(self,'Renomear preset','Novo nome:',text=old)
        if not ok:return
        try:
            clean=self.voice_presets.rename(old,name)
            self._refresh_voice_presets(clean)
        except (OSError,ValueError,KeyError) as exc:
            QMessageBox.warning(self,'Preset de voz',str(exc))

    def _delete_voice_preset(self):
        name=self.eq_preset.currentText()
        if name not in self._custom_voice_presets:return
        try:
            self.voice_presets.delete(name)
            self._refresh_voice_presets('Natural')
        except (OSError,ValueError,KeyError) as exc:
            QMessageBox.warning(self,'Preset de voz',str(exc))

    def _restore_preferences(self):
        settings=self._settings
        voice=str(settings.value('narration/voice','rafael'))
        voice_index=self.voice.findData(voice)
        if voice_index>=0:self.voice.setCurrentIndex(voice_index)
        language=str(settings.value('narration/language','portuguese'))
        language_index=self.language.findData(language)
        if language_index>=0:self.language.setCurrentIndex(language_index)
        self.sample_path.setText(str(settings.value('narration/sample_path','')))
        engine=str(settings.value('narration/clone_engine','qwen3-tts-local'))
        index=self.clone_engine.findData(engine)
        if index>=0:self.clone_engine.setCurrentIndex(index)
        self.reference_text.setText(str(settings.value('narration/reference_text','')))
        self.text.setPlainText(str(settings.value('narration/draft','')))
        self.name.setText(str(settings.value('narration/title','Narração')))
        self.quantize.setChecked(bool(settings.value('narration/quantize',False,type=bool)))

    def _schedule_preferences_save(self,*_args):
        self._preferences_timer.start()

    def save_preferences(self):
        settings=self._settings
        settings.setValue('narration/voice',self.voice.currentData() or 'rafael')
        settings.setValue('narration/language',self.language.currentData() or 'portuguese')
        settings.setValue('narration/sample_path',self.sample_path.text())
        settings.setValue('narration/clone_engine',self.clone_engine.currentData())
        settings.setValue('narration/reference_text',self.reference_text.text())
        settings.setValue('narration/draft',self.text.toPlainText())
        settings.setValue('narration/title',self.name.text())
        settings.setValue('narration/quantize',self.quantize.isChecked())
        settings.sync()

    def closeEvent(self,event):
        self._preferences_timer.stop()
        self.save_preferences()
        super().closeEvent(event)

    def _update_custom(self):
        custom = self.voice.currentData() == '__custom__'
        self.sample_path.setVisible(custom)
        self.choose_sample.setVisible(custom)
        self.authorized.setVisible(custom)
        qwen = custom and self.clone_engine.currentData() == 'qwen3-tts-local'
        pocket_clone = custom and self.clone_engine.currentData() == 'pocket-tts'
        self.activate_cloning.setVisible(pocket_clone)
        self.clone_engine.setVisible(custom)
        self.reference_text.setVisible(qwen)
        self.install_qwen.setVisible(qwen)
        self.qwen_status.setVisible(qwen and bool(self.qwen_status.text()))
        self.quantize.setVisible(not qwen)
        self.clone_status.setVisible(pocket_clone and bool(self.clone_status.text()))
        selected = self.voice.currentData()
        if custom:
            if qwen:
                self.license_note.setText('Qwen3-TTS Base 0.6B: pesos públicos Apache-2.0; preparação baixa o modelo (~2,5 GB) e cria ambiente isolado. Depois, referência e síntese rodam localmente, sem enviar sua gravação. Forneça o texto exato da amostra para melhor resultado; sem ele, o modo só pelo vetor de voz pode reduzir a qualidade. Use somente voz autorizada.')
            else:
                self.license_note.setText(
                    'Pocket TTS: a amostra e a síntese são processadas localmente, mas a clonagem pessoal exige aceitar os termos e obter os pesos oficiais em '
                    '<a href="https://huggingface.co/kyutai/pocket-tts">Hugging Face · Pocket TTS</a>. '
                    'Use AUTORIZAR_POCKET_TTS.bat. Confirme autorização expressa para a voz. Os pesos apenas de catálogo não clonam voz pessoal.')
        elif selected == 'rafael':
            self.license_note.setText('Preset oficial português (Kyutai). A amostra não é redistribuída no ZIP.')
        else:
            self.license_note.setText('Amostra do Voice-Zero disponibilizada como CC0 pela Kyutai. '
                                      'Pronúncia em português pode variar.')

    def _choose_sample(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Escolher amostra autorizada', '',
            'Amostras de voz (*.wav *.mp3 *.flac *.ogg *.m4a *.safetensors);;Todos os arquivos (*)')
        if path:
            self.sample_path.setText(path)

    def _activate_cloning(self):
        app_root=Path(__file__).resolve().parents[2]
        authorizer=app_root/'AUTORIZAR_POCKET_TTS.bat'
        if not authorizer.is_file():
            QMessageBox.warning(self,'Ativar clonagem',
                f'Não encontrei o autorizador do Pocket TTS nesta pasta:\n{authorizer}')
            return
        try:
            env=os.environ.copy()
            log_root=Path(env.get('LOCALAPPDATA',str(Path.home())))/'BFS'/'logs'
            log_root.mkdir(parents=True,exist_ok=True)
            self._clone_activation_log=log_root/'pocket_clone_activation.log'
            self._clone_activation_log.unlink(missing_ok=True)
            env['BFS_CLONE_ACTIVATION_LOG']=str(self._clone_activation_log)
            # O autorizador roda a prova sintética do encoder antes de retornar.
            # Evita manter a janela de console parada em um `pause`, permitindo
            # ao painel apresentar o resultado real sem outra inferência.
            env['BFS_NO_PAUSE']='1'
            self._clone_activation_process=subprocess.Popen(
                ['cmd.exe','/d','/c','call',str(authorizer)],cwd=str(app_root),env=env,
                creationflags=getattr(subprocess,'CREATE_NEW_CONSOLE',0))
            self.activate_cloning.setEnabled(False)
            self._set_clone_status('Conclua o login no console que abriu. O encoder será validado ao final; esta prova usa áudio sintético.')
            self._clone_watch_timer.start()
        except OSError as exc:
            self._clone_activation_process=None
            QMessageBox.warning(self,'Ativar clonagem',
                f'Não foi possível abrir o autorizador. Execute AUTORIZAR_POCKET_TTS.bat manualmente.\n{exc}')

    def _install_qwen(self):
        from berofel.services.qwen3_tts_local import is_ready
        if is_ready():
            self.qwen_status.setText('Qwen3 local pronto. A referência e a síntese permanecem no PC.')
            self.qwen_status.setVisible(True)
            return
        answer=QMessageBox.question(self,'Preparar clonagem local Qwen3',
            'Será criado um ambiente Python isolado e baixados cerca de 2,5 GB de pesos públicos, além das dependências. É necessária internet apenas durante a preparação. A gravação escolhida não será enviada. Continuar?',
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer!=QMessageBox.StandardButton.Yes:return
        app_root=Path(__file__).resolve().parents[2]
        installer=app_root/'INSTALAR_QWEN3_TTS_LOCAL.bat'
        if not installer.is_file():
            QMessageBox.warning(self,'Qwen3 local',f'Instalador ausente: {installer}')
            return
        try:
            self._qwen_install_process=subprocess.Popen(
                ['cmd.exe','/d','/c','call',str(installer)],cwd=str(app_root),
                creationflags=getattr(subprocess,'CREATE_NEW_CONSOLE',0))
            self.qwen_status.setText('Instalação iniciada em console separado. Quando terminar, feche e reabra o BerofelStudio.')
            self.qwen_status.setVisible(True)
        except OSError as exc:
            QMessageBox.warning(self,'Qwen3 local',f'Não foi possível iniciar o instalador: {exc}')

    def _set_clone_status(self,text):
        self.clone_status.setText(text)
        self.clone_status.setVisible(self.voice.currentData()=='__custom__' and bool(text))

    def _poll_clone_activation(self):
        process=self._clone_activation_process
        if process is None:
            self._clone_watch_timer.stop()
            return
        try:
            return_code=process.poll()
        except Exception as exc:
            self._clone_watch_timer.stop()
            self._clone_activation_process=None
            self.activate_cloning.setEnabled(True)
            self._set_clone_status(f'Não foi possível confirmar a ativação: {exc}')
            return
        if return_code is None:
            return
        self._clone_watch_timer.stop()
        self._clone_activation_process=None
        self.activate_cloning.setEnabled(True)
        if return_code==0:
            self._set_clone_status('Clonagem local ativada: o encoder aceitou uma amostra sintética. Selecione sua gravação autorizada; o perfil de voz será guardado no cache local para reutilização.')
        else:
            log_path=getattr(self,'_clone_activation_log',None)
            try:
                diagnostic=log_path.read_text(encoding='utf-8',errors='replace').strip() if log_path else ''
            except OSError:
                diagnostic=''
            if diagnostic:
                diagnostic=diagnostic[-900:]
                self._set_clone_status(f'Ativação não concluída; pesos existentes preservados.\n{diagnostic}')
            else:
                self._set_clone_status('Ativação não concluída. Confira o console do autorizador e o login/termos do Hugging Face; pesos existentes preservados.')

    def set_text(self, text: str):
        self.text.setPlainText(text)

    def _generate(self, add_to_timeline: bool):
        custom = self.voice.currentData() == '__custom__'
        if custom and not self.authorized.isChecked():
            QMessageBox.warning(self, 'Autorização',
                                'Para usar uma voz personalizada, confirme que possui autorização expressa.')
            return
        voice = self.sample_path.text().strip() if custom else preset_voice(self.voice.currentData())
        engine=self.clone_engine.currentData() if custom else 'pocket-tts'
        req = NarrationRequest(text=self.text.toPlainText(), voice=voice,
                               language=self.language.currentData(),
                               consent=custom and self.authorized.isChecked(),
                               quantize=self.quantize.isChecked(),
                               title=self.name.text().strip() or 'Narração',
                               engine=engine,
                               reference_text=self.reference_text.text().strip() if custom and engine=='qwen3-tts-local' else '')
        if self.on_generate:
            self.on_generate(req, add_to_timeline)

    def busy(self, busy: bool):
        self.insert.setDisabled(busy)
        self.generate_file.setDisabled(busy)
        if busy:
            self.status.setText('Gerando em processo separado. O modelo será descarregado ao terminar...')

    def set_result(self, path: str, duration: float, cache_hit: bool):
        self.last_audio = path
        self.listen.setEnabled(True)
        self.status.setText(f'WAV pronto ({duration:.1f}s). ' +
                            ('Reaproveitado do cache.' if cache_hit else 'Salvo no cache.') +
                            '\n' + str(Path(path)))

    def _listen(self):
        if self.last_audio and Path(self.last_audio).is_file():
            self._player.stop()
            self._player.setSource(QUrl.fromLocalFile(self.last_audio))
            self._player.play()

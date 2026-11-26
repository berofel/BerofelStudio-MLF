"""Painel fixo de narração do BerofelStudio: sempre acessível à direita."""
from __future__ import annotations
import os
import hashlib
import json
import inspect
from pathlib import Path
import subprocess

from PySide6.QtCore import QUrl, QTimer, QSettings, Qt, QThread, Signal
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QTextEdit,
                               QPushButton, QCheckBox, QFileDialog, QLineEdit, QHBoxLayout,
                               QMessageBox, QScrollArea, QInputDialog,
                               QGroupBox, QSizePolicy, QBoxLayout, QTabWidget,
                               QDialog, QDialogButtonBox, QTableWidget,
                               QTableWidgetItem, QHeaderView)
from .wheel_controls import (WheelGuardComboBox as QComboBox,
    WheelGuardDoubleSpinBox as QDoubleSpinBox, WheelGuardSlider as QSlider)

from berofel.services.narration_service import (LANGUAGES, NarrationRequest,
                                                validate_clone_conditioning)
from berofel.services.voice_dsp import VOICE_EQ_PRESETS, clip_voice_eq
from berofel.services.voice_presets import VoicePresetManager
from berofel.services.voice_profiles import VoiceProfileManager

_VOICE_REFERENCE_THREADS=set()


class _VoiceReferenceInspection(QThread):
    completed = Signal(str, object, object)

    def __init__(self, source: str):
        super().__init__()
        self.source = source

    def run(self):
        try:
            from berofel.services.audio_reference import inspect_voice_reference
            self.completed.emit(self.source, inspect_voice_reference(self.source), None)
        except Exception as exc:
            self.completed.emit(self.source, None, str(exc))


class NarrationPanel(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.on_generate = None
        self.on_add_last_to_timeline = None
        self.on_use_transcript = None
        self.on_prepare_voice = None
        self.on_transcribe_reference = None
        self.on_verify_last = None
        self.on_compare_identity = None
        self.on_regenerate_segment = None
        self.last_audio = ''
        self.last_request = None
        self.last_spoken_text = ''
        self.last_engine = ''
        self.last_threads = None
        self.last_reference_path = ''
        self.last_voice_consent = False
        self.audio_history=[]
        self._voice_reference_quality_cache={}
        self._voice_reference_inspections={}
        self._voice_reference_inspection_modes={}
        self._voice_reference_warning_seen=set()
        self._reviewed_reference_key=''
        self.setWidgetResizable(True)
        self.setVerticalScrollBarPolicy(self.verticalScrollBarPolicy())
        self.setHorizontalScrollBarPolicy(self.horizontalScrollBarPolicy())
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        self.mode_tabs = QTabWidget()
        self.one_voice_page = QWidget()
        outer.addWidget(self.mode_tabs)
        layout = QVBoxLayout(self.one_voice_page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(9)
        page.setMinimumWidth(0)
        page.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        self._content_page=self.one_voice_page
        self._compact=False
        self._base_content_font=self.one_voice_page.font()
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
        self.text.setToolTip('Sem limite artificial de caracteres. Textos extensos são divididos em trechos seguros quando necessário e entregues como um único WAV.')
        self.text.setMinimumHeight(145)
        layout.addWidget(self.text)
        fill = QPushButton('↳ Trazer transcrição dos blocos selecionados')
        fill.clicked.connect(lambda: self.on_use_transcript() if self.on_use_transcript else None)
        layout.addWidget(fill)
        self._responsive_buttons=[
            (fill,'↳ Usar transcrição selecionada','↳ Usar transcrição'),
        ]

        layout.addWidget(QLabel('Idioma da narração'))
        self.language = QComboBox()
        for name, code in LANGUAGES:
            self.language.addItem(name, code)
        layout.addWidget(self.language)

        fast_title=QLabel('NARRAÇÃO RÁPIDA · PERFIS PREPARADOS')
        fast_title.setStyleSheet('color:#9cc7ff;font-weight:800;font-size:12px;')
        layout.addWidget(fast_title)
        layout.addWidget(QLabel('Selecione um perfil salvo para reutilizar a referência e o condicionamento vocal.'))
        layout.addWidget(QLabel('Perfil de voz Qwen3 (clonagem local autorizada)'))
        self.voice = QComboBox()
        self.voice_profiles=VoiceProfileManager()
        self._voice_profile_error=''
        self._append_voice_profile_items()
        self.voice.addItem('Minha voz / amostra com autorização', '__custom__')
        self.voice.setCurrentIndex(self.voice.findData('__custom__'))
        self.voice.currentIndexChanged.connect(self._update_custom)
        # User activation (not settings restoration) can warm the fast local
        # backend while the user prepares the script, reducing first-request
        # latency without loading large models on every editor launch.
        self.voice.activated.connect(self._prewarm_selected_fast_profile)
        layout.addWidget(self.voice)

        self.sample_path = QLineEdit()
        self.sample_path.setPlaceholderText('Selecione uma amostra de voz autorizada...')
        self.sample_path.setReadOnly(True)
        layout.addWidget(self.sample_path)
        choose = QPushButton('📁 Escolher amostra (WAV, MP3, FLAC...)')
        choose.clicked.connect(self._choose_sample)
        layout.addWidget(choose)
        self.choose_sample = choose
        self.validate_sample=QPushButton('✓ Verificar qualidade da gravação')
        self.validate_sample.clicked.connect(self._validate_voice_sample)
        layout.addWidget(self.validate_sample)
        self.clone_detail_title=QLabel('CLONAGEM DETALHADA · NOVA REFERÊNCIA')
        self.clone_detail_title.setStyleSheet('color:#ffb45f;font-weight:800;font-size:12px;')
        layout.addWidget(self.clone_detail_title)
        profile_actions=QHBoxLayout()
        self.save_voice_profile=QPushButton('Salvar perfil')
        self.update_voice_reference=QPushButton('Atualizar transcrição do perfil')
        self.update_voice_reference.setToolTip(
            'Salva o texto exato usado pela clonagem Original; preserva a gravação e a autorização.')
        self.rename_voice_profile=QPushButton('Renomear perfil')
        self.delete_voice_profile=QPushButton('Excluir perfil')
        self.save_voice_profile.clicked.connect(self._save_voice_profile)
        self.update_voice_reference.clicked.connect(self._update_voice_reference_text)
        self.rename_voice_profile.clicked.connect(self._rename_voice_profile)
        self.delete_voice_profile.clicked.connect(self._delete_voice_profile)
        for button in (self.save_voice_profile,self.update_voice_reference,
                       self.rename_voice_profile,self.delete_voice_profile):
            profile_actions.addWidget(button)
        layout.addLayout(profile_actions)
        self._voice_profile_action_rows=[profile_actions]
        self.authorized = QCheckBox('Confirmo autorização expressa para clonar esta voz.')
        layout.addWidget(self.authorized)
        # Compatibility field: only Qwen3-TTS Base can be selected or run.
        self.activate_cloning = QPushButton('')
        self.activate_cloning.hide()
        self.clone_engine = QComboBox()
        try:
            from berofel.services.qwen3_purec_tts import is_ready as purec_qwen_ready
            if purec_qwen_ready():
                self.clone_engine.addItem('Equilibrado — Pure C INT8 · 6 threads',
                                           'qwen3-tts-purec-int8')
                self.clone_engine.addItem('Turbo — Pure C Mixer · 6 threads',
                                           'qwen3-tts-purec-mixed')
                self.clone_engine.insertSeparator(self.clone_engine.count())
            self.clone_engine.addItem('Recomendado para clonagem · Original Qwen3-TTS Base', 'qwen3-tts-local')
        except (OSError,ValueError,ImportError):
            self.clone_engine.addItem('Original · Qwen3-TTS Base', 'qwen3-tts-local')
        try:
            from berofel.services.qwen3_native_tts import is_ready as native_qwen_ready
            if native_qwen_ready():
                self.clone_engine.addItem('Outros perfis · Turbo Q4 · 6 threads', 'qwen3-tts-native-q4')
                self.clone_engine.addItem('Outros perfis · Equilibrado Q4 · 8 threads', 'qwen3-tts-native-q4-balanced')
        except (OSError,ValueError,ImportError):
            pass
        self.clone_engine.setVisible(False)
        self.clone_engine.currentIndexChanged.connect(self._update_custom)
        self.clone_engine.activated.connect(self._prewarm_selected_fast_profile)
        layout.addWidget(self.clone_engine)
        self.purec_thread_label=QLabel('Turbo Pure C mixed · threads da CPU (6 recomendado)')
        self.purec_thread_label.setToolTip(
            'Mais threads podem acelerar uma geração isolada, mas deixam menos CPU livre. '
            'Se o servidor estiver aquecido, a próxima geração com outro valor reinicia o motor.')
        self.purec_threads=QComboBox()
        for count in (2,4,6,8):
            self.purec_threads.addItem(f'{count} threads',count)
        self.purec_threads.setCurrentIndex(self.purec_threads.findData(6))
        self.purec_thread_label.setVisible(False)
        self.purec_threads.setVisible(False)
        self.purec_threads.currentIndexChanged.connect(lambda _index:self._update_custom())
        layout.addWidget(self.purec_thread_label)
        layout.addWidget(self.purec_threads)
        self.reference_text = QLineEdit()
        self.reference_text.setPlaceholderText('Transcrição exata do trecho escolhido — confira o horário em Verificar gravação')
        self.reference_text.setToolTip('A gravação completa é varrida e o Qwen usa uma janela curta. No Original, o texto precisa corresponder exatamente ao áudio dessa janela, não à transcrição do arquivo inteiro.')
        layout.addWidget(self.reference_text)
        self.reference_text_reviewed=QCheckBox(
            'Conferi que a transcrição corresponde à janela vocal selecionada')
        self.reference_text_reviewed.setToolTip(
            'O Qwen usa o áudio e este texto juntos para clonar a voz. Revise o rascunho '
            'local, confira o intervalo informado e marque esta opção somente quando '
            'o texto corresponder ao trecho falado.')
        self.reference_text_reviewed.setVisible(False)
        layout.addWidget(self.reference_text_reviewed)
        self.use_emotional_reference=QCheckBox(
            'Transferir o estilo desta gravação (Pure C experimental)')
        self.use_emotional_reference.setToolTip(
            'Usa a própria amostra autorizada como referência de interpretação em toda a narração. '
            'Escolha uma gravação com a emoção desejada, transcreva com Parakeet e revise o texto. '
            'O servidor precisa recarregar ao ativar/trocar a referência; a síntese pode ficar mais lenta. '
            'Não troca automaticamente de emoção frase a frase.')
        self.use_emotional_reference.setVisible(False)
        self.use_emotional_reference.toggled.connect(
            self._update_emotional_reference_visibility)
        layout.addWidget(self.use_emotional_reference)
        self.transcribe_reference=QPushButton('Transcrever referência (Parakeet local)')
        self.transcribe_reference.setToolTip(
            'Transcreve a janela vocal selecionada com o Parakeet TDT v3 ONNX INT8 local. '
            'Revise e corrija o texto antes de usá-lo na clonagem PT-BR.')
        self.transcribe_reference.clicked.connect(self._transcribe_reference)
        layout.addWidget(self.transcribe_reference)
        self.pronunciation_dictionary=QPushButton('Dicionário de pronúncia PT-BR…')
        self.pronunciation_dictionary.setToolTip(
            'Cadastre nomes e termos próprios desta referência vocal. As regras '
            'só alteram a cópia enviada ao sintetizador; roteiro e legendas ficam intactos.')
        self.pronunciation_dictionary.clicked.connect(self._edit_pronunciation_dictionary)
        layout.addWidget(self.pronunciation_dictionary)
        self._responsive_buttons.append((self.pronunciation_dictionary,
            'Dicionário de pronúncia PT-BR','Pronúncia PT-BR'))
        self._responsive_buttons.append((self.transcribe_reference,
            'Transcrever referência','Transcrever referência'))
        self.install_qwen = QPushButton('⬇ Preparar Qwen3 local (download explícito)')
        self.install_qwen.clicked.connect(self._install_qwen)
        layout.addWidget(self.install_qwen)
        self.qwen_status = QLabel('')
        self.qwen_status.setWordWrap(True)
        self.qwen_status.setStyleSheet('color:#8b9db3;font-size:11px;')
        layout.addWidget(self.qwen_status)
        self._qwen_install_process=None
        self._qwen_install_log_handle=None
        self._qwen_install_log_path=None
        self._qwen_install_timer=QTimer(self)
        self._qwen_install_timer.setInterval(1000)
        self._qwen_install_timer.timeout.connect(self._poll_qwen_install)
        self.license_note = QLabel('Qwen3-TTS Base não inclui vozes pré-gravadas: crie ou importe um perfil autorizado neste computador. Perfis privados não são distribuídos pelo instalador.')
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
        self._responsive_action_rows=[profile_actions,preset_actions]
        self.eq_sliders={};self.eq_readouts={}
        self._eq_rows=[]
        self._eq_value_boxes=[]
        for key,label in (('bass_db','Graves'),('mids_db','Médios'),('treble_db','Agudos')):
            row=QWidget();row_layout=QHBoxLayout(row)
            row_layout.setContentsMargins(0,0,0,0);row_layout.setSpacing(4)
            name=QLabel(label);name.setMinimumWidth(0)
            slider=QSlider(Qt.Orientation.Horizontal);slider.setRange(-120,120);slider.setPageStep(10)
            value=QDoubleSpinBox();value.setRange(-12.,12.);value.setDecimals(1)
            value.setSingleStep(.1);value.setSuffix(' dB');value.setFixedWidth(78)
            reset=QPushButton('↺');reset.setFixedWidth(30);reset.setToolTip(f'Restaurar {label.lower()} para 0 dB')
            reset.clicked.connect(lambda _checked=False,k=key:self._reset_eq_band(k))
            slider.valueChanged.connect(lambda number,k=key,out=value:self._show_eq_value(k,number,out))
            value.valueChanged.connect(lambda number,target=slider:target.setValue(round(number*10)))
            slider.sliderPressed.connect(self._start_eq_drag)
            slider.sliderReleased.connect(self._finish_eq_drag)
            controls=QWidget();controls_layout=QHBoxLayout(controls)
            controls_layout.setContentsMargins(0,0,0,0);controls_layout.setSpacing(3)
            controls_layout.addWidget(value);controls_layout.addWidget(reset)
            row_layout.addWidget(name);row_layout.addWidget(slider,1);row_layout.addWidget(controls)
            layout.addWidget(row)
            self.eq_sliders[key]=slider;self.eq_readouts[key]=value
            self._eq_rows.append((row_layout,name,slider,controls))
            self._eq_value_boxes.append(value)
        pitch_row=QWidget();pitch_layout=QHBoxLayout(pitch_row)
        pitch_layout.setContentsMargins(0,0,0,0);pitch_layout.setSpacing(4)
        self.pitch_label=QLabel('Pitch');self.pitch_label.setMinimumWidth(0)
        pitch_layout.addWidget(self.pitch_label)
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
        pitch_controls=QWidget();pitch_controls_layout=QHBoxLayout(pitch_controls)
        pitch_controls_layout.setContentsMargins(0,0,0,0);pitch_controls_layout.setSpacing(3)
        pitch_controls_layout.addWidget(self.pitch_readout);pitch_controls_layout.addWidget(self.pitch_reset)
        pitch_layout.addWidget(self.pitch_slider,1);pitch_layout.addWidget(pitch_controls)
        self._pitch_row=(pitch_layout,self.pitch_label,self.pitch_slider,pitch_controls)
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
        self.speed_label=QLabel('Velocidade');self.speed_label.setMinimumWidth(0)
        speed_layout.addWidget(self.speed_label)
        self.speed_slider=QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(70,130);self.speed_slider.setSingleStep(5);self.speed_slider.setPageStep(5)
        self.speed_readout=QDoubleSpinBox();self.speed_readout.setRange(.70,1.30)
        self.speed_readout.setDecimals(2);self.speed_readout.setSingleStep(.05)
        self.speed_readout.setSuffix('×');self.speed_readout.setFixedWidth(78)
        speed_layout.addWidget(self.speed_slider,1);speed_layout.addWidget(self.speed_readout)
        layout.addWidget(speed_row)
        self._speed_row=(speed_layout,self.speed_label,self.speed_slider,self.speed_readout)
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
        self._responsive_action_rows.append(voice_actions)
        self._responsive_buttons.extend([
            (self.save_voice_profile,'Salvar perfil','Salvar perfil'),
            (self.rename_voice_profile,'Renomear perfil','Renomear'),
            (self.delete_voice_profile,'Excluir perfil','Excluir'),
            (self.save_voice_preset,'Salvar preset','Salvar'),
            (self.rename_voice_preset,'Renomear','Renomear'),
            (self.delete_voice_preset,'Excluir','Excluir'),
            (self.copy_voice_adjustments,'Copiar ajustes','Copiar'),
            (self.paste_voice_adjustments,'Colar ajustes','Colar'),
            (self.eq_reset,'Restaurar todas as bandas','Restaurar EQ'),
        ])
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
        self.add_last = QPushButton('＋ Adicionar última narração à timeline')
        self.add_last.setEnabled(False)
        self.add_last.clicked.connect(self._add_last_to_timeline)
        layout.addWidget(self.add_last)
        self.listen = QPushButton('♫ Ouvir última narração')
        self.listen.setEnabled(False)
        self.listen.clicked.connect(self._listen)
        layout.addWidget(self.listen)
        self.regenerate_segment=QPushButton('↻ Regenerar um trecho da narração longa')
        self.regenerate_segment.setEnabled(False)
        self.regenerate_segment.setToolTip(
            'Refaz somente um trecho com o mesmo texto e perfil, preserva as demais amostras e cria um WAV novo.')
        self.regenerate_segment.clicked.connect(self._regenerate_segment)
        layout.addWidget(self.regenerate_segment)
        self.verify_last=QPushButton('✓ Verificar texto com Parakeet local')
        self.verify_last.setEnabled(False)
        self.verify_last.setToolTip(
            'Transcreve o WAV gerado com Parakeet TDT v3 ONNX INT8/CPU e compara '
            'o texto falado. É opcional e não avalia identidade vocal.')
        self.verify_last.clicked.connect(self._verify_last)
        layout.addWidget(self.verify_last)
        self.compare_identity = QPushButton('◉ Comparar identidade vocal · experimental')
        self.compare_identity.setEnabled(False)
        self.compare_identity.setToolTip(
            'Extrai x-vectors Qwen da referência e do WAV gerado. É uma verificação '
            'manual e mais lenta; pode reiniciar o servidor uma vez por perfil. '
            'O escore não é calibrado, não decide aprovação e não substitui a audição.')
        self.compare_identity.clicked.connect(self._compare_identity)
        layout.addWidget(self.compare_identity)
        self.listen_previous=QPushButton('♫ Ouvir geração anterior')
        self.listen_previous.setEnabled(False)
        self.listen_previous.clicked.connect(self._listen_previous)
        layout.addWidget(self.listen_previous)
        self._responsive_buttons.extend([
            (choose,'📁 Escolher amostra de voz','📁 Amostra'),
            (self.validate_sample,'✓ Verificar qualidade da gravação','✓ Validar voz'),
            (self.activate_cloning,'🔐 Preparar clonagem local…','🔐 Clonagem local'),
            (self.install_qwen,'⬇ Preparar Qwen3 local','⬇ Preparar Qwen3'),
            (self.insert,'▶ Gerar e adicionar na timeline','▶ Gerar na timeline'),
            (self.generate_file,'♬ Gerar somente o WAV','♬ Gerar WAV'),
            (self.add_last,'＋ Adicionar última narração à timeline','＋ Adicionar WAV'),
            (self.listen,'♫ Ouvir a última narração','♫ Ouvir narração'),
            (self.regenerate_segment,'↻ Regenerar um trecho da narração longa','↻ Regenerar trecho'),
            (self.verify_last,'✓ Verificar texto com Parakeet local','✓ Verificar com Parakeet'),
            (self.compare_identity,'◉ Comparar identidade vocal · experimental','◉ Comparar identidade'),
            (self.listen_previous,'♫ Ouvir geração anterior','♫ Ouvir anterior'),
        ])
        self.status = QLabel('O Qwen3 Base é carregado uma vez e mantido aquecido durante a sessão do editor.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        if self._voice_profile_error:
            self.status.setText(self._voice_profile_error)
        layout.addStretch()
        self.mode_tabs.addTab(self.one_voice_page, 'UMA VOZ')
        from .multivoice_panel import MultiVoicePanel
        self.multivoice_panel = MultiVoicePanel(self)
        self.mode_tabs.addTab(self.multivoice_panel, 'VÁRIAS VOZES')
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
        self._active_profile_language_id=''
        self._restore_preferences()
        self._preferences_timer=QTimer(self)
        self._preferences_timer.setSingleShot(True)
        self._preferences_timer.setInterval(450)
        self._preferences_timer.timeout.connect(self.save_preferences)
        self.text.textChanged.connect(self._schedule_preferences_save)
        self.language.currentIndexChanged.connect(self._schedule_preferences_save)
        self.language.currentIndexChanged.connect(self._update_custom)
        self.voice.currentIndexChanged.connect(self._schedule_preferences_save)
        self.voice.activated.connect(self._warn_selected_saved_voice_quality)
        self.sample_path.textChanged.connect(self._schedule_preferences_save)
        self.clone_engine.currentIndexChanged.connect(self._schedule_preferences_save)
        self.purec_threads.currentIndexChanged.connect(self._schedule_preferences_save)
        self.reference_text.textChanged.connect(self._schedule_preferences_save)
        self.reference_text.textChanged.connect(self._refresh_clone_guidance)
        self.reference_text.textChanged.connect(self._reference_text_edited)
        self.reference_text_reviewed.toggled.connect(self._reference_review_toggled)
        self.reference_text_reviewed.toggled.connect(self._refresh_clone_guidance)
        self.sample_path.textChanged.connect(self._reference_audio_changed)
        self.sample_path.textChanged.connect(self._refresh_clone_guidance)
        self.language.currentIndexChanged.connect(self._refresh_clone_guidance)
        self.language.currentIndexChanged.connect(self._ensure_ptbr_clone_backend)
        self.clone_engine.currentIndexChanged.connect(self._ensure_ptbr_clone_backend)
        from berofel.services.qwen3_tts_local import is_ready as qwen_local_ready
        if qwen_local_ready():
            self.qwen_status.setText('Qwen3-TTS local pronto. As referências e gerações ficam no PC.')
        self.quantize.toggled.connect(self._schedule_preferences_save)
        self.name.textChanged.connect(self._schedule_preferences_save)
        self._update_custom()
        # The historical default was Pure C INT8, which omits ref_text. Keep
        # existing fast profiles available, but use the full Base ICL path for
        # the default PT-BR workflow and migrate incompatible saved defaults.
        self._ensure_ptbr_clone_backend()
        self.set_clip(None)
        self._make_controls_responsive()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self._update_responsive_layout()

    def showEvent(self,event):
        super().showEvent(event)
        self._update_responsive_layout()

    def _update_responsive_layout(self):
        if not hasattr(self,'_content_page') or not hasattr(self,'_eq_rows'):return
        width=self.viewport().width()
        compact=width<340
        if compact==self._compact:return
        self._compact=compact
        self._content_page.layout().setContentsMargins(5 if compact else 8,5 if compact else 8,
                                                      5 if compact else 8,5 if compact else 8)
        self._content_page.layout().setSpacing(6 if compact else 9)
        for row,name,slider,controls in self._eq_rows:
            row.setDirection(QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight)
            name.setMinimumWidth(0 if compact else 48)
            slider.setMinimumWidth(0)
        for row,name,slider,controls in (self._pitch_row,self._speed_row):
            row.setDirection(QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight)
            slider.setMinimumWidth(0)
        for row in getattr(self,'_responsive_action_rows',[]):
            row.setDirection(QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight)
        for spin in self._eq_value_boxes+[self.pitch_readout,self.speed_readout]:
            spin.setFixedWidth(62 if compact else 78)
        for button,full,short in self._responsive_buttons:
            button.setText(short if compact else full)
        base=self._base_content_font
        base=type(base)(base)
        if compact:base.setPointSizeF(max(8.0,base.pointSizeF()-.7))
        self._content_page.setFont(base)
        self._content_page.updateGeometry()

    def _make_controls_responsive(self):
        for button,_,_ in self._responsive_buttons:
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
        for button in self._content_page.findChildren(QPushButton):
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
        for checkbox in self._content_page.findChildren(QCheckBox):
            checkbox.setMinimumWidth(0)
            checkbox.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
        for widget_type in (QComboBox,QLineEdit):
            for control in self._content_page.findChildren(widget_type):
                control.setMinimumWidth(0)
                control.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)

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
        voice=str(settings.value('narration/voice','__custom__'))
        voice_index=self.voice.findData(voice)
        if voice_index>=0:self.voice.setCurrentIndex(voice_index)
        language=str(settings.value('narration/language','portuguese'))
        language_index=self.language.findData(language)
        if language_index>=0:self.language.setCurrentIndex(language_index)
        if not self._voice_profile_id(voice):
            self.sample_path.setText(str(settings.value('narration/sample_path','')))
        engine=str(settings.value('narration/clone_engine','qwen3-tts-local'))
        index=self.clone_engine.findData(engine)
        if index<0:index=self.clone_engine.findData('qwen3-tts-local')
        if index>=0:self.clone_engine.setCurrentIndex(index)
        try:thread_count=int(settings.value('narration/purec_threads',6))
        except (TypeError,ValueError):thread_count=6
        thread_index=self.purec_threads.findData(thread_count)
        if thread_index<0:thread_index=self.purec_threads.findData(6)
        if thread_index>=0:self.purec_threads.setCurrentIndex(thread_index)
        self.reference_text.setText(str(settings.value('narration/reference_text','')))
        # An unprofiled reference has no durable proof that this transcript was
        # checked against the selected audio. Require confirmation per session.
        self.reference_text_reviewed.setChecked(False)
        self.text.setPlainText(str(settings.value('narration/draft','')))
        self.name.setText(str(settings.value('narration/title','Narração')))
        self.quantize.setChecked(bool(settings.value('narration/quantize',False,type=bool)))

    def _schedule_preferences_save(self,*_args):
        self._preferences_timer.start()

    def _ensure_ptbr_clone_backend(self,*_args):
        """Keep PT-BR Pure C selectable; never silently switch the user's engine."""
        if self.language.currentData()!='portuguese':
            return
        engine=self.clone_engine.currentData()
        if engine in ('qwen3-tts-purec-mixed','qwen3-tts-purec-int8','qwen3-tts-local'):
            return
        index=self.clone_engine.findData('qwen3-tts-local')
        if index>=0:
            self.clone_engine.setCurrentIndex(index)
            self.status.setText('Este perfil ainda não foi validado para PT-BR; usando Original Qwen3 Base.')

    def _prewarm_selected_fast_profile(self,*_args):
        """Warm the Turbo model only after the user selects a saved voice/mode."""
        engine=self.clone_engine.currentData()
        if engine not in ('qwen3-tts-purec-mixed','qwen3-tts-purec-int8'):
            return
        profile_id=self._voice_profile_id(self.voice.currentData())
        if not profile_id or not self.on_prepare_voice:
            return
        try:
            profile=self.voice_profiles.get(profile_id)
            if not profile.get('authorized'):
                return
            reference=profile.get('sample_path','')
            if not reference or not Path(reference).is_file():
                return
            self.status.setText(
                'Preparando voz e motor local em segundo plano para acelerar a primeira narração...')
            thread_count=(self.purec_threads.currentData()
                          if engine=='qwen3-tts-purec-mixed' else None)
            self._prepare_voice(reference,profile.get('reference_text',''),
                                profile.get('name',''),thread_count,
                                profile_id=profile_id)
        except (OSError,ValueError,KeyError):
            # Generation remains available and will surface its own detailed
            # error if the saved profile cannot be prepared.
            return

    def save_preferences(self):
        settings=self._settings
        settings.setValue('narration/voice',self.voice.currentData() or 'rafael')
        settings.setValue('narration/language',self.language.currentData() or 'portuguese')
        settings.setValue('narration/sample_path',self.sample_path.text())
        settings.setValue('narration/clone_engine',self.clone_engine.currentData())
        settings.setValue('narration/purec_threads',self.purec_threads.currentData() or 6)
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
        selected=self.voice.currentData()
        profile_id=self._voice_profile_id(selected)
        custom = selected == '__custom__' or bool(profile_id)
        profile=None
        if profile_id:
            try:
                profile=self.voice_profiles.get(profile_id)
                self.sample_path.setText(profile['sample_path'])
                self.reference_text.setText(profile.get('reference_text',''))
                self.reference_text_reviewed.setChecked(
                    bool(profile.get('reference_text_reviewed', False)))
                # A profile's saved language is a selection default, not an
                # override. Applying it every time the engine changes made a
                # user's explicit language choice revert unexpectedly.
                if profile_id!=self._active_profile_language_id:
                    language_index=self.language.findData(
                        profile.get('language','portuguese'))
                    if language_index>=0:self.language.setCurrentIndex(language_index)
                    self._active_profile_language_id=profile_id
                self.authorized.setChecked(bool(profile.get('authorized',False)))
                self.authorized.setEnabled(not bool(profile.get('authorized',False)))
                if Path(profile['sample_path']).suffix.lower()=='.safetensors':
                    self._voice_profile_error='Este perfil legado não contém a gravação de referência. Importe o áudio original para preparar um perfil Qwen3 Base.'
            except (OSError,ValueError,KeyError) as exc:
                self.sample_path.clear()
                self._voice_profile_error=str(exc)
                self.authorized.setChecked(False)
                self.authorized.setEnabled(True)
        else:
            self._active_profile_language_id=''
            self.reference_text_reviewed.setChecked(False)
            self.authorized.setChecked(False)
            self.authorized.setEnabled(True)
        self.sample_path.setVisible(custom)
        self.choose_sample.setVisible(selected=='__custom__')
        self.validate_sample.setVisible(custom)
        self.clone_detail_title.setVisible(selected=='__custom__')
        self.authorized.setVisible(custom)
        self.save_voice_profile.setVisible(selected=='__custom__')
        self.rename_voice_profile.setVisible(bool(profile_id))
        self.delete_voice_profile.setVisible(bool(profile_id))
        engine=self.clone_engine.currentData()
        qwen = custom and engine in ('qwen3-tts-local','qwen3-tts-native-q4',
                                     'qwen3-tts-native-q4-balanced','qwen3-tts-purec-mixed',
                                     'qwen3-tts-purec-int8')
        self.activate_cloning.hide()
        self.clone_engine.setVisible(custom and self.clone_engine.count()>1)
        use_thread_choice=(custom and engine=='qwen3-tts-purec-mixed')
        self.purec_thread_label.setVisible(use_thread_choice)
        self.purec_threads.setVisible(use_thread_choice)
        self.reference_text.setVisible(qwen)
        use_emotion_reference = (qwen and engine in
            ('qwen3-tts-purec-mixed','qwen3-tts-purec-int8'))
        emotion_reference_supported=False
        if use_emotion_reference:
            try:
                from berofel.services.qwen3_purec_tts import supports_emotion_by_example
                emotion_reference_supported=supports_emotion_by_example()
            except (OSError,RuntimeError,ValueError,ImportError):
                emotion_reference_supported=False
        self._emotion_reference_supported=emotion_reference_supported
        self.use_emotional_reference.setVisible(
            use_emotion_reference and emotion_reference_supported)
        if use_emotion_reference and not emotion_reference_supported and \
                self.use_emotional_reference.isChecked():
            self.use_emotional_reference.setChecked(False)
        self._update_emotional_reference_visibility()
        self.transcribe_reference.setVisible(
            qwen and (self.language.currentData()=='portuguese' or
                      (use_emotion_reference and emotion_reference_supported and
                       self.use_emotional_reference.isChecked())))
        self.update_voice_reference.setVisible(bool(profile_id) and qwen)
        self.install_qwen.setVisible(qwen and engine=='qwen3-tts-local')
        self.qwen_status.setVisible(qwen and bool(self.qwen_status.text()))
        self.quantize.hide()  # Quantization is selected through explicit backend profiles below.
        if custom:
            if engine in ('qwen3-tts-purec-mixed','qwen3-tts-purec-int8') and qwen:
                mode=('Turbo Pure C mixed · Talker INT8 / Code Predictor INT4'
                      if engine=='qwen3-tts-purec-mixed' else 'Equilibrado Pure C INT8')
                self.license_note.setText(f'{mode} experimental: Qwen3 Base local. O perfil vocal é preparado em cache e o servidor é mantido ativo para a voz selecionada. Trocar de perfil, quantidade de threads ou modo de precisão reinicia e recarrega o modelo. Usa runtime MSYS2/OpenBLAS local; compare a amostra antes de escolher.')
            elif engine in ('qwen3-tts-native-q4','qwen3-tts-native-q4-balanced') and qwen:
                profile_name='Turbo · Q4 · 6 threads' if engine=='qwen3-tts-native-q4' else 'Equilibrado · Q4 · 8 threads'
                self.license_note.setText(f'{profile_name} experimental: usa o modelo Qwen3-TTS Base 0.6B nativo e o x-vector preparado. Prioriza velocidade; a clonagem detalhada continua disponível em Original. A naturalidade varia entre gerações; compare as amostras antes de escolher. Use apenas voz autorizada.')
            elif qwen:
                self.license_note.setText('Qwen3-TTS Base 0.6B: pesos públicos Apache-2.0; preparação baixa o modelo (~2,5 GB) e cria ambiente isolado. Depois, referência e síntese rodam localmente, sem enviar sua gravação. Forneça o texto exato da amostra para melhor resultado; sem ele, o modo só pelo vetor de voz pode reduzir a qualidade. Use somente voz autorizada.')
            else:
                self.license_note.setText('Importe uma referência de voz autorizada para gerar com Qwen3-TTS Base.')
        else:
            self.license_note.setText('Qwen3-TTS Base usa áudio de referência e sua transcrição para clonagem local. A amostra não sai deste computador.')
        self.license_note.setText(self.license_note.text() +
            ' O modelo Base não inclui um catálogo de vozes; perfis autorizados são criados/importados neste computador e não vêm no instalador.')
        self._clone_engine_note=self.license_note.text()
        self._refresh_clone_guidance(engine)

    def _update_emotional_reference_visibility(self, *_args):
        """Refresh transcript-review visibility without clearing user approval."""
        selected=self.voice.currentData()
        custom=(selected=='__custom__' or bool(self._voice_profile_id(selected)))
        engine=self.clone_engine.currentData()
        purec=engine in ('qwen3-tts-purec-mixed','qwen3-tts-purec-int8')
        original_ptbr=(engine=='qwen3-tts-local' and
                       self.language.currentData()=='portuguese')
        self.reference_text_reviewed.setVisible(
            custom and (original_ptbr or
                        (purec and getattr(self,'_emotion_reference_supported',False)
                         and self.use_emotional_reference.isChecked())))
        if purec:
            self.transcribe_reference.setVisible(
                custom and (self.language.currentData()=='portuguese' or
                            (getattr(self,'_emotion_reference_supported',False) and
                             self.use_emotional_reference.isChecked())))
        self._refresh_clone_guidance()

    def _refresh_clone_guidance(self,*args):
        """Keep the selected clone path and its real limitations visible in the UI."""
        if not hasattr(self,'license_note'):
            return
        engine=self.clone_engine.currentData()
        base=getattr(self,'_clone_engine_note',self.license_note.text())
        notes=[]
        if self.language.currentData()=='portuguese':
            notes.append('Português brasileiro: o Qwen3 Base recebe o idioma “Portuguese”, sem token separado de sotaque. A clonagem usa a voz e a pronúncia da gravação; uma referência em PT-BR é necessária e o resultado ainda deve ser conferido.')
        if engine in ('qwen3-tts-purec-int8','qwen3-tts-purec-mixed'):
            notes.append('Modo rápido Pure C: usa o x-vector extraído da gravação, ignora a transcrição e pode reduzir a fidelidade do sotaque/identidade. O texto ainda aparece aqui para referência, mas não é enviado como condicionamento. Confira a amostra antes de usar.')
            if getattr(self,'use_emotional_reference',None) is not None and self.use_emotional_reference.isChecked():
                notes.append('Transferência experimental por exemplo ativa: o Pure C recebe a própria gravação e sua transcrição revisada ao iniciar o servidor. O estilo fica aplicado a todas as falas dessa sessão; alternar para outro estilo reinicia o servidor e a saída ainda precisa ser avaliada auditivamente.')
            elif not getattr(self,'_emotion_reference_supported',False):
                notes.append('A referência de estilo experimental está indisponível: este executável Pure C não anunciou ou não confirmou `--emo-ref` + `--emo-ref-text` para WAV mono 24 kHz.')
        elif engine in ('qwen3-tts-native-q4','qwen3-tts-native-q4-balanced'):
            notes.append('Este backend ainda não foi validado para PT-BR. Use Original para condicionamento completo ou selecione Pure C conscientemente para o modo rápido por x-vector.')
        elif not self.reference_text.text().strip():
            notes.append('A transcrição da referência está vazia. Em PT-BR, a geração fica bloqueada até o Qwen usar áudio e transcrição juntos. Clique em “Transcrever referência” e revise o texto.')
        else:
            notes.append('Original Qwen3-TTS Base envia o áudio e a transcrição literal da referência juntos (clonagem por contexto), preservando melhor a pronúncia e o estilo da amostra.')
            if not self._reference_transcript_is_reviewed():
                notes.append('Confira o rascunho/transcrição exata da janela vocal e marque a confirmação antes de gerar; um erro no texto pode prejudicar a clonagem.')
        if self.sample_path.text().strip():
            notes.append('A gravação será varrida por inteiro para localizar o trecho usado na clonagem; o modelo recebe somente uma janela curta.')
        text=base+('\n\n'+'\n'.join(notes) if notes else '')
        self.license_note.setText(text)

    def _choose_sample(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Escolher amostra autorizada', '',
            'Amostras de voz (*.wav *.mp3 *.flac *.ogg *.m4a);;Todos os arquivos (*)')
        if path:
            if self.voice.currentData()!='__custom__':
                index=self.voice.findData('__custom__')
                if index>=0:self.voice.setCurrentIndex(index)
            self.sample_path.setText(path)
            self._warn_sample_quality_if_needed(path)

    def _warn_sample_quality_if_needed(self,source):
        resolved=str(Path(source).expanduser().resolve())
        try:
            stat=Path(resolved).stat()
            key=(resolved,stat.st_size,stat.st_mtime_ns)
        except OSError:
            self._start_voice_reference_inspection(resolved,'warning')
            return
        report=self._voice_reference_quality_cache.get(key)
        if report is not None:
            self._show_voice_reference_warning_once(key,report)
            return
        self._start_voice_reference_inspection(resolved,'warning')

    def _warn_selected_saved_voice_quality(self,_index=None):
        """Warn when the user selects a saved profile whose reference is weak."""
        profile_id=self._voice_profile_id(self.voice.currentData())
        if not profile_id:return
        try:
            profile=self.voice_profiles.get(profile_id)
        except (OSError,ValueError,KeyError):
            return
        sample=Path(profile['sample_path'])
        try:
            if not sample.is_file() or sample.stat().st_size<=44:return
        except OSError:
            return
        self._warn_sample_quality_if_needed(sample)

    def _show_voice_reference_warning_once(self,key,report):
        if key in self._voice_reference_warning_seen:return
        self._voice_reference_warning_seen.add(key)
        self._show_voice_reference_warning(report)

    def _start_voice_reference_inspection(self,source,mode):
        resolved=str(Path(source).expanduser().resolve())
        existing=self._voice_reference_inspections.get(resolved)
        if existing and existing.isRunning():
            if mode=='report':self._voice_reference_inspection_modes[resolved]=mode
            return
        self._voice_reference_inspection_modes[resolved]=mode
        thread=_VoiceReferenceInspection(resolved)
        self._voice_reference_inspections[resolved]=thread
        _VOICE_REFERENCE_THREADS.add(thread)
        thread.finished.connect(lambda task=thread:_VOICE_REFERENCE_THREADS.discard(task))
        thread.completed.connect(self._voice_reference_inspection_finished)
        thread.start()

    def _voice_reference_inspection_finished(self,source,report,error):
        resolved=str(Path(source).expanduser().resolve())
        self._voice_reference_inspections.pop(resolved,None)
        mode=self._voice_reference_inspection_modes.pop(resolved,'')
        if error:
            if mode:QMessageBox.warning(self,'Verificação da gravação',str(error))
            return
        key=None
        try:
            stat=Path(source).stat()
            key=(resolved,stat.st_size,stat.st_mtime_ns)
            self._voice_reference_quality_cache[key]=report
        except OSError:
            pass
        if str(Path(self.sample_path.text()).expanduser().resolve())!=resolved:return
        if mode=='report':self._show_voice_reference_report(report)
        elif mode=='warning' and key is not None:
            self._show_voice_reference_warning_once(key,report)

    def _show_voice_reference_warning(self,report):
        from berofel.services.audio_reference import voice_reference_warnings
        warnings=voice_reference_warnings(report)
        if not warnings:return
        details='\n'.join('• '+str(warning) for warning in warnings)
        start=float(report.get('selected_start',0))
        end=start+float(report.get('duration',0))
        QMessageBox.warning(self,'Amostra pode prejudicar a clonagem',
            f'Arquivo: {report.get("source_duration",report.get("duration",0)):.1f} s; '
            f'trecho escolhido: {start:.1f}–{end:.1f} s. '
            f'{report.get("audible_signal_seconds",0):.1f} s com sinal acima do piso de silêncio; '
            f'trecho quase silencioso: {report.get("silence_fraction",0):.0%}.\n'
            f'Essas condições podem reduzir a clareza ou a semelhança vocal. Para uma clonagem mais estável, grave 10–20 s de fala contínua, limpa e no sotaque desejado.\n\n'
            f'{details}\n\nA gravação original será preservada; você pode escolher outra amostra.')

    def _show_voice_reference_report(self,report):
        features=report.get('acoustic_features') or {}
        pitch=report.get('pitch_features') or {}
        spectral=report.get('spectral_features') or {}
        lines=[f'Duração do arquivo: {report.get("source_duration",report["duration"]):.2f} s',
               f'Trecho usado para condicionar a voz: {report["duration"]:.2f} s',
               f'Início do trecho escolhido: {report.get("selected_start",0):.2f} s',
               'A gravação inteira foi varrida para localizar atividade acústica; o Qwen usa somente este trecho curto como referência.',
               f'Sinal acima do piso de silêncio: {report.get("audible_signal_seconds",0):.2f} s',
               f'Taxa: {report["sample_rate"]} Hz mono',
               f'Nível RMS: {report["rms_dbfs"]:.1f} dBFS',
               f'Pico: {report["peak_dbfs"]:.1f} dBFS',
               f'Trecho quase silencioso: {report["silence_fraction"]:.0%}',
               f'Amostras saturadas: {report["clipped_fraction"]:.2%}']
        if features:
            lines.extend([
                f'Crest factor: {features.get("crest_factor_db",0):.1f} dB',
                f'ZCR mediana por quadro: {features.get("frame_zcr_p50",0) or 0:.3f}',
                f'RMS p10/p50/p90: {features.get("frame_rms_dbfs_p10",0):.1f} / '
                f'{features.get("frame_rms_dbfs_p50",0):.1f} / '
                f'{features.get("frame_rms_dbfs_p90",0):.1f} dBFS',
                'SNR: não estimado (sem trecho de ruído de referência confiável)'])
        if pitch.get('status') == 'measured' and pitch.get('f0_median_hz') is not None:
            lines.append(
                f'F0 descritiva: mediana {pitch["f0_median_hz"]:.1f} Hz '
                f'(p10–p90 {pitch["f0_p10_hz"]:.1f}–{pitch["f0_p90_hz"]:.1f} Hz); '
                f'confiança YIN mediana {pitch["confidence_median"]:.2f}, '
                f'{pitch["voiced_frame_count"]}/{pitch["sampled_frame_count"]} quadros vozeados')
            lines.append('F0 descreve pitch nesta amostra; não identifica a pessoa nem comprova fidelidade da clonagem.')
        elif pitch.get('status') == 'unvoiced_or_low_confidence':
            lines.append('F0 não estimada com confiança suficiente; não foi tratada como pitch zero.')
        elif pitch.get('status') == 'insufficient_voiced_coverage':
            lines.append(
                f'F0 não resumida: somente {pitch.get("voiced_frame_count",0)} quadros '
                f'vozeados confiáveis de {pitch.get("sampled_frame_count",0)}; '
                'grave uma referência com fala mais contínua para obter essa medida.')
        if spectral.get('status')=='measured':
            lines.append(
                f'Espectro mediano: centroide {spectral["spectral_centroid_hz_p50"]:.0f} Hz; '
                f'rolloff 85% {spectral["spectral_rolloff85_hz_p50"]:.0f} Hz; '
                f'flatness {spectral["spectral_flatness_p50"]:.3f}')
            mfcc=spectral.get('mfcc_median') or []
            if mfcc:
                lines.append('MFCCs medianos C0–C4: '+', '.join(f'{value:.1f}' for value in mfcc[:5]))
            hnr=spectral.get('hnr_acf_proxy_db_p50')
            if hnr is not None:
                lines.append(f'Periodicidade ACF (proxy HNR não calibrado): {hnr:.1f} dB')
            lines.append('Espectro/MFCC/periodicidade descrevem o sinal; não identificam locutor nem comprovam fidelidade do clone.')
        elif spectral.get('status')=='unvoiced_or_low_energy':
            lines.append('Análise espectral indisponível: trecho sem energia vocal suficiente.')
        if report['warnings']:
            lines.extend(['','Recomendações:',*('• '+item for item in report['warnings'])])
        else:
            lines.extend(['','Amostra tecnicamente adequada para preparar o perfil.'])
        QMessageBox.information(self,'Verificação local da gravação','\n'.join(lines))

    def _validate_voice_sample(self):
        source=self.sample_path.text().strip()
        if not source:
            QMessageBox.information(self,'Verificar gravação','Escolha primeiro uma gravação de referência.')
            return
        self._start_voice_reference_inspection(source,'report')

    @staticmethod
    def _voice_profile_id(value):
        value=str(value or '')
        prefix='voice-profile:'
        return value[len(prefix):] if value.startswith(prefix) else ''

    def _prepare_voice(self, reference, reference_text, name='', thread_count=None,
                       *, profile_id=None):
        """Call configured profile preparers with backward-compatible arguments."""
        callback=self.on_prepare_voice
        if callback is None:
            return
        try:
            parameters=inspect.signature(callback).parameters
            # Only an explicit parameter opts into this extra metadata; a
            # generic **kwargs test double or third-party callback should see
            # the historical call shape unchanged.
            supports_metadata='profile_id' in parameters
        except (TypeError,ValueError):
            supports_metadata=False
        args=(reference,reference_text,name)
        if thread_count is not None:
            args+=(thread_count,)
        if supports_metadata and profile_id:
            callback(*args,profile_id=profile_id)
        else:
            callback(*args)

    def _append_voice_profile_items(self,select_data=None):
        selected=select_data if select_data is not None else self.voice.currentData()
        self.voice.blockSignals(True)
        for index in reversed(range(self.voice.count())):
            if self._voice_profile_id(self.voice.itemData(index)):
                self.voice.removeItem(index)
        try:
            profiles=self.voice_profiles.list_profiles()
            self._voice_profile_error=''
            for profile in profiles:
                self.voice.addItem(f'Perfil local · {profile["name"]}',
                                   f'voice-profile:{profile["id"]}')
        except (OSError,ValueError,KeyError) as exc:
            self._voice_profile_error=f'Não foi possível carregar os perfis de voz locais: {exc}'
        index=self.voice.findData(selected)
        if index>=0:self.voice.setCurrentIndex(index)
        self.voice.blockSignals(False)
        if self._voice_profile_error and hasattr(self,'status'):
            self.status.setText(self._voice_profile_error)

    def _save_voice_profile(self):
        if self.voice.currentData()!='__custom__':return
        if not self.authorized.isChecked():
            QMessageBox.warning(self,'Perfil de voz',
                'Confirme que possui autorização expressa para armazenar esta referência de voz.')
            return
        source=self.sample_path.text().strip()
        if not source:
            QMessageBox.warning(self,'Perfil de voz','Escolha primeiro uma gravação de referência.')
            return
        name,ok=QInputDialog.getText(self,'Salvar perfil de voz local','Nome do perfil:')
        if not ok:return
        try:
            reference_text=self.reference_text.text().strip()
            if not reference_text and self.clone_engine.currentData() not in (
                    'qwen3-tts-purec-mixed','qwen3-tts-purec-int8'):
                QMessageBox.warning(self,'Perfil de voz','Informe a transcrição exata da gravação para ativar a clonagem Qwen3 com referência textual.')
                return
            reviewed=(self.language.currentData()!='portuguese' or
                      self.clone_engine.currentData()!='qwen3-tts-local' or
                      self._reference_transcript_is_reviewed())
            if not reviewed:
                QMessageBox.warning(self,'Revisar transcrição',
                    'Confira a transcrição da janela vocal e marque a confirmação antes de salvar este perfil PT-BR para clonagem detalhada.')
                return
            profile=self.voice_profiles.create(name,source,self.language.currentData() or 'portuguese',
                                               reference_text,authorized=True,
                                               reference_text_reviewed=reviewed)
            # Reuse the already completed inspection if this exact source
            # revision was checked. Saving a profile must not trigger another
            # full audio scan just to persist its descriptive measurements.
            try:
                source_path=Path(source).expanduser().resolve()
                stat=source_path.stat()
                cached_report=self._voice_reference_quality_cache.get(
                    (str(source_path),stat.st_size,stat.st_mtime_ns))
                if cached_report:
                    self.voice_profiles.save_acoustic_fingerprint(
                        profile['id'],cached_report)
            except (OSError,ValueError,KeyError):
                pass
            data=f'voice-profile:{profile["id"]}'
            self._append_voice_profile_items(data)
            self.multivoice_panel.refresh_profiles()
            self._update_custom()
            self.status.setText(f'Perfil “{profile["name"]}” salvo em pasta privada local. A amostra original foi preservada.')
            if self.on_prepare_voice:
                self._prepare_voice(profile['sample_path'],reference_text,
                                    profile['name'],profile_id=profile['id'])
        except (OSError,ValueError,KeyError) as exc:
            QMessageBox.warning(self,'Perfil de voz',str(exc))

    def _update_voice_reference_text(self):
        profile_id=self._voice_profile_id(self.voice.currentData())
        if not profile_id:return
        if (self.language.currentData()=='portuguese' and
                self.clone_engine.currentData()=='qwen3-tts-local' and
                not self._reference_transcript_is_reviewed()):
            QMessageBox.warning(self,'Revisar transcrição',
                'Confira a transcrição da janela vocal e marque a confirmação antes de salvá-la no perfil.')
            return
        try:
            profile=self.voice_profiles.update_reference_text(
                profile_id,self.reference_text.text(),
                reviewed=self.reference_text_reviewed.isChecked())
            signals_were_blocked=self.reference_text.blockSignals(True)
            try:
                self.reference_text.setText(profile['reference_text'])
            finally:
                self.reference_text.blockSignals(signals_were_blocked)
            self.reference_text_reviewed.setChecked(False)
            self.reference_text_reviewed.setChecked(
                bool(profile.get('reference_text_reviewed',False)))
            self.save_preferences()
            self.status.setText(
                f'Transcrição de “{profile["name"]}” atualizada. A gravação original foi preservada.')
            if self.on_prepare_voice and self.clone_engine.currentData()=='qwen3-tts-local':
                self._prepare_voice(profile['sample_path'],profile['reference_text'],
                                    profile['name'],profile_id=profile_id)
        except (OSError,ValueError,KeyError) as exc:
            QMessageBox.warning(self,'Perfil de voz',str(exc))

    def _rename_voice_profile(self):
        profile_id=self._voice_profile_id(self.voice.currentData())
        if not profile_id:return
        try:current=self.voice_profiles.get(profile_id)
        except (OSError,ValueError,KeyError) as exc:
            QMessageBox.warning(self,'Perfil de voz',str(exc));return
        name,ok=QInputDialog.getText(self,'Renomear perfil de voz','Novo nome:',text=current['name'])
        if not ok:return
        try:
            renamed=self.voice_profiles.rename(profile_id,name)
            data=f'voice-profile:{profile_id}'
            self.multivoice_panel.refresh_profiles()
            self._append_voice_profile_items(data)
            self._update_custom()
            self.status.setText(f'Perfil renomeado para “{renamed}”.')
        except (OSError,ValueError,KeyError) as exc:
            QMessageBox.warning(self,'Perfil de voz',str(exc))

    def _delete_voice_profile(self):
        profile_id=self._voice_profile_id(self.voice.currentData())
        if not profile_id:return
        try:profile=self.voice_profiles.get(profile_id)
        except (OSError,ValueError,KeyError) as exc:
            QMessageBox.warning(self,'Perfil de voz',str(exc));return
        answer=QMessageBox.question(self,'Excluir perfil local',
            f'Excluir o perfil “{profile["name"]}” e a cópia privada armazenada pelo BerofelStudio?\n\n'
            'O arquivo original que você selecionou não será removido.',
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer!=QMessageBox.StandardButton.Yes:return
        try:
            self.voice_profiles.delete(profile_id)
            self.multivoice_panel.refresh_profiles()
            self._append_voice_profile_items('__custom__')
            self._update_custom()
            self.status.setText(f'Perfil “{profile["name"]}” excluído. O original permaneceu intacto.')
        except (OSError,ValueError,KeyError) as exc:
            QMessageBox.warning(self,'Perfil de voz',str(exc))

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
        installer=app_root/'scripts'/'instalar_qwen3_tts_local.ps1'
        if not installer.is_file():
            QMessageBox.warning(self,'Qwen3 local',f'Instalador ausente: {installer}')
            return
        try:
            log_root=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'BFS'/'logs'
            log_root.mkdir(parents=True,exist_ok=True)
            self._qwen_install_log_path=log_root/'qwen3_install.log'
            self._qwen_install_log_handle=self._qwen_install_log_path.open('w',encoding='utf-8',errors='replace')
            env=os.environ.copy()
            env['BFS_NO_PAUSE']='1'
            self._qwen_install_process=subprocess.Popen(
                ['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(installer)],
                cwd=str(app_root),env=env,
                stdout=self._qwen_install_log_handle,stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.qwen_status.setText('Instalação do Qwen3 em segundo plano. Acompanhe o progresso aqui.')
            self.qwen_status.setVisible(True)
            self._qwen_install_timer.start()
        except OSError as exc:
            if self._qwen_install_log_handle:
                self._qwen_install_log_handle.close();self._qwen_install_log_handle=None
            QMessageBox.warning(self,'Qwen3 local',f'Não foi possível iniciar o instalador: {exc}')

    def _poll_qwen_install(self):
        process=self._qwen_install_process
        if process is None:
            self._qwen_install_timer.stop();return
        code=process.poll()
        if code is None:
            try:
                self._qwen_install_log_handle.flush()
                lines=self._qwen_install_log_path.read_text(encoding='utf-8',errors='replace').splitlines()
                detail=next((line.strip() for line in reversed(lines) if line.strip()),'Preparando ambiente local...')
                self.qwen_status.setText(f'Instalação Qwen3 em segundo plano · {detail[-180:]}')
            except OSError:pass
            return
        self._qwen_install_timer.stop()
        if self._qwen_install_log_handle:
            self._qwen_install_log_handle.close();self._qwen_install_log_handle=None
        if code==0:
            self.qwen_status.setText('Qwen3 local instalado. Feche e reabra o BerofelStudio para usar a clonagem.')
        else:
            self.qwen_status.setText(f'Instalação Qwen3 falhou (código {code}). Log: {self._qwen_install_log_path}')

    def set_text(self, text: str):
        self.text.setPlainText(text)

    def _generate(self, add_to_timeline: bool):
        self._ensure_ptbr_clone_backend()
        selected_voice=self.voice.currentData()
        profile_id=self._voice_profile_id(selected_voice)
        custom = selected_voice == '__custom__' or bool(profile_id)
        profile=None
        if profile_id:
            try:profile=self.voice_profiles.get(profile_id);voice=profile['sample_path']
            except (OSError,ValueError,KeyError) as exc:
                QMessageBox.warning(self,'Perfil de voz',str(exc));return
        else:
            voice = self.sample_path.text().strip() if custom else ''
        profile_authorized=bool(profile and profile.get('authorized',False))
        if custom and not profile_authorized and not self.authorized.isChecked():
            QMessageBox.warning(self, 'Autorização',
                'Confirme que possui autorização expressa para clonar esta voz. Ao salvar o perfil, a confirmação fica registrada para reutilização local.')
            return
        if profile_id and self.authorized.isChecked() and not profile_authorized:
            try:self.voice_profiles.authorize(profile_id)
            except (OSError,ValueError,KeyError) as exc:
                QMessageBox.warning(self,'Autorização do perfil',str(exc));return
            self.authorized.setEnabled(False)
        if not custom:
            QMessageBox.warning(self,'Perfil de voz Qwen3',
                'Qwen3-TTS Base precisa de uma gravação de referência. Selecione um perfil local ou importe uma amostra autorizada.')
            return
        if not voice or not Path(voice).is_file():
            QMessageBox.warning(self,'Amostra de voz','Escolha uma gravação de referência válida antes de gerar.')
            return
        engine=self.clone_engine.currentData() or 'qwen3-tts-local'
        emotion_by_example=(engine in ('qwen3-tts-purec-mixed','qwen3-tts-purec-int8')
                            and self.use_emotional_reference.isChecked())
        req = NarrationRequest(text=self.text.toPlainText(), voice=voice,
                               language=self.language.currentData(),
                               consent=custom and (profile_authorized or self.authorized.isChecked()),
                               quantize=self.quantize.isChecked(),
                               title=self.name.text().strip() or 'Narração',
                               engine=engine,
                               reference_text=(self.reference_text.text().strip()
                                   if custom and (engine not in (
                                       'qwen3-tts-purec-mixed','qwen3-tts-purec-int8')
                                       or emotion_by_example) else ''),
                               reference_text_reviewed=(
                                   self._reference_transcript_is_reviewed()
                                   if engine=='qwen3-tts-local' or emotion_by_example else False),
                               thread_count=(self.purec_threads.currentData()
                                             if engine=='qwen3-tts-purec-mixed' else None),
                               emotion_by_example=emotion_by_example)
        try:
            validate_clone_conditioning(req)
        except ValueError as exc:
            QMessageBox.warning(self,'Clonagem PT-BR',str(exc))
            return
        if self.on_generate:
            self.on_generate(req, add_to_timeline)

    def _transcribe_reference(self):
        source=self.sample_path.text().strip()
        if not source or not Path(source).is_file():
            QMessageBox.warning(self,'Transcrever referência',
                'Escolha uma gravação de voz antes de transcrevê-la.')
            return
        if self.on_transcribe_reference is None:
            QMessageBox.warning(self,'Transcrever referência',
                'A transcrição local não está conectada nesta sessão do editor.')
            return
        self.transcribe_reference.setDisabled(True)
        self.status.setText('Preparando transcrição local da janela vocal…')
        self.on_transcribe_reference(source)

    def set_reference_transcript(self,result:dict):
        """Place a local ASR draft into the editable field; user must review it."""
        text=str(result.get('text') or '').strip()
        if not text:
            raise ValueError('A transcrição local não contém texto para revisar.')
        self.reference_text.setText(text)
        self.reference_text_reviewed.setChecked(False)
        window=result.get('reference_window') or {}
        start=float(window.get('start',0.0));duration=float(window.get('duration',0.0))
        confidence=result.get('mean_word_confidence')
        confidence_note=(f' confiança média {float(confidence):.0%};' if confidence is not None
                         else '')
        self.status.setText(
            f'Rascunho Parakeet local pronto{confidence_note} · janela {start:.1f}–'
            f'{start+duration:.1f}s. Revise a transcrição e corrija qualquer erro antes '
            'de gerar; o texto da gravação não foi alterado automaticamente.')

    def _reference_text_edited(self,*_args):
        """Editing a transcript invalidates any prior review confirmation."""
        if self.reference_text_reviewed.isChecked():
            self.reference_text_reviewed.setChecked(False)

    def _reference_audio_changed(self,*_args):
        """Selecting another recording invalidates transcript review."""
        if self.reference_text_reviewed.isChecked():
            self.reference_text_reviewed.setChecked(False)

    def _reference_review_toggled(self,reviewed:bool):
        self._reviewed_reference_key=(self._reference_review_key() if reviewed else '')

    def _reference_review_key(self) -> str:
        source=Path(self.sample_path.text().strip()).expanduser()
        try:
            stat=source.stat()
            transcript_hash=hashlib.sha256(
                self.reference_text.text().strip().encode('utf-8')).hexdigest()
            return (f'{source.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|'
                    f'{transcript_hash}')
        except OSError:
            return ''

    def _reference_transcript_is_reviewed(self) -> bool:
        if not self.reference_text_reviewed.isChecked():
            return False
        current=self._reference_review_key()
        if not current or current!=self._reviewed_reference_key:
            self.reference_text_reviewed.setChecked(False)
            return False
        return True

    def set_reference_transcription_busy(self,busy:bool):
        self.transcribe_reference.setDisabled(bool(busy))

    def busy(self, busy: bool):
        self.insert.setDisabled(busy)
        self.generate_file.setDisabled(busy)
        self.verify_last.setDisabled(bool(busy) or not bool(self.last_spoken_text))
        self.regenerate_segment.setDisabled(bool(busy) or not self._has_regenerable_segments())
        self.set_identity_check_busy(bool(busy))
        if busy:
            self.status.setText('Qwen3-TTS em processo local isolado; o modelo é reutilizado durante esta sessão.')

    def set_result(self, path: str, duration: float, cache_hit: bool, engine: str='',
                   threads: int | None = None, title: str='',
                   reference_window: dict | None=None, conditioning_mode: str='',
                   source_text: str='', spoken_text: str='',
                   voice_reference_path: str='', voice_consent: bool=False,
                   request: NarrationRequest | None=None):
        self.last_audio = path
        self.last_request = request
        self.last_spoken_text = str(spoken_text or source_text or '')
        self.last_engine = str(engine or '')
        self.last_threads = threads
        self.last_reference_path = str(voice_reference_path or '')
        self.last_voice_consent = bool(voice_consent)
        self.last_duration = float(duration)
        self.last_title = str(title or Path(path).stem)
        mode={'qwen3-tts-local':'Original','qwen3-tts-native-q4':'Turbo · Q4 · 6 threads',
              'qwen3-tts-native-q4-balanced':'Equilibrado · Q4 · 8 threads',
              'qwen3-tts-purec-mixed':f'Turbo · Pure C mixed · {threads or self.purec_threads.currentData()} threads (experimental)',
              'qwen3-tts-purec-int8':'Equilibrado · Pure C INT8 · 6 threads (experimental)'}.get(engine,engine or 'Qwen3-TTS')
        if not self.audio_history or Path(self.audio_history[-1][0])!=Path(path):
            self.audio_history.append((path,mode))
            self.audio_history=self.audio_history[-8:]
        self.listen_previous.setEnabled(len(self.audio_history)>1)
        self.listen.setEnabled(True)
        self.verify_last.setEnabled(bool(self.last_spoken_text))
        self.compare_identity.setEnabled(
            self.last_engine in ('qwen3-tts-purec-mixed','qwen3-tts-purec-int8') and
            bool(self.last_voice_consent) and bool(self.last_reference_path) and
            Path(self.last_reference_path).is_file() and Path(path).is_file())
        self.add_last.setEnabled(True)
        self.regenerate_segment.setEnabled(self._has_regenerable_segments())
        reference_note=''
        if engine=='qwen3-tts-local' and reference_window:
            start=float(reference_window.get('start',0))
            end=start+float(reference_window.get('duration',0))
            method='áudio + transcrição' if conditioning_mode=='audio+transcript' else 'vetor de voz'
            reference_note=f'\nReferência usada: {start:.1f}–{end:.1f}s · {method}.'
        elif conditioning_mode=='speaker-embedding-only':
            reference_note='\nEste backend usa apenas o vetor da voz e não utiliza a transcrição da referência.'
        self.status.setText(f'WAV pronto · {mode} ({duration:.1f}s). ' +
                            ('Reaproveitado do cache.' if cache_hit else 'Salvo no cache.') +
                            reference_note+'\n' + str(Path(path)))

    def _has_regenerable_segments(self) -> bool:
        if not self.last_audio or not self.last_request:
            return False
        return Path(self.last_audio).with_suffix('.segments.json').is_file()

    def _regenerate_segment(self):
        if not self._has_regenerable_segments() or not self.on_regenerate_segment:
            return
        sidecar=Path(self.last_audio).with_suffix('.segments.json')
        try:
            manifest=json.loads(sidecar.read_text(encoding='utf-8'))
            if manifest.get('schema_version')!=2 or not isinstance(manifest.get('segments'),list):
                raise ValueError('Manifesto de trechos não compatível.')
            segments=manifest['segments']
            choices=[
                f"Trecho {int(item.get('index', position + 1))} · "
                f"{float(item.get('start_seconds', 0)):.1f}–"
                f"{float(item.get('end_seconds', 0)):.1f}s · "
                f"{str(item.get('spoken_text', '')).strip()[:100]}"
                for position,item in enumerate(segments)
            ]
            if len(choices)<2:
                raise ValueError('A narração não possui divisões recuperáveis.')
        except (OSError,ValueError,TypeError,KeyError) as exc:
            QMessageBox.warning(self,'Regenerar trecho',str(exc))
            return
        selected,ok=QInputDialog.getItem(
            self,'Regenerar trecho da narração',
            'Escolha uma parte. A operação gera um WAV novo e preserva o original:',
            choices,0,False)
        if ok and selected in choices:
            self.regenerate_segment.setDisabled(True)
            self.on_regenerate_segment(self.last_audio,self.last_request,
                                       choices.index(selected))

    def _verify_last(self):
        if (self.last_audio and Path(self.last_audio).is_file() and
                self.last_spoken_text and self.on_verify_last):
            self.verify_last.setDisabled(True)
            self.status.setText('Verificando o texto do WAV com Parakeet TDT v3 ONNX INT8/CPU…')
            self.on_verify_last(self.last_audio, self.last_spoken_text)

    def _compare_identity(self):
        if (self.compare_identity.isEnabled() and self.on_compare_identity and
                self.last_audio and self.last_reference_path):
            self.compare_identity.setDisabled(True)
            self.status.setText('Comparando x-vectors Qwen. Isso pode reiniciar o servidor; nenhuma reprodução será iniciada…')
            self.on_compare_identity(
                self.last_audio, self.last_reference_path, self.last_engine,
                self.last_threads, self.last_voice_consent)

    def set_identity_check_busy(self, busy: bool):
        self.compare_identity.setDisabled(bool(busy) or not (
            self.last_engine in ('qwen3-tts-purec-mixed','qwen3-tts-purec-int8') and
            self.last_voice_consent and self.last_reference_path and
            Path(self.last_reference_path).is_file() and
            self.last_audio and Path(self.last_audio).is_file()))

    def set_identity_result(self, result: dict):
        score = float(result['cosine_similarity'])
        self.status.setText(
            f"Similaridade heurística do x-vector Qwen: {score:.3f}. "
            "Não calibrada: não é uma probabilidade nem comprova fidelidade da voz. "
            "Confirme ouvindo a amostra e a narração. O servidor restaurou a voz selecionada.")

    def _edit_pronunciation_dictionary(self):
        selected = self.voice.currentData()
        profile_id = self._voice_profile_id(selected)
        if profile_id:
            try:
                reference = self.voice_profiles.get(profile_id)['sample_path']
            except (OSError, ValueError, KeyError) as exc:
                QMessageBox.warning(self, 'Dicionário de pronúncia', str(exc))
                return
        elif selected == '__custom__':
            reference = self.sample_path.text().strip()
        else:
            reference = ''
        if not reference or not Path(reference).is_file():
            QMessageBox.information(self, 'Dicionário de pronúncia',
                'Escolha uma amostra ou perfil local antes de editar as pronúncias.')
            return
        from berofel.services.voice_intelligence.pronunciation_dictionary import PronunciationDictionary
        try:
            dictionary = PronunciationDictionary(reference)
            entries = dictionary.load()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, 'Dicionário de pronúncia', str(exc))
            return

        dialog = QDialog(self)
        dialog.setWindowTitle('Pronúncia PT-BR desta voz')
        dialog.resize(900, 420)
        layout = QVBoxLayout(dialog)
        help_text = QLabel(
            'Ajustes locais por conteúdo da referência. A transcrição, o roteiro e as legendas não são alterados.')
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        table = QTableWidget(0, 7, dialog)
        table.setHorizontalHeaderLabels(['Termo original', 'Forma falada', 'Idioma',
            'Fonética opcional', 'Contexto opcional', 'Diferenciar maiúsculas', 'Ativo'])
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table)

        def set_check(row, column, checked):
            item = QTableWidgetItem()
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            table.setItem(row, column, item)

        def add_row(value=None):
            value = value or {'original': '', 'spoken_form': '', 'language': 'pt-br',
                              'phonetic_form': '', 'context': '',
                              'case_sensitive': False, 'enabled': True}
            row = table.rowCount()
            table.insertRow(row)
            for column, key in enumerate(('original', 'spoken_form', 'language',
                                          'phonetic_form', 'context')):
                table.setItem(row, column, QTableWidgetItem(str(value.get(key, ''))))
            set_check(row, 5, value.get('case_sensitive') is True)
            set_check(row, 6, value.get('enabled', True) is True)

        for entry in entries:
            add_row(entry)
        actions = QHBoxLayout()
        add_button = QPushButton('＋ Adicionar termo')
        remove_button = QPushButton('− Remover selecionados')
        actions.addWidget(add_button); actions.addWidget(remove_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        add_button.clicked.connect(lambda: add_row())

        def remove_selected():
            for row in sorted({index.row() for index in table.selectionModel().selectedRows()}, reverse=True):
                table.removeRow(row)
        remove_button.clicked.connect(remove_selected)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                                   QDialogButtonBox.StandardButton.Cancel, parent=dialog)
        layout.addWidget(buttons)
        buttons.rejected.connect(dialog.reject)

        def save_dictionary():
            try:
                rows = []
                for row in range(table.rowCount()):
                    text = [table.item(row, col).text().strip() if table.item(row, col) else ''
                            for col in range(5)]
                    rows.append({'original': text[0], 'spoken_form': text[1],
                        'language': text[2] or 'pt-br', 'phonetic_form': text[3],
                        'context': text[4],
                        'case_sensitive': table.item(row, 5).checkState() == Qt.CheckState.Checked,
                        'enabled': table.item(row, 6).checkState() == Qt.CheckState.Checked})
                dictionary.save([row for row in rows if row['original'] or row['spoken_form']])
            except (OSError, ValueError) as exc:
                QMessageBox.warning(dialog, 'Dicionário de pronúncia', str(exc))
                return
            dialog.accept()
        buttons.accepted.connect(save_dictionary)
        dialog.exec()

    def set_quality_check_busy(self, busy: bool):
        self.verify_last.setDisabled(bool(busy) or not bool(self.last_spoken_text))

    def set_quality_result(self, result: dict):
        wer = float(result.get('word_error_rate', 0.0)) * 100
        cer = float(result.get('character_error_rate', 0.0)) * 100
        recognized = str(result.get('recognized_text') or '').strip()
        trailing = result.get('trailing_gap_seconds')
        audio_warnings = result.get('audio_warnings') or []
        audio_note = (f"\nÁudio: RMS {float(result.get('audio_rms_dbfs', 0)):.1f} dBFS · "
                      f"pico {float(result.get('audio_peak_dbfs', 0)):.1f} dBFS · "
                      f"clipping {float(result.get('audio_clipped_fraction', 0))*100:.2f}%.")
        if result.get('verification_skipped_reason'):
            audio_note += f"\n{result['verification_skipped_reason']}"
        if audio_warnings:
            audio_note += "\n" + " ".join(str(warning) for warning in audio_warnings)
        timing_note = (f'\nFim reconhecido em {result.get("last_recognized_word_end_seconds"):.2f} s; '
                       f'intervalo restante {float(trailing):.2f} s. Confira o final ouvindo.'
                       if result.get('review_ending') and trailing is not None and
                       result.get('last_recognized_word_end_seconds') is not None else '')
        if result.get('verification_skipped_reason'):
            summary = "Integridade do WAV verificada; comparação textual não executada."
        else:
            summary = (f"Parakeet TDT v3 ONNX INT8/CPU · erro textual estimado: "
                       f"WER {wer:.1f}% · CER {cer:.1f}%. Revisão humana recomendada; "
                       "isso não mede fidelidade da identidade vocal.\n"
                       f"Reconhecido: {recognized or '(nenhuma fala reconhecida)'}")
        self.status.setText(f"{summary}{audio_note}{timing_note}")

    def _add_last_to_timeline(self):
        if self.last_audio and Path(self.last_audio).is_file() and self.on_add_last_to_timeline:
            self.on_add_last_to_timeline(self.last_audio, getattr(self,'last_duration',0.0),
                                         getattr(self,'last_title',Path(self.last_audio).stem))

    def _listen(self):
        if self.last_audio and Path(self.last_audio).is_file():
            self._play_audio(self.last_audio)

    def _listen_previous(self):
        if len(self.audio_history)>1:
            previous=self.audio_history[-2][0]
            if Path(previous).is_file():self._play_audio(previous)

    def _play_audio(self,path:str):
        if Path(path).is_file():
            self._player.stop()
            self._player.setSource(QUrl.fromLocalFile(path))
            self._player.play()

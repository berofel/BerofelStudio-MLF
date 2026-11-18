"""Ações independentes 0.8; espaço fixo no painel direito, sem modais de seleção."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QScrollArea, QWidget, QVBoxLayout, QHBoxLayout,
    QBoxLayout, QSizePolicy, QLabel, QLineEdit, QPushButton,
    QTextEdit, QFrame, QCheckBox)
from .wheel_controls import WheelGuardComboBox as QComboBox

from berofel.services.action_scope import ScopeSpec, resolve_scope, scope_summary
from berofel.services.batch_editing import plan_actions

SCOPES = [
    ('Um bloco selecionado', 'one'),
    ('Vários blocos selecionados', 'selected'),
    ('Faixa inteira escolhida', 'track'),
    ('Intervalo In/Out (todas as faixas)', 'interval'),
    ('Intervalo In/Out da faixa escolhida', 'track_interval'),
    ('Projeto inteiro', 'project'),
]
ACTIONS = [
    ('Transcrever · somente Whisper', 'transcribe'),
    ('Legendas automáticas · Whisper', 'subtitles'),
    ('Detectar silêncios · só Silero', 'silence'),
    ('Vícios de linguagem · Whisper + Qwen', 'fillers'),
    ('Análise contextual · sem cortes', 'context'),
    ('Exportar legendas SRT do alcance', 'srt'),
    ('Usar transcrição na narração', 'narration'),
]


def parse_timecode(value: str) -> float:
    """Aceita segundos, mm:ss ou hh:mm:ss, com parte decimal opcional."""
    parts = value.strip().replace(',', '.').split(':')
    if not 1 <= len(parts) <= 3:
        raise ValueError('Use segundos, MM:SS ou HH:MM:SS.')
    try:
        parsed = [float(p) for p in parts]
    except ValueError as exc:
        raise ValueError('Tempo inválido: use HH:MM:SS.') from exc
    if any(n < 0 for n in parsed):
        raise ValueError('O tempo não pode ser negativo.')
    if len(parsed) > 1 and any(n >= 60 or n != int(n) for n in parsed[:-1]):
        raise ValueError('Os minutos e as horas precisam ser inteiros; apenas os segundos podem ter decimais.')
    if len(parsed) > 1 and parsed[-1] >= 60:
        raise ValueError('Os segundos devem ser menores que 60.')
    return sum(n * 60**i for i,n in enumerate(reversed(parsed)))


def format_timecode(t: float) -> str:
    ms = round(max(0,t)*1000)
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    seconds, ms = divmod(ms, 1_000)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}.{ms:03d}'


class ActionsPanel(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.on_execute = None
        self.on_execute_plan = None
        self.on_clipper = None
        self.project = None
        self.selected_ids = []
        self.playhead = 0.0
        self._busy = False
        self._compact=None
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page = QWidget()
        page.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        box = QVBoxLayout(page)
        box.setContentsMargins(9,10,9,10)
        box.setSpacing(8)
        assistant_head=QHBoxLayout()
        title=QLabel('ASSISTENTE LOCAL')
        title.setStyleSheet('color:#ffad70;font-weight:850;font-size:13px;letter-spacing:.5px;')
        assistant_head.addWidget(title,1)
        self.local_badge=QLabel('● IA LOCAL')
        self.local_badge.setToolTip('As análises usam os motores locais instalados no computador.')
        self.local_badge.setStyleSheet('color:#a8edc2;background:#183628;border:1px solid #356649;'
                                       'border-radius:9px;padding:3px 7px;font-size:9px;font-weight:750;')
        assistant_head.addWidget(self.local_badge)
        box.addLayout(assistant_head)
        subtitle=QLabel('Analisar e revisar')
        subtitle.setStyleSheet('font-size:15px;font-weight:800;color:#f1f3f5;')
        box.addWidget(subtitle)
        description=QLabel('Escolha o alcance e as funções. A fila Batata Quente executa as etapas '
                           'pesadas em sequência; a timeline continua livre e nenhum arquivo é alterado ao importar.')
        description.setWordWrap(True)
        box.addWidget(description)
        box.addWidget(QLabel('Aplicar em'))
        self.scope = QComboBox()
        for name, key in SCOPES:
            self.scope.addItem(name,key)
        self.scope.setCurrentIndex(1)
        self.scope.currentIndexChanged.connect(self.update_scope_preview)
        box.addWidget(self.scope)
        self.track_label=QLabel('Faixa escolhida')
        self.track_combo=QComboBox()
        self.track_combo.currentIndexChanged.connect(self.update_scope_preview)
        box.addWidget(self.track_label)
        box.addWidget(self.track_combo)
        self.time_label=QLabel('Intervalo marcado na timeline')
        box.addWidget(self.time_label)
        row=QHBoxLayout()
        self.timecode_row=row
        self.start=QLineEdit('00:00:00.000')
        self.start.setPlaceholderText('Entrada (In)')
        self.end=QLineEdit('00:00:05.000')
        self.end.setPlaceholderText('Saída (Out)')
        self.start.textChanged.connect(self.update_scope_preview)
        self.end.textChanged.connect(self.update_scope_preview)
        row.addWidget(self.start)
        row.addWidget(self.end)
        box.addLayout(row)
        row2=QHBoxLayout()
        self.in_out_row=row2
        self.in_btn=QPushButton('In = cursor')
        self.out_btn=QPushButton('Out = cursor')
        self.in_btn.clicked.connect(lambda:self.start.setText(format_timecode(self.playhead)))
        self.out_btn.clicked.connect(lambda:self.end.setText(format_timecode(self.playhead)))
        row2.addWidget(self.in_btn)
        row2.addWidget(self.out_btn)
        box.addLayout(row2)
        self.summary=QLabel('Selecione um ou mais blocos na timeline.')
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet('color:#ffb370;background:#202329;border-left:3px solid #f5822b;'
                                    'padding:7px 8px;font-weight:650;')
        box.addWidget(self.summary)
        line=QFrame();line.setFrameShape(QFrame.Shape.HLine)
        box.addWidget(line)
        self.action_buttons=[]
        section=QLabel('AÇÕES DA EDIÇÃO  ·  selecione uma ou mais')
        section.setStyleSheet('color:#ffad70;font-weight:800;font-size:10px;')
        box.addWidget(section)
        self.action_checks={}
        self._action_labels={}
        chosen_actions=[
            ('silence','Remover silêncios · Silero VAD'),
            ('transcribe','Transcrever · Faster-Whisper'),
            ('fillers','Revisar vícios de linguagem · Qwen'),
            ('context','Analisar contexto · Qwen (sem corte automático)'),
            ('subtitles','Criar legendas automáticas editáveis'),
            ('srt','Exportar legendas SRT ao final'),
            ('narration','Narração · Pocket TTS (texto/voz do painel)')]
        for key,label in chosen_actions:
            check=QCheckBox(label)
            check.setToolTip(f'{label}. Pode combinar com outras ações; o editor resolve as dependências.')
            check.stateChanged.connect(self._update_plan)
            box.addWidget(check)
            self.action_checks[key]=check
            self._action_labels[key]=label
        presets=QHBoxLayout()
        self.presets_row=presets
        all_btn=QPushButton('Edição completa')
        all_btn.setToolTip('Silero, Whisper, Qwen e legendas; revise os cortes antes de aplicar.')
        all_btn.clicked.connect(lambda:self.set_actions(('silence','transcribe','fillers','subtitles')))
        presets.addWidget(all_btn)
        clear_btn=QPushButton('Desmarcar')
        clear_btn.clicked.connect(lambda:self.set_actions(()))
        presets.addWidget(clear_btn)
        box.addLayout(presets)
        self.optimize=QCheckBox('Usar Silero para poupar tempo do Whisper')
        self.optimize.setChecked(True)
        self.optimize.setToolTip('Ignora intervalos sem voz durante a transcrição, mas não corta o vídeo sem aprovação.')
        self.optimize.stateChanged.connect(self._update_plan)
        box.addWidget(self.optimize)
        self.plan_label=QLabel('Escolha as funções para montar a fila.')
        self.plan_label.setWordWrap(True)
        self.plan_label.setStyleSheet('color:#ffb370;background:#202329;border:1px solid #3e434b;'
                                      'border-radius:5px;padding:7px 8px;font-weight:650;')
        box.addWidget(self.plan_label)
        self.batch_button=QPushButton('▶ APLICAR EDIÇÃO · executar fila')
        self.batch_button.setToolTip('Executar a fila selecionada no alcance escolhido.')
        self.batch_button.setObjectName('batch_apply')
        self.batch_button.setStyleSheet('QPushButton#batch_apply{background:#ff8126;color:#24170f;'
                                        'font-weight:850;padding:10px;border:1px solid #ff9a4e;border-radius:6px;} '
                                        'QPushButton#batch_apply:hover{background:#ffa04d;}')
        self.batch_button.clicked.connect(self._trigger_batch)
        box.addWidget(self.batch_button)
        self.action_buttons.append(self.batch_button)
        hint=QLabel('Ao terminar: aprovar todos os cortes, escolher individualmente ou '
                    'não cortar. As etapas concluídas ficam em cache. A edição na timeline continua livre.')
        hint.setWordWrap(True)
        box.addWidget(hint)
        line_single=QFrame();line_single.setFrameShape(QFrame.Shape.HLine)
        box.addWidget(line_single)
        self.clipper_button=QPushButton('✂ Clipador Inteligente · sugerir destaques')
        self.clipper_button.setToolTip('Reutiliza transcrição e waveform para ranquear intervalos. Não corta sem confirmação.')
        self.clipper_button.clicked.connect(self._trigger_clipper)
        box.addWidget(self.clipper_button)
        self.action_buttons.append(self.clipper_button)
        box.addWidget(QLabel('AÇÕES AVULSAS · um clique, uma função'))
        for label,key in ACTIONS:
            button=QPushButton(label)
            button.setToolTip('Executa somente esta ação no alcance indicado.')
            button.clicked.connect(lambda _, action=key:self._trigger(action))
            box.addWidget(button)
            self.action_buttons.append(button)
        line2=QFrame();line2.setFrameShape(QFrame.Shape.HLine)
        box.addWidget(line2)
        box.addWidget(QLabel('Legenda escrita manualmente (sem IA)'))
        self.manual_text=QTextEdit()
        self.manual_text.setPlaceholderText('Escreva sua legenda. Pode editar o bloco de texto na timeline depois.')
        self.manual_text.setMinimumHeight(85)
        box.addWidget(self.manual_text)
        manual=QPushButton('+ Criar legendas manuais no alcance')
        manual.clicked.connect(lambda:self._trigger('manual'))
        box.addWidget(manual)
        self.action_buttons.append(manual)
        foot=QLabel('Narração livre: abra a aba 🎙 Narração, escreva o texto e escolha a voz. '
                    'Para narrar a transcrição de um alcance, use “Usar transcrição na narração”.')
        foot.setWordWrap(True)
        foot.setStyleSheet('color:#8da4ba;')
        box.addWidget(foot)
        box.addStretch()
        self.setWidget(page)
        self.update_scope_preview()
        self._update_plan()
        self._apply_compact(self.width()<320)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self._apply_compact(event.size().width()<320)

    def _apply_compact(self,compact: bool):
        if self._compact==compact:return
        self._compact=compact
        direction=(QBoxLayout.Direction.TopToBottom if compact
                   else QBoxLayout.Direction.LeftToRight)
        for layout in (self.timecode_row,self.in_out_row,self.presets_row):
            layout.setDirection(direction)
        self.local_badge.setVisible(not compact)
        labels={'silence':'Silêncio · Silero','transcribe':'Transcrever · Whisper',
                'fillers':'Vícios · Qwen','context':'Contexto · Qwen',
                'subtitles':'Legendas automáticas','srt':'Exportar SRT',
                'narration':'Narração · Pocket TTS'}
        for key,check in self.action_checks.items():
            check.setText(labels[key] if compact else self._action_labels[key])
        self.batch_button.setText('▶ APLICAR EDIÇÃO' if compact
                                  else '▶ APLICAR EDIÇÃO · executar fila')
        self.clipper_button.setText('✂ Clipador Inteligente' if compact else
                                    '✂ Clipador Inteligente · sugerir destaques')
        self.manual_text.setMinimumHeight(64 if compact else 85)

    def checked_actions(self):
        return tuple(name for name,check in self.action_checks.items() if check.isChecked())

    def set_actions(self, names):
        chosen=set(names)
        for key,check in self.action_checks.items():
            check.blockSignals(True)
            check.setChecked(key in chosen)
            check.blockSignals(False)
        self._update_plan()

    def _update_plan(self, *args):
        try:
            plan=plan_actions(self.checked_actions(),self.optimize.isChecked())
        except ValueError:
            self.plan_label.setText('Marque uma ou mais ações para montar a fila.')
            self.batch_button.setEnabled(False)
            return
        labels={'silence':'Silero','whisper':'Whisper',
                'whisper_qwen':'Whisper + Qwen','qwen':'Qwen','subtitles':'Legendas',
                'srt':'SRT','narration':'Pocket TTS'}
        self.plan_label.setText('Fila automática: ' + ' → '.join(labels[name] for name in plan.phases) +
            ('\nSilero reduz o áudio analisado pelo Whisper, mas os cortes aguardam sua aprovação.'
             if plan.use_vad_for_asr else ''))
        self.batch_button.setEnabled(not self._busy)

    def _trigger_batch(self):
        if self._busy or not self.checked_actions():return
        if self.on_execute_plan:
            self.on_execute_plan(self.checked_actions(),self.optimize.isChecked())

    def _trigger(self, action):
        if self._busy:return
        if self.on_execute:self.on_execute(action)

    def _trigger_clipper(self):
        if not self._busy and self.on_clipper:
            self.on_clipper()

    def spec(self) -> ScopeSpec:
        return ScopeSpec(mode=self.scope.currentData(),
                         selected_ids=tuple(self.selected_ids),
                         track_id=self.track_combo.currentData() or '',
                         in_time=parse_timecode(self.start.text()),
                         out_time=parse_timecode(self.end.text()))

    def selection(self):
        if self.project is None:
            raise ValueError('Projeto ainda não disponível.')
        return resolve_scope(self.project,self.spec())

    def set_context(self, project, selected_ids, track_id, playhead):
        self.project=project
        self.selected_ids=list(selected_ids)
        self.playhead=float(playhead)
        previous=self.track_combo.currentData() or track_id
        self.track_combo.blockSignals(True)
        self.track_combo.clear()
        for track in project.tracks:
            self.track_combo.addItem(track.name,track.id)
        pos=self.track_combo.findData(previous)
        if pos < 0:pos=self.track_combo.findData(track_id)
        self.track_combo.setCurrentIndex(max(0,pos))
        self.track_combo.blockSignals(False)
        self.update_scope_preview()

    def update_scope_preview(self, *args):
        mode=self.scope.currentData()
        is_track=mode in ('track','track_interval')
        is_range=mode in ('interval','track_interval')
        for control in (self.track_label,self.track_combo):
            control.setVisible(is_track)
        for control in (self.time_label,self.start,self.end,self.in_btn,self.out_btn):
            control.setVisible(is_range)
        if self.project is None:
            return
        try:
            _,targets=self.selection()
            n,seconds=scope_summary(targets)
            if not n:
                message='Nenhum bloco de áudio ou vídeo neste alcance.'
            else:
                message=f'{n} bloco(s) · {format_timecode(seconds)} de conteúdo a processar'
            self.summary.setText(message)
        except ValueError as exc:
            self.summary.setText(str(exc))

    def busy(self,value: bool):
        self._busy=bool(value)
        for button in self.action_buttons:
            button.setDisabled(value)
        if not value:self._update_plan()

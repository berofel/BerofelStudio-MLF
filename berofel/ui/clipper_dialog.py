"""Revisão leve e não modal dos candidatos do Clipador Inteligente."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QDialog,
    QCheckBox, QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget)
from .wheel_controls import (WheelGuardComboBox as QComboBox,
    WheelGuardDoubleSpinBox as QDoubleSpinBox, WheelGuardSpinBox as QSpinBox)

from berofel.services.clipper import ClipperOptions, suggest_title
from berofel.services.clip_audio_signals import CLIP_SCORE_PROFILES


class ClipperDialog(QDialog):
    analyze_requested=Signal(object)
    cancel_requested=Signal()
    preview_requested=Signal(object)
    insert_requested=Signal(object)
    markers_requested=Signal(object)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.setWindowTitle('Clipador Inteligente · revisar destaques')
        self.resize(900,620)
        self.setMinimumSize(620,420)
        self.setModal(False)
        root=QVBoxLayout(self)
        intro=QLabel('CLIPADOR INTELIGENTE  ·  TRANSCRIÇÃO + SINAIS DE ÁUDIO')
        intro.setStyleSheet('color:#ffad70;font-weight:850;font-size:12px;letter-spacing:.5px;')
        root.addWidget(intro)
        explanation=QLabel('A nota 0–100 é um ranking editorial explicável, não uma previsão de viralização. '
            'O Clipador reutiliza a transcrição existente do Parakeet. Equilibrado mede RMS/picos em PCM por '
            'streaming; Rápido lê apenas waveforms já armazenadas na timeline (aproximação de pico em 100 ms); '
            'Avançado também aplica TextRank local às falas do candidato. '
            'Sem transcrição salva, pode sugerir trechos para revisão por picos relativos de áudio ou mudanças '
            'em miniaturas já armazenadas; isso não reconhece ações nem conteúdo. '
            'A análise não corta nem renderiza a mídia. Cada candidato precisa de confirmação.')
        explanation.setWordWrap(True)
        explanation.setStyleSheet('color:#bac2cc;')
        root.addWidget(explanation)

        options=QHBoxLayout()
        options.addWidget(QLabel('Duração mínima (s)'))
        self.minimum=QSpinBox();self.minimum.setRange(3,300);self.minimum.setValue(15)
        options.addWidget(self.minimum)
        options.addWidget(QLabel('máxima (s)'))
        self.maximum=QSpinBox();self.maximum.setRange(4,600);self.maximum.setValue(60)
        options.addWidget(self.maximum)
        options.addWidget(QLabel('candidatos'))
        self.maximum_candidates=QSpinBox();self.maximum_candidates.setRange(1,50)
        self.maximum_candidates.setValue(8)
        options.addWidget(self.maximum_candidates)
        options.addWidget(QLabel('sensibilidade (dB)'))
        self.sensitivity=QDoubleSpinBox();self.sensitivity.setRange(1.,24.)
        self.sensitivity.setSingleStep(1.);self.sensitivity.setDecimals(1)
        self.sensitivity.setValue(6.)
        options.addWidget(self.sensitivity)
        options.addWidget(QLabel('perfil'))
        self.profile=QComboBox()
        self.profile.addItems(tuple(CLIP_SCORE_PROFILES))
        self.profile.setToolTip('Altera os pesos do ranking editorial; não executa outra transcrição.')
        options.addWidget(self.profile)
        options.addWidget(QLabel('modo'))
        self.mode=QComboBox()
        self.mode.addItems(('Rápido','Equilibrado','Avançado'))
        self.mode.setCurrentText('Equilibrado')
        self.mode.setToolTip('Rápido: waveform em cache; Equilibrado: PCM + regras; Avançado: PCM + TextRank local. Todos reutilizam a transcrição Parakeet.')
        options.addWidget(self.mode)
        root.addLayout(options)

        self.weight_group=QGroupBox('Ajuste avançado de pesos · experimental')
        self.weight_group.setCheckable(True)
        self.weight_group.setChecked(False)
        weight_layout=QVBoxLayout(self.weight_group)
        weight_note=QLabel('Prioridades relativas do ranking (não são probabilidades). '
                           'Os demais cálculos e a transcrição em cache são reutilizados.')
        weight_note.setWordWrap(True)
        weight_layout.addWidget(weight_note)
        self.weight_controls=QWidget()
        weight_grid=QGridLayout(self.weight_controls)
        self.score_weight_controls={}
        labels={'hook':'Gancho','context':'Contexto','audio':'Áudio',
                'value':'Informação','payoff':'Desfecho','rhythm':'Ritmo',
                'visual':'Visual'}
        for index,(key,label) in enumerate(labels.items()):
            row,column=divmod(index,4)
            cell=QWidget();cell_layout=QVBoxLayout(cell)
            cell_layout.setContentsMargins(0,0,0,0)
            cell_layout.addWidget(QLabel(label))
            spin=QDoubleSpinBox();spin.setRange(0.,100.)
            spin.setDecimals(0);spin.setSingleStep(5.);spin.setSuffix('%')
            spin.setToolTip(f'Peso de {label.lower()} neste perfil. Zero desconsidera essa dimensão.')
            cell_layout.addWidget(spin)
            weight_grid.addWidget(cell,row,column)
            self.score_weight_controls[key]=spin
        weight_layout.addWidget(self.weight_controls)
        self.weight_controls.setVisible(False)
        self.weight_group.toggled.connect(self.weight_controls.setVisible)
        self.profile.currentTextChanged.connect(self._reset_profile_weights)
        self._reset_profile_weights(self.profile.currentText())
        root.addWidget(self.weight_group)

        visual_row=QHBoxLayout()
        self.visual_analysis=QCheckBox('Análise visual opcional · somente miniaturas já em cache')
        self.visual_analysis.setToolTip(
            'Compara mudanças entre miniaturas existentes da timeline. Não solicita novos quadros, '
            'não decodifica o vídeo e não identifica semanticamente o que aparece.')
        visual_row.addWidget(self.visual_analysis)
        visual_row.addStretch(1)
        root.addLayout(visual_row)

        self.status=QLabel('Analise somente o alcance escolhido na aba Ações IA.')
        self.status.setWordWrap(True)
        self.status.setStyleSheet('color:#ffbe83;background:#202329;border-left:3px solid #f5822b;padding:6px;')
        root.addWidget(self.status)
        boundary_row=QHBoxLayout()
        boundary_row.addWidget(QLabel('Ajuste por palavra · início'))
        self.start_boundary=QComboBox();self.start_boundary.setMinimumWidth(150)
        boundary_row.addWidget(self.start_boundary,1)
        boundary_row.addWidget(QLabel('fim'))
        self.end_boundary=QComboBox();self.end_boundary.setMinimumWidth(150)
        boundary_row.addWidget(self.end_boundary,1)
        root.addLayout(boundary_row)
        self.table=QTableWidget(0,6)
        self.table.setHorizontalHeaderLabels(('Usar','Nota','Tempo · duração',
                                              'Título sugerido','Texto transcrito',
                                              'Sinais e avisos'))
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        header=self.table.horizontalHeader()
        header.setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1,QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2,QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3,QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4,QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5,QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(lambda _row,_column:self._preview_current())
        self.table.currentCellChanged.connect(lambda row,*_args:self._load_boundaries(row))
        self.start_boundary.currentIndexChanged.connect(lambda *_:self._boundary_changed('start'))
        self.end_boundary.currentIndexChanged.connect(lambda *_:self._boundary_changed('end'))
        root.addWidget(self.table,1)

        actions=QHBoxLayout()
        self.analyze_button=QPushButton('⌕ Analisar com configurações')
        self.analyze_button.clicked.connect(self._analyze)
        actions.addWidget(self.analyze_button)
        self.cancel_button=QPushButton('Cancelar análise')
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        actions.addWidget(self.cancel_button)
        self.preview_button=QPushButton('▶ Prévia no monitor')
        self.preview_button.clicked.connect(self._preview_current)
        actions.addWidget(self.preview_button)
        self.markers_button=QPushButton('⚑ Marcar eventos')
        self.markers_button.setToolTip('Adiciona marcadores dos eventos acústicos à timeline; operação reversível por Ctrl+Z.')
        self.markers_button.clicked.connect(self._mark_events)
        actions.addWidget(self.markers_button)
        self.insert_button=QPushButton('＋ Adicionar marcados à timeline')
        self.insert_button.setStyleSheet('background:#ff8126;color:#24170f;font-weight:800;')
        self.insert_button.clicked.connect(self._insert)
        actions.addWidget(self.insert_button)
        self.select_all=QPushButton('Marcar todos')
        self.select_all.clicked.connect(lambda:self._set_all(True))
        actions.addWidget(self.select_all)
        self.clear_all=QPushButton('Limpar')
        self.clear_all.clicked.connect(lambda:self._set_all(False))
        actions.addWidget(self.clear_all)
        root.addLayout(actions)

        self._candidates=[]
        self._events=[]
        self._updating_boundaries=False

    def options(self):
        if self.maximum.value()<=self.minimum.value():
            QMessageBox.information(self,'Clipador Inteligente',
                'A duração máxima precisa ser maior que a duração mínima.')
            return None
        return ClipperOptions(self.minimum.value(),self.maximum.value(),
            self.maximum_candidates.value(),self.sensitivity.value(),self.profile.currentText(),
            self.mode.currentText(),self.visual_analysis.isChecked(),
            ({key:spin.value()/100. for key,spin in self.score_weight_controls.items()}
             if self.weight_group.isChecked() else None))

    def _reset_profile_weights(self,profile):
        weights=CLIP_SCORE_PROFILES.get(profile,CLIP_SCORE_PROFILES['Geral'])
        for key,spin in self.score_weight_controls.items():
            spin.setValue(float(weights.get(key,0.))*100.)

    def _analyze(self):
        options=self.options()
        if options is not None:
            self.analyze_requested.emit(options)

    def set_busy(self,busy: bool):
        self.analyze_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        for widget in (self.minimum,self.maximum,self.maximum_candidates,self.sensitivity,
                       self.profile,self.mode,self.visual_analysis):
            widget.setEnabled(not busy)
        self.weight_group.setEnabled(not busy)
        if busy:self.status.setText('Calculando em segundo plano; você pode continuar editando a timeline.')

    def set_results(self,result: dict):
        self.set_busy(False)
        self._candidates=list(result.get('candidates',[]))
        self._events=list(result.get('events',[]))
        self.table.setRowCount(len(self._candidates))
        for row,candidate in enumerate(self._candidates):
            check=QTableWidgetItem('')
            check.setFlags(check.flags()|Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(Qt.CheckState.Unchecked)
            check.setData(Qt.ItemDataRole.UserRole,candidate)
            self.table.setItem(row,0,check)
            coverage=float(candidate.get('evidence_coverage',0.))
            self.table.setItem(row,1,QTableWidgetItem(
                f"{candidate['score']:.1f}/100 · evidência {coverage:.0%}"))
            self.table.setItem(row,2,QTableWidgetItem(
                f"{candidate['source_start']:.2f}–{candidate['source_end']:.2f}s  ·  {candidate['duration']:.1f}s"))
            title=str(candidate.get('suggested_title') or suggest_title(candidate.get('text','')))
            candidate['suggested_title']=title
            self.table.setItem(row,3,QTableWidgetItem(title))
            transcript_text=candidate.get('text','')
            if not candidate.get('transcript_available',True):
                transcript_text=(
                    'Sem palavras do Parakeet nesta janela · confirme áudio/vídeo'
                    if candidate.get('transcript_present') else
                    'Sem transcrição · candidato baseado apenas em sinais observados')
            self.table.setItem(row,4,QTableWidgetItem(transcript_text))
            evidence='; '.join(candidate.get('reasons',[])) or 'Sem evidência textual forte.'
            components=candidate.get('score_components',{})
            labels={'hook':'gancho','context':'contexto','audio':'áudio',
                    'value':'informação','payoff':'desfecho','rhythm':'ritmo','visual':'visual'}
            measured=[f"{labels.get(key,key)} {value:.2f}" for key,value in components.items()
                      if value is not None]
            if measured:evidence+='  ·  componentes: '+', '.join(measured)
            if candidate.get('text_rank_score') is not None:
                evidence+=f"  ·  TextRank local {float(candidate['text_rank_score']):.2f}"
            warnings=candidate.get('warnings',[])
            if warnings:evidence+='  ⚠ '+'; '.join(warnings)
            if candidate.get('events'):
                evidence+=f"  ·  {len(candidate['events'])} evento(s) observável(is)"
            self.table.setItem(row,5,QTableWidgetItem(evidence))
            self.table.item(row,3).setToolTip('Título extraído da transcrição; sem geração por IA.')
            self.table.item(row,4).setToolTip(candidate.get('text',''))
            self.table.item(row,5).setToolTip(evidence)
        if self._candidates:
            self.table.selectRow(0)
            self._load_boundaries(0)
        stats=result.get('stats',{})
        rss=stats.get('rss_mb')
        rss_label=f" · RSS {rss:.1f} MiB" if rss is not None else ''
        profile=stats.get('profile','Geral')
        mode=stats.get('mode','Equilibrado')
        status_text=(f"{len(self._candidates)} candidato(s) · {len(self._events)} evento(s) acústico(s) · "
            f"{stats.get('elapsed_seconds',0):.2f}s · cache {stats.get('cache_hits',0)} hit(s)/"
            f"{stats.get('cache_misses',0)} novo(s) · decodificados {stats.get('decoded_seconds',0):.1f}s"
            +rss_label+f" · {mode} · perfil {profile}. A nota usa somente evidências disponíveis.")
        if not self._candidates:
            warnings=[str(warning) for clip in result.get('clips',[])
                      for warning in clip.get('warnings',[]) if warning]
            if warnings:status_text+=' '+warnings[0]
        self.status.setText(status_text)

    def _selected_candidate(self):
        row=self.table.currentRow()
        if row<0 and self.table.rowCount():row=0
        item=self.table.item(row,0) if row>=0 else None
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    @staticmethod
    def _fill_boundary(combo,choices,selected_ms):
        combo.clear()
        for choice in choices:
            at=int(choice['ms'])
            combo.addItem(f"{at/1000:.2f}s · {choice.get('word','')}",at)
        index=combo.findData(int(selected_ms))
        combo.setCurrentIndex(max(0,index))

    def _load_boundaries(self,row):
        if row<0 or row>=self.table.rowCount():return
        candidate=self.table.item(row,0).data(Qt.ItemDataRole.UserRole)
        if not candidate:return
        self._updating_boundaries=True
        self._fill_boundary(self.start_boundary,candidate.get('start_choices',[]),
                            candidate['start_ms'])
        self._fill_boundary(self.end_boundary,candidate.get('end_choices',[]),
                            candidate['end_ms'])
        self.start_boundary.setEnabled(bool(candidate.get('start_choices')))
        self.end_boundary.setEnabled(bool(candidate.get('end_choices')))
        self._updating_boundaries=False

    def _boundary_changed(self,which):
        if self._updating_boundaries:return
        candidate=self._selected_candidate()
        if not candidate:return
        start=(int(self.start_boundary.currentData()) if which=='start'
               else int(candidate['start_ms']))
        end=(int(self.end_boundary.currentData()) if which=='end'
             else int(candidate['end_ms']))
        minimum=int(candidate.get('min_duration_ms',0))
        maximum=int(candidate.get('max_duration_ms',10**12))
        if not minimum<=end-start<=maximum:
            self._updating_boundaries=True
            if which=='start':
                valid=[choice for choice in candidate.get('end_choices',[])
                       if minimum<=int(choice['ms'])-start<=maximum]
                if valid:
                    chosen=min(valid,key=lambda choice:abs(int(choice['ms'])-int(candidate['end_ms'])))
                    self._fill_boundary(self.end_boundary,valid,int(chosen['ms']))
                    end=int(chosen['ms'])
                else:
                    self._fill_boundary(self.start_boundary,candidate.get('start_choices',[]),
                                        int(candidate['start_ms']))
                    self._updating_boundaries=False
                    return
            else:
                valid=[choice for choice in candidate.get('start_choices',[])
                       if minimum<=end-int(choice['ms'])<=maximum]
                if valid:
                    chosen=min(valid,key=lambda choice:abs(int(choice['ms'])-int(candidate['start_ms'])))
                    self._fill_boundary(self.start_boundary,valid,int(chosen['ms']))
                    start=int(chosen['ms'])
                else:
                    self._fill_boundary(self.end_boundary,candidate.get('end_choices',[]),
                                        int(candidate['end_ms']))
                    self._updating_boundaries=False
                    return
            self._updating_boundaries=False
        if start==candidate['start_ms'] and end==candidate['end_ms']:return
        candidate=dict(candidate)
        candidate.update({'start_ms':start,'end_ms':end,'source_start':start/1000.,
            'source_end':end/1000.,'duration':(end-start)/1000.,'score_adjusted':True})
        spans=[word for word in candidate.get('word_spans',[])
               if int(word['start_ms'])>=start and int(word['end_ms'])<=end]
        candidate['text']=' '.join(str(word['text']) for word in spans).strip()
        if candidate.get('transcript_available',True):
            candidate['suggested_title']=suggest_title(candidate['text'])
        warning=('Bordas ajustadas por tempo; confirme o acontecimento no preview.'
                 if not candidate.get('transcript_available',True) else
                 'Bordas ajustadas por palavra; a nota original não foi recalculada.')
        if warning not in candidate['warnings']:candidate['warnings'].append(warning)
        row=self.table.currentRow()
        self.table.item(row,0).setData(Qt.ItemDataRole.UserRole,candidate)
        self.table.item(row,2).setText(
            f"{candidate['source_start']:.2f}–{candidate['source_end']:.2f}s  ·  {candidate['duration']:.1f}s")
        self.table.item(row,3).setText(candidate['suggested_title'])
        self.table.item(row,4).setText(candidate['text'] or
            ('Sem transcrição · candidato baseado apenas em sinais observados'
             if not candidate.get('transcript_available',True) else ''))
        self.table.item(row,5).setText('; '.join(candidate['reasons'])+'  ⚠ '+
                                      '; '.join(candidate['warnings']))

    def _preview_current(self):
        candidate=self._selected_candidate()
        if candidate:self.preview_requested.emit(candidate)

    def _set_all(self,value):
        for row in range(self.table.rowCount()):
            self.table.item(row,0).setCheckState(
                Qt.CheckState.Checked if value else Qt.CheckState.Unchecked)

    def selected_candidates(self):
        return [self.table.item(row,0).data(Qt.ItemDataRole.UserRole)
            for row in range(self.table.rowCount())
            if self.table.item(row,0).checkState()==Qt.CheckState.Checked]

    def _insert(self):
        candidates=self.selected_candidates()
        if candidates:self.insert_requested.emit(candidates)

    def _mark_events(self):
        if self._events:self.markers_requested.emit(self._events)

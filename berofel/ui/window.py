"""Janela principal do BerofelStudio."""
from __future__ import annotations
import copy
import os
import tempfile
import threading
from dataclasses import replace as dataclass_replace
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QThreadPool, QTimer, QSize, Signal, QSettings
from PySide6.QtGui import QAction, QKeySequence, QPixmap, QPainter, QPainterPath, QColor, QFontDatabase, QFont
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QPushButton,
    QLabel, QFileDialog, QMessageBox, QScrollArea,
    QCheckBox, QDialog, QDialogButtonBox, QProgressBar,
    QToolButton, QFrame, QStackedWidget, QLineEdit,
    QTextEdit, QSizePolicy, QInputDialog, QApplication, QTabWidget,
    QAbstractScrollArea
)
from .wheel_controls import (WheelGuardComboBox as QComboBox,
    WheelGuardDoubleSpinBox as QDoubleSpinBox, WheelGuardSpinBox as QSpinBox,
    WheelGuardSlider as QSlider)
from berofel import __version__
from berofel.core.project import Project, Clip, new_id
from berofel.core.motion import ANIMATABLE, value_at, put_keyframe, delete_keyframe
from berofel.services.ffmpeg import media_info, supports_filter
from berofel.services.export_multitrack import export_audio_wav
from berofel.services.proxies import create_proxy, find_proxy
from berofel.services.analysis import analyze_clips, repetitions_clips
from berofel.services.ai_pipeline import AIOptions, run_analysis, default_llama_cli, default_qwen_model
from berofel.services.batch_editing import plan_actions, run_edit_queue, apply_reviewed_cuts
from berofel.services.subtitles import merge_reports, export_srt, timeline_words
from berofel.services.action_scope import (ScopeSpec, resolve_scope, scope_summary,
    local_to_original_proposal, scope_is_still_valid)
from berofel.services.caption_actions import (create_manual_caption, create_auto_captions,
    export_scoped_srt, scoped_cues)
from berofel.services.transcript_coverage import (record_coverage,has_coverage,words_in_clip)
from berofel.services.clipper import analyze_clips as analyze_clip_candidates
from berofel.ui.actions_panel import ActionsPanel, format_timecode
from berofel.ui.clipper_dialog import ClipperDialog
from berofel.services.export_multitrack import export_project, render_frame
from berofel.services.preview_pipeline import prepare_commands
from berofel.ui.live_preview import LivePreview
from berofel.ui.narration_stream import NarrationStreamPlayer
from berofel.services.tasks import Task
from berofel.ui.timeline import TimelineWidget
from berofel.ui.process_panel import ProcessPanel, make_processing_error_dialog
from berofel.ui.narration_panel import NarrationPanel
from berofel.ui.caption_panel import CaptionPanel
from berofel.ui.studio_header import StudioHeader
from berofel.ui.library_panel import LibraryDock
from berofel.ui.preview_transport import PreviewTransport
from berofel.services.narration_service import NarrationRequest, generate_narration, validate_request
from berofel.services.project_recovery import (newer_autosave_project, load_project,
    write_autosave_snapshot)

MEDIA_FILTER=('Midias (*.mp4 *.mov *.mkv *.avi *.webm *.mp3 *.wav *.m4a '
              '*.flac *.ogg *.png *.jpg *.jpeg *.bmp *.webp);;Todos os arquivos (*)')
IMAGES={'.png','.jpg','.jpeg','.bmp','.webp'}
_REGISTERED_UI_FONT_IDS=[]


def _register_windows_ui_fonts():
    """Register system UI fonts when the Qt platform plugin misses Windows fonts."""
    if os.name!='nt' or QApplication.instance() is None:
        return
    families=set(QFontDatabase.families())
    fonts_dir=Path(os.environ.get('WINDIR',r'C:\Windows'))/'Fonts'
    fonts=(('segoeui.ttf','Segoe UI'),('segoeuib.ttf','Segoe UI'),
           ('segoeuii.ttf','Segoe UI'),('seguisym.ttf','Segoe UI Symbol'),
           ('seguiemj.ttf','Segoe UI Emoji'))
    for filename,family in fonts:
        if family in families:continue
        font_path=fonts_dir/filename
        if not font_path.is_file():
            continue
        font_id=QFontDatabase.addApplicationFont(str(font_path))
        if font_id>=0:
            _REGISTERED_UI_FONT_IDS.append(font_id)
            families.update(QFontDatabase.applicationFontFamilies(font_id))


class InspectorGroup(QWidget):
    """Grupo expansível compacto para o inspector contextual."""
    def __init__(self,title,parent=None):
        super().__init__(parent)
        self.setObjectName('inspectorGroup')
        root=QVBoxLayout(self);root.setContentsMargins(0,0,0,0);root.setSpacing(3)
        self.toggle=QToolButton();self.toggle.setObjectName('inspectorGroupButton')
        self.toggle.setText('⌄  '+title);self.toggle.setCheckable(True);self.toggle.setChecked(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow)
        self.toggle.toggled.connect(self._toggle)
        root.addWidget(self.toggle)
        self.body=QWidget();self.body.setObjectName('inspectorGroupBody')
        self.body_layout=QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(8,2,5,7);self.body_layout.setSpacing(5)
        root.addWidget(self.body)

    def _toggle(self,expanded):
        self.body.setVisible(expanded)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)


class PreviewImage(QWidget):
    """Nao deforma a previa e oferece arraste direto da camada selecionada."""
    transformed = Signal(int,int)
    scale_requested = Signal(float)
    import_requested = Signal()
    def __init__(self,parent=None):
        super().__init__(parent)
        self.pixmap=None
        self.hint='Importe uma mídia. A prévia mostrará todas as camadas juntas.'
        self.setMinimumHeight(100)
        self.selection=None
        self.selection_time=0.0
        self.canvas=(1280,720)
        self._drag_origin=None
        self._drag_delta=(0.0,0.0)
        self.preview_text=None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName('Importar vídeo')
        self.setAccessibleDescription('Botão de importação na tela inicial da prévia.')

    def set_image(self, image):
        pix=QPixmap.fromImage(image)
        if not pix.isNull():
            self.pixmap=pix
            self.update()

    def load(self,path):
        pix=QPixmap(str(path))
        if not pix.isNull():
            self.pixmap=pix
            self.update()

    def set_selection(self,clip,width,height,at=0.0):
        if clip is not self.selection:self.preview_text=None
        self.selection=clip
        self.selection_time=at
        self.canvas=(max(1,width),max(1,height))
        self.update()

    def set_preview_text(self,text):
        self.preview_text=str(text)
        self.update()

    def _image_geometry(self):
        if self.pixmap:
            size=self.pixmap.size()
            ratio=min(self.width()/max(1,size.width()),self.height()/max(1,size.height()))
            w,h=size.width()*ratio,size.height()*ratio
        else:
            ratio=min(self.width()/self.canvas[0],self.height()/self.canvas[1])
            w,h=self.canvas[0]*ratio,self.canvas[1]*ratio
        return ((self.width()-w)/2,(self.height()-h)/2,w,h)

    def mousePressEvent(self,event):
        if self.pixmap is None and self.selection is None and event.button()==Qt.MouseButton.LeftButton:
            rect=self._welcome_button_rect()
            if rect.contains(event.position().toPoint()):
                self.import_requested.emit()
                event.accept();return
        if self.selection is not None and event.button()==Qt.MouseButton.LeftButton:
            x,y,w,h=self._image_geometry()
            if x<=event.position().x()<=x+w and y<=event.position().y()<=y+h:
                self._drag_origin=event.position()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept();return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self,event):
        if self._drag_origin is not None:
            dx=event.position().x()-self._drag_origin.x()
            dy=event.position().y()-self._drag_origin.y()
            _,_,w,h=self._image_geometry()
            self._drag_origin=None
            self._drag_delta=(0.0,0.0)
            self.unsetCursor()
            if abs(dx)+abs(dy)>=2:
                self.transformed.emit(round(dx*self.canvas[0]/max(1,w)),round(dy*self.canvas[1]/max(1,h)))
            event.accept();return
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self,event):
        if self._drag_origin is not None:
            self._drag_delta=(event.position().x()-self._drag_origin.x(),
                              event.position().y()-self._drag_origin.y())
            self.update()
            event.accept();return
        super().mouseMoveEvent(event)

    def keyPressEvent(self,event):
        if (self.pixmap is None and self.selection is None and
                event.key() in (Qt.Key.Key_Return,Qt.Key.Key_Enter,Qt.Key.Key_Space)):
            self.import_requested.emit()
            event.accept();return
        super().keyPressEvent(event)

    def wheelEvent(self,event):
        if self.selection is not None and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.scale_requested.emit(1.1 if event.angleDelta().y()>0 else 1/1.1)
            event.accept();return
        super().wheelEvent(event)

    def paintEvent(self,event):
        p=QPainter(self)
        p.fillRect(self.rect(),QColor('#070c15'))
        if self.pixmap:
            rect=self.rect()
            scaled=self.pixmap.scaled(rect.size(),Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation)
            x=(rect.width()-scaled.width())//2
            y=(rect.height()-scaled.height())//2
            p.drawPixmap(x,y,scaled)
        else:
            from PySide6.QtCore import QRectF
            cx,cy=self.width()/2,self.height()/2
            compact=self.height()<145
            play=QPainterPath()
            play_y=cy-31 if compact else cy-46
            play.moveTo(cx-8,play_y-12);play.lineTo(cx+13,play_y);play.lineTo(cx-8,play_y+12);play.closeSubpath()
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#ff8126'));p.drawPath(play)
            p.setPen(QColor('#eef2f7'))
            title_font=QFont(self.font());title_font.setBold(True);title_font.setPointSize(max(11,title_font.pointSize()+2))
            p.setFont(title_font)
            title_y=cy-10 if compact else cy-29
            p.drawText(QRectF(20,title_y,self.width()-40,24 if compact else 30),
                       int(Qt.AlignmentFlag.AlignCenter),'Seu vídeo aparece aqui')
            if not compact:
                p.setFont(self.font());p.setPen(QColor('#91a6bf'))
                p.drawText(QRectF(20,cy+3,self.width()-40,25),int(Qt.AlignmentFlag.AlignCenter),
                           'Importe uma mídia para começar a edição')
            button=self._welcome_button_rect()
            p.setPen(QColor('#ff9b4e'));p.setBrush(QColor('#ff8126'))
            p.drawRoundedRect(QRectF(button),6 if compact else 7,6 if compact else 7)
            p.setPen(QColor('#24170f'))
            button_font=QFont(self.font());button_font.setBold(True);p.setFont(button_font)
            p.drawText(QRectF(button),int(Qt.AlignmentFlag.AlignCenter),'Importar vídeo')
        if self.selection is not None:
            from PySide6.QtCore import QRectF
            x,y,w,h=self._image_geometry()
            scale=max(.05,float(value_at(self.selection,'scale',self.selection_time)))
            px=x+w/2+value_at(self.selection,'pos_x',self.selection_time)*w/self.canvas[0]
            py=y+h/2+value_at(self.selection,'pos_y',self.selection_time)*h/self.canvas[1]
            if self._drag_origin is not None:
                px+=self._drag_delta[0];py+=self._drag_delta[1]
            box=QRectF(px-w*scale*.45,py-h*scale*.45,w*scale*.9,h*scale*.9)
            p.save()
            p.translate(px,py)
            p.rotate(value_at(self.selection,'rotation',self.selection_time))
            p.setPen(QColor('#71d9fe'))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(-w*scale*.45,-h*scale*.45,w*scale*.9,h*scale*.9))
            for hx,hy in ((-w*scale*.45,-h*scale*.45),(w*scale*.45,-h*scale*.45),
                          (-w*scale*.45,h*scale*.45),(w*scale*.45,h*scale*.45)):
                p.fillRect(QRectF(hx-3,hy-3,6,6),QColor('#f8d57a'))
            p.restore()
            if (self.selection.kind=='text' and
                    (self._drag_origin is not None or self.preview_text is not None)):
                from PySide6.QtCore import QRectF
                text=(self.selection.text if self.preview_text is None else self.preview_text)
                p.save();p.setFont(QFont(getattr(self.selection,'font_family','Arial'),
                                         max(8,int(self.selection.font_size*min(w/self.canvas[0],h/self.canvas[1])/1.35)),
                                         QFont.Weight.Bold))
                p.setPen(QColor(getattr(self.selection,'font_color','#FFFFFF')))
                bounds=QRectF(px-w*.43,py-h*.43,w*.86,h*.86)
                p.drawText(bounds,int(Qt.AlignmentFlag.AlignCenter|Qt.TextFlag.TextWordWrap),text)
                p.restore()
            p.setPen(QColor('#c1eaff'))
            p.drawText(int(x+5),int(y+18),'Arraste para posicionar · Ctrl+roda: escala')

    def _welcome_button_rect(self):
        from PySide6.QtCore import QRect
        width=min(144,max(116,self.width()-32))
        compact=self.height()<145
        height=30 if compact else 38
        y=self.height()//2+(16 if compact else 40)
        y=min(y,max(0,self.height()-height-4))
        return QRect((self.width()-width)//2,y,width,height)


class InfiniteTools(QScrollArea):
    """Tres copias identicas; ao cruzar limites, reposiciona invisivelmente."""
    def __init__(self,actions,parent=None):
        super().__init__(parent)
        self.setFixedHeight(52)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWidgetResizable(False)
        holder=QWidget()
        lay=QHBoxLayout(holder)
        lay.setContentsMargins(0,0,0,0)
        lay.setSpacing(5)
        self._widths=[]
        for _ in range(3):
            for label,callback in actions:
                b=QPushButton(label)
                b.setFixedHeight(37)
                w=max(84,b.sizeHint().width()+15)
                b.setFixedWidth(w)
                b.clicked.connect(callback)
                lay.addWidget(b)
                if len(self._widths)<len(actions): self._widths.append(w)
        self.cycle_width=sum(self._widths)+len(self._widths)*5
        holder.setFixedSize(self.cycle_width*3,46)
        self.setWidget(holder)
        self.horizontalScrollBar().valueChanged.connect(self._wrap)
        QTimer.singleShot(0,self._center)

    def _center(self):
        self.horizontalScrollBar().setValue(self.cycle_width)

    def _wrap(self,v):
        # Ajuste em blocos identicos, sem salto no conteudo visual.
        new=v
        if v<self.cycle_width: new=v+self.cycle_width
        elif v>=2*self.cycle_width: new=v-self.cycle_width
        if new!=v:
            sb=self.horizontalScrollBar()
            sb.blockSignals(True);sb.setValue(new);sb.blockSignals(False)

    def wheelEvent(self,event):
        dy=event.angleDelta().y() or event.angleDelta().x()
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value()-dy)
        event.accept()


class SuggestionsDialog(QDialog):
    preview_requested=Signal(str,float,float)

    def __init__(self,findings,title='Sugestoes',parent=None):
        super().__init__(parent)
        self.findings=findings
        self.setWindowTitle(title)
        # A revisão ocupa o lado direito como no editor legado, mantendo o
        # monitor principal visível para conferir a sugestão.
        parent_width=parent.width() if parent is not None else 720
        parent_height=parent.height() if parent is not None else 620
        self.resize(min(430,max(320,parent_width-24)),min(660,max(480,parent_height-28)))
        if parent is not None:
            from PySide6.QtCore import QPoint
            self.move(parent.mapToGlobal(QPoint(max(0,parent_width-self.width()-10),
                                                max(0,parent_height-self.height()-8))))
        root=QVBoxLayout(self)
        info=QLabel('ASSISTENTE LOCAL  ·  REVISÃO HUMANA')
        info.setStyleSheet('color:#ffad70;font-weight:850;font-size:12px;letter-spacing:.5px;')
        root.addWidget(info)
        description=QLabel('Confira o intervalo e o motivo sugeridos. “Manter” e “Cortar” alteram apenas '
                    'a seleção desta revisão; os arquivos originais permanecem intactos.')
        description.setWordWrap(True);root.addWidget(description)

        navigation=QHBoxLayout()
        self.review_position=QLabel('Sugestão 0 de 0')
        self.review_position.setStyleSheet('color:#ffab66;font-weight:750;')
        navigation.addWidget(self.review_position,1)
        self.previous_button=QPushButton('‹ Anterior')
        self.previous_button.clicked.connect(lambda:self._navigate(-1))
        navigation.addWidget(self.previous_button)
        self.next_button=QPushButton('Próxima ›')
        self.next_button.clicked.connect(lambda:self._navigate(1))
        navigation.addWidget(self.next_button)
        root.addLayout(navigation)

        card=QFrame();card.setObjectName('suggestionReviewCard')
        card.setStyleSheet('QFrame#suggestionReviewCard{background:#202329;border:1px solid #454b54;'
                           'border-left:3px solid #f5822b;border-radius:6px;}')
        card_layout=QVBoxLayout(card);card_layout.setContentsMargins(10,8,10,8);card_layout.setSpacing(4)
        interval_label=QLabel('INTERVALO SUGERIDO')
        interval_label.setStyleSheet('color:#aab2bd;font-size:9px;font-weight:800;letter-spacing:.7px;')
        card_layout.addWidget(interval_label)
        self.review_interval=QLabel('');self.review_interval.setWordWrap(True)
        self.review_interval.setStyleSheet('color:#f2f4f7;font-weight:750;font-size:13px;')
        card_layout.addWidget(self.review_interval)
        self.review_reason=QLabel('');self.review_reason.setWordWrap(True)
        self.review_reason.setStyleSheet('color:#bac2cc;')
        card_layout.addWidget(self.review_reason)
        self.preview_button=QPushButton('▶  Ver trecho no monitor')
        self.preview_button.setToolTip('Busca o trecho na timeline e reproduz pela prévia principal do projeto.')
        self.preview_button.clicked.connect(self._preview_current)
        card_layout.addWidget(self.preview_button)
        decision_row=QHBoxLayout()
        self.keep_button=QPushButton('✓ Manter')
        self.keep_button.setToolTip('Retira esta sugestão da seleção de cortes.')
        self.keep_button.setStyleSheet('QPushButton{background:#292e34;border:1px solid #505660;'
                                       'color:#e6ebf0;font-weight:700;padding:6px 12px;}')
        self.keep_button.clicked.connect(lambda:self._set_current(False))
        decision_row.addWidget(self.keep_button)
        self.cut_button=QPushButton('✂ Cortar')
        self.cut_button.setToolTip('Inclui esta sugestão na seleção de cortes a aplicar.')
        self.cut_button.setStyleSheet('QPushButton{background:#ff8126;border:1px solid #ff9a4e;'
                                      'color:#24170f;font-weight:800;padding:6px 12px;}')
        self.cut_button.clicked.connect(lambda:self._set_current(True))
        decision_row.addWidget(self.cut_button)
        card_layout.addLayout(decision_row);root.addWidget(card)

        bulk_info=QLabel('TODAS AS SUGESTÕES  ·  escolha por item ou use a seleção em massa')
        bulk_info.setStyleSheet('color:#ffad70;font-size:10px;font-weight:800;')
        root.addWidget(bulk_info)
        filters=QHBoxLayout()
        filters.addWidget(QLabel('Tipo:'))
        self.filter_type=QComboBox()
        self.filter_type.addItem('Todos os tipos','all')
        type_labels={'silencio':'Silêncio · Silero','contexto':'Contexto · Qwen',
                     'repeticao':'Repetições','filler':'Vícios de fala'}
        types=sorted({str(f.get('type') or 'outro') for f in findings})
        for kind in types:
            self.filter_type.addItem(type_labels.get(kind,kind.capitalize()),kind)
        filters.addWidget(self.filter_type)
        self.filter_search=QLineEdit()
        self.filter_search.setPlaceholderText('Buscar clipe, motivo ou texto…')
        self.filter_search.setClearButtonEnabled(True)
        filters.addWidget(self.filter_search,1)
        root.addLayout(filters)
        self.filter_count=QLabel('')
        self.filter_count.setObjectName('suggestionFilterCount')
        root.addWidget(self.filter_count)
        scroll=QScrollArea();scroll.setWidgetResizable(True)
        inside=QWidget();lay=QVBoxLayout(inside)
        self.checks=[]
        for f in findings:
            note=f.get('note','Silêncio detectado')
            score=(f"  |  Nota sugerida: {f['score']}/100" if f.get('type')=='contexto' and
                   f.get('score') is not None else '')
            c=QCheckBox(f"{f['title']}  {f['a']:.2f}–{f['b']:.2f}s  {note}{score}")
            c.setStyleSheet('QCheckBox{spacing:8px;}')
            c.setToolTip('Tempos relativos ao bloco selecionado, nunca ao vídeo inteiro.')
            c.setChecked(f.get('checked',False))
            lay.addWidget(c);self.checks.append(c)
        lay.addStretch();scroll.setWidget(inside);root.addWidget(scroll)
        bulk=QHBoxLayout()
        select_visible=QPushButton('✓ Marcar visíveis')
        select_visible.setToolTip('Marca apenas as sugestões que passam pelos filtros atuais.')
        select_visible.clicked.connect(lambda:self._set_visible(True))
        bulk.addWidget(select_visible)
        clear_visible=QPushButton('Desmarcar visíveis')
        clear_visible.clicked.connect(lambda:self._set_visible(False))
        bulk.addWidget(clear_visible)
        root.addLayout(bulk)
        bulk=QHBoxLayout()
        select_all=QPushButton('✓ Selecionar TODOS')
        select_all.setToolTip('Marca de uma vez todas as sugestões, mesmo que haja centenas.')
        select_all.clicked.connect(lambda:self._set_all(True))
        bulk.addWidget(select_all)
        self.approve_all_button=QPushButton('✂ Aprovar e aplicar TODOS')
        self.approve_all_button.setObjectName('approveAllCuts')
        self.approve_all_button.setToolTip(
            'Aplica imediatamente todos os cortes sugeridos; o projeto continua com Undo.')
        self.approve_all_button.setEnabled(bool(self.findings))
        self.approve_all_button.clicked.connect(self._approve_all)
        bulk.addWidget(self.approve_all_button)
        deselect=QPushButton('Desmarcar todos')
        deselect.clicked.connect(lambda:self._set_all(False))
        bulk.addWidget(deselect)
        root.addLayout(bulk)
        self.counter=QLabel('')
        self.counter.setStyleSheet('color:#a2c8ff;font-weight:bold;')
        root.addWidget(self.counter)
        self.current_index=0
        for index,cb in enumerate(self.checks):
            cb.stateChanged.connect(lambda _state,i=index:self._select_changed(i))
        self.filter_type.currentIndexChanged.connect(self._apply_filters)
        self.filter_search.textChanged.connect(self._apply_filters)
        self._apply_filters()
        self._update_count()
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|
                                  QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Aplicar apenas os marcados')
        skip=buttons.addButton('Pular cortes',QDialogButtonBox.ButtonRole.ActionRole)
        skip.setToolTip('Preserva transcrição e legendas solicitadas, sem cortar nenhum trecho.')
        skip.clicked.connect(lambda:self.done(2))
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _approve_all(self):
        if not self.findings:return
        self._set_all(True)
        self.accept()

    def _preview_current(self):
        if not self.findings:return
        finding=self.findings[self.current_index]
        self.preview_requested.emit(str(finding.get('clip_id','')),
                                    float(finding.get('a',0)),float(finding.get('b',0)))

    def _set_all(self, checked: bool):
        for box in self.checks:
            box.blockSignals(True)
            box.setChecked(checked)
            box.blockSignals(False)
        self._update_count()

    def _set_visible(self,checked: bool):
        for box in self.checks:
            if box.isHidden():continue
            box.blockSignals(True);box.setChecked(checked);box.blockSignals(False)
        self._update_count()

    def _apply_filters(self,*_):
        kind=self.filter_type.currentData()
        query=self.filter_search.text().strip().casefold()
        visible=[]
        for index,(finding,box) in enumerate(zip(self.findings,self.checks)):
            matches_type=kind=='all' or str(finding.get('type') or 'outro')==kind
            text=' '.join(str(finding.get(key,'')) for key in
                          ('title','note','a','b','text')).casefold()
            matches_text=not query or query in text
            shown=matches_type and matches_text
            box.setVisible(shown)
            if shown:visible.append(index)
        self.filter_count.setText(f'{len(visible)} de {len(self.checks)} sugestões visíveis')
        if visible and self.current_index not in visible:
            self.current_index=visible[0]
        self._update_current()

    def _visible_indices(self):
        return [index for index,box in enumerate(self.checks) if not box.isHidden()]

    def _select_changed(self,index):
        self.current_index=index
        self._update_count()

    def _navigate(self,delta):
        visible=self._visible_indices()
        if not visible:return
        current=visible.index(self.current_index) if self.current_index in visible else 0
        self.current_index=visible[(current+delta)%len(visible)]
        self._update_current()

    def _set_current(self,checked):
        if not self.checks:return
        box=self.checks[self.current_index]
        box.blockSignals(True);box.setChecked(checked);box.blockSignals(False)
        self._update_count()

    def _update_count(self, *args):
        n=sum(c.isChecked() for c in self.checks)
        self.counter.setText(f'{n} de {len(self.checks)} cortes selecionados · '
                             f'{len(self._visible_indices())} visíveis')
        self._update_current()

    def _update_current(self):
        total=len(self.checks)
        visible=self._visible_indices()
        if not visible:
            self.review_position.setText('Nenhuma sugestão visível')
            self.review_interval.setText('Altere os filtros para mostrar sugestões.')
            self.review_reason.setText('')
            self.previous_button.setEnabled(False);self.next_button.setEnabled(False)
            self.keep_button.setEnabled(False);self.cut_button.setEnabled(False)
            return
        if self.current_index not in visible:self.current_index=visible[0]
        finding=self.findings[self.current_index]
        if len(visible)==total:
            position=f'Sugestão {visible.index(self.current_index)+1} de {total}'
        else:
            position=(f'Sugestão {visible.index(self.current_index)+1} de '
                      f'{len(visible)} visíveis · {total} total')
        self.review_position.setText(position)
        self.review_interval.setText(
            f"{finding.get('title','Trecho')}  ·  {finding.get('a',0):.2f}–{finding.get('b',0):.2f}s")
        self.review_reason.setText('Por que a IA marcou: '+str(finding.get('note','Revisão manual solicitada.')))
        self.previous_button.setEnabled(len(visible)>1);self.next_button.setEnabled(len(visible)>1)
        self.keep_button.setEnabled(True);self.cut_button.setEnabled(True)

    def accepted_findings(self):
        return [f for f,c in zip(self.findings,self.checks) if c.isChecked()]


class TranscriptDialog(QDialog):
    def __init__(self, reports, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Transcricao - tempos das palavras salvos no projeto')
        self.resize(750, 510)
        layout=QVBoxLayout(self)
        message=QLabel('Transcricao dos blocos selecionados. Os tempos sao relativos a cada bloco. '
                       'O cache e persistente e a legenda SRT usa os tempos da timeline apos cortes.')
        message.setWordWrap(True)
        layout.addWidget(message)
        edit=QTextEdit(self)
        edit.setReadOnly(True)
        sections=[]
        for r in reports:
            lines=[f"[{w['start']:.2f}-{w['end']:.2f}] {w['text']}" for w in r['words']]
            sections.append(f"=== {r['title']} - {len(r['words'])} palavras ===\n" + '\n'.join(lines))
        edit.setPlainText('\n\n'.join(sections) or '(Nenhuma palavra reconhecida)')
        layout.addWidget(edit)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        _register_windows_ui_fonts()
        self.project=Project()
        self.history=[]
        self.future=[]
        self._clip_clipboard=[]
        self._voice_adjustment_clipboard=None
        self.selected_ids=[]
        self._voice_eq_snapshot_pending=False
        self.active_track_id=self.project.tracks[0].id
        self.workers=set()
        self._autosave_task=None
        self._project_io_lock=threading.Lock()
        self._closing=False
        self._open_error_dialogs=set()
        self._ai_busy=False
        self.active_task=None
        self._clipper_dialog=None
        self._clipper_task=None
        self.media_cache={}
        self.active_clip_id=None
        self._pending_source_ms=None
        self._preview_token=0
        self._render_seq=0
        self._preview_files=[]
        self._playback_snapshot = None
        self._playback_settings = (640, 24)
        self._preview_next_pending = False
        self._review_preview_end = None
        # Sugestões permanecem disponíveis para revisão manual se o diálogo
        # for fechado; o passo Revisar do fluxo legado pode reabri-las.
        self._pending_review_findings = copy.deepcopy(self.project.review_queue) or None
        self._pending_review_title = self.project.review_title
        self._auto_key=True
        self._selected_keyfield='scale' 
        self.setWindowTitle(f'BerofelStudio — Studio {__version__} · Prévia Contínua')
        # Usa a area real DISPONIVEL do monitor em coordenadas Qt/DPI,
        # em vez de fixar uma resolucao que pode sair das bordas.
        screen=QApplication.primaryScreen()
        if screen:
            available=screen.availableGeometry()
            w=max(1,available.width()-18)
            h=max(1,available.height()-18)
            self._screen_available_width=w
            self.resize(min(1360,w),min(850,h))
            self.setMinimumSize(min(630,w),min(490,h))
        else:
            self._screen_available_width=1200
            self.resize(1200,760)
            self.setMinimumSize(630,490)
        self._build()
        self._hide_auxiliary_scrollbars()
        self._restore_ui_state()
        self.live=LivePreview(self)
        self.live.frame_ready.connect(self._live_frame)
        self.live.position_changed.connect(self._live_position)
        self.live.playing_changed.connect(self._live_state)
        self.live.status_changed.connect(self.statusBar().showMessage)
        self.live.failed.connect(self._live_error)
        self.live.voice_control_failed.connect(self._live_voice_control_error)
        self.live.reached_end.connect(lambda:self.statusBar().showMessage('Fim da timeline.'))
        self.live.next_requested.connect(self._prepare_next_preview_window)
        self._frame_debounce=QTimer(self)
        self._frame_debounce.setSingleShot(True)
        self._frame_debounce.setInterval(230)
        self._frame_debounce.timeout.connect(self._render_static_on_seek)
        self._theme()
        self._fit_timeline_toolbar()
        self._shortcuts()
        self.refresh()
        self.autosave=QTimer(self)
        self.autosave.timeout.connect(self._autosave)
        self.autosave.start(120_000)

    def _hide_auxiliary_scrollbars(self):
        """Keep content scrollable while reserving visible bars for the timeline."""
        for area in self.findChildren(QAbstractScrollArea):
            if area is self.timeline.view:
                continue
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def _pane_minimum(self,preferred):
        # Reserva handles e margens mesmo em telas pequenas/DPI alto.
        budget=max(80,int((self._screen_available_width-32)/3))
        return min(int(preferred),budget)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        tabs=getattr(self,'side_tabs',None)
        if tabs is not None:
            minimum=self._pane_minimum(150)
            if tabs.minimumWidth()!=minimum:tabs.setMinimumWidth(minimum)
            self._apply_compact_tabs(event.size().width()<1180)

    def _apply_compact_tabs(self,compact):
        if not hasattr(self,'side_tabs'):return
        labels=('IA','Clipes','Voz','Leg.') if compact else (
            'Assistente IA','Propriedades','🎙 Narração','Legendas')
        full=('Assistente IA','Propriedades','Narração','Legendas')
        for index,(label,name) in enumerate(zip(labels,full)):
            self.side_tabs.setTabText(index,label)
            self.side_tabs.setTabToolTip(index,name)
            self.side_tabs.setTabWhatsThis(index,name)

    def _build(self):
        root=QWidget();self.setCentralWidget(root)
        outer=QVBoxLayout(root)
        outer.setContentsMargins(7,7,7,7)
        outer.setSpacing(5)
        self.header=StudioHeader(__version__,self)
        self.project_name=self.header.project_name
        self.header.project_action.connect(self._header_project_action)
        self.header.stage_requested.connect(self._header_stage_action)
        self.process_panel=ProcessPanel(self.header,compact=True)
        self.header.set_task_widget(self.process_panel)
        outer.addWidget(self.header)

        actions=[('Importar',self.import_media),('+ Bloco',self.add_media),
                 ('+ Texto',self.add_title),('+ Camada',self.add_track),
                 ('Dividir [Ctrl+K]',self.split_at_cursor),('Excluir [Del]',self.delete_clips),
                 ('Desfazer',self.undo),('Refazer',self.redo),
                 ('Ajustar timeline',self.fit_timeline),
                 ('Marcador [M]',self.add_marker),
                 ('Ripple excluir',self.ripple_delete_selected),
                 ('Roll · ajustar emenda',self.roll_edit_selected),
                 ('Dissolvência',self.make_transition),
                 ('Agrupar',self.group_selected),('Separar áudio',self.separate_audio),
                 ('Criar proxies',self.create_proxies),
                 ('⚙ Ações IA · escolher alcance',self.open_actions),
                 ('▶ Edição completa · marcar funções',self.open_actions),
                 ('Somente transcrever',self.transcribe_selected),
                 ('Somente silêncios · Silero',self.analyze_intelligent),
                 ('Vícios de linguagem · Qwen',self.analyze_semantic),
                 ('Legenda automática',lambda:self.execute_modular('subtitles')),
                 ('Exportar SRT do alcance',lambda:self.execute_modular('srt')),
                 ('Exportar WAV da timeline',self.export_audio),
                 ('Silêncios FFmpeg · alternativo',self.analyze_silence),
                 ('Quadro final',self.render_current_frame),
                 ('Prévia MP4 (reserva)',self.preview_mp4_fallback),
                 ('🎨 Cor e recorte',self.open_color_controls),
                 ('🎙 Narração Qwen3 Base',self.open_narration)]
        self.tools=InfiniteTools(actions)
        outer.addWidget(self.tools)
        self.tools.setVisible(False)

        self.workspace_splitter=QSplitter(Qt.Orientation.Vertical)
        self.workspace_splitter.setObjectName('workspaceSplitter')
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.setHandleWidth(6)
        outer.addWidget(self.workspace_splitter,1)
        editor_area=QWidget()
        editor_layout=QVBoxLayout(editor_area)
        editor_layout.setContentsMargins(0,0,0,0)
        editor_layout.setSpacing(5)

        self.horizontal=QSplitter(Qt.Orientation.Horizontal)
        self.horizontal.setChildrenCollapsible(False)
        self.horizontal.setHandleWidth(5)
        editor_layout.addWidget(self.horizontal,1)

        self.tool_scroll=QScrollArea()
        self.tool_scroll.setObjectName('timelineToolScroll')
        self.tool_scroll.setWidgetResizable(True)
        self.tool_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.tool_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tool_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tool_scroll.setFixedHeight(38)
        self.timeline_tool_holder=QWidget()
        self.timeline_tool_layout=QHBoxLayout(self.timeline_tool_holder)
        self.timeline_tool_layout.setContentsMargins(2,0,2,0)
        self.timeline_tool_layout.setSpacing(3)
        self.timeline_tool_buttons=[]
        self.tool_scroll.setWidget(self.timeline_tool_holder)
        self.tool_rail=self.tool_scroll  # compatibilidade com atalhos/temas antigos

        # Biblioteca lateral: categorias e filtros ficam na UI; arquivos e
        # operações editoriais permanecem no projeto canônico atual.
        self.library=LibraryDock(self)
        self.library.setMinimumWidth(self._pane_minimum(160))
        self.media_list=self.library.media_list
        self.library.import_requested.connect(self.import_media)
        self.library.relink_requested.connect(self.relink_selected_media)
        self.library.marker_activated.connect(self.seek_to)
        self.media_list.itemDoubleClicked.connect(lambda _:self.add_media())
        self.library.add_nav_button('actions','Ações','⚙',self.open_actions)
        self.library.add_nav_button('narration','Narração','🎙',self.open_narration)
        self.library.add_nav_button('captions','Legendas','T',self.open_captions)
        self.horizontal.addWidget(self.library)

        # Preview central: stream composto (FFmpeg + Qt); MP4 é só fallback.
        center=QWidget();cl=QVBoxLayout(center);cl.setContentsMargins(5,5,5,5)
        preview_heading=self._section('PRÉVIA')
        preview_heading.setObjectName('previewHeading')
        preview_heading.setWordWrap(False)
        cl.addWidget(preview_heading)
        self.preview_stack=QStackedWidget()
        self.preview_image=PreviewImage()
        self.preview_image.import_requested.connect(self.import_media)
        self.preview_image.transformed.connect(self.move_in_preview)
        self.preview_image.scale_requested.connect(self.zoom_in_preview)
        self.video=QVideoWidget()
        self.preview_stack.addWidget(self.preview_image)
        self.preview_stack.addWidget(self.video)
        self.preview_stack.setCurrentWidget(self.preview_image)
        cl.addWidget(self.preview_stack,1)
        self.transport=PreviewTransport(self)
        self.transport.play_requested.connect(self.toggle_play)
        self.transport.seek_requested.connect(self._transport_seek)
        self.transport.frame_step_requested.connect(self.step_frame)
        self.transport.final_frame_requested.connect(self.render_current_frame)
        self.transport.volume_changed.connect(self.set_preview_volume)
        cl.addWidget(self.transport)
        # Aliases preservam o contrato interno da janela e do modo reserva.
        self.play_button=self.transport.play_button
        self.preview_quality=self.transport.quality
        self.final_frame=self.transport.final_frame_button
        self.time_label=self.transport.time_label
        self.player=QMediaPlayer(self)
        self.audio=QAudioOutput(self)
        self.narration_stream=NarrationStreamPlayer(self,
            lambda message:self.statusBar().showMessage(message,5000))
        self.audio.setVolume(.85)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        center.setMinimumWidth(self._pane_minimum(180))
        self.horizontal.addWidget(center)

        # Propriedades fixas na direita. Conteudo interno quebra verticalmente.
        self.props_scroll=QScrollArea()
        self.props_scroll.setWidgetResizable(True)
        self.props_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.props_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.props_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.props_inner=QWidget()
        self.props_layout=QVBoxLayout(self.props_inner)
        self.props_layout.setContentsMargins(7,5,7,5)
        self.props_layout.setSpacing(7)
        self.props_scroll.setWidget(self.props_inner)
        self.props_scroll.setMinimumWidth(0)
        self.side_tabs=QTabWidget()
        self.actions_panel=ActionsPanel(self)
        self.actions_panel.on_execute=self.execute_modular
        self.actions_panel.on_execute_plan=self.execute_edit_queue
        self.actions_panel.on_clipper=self.open_clipper
        self.side_tabs.addTab(self.actions_panel, 'Assistente IA')
        self.side_tabs.addTab(self.props_scroll, 'Propriedades')
        self.narration_panel=NarrationPanel(self)
        self.narration_panel.on_generate=self.generate_narration_ui
        self.narration_panel.on_prepare_voice=self.prepare_narration_voice
        self.narration_panel.on_use_transcript=self.use_selected_transcript
        self.narration_panel.on_voice_eq_begin=self.begin_voice_eq_edit
        self.narration_panel.on_voice_eq_change=self.apply_voice_eq_edit
        self.narration_panel.on_voice_speed_change=self.set_narration_speed
        self.narration_panel.on_copy_voice_adjustments=self.copy_voice_adjustments
        self.narration_panel.on_paste_voice_adjustments=self.paste_voice_adjustments
        self.side_tabs.addTab(self.narration_panel, '🎙 Narração')
        self.captions_panel=CaptionPanel(self)
        self.captions_panel.caption_selected.connect(self.select_caption_from_panel)
        self.captions_panel.add_requested.connect(self.add_caption_from_panel)
        self.captions_panel.apply_text_requested.connect(self.apply_caption_text)
        self.captions_panel.property_changed.connect(self.change_caption_property)
        self.captions_panel.preview_text_changed.connect(self.preview_caption_text)
        self.captions_panel.preset_requested.connect(self.apply_caption_preset)
        self.side_tabs.addTab(self.captions_panel, 'Legendas')
        self._apply_compact_tabs(self.width()<1180)
        self.narration_panel.setMinimumWidth(0)
        self.narration_panel.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Expanding)
        self.side_tabs.setMinimumWidth(self._pane_minimum(150))
        self.side_tabs.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Expanding)
        self.horizontal.addWidget(self.side_tabs)
        self.horizontal.setSizes([250,720,320])
        # Nenhum painel troca de posicao ao reduzir janela.

        # O progresso compacto vive no cabeçalho; não reduz altura do preview
        # nem altera o espaço reservado à timeline.
        self.workspace_splitter.addWidget(editor_area)

        # A timeline e uma area independente, horizontal linear e multilinha.
        timeline_box=QWidget()
        bl=QVBoxLayout(timeline_box)
        bl.setContentsMargins(2,2,2,2)
        bl.setSpacing(4)
        bar=QHBoxLayout()
        timeline_heading=self._section('TIMELINE | CAMADAS LIVRES')
        timeline_heading.setObjectName('timelineHeading')
        timeline_heading.setWordWrap(False)
        bar.addWidget(timeline_heading)
        bar.addWidget(self.tool_scroll,1)
        bar.addStretch()
        self.track_combo=QComboBox()
        self.track_combo.setMinimumWidth(92)
        self.track_combo.currentIndexChanged.connect(self._choose_active_track)
        bar.addWidget(QLabel('Inserir em:'))
        bar.addWidget(self.track_combo)
        plus=QPushButton('+ Camada')
        plus.clicked.connect(self.add_track)
        bar.addWidget(plus)
        add=QPushButton('+ Texto')
        add.clicked.connect(self.add_title)
        bar.addWidget(add)
        bl.addLayout(bar)
        # Ferramentas compactas ficam ao lado do cabeçalho da timeline.
        self.select_tool_btn=QToolButton();self.select_tool_btn.setText('↖ V')
        self.select_tool_btn.setObjectName('timelineSelectTool')
        self.select_tool_btn.setCheckable(True);self.select_tool_btn.setChecked(True)
        self.select_tool_btn.setToolTip('Selecionar e mover clipes ou ajustar suas bordas [V]')
        self.select_tool_btn.setAccessibleName('Selecionar [V]')
        self.select_tool_btn.clicked.connect(self.activate_select)
        self._add_timeline_tool(self.select_tool_btn)
        self.blade_tool_btn=QToolButton();self.blade_tool_btn.setText('✂ B')
        self.blade_tool_btn.setObjectName('timelineBladeTool')
        self.blade_tool_btn.setCheckable(True)
        self.blade_tool_btn.setToolTip('Ativar a lâmina; clique num clipe para dividir [B]')
        self.blade_tool_btn.setAccessibleName('Lâmina [B]')
        self.blade_tool_btn.clicked.connect(self.activate_blade)
        self._add_timeline_tool(self.blade_tool_btn)
        self.slide_tool_btn=QToolButton();self.slide_tool_btn.setText('↔ G')
        self.slide_tool_btn.setObjectName('timelineSlideTool')
        self.slide_tool_btn.setCheckable(True)
        self.slide_tool_btn.setToolTip('Arraste um clipe entre vizinhos contíguos; mantém a sequência [G]')
        self.slide_tool_btn.setAccessibleName('Slide [G]')
        self.slide_tool_btn.clicked.connect(self.activate_slide)
        self._add_timeline_tool(self.slide_tool_btn)
        self.snap_btn=QToolButton();self.snap_btn.setText('🧲')
        self.snap_btn.setCheckable(True);self.snap_btn.setChecked(True)
        self.snap_btn.setToolTip('Encaixar na cabeça de reprodução, cortes e marcadores [S]')
        self.snap_btn.setAccessibleName('Ímã de encaixe [S]')
        self.snap_btn.toggled.connect(self.toggle_snapping)
        self._add_timeline_tool(self.snap_btn)
        tool_specs=[
            ('✂ Dividir','✂',self.split_at_cursor),
            ('Ripple apagar','RIP',self.ripple_delete_selected),
            ('Roll emenda','ROL',self.roll_edit_selected),
            ('Slide numérico ±s','±s',self.slide_edit_selected),
            ('Slip da fonte','SLP',self.slip_selected),
            ('Keyframe','KF',self.add_keyframe),
            ('Dissolvência','DIS',self.make_transition),
            ('Marcador','M',self.add_marker),
            ('Agrupar','AGR',self.group_selected),
            ('Separar áudio','A/V',self.separate_audio),
            ('Proxy leve','PRX',self.create_proxies),
            ('Reduzir zoom','−',lambda:self.zoom_timeline(1/1.25)),
            ('Aumentar zoom','+',lambda:self.zoom_timeline(1.25)),
            ('Página anterior','‹',lambda:self.pan_timeline_page(-1)),
            ('Próxima página','›',lambda:self.pan_timeline_page(1)),
            ('Ajustar timeline [F]','F',self.fit_timeline),
        ]
        for title,label,fn in tool_specs:
            btn=QToolButton();btn.setText(label)
            if title=='Página anterior':
                btn.setToolTip('Rolar a timeline uma página para a esquerda')
                btn.setAccessibleName('Rolar timeline para a esquerda')
            elif title=='Próxima página':
                btn.setToolTip('Rolar a timeline uma página para a direita')
                btn.setAccessibleName('Rolar timeline para a direita')
            else:
                btn.setToolTip(title)
                btn.setAccessibleName(title)
            if title=='Slide numérico ±s':
                btn.setObjectName('timelineSlideNumeric')
                btn.setToolTip('Slide numérico em segundos: move o clipe entre os vizinhos e preserva a duração da sequência.')
                btn.setAccessibleName('Ajustar Slide numericamente em segundos')
            btn.clicked.connect(fn)
            self._add_timeline_tool(btn)
        self.timeline_tool_layout.addStretch(1)
        hint2=QLabel('De cima para baixo: FRENTE → FUNDO  |  V: selecionar  ·  B: lamina  ·  '
                     'Ctrl+clique: multipla  ·  Ctrl+roda: zoom  ·  Shift+roda: subir/descer'
                     '  ·  roda: esquerda/direita  ·  J: -2s / K: pausa / L: reproduzir'
                     '  ·  , / .: quadro anterior/próximo')
        hint2.setWordWrap(True)
        hint2.setObjectName('hint')
        bl.addWidget(hint2)
        self.timeline=TimelineWidget()
        self.timeline.selected_changed.connect(self.selection_changed)
        self.timeline.seek_requested.connect(self.seek_to)
        self.timeline.clip_move_requested.connect(self.move_clip)
        self.timeline.clip_trim_requested.connect(self.trim_clip)
        self.timeline.slide_requested.connect(self._slide_dragged)
        self.timeline.split_requested.connect(self.split_on_blade)
        self.timeline.media_dropped.connect(self.on_media_drop)
        self.timeline.track_change_requested.connect(self.track_action)
        self.timeline.mode_changed.connect(self._mode_status)
        self.timeline.context_action_requested.connect(self.timeline_context_action)
        self.timeline.batch_move_requested.connect(self.batch_move)
        self.timeline.volume_keyframe_changed.connect(self.move_volume_keyframe)
        self.timeline.volume_keyframe_delete_requested.connect(self.delete_volume_keyframe_at)
        self.timeline.audio_fade_changed.connect(self.set_audio_fade)
        self.timeline.keyframe_time_changed.connect(self.move_keyframe_time)
        self.timeline.keyframe_delete_requested.connect(self.delete_keyframe_at)
        self.timeline.play_toggle_requested.connect(self.toggle_play)
        bl.addWidget(self.timeline,1)
        self.workspace_splitter.addWidget(timeline_box)
        self.workspace_splitter.setStretchFactor(0,3)
        self.workspace_splitter.setStretchFactor(1,2)
        self.workspace_splitter.setSizes([420,320])
        self.statusBar().showMessage('Pronto. ▶ reproduz todas as camadas; use 640px para melhor desempenho.')

    def _transport_seek(self,value):
        if value==float('inf'):
            self.seek_to(self.project.duration)
        elif value==0:
            self.seek_to(0.)
        else:
            self.nudge_playhead(value)

    def set_preview_volume(self,value):
        value=max(0.,min(1.,float(value)))
        self.audio.setVolume(value)
        if hasattr(self,'live'):self.live.set_volume(value)

    def _header_project_action(self,action):
        callback={'new':self.new_project,'open':self.open_project,'save':self.save_project,
                  'reset_layout':self.restore_default_layout}.get(action)
        if callback:callback()

    def restore_default_layout(self):
        """Recupera proporções usáveis sem tocar no conteúdo do projeto."""
        self.horizontal.setSizes([250,720,320])
        self.workspace_splitter.setSizes([420,320])
        self.side_tabs.setCurrentIndex(0)
        self.timeline.view.pps=21.0
        self.timeline.view.update()
        self._save_ui_state()
        self.statusBar().showMessage('Layout padrão restaurado. O conteúdo do projeto não foi alterado.',5000)

    def _header_stage_action(self,stage):
        self.header.set_stage(stage)
        if stage=='import':
            self.import_media()
        elif stage=='analyze':
            self.open_actions()
        elif stage=='review':
            if self._pending_review_findings:
                self._show_pending_review()
            else:
                self.open_actions()
                self.header.set_stage('review')
                self.statusBar().showMessage(
                    'As sugestões são revisadas antes de aplicar cortes. Não há cortes pendentes; '
                    'escolha uma ação na aba Ações IA para analisar.')
        elif stage=='export':
            self.export_video()

    def _preview_review_finding(self,clip_id,source_start,source_end):
        """Audiciona uma sugestão no player canônico sem abrir outro decoder."""
        clip=self.project.clip(clip_id)
        if clip is None or clip.speed<=0:
            self.statusBar().showMessage('O bloco desta sugestão não está mais na timeline.')
            return
        self.selected_ids=[clip.id]
        self.refresh(self.selected_ids)
        # A margem ajuda a avaliar a fala que antecede o trecho marcado.
        source_offset=max(0.,min(clip.end-clip.start,float(source_start)-.65))
        timeline_position=clip.timeline_start+source_offset/clip.speed
        self.seek_to(timeline_position)
        self.toggle_play()
        source_end_offset=max(0.,min(clip.end-clip.start,float(source_end)))
        self._review_preview_end=clip.timeline_start+source_end_offset/clip.speed
        self.statusBar().showMessage(
            f'Prévia da sugestão · {max(0.,source_end-source_start):.2f}s · '
            'reprodução pela composição principal. Use Espaço para pausar.')

    def _theme(self):
        self.setStyleSheet('''
        QWidget{background:#181b20;color:#eef0f3;font-family:'Segoe UI';font-size:12px;}
        QMainWindow,QSplitter{background:#101216;}
        QLabel#brand{font-size:17px;font-weight:900;color:#ff9a4c;}
        QLabel#hint{color:#8b9db3;font-size:11px;}
        QPushButton,QToolButton{background:#272b31;border:1px solid #42474f;border-radius:5px;padding:5px 7px;}
        QPushButton:hover,QToolButton:hover{background:#383d45;border-color:#e17b35;}
        QToolButton#timelineSelectTool:checked,QToolButton#timelineBladeTool:checked,
        QToolButton#timelineSlideTool:checked{
            background:#38271b;color:#ffb370;border-color:#f5822b;font-weight:750;}
        QPushButton:pressed{background:#493321;}
        QListWidget{background:#121519;border:1px solid #383d45;border-radius:5px;}
        QListWidget::item{padding:7px 5px;}
        QListWidget::item:selected{background:#653c21;}
        QScrollBar:horizontal{background:transparent;height:0px;margin:0;border:0;}
        QScrollBar:vertical{background:transparent;width:0px;margin:0;border:0;}
        QScrollBar#timelineHorizontalScrollBar:horizontal{background:#14181e;height:12px;}
        QScrollBar#timelineVerticalScrollBar:vertical{background:#14181e;width:12px;}
        QScrollBar::handle:horizontal,QScrollBar::handle:vertical{
            background:#454b54;border:1px solid #59616b;border-radius:4px;min-width:24px;min-height:24px;}
        QScrollBar::handle:horizontal:hover,QScrollBar::handle:vertical:hover{background:#626b77;}
        QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal,
        QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{
            background:#202329;border:0;width:12px;height:12px;}
        QScrollBar::add-page:horizontal,QScrollBar::sub-page:horizontal,
        QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:#171a1f;}
        QScrollArea{border:0;}
        QSlider::groove:horizontal{height:5px;background:#41464e;}
        QSlider::handle:horizontal{background:#ff8126;width:12px;margin:-5px 0;}
        QProgressBar{text-align:center;border:1px solid #494e56;border-radius:4px;}
        QProgressBar::chunk{background:#f5822b;}
        QSplitter::handle{background:#383d45;}
        QFrame#processDock{background:#202329;border:1px solid #42474f;border-radius:6px;}
        QFrame#processDock QLabel{background:transparent;}
        QFrame#timelineToolRail{background:#14181e;border:1px solid #30343b;border-radius:6px;}
        QLabel#timelineToolHeading{color:#aeb5bf;font-size:9px;font-weight:800;letter-spacing:.4px;}
        QToolButton#timelineToolScroll{background:transparent;}
        QWidget#taskProgressSlot{background:transparent;}

        QWidget#studioHeader{background:#111720;border:1px solid #283443;border-radius:6px;}
        QLabel#brandMark{background:#151b1e;border:1px solid #33404a;border-radius:8px;padding:0;}
        QLabel#brandName{color:#f3f6fa;font-size:14px;font-weight:900;letter-spacing:1px;}
        QLabel#brandVersion{color:#8e9baa;font-size:9px;font-weight:700;letter-spacing:.6px;}
        QLabel#projectName{color:#e1e8f0;font-weight:650;}
        QLabel#localStatus{color:#a8edc2;background:#183628;border:1px solid #356649;
            border-radius:9px;padding:4px 9px;font-size:10px;font-weight:700;}
        QWidget#studioHeader QPushButton#workflowStage{background:transparent;color:#9daaba;
            border:1px solid #303b49;border-radius:13px;padding:2px 12px;font-weight:700;}
        QWidget#studioHeader QPushButton#workflowStage:hover{color:#fff1e6;border-color:#db7528;background:#30251d;}
        QWidget#studioHeader QPushButton#workflowStage:checked{color:#ffb370;border-color:#f5822b;background:#38271b;}
        QWidget#studioHeader QPushButton#workflowStage[stageState="complete"]{
            color:#d9e3ed;border-color:#566879;background:#202a36;}
        QFrame#workflowConnector{background:#3c4654;border:0;}
        QFrame#workflowConnector[completed="true"]{background:#ff8126;}
        QWidget#studioHeader QPushButton#quietAction{background:#202a36;border:1px solid #364454;
            border-radius:5px;padding:4px 9px;}
        QWidget#studioHeader QPushButton#quietAction:hover{border-color:#ed8c45;}
        QWidget#studioHeader QPushButton#primaryAction{background:#ff8126;color:#24170f;
            border:1px solid #ff9a4e;border-radius:5px;padding:4px 15px;font-weight:800;}
        QWidget#studioHeader QPushButton#primaryAction:hover{background:#ffa04d;}
        QWidget#studioHeader QToolButton#projectMenu{background:transparent;border:1px solid #364454;
            border-radius:5px;padding:4px 9px;}
        QWidget#studioHeader QToolButton#projectMenu:hover{border-color:#ed8c45;background:#202a36;}

        QWidget#previewTransport{background:#202329;border:1px solid #383d45;border-radius:5px;}
        QWidget#previewTransport QPushButton#transportButton{background:transparent;border:1px solid transparent;
            border-radius:4px;padding:2px 7px;min-height:28px;color:#d7dbe1;font-weight:650;}
        QWidget#previewTransport QPushButton#transportButton:hover{background:#30343a;border-color:#5c626a;}
        QWidget#previewTransport QPushButton#playPrimary{background:#ff8126;color:#24170f;
            border:1px solid #ff9a4e;border-radius:18px;min-height:34px;min-width:38px;
            padding:0;font-size:15px;font-weight:900;}
        QWidget#previewTransport QPushButton#playPrimary:hover{background:#ffa04d;}
        QLabel#transportTime{background:transparent;color:#ffab66;font-family:'Cascadia Mono','Consolas';
            font-size:12px;font-weight:750;}
        QLabel#volumeLabel{background:transparent;color:#aeb5bf;font-size:9px;font-weight:700;}
        QWidget#previewTransport QComboBox#previewQuality{min-height:27px;padding:1px 5px;}
        QWidget#previewTransport QSlider#previewVolume::handle:horizontal{width:11px;background:#ff8126;}

        QWidget#inspectorGroup{background:#202329;border:1px solid #383d45;border-radius:5px;}
        QToolButton#inspectorGroupButton{background:#24282e;color:#f0f2f5;border:0;
            border-radius:4px;text-align:left;padding:6px 8px;font-weight:750;}
        QToolButton#inspectorGroupButton:hover{background:#30343a;color:#ffb370;}
        QWidget#inspectorGroupBody{background:transparent;border:0;}

        QFrame#libraryDock{background:#171a1f;border:1px solid #30343b;border-radius:6px;}
        QFrame#libraryRail{background:#121519;border-right:1px solid #30343b;}
        QToolButton#libraryNavButton{background:transparent;color:#aeb5bf;border:1px solid transparent;
            border-radius:5px;padding:4px 1px;font-size:9px;font-weight:650;}
        QToolButton#libraryNavButton:hover{background:#282d34;color:#fff;border-color:#474d56;}
        QToolButton#libraryNavButton:checked{background:#38271b;color:#ffad70;border-color:#f5822b;}
        QLabel#libraryHeading{color:#ffad70;font-size:11px;font-weight:800;letter-spacing:.6px;}
        QLabel#libraryHint{color:#9da5af;font-size:10px;}
        QLabel#libraryCount{color:#9da5af;font-size:10px;}
        QPushButton#libraryPrimary{background:#ff8126;color:#24170f;border:1px solid #ff9a4e;
            border-radius:5px;padding:5px 7px;font-weight:750;}
        QPushButton#libraryPrimary:hover{background:#ffa04d;}
        QTabWidget::pane{background:#181b20;border:1px solid #30343b;border-radius:4px;}
        QTabBar::tab{background:#202329;color:#aeb5bf;border:1px solid #30343b;
            padding:6px 9px;min-height:24px;}
        QTabBar::tab:hover{color:#f4f5f6;border-color:#8a542e;}
        QTabBar::tab:selected{background:#38271b;color:#ffb370;border-bottom:2px solid #f5822b;font-weight:750;}

        QLineEdit,QDoubleSpinBox,QSpinBox,QComboBox,QTextEdit{
            border:1px solid #494e56;border-radius:4px;padding:4px;background:#121519;}
        ''')

    @staticmethod
    def _section(text):
        label=QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet('color:#ffad70;font-weight:800;')
        return label

    def _fit_timeline_toolbar(self):
        # A barra é horizontal e compacta; texto completo permanece no tooltip.
        for button in self.timeline_tool_buttons:
            button.setMinimumWidth(0)
            button.setMaximumWidth(36)
            button.setFixedSize(32,30)
        self.timeline_tool_holder.adjustSize()

    def _add_timeline_tool(self, button):
        button.setFixedSize(32,30)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.timeline_tool_layout.addWidget(button)
        self.timeline_tool_buttons.append(button)

    @staticmethod
    def _ui_settings():
        return QSettings(QSettings.Format.IniFormat,QSettings.Scope.UserScope,
                         'Berofel','BerofelStudio')

    def _restore_ui_state(self):
        settings=self._ui_settings()
        geometry=settings.value('ui/window_geometry')
        if geometry:
            try:self.restoreGeometry(geometry)
            except (TypeError,RuntimeError):pass
        raw=settings.value('ui/panel_sizes',[])
        if isinstance(raw,str):raw=raw.split(',')
        try:sizes=[int(value) for value in raw]
        except (TypeError,ValueError):sizes=[]
        if len(sizes)==4 and any(value>0 for value in sizes):
            sizes=sizes[1:]  # migra proporções salvas antes da remoção da faixa lateral
        if len(sizes)==3 and any(value>0 for value in sizes):
            self.horizontal.setSizes(sizes)
        raw_workspace=settings.value('ui/workspace_sizes',[])
        if isinstance(raw_workspace,str):raw_workspace=raw_workspace.split(',')
        try:workspace_sizes=[int(value) for value in raw_workspace]
        except (TypeError,ValueError):workspace_sizes=[]
        if len(workspace_sizes)==2 and any(value>0 for value in workspace_sizes):
            self.workspace_splitter.setSizes(workspace_sizes)
        try:
            quality=int(settings.value('ui/preview_quality',0))
            if 0<=quality<self.preview_quality.count():
                self.preview_quality.setCurrentIndex(quality)
            tab=int(settings.value('ui/inspector_tab',0))
            if 0<=tab<self.side_tabs.count():
                self.side_tabs.setCurrentIndex(tab)
            volume=max(0,min(100,int(settings.value('ui/preview_volume',85))))
            self.transport.volume.setValue(volume)
            zoom=float(settings.value('ui/timeline_zoom',21.0))
            if 3.0<=zoom<=180.0:
                self.timeline.view.pps=zoom
            raw_snap=settings.value('ui/timeline_snapping',True)
            snapping=(raw_snap if isinstance(raw_snap,bool)
                      else str(raw_snap).strip().casefold() not in ('0','false','off','no'))
            self.snap_btn.setChecked(snapping)
        except (TypeError,ValueError):
            pass

    def _save_ui_state(self):
        settings=self._ui_settings()
        settings.setValue('ui/window_geometry',self.saveGeometry())
        settings.setValue('ui/panel_sizes',self.horizontal.sizes())
        settings.setValue('ui/workspace_sizes',self.workspace_splitter.sizes())
        settings.setValue('ui/preview_quality',self.preview_quality.currentIndex())
        settings.setValue('ui/preview_volume',self.transport.volume.value())
        settings.setValue('ui/inspector_tab',self.side_tabs.currentIndex())
        settings.setValue('ui/timeline_zoom',self.timeline.view.pps)
        settings.setValue('ui/timeline_snapping',self.snap_btn.isChecked())
        settings.sync()

    def _shortcuts(self):
        shortcuts=[('Ctrl+I',self.import_media),('Ctrl+S',self.save_project),
                   ('Ctrl+O',self.open_project),('Ctrl+N',self.new_project),
                   ('Ctrl+C',self.copy_selected_clips),('Ctrl+V',self.paste_clips),
                   ('Ctrl+Z',self.undo),('Ctrl+Y',self.redo),
                   ('Delete',self.delete_clips),
                   ('Ctrl+K',self.split_at_cursor),
                   ('Ctrl+Shift+Delete',self.ripple_delete_selected),
                   ('Ctrl+G',self.group_selected),('Ctrl+Shift+G',self.ungroup_selected),
                   ('M',self.add_marker),('F',self.fit_timeline),
                   ('S',lambda:self.snap_btn.setChecked(not self.snap_btn.isChecked())),
                   ('J',lambda:self.nudge_playhead(-2)),('K',self.pause_playback),
                   ('L',self.play_forward),(',',lambda:self.step_frame(-1)),
                   ('.',lambda:self.step_frame(1))]
        for text,fn in shortcuts:
            action=QAction(self)
            action.setShortcut(QKeySequence(text))
            action.triggered.connect(fn)
            if text in ('J','K','L',',','.','M','F','S','Ctrl+C','Ctrl+V'):
                action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
                self.timeline.addAction(action)
            else:
                self.addAction(action)

    def open_actions(self):
        self.actions_panel.set_context(self.project,self.selected_ids,self.active_track_id,
                                       self.timeline.view.cursor_time)
        self.side_tabs.setCurrentWidget(self.actions_panel)
        self.header.set_stage('analyze')

    def open_narration(self):
        self.side_tabs.setCurrentWidget(self.narration_panel)

    def open_captions(self):
        self.captions_panel.set_context(self.project,self.selected_ids)
        self.side_tabs.setCurrentWidget(self.captions_panel)
        self.library.show_page('media')
        self.statusBar().showMessage('Painel de legendas aberto: selecione uma legenda ou escreva uma nova.')

    def select_caption_from_panel(self,clip_id):
        clip=self.project.clip(str(clip_id))
        if not clip or clip.kind!='text':return
        self.selected_ids=[clip.id]
        self.refresh([clip.id])
        self.side_tabs.setCurrentWidget(self.captions_panel)

    def add_caption_from_panel(self,text):
        if not str(text).strip():
            self.statusBar().showMessage('Escreva o texto da legenda no painel antes de adicionar.')
            self.captions_panel.text_edit.setFocus()
            return
        at=max(0.,self.timeline.view.cursor_time)
        self.snapshot()
        clip=create_manual_caption(self.project,str(text),at,at+3.0)
        self.refresh([clip.id])
        self.side_tabs.setCurrentWidget(self.captions_panel)
        self.statusBar().showMessage('Legenda adicionada no playhead; Ctrl+Z para desfazer.')

    def apply_caption_text(self,clip_id,text):
        clip=self.project.clip(str(clip_id))
        if not clip or clip.kind!='text':return
        if clip.id not in self.selected_ids:
            self.selected_ids=[clip.id]
        self.change_prop('text',str(text))
        self.side_tabs.setCurrentWidget(self.captions_panel)

    def change_caption_property(self,clip_id,field,value):
        clip=self.project.clip(str(clip_id))
        if not clip or clip.kind!='text':return
        if clip.id not in self.selected_ids:
            self.selected_ids=[clip.id]
        self.change_prop(str(field),value)
        self.side_tabs.setCurrentWidget(self.captions_panel)

    def preview_caption_text(self,clip_id,text):
        if self.selected_ids==[str(clip_id)]:
            self.preview_image.set_preview_text(str(text))

    def apply_caption_preset(self,index):
        if len(self.selected_ids)!=1:return
        clip=self.project.clip(self.selected_ids[0])
        if not clip or clip.kind!='text' or not self.project.track_is_editable(clip.track_id):return
        styles={1:('Arial',44,'#FFFFFF',3),
                2:('Arial',38,'#FFFFFF',2),
                3:('Arial',54,'#FFD166',4),
                4:('Segoe UI',36,'#F2F5F8',1)}
        style=styles.get(int(index))
        if not style:return
        self.snapshot()
        (clip.font_family,clip.font_size,clip.font_color,clip.stroke_width)=style
        self.refresh([clip.id])
        self.side_tabs.setCurrentWidget(self.captions_panel)

    def use_selected_transcript(self):
        """Extrai apenas palavras dos clipes selecionados, conforme tempo atual."""
        selected=set(self.selected_ids)
        # O escopo da aba Ações IA pode ser faixa ou projeto, sem seleção.
        # O texto livre de narração continua independente de qualquer escopo.
        try:
            _, targets = self.actions_panel.selection()
            words_for_scope=scoped_cues(self.project,targets)
            text=' '.join(cue[2] for cue in words_for_scope)
        except ValueError:
            text=''
        if not text:
            words=[w for w in timeline_words(self.project) if w['clip_id'] in selected]
            text=' '.join(w['text'] for w in words)
        else:
            words=text.split()
        if not words:
            QMessageBox.information(self,'Texto da transcrição',
                'Não há transcrição nesses blocos. Use Transcrever IA primeiro, ou digite o texto livremente.')
            return
        self.narration_panel.set_text(text)
        self.open_narration()
        self.statusBar().showMessage(f'{len(words)} palavras da transcrição carregadas na narração.')

    def generate_narration_ui(self, request: NarrationRequest, add_to_timeline: bool):
        if self._ai_busy or self.active_task is not None:
            QMessageBox.information(self,'Batata Quente',
                'Já há um processo de IA em andamento. Gere a narração após sua conclusão.')
            return
        try:
            validate_request(request.text, request.voice, request.language, request.consent)
        except (ValueError, FileNotFoundError, PermissionError) as exc:
            QMessageBox.warning(self,'Narração Qwen3-TTS',str(exc))
            return
        from dataclasses import replace
        request=replace(request,project_path=self.project.path)
        position=self.timeline.view.cursor_time
        self._ai_busy=True
        self.narration_panel.busy(True)
        streaming=request.engine=='qwen3-tts-native-q4'
        if streaming:self.narration_stream.begin()
        engine_label=('Qwen Turbo Q4 experimental' if request.engine=='qwen3-tts-native-q4'
                      else 'Qwen3-TTS Base local')
        self.statusBar().showMessage(f'Batata Quente: {engine_label} gerando em processo isolado...')
        def ready(result):
            path=result['path']
            duration=result['duration']
            self.narration_panel.set_result(path,duration,result['cache_hit'])
            if add_to_timeline:
                self.snapshot()
                narration_track=next((t for t in self.project.tracks if t.name=='Narração' and not t.locked),None)
                if narration_track is None:
                    narration_track=self.project.add_track('Narração',0)
                self.active_track_id=narration_track.id
                clip=Clip(source=path,start=0,end=duration,title=result['title'],
                          track_id=narration_track.id,timeline_start=position,
                          kind='audio',include_audio=True,source_length=duration)
                self.project.add_clip(clip)
                if path not in self.project.media:
                    self.project.media.append(path)
                self.refresh([clip.id])
                self.open_narration()
                self.statusBar().showMessage(f'Narração adicionada à timeline ({duration:.1f}s).')
            else:
                self.statusBar().showMessage('Narração WAV salva. Clique em Ouvir para conferir.')
        task=self._task(generate_narration,ready,request,label=f'{engine_label} · narração',
            on_audio_chunk=self.narration_stream.push if streaming else None,
            on_audio_success=self.narration_stream.finish if streaming else None,
            on_audio_stop=self.narration_stream.stop if streaming else None)
        if task is None:
            self._ai_busy=False
            self.narration_panel.busy(False)
            if streaming:self.narration_stream.stop()
            return
        def finish():
            self._ai_busy=False
            self.narration_panel.busy(False)
        task.signals.finished.connect(finish)

    def prepare_narration_voice(self,reference: str,reference_text: str,name: str=''):
        """Warm the shared Base model and prepare a reusable profile prompt."""
        if self._ai_busy or self.active_task is not None:
            self.narration_panel.status.setText(
                'Perfil salvo. A preparação será feita na próxima narração, pois a fila de IA está ocupada.')
            return
        from berofel.services.qwen3_tts_local import is_ready,prepare_local_voice_prompt
        if not is_ready():
            self.narration_panel.status.setText(
                'Perfil salvo. Instale o Qwen3-TTS Base para preparar sua voz localmente.')
            return
        self._ai_busy=True
        self.narration_panel.busy(True)
        def ready(result):
            cached='já preparado' if result.get('prompt_cache_hit') else 'preparado e salvo no cache local'
            self.narration_panel.status.setText(
                f'Perfil de voz {cached}. O modelo Qwen3 permanece carregado nesta sessão.')
        task=self._task(prepare_local_voice_prompt,ready,reference,reference_text,
                        label='Preparar perfil Qwen3'+(f' · {name}' if name else ''))
        if task is None:
            self._ai_busy=False;self.narration_panel.busy(False);return
        task.signals.finished.connect(
            lambda:(setattr(self,'_ai_busy',False),self.narration_panel.busy(False)))

    def _unavailable(self,feature):
        QMessageBox.information(self,feature,f'{feature} esta identificado na interface, '
                                 'mas ainda nao foi conectado ao motor de edicao. '
                                 'A versao 0.4 prioriza timeline e IA sequencial.')

    def open_color_controls(self):
        """Abre os ajustes visuais canônicos do clipe selecionado no inspetor."""
        if len(self.selected_ids)!=1:
            QMessageBox.information(self,'Cor e recorte',
                'Selecione um vídeo ou uma imagem para ajustar cor e recorte.')
            return
        clip=self.project.clip(self.selected_ids[0])
        if not clip or clip.kind not in ('video','image'):
            QMessageBox.information(self,'Cor e recorte',
                'Os ajustes de cor e recorte estão disponíveis para vídeo e imagem.')
            return
        self.side_tabs.setCurrentWidget(self.props_scroll)
        group=next((item for item in self.props_scroll.findChildren(InspectorGroup)
                    if item.toggle.text().endswith('Cor e recorte')),None)
        if group is None:
            self._update_properties()
            group=next((item for item in self.props_scroll.findChildren(InspectorGroup)
                        if item.toggle.text().endswith('Cor e recorte')),None)
        if group is not None:
            group.toggle.setChecked(True)
            self.props_scroll.ensureWidgetVisible(group)
            self.statusBar().showMessage('Ajustes de cor e recorte do clipe selecionado.')

    def toggle_tools(self):
        self.tool_rail.setFocus()
        self.statusBar().showMessage('Ferramentas da timeline disponíveis na faixa vertical ao lado da biblioteca.',4000)

    def snapshot(self):
        self.history.append(copy.deepcopy(self.project))
        if len(self.history)>80: self.history.pop(0)
        self.future.clear()

    def undo(self):
        if self.history:
            self.future.append(copy.deepcopy(self.project))
            self.project=self.history.pop()
            self.active_track_id=self.project.tracks[0].id
            self.refresh()

    def redo(self):
        if self.future:
            self.history.append(copy.deepcopy(self.project))
            self.project=self.future.pop()
            self.active_track_id=self.project.tracks[0].id
            self.refresh()

    def copy_selected_clips(self):
        selected=set(self.selected_ids)
        if not selected:
            self.statusBar().showMessage('Selecione clipes na timeline para copiar.')
            return
        groups={clip.group_id for clip in self.project.clips
                if clip.id in selected and clip.group_id}
        selected.update(clip.id for clip in self.project.clips
                        if clip.group_id in groups)
        selected.update(clip.id for clip in self.project.clips
                        if clip.kind=='text' and clip.caption_anchor_clip_id in selected)
        self._clip_clipboard=copy.deepcopy([clip for clip in self.project.clips
                                           if clip.id in selected])
        self.statusBar().showMessage(
            f'{len(self._clip_clipboard)} clipe(s) copiados, incluindo vínculos e legendas ancoradas. Ctrl+V para colar.')

    def paste_clips(self):
        if not self._clip_clipboard:
            self.statusBar().showMessage('Copie clipes antes de colar.')
            return
        eligible=[clip for clip in self._clip_clipboard
                  if self.project.track(clip.track_id)
                  and self.project.track_is_editable(clip.track_id)]
        eligible_ids={clip.id for clip in eligible}
        eligible=[clip for clip in eligible
                  if not clip.caption_anchor_clip_id or clip.caption_anchor_clip_id in eligible_ids]
        if not eligible:
            QMessageBox.information(self,'Colar clipes',
                'As camadas de origem não existem ou estão bloqueadas neste projeto.')
            return
        origin=min(clip.timeline_start for clip in eligible)
        delta=self.timeline.view.cursor_time-origin
        id_map={clip.id:new_id() for clip in eligible}
        group_map={group:new_id() for group in {clip.group_id for clip in eligible if clip.group_id}}
        clones=[]
        for source in eligible:
            clip=copy.deepcopy(source)
            clip.id=id_map[source.id]
            clip.timeline_start=max(0.,round(source.timeline_start+delta,4))
            if clip.group_id:clip.group_id=group_map[clip.group_id]
            if clip.caption_anchor_clip_id in id_map:
                clip.caption_anchor_clip_id=id_map[clip.caption_anchor_clip_id]
            clones.append(clip)
        self.snapshot()
        pasted=[]
        try:
            for clip in clones:
                self.project.add_clip(clip)
                pasted.append(clip)
                if clip.source and clip.source not in self.project.media:
                    self.project.media.append(clip.source)
        except Exception as exc:
            self.undo()
            QMessageBox.warning(self,'Colar clipes',str(exc))
            return
        self.refresh([clip.id for clip in pasted])
        self.statusBar().showMessage(
            f'{len(pasted)} clipe(s) colados no playhead. Ctrl+Z para desfazer.')

    def refresh(self,selection=None):
        if hasattr(self,'live'):
            self.stop_playback()
        selected=self.selected_ids if selection is None else list(selection)
        self.project_name.setText(self.project.name)
        self.transport.set_time(self.timeline.view.cursor_time,self.project.duration,self.project.fps)
        library=[];seen=set()
        for p in [*self.project.media,*(c.source for c in self.project.clips if c.source)]:
            key=str(Path(p).resolve()).casefold()
            if key not in seen:
                seen.add(key);library.append(p)
        self.library.set_media(library)
        self.library.set_markers(self.project.markers)
        if hasattr(self,'captions_panel'):
            self.captions_panel.set_context(self.project,selected)
        self.track_combo.blockSignals(True)
        self.track_combo.clear()
        for t in self.project.tracks:
            self.track_combo.addItem(t.name,t.id)
        if not self.project.track(self.active_track_id):
            self.active_track_id=self.project.tracks[0].id
        for i in range(self.track_combo.count()):
            if self.track_combo.itemData(i)==self.active_track_id:
                self.track_combo.setCurrentIndex(i);break
        self.track_combo.blockSignals(False)
        self.timeline.set_project(self.project,selected)
        chosen=self.project.clip(selected[0]) if len(selected)==1 else None
        visual_selection=(chosen if chosen and chosen.kind in ('video','image','text') else None)
        self.preview_image.set_selection(visual_selection,self.project.width,self.project.height,
                                         self.timeline.view.cursor_time-(chosen.timeline_start if chosen else 0))
        if hasattr(self,'narration_panel'):
            lane=self.project.track(chosen.track_id) if chosen else None
            self.narration_panel.set_clip(chosen,editable=bool(lane and not lane.locked))
        if chosen and chosen.kind=='text' and hasattr(self,'side_tabs'):
            self.side_tabs.setCurrentWidget(self.captions_panel)
        self._update_properties()
        self.actions_panel.set_context(self.project,selected,self.active_track_id,
                                       self.timeline.view.cursor_time)
        self._hide_auxiliary_scrollbars()
        if hasattr(self,'_frame_debounce') and self.project.clips:
            # Mostra a composição estática após o usuário editar um bloco.
            self._frame_debounce.start()

    def _reveal_ai_edit_result(self,new_targets,approved):
        """Keep AI cut results highlighted and bring their range into view."""
        targets=list(new_targets or ())
        if approved and targets:
            selection=list(dict.fromkeys(str(target.original_id) for target in targets
                                         if getattr(target,'original_id',None)))
        else:
            selection=list(self.selected_ids)
        self.refresh(selection)
        if approved and targets:
            start=min(float(target.timeline_start) for target in targets)
            end=max(float(target.timeline_end) for target in targets)
            self.timeline.view.reveal_time_range(start,end)

    def _choose_active_track(self,index):
        new=self.track_combo.itemData(index)
        if new:
            self.active_track_id=new
            self.actions_panel.set_context(self.project,self.selected_ids,self.active_track_id,
                                           self.timeline.view.cursor_time)

    def track_action(self,track_id,action):
        self.active_track_id=track_id
        track=self.project.track(track_id)
        if not track:return
        if action=='activate':
            self.refresh(self.selected_ids);return
        if action=='mix':
            self.edit_track_mix(track);return
        if action=='rename':
            name,ok=QInputDialog.getText(self,'Renomear camada','Novo nome:',text=track.name)
            if not ok or not name.strip() or name==track.name:return
            self.snapshot();track.name=name.strip()
        elif action=='remove':
            if len(self.project.tracks)<=1 or any(c.track_id==track_id for c in self.project.clips):
                QMessageBox.information(self,'Camada','Remova ou mova os blocos antes de excluir esta camada. '
                                        'Pelo menos uma camada deve existir.')
                return
            self.snapshot()
            self.project.delete_track(track_id)
        elif action in ('up','down'):
            idx=next((i for i,t in enumerate(self.project.tracks) if t.id==track_id),-1)
            if idx<0 or not 0<=idx+(-1 if action=='up' else 1)<len(self.project.tracks):return
            self.snapshot();self.project.move_track(track_id,-1 if action=='up' else 1)
        elif action in ('hide','mute','solo','lock'):
            self.snapshot()
            attr={'hide':'hidden','mute':'muted','solo':'solo','lock':'locked'}[action]
            setattr(track,attr,not getattr(track,attr))
        self.refresh(self.selected_ids)

    def edit_track_mix(self,track):
        dialog=QDialog(self)
        dialog.setWindowTitle('Mixagem · '+track.name)
        layout=QVBoxLayout(dialog)
        gain=QDoubleSpinBox(dialog);gain.setRange(0.,4.);gain.setDecimals(2)
        gain.setSingleStep(.1);gain.setValue(max(0.,min(4.,float(track.volume))))
        gain.setSuffix(' ×')
        pan=QDoubleSpinBox(dialog);pan.setRange(-1.,1.);pan.setDecimals(2)
        pan.setSingleStep(.1);pan.setValue(max(-1.,min(1.,float(track.pan))))
        pan.setToolTip('−1 = esquerda · 0 = centro · +1 = direita')
        layout.addWidget(QLabel('Ganho da faixa (multiplicador linear)'))
        layout.addWidget(gain)
        layout.addWidget(QLabel('Balanço estéreo (−1 esquerda · +1 direita)'))
        layout.addWidget(pan)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|
                                 QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        if (abs(track.volume-gain.value())<1e-6 and
                abs(track.pan-pan.value())<1e-6):return
        self.snapshot()
        track.volume=gain.value();track.pan=pan.value()
        self.refresh(self.selected_ids)
        self.statusBar().showMessage(
            f'Mixagem de {track.name}: ganho {track.volume:.2f}× · balanço {track.pan:+.2f}.')

    def add_track(self):
        name,ok=QInputDialog.getText(self,'Nova camada universal',
                  'Nome (aceita video, imagem, texto e audio):',
                  text=f'Camada {len(self.project.tracks)+1}')
        if not ok:return
        idx=next((i for i,t in enumerate(self.project.tracks) if t.id==self.active_track_id),0)
        self.snapshot()
        track=self.project.add_track(name,idx)
        self.active_track_id=track.id
        self.refresh()
        self.statusBar().showMessage(f'Camada {track.name} adicionada acima da atual.')

    def import_media(self):
        paths,_=QFileDialog.getOpenFileNames(self,'Importar arquivos','',MEDIA_FILTER)
        if paths:
            self.snapshot()
            self.project.media.extend(p for p in paths if p not in self.project.media)
            self.refresh(self.selected_ids)
            self.header.set_stage('analyze')
            self.statusBar().showMessage(f'{len(paths)} arquivo(s) importado(s).')

    def relink_selected_media(self):
        item=self.media_list.currentItem()
        if item is None:
            QMessageBox.information(self,'Relink mídia','Selecione uma mídia na biblioteca.')
            return
        old_path=item.data(Qt.ItemDataRole.UserRole)
        new_path,_=QFileDialog.getOpenFileName(
            self,'Localizar mídia · '+Path(old_path).name,'',MEDIA_FILTER)
        if not new_path:return
        if not Path(new_path).is_file():
            QMessageBox.warning(self,'Relink mídia','O arquivo escolhido não existe mais.')
            return
        try:
            self.snapshot()
            updated=self.project.relink_media(old_path,new_path)
            if not updated:
                QMessageBox.warning(self,'Relink mídia',
                    'Nenhuma referência do projeto corresponde ao arquivo selecionado.')
                return
            self.refresh(self.selected_ids)
            self.statusBar().showMessage(
                f'Mídia relinkada em {updated} referência(s). Salve o projeto para persistir a alteração.')
        except Exception as ex:
            QMessageBox.warning(self,'Relink mídia',str(ex))

    def add_media(self):
        item=self.media_list.currentItem()
        if not item:
            QMessageBox.information(self,'Biblioteca','Selecione um arquivo na biblioteca.');return
        self.insert_path(item.data(Qt.ItemDataRole.UserRole),self.active_track_id,
                         self.timeline.view.cursor_time)

    def on_media_drop(self,path,track_id,at):
        self.insert_path(path,track_id,at)

    def insert_path(self,path,track_id,at):
        try:
            extension=Path(path).suffix.lower()
            if not Path(path).is_file(): raise FileNotFoundError(path)
            if extension in IMAGES:
                kind='image';duration=5.0;has_audio=False
            else:
                if path not in self.media_cache:
                    self.media_cache[path]=media_info(path)
                duration,has_video,has_audio=self.media_cache[path]
                kind='video' if has_video else 'audio'
                if duration<=.08:
                    raise ValueError('Nao foi possivel identificar uma duracao valida.')
            self.snapshot()
            c=Clip(source=path,start=0,end=duration,title=Path(path).stem,
                   track_id=track_id,timeline_start=round(max(0,at),3),
                   kind=kind,include_audio=has_audio,source_length=duration)
            self.project.add_clip(c)
            if path not in self.project.media:self.project.media.append(path)
            self.active_track_id=track_id
            self.refresh([c.id])
            self.timeline.set_cursor(c.timeline_start)
            self.statusBar().showMessage(f'{kind.upper()} colocado em {self.project.track(track_id).name}. '
                                         'Arraste para alterar a camada ou a posicao.')
        except Exception as ex:
            QMessageBox.warning(self,'Inserir arquivo',str(ex))

    def add_title(self):
        text,ok=QInputDialog.getMultiLineText(self,'Adicionar texto','Texto sobre o video:')
        if not ok or not text.strip():return
        self.snapshot()
        c=Clip(source='',start=0,end=5,title=text.strip().splitlines()[0][:30],
               track_id=self.active_track_id,timeline_start=self.timeline.view.cursor_time,
               kind='text',text=text.strip())
        self.project.add_clip(c)
        self.refresh([c.id])

    def selection_changed(self,ids):
        self.selected_ids=ids
        selected_clip=self.project.clip(ids[0]) if len(ids)==1 else None
        if hasattr(self,'preview_image'):
            self.preview_image.set_selection(selected_clip,self.project.width,self.project.height,
                                             self.timeline.view.cursor_time-(selected_clip.timeline_start if selected_clip else 0))
        if hasattr(self,'narration_panel'):
            lane=self.project.track(selected_clip.track_id) if selected_clip else None
            self.narration_panel.set_clip(selected_clip,editable=bool(lane and not lane.locked))
        if hasattr(self,'captions_panel'):
            self.captions_panel.set_context(self.project,ids)
        self._update_properties()
        if selected_clip and selected_clip.kind=='text':
            self.side_tabs.setCurrentWidget(self.captions_panel)
        if hasattr(self,'actions_panel'):
            self.actions_panel.set_context(self.project,self.selected_ids,self.active_track_id,
                                           self.timeline.view.cursor_time)

    def _property_row(self,label,widget):
        holder=QWidget()
        lay=QVBoxLayout(holder)
        lay.setSpacing(2);lay.setContentsMargins(0,0,0,0)
        name=QLabel(label);name.setWordWrap(True)
        lay.addWidget(name)
        lay.addWidget(widget)
        target=getattr(self,'_property_target_layout',None)
        (target if target is not None else self.props_layout).addWidget(holder)

    def _property_group(self,title):
        group=InspectorGroup(title)
        self.props_layout.addWidget(group)
        return group

    def _numeric_prop(self,clip,field,label,minv,maxv,step=0.05,decimals=2,integer=False):
        spin=QSpinBox() if integer else QDoubleSpinBox()
        spin.setRange(minv,maxv)
        if not integer:
            spin.setDecimals(decimals)
            spin.setSingleStep(step)
        at=self.timeline.view.cursor_time-clip.timeline_start
        current=value_at(clip,field,max(0,at)) if field in ANIMATABLE and clip.keyframes.get(field) else getattr(clip,field)
        spin.setValue(current)
        spin.editingFinished.connect(lambda f=field,s=spin:self.change_prop(f,s.value()))
        self._property_row(label,spin)

    def _update_properties(self):
        if not hasattr(self,'props_layout'):return
        while self.props_layout.count():
            item=self.props_layout.takeAt(0)
            w=item.widget()
            if w:w.deleteLater()
        self._property_target_layout=None
        self.props_layout.addWidget(self._section('INSPECTOR DO CLIP'))
        ids=self.selected_ids
        note=QLabel(f'{len(ids)} bloco(s) selecionado(s)')
        note.setWordWrap(True)
        self.props_layout.addWidget(note)
        if len(ids)!=1:
            t=QLabel('Selecione um bloco para editar suas propriedades. '
                     'Os comandos de dividir, excluir e analise de IA aceitam varios blocos selecionados.')
            t.setWordWrap(True);self.props_layout.addWidget(t)
            self.props_layout.addStretch();return
        c=self.project.clip(ids[0])
        if not c:return
        text=QLabel(f'{c.kind.upper()}  ·  {Path(c.source).name if c.source else "Texto criado no editor"}\n'
                    f'Intervalo de origem: {c.start:.2f}–{c.end:.2f}s\n'
                    f'Camada: {self.project.track(c.track_id).name}')
        text.setWordWrap(True)
        text.setStyleSheet('color:#bec5ce;background:#202329;border-left:3px solid #f5822b;padding:7px 8px;')
        self.props_layout.addWidget(text)

        basic=self._property_group('Bloco e tempo')
        self._property_target_layout=basic.body_layout
        title=QLineEdit(c.title)
        title.editingFinished.connect(lambda:self.change_prop('title',title.text()))
        self._property_row('Nome do bloco',title)
        combo=QComboBox()
        for tr in self.project.tracks: combo.addItem(tr.name,tr.id)
        combo.setCurrentIndex(next((i for i in range(combo.count()) if combo.itemData(i)==c.track_id),0))
        combo.currentIndexChanged.connect(lambda index:self.move_clip(c.id,combo.itemData(index),c.timeline_start))
        self._property_row('Mover para camada (frente ou fundo)',combo)
        self._numeric_prop(c,'timeline_start','Inicio na timeline (segundos)',0,360000,step=.1)
        self._numeric_prop(c,'stack_order','Ordem dentro da camada (maior = na frente)',0,100000,integer=True)

        visual_kind=c.kind in ('video','image','text')
        audio_kind=c.kind in ('video','audio')
        motion=self._property_group('Movimento e velocidade')
        self._property_target_layout=motion.body_layout
        if c.kind in ('video','audio'):
            self._numeric_prop(c,'speed','Velocidade (0,25× a 10×)',.25,10,step=.25)
            speed_presets=QComboBox()
            for label,num in [('Velocidade predefinida',''),('0,25×',.25),('0,5×',.5),
                              ('1×',1.),('2×',2.),('3×',3.),('4×',4.),('10×',10.)]:
                speed_presets.addItem(label,num)
            speed_presets.currentIndexChanged.connect(lambda index:self.set_speed(c.id,speed_presets.itemData(index))
                                                       if index>0 else None)
            self._property_row('Aplicar velocidade rápida',speed_presets)
        if visual_kind:
            self._numeric_prop(c,'opacity','Opacidade da imagem (0–1)',0,1,step=.05)
            self._numeric_prop(c,'scale','Escala da imagem (0,05–3)',.05,3,step=.05)
            self._numeric_prop(c,'pos_x','Posicao horizontal (px)',-4000,4000,integer=True)
            self._numeric_prop(c,'pos_y','Posicao vertical (px)',-4000,4000,integer=True)
            self._numeric_prop(c,'rotation','Rotação (graus)',-360,360,step=5)

        if c.kind in ('video','image'):
            color=self._property_group('Cor e recorte')
            self._property_target_layout=color.body_layout
            self._numeric_prop(c,'brightness','Brilho (-1 a 1)',-1,1,step=.05)
            self._numeric_prop(c,'contrast','Contraste (0 a 2)',0,2,step=.05)
            self._numeric_prop(c,'saturation','Saturação (0 a 3)',0,3,step=.1)
            for fld,description in [('crop_left','Recorte à esquerda'),('crop_right','Recorte à direita'),
                                    ('crop_top','Recorte em cima'),('crop_bottom','Recorte embaixo')]:
                self._numeric_prop(c,fld,description+' (fração)',0,.45,step=.02)

        if visual_kind:
            appearance=self._property_group('Aparência e duração')
            self._property_target_layout=appearance.body_layout
            self._numeric_prop(c,'fade_in','Fade visual de entrada (s)',0,max(.1,c.duration),step=.1)
            self._numeric_prop(c,'fade_out','Fade visual de saída (s)',0,max(.1,c.duration),step=.1)
            if c.kind in ('text','image'):
                spin=QDoubleSpinBox();spin.setRange(.1,360000)
                spin.setValue(c.duration);spin.setSuffix(' s')
                spin.editingFinished.connect(lambda:self.change_prop('duration',spin.value()))
                self._property_row('Duração na timeline',spin)
            if c.kind=='text':
                self._numeric_prop(c,'font_size','Tamanho da letra (px)',12,200,integer=True)
                edit=QTextEdit();edit.setPlainText(c.text);edit.setMinimumHeight(90)
                edit.textChanged.connect(lambda e=edit:self.preview_image.set_preview_text(e.toPlainText()))
                self._property_row('Texto da legenda (prévia imediata)',edit)
                apply=QPushButton('Aplicar texto')
                apply.clicked.connect(lambda:self.change_prop('text',edit.toPlainText()))
                self._property_target_layout.addWidget(apply)
                family=QComboBox()
                for name in ('Arial','Calibri','Segoe UI','Verdana','Georgia'):
                    family.addItem(name)
                family.setCurrentText(c.font_family)
                family.currentTextChanged.connect(lambda value:self.change_prop('font_family',value))
                self._property_row('Fonte',family)
                color=QLineEdit(c.font_color);color.setMaxLength(7)
                color.setPlaceholderText('#FFFFFF')
                color.editingFinished.connect(lambda field=color:self.change_prop('font_color',field.text()))
                self._property_row('Cor do texto (hexadecimal)',color)
                stroke=QSpinBox();stroke.setRange(0,12);stroke.setValue(c.stroke_width)
                stroke.valueChanged.connect(lambda value:self.change_prop('stroke_width',value))
                self._property_row('Contorno da legenda',stroke)
                templates=QComboBox()
                for name in ('Modelo de legenda','Clássica','Compacta','Destaque','Discreta'):
                    templates.addItem(name)
                templates.activated.connect(lambda index:self.apply_caption_preset(index) if index else None)
                self._property_row('Estilo pronto',templates)

        if audio_kind:
            audio=self._property_group('Áudio e limpeza')
            self._property_target_layout=audio.body_layout
            self._numeric_prop(c,'volume','Volume do clipe (0–4)',0,4,step=.1)
            self._numeric_prop(c,'audio_fade_in','Fade de áudio entrada (s)',0,max(.1,c.duration),step=.1)
            self._numeric_prop(c,'audio_fade_out','Fade de áudio saída (s)',0,max(.1,c.duration),step=.1)
            self._numeric_prop(c,'audio_highpass','Filtro passa-altas (Hz; 0 = desligado)',0,20000,integer=True)
            self._numeric_prop(c,'audio_lowpass','Filtro passa-baixas (Hz; 0 = desligado)',0,20000,integer=True)
            pitch=QCheckBox('Preservar tom ao alterar velocidade')
            pitch.setObjectName('preservePitch')
            pitch.setToolTip('Usa time-stretch Rubber Band no mesmo grafo da prévia e da exportação. '
                             'Pode consumir mais CPU; em velocidade 1× não altera o áudio.')
            pitch.setChecked(c.preserve_pitch)
            pitch.toggled.connect(lambda value:self.change_prop('preserve_pitch',value))
            self._property_target_layout.addWidget(pitch)
            noise=QCheckBox('Redução de ruído FFT')
            noise.setChecked(c.audio_denoise)
            noise.toggled.connect(lambda v:self.change_prop('audio_denoise',v))
            self._property_target_layout.addWidget(noise)
            if c.kind=='video':
                check=QCheckBox('Incluir som do arquivo no mix')
                check.setChecked(c.include_audio)
                check.toggled.connect(lambda v:self.change_prop('include_audio',v))
                self._property_target_layout.addWidget(check)

        if c.kind in ('video','image','text','audio'):
            key_group=self._property_group('Keyframes')
            self._property_target_layout=key_group.body_layout
            self.auto_key=QCheckBox('Criar keyframe ao alterar no cursor')
            self.auto_key.setChecked(self._auto_key)
            self.auto_key.toggled.connect(lambda v:setattr(self,'_auto_key',v))
            self._property_target_layout.addWidget(self.auto_key)
            self.key_field_combo=QComboBox()
            fields=[('Posição X','pos_x'),('Posição Y','pos_y'),('Escala','scale'),
                    ('Opacidade','opacity'),('Volume','volume'),('Rotação','rotation')]
            for name,field in fields:
                if field=='volume' and c.kind not in ('audio','video'):continue
                if field=='opacity' and c.kind=='audio':continue
                if field in ('pos_x','pos_y','scale','rotation') and c.kind=='audio':continue
                self.key_field_combo.addItem(name,field)
            self.key_field_combo.setCurrentIndex(max(0,next((i for i in range(self.key_field_combo.count())
                if self.key_field_combo.itemData(i)==self._selected_keyfield),0)))
            self.key_field_combo.currentIndexChanged.connect(self._keyfield_changed)
            self._property_row('Propriedade animada',self.key_field_combo)
            self.ease_combo=QComboBox()
            for name,key in [('Linear','linear'),('Ease in','ease-in'),('Ease out','ease-out'),
                             ('Suave','smooth'),('Bézier suave','bezier')]:
                self.ease_combo.addItem(name,key)
            self._property_row('Curva de animação',self.ease_combo)
            self.ease_combo.currentIndexChanged.connect(self._bezier_curve_visibility)
            self.bezier_controls=QWidget()
            bezier_row=QHBoxLayout(self.bezier_controls)
            bezier_row.setContentsMargins(0,0,0,0);bezier_row.setSpacing(5)
            self.bezier_c1=QDoubleSpinBox();self.bezier_c1.setRange(0,1)
            self.bezier_c1.setSingleStep(.05);self.bezier_c1.setDecimals(2)
            self.bezier_c1.setValue(.1);self.bezier_c1.setPrefix('C1 ')
            self.bezier_c1.setToolTip('Controle vertical inicial da curva, de 0 a 1.')
            self.bezier_c2=QDoubleSpinBox();self.bezier_c2.setRange(0,1)
            self.bezier_c2.setSingleStep(.05);self.bezier_c2.setDecimals(2)
            self.bezier_c2.setValue(.9);self.bezier_c2.setPrefix('C2 ')
            self.bezier_c2.setToolTip('Controle vertical final da curva, de 0 a 1.')
            bezier_row.addWidget(self.bezier_c1);bezier_row.addWidget(self.bezier_c2)
            self._property_row('Controles Bézier',self.bezier_controls)
            self.bezier_controls.setVisible(self.ease_combo.currentData()=='bezier')
            navigation=QHBoxLayout()
            self.key_previous=QPushButton('◀ Anterior')
            self.key_previous.setObjectName('keyframePrevious')
            self.key_previous.setAccessibleName('Ir ao keyframe anterior')
            self.key_previous.clicked.connect(lambda:self.navigate_keyframe(-1))
            self.key_next=QPushButton('Próximo ▶')
            self.key_next.setObjectName('keyframeNext')
            self.key_next.setAccessibleName('Ir ao próximo keyframe')
            self.key_next.clicked.connect(lambda:self.navigate_keyframe(1))
            navigation.addWidget(self.key_previous);navigation.addWidget(self.key_next)
            self._property_target_layout.addLayout(navigation)
            row=QHBoxLayout()
            for label,callback in [('◆ Adicionar',self.add_keyframe),('✕ Apagar',self.delete_keyframe)]:
                button=QPushButton(label);button.clicked.connect(callback);row.addWidget(button)
            self._property_target_layout.addLayout(row)
            self.key_apply_curve=QPushButton('Aplicar curva ao keyframe no cursor')
            self.key_apply_curve.setToolTip('Atualiza a interpolação do keyframe mais próximo; Undo disponível.')
            self.key_apply_curve.clicked.connect(self.apply_keyframe_curve)
            self._property_target_layout.addWidget(self.key_apply_curve)
            existing=sum(len(points) for points in c.keyframes.values())
            frames=QLabel(f'{existing} keyframe(s). Ajuste a propriedade no cursor para animar.')
            frames.setWordWrap(True);self._property_target_layout.addWidget(frames)
            self._update_keyframe_navigation()
            self._load_keyframe_curve_at_cursor()
        self._property_target_layout=None
        self.props_layout.addStretch()

    def _keyfield_changed(self,index):
        self._selected_keyfield=self.key_field_combo.itemData(index)
        self._update_keyframe_navigation()
        self._load_keyframe_curve_at_cursor()

    def _bezier_curve_visibility(self,*_):
        if hasattr(self,'bezier_controls'):
            self.bezier_controls.setVisible(self.ease_combo.currentData()=='bezier')

    def _load_keyframe_curve_at_cursor(self):
        if not hasattr(self,'key_apply_curve'):return
        clip=self.project.clip(self.selected_ids[0]) if len(self.selected_ids)==1 else None
        field=self.key_field_combo.currentData() if hasattr(self,'key_field_combo') else ''
        local=self.timeline.view.cursor_time-clip.timeline_start if clip else 0.
        points=clip.keyframes.get(field,[]) if clip else []
        nearest=min(points,key=lambda point:abs(float(point.get('t',0))-local),default=None)
        if nearest is None or abs(float(nearest.get('t',0))-local)>.035:
            self.key_apply_curve.setEnabled(False)
            return
        self.key_apply_curve.setEnabled(bool(self.project.track_is_editable(clip.track_id)))
        index=self.ease_combo.findData(nearest.get('easing','linear'))
        if index>=0:self.ease_combo.setCurrentIndex(index)
        self.bezier_c1.setValue(float(nearest.get('bezier_c1',.1)))
        self.bezier_c2.setValue(float(nearest.get('bezier_c2',.9)))
        self._bezier_curve_visibility()

    def _update_keyframe_navigation(self):
        if not hasattr(self,'key_previous') or len(self.selected_ids)!=1:return
        clip=self.project.clip(self.selected_ids[0])
        field=self.key_field_combo.currentData() if hasattr(self,'key_field_combo') else ''
        points=clip.keyframes.get(field,[]) if clip else []
        local=self.timeline.view.cursor_time-clip.timeline_start if clip else 0.
        epsilon=1e-4
        self.key_previous.setEnabled(any(float(point.get('t',0))<local-epsilon for point in points))
        self.key_next.setEnabled(any(float(point.get('t',0))>local+epsilon for point in points))

    def navigate_keyframe(self,direction):
        if len(self.selected_ids)!=1:return
        clip=self.project.clip(self.selected_ids[0])
        if not clip:return
        field=self.key_field_combo.currentData()
        local=self.timeline.view.cursor_time-clip.timeline_start
        times=sorted(float(point.get('t',0)) for point in clip.keyframes.get(field,[]))
        candidates=[at for at in times if at<local-1e-4] if direction<0 else [
            at for at in times if at>local+1e-4]
        if not candidates:
            self.statusBar().showMessage('Não há outro keyframe nesta direção para a propriedade escolhida.')
            return
        target=max(candidates) if direction<0 else min(candidates)
        self.seek_to(clip.timeline_start+target)
        self._update_properties()
        self.statusBar().showMessage(f'Cursor no keyframe {field} · {target:.3f}s do bloco.')

    def change_prop(self,field,value):
        if len(self.selected_ids)!=1:return
        c=self.project.clip(self.selected_ids[0])
        if not c or not self.project.track_is_editable(c.track_id):return
        if field in ('font_color','stroke_color') and not QColor(str(value)).isValid():
            self.statusBar().showMessage('Use uma cor hexadecimal válida, por exemplo #FFFFFF.')
            return
        if field=='speed':
            self.set_speed(c.id,value);return
        if field=='preserve_pitch':
            if c.preserve_pitch==bool(value):return
            if c.kind in ('video','audio') and not self.project.can_edit_linked_av(c.id):
                self.statusBar().showMessage('Desbloqueie todas as faixas AV vinculadas para alterar velocidade/áudio.')
                return
            self.snapshot()
            changed=self.project.set_pitch_preservation(c.id,value)
            self.refresh(changed or [c.id]);return
        if field in ANIMATABLE and self._auto_key and c.keyframes.get(field):
            local_time=self.timeline.view.cursor_time-c.timeline_start
            if 0<=local_time<=c.duration:
                self.snapshot()
                put_keyframe(c,field,local_time,value,self.ease_combo.currentData()
                             if hasattr(self,'ease_combo') else 'linear')
                self.refresh([c.id]);return
        if field=='duration':
            if abs(c.duration-value)<.0001:return
            self.snapshot();c.end=c.start+value*c.speed;c.source_length=max(c.source_length,c.end)
            self.project._sync_auto_captions(c)
        elif field=='timeline_start':
            self.snapshot()
            self.project.move_clip(c.id,c.track_id,value)
        else:
            if getattr(c,field)==value:return
            self.snapshot();setattr(c,field,value)
        self.refresh([c.id])

    def begin_voice_eq_edit(self,clip_id):
        clip=self.project.clip(clip_id)
        if not clip or not self.project.track_is_editable(clip.track_id):
            return
        self.snapshot()
        self._voice_eq_snapshot_pending=True

    def apply_voice_eq_edit(self,clip_id,values,bypass,preset_name):
        clip=self.project.clip(clip_id)
        if (not clip or not self.project.track_is_editable(clip.track_id) or
                clip.kind not in ('audio','video') or not clip.include_audio):
            return
        fields={'voice_eq_bass_db':float(values['bass_db']),
                'voice_eq_mids_db':float(values['mids_db']),
                'voice_eq_treble_db':float(values['treble_db']),
                'voice_pitch_semitones':float(values['pitch_semitones']),
                'voice_dsp_bypass':bool(bypass),
                'voice_dsp_preset':str(preset_name)}
        changed=any(getattr(clip,key)!=value for key,value in fields.items())
        if not changed:
            if self._voice_eq_snapshot_pending and self.history:
                self.history.pop()
            self._voice_eq_snapshot_pending=False
            return
        resume_preview=bool(self.live.active and not self.live.paused)
        resume_at=self.timeline.view.cursor_time
        for key,value in fields.items():setattr(clip,key,value)
        self._voice_eq_snapshot_pending=False
        playback_clip=(self._playback_snapshot.clip(clip.id)
                       if self._playback_snapshot is not None else None)
        if (resume_preview and playback_clip and
                self.live.update_voice_eq(clip.id,fields,bypass)):
            self._playback_snapshot=copy.deepcopy(self.project)
            self._preview_token+=1  # pending prefetched window used stale EQ
            self._preview_next_pending=False
            self.live.discard_prefetch()
            self._refresh_voice_edit_ui(clip.id)
            self.statusBar().showMessage('EQ atualizado durante a reprodução sem reiniciar o TTS nem o FFmpeg.')
            return
        self.refresh([clip.id])
        if resume_preview:
            # FFmpeg's current pipe cannot mutate a filter graph in place. Rebuild
            # from the exact playhead with the new DSP instead of silently leaving
            # playback stopped after the user releases a control.
            self.timeline.set_cursor(resume_at)
            self.transport.set_time(resume_at,self.project.duration,self.project.fps)
            self._frame_debounce.stop()
            QTimer.singleShot(0,self.toggle_play)

    def copy_voice_adjustments(self,clip_id):
        clip=self.project.clip(clip_id)
        if (not clip or not self.project.track_is_editable(clip.track_id) or
                clip.kind not in ('audio','video') or not clip.include_audio):
            return False
        self._voice_adjustment_clipboard={key:copy.deepcopy(getattr(clip,key)) for key in (
            'voice_eq_bass_db','voice_eq_mids_db','voice_eq_treble_db',
            'voice_pitch_semitones','voice_dsp_bypass','voice_dsp_preset',
            'speed','preserve_pitch')}
        self.statusBar().showMessage(f'Ajustes de voz copiados de “{clip.title or "clipe"}”.')
        return True

    def paste_voice_adjustments(self,clip_id):
        values=self._voice_adjustment_clipboard
        clip=self.project.clip(clip_id)
        if not values:
            self.statusBar().showMessage('Copie primeiro os ajustes de outro clipe de áudio.')
            return False
        if (not clip or not self.project.track_is_editable(clip.track_id) or
                clip.kind not in ('audio','video') or not clip.include_audio):
            self.statusBar().showMessage('Selecione um clipe de áudio editável para colar os ajustes.')
            return False
        speed=float(values['speed'])
        copy_speed=.70<=speed<=1.30
        linked=self.project.linked_av_members(clip_id)
        linked_speed_change=(copy_speed and any(abs(member.speed-speed)>1e-6
                                                for member in linked))
        linked_pitch_mode_change=(copy_speed and any(
            member.preserve_pitch!=bool(values['preserve_pitch']) for member in linked))
        if ((linked_speed_change or linked_pitch_mode_change) and
                not self.project.can_edit_linked_av(clip_id)):
            self.statusBar().showMessage('Desbloqueie todas as faixas AV vinculadas para colar a velocidade.')
            return False
        fields={key:copy.deepcopy(values[key]) for key in (
            'voice_eq_bass_db','voice_eq_mids_db','voice_eq_treble_db',
            'voice_pitch_semitones','voice_dsp_bypass','voice_dsp_preset')}
        changed=any(getattr(clip,key)!=value for key,value in fields.items())
        changed=changed or linked_speed_change or linked_pitch_mode_change
        if not changed:return False
        resume_preview=bool(self.live.active and not self.live.paused)
        resume_at=self.timeline.view.cursor_time
        self.snapshot()
        for key,value in fields.items():setattr(clip,key,value)
        if copy_speed:
            self.project.set_speed(clip_id,speed)
            self.project.set_pitch_preservation(clip_id,bool(values['preserve_pitch']))
        self.refresh([clip_id])
        if resume_preview:
            self.timeline.set_cursor(resume_at)
            self.transport.set_time(resume_at,self.project.duration,self.project.fps)
            self._frame_debounce.stop()
            QTimer.singleShot(0,self.toggle_play)
        message='Ajustes de EQ e pitch colados'
        message+=(' com a velocidade do clipe. ' if copy_speed else
                  '; velocidade mantida porque a origem está fora do intervalo do painel. ')
        self.statusBar().showMessage(message+'Ctrl+Z para desfazer.')
        return True

    def _refresh_voice_edit_ui(self,clip_id):
        """Refresh clip/inspector widgets without stopping a live audio graph."""
        self.timeline.set_project(self.project,self.selected_ids)
        chosen=self.project.clip(self.selected_ids[0]) if len(self.selected_ids)==1 else None
        if hasattr(self,'narration_panel'):
            lane=self.project.track(chosen.track_id) if chosen else None
            self.narration_panel.set_clip(chosen,editable=bool(lane and not lane.locked))
        self._update_properties()
        self.actions_panel.set_context(self.project,self.selected_ids,self.active_track_id,
                                       self.timeline.view.cursor_time)

    def move_clip(self,clip_id,track_id,at):
        c=self.project.clip(clip_id)
        if not c or (c.track_id==track_id and abs(c.timeline_start-at)<.02):return
        if not self.project.track_is_editable(c.track_id) or not self.project.track_is_editable(track_id):
            self.refresh(self.selected_ids)
            self.statusBar().showMessage('Desbloqueie as duas camadas para mover o bloco.');return
        self.snapshot()
        self.project.move_clip(clip_id,track_id,at)
        self.active_track_id=track_id
        self.refresh(self.selected_ids or [clip_id])

    def batch_move(self,moves):
        if not moves:return
        if any(not self.project.track_is_editable(self.project.clip(cid).track_id) or
                   not self.project.track_is_editable(tid) for cid,tid,_ in moves if self.project.clip(cid)):
            self.statusBar().showMessage('Uma das camadas está bloqueada.');self.refresh(self.selected_ids);return
        self.snapshot()
        for cid,tid,at in moves:self.project.move_clip(cid,tid,at)
        self.refresh([cid for cid,_,_ in moves])

    def trim_clip(self,clip_id,side,at):
        c=self.project.clip(clip_id)
        if not c:return
        if c.kind in ('video','audio') and not self.project.can_edit_linked_av(clip_id):
            self.statusBar().showMessage('Desbloqueie todas as faixas AV vinculadas para aparar sem dessincronizar.')
            self.refresh(self.selected_ids or [clip_id]);return
        self.snapshot()
        updated=self.project.trim_clip(clip_id,side,at)
        if not updated:self.history.pop()
        self.refresh(self.selected_ids or [clip_id])

    def _mode_status(self,blade):
        slide=self.timeline.view.slide_mode if hasattr(self,'timeline') else False
        if hasattr(self,'select_tool_btn'):
            self.select_tool_btn.setChecked(not blade and not slide)
            self.blade_tool_btn.setChecked(blade)
            self.slide_tool_btn.setChecked(slide)
        message=('Lâmina ativa: clique para dividir blocos.' if blade else
                 'Slide ativo: arraste um clipe entre vizinhos; os limites da sequência ficam preservados.'
                 if slide else 'Selecionar ativo: arraste blocos e bordas.')
        self.statusBar().showMessage(message)

    def activate_select(self):
        self.timeline.view.blade_mode=False
        self.timeline.view.slide_mode=False
        self._mode_status(False)
        self.timeline.view.setFocus()

    def activate_blade(self):
        self.timeline.view.blade_mode=True
        self.timeline.view.slide_mode=False
        self._mode_status(True)
        self.timeline.view.setFocus()

    def activate_slide(self):
        self.timeline.view.blade_mode=False
        self.timeline.view.slide_mode=True
        self._mode_status(False)
        self.timeline.view.setFocus()

    def _slide_dragged(self,clip_id,delta):
        if abs(float(delta))<1e-5:return
        target=self.project.clip(clip_id)
        if target is None:return
        selection=[target.id]
        if target.group_id:
            selection.extend(clip.id for clip in self.project.clips
                if clip.id!=target.id and clip.group_id==target.group_id and
                abs(clip.timeline_start-target.timeline_start)<.001 and
                abs(clip.timeline_end-target.timeline_end)<.001)
        self.snapshot()
        changed=self.project.slide_clip(clip_id,delta)
        if not changed:
            self.history.pop()
            self.refresh(selection)
            self.statusBar().showMessage(
                'Slide recusado: confira os dois vizinhos, as bordas da fonte e o bloqueio das faixas.')
            return
        self.refresh(selection)
        self.statusBar().showMessage(
            f'Slide aplicado: {delta:+.3f}s · sequência e grupos vinculados preservados. Ctrl+Z para desfazer.')

    def split_on_blade(self,clip_id,at):
        c=self.project.clip(clip_id)
        if not c:return
        if not c.timeline_start+.05<at<c.timeline_end-.05:return
        linked={clip_id}
        if c.group_id:
            linked.update(x.id for x in self.project.clips if x.group_id==c.group_id and
                          x.timeline_start+.05<at<x.timeline_end-.05)
            if any(not self.project.track_is_editable(x.track_id)
                   for x in self.project.clips if x.id in linked):
                self.statusBar().showMessage('Corte cancelado: desbloqueie todas as faixas do grupo de áudio/vídeo.')
                return
        if not self.project.track_is_editable(c.track_id):
            self.statusBar().showMessage('Corte cancelado: a camada selecionada está bloqueada.')
            return
        self.snapshot()
        changed=self.project.split_at_timeline(linked,at)
        if not changed:
            self.history.pop()
            self.statusBar().showMessage('Nenhum clipe editável cruza este ponto de corte.')
            return
        self.refresh()

    def split_at_cursor(self):
        if not self.selected_ids:
            QMessageBox.information(self,'Dividir','Selecione os blocos que deseja dividir.');return
        t=self.timeline.view.cursor_time
        inside=[c for c in self.project.clips if c.id in self.selected_ids and
                c.timeline_start+.05<t<c.timeline_end-.05]
        if not inside:
            QMessageBox.information(self,'Dividir','Posicione o cursor sobre os blocos selecionados.');return
        candidate_groups={c.group_id for c in inside if c.group_id}
        blocked_groups={group for group in candidate_groups if any(
            not self.project.track_is_editable(member.track_id)
            for member in self.project.clips if member.group_id==group and
            member.timeline_start+.05<t<member.timeline_end-.05)}
        ids={c.id for c in inside if self.project.track_is_editable(c.track_id) and
             c.group_id not in blocked_groups}
        groups={self.project.clip(cid).group_id for cid in ids
                if self.project.clip(cid) and self.project.clip(cid).group_id}
        ids.update(c.id for c in self.project.clips if c.group_id in groups and
                   c.group_id not in blocked_groups and c.timeline_start+.05<t<c.timeline_end-.05 and
                   self.project.track_is_editable(c.track_id))
        if not ids:
            self.statusBar().showMessage('Corte cancelado: desbloqueie as faixas dos clipes selecionados e vinculados.')
            return
        self.snapshot()
        changed=self.project.split_at_timeline(ids,t)
        if not changed:
            self.history.pop()
            self.statusBar().showMessage('Nenhum clipe pôde ser dividido nesse ponto.')
            return
        self.refresh()
        if blocked_groups:
            self.statusBar().showMessage('Grupos em camadas bloqueadas foram preservados; os outros clipes foram divididos.')

    def ripple_delete_selected(self):
        if not self.selected_ids:return
        self.snapshot()
        removed=self.project.ripple_delete(set(self.selected_ids))
        if removed:
            self.refresh([])
            self.statusBar().showMessage(f'{removed} blocos removidos; espaço fechado apenas nas faixas afetadas.')
        else:
            self.history.pop()

    def roll_edit_selected(self,anchor_id=None):
        candidates=[self.project.clip(cid) for cid in self.selected_ids]
        candidates=[clip for clip in candidates if clip and clip.kind in ('video','audio')]
        if anchor_id:
            anchor=self.project.clip(anchor_id)
            if anchor:
                candidates=[anchor]
        pair=None
        if len(candidates)>=2:
            candidates=sorted(candidates,key=lambda clip:clip.timeline_start)
            pair=(candidates[0],candidates[1])
        elif candidates:
            anchor=candidates[0]
            neighbors=[clip for clip in self.project.clips if clip.id!=anchor.id and
                       clip.track_id==anchor.track_id and clip.kind in ('video','audio')]
            previous=next((clip for clip in sorted(neighbors,key=lambda item:item.timeline_end,
                             reverse=True) if abs(clip.timeline_end-anchor.timeline_start)<.02),None)
            following=next((clip for clip in sorted(neighbors,key=lambda item:item.timeline_start)
                             if abs(anchor.timeline_end-clip.timeline_start)<.02),None)
            pair=(previous,anchor) if previous else (anchor,following) if following else None
        if not pair or not pair[0] or not pair[1]:
            QMessageBox.information(self,'Roll · ajustar emenda',
                'Selecione dois clipes adjacentes da mesma faixa ou um clipe que toque outro.')
            return
        left,right=pair
        if (left.track_id!=right.track_id or not self.project.track_is_editable(left.track_id)):
            QMessageBox.information(self,'Roll · ajustar emenda',
                'Os dois clipes precisam estar na mesma faixa desbloqueada.')
            return
        delta,ok=QInputDialog.getDouble(self,'Roll · ajustar emenda',
            'Deslocamento da emenda em segundos (positivo estende o clipe da esquerda):',
            0.,-min(left.duration-.1,right.start/max(.25,right.speed)),
            min(right.duration-.1,(left.source_length-left.end)/max(.25,left.speed)
                if left.source_length>left.end else 0.),3)
        if not ok or abs(delta)<1e-7:return
        self.snapshot()
        changed=self.project.roll_edit(left.id,right.id,delta)
        if not changed:
            self.history.pop()
            QMessageBox.information(self,'Roll · ajustar emenda',
                'A emenda não pode avançar além das bordas da mídia ou das faixas vinculadas.')
            return
        self.refresh(changed)
        self.statusBar().showMessage(
            f'Emenda deslocada {delta:+.3f}s; duração externa preservada. Ctrl+Z para desfazer.')

    def slide_edit_selected(self):
        candidates=[self.project.clip(cid) for cid in self.selected_ids]
        candidates=[clip for clip in candidates if clip and clip.kind in ('video','audio','image')]
        if len(candidates)!=1:
            QMessageBox.information(self,'Slide','Selecione exatamente um clipe entre dois vizinhos da faixa.')
            return
        clip=candidates[0]
        delta,ok=QInputDialog.getDouble(self,'Slide · deslocar clipe entre vizinhos',
            'Deslocamento em segundos (positivo move à direita; os vizinhos ajustam):',
            .5,-3600.,3600.,3)
        if not ok or abs(delta)<1e-7:return
        old_start=clip.timeline_start
        self.snapshot()
        changed=self.project.slide_clip(clip.id,delta)
        if not changed:
            self.history.pop()
            QMessageBox.information(self,'Slide indisponível',
                'O clipe precisa ter vizinhos contíguos na faixa. Confira também os limites da fonte '
                'e se todas as faixas do grupo AV estão desbloqueadas.')
            return
        self.refresh(changed)
        moved=self.project.clip(clip.id)
        actual=moved.timeline_start-old_start if moved else delta
        self.statusBar().showMessage(
            f'Slide aplicado: clipe deslocado {actual:+.3f}s; sequência preservada. Ctrl+Z para desfazer.')

    def slip_selected(self):
        candidates=[self.project.clip(cid) for cid in self.selected_ids]
        candidates=[clip for clip in candidates if clip and clip.kind in ('video','audio','image')
                    and self.project.track_is_editable(clip.track_id)]
        if not candidates:
            QMessageBox.information(self,'Slip da fonte',
                'Selecione um clipe editável de vídeo, áudio ou imagem.')
            return
        delta,ok=QInputDialog.getDouble(self,'Slip da fonte',
            'Deslocar o conteúdo dentro do arquivo (segundos). O clipe não muda de posição nem duração:',
            0.,-360000.,360000.,3)
        if not ok or abs(delta)<1e-7:return
        old_start=candidates[0].start
        self.snapshot()
        changed=[];processed=set()
        for clip in candidates:
            if clip.id in processed:continue
            altered=self.project.slip_clip(clip.id,delta)
            processed.update(altered);changed.extend(altered)
        if not changed:
            self.history.pop()
            self.statusBar().showMessage('O deslocamento foi limitado pelo início/fim da mídia.')
            return
        self.refresh(changed)
        actual=self.project.clip(changed[0]).start-old_start
        self.statusBar().showMessage(
            f'Slip aplicado: {actual:+.3f}s na fonte; posição e duração na timeline preservadas. Ctrl+Z para desfazer.')

    def create_proxies(self):
        selected=list({c.source for c in self.project.clips if c.id in self.selected_ids and c.kind=='video'})
        if not selected:
            QMessageBox.information(self,'Proxies','Selecione blocos de vídeo para gerar proxies de prévia.');return
        if self.active_task is not None:
            QMessageBox.information(self,'Batata Quente','Cancele ou finalize a tarefa atual antes.');return
        sources=selected
        def work(progress,control=None,stage=None):
            results=[]
            for i,source in enumerate(sources):
                if control:control.checkpoint()
                def update(cur,total,index=i):
                    if progress:progress(index*100+int(100*cur/max(1,total)),len(sources)*100)
                results.append(create_proxy(source,on_progress=update,control=control,stage=stage))
            return results
        def ready(paths):
            self.statusBar().showMessage(f'{len(paths)} proxy(s) pronto(s). Preview usará os arquivos leves; exportação será original.')
        self._task(work,ready,label=f'Gerar proxy de {len(sources)} vídeo(s)')

    def group_selected(self):
        if len(self.selected_ids)<2:
            self.statusBar().showMessage('Selecione dois ou mais blocos para agrupar (Ctrl+clique).');return
        self.snapshot()
        group=self.project.group_clips(set(self.selected_ids))
        if group:
            self.refresh(self.selected_ids)
            self.statusBar().showMessage('Clipes agrupados. Arraste um para mover todos juntos.')
        else:self.history.pop()

    def ungroup_selected(self):
        if not self.selected_ids:return
        self.snapshot()
        if self.project.ungroup_clips(set(self.selected_ids)):
            self.refresh(self.selected_ids)
        else:self.history.pop()

    def separate_audio(self):
        if len(self.selected_ids)!=1:
            QMessageBox.information(self,'Separar áudio','Selecione um vídeo por vez.');return
        c=self.project.clip(self.selected_ids[0])
        if not c or c.kind!='video' or not c.include_audio or not self.project.track_is_editable(c.track_id):
            QMessageBox.information(self,'Separar áudio','Selecione um vídeo com áudio habilitado e faixa destravada.');return
        _,_,has_audio=media_info(c.source)
        if not has_audio:
            QMessageBox.information(self,'Separar áudio','O arquivo não contém uma faixa de áudio.');return
        self.snapshot()
        index=next((i for i,t in enumerate(self.project.tracks) if t.id==c.track_id),0)+1
        track=self.project.add_track('Áudio separado',index)
        source_track=self.project.track(c.track_id)
        track.volume=source_track.volume
        track.pan=source_track.pan
        track.muted=source_track.muted
        track.solo=source_track.solo
        from berofel.core.project import new_id
        group=c.group_id or new_id()
        c.group_id=group;c.include_audio=False
        audio_clip=Clip(source=c.source,start=c.start,end=c.end,title=c.title+' · áudio',
                        track_id=track.id,timeline_start=c.timeline_start,kind='audio',
                        speed=c.speed,source_length=c.source_length,volume=c.volume,
                        audio_fade_in=c.audio_fade_in,audio_fade_out=c.audio_fade_out,
                        audio_highpass=c.audio_highpass,audio_lowpass=c.audio_lowpass,
                        audio_denoise=c.audio_denoise,preserve_pitch=c.preserve_pitch,
                        keyframes={'volume':copy.deepcopy(c.keyframes.get('volume',[]))},
                        group_id=group)
        self.project.add_clip(audio_clip)
        self.refresh([c.id,audio_clip.id])
        self.statusBar().showMessage('Áudio separado e vinculado ao vídeo. Ctrl+Shift+G desvincula.')

    def add_marker(self):
        self.snapshot()
        t=self.timeline.view.cursor_time
        marker=self.project.add_marker(t,f'Marcador {len(self.project.markers)+1}')
        self.refresh(self.selected_ids)
        self.statusBar().showMessage(f'⚑ Marcador em {marker["time"]:.2f}s. Ctrl+Z para desfazer.')

    def make_transition(self):
        candidates=[c for c in self.project.clips if c.id in self.selected_ids and c.kind in ('video','image')]
        if not candidates:
            QMessageBox.information(self,'Dissolvência','Selecione um ou dois blocos visuais da mesma camada.');return
        candidates.sort(key=lambda c:c.timeline_start)
        if len(candidates)==1:
            first=candidates[0]
            successors=sorted((c for c in self.project.clips if c.track_id==first.track_id and
                               c.id!=first.id and c.kind in ('video','image') and
                               c.timeline_start>=first.timeline_start),key=lambda c:c.timeline_start)
            if not successors:
                QMessageBox.information(self,'Dissolvência','Não há próximo bloco nessa camada.');return
            candidates=[first,successors[0]]
        kind,ok=QInputDialog.getItem(self,'Transição','Efeito:',
                 ['Dissolvência','Deslizar da direita','Zoom suave'],0,False)
        if not ok:return
        style={'Dissolvência':'dissolve','Deslizar da direita':'slide','Zoom suave':'zoom'}[kind]
        duration,ok=QInputDialog.getDouble(self,'Transição','Duração da transição (segundos):',
                                           .4,.05,10.,2)
        if not ok:return
        self.snapshot()
        if not self.project.transition_overlap(candidates[0].id,candidates[1].id,duration,style=style):
            self.history.pop()
            QMessageBox.information(self,'Dissolvência',
                'Use dois clipes visuais editáveis da mesma camada e desbloqueie as faixas '
                'de áudio vinculadas para manter a transição sincronizada.');return
        self.refresh([c.id for c in candidates[:2]])
        self.statusBar().showMessage(f'{kind} de {duration:.2f}s entre blocos (com crossfade de áudio).')

    def set_speed(self,clip_id,value):
        if value is None:return
        c=self.project.clip(clip_id)
        if not c or abs(c.speed-float(value))<1e-6:return
        if c.kind in ('video','audio') and not self.project.can_edit_linked_av(clip_id):
            self.statusBar().showMessage('Desbloqueie todas as faixas AV vinculadas para alterar a velocidade.')
            return
        self.snapshot()
        if not self.project.set_speed(clip_id,float(value)):
            self.history.pop();return
        self.refresh([clip_id])
        self.statusBar().showMessage(f'Velocidade {float(value):g}×; áudio e duração ajustados automaticamente.')

    def set_narration_speed(self,clip_id,value):
        """Change narration speed with pitch preservation when this FFmpeg supports it."""
        if value is None:return
        clip=self.project.clip(clip_id)
        if not clip or abs(clip.speed-float(value))<1e-6 and clip.preserve_pitch:return
        if clip.kind not in ('audio','video') or not self.project.can_edit_linked_av(clip_id):
            self.statusBar().showMessage('Desbloqueie todas as faixas AV vinculadas para alterar velocidade.')
            return
        supports_rubberband=supports_filter('rubberband')
        self.snapshot()
        changed_speed=self.project.set_speed(clip_id,float(value))
        changed_pitch=self.project.set_pitch_preservation(clip_id,True) if supports_rubberband else []
        if not changed_speed and not changed_pitch:
            self.history.pop();return
        self.refresh([clip_id])
        if supports_rubberband:
            self.statusBar().showMessage(
                f'Velocidade {float(value):.2f}× com pitch preservado; duração e legendas atualizadas.')
        else:
            self.statusBar().showMessage(
                'Velocidade aplicada. Este FFmpeg não oferece Rubber Band; o pitch pode mudar.')

    def add_keyframe(self):
        if len(self.selected_ids)!=1:return
        c=self.project.clip(self.selected_ids[0])
        if not c or not self.project.track_is_editable(c.track_id):return
        field=self.key_field_combo.currentData() if hasattr(self,'key_field_combo') else 'scale'
        if field not in ANIMATABLE:return
        at=self.timeline.view.cursor_time-c.timeline_start
        if not 0<=at<=c.duration:
            QMessageBox.information(self,'Keyframe','Coloque o cursor dentro do bloco selecionado.');return
        easing=self.ease_combo.currentData() if hasattr(self,'ease_combo') else 'linear'
        c1=self.bezier_c1.value() if hasattr(self,'bezier_c1') else .1
        c2=self.bezier_c2.value() if hasattr(self,'bezier_c2') else .9
        self.snapshot()
        put_keyframe(c,field,at,value_at(c,field,at),easing,c1,c2)
        self._selected_keyfield=field
        self.refresh([c.id])
        self.statusBar().showMessage(f'◆ Keyframe {field} em {at:.2f}s dentro do bloco.')

    def apply_keyframe_curve(self):
        if len(self.selected_ids)!=1:return
        clip=self.project.clip(self.selected_ids[0])
        if not clip or not self.project.track_is_editable(clip.track_id):return
        field=self.key_field_combo.currentData()
        local=self.timeline.view.cursor_time-clip.timeline_start
        points=clip.keyframes.get(field,[])
        target=min(points,key=lambda point:abs(float(point.get('t',0))-local),default=None)
        if target is None or abs(float(target.get('t',0))-local)>.035:
            self.statusBar().showMessage('Posicione o cursor sobre um keyframe para editar a curva.')
            return
        easing=self.ease_combo.currentData()
        c1=self.bezier_c1.value();c2=self.bezier_c2.value()
        if target.get('easing','linear')==easing and (easing!='bezier' or
                (abs(float(target.get('bezier_c1',.1))-c1)<1e-6 and
                 abs(float(target.get('bezier_c2',.9))-c2)<1e-6)):
            return
        self.snapshot()
        target['easing']=easing
        if easing=='bezier':
            target['bezier_c1']=c1;target['bezier_c2']=c2
        else:
            target.pop('bezier_c1',None);target.pop('bezier_c2',None)
        self.refresh([clip.id])
        self.statusBar().showMessage(f'Curva {easing} aplicada ao keyframe. Desfazer disponível.')

    def delete_keyframe(self):
        if len(self.selected_ids)!=1:return
        c=self.project.clip(self.selected_ids[0]);field=self.key_field_combo.currentData()
        if not c:return
        at=self.timeline.view.cursor_time-c.timeline_start
        self.snapshot()
        if delete_keyframe(c,field,at):self.refresh([c.id])
        else:self.history.pop();self.statusBar().showMessage('Nenhum keyframe próximo do cursor.')

    def move_volume_keyframe(self,clip_id,old_at,new_at,value):
        clip=self.project.clip(clip_id)
        if not clip or not self.project.track_is_editable(clip.track_id):return
        points=clip.keyframes.get('volume',[])
        target=next((point for point in points if abs(float(point.get('t',0))-old_at)<1e-4),None)
        if target is None:return
        new_at=max(0.,min(clip.duration,round(float(new_at),5)))
        if any(point is not target and abs(float(point.get('t',0))-new_at)<1e-4 for point in points):
            self.statusBar().showMessage('Já existe um keyframe de volume nesse instante.')
            self.refresh([clip_id]);return
        if abs(float(target.get('t',0))-new_at)<1e-5 and abs(float(target.get('value',0))-value)<1e-4:return
        self.snapshot()
        target['t']=new_at
        target['value']=max(0.,min(4.,float(value)))
        points.sort(key=lambda point:float(point.get('t',0)))
        self.refresh([clip_id])
        self.statusBar().showMessage(f'Automação de volume ajustada em {new_at:.2f}s · {target["value"]:.2f}×. Desfazer disponível.')

    def delete_volume_keyframe_at(self,clip_id,at):
        clip=self.project.clip(clip_id)
        if not clip or not self.project.track_is_editable(clip.track_id):return
        if not any(abs(float(point.get('t',0))-at)<1e-4
                   for point in clip.keyframes.get('volume',[])):return
        self.snapshot()
        delete_keyframe(clip,'volume',at,tolerance=1e-4)
        self.refresh([clip_id])
        self.statusBar().showMessage(f'Ponto de volume removido em {at:.2f}s. Desfazer disponível.')

    def set_audio_fade(self,clip_id,field,value):
        clip=self.project.clip(clip_id)
        if (field not in ('audio_fade_in','audio_fade_out') or not clip or
                not self.project.track_is_editable(clip.track_id)):return
        value=max(0.,min(clip.duration,float(value)))
        if abs(float(getattr(clip,field))-value)<1e-4:return
        self.snapshot()
        setattr(clip,field,value)
        self.refresh([clip_id])
        label='entrada' if field=='audio_fade_in' else 'saída'
        self.statusBar().showMessage(f'Fade de áudio de {label}: {value:.2f}s. Desfazer disponível.')

    def delete_keyframe_at(self,clip_id,field,at):
        clip=self.project.clip(clip_id)
        if (field not in ANIMATABLE or not clip or
                not self.project.track_is_editable(clip.track_id)):return
        points=clip.keyframes.get(field,[])
        if not any(abs(float(point.get('t',0))-at)<1e-4 for point in points):return
        self.snapshot()
        delete_keyframe(clip,field,at,tolerance=1e-4)
        self.refresh([clip_id])
        self.statusBar().showMessage(f'Keyframe {field} removido em {at:.2f}s. Desfazer disponível.')

    def move_keyframe_time(self,clip_id,field,old_at,new_at):
        clip=self.project.clip(clip_id)
        if (field not in ANIMATABLE or not clip or
                not self.project.track_is_editable(clip.track_id)):return
        points=clip.keyframes.get(field,[])
        target=next((point for point in points if abs(float(point.get('t',0))-old_at)<1e-4),None)
        if target is None:return
        new_at=max(0.,min(clip.duration,round(float(new_at),5)))
        if any(point is not target and abs(float(point.get('t',0))-new_at)<1e-4 for point in points):
            self.statusBar().showMessage(f'Já existe um keyframe {field} nesse instante.')
            self.refresh([clip_id]);return
        if abs(float(target.get('t',0))-new_at)<1e-5:return
        self.snapshot()
        target['t']=new_at
        points.sort(key=lambda point:float(point.get('t',0)))
        self.refresh([clip_id])
        self.statusBar().showMessage(f'Keyframe {field} movido para {new_at:.2f}s. Desfazer disponível.')

    def toggle_snapping(self,enabled):
        self.timeline.view.snapping=enabled
        self.statusBar().showMessage('Ímã ativado.' if enabled else 'Ímã desativado.')

    def zoom_timeline(self,factor):
        self.timeline.view.zoom(factor)

    def pan_timeline_page(self,direction):
        bar=self.timeline.view.horizontalScrollBar()
        page=max(80,bar.pageStep()-48)
        bar.setValue(bar.value()+int(direction)*page)

    def fit_timeline(self):
        self.timeline.view.zoom_to_fit()

    def timeline_context_action(self,action,clip_id):
        if action=='marker':self.add_marker();return
        c=self.project.clip(clip_id)
        if not c:return
        if action not in ('group','ungroup'):
            self.selected_ids=[clip_id]
            if action in ('ripple',) and c.group_id:
                self.selected_ids=[x.id for x in self.project.clips if x.group_id==c.group_id]
        if action=='ripple':self.ripple_delete_selected()
        elif action=='slip':self.slip_selected()
        elif action=='copy':self.copy_selected_clips()
        elif action=='paste':self.paste_clips()
        elif action=='group':self.group_selected()
        elif action=='ungroup':self.ungroup_selected()
        elif action=='separate_audio':self.separate_audio()
        elif action.startswith('speed'):
            self.set_speed(clip_id,float(action[5:]))
        elif action=='fade':
            if not self.project.track_is_editable(c.track_id):return
            self.snapshot()
            c.fade_in=min(.4,c.duration/2);c.fade_out=min(.4,c.duration/2)
            if c.kind in ('video','audio'):
                c.audio_fade_in=c.fade_in;c.audio_fade_out=c.fade_out
            self.refresh([clip_id])
        elif action=='transition':self.make_transition()
        elif action=='roll':self.roll_edit_selected(clip_id)

    def move_in_preview(self,dx,dy):
        if len(self.selected_ids)!=1:return
        c=self.project.clip(self.selected_ids[0])
        if not c or c.kind not in ('video','image','text') or not self.project.track_is_editable(c.track_id):return
        self.snapshot()
        t=self.timeline.view.cursor_time-c.timeline_start
        if self._auto_key and c.keyframes.get('pos_x') and 0<=t<=c.duration:
            put_keyframe(c,'pos_x',t,value_at(c,'pos_x',t)+dx)
            put_keyframe(c,'pos_y',t,value_at(c,'pos_y',t)+dy)
        else:c.pos_x+=dx;c.pos_y+=dy
        self.refresh([c.id])

    def zoom_in_preview(self,factor):
        if len(self.selected_ids)!=1:return
        c=self.project.clip(self.selected_ids[0])
        if not c or c.kind not in ('video','image','text') or not self.project.track_is_editable(c.track_id):return
        self.snapshot()
        t=self.timeline.view.cursor_time-c.timeline_start
        if self._auto_key and c.keyframes.get('scale') and 0<=t<=c.duration:
            put_keyframe(c,'scale',t,max(.05,min(3.,value_at(c,'scale',t)*factor)))
        else:c.scale=max(.05,min(3.,c.scale*factor))
        self.refresh([c.id])

    def nudge_playhead(self,seconds):
        self.seek_to(self.timeline.view.cursor_time+seconds)

    def step_frame(self,direction):
        fps=max(1,int(self.project.fps))
        current=int(round(self.timeline.view.cursor_time*fps))
        final_frame=max(0,int(round(self.project.duration*fps)))
        target=max(0,min(final_frame,current+(1 if direction>0 else -1)))
        self.seek_to(target/fps)

    def pause_playback(self):
        if self.live.active and not self.live.paused:self.live.pause()

    def play_forward(self):
        if not self.live.active or self.live.paused:self.toggle_play()

    def delete_clips(self):
        if self.selected_ids:
            self.snapshot();self.project.drop_ids(set(self.selected_ids))
            self.stop_playback()
            self.refresh([])

    def stop_playback(self, wait_for_cleanup=False):
        # Invalida preparo async, além de encerrar os 2 pipes de FFmpeg.
        self._review_preview_end=None
        self._preview_token += 1
        self._render_seq += 1
        self._playback_snapshot = None
        self._preview_next_pending = False
        if hasattr(self,'live'):
            self.live.stop(wait_for_cleanup=wait_for_cleanup)
        if hasattr(self,'player'):
            self.player.stop()
        if hasattr(self,'play_button'):
            self.transport.set_playing(False)

    def seek_to(self,t):
        self.stop_playback()
        t=max(0.,min(float(t),self.project.duration))
        self.timeline.set_cursor(t)
        self._load_keyframe_curve_at_cursor()
        self.transport.set_time(t,self.project.duration,self.project.fps)
        self.actions_panel.playhead=t
        if len(self.selected_ids)==1:
            clip=self.project.clip(self.selected_ids[0])
            if clip:self.preview_image.set_selection(clip,self.project.width,self.project.height,t-clip.timeline_start)
        if self.project.clips:
            self._frame_debounce.start()

    def _render_static_on_seek(self):
        # Evita iniciar um render por cada pixel do arraste do cursor.
        if self._closing or not self.project.clips or self.live.active:
            return
        self.render_current_frame()

    def toggle_play(self):
        if self.live.active:
            if self.live.paused:
                self.live.resume()
            else:
                self.live.pause()
            return
        if not self.project.clips:
            QMessageBox.information(self,'Preview','Adicione algum bloco à timeline.');return
        position=self.timeline.view.cursor_time
        if position >= self.project.duration-.01:
            position=0.0
            self.timeline.set_cursor(0.)
        self.stop_playback()
        self._frame_debounce.stop()
        token=self._preview_token
        snapshot=copy.deepcopy(self.project)
        (width,fps)=self.preview_quality.currentData()
        self._playback_snapshot = snapshot
        self._playback_settings = (width,fps)
        self._preview_next_pending = False
        self.preview_stack.setCurrentWidget(self.preview_image)
        self.transport.set_preparing()
        voice_control_clip_id=(self.selected_ids[0] if len(self.selected_ids)==1 else None)
        def prepare(progress,control=None,stage=None):
            if stage:stage('Preparando composição da prévia')
            if control:control.checkpoint()
            tmp=tempfile.TemporaryDirectory(prefix='bfs_preview_')
            try:
                cmd=prepare_commands(snapshot,position,tmp.name,preview_width=width,fps=fps,
                                     voice_control_clip_id=voice_control_clip_id)
                if control:control.checkpoint()
                return (token,cmd,tmp)
            except Exception:
                tmp.cleanup()
                raise
        def ready(result):
            serial,commands,tmp=result
            if serial!=self._preview_token:
                tmp.cleanup()
                return
            try:
                self.live.start(commands,tmp,project_end=snapshot.duration)
            except Exception as exc:
                tmp.cleanup()
                self._live_error(str(exc))
        self._ui_task(prepare,ready,label='Preparar prévia')

    def _prepare_next_preview_window(self, position: float):
        """Pré-carrega o próximo trecho sem ocupar a fila das IAs.

        A reprodução e os controles continuam independentes do Batata Quente.
        """
        snapshot=self._playback_snapshot
        if snapshot is None or self._preview_next_pending or position>=snapshot.duration-.02:
            return
        self._preview_next_pending=True
        token=self._preview_token
        width,fps=self._playback_settings
        voice_control_clip_id=(self.selected_ids[0] if len(self.selected_ids)==1 else None)
        def prepare(progress,control=None,stage=None):
            tmp=tempfile.TemporaryDirectory(prefix='bfs_next_')
            try:
                cmd=prepare_commands(snapshot,position,tmp.name,preview_width=width,fps=fps,
                                     voice_control_clip_id=voice_control_clip_id)
                return (cmd,tmp)
            except Exception:
                tmp.cleanup()
                raise
        def ready(result):
            commands,tmp=result
            self._preview_next_pending=False
            if token!=self._preview_token or not self.live.active:
                tmp.cleanup()
                return
            self.live.prefetch(commands,tmp)
        task=Task(prepare)
        self.workers.add(task)
        task.signals.success.connect(ready)
        def failure(message):
            if token==self._preview_token:
                self._preview_next_pending=False
                self._live_error('Falha na próxima janela: '+message)
        task.signals.error.connect(failure)
        task.signals.cancelled.connect(lambda: failure('Preparação cancelada'))
        task.signals.finished.connect(lambda:self.workers.discard(task))
        QThreadPool.globalInstance().start(task)

    def _live_frame(self,image):
        self.preview_image.set_image(image)
        self.preview_stack.setCurrentWidget(self.preview_image)

    def _live_position(self,at):
        review_end=self._review_preview_end
        if review_end is not None and at>=review_end:
            self._review_preview_end=None
            self.stop_playback()
            self.seek_to(review_end)
            self.statusBar().showMessage('Fim da prévia da sugestão. Use “Próxima” para continuar a revisão.')
            return
        self.timeline.set_cursor(at)
        self.transport.set_time(at,self.project.duration,self.project.fps)
        if len(self.selected_ids)==1:
            clip=self.project.clip(self.selected_ids[0])
            if clip:self.preview_image.set_selection(clip,self.project.width,self.project.height,at-clip.timeline_start)

    def _live_state(self,playing):
        self.transport.set_playing(playing)

    def _live_error(self,message):
        self.stop_playback()
        self.statusBar().showMessage('Falha no preview multitrilha: '+message[:150])
        QMessageBox.warning(self,'Prévia multitrilha',
            message+'\n\nVocê ainda pode usar Quadro final, exportação '
            'e a opção Prévia MP4 (reserva), no menu Ferramentas.')

    def _live_voice_control_error(self,clip_id):
        if not self.live.active:return
        position=self.timeline.view.cursor_time
        self.stop_playback()
        self.timeline.set_cursor(position)
        self.transport.set_time(position,self.project.duration,self.project.fps)
        self.statusBar().showMessage(
            'O ajuste EQ ao vivo falhou; a prévia será recomposta com os novos parâmetros.')
        QTimer.singleShot(0,self.toggle_play)

    def preview_mp4_fallback(self):
        """Reserva para máquinas em que os dispositivos de áudio/decoders falharem.

        Renderiza a timeline composta em MP4 temporário e a reproduz no Qt.
        Pode demorar em projetos longos; não é o modo de prévia principal.
        """
        if not self.project.clips:
            return
        self.stop_playback()
        snap=copy.deepcopy(self.project)
        token=self._preview_token
        output=str(Path(tempfile.gettempdir()) / f'bfs_reserva_{id(self)}_{token}.mp4')
        self._preview_files.append(output)
        def fn(progress,control=None,stage=None):
            export_project(snap,output,on_progress=progress,control=control,stage=stage)
            return output
        def ready(path):
            if token!=self._preview_token: return
            self.player.setSource(QUrl.fromLocalFile(path))
            self.preview_stack.setCurrentWidget(self.video)
            self.player.play()
            self.statusBar().showMessage('Reproduzindo MP4 composto (reserva).')
        self._task(fn,ready,label='Prévia MP4 · renderização')

    def _ui_task(self,fn,on_success,*args,label='Prévia interativa'):
        """Ações de usuário/visualização não disputam a vaga das IAs.

        Só os modelos do Batata Quente e exportações pesadas são serializados;
        play, busca de quadros e edição não são bloqueados por transcrição.
        """
        task=Task(fn,*args)
        self.workers.add(task)
        task.signals.success.connect(on_success)
        def failure(message):
            if self._closing:return
            self.transport.set_playing(False)
            QMessageBox.warning(self,label,message)
        task.signals.error.connect(failure)
        task.signals.cancelled.connect(lambda:self.transport.set_playing(False))
        task.signals.finished.connect(lambda:self.workers.discard(task))
        QThreadPool.globalInstance().start(task)
        return task

    def _task(self,fn,on_success,*args,label='Processamento',on_audio_chunk=None,
              on_audio_success=None,on_audio_stop=None):
        # Todas as tarefas demoradas compartilham UMA vaga. Não inicia uma
        # segunda IA/exportação antes de finalizar a atual (Batata Quente).
        if self.active_task is not None:
            QMessageBox.information(self,'Batata Quente',
                'Já existe um processo em execução. Pause, cancele ou aguarde sua conclusão.')
            return None
        task=Task(fn,*args)
        self.active_task=task
        self.workers.add(task)
        if on_audio_chunk is not None:task.signals.audio_chunk.connect(on_audio_chunk)
        # A fila restringe apenas trabalhos pesados; a timeline e os controles
        # visuais continuam utilizáveis e suas miniaturas seguem sob demanda.
        self.process_panel.begin(label,task.control)
        task.signals.progress.connect(self.process_panel.set_progress)
        task.signals.stage.connect(self.process_panel.set_stage)

        def success(result):
            if self.active_task is task:
                self.active_task=None
            self.process_panel.finish('concluido')
            on_success(result)

        def error(message):
            if self.active_task is task:
                self.active_task=None
            if self._closing:return
            self.process_panel.finish('erro',message)
            self.transport.set_playing(False)
            dialog=make_processing_error_dialog(self,message)
            self._open_error_dialogs.add(dialog)
            dialog.finished.connect(lambda _result, item=dialog:
                                    self._open_error_dialogs.discard(item))
            dialog.show()
            dialog.raise_()

        def cancelled():
            if self.active_task is task:
                self.active_task=None
            self.process_panel.finish('cancelado')
            self.transport.set_playing(False)
            self.statusBar().showMessage('Processamento cancelado. Cache já concluído preservado.')

        def finished():
            self.timeline.view.visual_cache.paused=False
            self.workers.discard(task)
            if self.active_task is task:
                # Segurança contra exceção inesperada antes dos sinais de status.
                self.active_task=None
                self.process_panel.finish('erro','Tarefa encerrada sem resultado.')

        task.signals.success.connect(success)
        task.signals.error.connect(error)
        task.signals.cancelled.connect(cancelled)
        task.signals.finished.connect(finished)
        if on_audio_success is not None:task.signals.success.connect(lambda _result:on_audio_success())
        if on_audio_stop is not None:
            task.signals.error.connect(lambda _message:on_audio_stop())
            task.signals.cancelled.connect(on_audio_stop)
        QThreadPool.globalInstance().start(task)
        return task

    def render_current_frame(self):
        if not self.project.clips:
            QMessageBox.information(self,'Quadro final','Adicione elementos na timeline primeiro.');return
        self.stop_playback();self.preview_stack.setCurrentWidget(self.preview_image)
        self._render_seq+=1
        seq=self._render_seq
        project=copy.deepcopy(self.project)
        at=self.timeline.view.cursor_time
        output=str(Path(tempfile.gettempdir())/f'bfs_frame_{seq}_{id(self)}.png')
        self._preview_files.append(output)
        def fn(progress,control=None,stage=None):
            if stage:stage('FFmpeg · renderizando quadro da timeline')
            if progress:progress(0,1)
            render_frame(project,at,output,control=control)
            if progress:progress(1,1)
            return seq,output
        def ready(result):
            token,path=result
            if token==self._render_seq and not self.live.active:
                self.preview_image.load(path)
                self.preview_stack.setCurrentWidget(self.preview_image)
                self.statusBar().showMessage('Quadro composto com a ordem real de todas as camadas.')
        self._ui_task(fn,ready,label='Quadro final · FFmpeg')

    def open_clipper(self):
        """Open a non-modal ranking tool that reuses only saved transcripts."""
        if self._ai_busy or self.active_task is not None:
            QMessageBox.information(self,'Clipador Inteligente',
                'A Batata Quente já está ocupada. A análise do Clipador pode começar quando a tarefa atual terminar.')
            return
        try:
            selected,targets=self.actions_panel.selection()
        except ValueError as exc:
            QMessageBox.information(self,'Clipador Inteligente',str(exc))
            self.open_actions()
            return
        if not selected:
            QMessageBox.information(self,'Clipador Inteligente',
                'Selecione blocos de áudio/vídeo ou escolha um alcance na aba Ações IA.')
            self.open_actions()
            return
        usable=[];missing=[]
        for clip in selected:
            if words_in_clip(self.project,clip):usable.append(clip)
            else:missing.append(clip.title or clip.id[:8])
        if not usable:
            QMessageBox.information(self,'Transcrição necessária',
                'O Clipador reutiliza as palavras já salvas e não inicia uma retranscrição. '
                'Marque “Transcrever · Faster-Whisper” na aba Ações IA para estes blocos e tente novamente.')
            self.open_actions()
            return
        source_paths={str(Path(clip.source).resolve()) for clip in usable}
        words=[dict(word) for word in self.project.transcripts
            if str(Path(word.get('source','')).resolve()) in source_paths]
        originals=copy.deepcopy({target.original_id:self.project.clip(target.original_id)
                                 for target in targets})
        dialog=ClipperDialog(self)
        dialog._clipper_context={'clips':copy.deepcopy(usable),'targets':copy.deepcopy(targets),
            'originals':originals,'words':words,'missing':missing}
        dialog.analyze_requested.connect(
            lambda options,dlg=dialog:self._run_clipper(dlg,options))
        dialog.cancel_requested.connect(lambda dlg=dialog:self._cancel_clipper(dlg))
        dialog.preview_requested.connect(self.preview_clipper_candidate)
        dialog.insert_requested.connect(
            lambda candidates,dlg=dialog:self.insert_clipper_candidates(dlg,candidates))
        dialog.markers_requested.connect(
            lambda events,dlg=dialog:self.mark_clipper_events(dlg,events))
        self._clipper_dialog=dialog
        dialog.show()
        dialog.raise_()
        if missing:
            dialog.status.setText('Alguns blocos sem transcrição foram ignorados: '+', '.join(missing[:5])+'.')

    def _run_clipper(self,dialog,options):
        context=getattr(dialog,'_clipper_context',None)
        if not context:return
        if self._ai_busy or self.active_task is not None:
            QMessageBox.information(dialog,'Clipador Inteligente',
                'Aguarde a tarefa da Batata Quente terminar antes de iniciar a análise.')
            return
        if not scope_is_still_valid(self.project,context['originals'],context['targets']):
            QMessageBox.warning(dialog,'Alcance alterado',
                'O projeto mudou desde que este Clipador foi aberto. Feche e abra a ferramenta novamente.')
            return
        selected=context['clips'];words=context['words']
        dialog.set_busy(True)
        def worker(progress,control=None,stage=None):
            return analyze_clip_candidates(selected,words,options,control=control,
                                           progress=progress,stage=stage)
        def ready(result):
            self._clipper_task=None
            if self._closing or not dialog:return
            if not scope_is_still_valid(self.project,context['originals'],context['targets']):
                dialog.set_busy(False)
                QMessageBox.warning(dialog,'Alcance alterado',
                    'Você editou o material durante a análise. Nada foi inserido; reabra o Clipador para atualizar os tempos.')
                return
            dialog.set_results(result)
            if context['missing']:
                dialog.status.setText(dialog.status.text()+' Blocos sem transcrição ignorados: '+
                    ', '.join(context['missing'][:5])+'.')
        task=self._task(worker,ready,label='Clipador Inteligente · PCM e transcrição')
        if task is None:
            dialog.set_busy(False)
            return
        self._clipper_task=task
        task.signals.cancelled.connect(lambda dlg=dialog:dlg.set_busy(False))
        task.signals.error.connect(lambda _message,dlg=dialog:dlg.set_busy(False))
        task.signals.finished.connect(
            lambda current=task:setattr(self,'_clipper_task',None)
            if self._clipper_task is current else None)

    def _cancel_clipper(self,dialog):
        task=self._clipper_task
        if task is not None and self.active_task is task:
            task.control.cancel()
            dialog.status.setText('Cancelando a decodificação. Os itens concluídos no cache serão preservados.')

    def preview_clipper_candidate(self,candidate):
        clip=self.project.clip(str(candidate.get('clip_id','')))
        if clip is None:
            QMessageBox.information(self,'Prévia do candidato',
                'O clipe de origem foi removido. Reabra o Clipador para atualizar os candidatos.')
            return
        start=float(candidate['source_start'])-clip.start
        end=float(candidate['source_end'])-clip.start
        if start<-.005 or end>clip.end-clip.start+.005:
            QMessageBox.information(self,'Prévia do candidato',
                'O intervalo mudou desde a análise. Reabra o Clipador para recalcular.')
            return
        self._preview_review_finding(clip.id,max(0.,start),max(0.,end))

    def insert_clipper_candidates(self,dialog,candidates):
        additions=[];next_positions={};skipped=[]
        for candidate in sorted(candidates,key=lambda item:(item.get('clip_id',''),
                                                             item.get('source_start',0.))):
            source_clip=self.project.clip(str(candidate.get('clip_id','')))
            if source_clip is None:
                skipped.append(candidate.get('title','clipe ausente'));continue
            start=float(candidate['source_start']);end=float(candidate['source_end'])
            track=self.project.track(source_clip.track_id)
            if (not track or track.locked or start<source_clip.start-.005 or
                    end>source_clip.end+.005 or end-start<.05 or
                    not Path(source_clip.source).is_file()):
                skipped.append(source_clip.title or source_clip.id[:8]);continue
            timeline_start=next_positions.get(source_clip.track_id)
            if timeline_start is None:
                timeline_start=max((clip.timeline_end for clip in self.project.clips
                    if clip.track_id==source_clip.track_id),default=0.)
            title=(source_clip.title or Path(source_clip.source).stem)[:90]
            clone=dataclass_replace(source_clip,id=new_id(),start=start,end=end,
                timeline_start=timeline_start,title=f'Clipador · {title}',keyframes={},
                fade_in=0.,fade_out=0.,audio_fade_in=0.,audio_fade_out=0.,
                group_id='',generated_by='clipper',caption_anchor_clip_id='',
                caption_source_start=None,caption_source_end=None,caption_words=[],
                caption_generated_text='')
            additions.append(clone)
            next_positions[source_clip.track_id]=timeline_start+clone.duration
        if not additions:
            QMessageBox.information(dialog,'Clipador Inteligente',
                'Nenhum candidato pôde ser inserido. Confira se a origem ainda existe e a faixa está desbloqueada.')
            if skipped:dialog.status.setText('Ignorados: '+', '.join(skipped[:5]))
            return
        self.snapshot()
        for clip in additions:self.project.add_clip(clip)
        ids=[clip.id for clip in additions]
        self.refresh(ids)
        self.statusBar().showMessage(
            f'{len(additions)} candidato(s) adicionados ao fim da(s) faixa(s). Ctrl+Z desfaz a inserção.')
        if skipped:
            dialog.status.setText(f'{len(additions)} inserido(s); {len(skipped)} ignorado(s) por faixa bloqueada, '
                                  'origem ausente ou intervalo alterado.')

    def mark_clipper_events(self,dialog,events):
        marks=[];seen=set()
        for event in events:
            clip=self.project.clip(str(event.get('clip_id','')))
            if clip is None:continue
            source_time=float(event.get('start_ms',0))/1000.
            if source_time<clip.start or source_time>clip.end:continue
            at=clip.timeline_start+(source_time-clip.start)/clip.speed
            label=f"Clipador · energia +{float(event.get('rise_db',0)):.1f} dB"
            key=(round(at,2),label)
            if key in seen:continue
            seen.add(key)
            if any(round(float(marker.get('time',-1)),2)==key[0] and
                   marker.get('label')==label for marker in self.project.markers):continue
            marks.append((at,label))
        if not marks:
            QMessageBox.information(dialog,'Eventos acústicos',
                'Não há eventos acústicos novos para marcar neste alcance.')
            return
        self.snapshot()
        for at,label in marks:self.project.add_marker(at,label)
        self.refresh(self.selected_ids)
        self.statusBar().showMessage(
            f'{len(marks)} evento(s) acústico(s) marcado(s) na timeline. Ctrl+Z desfaz os marcadores.')

    def execute_edit_queue(self, actions, optimize_silence=True):
        """Edição combinada 0.9: uma fila com IA sequencial e revisão única.

        A timeline permanece editável; se o usuário alterar o clipe-alvo durante
        a fila, os resultados continuam no cache, mas não são aplicados a
        coordenadas obsoletas. A montagem final é reversível por Ctrl+Z.
        """
        if self._ai_busy or self.active_task is not None:
            QMessageBox.information(self,'Batata Quente',
                'Uma IA já está trabalhando. Você pode continuar editando normalmente; '
                'não é possível iniciar duas IAs pesadas simultaneamente.')
            return
        try:
            chosen=tuple(actions)
            plan=plan_actions(chosen,optimize_silence)
            selected,targets=self.actions_panel.selection()
        except ValueError as exc:
            QMessageBox.information(self,'Preparar edição',str(exc))
            self.open_actions()
            return
        # Texto livre pode ser narrado sem clipe e sem transcrição.
        if not targets and chosen==('narration',):
            self.open_narration()
            self.narration_panel._generate(True)
            return
        if not targets:
            QMessageBox.information(self,'Alcance','Escolha um ou mais blocos de áudio/vídeo.')
            self.open_actions()
            return
        srt_path=''
        if 'srt' in chosen:
            srt_path,_=QFileDialog.getSaveFileName(self,'Salvar legendas da edição combinada','',
                                                   'Legendas SRT (*.srt)')
            if not srt_path:return
            if not srt_path.lower().endswith('.srt'):srt_path+='.srt'
        originals=copy.deepcopy({t.original_id:self.project.clip(t.original_id) for t in targets})
        opts=AIOptions()
        known={c.id:words_in_clip(self.project,c) for c in selected
               if has_coverage(self.project,c,opts.whisper_model,opts.language)}
        seconds=sum(t.playback_seconds for t in targets)
        self.statusBar().showMessage(f'Fila Batata Quente: {len(chosen)} ações, '
                                     f'{len(targets)} blocos, {format_timecode(seconds)}.')
        def worker(progress,control=None,stage=None):
            return run_edit_queue(selected,chosen,options=opts,known_words=known,
                                  optimize_silence=optimize_silence,
                                  progress=progress,control=control,stage=stage)
        def ready(results):
            if not scope_is_still_valid(self.project,originals,targets):
                QMessageBox.warning(self,'Alcance alterado',
                    'Você editou blocos analisados durante a fila. O cache foi preservado, '
                    'mas os resultados não serão aplicados sobre posições antigas. '
                    'Inicie a edição novamente para reutilizar o cache.')
                return
            by_target={target.original_id:target for target in targets}
            findings=[]
            if 'silence' in chosen or 'fillers' in chosen:
                for f in results['suggestions']:
                    target=by_target.get(f['clip_id'])
                    old=originals.get(f['clip_id'])
                    if target and old:
                        entry=local_to_original_proposal(f,target,old)
                        if entry['b']-entry['a']>=.03:
                            findings.append(entry)
            approved=[]
            if findings:
                review=SuggestionsDialog(findings,
                    f'Revisar {len(findings)} cortes · seleção em massa',self)
                review.preview_requested.connect(self._preview_review_finding)
                answer=review.exec()
                if answer==QDialog.DialogCode.Rejected:
                    self.statusBar().showMessage('Revisão cancelada. Cache das IAs preservado; projeto não alterado.')
                    return
                if answer==QDialog.DialogCode.Accepted:
                    approved=review.accepted_findings()
                # Pular cortes (código 2) preserva transcrição e legendas.
            baseline=copy.deepcopy(self.project)
            def finish_edit(progress,control=None,stage=None):
                working=copy.deepcopy(baseline)
                locked_cut_groups=set()
                for finding in approved:
                    target_clip=working.clip(str(finding.get('clip_id','')))
                    if target_clip and not working.can_edit_linked_av(target_clip.id):
                        locked_cut_groups.add(target_clip.group_id or target_clip.id)
                if stage:stage('Montagem não destrutiva · aprovados e transcrições')
                if progress:progress(0,3)
                count=merge_reports(working,results['reports'])
                if results['reports']:
                    record_coverage(working,results['reports'],opts.whisper_model,opts.language)
                if control:control.checkpoint()
                if progress:progress(1,3)
                new_targets=apply_reviewed_cuts(working,targets,approved,control=control)
                if progress:progress(2,3)
                if 'subtitles' in chosen:
                    if stage:stage('Legendas · sincronizando com os trechos sobreviventes')
                    create_auto_captions(working,new_targets)
                if progress:progress(3,3)
                return working,new_targets,count,locked_cut_groups
            def finished_edit(output):
                working,new_targets,count,locked_cut_groups=output
                if self.project!=baseline:
                    QMessageBox.warning(self,'Projeto alterado',
                        'O projeto foi alterado durante a montagem. Nenhum corte foi aplicado; '
                        'os resultados das IAs continuam salvos em cache.')
                    return
                self.snapshot()
                self.project=working
                self._reveal_ai_edit_result(new_targets,approved)
                saved_srt=0
                if srt_path:
                    try:
                        saved_srt=export_scoped_srt(self.project,new_targets,srt_path)
                    except Exception as exc:
                        QMessageBox.warning(self,'Exportar SRT',str(exc))
                if 'context' in chosen:
                    dlg=QDialog(self)
                    dlg.setWindowTitle('Análise contextual Qwen · resultados para revisão')
                    dlg.resize(730,480)
                    layout=QVBoxLayout(dlg)
                    info=QLabel('Relatório de contexto: nenhuma remoção é feita por esta ação. '
                                'Cortes só são aplicados quando aprovados na revisão.')
                    info.setWordWrap(True);layout.addWidget(info)
                    text=QTextEdit();text.setReadOnly(True)
                    lines=[]
                    for r in results.get('context_reports',results['reports']):
                        lines.append('=== '+r.get('title','Bloco')+' ===')
                        lines.append(' '.join(w.get('text','') for w in r.get('words',[])))
                        for f in r.get('suggestions',[]):
                            lines.append(f"{f.get('a',0):.2f}–{f.get('b',0):.2f}s · "
                                         f"{f.get('score','?')}/100 · {f.get('note','')}")
                    text.setPlainText('\n'.join(lines) or 'Nenhuma fala ou sugestão encontrada.')
                    layout.addWidget(text)
                    close=QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
                    close.rejected.connect(dlg.reject);layout.addWidget(close)
                    dlg.exec()
                if 'narration' in chosen:
                    # Se o usuário escreveu texto livre, respeita sua escolha.
                    # Senão usa a transcrição final da edição selecionada.
                    if not self.narration_panel.text.toPlainText().strip():
                        cues=scoped_cues(self.project,new_targets)
                        self.narration_panel.set_text(' '.join(c[2] for c in cues))
                    # Invoca a narração Qwen somente após liberar a vaga
                    # do gerenciador. A timeline não é bloqueada para edição.
                    if self.narration_panel.text.toPlainText().strip():
                        QTimer.singleShot(100,lambda:self.narration_panel._generate(True))
                    else:
                        QMessageBox.information(self,'Narração Qwen3-TTS',
                            'Não há texto para narrar. Escreva um roteiro na aba Narração.')
                        self.open_narration()
                removed=len(approved)
                msg=(f'Edição concluída: {removed} cortes aprovados, {count} palavras novas; '
                     f'Whisper analisou {results["asr_seconds"]:.1f}s de '
                     f'{results["source_seconds"]:.1f}s de fonte. '
                     f'Cache: {results["cache_hits"]} acertos.')
                if saved_srt:msg+=f' SRT: {saved_srt} legendas.'
                if locked_cut_groups:
                    msg+=(f' {len(locked_cut_groups)} trecho(s) mantido(s): '
                          'desbloqueie todas as faixas de áudio/vídeo vinculadas para cortar.')
                self.statusBar().showMessage(msg)
                if results.get('qwen_errors'):
                    detail='\n'.join(results['qwen_errors'])
                    QMessageBox.warning(self,'Qwen não concluiu',
                        'A etapa Qwen falhou, mas a transcrição, revisão de cortes e legendas '
                        'das outras etapas foram preservadas. O erro completo está abaixo.\n\n'+detail)
            self._task(finish_edit,finished_edit,label='Finalizar edição · cortes e legendas')
        self._ai_busy=True
        self.actions_panel.busy(True)
        task=self._task(worker,ready,label=f'Edição combinada · {len(chosen)} ações')
        if task:
            def done():
                self._ai_busy=False
                self.actions_panel.busy(False)
            task.signals.finished.connect(done)
        else:
            self._ai_busy=False
            self.actions_panel.busy(False)

    def execute_modular(self, action: str):
        """0.8: cada clique executa UMA ação sobre UM escopo explícito."""
        if self._ai_busy or self.active_task is not None:
            QMessageBox.information(self,'Batata Quente',
                'Já existe uma operação em andamento. Pause, cancele ou aguarde sua conclusão.')
            return
        try:
            selected,targets=self.actions_panel.selection()
        except ValueError as exc:
            QMessageBox.information(self,'Alcance da ferramenta',str(exc))
            self.open_actions()
            return
        if action=='manual' and self.actions_panel.scope.currentData() in ('interval','track_interval'):
            # Permite uma legenda manual mesmo em timeline inicialmente vazia.
            try:
                spec=self.actions_panel.spec()
                if spec.out_time<=spec.in_time:
                    raise ValueError('Marque uma Saída posterior à Entrada.')
            except ValueError as exc:
                QMessageBox.warning(self,'Legenda manual',str(exc))
                return
            spans=[(spec.in_time,spec.out_time)] if (self.actions_panel.scope.currentData()=='interval' or targets) else []
        else:
            spans=[(t.timeline_start,t.timeline_end) for t in targets]
        if action=='manual':
            text=self.actions_panel.manual_text.toPlainText().strip()
            if not text:
                QMessageBox.information(self,'Legenda manual',
                    'Escreva a legenda no campo da aba Ações IA.')
                return
            if not spans:
                QMessageBox.information(self,'Legenda manual',
                    'O alcance não contém blocos. Se preferir, marque um intervalo In/Out.')
                return
            if len(spans)>8 or sum(b-a for a,b in spans)>60:
                reply=QMessageBox.question(self,'Confirmar legendas manuais',
                    f'O texto será exibido em {len(spans)} bloco(s), durante '
                    f'{sum(b-a for a,b in spans):.1f}s no total. Deseja continuar?')
                if reply!=QMessageBox.StandardButton.Yes:return
            try:
                self.snapshot()
                new=[create_manual_caption(self.project,text,a,b) for a,b in spans]
                self.refresh([c.id for c in new])
                self.statusBar().showMessage(f'{len(new)} legenda(s) manuais na timeline; sem executar IA.')
            except Exception as exc:
                self.undo()
                QMessageBox.warning(self,'Legenda manual',str(exc))
            return
        if action=='srt':
            try:
                _, targets=resolve_scope(self.project,self.actions_panel.spec(),
                                         kinds=('audio','video','text'))
            except ValueError as exc:
                QMessageBox.information(self,'SRT',str(exc))
                return
        if not targets:
            QMessageBox.information(self,'Nenhum bloco',
                'Nenhum bloco compatível no alcance escolhido. Selecione outro alcance.')
            self.open_actions()
            return
        if action=='srt':
            path,_=QFileDialog.getSaveFileName(self,'Exportar apenas legendas deste alcance','',
                                               'Legendas SRT (*.srt)')
            if not path:return
            if not path.lower().endswith('.srt'):path+='.srt'
            try:
                total=export_scoped_srt(self.project,targets,path)
                QMessageBox.information(self,'SRT do alcance',f'{total} legendas exportadas: {path}')
            except Exception as exc:
                QMessageBox.warning(self,'SRT',str(exc))
            return
        if action=='narration':
            cues=scoped_cues(self.project,targets)
            if not cues:
                QMessageBox.information(self,'Narração',
                    'Não há transcrição nesse alcance. Use Transcrever primeiro, '
                    'ou escreva qualquer texto livre na aba Narração.')
                self.open_narration()
                return
            self.narration_panel.set_text(' '.join(c[2] for c in cues))
            self.open_narration()
            self.statusBar().showMessage(f'Texto de {len(cues)} legenda(s) carregado para narrar.')
            return
        if action not in ('transcribe','subtitles','silence','fillers','context'):
            QMessageBox.warning(self,'Ferramenta','Ação desconhecida: '+str(action))
            return
        if action in ('fillers','context'):
            if not default_llama_cli().is_file() or not default_qwen_model().is_file():
                QMessageBox.information(self,'Qwen não instalado',
                    'Execute INSTALAR_QWEN_OPCIONAL.bat. As outras ações funcionam sem Qwen.')
                return
        captured=copy.deepcopy({t.original_id:self.project.clip(t.original_id) for t in targets})
        count,seconds=scope_summary(targets)
        opts=AIOptions()
        # Snapshot das palavras para que a thread não consulte um projeto mutável.
        known={c.id:words_in_clip(self.project,c) for c in selected
               if has_coverage(self.project,c,opts.whisper_model,opts.language)
               and action!='silence'}
        descriptions={'transcribe':'Somente transcrição · Whisper',
                      'subtitles':'Somente legendas · Whisper',
                      'silence':'Somente silêncios · Silero',
                      'fillers':'Vícios de linguagem · Whisper + Qwen',
                      'context':'Análise contextual · Whisper + Qwen'}
        self.statusBar().showMessage(f'{descriptions[action]}: {count} bloco(s), '
                                     f'{format_timecode(seconds)} na timeline.')

        def worker(progress,control=None,stage=None):
            return run_analysis(selected,options=opts,progress=progress,
                                control=control,stage=stage,mode=action,known_words=known)

        def ready(data):
            # Nunca aplica relatório/cortes a fontes alteradas durante o job.
            if not scope_is_still_valid(self.project,captured,targets):
                QMessageBox.warning(self,'Resultados preservados no cache',
                    'Os blocos foram modificados durante a análise. Reexecute a ação '
                    'para aplicar aos novos tempos; o cache válido será reaproveitado.')
                return
            reports=data['reports']
            merged=0
            if action!='silence':
                self.snapshot()
                merged=merge_reports(self.project,reports)
                record_coverage(self.project,reports,opts.whisper_model,opts.language)
            if action=='subtitles':
                new=create_auto_captions(self.project,targets)
                self.refresh([c.id for c in new] or list(captured))
                QMessageBox.information(self,'Legendas automáticas',
                    f'{len(new)} novo(s) bloco(s) de legenda editáveis. '
                    'Os já existentes foram preservados. Nenhum silêncio foi cortado.')
            elif action=='transcribe':
                self.refresh(list(captured))
                TranscriptDialog(reports,self).exec()
            elif action=='context':
                self.refresh(list(captured))
                # Consulta contextual é deliberadamente somente leitura.
                dlg=QDialog(self)
                dlg.setWindowTitle('Qwen · análise contextual · nenhuma alteração de vídeo')
                dlg.resize(690,430)
                layout=QVBoxLayout(dlg)
                info=QLabel('Resultados para revisão. Nesta ação não é possível aplicar cortes. '
                            'Use Vícios de linguagem para revisar e cortar.')
                info.setWordWrap(True);layout.addWidget(info)
                view=QTextEdit();view.setReadOnly(True)
                lines=[]
                for r in reports:
                    lines.append('=== '+r['title']+' ===')
                    lines.append(' '.join(w['text'] for w in r.get('words',[])))
                    for f in r['suggestions']:
                        lines.append(f"{f['a']:.2f}–{f['b']:.2f}s | nota {f['score']} | {f['note']}")
                view.setPlainText('\n'.join(lines))
                layout.addWidget(view)
                b=QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
                b.rejected.connect(dlg.reject);layout.addWidget(b)
                dlg.exec()
            elif action in ('silence','fillers'):
                self.refresh(list(captured))
                by_id={t.original_id:t for t in targets}
                findings=[]
                for f in data['suggestions']:
                    target=by_id.get(f['clip_id'])
                    original=captured.get(f['clip_id'])
                    if target and original:
                        findings.append(local_to_original_proposal(f,target,original))
                self._review(findings,'Revisar silêncios' if action=='silence'
                             else 'Revisar vícios de linguagem')
            self.statusBar().showMessage(
                f"{descriptions[action]} concluído · cache {data['cache_hits']} "
                f"· etapas novas {data['cache_misses']} · palavras novas {merged}")
        self._ai_busy=True
        self.actions_panel.busy(True)
        task=self._task(worker,ready,label=descriptions[action])
        if task:
            def finished():
                self._ai_busy=False
                self.actions_panel.busy(False)
            task.signals.finished.connect(finished)
        else:
            self._ai_busy=False
            self.actions_panel.busy(False)

    def _chosen_for_ai(self):
        selected=[]
        for c in self.project.clips:
            if c.id in self.selected_ids and c.kind in ('video','audio'):
                selected.append(copy.deepcopy(c))
        return selected

    def _ai_task(self, semantic=False, show_suggestions=True):
        if self._ai_busy or self.active_task is not None:
            QMessageBox.information(self,'Análise IA','Já existe uma análise Batata Quente em andamento.')
            return
        selected=self._chosen_for_ai()
        if not selected:
            QMessageBox.information(self, 'Análise IA',
                                    'Selecione um ou mais blocos de vídeo/áudio na timeline. '
                                    'A análise nunca começa automaticamente.')
            return
        if semantic:
            if not default_llama_cli().is_file() or not default_qwen_model().is_file():
                QMessageBox.information(self, 'Qwen não instalado',
                                        'Instale o modelo e o executável via INSTALAR_QWEN_OPCIONAL.bat. '
                                        'Faster-Whisper e Silero continuam disponíveis sem Qwen.')
                return
        opts=AIOptions(enable_qwen=semantic)
        self.statusBar().showMessage(f'Batata Quente: processando {len(selected)} bloco(s) selecionado(s)...')
        def worker(progress,control=None,stage=None):
            return run_analysis(selected, options=opts, progress=progress,
                                control=control,stage=stage)
        def ready(data):
            # Não aceita aplicar propostas antigas a clipes que foram modificados.
            valid={}
            for sc in selected:
                now=self.project.clip(sc.id)
                if now and now.source==sc.source and abs(now.start-sc.start)<.001 and abs(now.end-sc.end)<.001:
                    valid[sc.id]=True
            if not valid:
                QMessageBox.warning(self,'Análise IA','Os blocos analisados foram alterados durante a análise. '
                                    'Os dados estão no cache; selecione novamente para aplicar cortes.')
                return
            reports=[r for r in data['reports'] if r['clip_id'] in valid]
            self.snapshot()
            newly_added=merge_reports(self.project,reports)
            self.refresh([c.id for c in selected if c.id in valid])
            self.statusBar().showMessage(f"Batata Quente concluída: {data['cache_hits']} etapas do cache, "
                                         f"{data['cache_misses']} processadas; {newly_added} palavras novas.")
            dlg=TranscriptDialog(reports,self)
            dlg.exec()
            if show_suggestions:
                findings=[f for r in reports for f in r['suggestions']]
                self._review(findings,'Revisar propostas Silero' + (' + Qwen' if semantic else ''))
        self._ai_busy=True
        task=self._task(worker,ready,label=('Qwen + Silero + Whisper' if semantic else
                                             'Silero + Whisper · transcrição'))
        if task:
            task.signals.finished.connect(lambda: setattr(self,'_ai_busy',False))
        else:
            self._ai_busy=False

    def transcribe_selected(self):
        self.execute_modular('transcribe')

    def analyze_intelligent(self):
        self.execute_modular('silence')

    def analyze_semantic(self):
        self.execute_modular('fillers')

    def export_captions(self):
        if not self.project.transcripts:
            QMessageBox.information(self,'Legendas','Transcreva primeiro os blocos selecionados com a ferramenta Transcrever IA.')
            return
        path,_=QFileDialog.getSaveFileName(self,'Exportar legendas sincronizadas','','Legendas SRT (*.srt)')
        if not path:return
        if not path.lower().endswith('.srt'):path+='.srt'
        try:
            total=export_srt(self.project,path)
            QMessageBox.information(self,'Legendas',f'{total} legendas exportadas em: {path}')
        except Exception as exc:
            QMessageBox.warning(self,'Legendas',str(exc))

    def analyze_silence(self):
        selected=self._chosen_for_ai()
        if not selected:
            QMessageBox.information(self,'Analise','Selecione um ou varios blocos com audio ou video na timeline. '
                                    'Nada e analisado automaticamente.');return
        self.statusBar().showMessage(f'Analisando somente {len(selected)} blocos selecionados...')
        self._task(analyze_clips,lambda findings:self._review(findings,'Silencios detectados'),
                   selected,label='Detectar silêncios · FFmpeg')

    def analyze_repetitions(self):
        # Mantido por compatibilidade com chamadas antigas; usa orquestrador novo.
        return self.analyze_semantic()

    def _repetitions_legacy(self):
        selected=self._chosen_for_ai()
        if not selected:
            QMessageBox.information(self,'Repeticoes','Selecione primeiro os blocos com fala.');return
        if QMessageBox.question(self,'Repeticoes',
            'Faster-Whisper verificara somente os blocos selecionados. '\
            'O modelo Base precisa estar instalado. Prosseguir?')==QMessageBox.StandardButton.Yes:
            self._task(repetitions_clips,
                       lambda findings:self._review(findings,'Possiveis repeticoes'),selected,
                       label='Repetições · Whisper legado')

    def _review(self,findings,title):
        if not findings:
            QMessageBox.information(self,title,'Nenhuma sugestao nos blocos analisados.');return
        self._pending_review_findings=copy.deepcopy(findings)
        for finding in self._pending_review_findings:
            clip=self.project.clip(str(finding.get('clip_id','')))
            if clip is None:
                continue
            finding['_review_anchor']={
                'source':clip.source,'start':clip.start,'end':clip.end,
                'speed':clip.speed,'track_id':clip.track_id,
            }
        self._pending_review_title=title
        self.project.review_queue=copy.deepcopy(self._pending_review_findings)
        self.project.review_title=title
        self.header.set_stage('review')
        self._show_pending_review()

    def _show_pending_review(self):
        """Reabre sugestões pendentes com seleções preservadas na sessão."""
        if not self._pending_review_findings:
            return
        findings=self._pending_review_findings
        title=self._pending_review_title or 'Revisar sugestões'
        dlg=SuggestionsDialog(findings,title,self)
        dlg.preview_requested.connect(self._preview_review_finding)
        result=dlg.exec()
        for finding,box in zip(findings,dlg.checks):
            finding['checked']=box.isChecked()
        if result!=QDialog.DialogCode.Accepted:
            self.project.review_queue=copy.deepcopy(findings)
            self.project.review_title=title
            self._autosave()
            self.statusBar().showMessage(
                f'{len(findings)} sugestão(ões) mantidas para revisão. Use a etapa Revisar para reabrir.')
            return
        choices=dlg.accepted_findings()
        changed=[]
        for finding in choices:
            anchor=finding.get('_review_anchor')
            clip=self.project.clip(str(finding.get('clip_id','')))
            track=self.project.track(clip.track_id) if clip else None
            if (not anchor or clip is None or track is None or track.locked or
                not self.project.can_edit_linked_av(clip.id) or
                clip.source!=anchor.get('source') or clip.track_id!=anchor.get('track_id') or
                abs(clip.start-float(anchor.get('start',-1)))>1e-7 or
                abs(clip.end-float(anchor.get('end',-1)))>1e-7 or
                abs(clip.speed-float(anchor.get('speed',-1)))>1e-7):
                changed.append(str(finding.get('title') or finding.get('clip_id','bloco')))
        if changed:
            self.project.review_queue=copy.deepcopy(findings)
            self.project.review_title=title
            self._autosave()
            QMessageBox.warning(self,'Revisão desatualizada',
                'O projeto mudou desde a análise ou a faixa está bloqueada. Nenhum corte foi '
                'aplicado. Reanalise os blocos antes de aprovar estas sugestões.')
            return
        self._pending_review_findings=None
        self._pending_review_title=''
        self.project.review_queue=[]
        self.project.review_title=''
        if not choices:return
        by_clip={}
        for item in choices:
            clip=self.project.clip(item['clip_id'])
            if not clip:continue
            # A análise trabalha com tempo na FONTE; o motor de edição com
            # tempo de PLAYBACK. Não perde cortes/legendas em clips 2×/10×.
            by_clip.setdefault(item['clip_id'],[]).append((item['a']/clip.speed,item['b']/clip.speed))
        # Executa cortes não destrutivos numa cópia, permitindo cancelar antes
        # de confirmar. O projeto original não é alterado durante a tarefa.
        baseline=copy.deepcopy(self.project)
        def apply(progress,control=None,stage=None):
            working=copy.deepcopy(baseline)
            total=len(by_clip)
            if stage:stage(f'Aplicando cortes · {total} bloco(s)')
            if progress:progress(0,total)
            for number,(clip_id,spans) in enumerate(by_clip.items(),1):
                if control:control.checkpoint()
                working.cut_intervals(clip_id,spans)
                if progress:progress(number,total)
            return working
        def ready(updated):
            if self.project!=baseline:
                QMessageBox.warning(self,'Cortes','O projeto mudou durante os cortes. '
                                    'Nenhum corte automático foi aplicado.')
                return
            self.snapshot()
            self.project=updated
            self.refresh([])
            self.statusBar().showMessage(
                f'{len(choices)} cortes aplicados somente a blocos escolhidos. Ctrl+Z desfaz.')
        self._task(apply,ready,label=f'Aplicar {len(choices)} cortes')

    def export_video(self):
        if not self.project.clips:
            QMessageBox.information(self,'Exportar','A timeline esta vazia.');return
        dest,_=QFileDialog.getSaveFileName(self,'Exportar MP4 1280x720/30fps','','MP4 (*.mp4)')
        if not dest:return
        if not dest.lower().endswith('.mp4'):dest+='.mp4'
        project=copy.deepcopy(self.project)
        self.header.set_stage('export')
        def fn(progress,control=None,stage=None):
            export_project(project,dest,on_progress=progress,control=control,stage=stage)
            return dest
        self._task(fn,lambda path:QMessageBox.information(self,'Exportacao concluida',path),
                   label='Exportar vídeo · FFmpeg')

    def export_audio(self):
        if not self.project.clips:
            QMessageBox.information(self,'Exportar WAV','A timeline está vazia.');return
        dest,_=QFileDialog.getSaveFileName(self,'Exportar mixagem WAV sem perdas','','WAV PCM (*.wav)')
        if not dest:return
        if not dest.lower().endswith('.wav'):dest+='.wav'
        project=copy.deepcopy(self.project)
        self.header.set_stage('export')
        def fn(progress,control=None,stage=None):
            return export_audio_wav(project,dest,control=control,stage=stage)
        self._task(fn,lambda path:QMessageBox.information(self,'Exportação WAV concluída',path),
                   label='Exportar WAV · PCM 24-bit')

    def _save_at(self,path):
        try:
            with self._project_io_lock:
                self.project.save(path)
            self.statusBar().showMessage('Projeto salvo: '+path)
            return True
        except Exception as ex:
            QMessageBox.warning(self,'Salvar',str(ex));return False

    def save_project(self):
        path=self.project.path
        if not path:
            path,_=QFileDialog.getSaveFileName(self,'Salvar projeto','','BerofelStudio (*.berofel.json)')
            if not path:return
            if not path.endswith('.json'):path+='.berofel.json'
        self._save_at(path)

    def open_project(self):
        path,_=QFileDialog.getOpenFileName(self,'Abrir projeto','','Projeto JSON (*.json)')
        if path:
            try:
                backup,recovered_project=newer_autosave_project(path)
                recover=False
                if backup:
                    choice=QMessageBox.question(self,'Recuperar projeto',
                        'Existe uma recuperação automática mais recente. Deseja recuperar esse estado?',
                        QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No|QMessageBox.StandardButton.Cancel,
                        QMessageBox.StandardButton.Yes)
                    if choice==QMessageBox.StandardButton.Cancel:return
                    recover=choice==QMessageBox.StandardButton.Yes
                self.stop_playback()
                self.project=(recovered_project if recover and recovered_project is not None
                              else load_project(path))
                self._pending_review_findings=copy.deepcopy(self.project.review_queue) or None
                self._pending_review_title=self.project.review_title
                self.header.set_stage('analyze' if self.project.media or self.project.clips else 'import')
                self.history.clear();self.future.clear()
                self.selected_ids=[]
                self.active_track_id=self.project.tracks[0].id
                self.active_clip_id=None
                self.preview_image.pixmap=None
                self.refresh([])
                if recover:self.statusBar().showMessage('Recuperação automática carregada; o arquivo original permanece preservado.')
            except Exception as ex:
                QMessageBox.warning(self,'Abrir',str(ex))

    def new_project(self):
        if self.project.clips and QMessageBox.question(self,'Novo projeto',
                 'Criar um novo projeto? Salve o atual se quiser preserva-lo.')!=QMessageBox.StandardButton.Yes:
            return
        self.stop_playback();self.project=Project()
        self._pending_review_findings=None;self._pending_review_title=''
        self.header.set_stage('import')
        self.history.clear();self.future.clear();self.selected_ids=[]
        self.active_track_id=self.project.tracks[0].id;self.active_clip_id=None
        self.preview_image.pixmap=None;self.refresh([])

    def _autosave(self):
        if not self.project.path or self._autosave_task is not None:
            return
        try:
            with self._project_io_lock:
                actual_path=self.project.path
                expected_mtime_ns=Path(actual_path).stat().st_mtime_ns
                snapshot=copy.deepcopy(self.project)
        except Exception as ex:
            self.statusBar().showMessage(f'Autosave não iniciado: {ex}')
            return
        task=Task(write_autosave_snapshot,snapshot,actual_path,expected_mtime_ns,
                  self._project_io_lock)
        self._autosave_task=task
        self.workers.add(task)
        task.signals.error.connect(
            lambda message:self.statusBar().showMessage('Falha no autosave: '+message))
        def finished():
            self.workers.discard(task)
            if self._autosave_task is task:
                self._autosave_task=None
        task.signals.finished.connect(finished)
        QThreadPool.globalInstance().start(task)

    def closeEvent(self,event):
        self._save_ui_state()
        self.narration_panel.save_preferences()
        self.narration_stream.stop()
        self._closing=True
        self.autosave.stop()
        self._frame_debounce.stop()
        self.timeline.view._visual_timer.stop()
        if self.workers:
            for task in tuple(self.workers):
                task.control.cancel()
            # Inclui prévias interativas e processos de IA; não deixa filhos
            # FFmpeg/llama/Whisper órfãos ao sair.
            QThreadPool.globalInstance().waitForDone(4000)
        try:
            from berofel.services.qwen3_tts_local import stop_local_worker
            stop_local_worker()
        except Exception:
            pass
        self.stop_playback(wait_for_cleanup=True)
        self.timeline.view.visual_cache.close()
        for p in self._preview_files:
            try:Path(p).unlink(missing_ok=True)
            except OSError:pass
        super().closeEvent(event)

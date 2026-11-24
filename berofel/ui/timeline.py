"""Timeline multitrilha universal: camadas em ordem visual, sem trilhas tipadas.

Elementos podem ocupar qualquer camada. Clips sobrepostos NA MESMA camada
sao exibidos em sublinhas automaticas para nunca se esconderem no editor.
"""
from __future__ import annotations
from pathlib import Path
from berofel.core.editing import snap_time
from berofel.core.motion import ANIMATABLE, value_at
from berofel.services.timeline_visuals import TimelineVisualCache

from PySide6.QtCore import Qt, Signal, QRectF, QMimeData, QUrl, QPoint, QPointF, QTimer
from PySide6.QtGui import QColor, QBrush, QPen, QFont, QFontMetrics, QDrag, QPainter, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QGraphicsView, QGraphicsScene,
    QGraphicsRectItem, QGraphicsSimpleTextItem, QGraphicsLineItem,
    QInputDialog, QMenu, QToolButton
)

BG = '#15181d'
TRACK_BG = '#1e2228'
BORDER = '#3a4048'
COLORS = {
    'video': ('#26598d','#4b9de1'),
    'audio': ('#1e6c61','#39b99f'),
    'image': ('#78622f','#e1b955'),
    'text': ('#6b438c','#bc82ef'),
}
KEYFRAME_COLORS={
    'pos_x':'#8fddff','pos_y':'#9df2d4','scale':'#ffe182',
    'opacity':'#c6a5ff','volume':'#ffc66d','rotation':'#ff9b8e',
}


def keyframe_marker_points(clip,pps,width,height):
    """Posições estáveis e separadas dos keyframes para todas as propriedades."""
    if width<=0 or height<16:return []
    output=[]
    top=height*.57
    lane_step=height*.32/max(1,len(ANIMATABLE)-1)
    for lane,field in enumerate(ANIMATABLE):
        points=sorted(clip.keyframes.get(field,[]),key=lambda point:float(point.get('t',0)))
        y=top+lane*lane_step
        for point in points:
            at=float(point.get('t',0))
            if not 0<=at<=clip.duration:continue
            x=max(2.,min(float(width)-2.,at*float(pps)))
            output.append((field,point,x,y))
    return output


def volume_envelope_points(clip, pps, width, height):
    """Converte keyframes de volume em pontos dentro do bloco da timeline."""
    if clip.kind not in ('video','audio') or not clip.keyframes.get('volume'):
        return []
    duration=clip.duration
    if duration<=0 or width<=0 or height<12:
        return []
    # A curva ocupa a faixa superior e fica acima do nome do clipe e da
    # waveform, que permanecem legíveis nas alturas compactas da timeline.
    top=max(2.,height*.05)
    bottom=max(top+4.,height*.27)
    points=[]
    for key in sorted(clip.keyframes['volume'],key=lambda item:float(item.get('t',0))):
        at=float(key.get('t',0))
        if not 0.<=at<=duration:
            continue
        value=max(0.,min(4.,float(key.get('value',clip.volume))))
        x=max(2.,min(float(width)-2.,at*float(pps)))
        y=bottom-(value/4.)*(bottom-top)
        points.append((x,y))
    return points


def audio_fade_envelope_points(clip,pps,width,height):
    """Amostra o ganho efetivo do clipe, incluindo fades e automação de volume."""
    if (clip.kind not in ('video','audio') or
            (clip.kind=='video' and not clip.include_audio) or width<=0 or height<12):
        return []
    fade_in=max(0.,min(float(clip.audio_fade_in),clip.duration))
    fade_out=max(0.,min(float(clip.audio_fade_out),clip.duration))
    if fade_in<=0 and fade_out<=0:return []
    duration=clip.duration
    top=max(2.,height*.05);bottom=max(top+4.,height*.27)
    times={0.,duration}
    if fade_in:times.update((fade_in*i/8 for i in range(9)))
    if fade_out:times.update((duration-fade_out+fade_out*i/8 for i in range(9)))
    times.update(float(key.get('t',0)) for key in clip.keyframes.get('volume',[])
                 if 0<=float(key.get('t',0))<=duration)
    points=[]
    for at in sorted(times):
        gain=max(0.,min(4.,float(value_at(clip,'volume',at))))
        if fade_in and at<fade_in:gain*=at/fade_in
        if fade_out and at>duration-fade_out:gain*=(duration-at)/fade_out
        x=max(2.,min(float(width)-2.,at*float(pps)))
        y=bottom-(gain/4.)*(bottom-top)
        points.append((x,y))
    return points


def audio_fade_handle_points(clip,pps,width,height):
    """Alças verdes; x representa a duração do fade dentro do tempo reproduzido."""
    envelope=audio_fade_envelope_points(clip,pps,width,height)
    if not envelope:return []
    duration=clip.duration
    top=max(2.,height*.05);bottom=max(top+4.,height*.27)
    fade_in=max(0.,min(float(clip.audio_fade_in),duration))
    fade_out=max(0.,min(float(clip.audio_fade_out),duration))
    handles=[]
    for field,at in (('audio_fade_in',fade_in),('audio_fade_out',duration-fade_out)):
        fade=(fade_in if field=='audio_fade_in' else fade_out)
        if fade<=0:continue
        gain=max(0.,min(4.,float(value_at(clip,'volume',at))))
        if fade_in and at<fade_in:gain*=at/fade_in
        if fade_out and at>duration-fade_out:gain*=(duration-at)/fade_out
        x=max(2.,min(float(width)-2.,at*float(pps)))
        y=bottom-(gain/4.)*(bottom-top)
        handles.append((field,x,y))
    return handles


def allocate_lanes(clips):
    """Interval partitioning: gera menor numero de subfaixas visiveis."""
    ends = []
    output = {}
    for c in sorted(clips, key=lambda x:(x.timeline_start, x.timeline_end, x.id)):
        found = next((i for i, end in enumerate(ends) if c.timeline_start >= end - 1e-7), None)
        if found is None:
            found = len(ends)
            ends.append(c.timeline_end)
        else:
            ends[found] = c.timeline_end
        output[c.id] = found
    return output, max(1, len(ends))


class ClipGraphics(QGraphicsRectItem):
    def __init__(self, clip, x, y, w, h, pps=21, visual_cache=None):
        super().__init__(QRectF(0,0,max(4,w),h))
        self.clip_id = clip.id
        self.clip = clip
        self.pps = pps
        self.visual_cache=visual_cache
        self._thumb_pixmaps={}
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemUsesExtendedStyleOption,True)
        self.setPos(x,y)
        self.setBrush(QBrush(QColor(COLORS.get(clip.kind,COLORS['video'])[0])))
        self.normal_color = QColor(COLORS.get(clip.kind,COLORS['video'])[1])
        self.setPen(QPen(self.normal_color,1))
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable,True)
        self.setZValue(30)
        tooltip=(f'{clip.title or clip.kind}\nTipo: {clip.kind}\n'
                 f'Camada: {clip.track_id[:8]}\n'
                 f'Timeline: {clip.timeline_start:.2f} a {clip.timeline_end:.2f}s\n'
                 f'Origem: {clip.start:.2f} a {clip.end:.2f}s\n'
                 f'Empilhamento nesta camada: {clip.stack_order}\n'
                 f'Velocidade: {clip.speed:g}× | Keyframes: {sum(map(len,clip.keyframes.values()))}\n'
                 f'Grupo: {clip.group_id[:8] if clip.group_id else "livre"}\n')
        if clip.keyframes.get('volume'):
            tooltip+='Automação de volume em dourado · arraste os pontos para editar.\n'
        if clip.keyframes:
            tooltip+='Keyframes por propriedade têm cores próprias · arraste horizontalmente para retimar.\n'
        if ((clip.audio_fade_in or clip.audio_fade_out) and
                (clip.kind=='audio' or clip.include_audio)):
            tooltip+='Fade de áudio em verde-claro · arraste os nós na timeline ou ajuste no Inspetor.\n'
        self.setToolTip(tooltip+'Arraste para mover · Arraste bordas para recuperar ou cortar · '
                        'Ctrl+clique: multisselecao')
        icon = {'video':'▶','audio':'♫','image':'▧','text':'T'}.get(clip.kind,'■')
        text = QGraphicsSimpleTextItem(self)
        text.setBrush(QBrush(QColor('#ffffff')))
        text.setFont(QFont('Segoe UI',9))
        label = f'{icon}  {clip.title or clip.kind}'
        fm = QFontMetrics(text.font())
        if w >= 40:
            text.setText(fm.elidedText(label,Qt.TextElideMode.ElideRight,max(12,int(w-13))))
            text.setPos(6,max(4,(h-19)/2))
        if w > 24:
            edge = QGraphicsRectItem(QRectF(max(1,w-6),2,4,h-4),self)
            edge.setPen(QPen(Qt.PenStyle.NoPen))
            edge.setBrush(QBrush(QColor('#d5e8ff')))
            edge.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def paint(self,painter,option,widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing,True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.brush())
        painter.drawRoundedRect(self.rect(),5,5)
        if self.visual_cache and self.clip.source:
            left=max(2,option.exposedRect.left(),self.rect().left())
            right=min(self.rect().right()-2,option.exposedRect.right())
            if right > left:
                painter.save()
                painter.setClipRect(self.rect().adjusted(2,2,-2,-2))
                if self.clip.kind in ('video','image'):
                    import math
                    x=math.floor(left/90)*90
                    while x<right:
                        source_time=(0 if self.clip.kind=='image' else
                            self.clip.start+max(0,x)/self.pps*self.clip.speed)
                        path=self.visual_cache.get_thumb(self.clip.source,source_time)
                        if path:
                            if path not in self._thumb_pixmaps:
                                if len(self._thumb_pixmaps)>48:self._thumb_pixmaps.clear()
                                self._thumb_pixmaps[path]=QPixmap(path)
                            image=self._thumb_pixmaps[path]
                            if not image.isNull():
                                painter.setOpacity(.50)
                                painter.drawPixmap(QRectF(x,3,90,self.rect().height()-6),image,QRectF(image.rect()))
                        x+=90
                if self.clip.kind in ('video','audio') and self.clip.include_audio:
                    middle=self.rect().height()*.73
                    amplitude=self.rect().height()*.19
                    painter.setOpacity(.78)
                    painter.setPen(QPen(QColor('#b6ffdc'),1))
                    current_tile=-1
                    wave=None
                    for x in range(max(2,int(left)),min(int(right),int(self.rect().right())),3):
                        sec=self.clip.start+x/self.pps*self.clip.speed
                        tile=self.visual_cache.wave_tile(sec)
                        if current_tile!=tile:
                            current_tile=tile
                            wave=self.visual_cache.get_wave(self.clip.source,sec)
                        if wave and wave.get('peaks'):
                            peaks=wave['peaks'];step=float(wave['step'])
                            idx=round((sec-wave['offset'])/step)
                            if 0<=idx<len(peaks):
                                peak=max(.025,float(peaks[idx]))
                                painter.drawLine(int(x),int(middle-amplitude*peak),
                                                 int(x),int(middle+amplitude*peak))
                painter.restore()
        pen = QPen(QColor('#ff8126') if self.isSelected() else self.normal_color,
                   2.4 if self.isSelected() else 1)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(self.rect(),5,5)
        envelope=volume_envelope_points(self.clip,self.pps,
            self.rect().width(),self.rect().height())
        fades=audio_fade_envelope_points(self.clip,self.pps,
            self.rect().width(),self.rect().height())
        if fades:
            painter.save()
            painter.setClipRect(self.rect().adjusted(1,1,-1,-1))
            painter.setPen(QPen(QColor('#b6ffdc'),1.2,Qt.PenStyle.DashLine))
            for first,second in zip(fades,fades[1:]):
                painter.drawLine(QPointF(*first),QPointF(*second))
            painter.setPen(QPen(QColor('#153c31'),.8))
            painter.setBrush(QColor('#b6ffdc'))
            for _field,x,y in audio_fade_handle_points(self.clip,self.pps,
                    self.rect().width(),self.rect().height()):
                painter.drawEllipse(QPointF(x,y),3.,3.)
            painter.restore()
        if envelope:
            painter.save()
            painter.setClipRect(self.rect().adjusted(1,1,-1,-1))
            painter.setPen(QPen(QColor('#ffe182'),1.6))
            for first,second in zip(envelope,envelope[1:]):
                painter.drawLine(QPointF(*first),QPointF(*second))
            painter.setBrush(QColor('#ffe182'))
            painter.setPen(QPen(QColor('#17191c'),.8))
            for x,y in envelope:
                painter.drawEllipse(QPointF(x,y),2.5,2.5)
            painter.restore()
        if self.clip.speed!=1:
            painter.setPen(QColor('#ffe6a7'))
            painter.drawText(QRectF(4,2,max(5,self.rect().width()-8),14),
                             Qt.AlignmentFlag.AlignRight,f'{self.clip.speed:g}×')
        markers=keyframe_marker_points(self.clip,self.pps,
            self.rect().width(),self.rect().height())
        if markers:
            painter.save()
            painter.setPen(QPen(QColor('#15181d'),.6))
            for field,_point,x,y in markers:
                painter.setBrush(QColor(KEYFRAME_COLORS.get(field,'#ffd36d')))
                painter.drawPolygon(QPolygonF([QPointF(x,y-2.4),QPointF(x+2.4,y),
                                               QPointF(x,y+2.4),QPointF(x-2.4,y)]))
            painter.restore()


class TimelineView(QGraphicsView):
    selected_changed = Signal(list)
    seek_requested = Signal(float)
    move_requested = Signal(str,str,float)
    trim_requested = Signal(str,str,float)
    split_requested = Signal(str,float)
    slide_requested = Signal(str,float)
    media_dropped = Signal(str,str,float)
    mode_changed = Signal(bool)
    play_toggle_requested = Signal()
    context_action_requested = Signal(str,object)
    batch_move_requested = Signal(object)
    volume_keyframe_changed = Signal(str,float,float,float)
    volume_keyframe_delete_requested = Signal(str,float)
    audio_fade_changed = Signal(str,str,float)
    keyframe_time_changed = Signal(str,str,float,float)
    keyframe_delete_requested = Signal(str,str,float)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.scene_ = QGraphicsScene(self)
        self.setScene(self.scene_)
        self.horizontalScrollBar().setObjectName('timelineHorizontalScrollBar')
        self.verticalScrollBar().setObjectName('timelineVerticalScrollBar')
        self.setBackgroundBrush(QColor(BG))
        self.setRenderHint(QPainter.RenderHint.Antialiasing,True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAcceptDrops(True)
        self.setMinimumHeight(190)
        self.pps = 21.0
        self.project = None
        self.items_by_id = {}
        self.row_geom = {}
        self.cursor_time = 0.0
        self.playhead = None
        self.blade_mode = False
        self.slide_mode = False
        self.snapping = True
        self.snap_px = 12
        self._markers = []
        self._drag = None
        self._width = 2000
        self.scene_.selectionChanged.connect(self._selection)
        self.visual_cache=TimelineVisualCache()
        self._last_visual_updates=-1
        self._visual_timer=QTimer(self)
        self._visual_timer.setInterval(700)
        self._visual_timer.timeout.connect(self._poll_visuals)
        self._visual_timer.start()

    def _poll_visuals(self):
        if self._last_visual_updates!=self.visual_cache.updates:
            self._last_visual_updates=self.visual_cache.updates
            self.viewport().update()

    def set_project(self,project,selected=()):
        self.project = project
        self.rebuild(selected)

    def rebuild(self,selected=()):
        self.scene_.blockSignals(True)
        self.scene_.clear()
        self.items_by_id.clear()
        self.row_geom.clear()
        if self.project is None:
            self._width=0
            self.playhead=None
            empty_rect=QRectF(0,0,0,0)
            self.scene_.setSceneRect(empty_rect)
            self.setSceneRect(empty_rect)
            self.scene_.blockSignals(False)
            self._selection()
            return
        sec_w = self.pps
        scene_length = max(35., self.project.duration+10.)
        self._width = max(900,int(scene_length * sec_w))
        # grade vertical por segundos
        max_seconds = int(scene_length)+1
        tick = 1 if self.pps >= 28 else (2 if self.pps >= 16 else 5)
        # Limita itens de cena em gravações longas (1h20 = milhares de marcas).
        # Os segundos continuam acessíveis pelo zoom; não estoura a GUI.
        while scene_length / tick > 950:
            tick *= 2
        for sec in range(0,max_seconds,tick):
            x=sec*sec_w
            line = self.scene_.addLine(x,32,x,4000,QPen(QColor('#30353c'),.5))
            line.setZValue(-2)
            label = self.scene_.addSimpleText(f'{sec//60:02d}:{sec%60:02d}')
            label.setBrush(QColor('#9caec6'))
            label.setPos(x+2,5)
        self._markers=[]
        for marker in self.project.markers:
            mx=marker['time']*sec_w
            if mx>self._width:continue
            shaft=self.scene_.addLine(mx,29,mx,4000,QPen(QColor('#f6a967'),1,Qt.PenStyle.DashLine))
            shaft.setZValue(60)
            flag=self.scene_.addRect(QRectF(mx-4,21,9,9),QPen(QColor('#f6a967')),QBrush(QColor('#f6a967')))
            flag.setToolTip(marker.get('label','Marcador'))
            flag.setZValue(61)
            self._markers.append(flag)
        y=36
        for track in self.project.tracks:
            clips=[c for c in self.project.clips if c.track_id==track.id]
            lanes,count=allocate_lanes(clips)
            height=max(track.height, 14+count*56)
            self.row_geom[track.id]=(y,height)
            shade=self.scene_.addRect(QRectF(0,y,self._width,height),
                                      QPen(QColor(BORDER),.6),QBrush(QColor(TRACK_BG)))
            shade.setZValue(-3)
            # linha guia de cada subfaixa
            for k in range(1,count):
                ln=self.scene_.addLine(0,y+k*56,self._width,y+k*56,QPen(QColor('#334760'),.5))
                ln.setZValue(-2)
            for clip in clips:
                item=ClipGraphics(clip,clip.timeline_start*sec_w,
                    y+6+56*lanes[clip.id],clip.duration*sec_w,44,sec_w,self.visual_cache)
                if track.locked:
                    item.setOpacity(.62)
                self.scene_.addItem(item)
                item.setSelected(clip.id in selected)
                self.items_by_id[clip.id]=item
            y += height
        self.playhead=self.scene_.addLine(0,0,0,y,QPen(QColor('#ff8126'),1.8))
        self.playhead.setZValue(100)
        scene_rect=QRectF(0,0,self._width,max(200,y+2))
        self.scene_.setSceneRect(scene_rect)
        self._position_playhead()
        self.scene_.blockSignals(False)
        # Rebuild blocks scene signals to suppress selection churn. Explicitly
        # sync the view rect so QGraphicsView recalculates scrollbar ranges after
        # AI cuts, project loads, trims, and zooms change the timeline extent.
        self.setSceneRect(scene_rect)
        self._selection()

    def _position_playhead(self):
        if self.playhead:
            y=self.scene_.sceneRect().height() or 500
            self.playhead.setLine(self.cursor_time*self.pps,0,self.cursor_time*self.pps,y)

    def set_cursor(self,at:float):
        self.cursor_time=max(0.,at)
        self._position_playhead()

    def selected_ids(self):
        return [cid for cid, item in self.items_by_id.items() if item.isSelected()]

    def select_all_clips(self):
        for item in self.items_by_id.values(): item.setSelected(True)
        self._selection()

    def _selection(self):
        self.selected_changed.emit(self.selected_ids())

    def _clip_at(self, point):
        item=self.scene_.itemAt(point,self.transform())
        while item is not None and not isinstance(item,ClipGraphics):
            item=item.parentItem()
        return item if isinstance(item,ClipGraphics) else None

    def _row_at(self,y):
        for tid,(row_y,height) in self.row_geom.items():
            if row_y<=y<row_y+height:
                return tid
        return None

    def _snap_clip_local_time(self,clip,local_time):
        local_time=max(0.,min(clip.duration,float(local_time)))
        if not self.snapping:return local_time
        absolute=snap_time(self.project,clip.timeline_start+local_time,clip.id,
            threshold=self.snap_px/self.pps,
            extra=(self.cursor_time,clip.timeline_start,clip.timeline_end))
        return max(0.,min(clip.duration,absolute-clip.timeline_start))

    def _slide_preview_items(self,clip):
        """Geometry-only preview of the affected triplets; project stays untouched."""
        members=[clip]
        if clip.group_id:
            members=[item for item in self.project.clips if item.group_id==clip.group_id and
                     item.kind in ('video','audio','image') and
                     abs(item.timeline_start-clip.timeline_start)<.001 and
                     abs(item.timeline_end-clip.timeline_end)<.001]
        affected=[];seen=set()
        for middle in members:
            neighbors=[item for item in self.project.clips if item.id!=middle.id and
                       item.track_id==middle.track_id and item.kind in ('video','audio','image')]
            left=[item for item in neighbors if abs(item.timeline_end-middle.timeline_start)<.02]
            right=[item for item in neighbors if abs(middle.timeline_end-item.timeline_start)<.02]
            if len(left)!=1 or len(right)!=1:return []
            for role,model in (('left',left[0]),('middle',middle),('right',right[0])):
                if model.id in seen or model.id not in self.items_by_id:return []
                seen.add(model.id)
                item=self.items_by_id[model.id]
                affected.append((item,role,item.scenePos().x(),item.scenePos().y(),
                                 item.rect().width(),item.rect().height()))
        return affected

    def mousePressEvent(self,event):
        point=self.mapToScene(event.position().toPoint())
        if event.button()==Qt.MouseButton.LeftButton:
            if point.y() < 33:
                self.set_cursor(point.x()/self.pps)
                self.seek_requested.emit(self.cursor_time)
                event.accept(); return
            item=self._clip_at(point)
            if item and self.blade_mode:
                self.split_requested.emit(item.clip_id,max(0.,point.x()/self.pps))
                event.accept(); return
            if item:
                c=self.project.clip(item.clip_id) if self.project else None
                if c and self.project.track_is_editable(c.track_id):
                    local_x=point.x()-item.scenePos().x()
                    envelope=volume_envelope_points(c,self.pps,item.rect().width(),item.rect().height())
                    if not self.slide_mode and c.keyframes.get('volume') and envelope:
                        local_y=point.y()-item.scenePos().y()
                        ordered=sorted(c.keyframes['volume'],key=lambda key:float(key.get('t',0)))
                        nearest=min(range(len(envelope)),key=lambda i:
                            (envelope[i][0]-local_x)**2+(envelope[i][1]-local_y)**2)
                        ex,ey=envelope[nearest]
                        if (ex-local_x)**2+(ey-local_y)**2<=100:
                            key=ordered[nearest]
                            item.setSelected(True)
                            self._drag=dict(id=c.id,mode='volume',item=item,key=key,
                                orig_t=float(key.get('t',0)),orig_value=float(key.get('value',c.volume)),
                                new_t=float(key.get('t',0)),new_value=float(key.get('value',c.volume)))
                            event.accept();return
                    fade_handles=audio_fade_handle_points(c,self.pps,
                        item.rect().width(),item.rect().height())
                    if not self.slide_mode and fade_handles:
                        local_y=point.y()-item.scenePos().y()
                        nearest=min(fade_handles,key=lambda handle:
                            (handle[1]-local_x)**2+(handle[2]-local_y)**2)
                        field,fx,fy=nearest
                        if (fx-local_x)**2+(fy-local_y)**2<=100:
                            item.setSelected(True)
                            self._drag=dict(id=c.id,mode='fade',item=item,field=field,
                                original=float(getattr(c,field)),new_value=float(getattr(c,field)))
                            event.accept();return
                    key_markers=keyframe_marker_points(c,self.pps,
                        item.rect().width(),item.rect().height())
                    if not self.slide_mode and key_markers:
                        local_y=point.y()-item.scenePos().y()
                        nearest=min(key_markers,key=lambda marker:
                            (marker[2]-local_x)**2+(marker[3]-local_y)**2)
                        field,key,x,y=nearest
                        if (x-local_x)**2+(y-local_y)**2<=36:
                            item.setSelected(True)
                            self._drag=dict(id=c.id,mode='keyframe_time',item=item,
                                field=field,key=key,original=float(key.get('t',0)),
                                new_time=float(key.get('t',0)))
                            event.accept();return
                    side=('slide' if self.slide_mode else
                          'left' if local_x<7 else ('right' if local_x>item.rect().width()-8 else 'move'))
                    affected=self._slide_preview_items(c) if side=='slide' else []
                    other_ids=self.selected_ids()
                    group={cid:(g.scenePos().x(),g.scenePos().y())
                           for cid,g in self.items_by_id.items()
                           if cid in other_ids and cid!=c.id and
                           self.project.track_is_editable(self.project.clip(cid).track_id)}
                    self._drag=dict(id=c.id,mode=side,from_pt=point,orig_x=item.scenePos().x(),
                                    orig_y=item.scenePos().y(),orig_w=item.rect().width(),item=item,
                                    group=group if side=='move' and c.id in other_ids else {},
                                    affected=affected)
        super().mousePressEvent(event)
        if event.button()==Qt.MouseButton.LeftButton and self._drag and self.project:
            clip=self.project.clip(self._drag['id'])
            if clip and clip.group_id and not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                for other in self.project.clips:
                    if other.group_id==clip.group_id and other.id in self.items_by_id:
                        self.items_by_id[other.id].setSelected(True)
                self._drag['group']={cid:(g.scenePos().x(),g.scenePos().y())
                    for cid,g in self.items_by_id.items() if cid !=clip.id and g.isSelected() and
                    self.project.track_is_editable(self.project.clip(cid).track_id)}

    def mouseMoveEvent(self,event):
        if self._drag and event.buttons() & Qt.MouseButton.LeftButton:
            pt=self.mapToScene(event.position().toPoint())
            drag=self._drag
            if drag['mode']=='volume':
                item=drag['item'];clip=self.project.clip(drag['id'])
                if not clip:return
                local_x=max(0.,min(item.rect().width(),pt.x()-item.scenePos().x()))
                local_y=max(0.,min(item.rect().height()*.27,pt.y()-item.scenePos().y()))
                top=max(2.,item.rect().height()*.05)
                bottom=max(top+4.,item.rect().height()*.27)
                drag['new_t']=self._snap_clip_local_time(clip,local_x/self.pps)
                drag['new_value']=max(0.,min(4.,(bottom-local_y)*4./(bottom-top)))
                drag['key']['t']=drag['new_t'];drag['key']['value']=drag['new_value']
                item.update();event.accept();return
            if drag['mode']=='fade':
                item=drag['item'];clip=self.project.clip(drag['id'])
                if not clip:return
                local_x=max(0.,min(item.rect().width(),pt.x()-item.scenePos().x()))
                at=self._snap_clip_local_time(clip,local_x/self.pps)
                drag['new_value']=max(0.,min(clip.duration,
                    at if drag['field']=='audio_fade_in' else clip.duration-at))
                setattr(clip,drag['field'],drag['new_value'])
                item.update();event.accept();return
            if drag['mode']=='keyframe_time':
                item=drag['item'];clip=self.project.clip(drag['id'])
                if not clip:return
                local_x=max(0.,min(item.rect().width(),pt.x()-item.scenePos().x()))
                drag['new_time']=self._snap_clip_local_time(clip,local_x/self.pps)
                drag['key']['t']=drag['new_time']
                item.update();event.accept();return
            dx=pt.x()-drag['from_pt'].x()
            if abs(dx)>3 or abs(pt.y()-drag['from_pt'].y())>5:
                drag['changed']=True
                item=drag['item']
                if drag['mode'] in ('move','slide'):
                    proposed=max(0,drag['orig_x']+dx)
                    if self.snapping and self.project:
                        clip=self.project.clip(drag['id'])
                        nearest=snap_time(self.project,proposed/self.pps,drag['id'],
                                          threshold=self.snap_px/self.pps,
                                          extra=(self.cursor_time,), also_end=clip.duration)
                        proposed=nearest*self.pps
                    if drag['mode']=='slide' and drag.get('affected'):
                        delta_px=proposed-drag['orig_x']
                        for affected_item,role,old_x,old_y,old_w,old_h in drag['affected']:
                            if role=='left':x,width=old_x,max(2.,old_w+delta_px)
                            elif role=='middle':x,width=old_x+delta_px,old_w
                            else:x,width=old_x+delta_px,max(2.,old_w-delta_px)
                            affected_item.setPos(x,old_y)
                            affected_item.setRect(0,0,width,old_h)
                    else:
                        item.setPos(proposed, drag['orig_y'] if drag['mode']=='slide' else
                                    max(36,drag['orig_y']+(pt.y()-drag['from_pt'].y())))
                    if drag['mode']=='move':
                        for cid,(old_x,old_y) in drag['group'].items():
                            self.items_by_id[cid].setPos(max(0,old_x+proposed-drag['orig_x']), old_y)
                elif drag['mode']=='left':
                    newleft=min(drag['orig_x']+drag['orig_w']-4,max(0,drag['orig_x']+dx))
                    if self.snapping and self.project:
                        newleft=snap_time(self.project,newleft/self.pps,drag['id'],
                                          threshold=self.snap_px/self.pps,
                                          extra=(self.cursor_time,))*self.pps
                    item.setPos(newleft,drag['orig_y'])
                    item.setRect(0,0,drag['orig_w']+drag['orig_x']-newleft,item.rect().height())
                elif drag['mode']=='right':
                    new_width=max(4,drag['orig_w']+dx)
                    if self.snapping and self.project:
                        edge=snap_time(self.project,(drag['orig_x']+new_width)/self.pps,
                                       drag['id'],threshold=self.snap_px/self.pps,
                                       extra=(self.cursor_time,))
                        new_width=max(4,edge*self.pps-drag['orig_x'])
                    item.setRect(0,0,new_width,item.rect().height())
                event.accept();return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        drag=self._drag
        self._drag=None
        if drag and drag['mode']=='volume' and event.button()==Qt.MouseButton.LeftButton:
            drag['key']['t']=drag['orig_t'];drag['key']['value']=drag['orig_value']
            if abs(drag['new_t']-drag['orig_t'])>1e-4 or abs(drag['new_value']-drag['orig_value'])>1e-3:
                self.volume_keyframe_changed.emit(drag['id'],drag['orig_t'],
                    drag['new_t'],drag['new_value'])
            drag['item'].update();event.accept();return
        if drag and drag['mode']=='fade' and event.button()==Qt.MouseButton.LeftButton:
            setattr(drag['item'].clip,drag['field'],drag['original'])
            if abs(drag['new_value']-drag['original'])>1e-4:
                self.audio_fade_changed.emit(drag['id'],drag['field'],drag['new_value'])
            drag['item'].update();event.accept();return
        if drag and drag['mode']=='keyframe_time' and event.button()==Qt.MouseButton.LeftButton:
            drag['key']['t']=drag['original']
            if abs(drag['new_time']-drag['original'])>1e-4:
                self.keyframe_time_changed.emit(drag['id'],drag['field'],
                    drag['original'],drag['new_time'])
            drag['item'].update();event.accept();return
        if drag and drag.get('changed') and event.button()==Qt.MouseButton.LeftButton:
            item=drag['item']
            if drag['mode']=='slide':
                delta=(item.scenePos().x()-drag['orig_x'])/self.pps
                if abs(delta)>1e-4:self.slide_requested.emit(drag['id'],delta)
                event.accept();return
            if drag['mode']=='move':
                trackid=self._row_at(item.scenePos().y()+20)
                if trackid:
                    if drag['group']:
                        # Arraste agrupado horizontal, preservando as camadas originais.
                        offset=(item.scenePos().x()-drag['orig_x'])/self.pps
                        moves=[(drag['id'],trackid,max(0,item.scenePos().x()/self.pps))]
                        for cid,(old_x,old_y) in drag['group'].items():
                            clip=self.project.clip(cid)
                            if clip:moves.append((cid,clip.track_id,max(0,old_x/self.pps+offset)))
                        self.batch_move_requested.emit(moves)
                    else:
                        self.move_requested.emit(drag['id'],trackid,max(0,item.scenePos().x()/self.pps))
            elif drag['mode']=='left':
                self.trim_requested.emit(drag['id'],'left',max(0,item.scenePos().x()/self.pps))
            else:
                right=(item.scenePos().x()+item.rect().width())/self.pps
                self.trim_requested.emit(drag['id'],'right',max(0,right))
            event.accept();return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self,event):
        point=self.mapToScene(event.position().toPoint())
        self.set_cursor(point.x()/self.pps)
        self.seek_requested.emit(self.cursor_time)
        event.accept()

    def zoom(self, factor, selected=(), anchor_x=None):
        # Preserve the time under the pointer (wheel) or viewport center
        # (toolbar buttons) while the scene width is rebuilt.
        viewport_x=(self.viewport().width()//2 if anchor_x is None
                    else max(0,min(self.viewport().width(),int(anchor_x))))
        anchor_y=self.viewport().height()//2
        anchor_time=self.mapToScene(QPoint(viewport_x,anchor_y)).x()/max(.001,self.pps)
        self.pps=max(3.0,min(180.,self.pps*factor))
        self.rebuild(selected or self.selected_ids())
        self.horizontalScrollBar().setValue(round(anchor_time*self.pps-viewport_x))

    def zoom_to_fit(self):
        if self.project:
            self.pps=max(3.,min(120.,(self.viewport().width()-24)/max(4.,self.project.duration+3)))
            self.rebuild(self.selected_ids())

    def reveal_time_range(self,start,end=None,margin_fraction=.08):
        """Scroll to a time range without changing timeline zoom."""
        if not self.project:return
        start=max(0.,float(start))
        end=start if end is None else max(start,float(end))
        bar=self.horizontalScrollBar()
        width=max(1,self.viewport().width())
        margin=max(24,int(width*max(0.,min(.25,float(margin_fraction)))))
        left=start*self.pps
        right=end*self.pps
        current=bar.value()
        visible_right=current+width
        if left<current+margin:
            bar.setValue(max(0,int(left-margin)))
        elif right>visible_right-margin:
            # Keep the beginning of a long selection visible; the user can
            # continue through it with the timeline's ordinary horizontal bar.
            target=left-margin if right-left>width-2*margin else right-width+margin
            bar.setValue(max(0,int(target)))

    def contextMenuEvent(self,event):
        point=self.mapToScene(event.pos())
        item=self._clip_at(point)
        menu=QMenu(self)
        if item:
            # Right-click establishes an explicit target before the menu opens.
            # Clicking an already-selected clip keeps the whole multiselection.
            selected_before=tuple(self.selected_ids())
            if item.clip_id not in selected_before:
                for selected_id in selected_before:
                    selected_item=self.items_by_id.get(selected_id)
                    if selected_item is not None:
                        selected_item.setSelected(False)
                item.setSelected(True)
            context_target={
                'clip_id':str(item.clip_id),
                'selected_ids':tuple(self.selected_ids()),
            }
            keyframe_at=None
            clip=self.project.clip(item.clip_id) if self.project else None
            if clip:
                local_x=point.x()-item.scenePos().x()
                local_y=point.y()-item.scenePos().y()
                markers=keyframe_marker_points(clip,self.pps,item.rect().width(),item.rect().height())
                if markers:
                    nearest=min(markers,key=lambda marker:(marker[2]-local_x)**2+(marker[3]-local_y)**2)
                    field,key,mx,my=nearest
                    if (mx-local_x)**2+(my-local_y)**2<=36:
                        keyframe_at=(field,float(key.get('t',0)))
            key_at=None
            clip=self.project.clip(item.clip_id) if self.project else None
            if clip and clip.keyframes.get('volume') and keyframe_at is None:
                local_x=point.x()-item.scenePos().x()
                local_y=point.y()-item.scenePos().y()
                envelope=volume_envelope_points(clip,self.pps,item.rect().width(),item.rect().height())
                ordered=sorted(clip.keyframes['volume'],key=lambda key:float(key.get('t',0)))
                if envelope:
                    nearest=min(range(len(envelope)),key=lambda i:
                        (envelope[i][0]-local_x)**2+(envelope[i][1]-local_y)**2)
                    if (envelope[nearest][0]-local_x)**2+(envelope[nearest][1]-local_y)**2<=100:
                        key_at=float(ordered[nearest].get('t',0))
            delete_keyframe=None
            if keyframe_at is not None:
                field,at=keyframe_at
                delete_keyframe=menu.addAction(f'Excluir keyframe {field} · {at:.2f}s (Undo)')
                menu.addSeparator()
            delete_volume=None
            if key_at is not None:
                delete_volume=menu.addAction('Excluir ponto de volume · Undo disponível')
                menu.addSeparator()
            actions={
                'split': menu.addAction('✂ Dividir aqui'),
                'copy':menu.addAction('Copiar clipe(s)  ·  Ctrl+C'),
                'paste':menu.addAction('Colar no playhead  ·  Ctrl+V'),
                'slip':menu.addAction('↔ Deslocar conteúdo da fonte…'),
                'roll':menu.addAction('↔ Ajustar emenda (roll)…'),
                'ripple': menu.addAction('Excluir e fechar espaço na faixa'),
                'speed2': menu.addAction('Velocidade 2×'),
                'speed4': menu.addAction('Velocidade 4×'),
                'speed10': menu.addAction('Velocidade 10×'),
                'fade': menu.addAction('Fade de entrada e saída (0,4s)'),
                'transition':menu.addAction('Transição para o próximo bloco'),
                'separate_audio':menu.addAction('Separar áudio da imagem'),
                'group':menu.addAction('Agrupar clipes selecionados'),
                'ungroup':menu.addAction('Desagrupar clipes'),
            }
            chosen=menu.exec(event.globalPos())
            if delete_keyframe is not None and chosen==delete_keyframe:
                self.keyframe_delete_requested.emit(item.clip_id,*keyframe_at)
                event.accept();return
            if delete_volume is not None and chosen==delete_volume:
                self.volume_keyframe_delete_requested.emit(item.clip_id,key_at)
                event.accept();return
            action=next((name for name,act in actions.items() if act==chosen),None)
            if action:
                if action=='split':self.split_requested.emit(item.clip_id,point.x()/self.pps)
                else:self.context_action_requested.emit(action,context_target)
        else:
            add=menu.addAction('Adicionar marcador aqui [M]')
            chosen=menu.exec(event.globalPos())
            if chosen==add:
                self.set_cursor(max(0,point.x()/self.pps))
                self.context_action_requested.emit('marker',{'clip_id':'','selected_ids':()})
        event.accept()

    def wheelEvent(self,event):
        self.scroll_from_wheel(event)

    def scroll_from_wheel(self,event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            current=self.selected_ids()
            delta=event.pixelDelta().y() or event.angleDelta().y()
            self.zoom(1.15 if delta>0 else 1/1.15,current,
                      anchor_x=round(event.position().x()))
            event.accept();return
        pixels=event.pixelDelta()
        angles=event.angleDelta()
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            bar=self.verticalScrollBar()
            delta=pixels.y() or pixels.x() or angles.y() or angles.x()
        else:
            bar=self.horizontalScrollBar()
            delta=pixels.x() or pixels.y() or angles.x() or angles.y()
        if delta:
            # QWheelEvent usa sinais opostos para movimento do gesto e do
            # conteúdo: arrastar o trackpad para a esquerda avança no tempo.
            bar.setValue(bar.value()-int(delta))
        event.accept()

    def keyPressEvent(self,event):
        # Atalhos simples apenas quando a timeline tem foco, sem roubar
        # teclas de entrada dos campos de propriedades.
        if event.modifiers()==Qt.KeyboardModifier.ControlModifier and event.key()==Qt.Key.Key_A:
            self.select_all_clips()
            event.accept();return
        if event.modifiers()==Qt.KeyboardModifier.NoModifier:
            if event.key()==Qt.Key.Key_Space:
                self.play_toggle_requested.emit()
                event.accept();return
            if event.key()==Qt.Key.Key_V:
                self.blade_mode=False
                self.slide_mode=False
                self.mode_changed.emit(False)
                event.accept();return
            if event.key()==Qt.Key.Key_B:
                self.blade_mode=True
                self.slide_mode=False
                self.mode_changed.emit(True)
                event.accept();return
            if event.key()==Qt.Key.Key_G:
                self.blade_mode=False
                self.slide_mode=True
                self.mode_changed.emit(False)
                event.accept();return
        super().keyPressEvent(event)

    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
        else: super().dragEnterEvent(event)

    def dragMoveEvent(self,event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
        else: super().dragMoveEvent(event)

    def dropEvent(self,event):
        if event.mimeData().hasUrls():
            point=self.mapToScene(event.position().toPoint())
            trackid=self._row_at(point.y())
            if trackid:
                for url in event.mimeData().urls():
                    if url.isLocalFile():
                        self.media_dropped.emit(url.toLocalFile(),trackid,max(0,point.x()/self.pps))
                event.acceptProposedAction();return
        super().dropEvent(event)


class TrackHeader(QWidget):
    change_requested = Signal(str,str)
    def __init__(self,track,height,parent=None):
        super().__init__(parent)
        self.track=track
        self.setFixedHeight(int(height))
        self.setObjectName('trackHeader')
        outer=QVBoxLayout(self)
        outer.setContentsMargins(5,4,5,4)
        outer.setSpacing(2)
        title=QLabel(track.name)
        title.setObjectName('trackName')
        title.setWordWrap(True)
        title.setMinimumHeight(19)
        title.setToolTip('Ordem de cima para baixo: frente → fundo. Duplo clique para renomear.')
        # Renomeacao pelo menu de contexto, evitando sobrescrever evento Qt.
        outer.addWidget(title)
        row=QHBoxLayout();row.setSpacing(2)
        for text,tip,action,active in [
            ('↑','Mover para cima (frente)','up',False),
            ('↓','Mover para baixo (fundo)','down',False),
            ('◉','Ocultar IMAGEM desta camada','hide',track.hidden),
            ('♫','Silenciar AUDIO desta camada','mute',track.muted),
            ('S','Ouvir somente AUDIO desta camada (solo)','solo',track.solo),
            ('▣','Bloquear edicao da camada','lock',track.locked),
        ]:
            btn=QToolButton(self);btn.setObjectName(f'trackAction_{action}')
            btn.setText(text);btn.setToolTip(tip);btn.setAccessibleName(tip)
            btn.setProperty('trackAction',action)
            btn.setFixedSize(24,24)
            btn.setCheckable(action in ('hide','mute','solo','lock'))
            btn.setChecked(active)
            btn.clicked.connect(lambda checked=False,a=action: self.change_requested.emit(track.id,a))
            row.addWidget(btn)
        outer.addLayout(row)
        outer.addStretch(1)
        self.setStyleSheet('QWidget#trackHeader{background:#202329;border-bottom:1px solid #383d45;} '
                           'QToolButton{background:#2b3037;color:#e5e8ec;border:0;border-radius:3px;} '
                           'QToolButton:hover{background:#3b4149;} '
                           'QToolButton:checked{background:#653c21;color:#ffb370;} '
                           'QToolButton#trackAction_hide:checked{background:#244f6c;color:#c8eaff;} '
                           'QToolButton#trackAction_mute:checked{background:#622f35;color:#ffd1d4;} '
                           'QToolButton#trackAction_solo:checked{background:#285b42;color:#ceffdf;} '
                           'QToolButton#trackAction_lock:checked{background:#67512b;color:#ffe8b1;}')

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            self.change_requested.emit(self.track.id,'activate')
        super().mousePressEvent(event)

    def contextMenuEvent(self,event):
        menu=QMenu(self)
        rename=menu.addAction('Renomear camada')
        up=menu.addAction('Mover para frente (cima)')
        down=menu.addAction('Mover para fundo (baixo)')
        menu.addSeparator()
        mix=menu.addAction('Mixagem de áudio · ganho e balanço')
        menu.addSeparator()
        delete=menu.addAction('Excluir camada vazia')
        selected=menu.exec(event.globalPos())
        action={rename:'rename',up:'up',down:'down',mix:'mix',delete:'remove'}.get(selected)
        if action:
            self.change_requested.emit(self.track.id,action)


class TimelineHeaderScrollArea(QScrollArea):
    """Cabeçalhos de faixa que encaminham a roda para a régua do tempo."""
    def __init__(self,parent=None):
        super().__init__(parent)
        self.timeline_view=None

    def wheelEvent(self,event):
        if self.timeline_view is not None:
            self.timeline_view.scroll_from_wheel(event)
            return
        super().wheelEvent(event)


class TimelineWidget(QWidget):
    selected_changed = Signal(list)
    seek_requested = Signal(float)
    clip_move_requested = Signal(str,str,float)
    clip_trim_requested = Signal(str,str,float)
    split_requested = Signal(str,float)
    slide_requested = Signal(str,float)
    media_dropped = Signal(str,str,float)
    mode_changed = Signal(bool)
    play_toggle_requested = Signal()
    track_change_requested = Signal(str,str)
    context_action_requested = Signal(str,object)
    batch_move_requested = Signal(object)
    volume_keyframe_changed = Signal(str,float,float,float)
    volume_keyframe_delete_requested = Signal(str,float)
    audio_fade_changed = Signal(str,str,float)
    keyframe_time_changed = Signal(str,str,float,float)
    keyframe_delete_requested = Signal(str,str,float)

    def __init__(self,parent=None):
        super().__init__(parent)
        lay=QHBoxLayout(self)
        lay.setSpacing(0);lay.setContentsMargins(0,0,0,0)
        self.headers=TimelineHeaderScrollArea()
        self.headers.setFixedWidth(178)
        self.headers.setWidgetResizable(False)
        self.headers.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.headers.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.headers.setFrameShape(QFrame.Shape.NoFrame)
        self.view=TimelineView(self)
        self.headers.timeline_view=self.view
        lay.addWidget(self.headers)
        lay.addWidget(self.view,1)
        self.view.selected_changed.connect(self.selected_changed)
        self.view.seek_requested.connect(self.seek_requested)
        self.view.move_requested.connect(self.clip_move_requested)
        self.view.trim_requested.connect(self.clip_trim_requested)
        self.view.split_requested.connect(self.split_requested)
        self.view.slide_requested.connect(self.slide_requested)
        self.view.media_dropped.connect(self.media_dropped)
        self.view.mode_changed.connect(self.mode_changed)
        self.view.play_toggle_requested.connect(self.play_toggle_requested)
        self.view.context_action_requested.connect(self.context_action_requested)
        self.view.batch_move_requested.connect(self.batch_move_requested)
        self.view.volume_keyframe_changed.connect(self.volume_keyframe_changed)
        self.view.volume_keyframe_delete_requested.connect(self.volume_keyframe_delete_requested)
        self.view.audio_fade_changed.connect(self.audio_fade_changed)
        self.view.keyframe_time_changed.connect(self.keyframe_time_changed)
        self.view.keyframe_delete_requested.connect(self.keyframe_delete_requested)
        self.view.verticalScrollBar().valueChanged.connect(
            self.headers.verticalScrollBar().setValue)
        self.headers.verticalScrollBar().valueChanged.connect(
            self.view.verticalScrollBar().setValue)
        self.setMinimumHeight(185)

    def set_project(self,project,selected=()):
        self.view.set_project(project,selected)
        self.rebuild_headers()

    def rebuild_headers(self):
        old=self.headers.takeWidget()
        if old: old.deleteLater()
        widget=QWidget()
        widget.setFixedWidth(177)
        total_height=int(self.view.scene_.sceneRect().height())
        widget.setFixedHeight(max(200,total_height))
        for track in self.view.project.tracks:
            y,h=self.view.row_geom[track.id]
            head=TrackHeader(track,h,widget)
            head.setGeometry(0,int(y),177,int(h))
            head.change_requested.connect(self.track_change_requested)
        ruler=QLabel(' FRENTE ↑  |  FUNDO ↓',widget)
        ruler.setGeometry(0,0,177,35)
        ruler.setStyleSheet('color:#f7cf85;background:#111924;font-weight:bold;')
        self.headers.setWidget(widget)

    def selected_ids(self): return self.view.selected_ids()
    def select_all_clips(self): self.view.select_all_clips()
    def set_cursor(self,t): self.view.set_cursor(t)

    def wheelEvent(self,event):
        super().wheelEvent(event)

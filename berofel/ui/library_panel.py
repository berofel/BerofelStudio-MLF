"""Biblioteca lateral inspirada no LibraryDock legado, ligada ao projeto atual."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QColor, QDrag
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QScrollArea, QStackedWidget, QToolButton, QVBoxLayout,
    QWidget,
)
from .wheel_controls import WheelGuardComboBox as QComboBox


class MediaList(QListWidget):
    """Arrasta caminhos de mídia válidos para qualquer faixa da timeline."""
    def startDrag(self, actions):
        item=self.currentItem()
        if not item:return
        from PySide6.QtCore import QMimeData
        mime=QMimeData()
        mime.setUrls([QUrl.fromLocalFile(item.data(Qt.ItemDataRole.UserRole))])
        drag=QDrag(self);drag.setMimeData(mime);drag.exec(Qt.DropAction.CopyAction)


class LibraryDock(QFrame):
    import_requested = Signal()
    relink_requested = Signal()
    marker_activated = Signal(float)

    VIDEO={'.mp4','.mov','.mkv','.avi','.webm','.m4v','.mpg','.mpeg'}
    AUDIO={'.mp3','.wav','.m4a','.flac','.ogg','.aac','.wma'}
    IMAGE={'.png','.jpg','.jpeg','.bmp','.webp','.tif','.tiff'}

    def __init__(self,parent=None):
        super().__init__(parent)
        self._compact_labels=None
        self.setObjectName('libraryDock')
        self.setMinimumWidth(205);self.setMaximumWidth(440)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True)
        root=QHBoxLayout(self);root.setContentsMargins(0,0,0,0);root.setSpacing(0)

        rail=QFrame();rail.setObjectName('libraryRail');rail.setFixedWidth(65)
        nav=QVBoxLayout(rail);nav.setContentsMargins(4,7,4,7);nav.setSpacing(5)
        self.nav_buttons={}
        for key,label,icon in (('media','Mídia','▧'),('markers','Marcadores','⚑')):
            button=QToolButton();button.setObjectName('libraryNavButton')
            button.setText(f'{icon}\n{label}');button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setCheckable(True);button.setFixedHeight(54)
            button.clicked.connect(lambda checked=False,value=key:self.show_page(value))
            nav.addWidget(button);self.nav_buttons[key]=button
        nav.addStretch(1);root.addWidget(rail)

        self.stack=QStackedWidget();self.stack.setObjectName('libraryStack')
        root.addWidget(self.stack,1)
        self.media_page=QWidget();media=QVBoxLayout(self.media_page)
        media.setContentsMargins(9,8,9,8);media.setSpacing(6)
        self.heading=QLabel('BIBLIOTECA DE MÍDIA');self.heading.setObjectName('libraryHeading')
        self.heading.setToolTip('Biblioteca de mídia')
        media.addWidget(self.heading)
        help_text=QLabel('Arraste para uma faixa ou dê dois cliques para inserir.')
        help_text.setObjectName('libraryHint');help_text.setWordWrap(True);media.addWidget(help_text)
        self.search=QLineEdit();self.search.setPlaceholderText('⌕  Buscar mídia…')
        self.search.setClearButtonEnabled(True);self.search.textChanged.connect(self.apply_filters)
        media.addWidget(self.search)
        self.type_filter=QComboBox()
        for label,key in (('Todos os tipos','all'),('Vídeo','video'),('Áudio','audio'),('Imagem','image')):
            self.type_filter.addItem(label,key)
        self.type_filter.currentIndexChanged.connect(self.apply_filters)
        media.addWidget(self.type_filter)
        self.media_list=MediaList();self.media_list.setWordWrap(True)
        self.media_list.setDragEnabled(True)
        self.media_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.media_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        media.addWidget(self.media_list,1)
        self.count_label=QLabel('0 mídias');self.count_label.setObjectName('libraryCount')
        media.addWidget(self.count_label)
        self.import_button=QPushButton('+ Importar arquivos');self.import_button.setObjectName('libraryPrimary')
        self.import_button.setToolTip('Importar arquivos de mídia')
        self.import_button.clicked.connect(self.import_requested)
        media.addWidget(self.import_button)
        self.relink_button=QPushButton('↪ Relink mídia selecionada')
        self.relink_button.setToolTip('Associe a referência ausente a um arquivo localizado manualmente.')
        self.relink_button.clicked.connect(self.relink_requested)
        media.addWidget(self.relink_button)
        self.media_scroll=QScrollArea()
        self.media_scroll.setObjectName('libraryMediaScroll')
        self.media_scroll.setWidgetResizable(True)
        self.media_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.media_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.media_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.media_scroll.setWidget(self.media_page)
        self.stack.addWidget(self.media_scroll)

        self.marker_page=QWidget();markers=QVBoxLayout(self.marker_page)
        markers.setContentsMargins(9,8,9,8);markers.setSpacing(6)
        self.marker_heading=QLabel('MARCADORES DA TIMELINE')
        self.marker_heading.setObjectName('libraryHeading')
        self.marker_heading.setToolTip('Marcadores da timeline')
        markers.addWidget(self.marker_heading)
        marker_hint=QLabel('Dê dois cliques para navegar até um marcador.')
        marker_hint.setObjectName('libraryHint');marker_hint.setWordWrap(True);markers.addWidget(marker_hint)
        self.marker_list=QListWidget();self.marker_list.setObjectName('markerList')
        self.marker_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.marker_list.itemDoubleClicked.connect(self._activate_marker)
        markers.addWidget(self.marker_list,1)
        self.marker_count=QLabel('0 marcadores');self.marker_count.setObjectName('libraryCount')
        markers.addWidget(self.marker_count)
        self.marker_scroll=QScrollArea()
        self.marker_scroll.setObjectName('libraryMarkerScroll')
        self.marker_scroll.setWidgetResizable(True)
        self.marker_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.marker_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.marker_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.marker_scroll.setWidget(self.marker_page)
        self.stack.addWidget(self.marker_scroll)
        self.show_page('media')
        self._set_compact_labels(self.width()<245)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self._set_compact_labels(event.size().width()<245)

    def _set_compact_labels(self,compact):
        compact=bool(compact)
        if compact==self._compact_labels or not hasattr(self,'heading'):
            return
        self._compact_labels=compact
        self.heading.setText('BIBLIOTECA' if compact else 'BIBLIOTECA DE MÍDIA')
        self.import_button.setText('+ Importar' if compact else '+ Importar arquivos')
        self.relink_button.setText('↪ Relink mídia' if compact else '↪ Relink mídia selecionada')
        self.marker_heading.setText('MARCADORES' if compact else 'MARCADORES DA TIMELINE')

    def show_page(self,key):
        index={'media':0,'markers':1}.get(key)
        if index is None:return
        self.stack.setCurrentIndex(index)
        for name,button in self.nav_buttons.items():button.setChecked(name==key)

    def add_nav_button(self,key,label,icon,callback):
        """Acrescenta um acesso de ferramenta à rail lateral da biblioteca."""
        if key in self.nav_buttons:return self.nav_buttons[key]
        rail=self.findChild(QFrame,'libraryRail')
        if rail is None:return None
        nav=rail.layout()
        button=QToolButton();button.setObjectName('libraryNavButton')
        button.setText(f'{icon}\n{label}')
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        button.setCheckable(True);button.setFixedHeight(54)
        button.clicked.connect(callback)
        nav.insertWidget(max(0,nav.count()-1),button)
        self.nav_buttons[key]=button
        return button

    def set_media(self,paths):
        self.media_list.clear()
        for source in paths:
            path=Path(source);missing=not path.is_file()
            item=QListWidgetItem(('⚠ ' if missing else '')+path.name+(' · ausente' if missing else ''))
            item.setData(Qt.ItemDataRole.UserRole,str(source));item.setToolTip(str(source))
            suffix=path.suffix.casefold()
            kind=('video' if suffix in self.VIDEO else 'audio' if suffix in self.AUDIO else
                  'image' if suffix in self.IMAGE else 'other')
            item.setData(Qt.ItemDataRole.UserRole+1,kind)
            if missing:item.setForeground(QColor('#ff9a83'))
            self.media_list.addItem(item)
        self.count_label.setText(f'{len(paths)} mídia(s)')
        self.apply_filters()

    def set_markers(self,markers):
        self.marker_list.clear()
        for marker in markers:
            at=max(0.,float(marker.get('time',0.)))
            label=str(marker.get('label','Marcador'))
            item=QListWidgetItem(f'⚑  {int(at//60):02d}:{at%60:05.2f}  ·  {label}')
            item.setData(Qt.ItemDataRole.UserRole,at);item.setToolTip(f'{at:.3f} s · {label}')
            self.marker_list.addItem(item)
        count=len(markers);self.marker_count.setText(f'{count} marcador(es)')

    def apply_filters(self,*_):
        query=self.search.text().strip().casefold()
        kind=self.type_filter.currentData()
        visible=0
        for index in range(self.media_list.count()):
            item=self.media_list.item(index)
            matches_text=(not query or query in item.text().casefold() or
                          query in str(item.data(Qt.ItemDataRole.UserRole)).casefold())
            matches_type=(kind=='all' or item.data(Qt.ItemDataRole.UserRole+1)==kind)
            show=matches_text and matches_type
            item.setHidden(not show);visible+=int(show)
        total=self.media_list.count()
        self.count_label.setText(f'{visible} de {total} mídia(s)' if query or kind!='all'
                                 else f'{total} mídia(s)')

    def _activate_marker(self,item):
        self.marker_activated.emit(float(item.data(Qt.ItemDataRole.UserRole)))

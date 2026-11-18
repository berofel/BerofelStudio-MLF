"""Painel único e permanente de tarefas; ocupa espaço próprio no layout Qt."""
from __future__ import annotations

from datetime import datetime
import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (QFrame, QLabel, QPushButton, QProgressBar,
                               QVBoxLayout, QHBoxLayout, QPlainTextEdit,
                               QApplication, QMessageBox, QSizePolicy)


def explain_processing_error(message: str) -> tuple[str, str, str]:
    """Traduz erros comuns para uma ação clara, preservando o detalhe original."""
    detail = str(message)
    normalized = detail.casefold()
    if ('voice cloning is disabled' in normalized or
            'clonagem de áudio está desativada' in normalized or
            'somente de catálogo' in normalized):
        return (
            'Clonagem de voz ainda não ativada',
            'O Pocket TTS está usando pesos que permitem apenas as vozes do catálogo. '
            'Sua amostra não foi processada.',
            'Aceite os termos em https://huggingface.co/kyutai/pocket-tts, execute '
            'AUTORIZAR_POCKET_TTS.bat na pasta do editor e tente novamente. '
            'O arquivo original da amostra permanece intacto.',
        )
    if 'winerror 206' in normalized and 'qwen' in normalized:
        return (
            'Não foi possível iniciar o Qwen',
            'O Windows recusou iniciar o llama-cli por causa do tamanho de um caminho ou comando (WinError 206).',
            'Reabra pelo ABRIR_BEROFELSTUDIO.bat da raiz para garantir a versão atual. '
            'Ela envia os prompts em lotes por arquivos curtos em %LOCALAPPDATA%\\BFS\\tmp. '
            'Se o erro persistir, copie o relatório da Batata Quente e confira se o llama-cli e o modelo GGUF '
            'estão instalados em caminhos curtos. O detalhe técnico completo está abaixo.',
        )
    if 'qwen' in normalized and ('timed out' in normalized or 'timeoutexpired' in normalized):
        return (
            'O Qwen demorou mais que o limite do lote',
            'A análise local foi interrompida neste trecho. Transcrições e resultados já salvos no cache foram preservados.',
            'Tente novamente: os trechos concluídos serão reutilizados. Para avançar mais rápido, selecione um intervalo menor; '
            'a fila continua com legendas e outras etapas mesmo se o Qwen falhar. O erro técnico completo está abaixo.',
        )
    return ('Falha no processamento', detail, '')


def make_processing_error_dialog(parent, message: str) -> QMessageBox:
    title, body, help_text = explain_processing_error(message)
    dialog = QMessageBox(QMessageBox.Icon.Warning, title, body,
                        QMessageBox.StandardButton.Ok, parent)
    dialog.setWindowModality(Qt.WindowModality.NonModal)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    ok_button = dialog.button(QMessageBox.StandardButton.Ok)
    if ok_button:
        ok_button.setText('Entendi')
    if help_text:
        dialog.setInformativeText(help_text)
        dialog.setDetailedText(str(message))
        details_button = next((button for button in dialog.findChildren(QPushButton)
                               if button is not ok_button), None)
        if details_button:
            details_button.setText('Mostrar detalhes')
            details_button.setMinimumWidth(max(150, details_button.sizeHint().width() + 16))
    return dialog


def _clock(seconds):
    seconds = max(0, round(seconds))
    if seconds >= 3600:
        return f'{seconds // 3600:02d}:{(seconds // 60) % 60:02d}:{seconds % 60:02d}'
    return f'{seconds // 60:02d}:{seconds % 60:02d}'


class ProcessPanel(QFrame):
    """Mostra uma única tarefa por vez; não usa popup nem sobreposição."""
    def __init__(self, parent=None, compact=False):
        super().__init__(parent)
        self.compact=bool(compact)
        self.setObjectName('compactProcessDock' if self.compact else 'processDock')
        self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Maximum)
        self._control = None
        self._name = ''
        self._done = 0
        self._total = 0
        self._stage_start = 0.
        self._stage = ''
        self._log = []
        self._active = False
        self._resource_tick = 0
        self._compact_idle = True
        root = QVBoxLayout(self)
        if self.compact:
            root.setContentsMargins(0, 0, 0, 0)
        else:
            root.setContentsMargins(10, 7, 10, 7)
        root.setSpacing(1 if self.compact else 4)
        top = QHBoxLayout()
        top.setSpacing(3 if self.compact else 7)
        self.title = QLabel('BATATA QUENTE  ·  Aguardando tarefa')
        self.title.setStyleSheet('font-weight:800;color:#ffad70;')
        self.title.setWordWrap(not self.compact)
        top.addWidget(self.title, 1)
        self.pause_btn = QPushButton('Ⅱ Pausar')
        self.pause_btn.setToolTip('Suspende o processo e seus subprocessos. Continue de onde parou.')
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.pause_btn.setEnabled(False)
        top.addWidget(self.pause_btn)
        self.cancel_btn = QPushButton('■ Cancelar')
        self.cancel_btn.setToolTip('Encerra a tarefa e todos os subprocessos ativos. Preserva cache concluído.')
        self.cancel_btn.clicked.connect(self.cancel)
        self.cancel_btn.setEnabled(False)
        top.addWidget(self.cancel_btn)
        self.top_layout=top
        root.addLayout(top)

        middle = QHBoxLayout()
        middle.setSpacing(2 if self.compact else 8)
        self.bar = QProgressBar()
        self.bar.setMinimum(0)
        self.bar.setMaximum(100)
        self.bar.setValue(0)
        self.bar.setFormat('%p%')
        self.bar.setMinimumHeight(14 if self.compact else 21)
        if self.compact:self.bar.setMaximumHeight(15)
        middle.addWidget(self.bar, 1)
        self.percent = QLabel('0%')
        self.percent.setMinimumWidth(0 if self.compact else 42)
        self.percent.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        middle.addWidget(self.percent)
        if self.compact:self.percent.hide()  # a porcentagem já está centrada na barra
        root.addLayout(middle)

        stats = QHBoxLayout()
        stats.setSpacing(6)
        self.step_label = QLabel('Pronto para transcrever, narrar, analisar ou exportar.')
        self.step_label.setToolTip('A porcentagem acompanha etapas, trechos e lotes de inferência; não é uma previsão de tempo.')
        self.step_label.setWordWrap(not self.compact)
        if self.compact:self.step_label.setStyleSheet('font-size:9px;color:#aab2bd;')
        stats.addWidget(self.step_label, 2)
        self.time_label = QLabel('Decorrido 00:00  ·  Restante —')
        stats.addWidget(self.time_label, 1)
        self.stats_layout=stats
        root.addLayout(stats)
        bottom = QHBoxLayout()
        self.resource_label = QLabel('CPU / RAM: sem tarefa ativa')
        self.resource_label.setObjectName('hint')
        self.resource_label.setWordWrap(True)
        bottom.addWidget(self.resource_label, 1)
        self.detail_btn = QPushButton('Detalhes ▾')
        self.detail_btn.clicked.connect(self.toggle_details)
        bottom.addWidget(self.detail_btn)
        self.copy_btn = QPushButton('Copiar relatório')
        self.copy_btn.setToolTip('Copia etapas e tempos para enviar feedback de desempenho.')
        self.copy_btn.clicked.connect(self.copy_report)
        bottom.addWidget(self.copy_btn)
        root.addLayout(bottom)
        self.bottom_layout=bottom
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(92)
        self.details.setPlaceholderText('As etapas executadas aparecerão aqui.')
        self.details.setVisible(False)
        root.addWidget(self.details)
        self._timer = QTimer(self)
        self._timer.setInterval(750)
        self._timer.timeout.connect(self.refresh_metrics)
        self._hide_timer=QTimer(self);self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_after_finish)
        self._set_compact_idle(True)
        if self.compact:
            self.title.setMaximumWidth(185)
            self.title.setStyleSheet('font-size:9px;font-weight:750;color:#ffad70;')
            self.pause_btn.setText('Ⅱ');self.pause_btn.setFixedSize(23,19)
            self.pause_btn.setToolTip('Pausar ou continuar o processo')
            self.cancel_btn.setText('×');self.cancel_btn.setFixedSize(22,19)
            self.cancel_btn.setToolTip('Cancelar o processo')
            self.bottom_layout.removeWidget(self.detail_btn)
            self.top_layout.addWidget(self.detail_btn)
            self.detail_btn.setText('⋯');self.detail_btn.setFixedSize(22,19)
            self.detail_btn.setToolTip('Mostrar etapas e detalhes do processo')
            self.setMaximumHeight(53)

    def _set_compact_idle(self, compact):
        """Libera altura para preview/timeline quando ainda não há job ativo."""
        self._compact_idle=bool(compact)
        visible=not self._compact_idle
        self._hide_timer.stop()
        if self.compact:
            self.setVisible(visible)
            for widget in (self.title,self.pause_btn,self.cancel_btn,self.bar,
                           self.step_label,self.detail_btn):
                widget.setVisible(visible)
            for widget in (self.percent,self.time_label,self.resource_label,self.copy_btn):
                widget.hide()
            self.details.setVisible(False)
            return
        for widget in (self.pause_btn,self.cancel_btn,self.bar,self.percent,
                       self.step_label,self.time_label,self.resource_label,
                       self.detail_btn,self.copy_btn):
            widget.setVisible(visible)
        self.layout().setSpacing(0 if self._compact_idle else 4)

    def _entry(self, message):
        stamp = datetime.now().strftime('%H:%M:%S')
        self._log.append(f'[{stamp}] {message}')
        self.details.setPlainText('\n'.join(self._log[-100:]))
        scroll = self.details.verticalScrollBar()
        scroll.setValue(scroll.maximum())

    def begin(self, name, control):
        self._set_compact_idle(False)
        self.show()
        self._control = control
        self._active = True
        self._name = name
        self._done = 0
        self._total = 0
        self._stage = ''
        self._stage_start = 0.
        self._resource_tick = 0
        self._log = []
        self.title.setText(('● ' if self.compact else 'BATATA QUENTE  ·  ')+name)
        self.title.setToolTip(name)
        self.step_label.setText('Iniciando tarefa...')
        self.time_label.setText('Decorrido 00:00  ·  Restante —')
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.percent.setText('0%')
        self.pause_btn.setText('Ⅱ' if self.compact else 'Ⅱ Pausar')
        self.pause_btn.setEnabled(True)
        self.cancel_btn.setText('×' if self.compact else '■ Cancelar')
        self.cancel_btn.setEnabled(True)
        self._entry(f'INÍCIO: {name}')
        self._timer.start()
        self.refresh_metrics()

    def set_stage(self, name):
        if not self._active:
            return
        if self._stage and self._stage != name:
            self._entry(f'Etapa concluída: {self._stage} ({_clock(self._control.elapsed() - self._stage_start)})')
        if self._stage != name:
            self._stage = name
            self._stage_start = self._control.elapsed()
            self._entry('ETAPA: ' + name)
        self.step_label.setText(name)

    def set_progress(self, done, total):
        if not self._active:
            return
        self._done, self._total = max(0., float(done)), max(0, int(total))
        percent = min(100, int(self._done * 100 / self._total)) if self._total else 0
        self.bar.setRange(0, 100)
        self.bar.setValue(percent)
        self.percent.setText(f'{percent}%')
        self.refresh_metrics()

    def toggle_pause(self):
        if not self._active or self._control is None:
            return
        try:
            if self._control.paused:
                self._control.resume()
                self.pause_btn.setText('Ⅱ Pausar')
                self._entry('RETOMADA: a tarefa continua sem refazer etapas anteriores')
            else:
                self._control.pause()
                self.pause_btn.setText('▶ Continuar')
                self._entry('PAUSA: subprocessos suspensos; cache preservado')
            self.refresh_metrics()
        except RuntimeError as exc:
            QMessageBox.warning(self, 'Controle de processos', str(exc))

    def cancel(self):
        if self._active and self._control is not None:
            self._control.cancel()
            self.cancel_btn.setEnabled(False)
            self.pause_btn.setEnabled(False)
            self.step_label.setText('Cancelando processo e subprocessos...')
            self._entry('CANCELAMENTO SOLICITADO')

    def finish(self, status, details=''):
        if not self._active:
            return
        self._timer.stop()
        self._active = False
        self.pause_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        elapsed = self._control.elapsed() if self._control else 0.
        if status == 'concluido':
            self.bar.setRange(0, 100)
            self.bar.setValue(100)
            self.percent.setText('100%')
            self.title.setText(('✓ ' if self.compact else 'BATATA QUENTE  ·  Concluído: ')+self._name)
            self.step_label.setText('Tarefa finalizada com sucesso.')
        elif status == 'cancelado':
            self.title.setText(('■ ' if self.compact else 'BATATA QUENTE  ·  Cancelado: ')+self._name)
            self.step_label.setText('Interrompido. Etapas concluídas continuam no cache.')
        else:
            self.title.setText(('! ' if self.compact else 'BATATA QUENTE  ·  Erro: ')+self._name)
            self.step_label.setText('Falha na tarefa. Abra Detalhes para conferir.')
        self.time_label.setText('Duração: ' + _clock(elapsed))
        self._entry(f'FIM: {status.upper()} · {_clock(elapsed)}' + (' · ' + details[:500] if details else ''))
        self.refresh_metrics()
        self._control = None
        if self.compact:
            self._hide_timer.start(8000)

    def _hide_after_finish(self):
        if self.compact and not self._active and not self.details.isVisible():
            self._set_compact_idle(True)

    def refresh_metrics(self):
        if not self._control:
            return
        elapsed = self._control.elapsed()
        if self._active:
            if self._control.paused:
                eta = 'pausado'
            elif self._total > 0 and 0 < self._done < self._total and elapsed >= 3:
                remaining = elapsed * (self._total - self._done) / self._done
                eta = '~' + _clock(remaining)
            elif self._total > 0 and self._done >= self._total:
                eta = '00:00'
            else:
                eta = 'calculando'
            self.time_label.setText(f'Decorrido {_clock(elapsed)}  ·  Restante {eta}')
        self._resource_tick += 1
        if self._resource_tick % 2 == 1 or not self._active:
            stats = self._control.resources()
            if stats:
                self.resource_label.setText(
                    f"Editor + filhos: {stats['memory_mb']:.0f} MB RAM · "
                    f"CPU {stats['cpu_percent']:.0f}% · "
                    f"{stats['process_count']} processo(s) · "
                    f"RAM livre {stats['system_available_mb']:.0f} MB")
            else:
                self.resource_label.setText('Métricas de CPU/RAM indisponíveis (instale psutil).')

    def toggle_details(self):
        visible = not self.details.isVisible()
        if self.compact and visible:
            self.show()
        self.details.setVisible(visible)
        self.detail_btn.setText('Detalhes ▴' if visible else 'Detalhes ▾')

    def copy_report(self):
        report = (f'BerofelStudio · Processo: {self._name or "nenhum"}\n'
                  f'Progresso: {self._done}/{self._total}\n'
                  f'{self.time_label.text()}\n'
                  f'{self.resource_label.text()}\n\n' + '\n'.join(self._log))
        QApplication.clipboard().setText(report)

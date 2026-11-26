"""Cache leve de thumbnails sob demanda e ondas por arquivo, fora da thread Qt.

Nao roda IA e nunca altera os originais. Apenas uma tarefa de thumbnail ou
waveform e executada por vez; pode pausar novos jobs durante o Batata Quente.
"""
from __future__ import annotations

from array import array
import hashlib
import json
import os
from collections import OrderedDict
from pathlib import Path
import queue
import re
import subprocess
import threading

from berofel.services.ffmpeg import ffmpeg_path

MAX_MEMORY_WAVE_TILES=96
MAX_CACHE_MEGABYTES=256
PRUNE_EVERY_COMPLETED_JOBS=24


def default_cache_dir():
    local=os.getenv('LOCALAPPDATA')
    return Path(local,'BFS','timeline') if local else Path.home()/'.cache'/'berofelstudio'/'timeline'


class TimelineVisualCache:
    def __init__(self, folder=None, start_worker=True):
        self.folder=Path(folder or default_cache_dir())
        self.folder.mkdir(parents=True,exist_ok=True)
        self.queue=queue.PriorityQueue(maxsize=36)
        self.pending=set()
        self.updates=0
        self.paused=False
        self.stopping=False
        self.proc=None
        self.memory=OrderedDict()
        self._memory_lock=threading.RLock()
        self._completed_since_prune=0
        self.thread=None
        if start_worker:
            self.thread=threading.Thread(target=self._run,name='BFS Timeline Cache',daemon=True)
            self.thread.start()

    def _hash(self,source):
        p=Path(source)
        try:
            stat=p.stat();signature=(str(p.resolve()),stat.st_size,stat.st_mtime_ns)
        except OSError:signature=(source,)
        return hashlib.sha1(repr(signature).encode()).hexdigest()[:20]

    def thumbnail_path(self,source,at):
        return self.folder/f'{self._hash(source)}_{max(0,int(at))}s.jpg'

    @staticmethod
    def wave_tile(at):
        return max(0,int(float(at)//60)*60)

    def waveform_path(self,source,at=0):
        return self.folder/f'{self._hash(source)}_wave_{self.wave_tile(at)}s.json' 

    def get_thumb(self,source,at,request=True):
        key=self.thumbnail_path(source,at)
        if key.is_file():return str(key)
        if request and Path(source).is_file():self._enqueue(0,'thumb',source,max(0,int(at)),key)
        return ''

    def get_wave(self,source,at=0,request=True):
        at=self.wave_tile(at)
        key=self.waveform_path(source,at)
        name=str(key)
        with self._memory_lock:
            if name in self.memory:
                self.memory.move_to_end(name)
                return self.memory[name]
            if key.is_file():
                try:
                    data=json.loads(key.read_text(encoding='utf-8'))
                    self._remember_wave(name,data)
                    return data
                except (ValueError,OSError):pass
        if request and Path(source).is_file():self._enqueue(10,'wave',source,at,key)
        return None

    def _remember_wave(self,name,data):
        with self._memory_lock:
            self.memory[name]=data
            self.memory.move_to_end(name)
            while len(self.memory)>MAX_MEMORY_WAVE_TILES:
                self.memory.popitem(last=False)

    def _enqueue(self,priority,kind,source,at,key):
        name=str(key)
        if name in self.pending:return
        try:
            self.queue.put_nowait((priority,kind,source,at,name))
            self.pending.add(name)
        except queue.Full:pass

    def _run(self):
        while not self.stopping:
            if self.paused:
                threading.Event().wait(.15)
                continue
            try:
                priority,kind,source,at,name=self.queue.get(timeout=.2)
            except queue.Empty:continue
            try:
                if kind=='thumb':self._thumbnail(source,at,Path(name))
                else:self._waveform(source,at,Path(name))
                self.updates+=1
                self._completed_since_prune+=1
                if self._completed_since_prune>=PRUNE_EVERY_COMPLETED_JOBS:
                    self.prune(MAX_CACHE_MEGABYTES)
                    self._completed_since_prune=0
            except (OSError,subprocess.SubprocessError,ValueError):
                pass
            finally:
                self.pending.discard(name)
                self.queue.task_done()

    def _thumbnail(self,source,at,dest):
        if dest.is_file():return
        partial=dest.with_suffix('.tmp.jpg')
        cmd=[ffmpeg_path(),'-hide_banner','-loglevel','error','-nostdin','-y',
             '-threads','1','-ss',str(at),'-i',source,'-frames:v','1',
             '-vf','scale=140:80:force_original_aspect_ratio=decrease',
             '-q:v','6','-update','1',str(partial)]
        proc=subprocess.Popen(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.proc=proc
        if self.stopping and proc.poll() is None:
            proc.kill()
        try:
            if proc.wait(timeout=12)==0 and partial.is_file() and partial.stat().st_size>50:
                os.replace(partial,dest)
        except subprocess.TimeoutExpired:
            proc.kill();proc.wait()
        finally:
            self.proc=None
            partial.unlink(missing_ok=True)

    def _waveform(self,source,at,dest):
        if dest.is_file():return
        cmd=[ffmpeg_path(),'-hide_banner','-loglevel','error','-nostdin',
             '-threads','1','-ss',str(at),'-t','60','-i',source,'-vn','-ac','1','-ar','4000',
             '-f','s16le','-acodec','pcm_s16le','pipe:1']
        proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.proc=proc
        if self.stopping and proc.poll() is None:
            proc.kill()
        peaks=[]
        try:
            # O tile tem no máximo 60 s a 4 kHz mono (480 KB PCM). communicate
            # aplica timeout também enquanto o pipe está aberto, ao contrário
            # de read(), que podia deixar a thread do cache bloqueada para sempre.
            pcm,_=proc.communicate(timeout=45)
            samples=array('h')
            samples.frombytes(pcm[:len(pcm)//2*2])
            for offset in range(0,len(samples),400):
                peak=max((abs(value) for value in samples[offset:offset+400]),default=0)
                peaks.append(round(min(1,peak/32768),3))
            if not self.stopping:
                temp=dest.with_suffix('.tmp')
                temp.write_text(json.dumps({'step':.1,'offset':at,'peaks':peaks}),encoding='utf-8')
                os.replace(temp,dest)
        finally:
            if proc.poll() is None:proc.kill();proc.wait()
            if proc.stdout:proc.stdout.close()
            self.proc=None

    def prune(self,max_megabytes=MAX_CACHE_MEGABYTES):
        # Somente artefatos finais criados pela timeline entram no orçamento;
        # arquivos temporários ou desconhecidos nunca são removidos por engano.
        generated=re.compile(r'^[0-9a-f]{20}_(?:\d+s\.jpg|wave_\d+s\.json)$')
        paths=[path for path in self.folder.iterdir()
               if path.is_file() and generated.fullmatch(path.name)]
        existing=[];size=0
        for path in paths:
            try:
                stat=path.stat()
                if path.is_file():
                    existing.append((path,stat.st_size,stat.st_mtime_ns))
                    size+=stat.st_size
            except OSError:
                continue
        limit=max_megabytes*1024*1024
        if size<=limit:return
        for p,n,_modified in sorted(existing,key=lambda item:item[2]):
            if size<=limit:break
            try:p.unlink();size-=n
            except OSError:pass

    def close(self):
        self.stopping=True
        proc=self.proc
        if proc is not None and proc.poll() is None:
            try:proc.kill()
            except OSError:pass
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=2.)

"""Versioned user presets for non-destructive voice DSP settings."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import tempfile

from PySide6.QtCore import QSettings

from berofel.services.voice_dsp import VOICE_EQ_PRESETS

PRESET_SCHEMA_VERSION=1


class VoicePresetManager:
    """Store user-created EQ/pitch presets outside projects and source media."""
    def __init__(self,path=None):
        if path is None:
            settings=QSettings(QSettings.Format.IniFormat,QSettings.Scope.UserScope,
                               'Berofel','BerofelStudio')
            base=Path(settings.fileName()).parent
            path=base/'voice_presets.json'
        self.path=Path(path)

    @staticmethod
    def _validate(values):
        result={}
        for key,low,high in (('bass_db',-12.,12.),('mids_db',-12.,12.),
                             ('treble_db',-12.,12.),('pitch_semitones',-4.,4.)):
            value=float(values.get(key,0.))
            if not math.isfinite(value) or not low<=value<=high:
                raise ValueError(f'Valor inválido para {key}.')
            result[key]=round(value,2)
        return result

    def _read(self):
        if not self.path.exists():return {}
        try:
            data=json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError,json.JSONDecodeError) as exc:
            raise ValueError(f'Não foi possível ler os presets de voz: {exc}') from exc
        if not isinstance(data,dict) or data.get('schema_version')!=PRESET_SCHEMA_VERSION:
            raise ValueError('Versão do arquivo de presets não suportada.')
        presets=data.get('presets',{})
        if not isinstance(presets,dict):raise ValueError('Lista de presets inválida.')
        return {str(name):self._validate(values) for name,values in presets.items()}

    def names(self):
        return sorted(self._read(),key=str.casefold)

    def get(self,name):
        presets=self._read()
        if name not in presets:raise KeyError(name)
        return dict(presets[name])

    def save(self,name,values):
        name=' '.join(str(name).strip().split())
        if not name or len(name)>64:raise ValueError('O nome do preset deve ter de 1 a 64 caracteres.')
        if name.casefold() in {key.casefold() for key in VOICE_EQ_PRESETS} | {'personalizado'}:
            raise ValueError('Escolha um nome diferente dos presets padrão.')
        presets=self._read();presets[name]=self._validate(values);self._write(presets)
        return name

    def rename(self,old_name,new_name):
        presets=self._read()
        if old_name not in presets:raise KeyError(old_name)
        new_name=' '.join(str(new_name).strip().split())
        if not new_name or len(new_name)>64:raise ValueError('O nome do preset deve ter de 1 a 64 caracteres.')
        if new_name!=old_name and (any(key.casefold()==new_name.casefold() for key in presets) or new_name.casefold() in
                {key.casefold() for key in VOICE_EQ_PRESETS} | {'personalizado'}):
            raise ValueError('Esse nome de preset já está em uso.')
        presets[new_name]=presets.pop(old_name);self._write(presets)
        return new_name

    def delete(self,name):
        presets=self._read()
        if name not in presets:raise KeyError(name)
        del presets[name];self._write(presets)

    def _write(self,presets):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        payload={'schema_version':PRESET_SCHEMA_VERSION,'presets':presets}
        fd,temp_name=tempfile.mkstemp(prefix='.voice-presets-',suffix='.json',dir=self.path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as stream:
                json.dump(payload,stream,ensure_ascii=False,indent=2,sort_keys=True)
                stream.write('\n');stream.flush();os.fsync(stream.fileno())
            os.replace(temp_name,self.path)
        finally:
            try:os.unlink(temp_name)
            except FileNotFoundError:pass

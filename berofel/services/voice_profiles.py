"""Private, persistent local profiles for authorized Qwen3 voice references."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from datetime import datetime, timezone
from uuid import uuid4


PROFILE_SCHEMA_VERSION = 1
PROFILE_EXTENSIONS = {'.wav', '.mp3', '.flac', '.ogg', '.m4a'}
_PROFILE_ID = re.compile(r'^[0-9a-f]{32}$')


class VoiceProfileManager:
    """Keep named voice references outside projects and the Git checkout.

    Creating a profile makes a private copy of the selected audio. The user's
    source is never moved, rewritten, or deleted; profile deletion only removes
    the copy owned by this manager.
    """

    def __init__(self, directory: str | Path | None = None):
        if directory is None:
            override = os.environ.get('BEROFEL_VOICE_PROFILE_DIR')
            if override:
                directory = Path(override).expanduser()
            else:
                local = os.environ.get('LOCALAPPDATA')
                directory = (Path(local) / 'BFS' / 'voices' if local else
                             Path.home() / '.local' / 'share' / 'BerofelStudio' / 'voices')
        self.directory = Path(directory).expanduser().resolve()
        self.samples = self.directory / 'samples'
        self.manifest = self.directory / 'profiles.json'

    def _read(self) -> dict[str, dict]:
        if not self.manifest.exists():
            return {}
        try:
            data = json.loads(self.manifest.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f'Não foi possível ler os perfis de voz locais: {exc}') from exc
        if not isinstance(data, dict) or data.get('schema_version') != PROFILE_SCHEMA_VERSION:
            raise ValueError('Versão do arquivo de perfis de voz não suportada.')
        profiles = data.get('profiles')
        if not isinstance(profiles, dict):
            raise ValueError('Lista de perfis de voz inválida.')
        normalized = {}
        for profile_id, item in profiles.items():
            if not _PROFILE_ID.fullmatch(str(profile_id)) or not isinstance(item, dict):
                raise ValueError('Identificador inválido no arquivo de perfis de voz.')
            name = self._normalize_name(item.get('name'))
            filename = str(item.get('sample', ''))
            relative = Path(filename)
            if relative.is_absolute() or len(relative.parts) != 2 or relative.parts[0] != 'samples':
                raise ValueError(f'Caminho inseguro no perfil “{name}”.')
            sample = (self.directory / relative).resolve()
            try:
                sample.relative_to(self.samples.resolve())
            except ValueError as exc:
                raise ValueError(f'Caminho inseguro no perfil “{name}”.') from exc
            normalized[profile_id] = {
                'id': profile_id, 'name': name, 'sample': filename,
                'sample_sha256': str(item.get('sample_sha256', '')),
                'language': str(item.get('language', 'portuguese')),
                'reference_text': str(item.get('reference_text', ''))[:4000],
                'authorized': item.get('authorized') is True,
                'created_utc': str(item.get('created_utc', '')),
            }
        names = [item['name'].casefold() for item in normalized.values()]
        if len(names) != len(set(names)):
            raise ValueError('Há nomes duplicados no arquivo de perfis de voz.')
        return normalized

    @staticmethod
    def _normalize_name(value) -> str:
        name = ' '.join(str(value or '').strip().split())
        if not name or len(name) > 64:
            raise ValueError('O nome do perfil deve ter de 1 a 64 caracteres.')
        if any(ord(char) < 32 for char in name):
            raise ValueError('O nome do perfil contém caracteres inválidos.')
        return name

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        return digest.hexdigest()

    def list_profiles(self) -> list[dict]:
        profiles = self._read()
        return [self.get(profile_id) for profile_id in
                sorted(profiles, key=lambda key: profiles[key]['name'].casefold())]

    def get(self, profile_id: str) -> dict:
        profiles = self._read()
        item = profiles.get(str(profile_id))
        if item is None:
            raise KeyError(profile_id)
        sample = (self.directory / item['sample']).resolve()
        if not sample.is_file():
            raise FileNotFoundError(f'A cópia local do perfil “{item["name"]}” não foi encontrada: {sample}')
        if item['sample_sha256'] and self._hash_file(sample) != item['sample_sha256']:
            raise ValueError(f'A cópia local do perfil “{item["name"]}” foi alterada ou está corrompida.')
        return dict(item, sample_path=str(sample))

    def create(self, name: str, source: str | Path, language: str = 'portuguese',
               reference_text: str = '', *, authorized: bool = False) -> dict:
        name = self._normalize_name(name)
        source_path = Path(source).expanduser().resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f'A amostra da voz não existe: {source_path}')
        if source_path.suffix.lower() not in PROFILE_EXTENSIONS:
            raise ValueError('Use uma gravação de referência WAV, MP3, FLAC, OGG ou M4A.')
        if source_path.stat().st_size <= 44:
            raise ValueError('A amostra ou perfil de voz está vazio ou incompleto.')
        if not language or len(str(language)) > 32:
            raise ValueError('Idioma do perfil inválido.')
        reference_text=' '.join(str(reference_text or '').split())
        if len(reference_text)>4000:
            raise ValueError('A transcrição da referência deve ter no máximo 4000 caracteres.')
        profiles = self._read()
        if any(item['name'].casefold() == name.casefold() for item in profiles.values()):
            raise ValueError('Já existe um perfil com esse nome.')

        profile_id = uuid4().hex
        suffix = source_path.suffix.lower()
        filename = f'samples/{profile_id}{suffix}'
        target = self.directory / filename
        self.samples.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f'.{profile_id}-', suffix='.part', dir=self.samples)
        try:
            with os.fdopen(fd, 'wb') as output, source_path.open('rb') as source_stream:
                shutil.copyfileobj(source_stream, output, length=1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_name, target)
            item = {
                'id': profile_id, 'name': name, 'sample': filename,
                'sample_sha256': self._hash_file(target),
                'language': str(language),
                'reference_text': reference_text,
                'authorized': bool(authorized),
                'created_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            }
            profiles[profile_id] = item
            try:
                self._write(profiles)
            except Exception:
                target.unlink(missing_ok=True)
                raise
            return dict(item, sample_path=str(target.resolve()))
        finally:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass

    def authorize(self, profile_id: str) -> dict:
        """Persist the user's explicit authorization for local voice reuse."""
        profiles = self._read()
        if profile_id not in profiles:
            raise KeyError(profile_id)
        profiles[profile_id]['authorized'] = True
        self._write(profiles)
        return self.get(profile_id)

    def update_reference_text(self, profile_id: str, reference_text: str) -> dict:
        """Update only the transcript metadata of a saved voice profile."""
        profiles = self._read()
        item = profiles.get(str(profile_id))
        if item is None:
            raise KeyError(profile_id)
        normalized = ' '.join(str(reference_text or '').split())
        if len(normalized) > 4000:
            raise ValueError('A transcrição da referência deve ter no máximo 4000 caracteres.')
        item['reference_text'] = normalized
        self._write(profiles)
        return self.get(str(profile_id))

    def rename(self, profile_id: str, new_name: str) -> str:
        new_name = self._normalize_name(new_name)
        profiles = self._read()
        if profile_id not in profiles:
            raise KeyError(profile_id)
        if any(key != profile_id and item['name'].casefold() == new_name.casefold()
               for key, item in profiles.items()):
            raise ValueError('Já existe um perfil com esse nome.')
        profiles[profile_id]['name'] = new_name
        self._write(profiles)
        return new_name

    def delete(self, profile_id: str) -> None:
        profiles = self._read()
        item = profiles.pop(str(profile_id), None)
        if item is None:
            raise KeyError(profile_id)
        sample = (self.directory / item['sample']).resolve()
        try:
            sample.relative_to(self.samples.resolve())
        except ValueError as exc:
            raise ValueError('O perfil aponta para um arquivo fora da pasta privada.') from exc
        self._write(profiles)
        try:
            sample.unlink(missing_ok=True)
        except OSError:
            # Metadata deletion is committed; a leftover private copy is harmless
            # and can be reclaimed manually without touching the original source.
            pass

    def _write(self, profiles: dict[str, dict]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = {'schema_version': PROFILE_SCHEMA_VERSION, 'profiles': profiles}
        fd, temporary_name = tempfile.mkstemp(prefix='.voice-profiles-', suffix='.json',
                                              dir=self.directory)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, self.manifest)
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass

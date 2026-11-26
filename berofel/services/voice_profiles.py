"""Private, persistent local profiles for authorized Qwen3 voice references."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
from datetime import datetime, timezone
from uuid import uuid4


PROFILE_SCHEMA_VERSION = 1
PROFILE_INTELLIGENCE_SCHEMA_VERSION = 1
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
        self.intelligence = self.directory / 'intelligence'
        # Profile samples can be long recordings. Verify the full digest once
        # per stable file identity in this manager instead of rereading every
        # voice whenever the UI refreshes its profile list.
        self._verified_samples: dict[str, tuple[int, int, int, int, str]] = {}

    @staticmethod
    def _sample_identity(sample: Path) -> tuple[int, int, int, int]:
        stat = sample.stat()
        return (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns,
                getattr(stat, 'st_ino', 0))

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
                # Backward compatible: profiles saved before transcript review
                # tracking remain unconfirmed until the user reviews them.
                'reference_text_reviewed': item.get('reference_text_reviewed') is True,
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
        expected_hash = item['sample_sha256']
        if expected_hash:
            identity = self._sample_identity(sample)
            cache_key = str(sample)
            cached = self._verified_samples.get(cache_key)
            if (cached is None or cached[:4] != identity or
                    cached[4] != expected_hash):
                actual_hash = self._hash_file(sample)
                if actual_hash != expected_hash:
                    self._verified_samples.pop(cache_key, None)
                    raise ValueError(f'A cópia local do perfil “{item["name"]}” foi alterada ou está corrompida.')
                self._verified_samples[cache_key] = (*identity, actual_hash)
        return dict(item, sample_path=str(sample))

    def create(self, name: str, source: str | Path, language: str = 'portuguese',
               reference_text: str = '', *, authorized: bool = False,
               reference_text_reviewed: bool = False) -> dict:
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
                'reference_text_reviewed': bool(reference_text_reviewed),
                'authorized': bool(authorized),
                'created_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            }
            identity = self._sample_identity(target)
            profiles[profile_id] = item
            try:
                self._write(profiles)
            except Exception:
                target.unlink(missing_ok=True)
                raise
            self._verified_samples[str(target.resolve())] = (*identity,
                                                               item['sample_sha256'])
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

    def update_reference_text(self, profile_id: str, reference_text: str, *,
                              reviewed: bool = False) -> dict:
        """Update only the transcript metadata of a saved voice profile."""
        profiles = self._read()
        item = profiles.get(str(profile_id))
        if item is None:
            raise KeyError(profile_id)
        normalized = ' '.join(str(reference_text or '').split())
        if len(normalized) > 4000:
            raise ValueError('A transcrição da referência deve ter no máximo 4000 caracteres.')
        item['reference_text'] = normalized
        item['reference_text_reviewed'] = bool(reviewed)
        self._write(profiles)
        return self.get(str(profile_id))

    def save_acoustic_fingerprint(self, profile_id: str, report: dict) -> dict:
        """Persist a compact acoustic summary tied to the exact private sample.

        This stores measurements already produced by ``audio_reference``;
        it never starts an analysis, stores PCM/transcript/path, or treats
        acoustic traits as proof of speaker identity.
        """
        profile = self.get(str(profile_id))
        if not isinstance(report, dict):
            raise ValueError('Relatório acústico inválido.')
        def finite(value):
            if value is None or isinstance(value, (str, bool, int)):
                return value
            if isinstance(value, float):
                if not math.isfinite(value):
                    return None
                return value
            if isinstance(value, dict):
                return {str(key): finite(item) for key, item in list(value.items())[:64]
                        if isinstance(key, (str, int, float))}
            if isinstance(value, (list, tuple)):
                return [finite(item) for item in value[:32]]
            return None

        fields = ('duration', 'source_duration', 'selected_start', 'active_fraction',
                  'sample_rate', 'rms_dbfs', 'audible_signal_seconds', 'peak_dbfs',
                  'clipped_fraction', 'silence_fraction', 'reference_quality_score',
                  'reference_quality_confidence', 'reference_quality_components',
                  'acoustic_features', 'pitch_features', 'spectral_features')
        summary = {key: finite(report[key]) for key in fields if key in report}
        payload = {
            'schema_version': PROFILE_INTELLIGENCE_SCHEMA_VERSION,
            'profile_id': str(profile_id),
            'sample_sha256': profile['sample_sha256'],
            'measurements': summary,
            'interpretation': {
                'acoustic_traits_are_identity_proof': False,
                'snr_is_calibrated': False,
                'pitch_is_speaker_identity': False,
            },
        }
        self._write_intelligence(str(profile_id), payload)
        return payload

    def bind_purec_fingerprint(self, profile_id: str, vector_path: str | Path,
                               *, engine: str, source_sha256: str,
                               model_id: str = 'qwen3-tts-0.6b-base',
                               model_key: str = '') -> dict:
        """Bind metadata to the existing validated Pure C x-vector cache.

        The vector stays in its existing private cache and is not copied into
        the profile store. Only its digest, format, and dimensions are saved.
        """
        profile = self.get(str(profile_id))
        if not source_sha256 or source_sha256 != profile['sample_sha256']:
            raise ValueError('O x-vector não corresponde ao áudio deste perfil.')
        vector = Path(vector_path).expanduser().resolve()
        from .qwen3_purec_tts import _profile_cache_root
        try:
            vector.relative_to(_profile_cache_root().resolve())
        except ValueError as exc:
            raise ValueError('O x-vector precisa estar no cache privado Pure C.') from exc
        from .voice_intelligence.speaker_fingerprint import (
            VECTOR_DIMENSION, VECTOR_FORMAT, read_purec_xvector,
        )
        read_purec_xvector(vector)
        current = self.get_voice_intelligence(str(profile_id)) or {
            'schema_version': PROFILE_INTELLIGENCE_SCHEMA_VERSION,
            'profile_id': str(profile_id),
            'sample_sha256': profile['sample_sha256'],
            'measurements': {},
            'interpretation': {
                'acoustic_traits_are_identity_proof': False,
                'snr_is_calibrated': False,
                'pitch_is_speaker_identity': False,
            },
        }
        current['purec_identity_vector'] = {
            'format': VECTOR_FORMAT,
            'dimension': VECTOR_DIMENSION,
            'sha256': self._hash_file(vector),
            'cache_key': vector.stem,
            'model_id': str(model_id),
            'model_key': str(model_key),
            'engine': str(engine),
            'calibrated_similarity_threshold': None,
        }
        self._write_intelligence(str(profile_id), current)
        return current

    def get_voice_intelligence(self, profile_id: str) -> dict | None:
        """Read sidecar only when schema, ID, and sample hash still match."""
        profile = self.get(str(profile_id))
        path = self._intelligence_path(str(profile_id))
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            return None
        if (not isinstance(payload, dict) or
                payload.get('schema_version') != PROFILE_INTELLIGENCE_SCHEMA_VERSION or
                payload.get('profile_id') != str(profile_id) or
                payload.get('sample_sha256') != profile['sample_sha256']):
            return None
        vector_meta = payload.get('purec_identity_vector')
        if isinstance(vector_meta, dict):
            try:
                from .qwen3_purec_tts import _profile_cache_root
                vector_path = (_profile_cache_root() /
                               f"{vector_meta['cache_key']}.bin").resolve()
                vector_path.relative_to(_profile_cache_root().resolve())
                if (not vector_path.is_file() or
                        self._hash_file(vector_path) != vector_meta.get('sha256')):
                    payload.pop('purec_identity_vector', None)
            except (OSError, KeyError, ValueError):
                payload.pop('purec_identity_vector', None)
        return payload

    def _intelligence_path(self, profile_id: str) -> Path:
        if not _PROFILE_ID.fullmatch(profile_id):
            raise ValueError('Identificador inválido no perfil de voz.')
        return self.intelligence / f'{profile_id}.json'

    def _write_intelligence(self, profile_id: str, payload: dict) -> None:
        path = self._intelligence_path(profile_id)
        self.intelligence.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix='.voice-intelligence-', suffix='.json',
                                              dir=self.intelligence)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2,
                          sort_keys=True, allow_nan=False)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, path)
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass

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
        self._verified_samples.pop(str(sample), None)
        try:
            self._intelligence_path(str(profile_id)).unlink(missing_ok=True)
        except OSError:
            pass
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

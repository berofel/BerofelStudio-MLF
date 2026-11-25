"""Cache transacional em disco por fonte, trecho, etapa e configuração.

Nenhum peso de IA é guardado na memória do editor. Resultados são JSON versionados;
se a origem mudar (tamanho/mtime), o identificador do cache muda.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path

CACHE_SCHEMA = 3


def cache_root() -> Path:
    override = os.environ.get('BEROFEL_AI_CACHE')
    if override:
        return Path(override).expanduser().resolve()
    local = os.environ.get('LOCALAPPDATA')
    return (Path(local) / 'BFS' / 'cache' / 'ai') if local else (Path.home() / '.cache' / 'BerofelStudio' / 'ai')


def source_identity(source: str) -> dict:
    file = Path(source).resolve(strict=True)
    stat = file.stat()
    return {'path': str(file), 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}


def digest(obj: object) -> str:
    raw = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(',', ':'), default=str)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]


def file_sha256(path: str | Path, *, chunk_bytes: int = 1024 * 1024) -> str:
    """Hash a file incrementally so long references never become a RAM copy."""
    if chunk_bytes <= 0:
        raise ValueError('chunk_bytes precisa ser positivo.')
    value = hashlib.sha256()
    with Path(path).expanduser().open('rb') as source:
        for chunk in iter(lambda: source.read(chunk_bytes), b''):
            value.update(chunk)
    return value.hexdigest()


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) and data.get('schema') == CACHE_SCHEMA else None
    except (OSError, ValueError):
        return None


class CacheStore:
    def __init__(self, root: Path | None = None):
        self.root = root or cache_root()

    def directory(self, source: str, start: float, end: float, options: dict) -> Path:
        key = digest({'schema': CACHE_SCHEMA, 'source': source_identity(source),
                      'start': round(start, 4), 'end': round(end, 4), 'options': options})
        return self.root / key[:2] / key

    @staticmethod
    def load(directory: Path, stage: str) -> dict | None:
        return read_json(directory / (stage + '.json'))

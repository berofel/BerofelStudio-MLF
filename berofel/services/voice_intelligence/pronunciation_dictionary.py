"""Private, deterministic pronunciation overrides for local voice profiles."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Iterable, Mapping

PRONUNCIATION_SCHEMA_VERSION = 1
MAX_ENTRIES = 5000
MAX_TERM_LENGTH = 160


def _default_root() -> Path:
    override = os.environ.get("BEROFEL_PRONUNCIATION_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    local = os.environ.get("LOCALAPPDATA")
    root = Path(local) / "BFS" if local else Path.home() / ".local" / "share" / "BerofelStudio"
    return root / "voices" / "pronunciation"


def _voice_key(reference: str | Path) -> str:
    source = Path(reference).expanduser().resolve()
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _entry(value: Mapping) -> dict:
    original = " ".join(str(value.get("original", "")).split())
    spoken = " ".join(str(value.get("spoken_form", "")).split())
    if not original or not spoken or len(original) > MAX_TERM_LENGTH or len(spoken) > MAX_TERM_LENGTH:
        raise ValueError("Cada pronúncia precisa de termo e forma falada de até 160 caracteres.")
    language = str(value.get("language", "portuguese")).strip().casefold()
    if language not in {"portuguese", "pt-br"}:
        raise ValueError("O dicionário vocal aceita somente entradas PT-BR nesta versão.")
    context = " ".join(str(value.get("context", "")).split())
    phonetic = str(value.get("phonetic_form", "")).strip()
    if len(context) > 240 or len(phonetic) > MAX_TERM_LENGTH:
        raise ValueError("Contexto ou forma fonética excede o limite permitido.")
    return {
        "original": original,
        "spoken_form": spoken,
        "language": "portuguese",
        "phonetic_form": phonetic,
        "context": context,
        "case_sensitive": value.get("case_sensitive") is True,
        "enabled": value.get("enabled", True) is True,
    }


class PronunciationDictionary:
    """Atomic JSON storage keyed by reference audio content, not file name."""

    def __init__(self, reference: str | Path, directory: str | Path | None = None):
        self.key = _voice_key(reference)
        self.directory = Path(directory).expanduser().resolve() if directory else _default_root()
        self.path = self.directory / f"{self.key}.json"

    def load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Não foi possível ler o dicionário local de pronúncia.") from exc
        if not isinstance(data, dict) or data.get("schema_version") != PRONUNCIATION_SCHEMA_VERSION:
            raise ValueError("Versão do dicionário de pronúncia não suportada.")
        entries = data.get("entries")
        if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
            raise ValueError("Lista de pronúncias inválida ou grande demais.")
        return [_entry(item) for item in entries if isinstance(item, dict)]

    def save(self, entries: Iterable[Mapping]) -> None:
        normalized = [_entry(item) for item in entries]
        if len(normalized) > MAX_ENTRIES:
            raise ValueError(f"O dicionário aceita até {MAX_ENTRIES} entradas.")
        identities = [(item["original"].casefold(), item["context"].casefold())
                      for item in normalized]
        if len(identities) != len(set(identities)):
            raise ValueError("Há termos duplicados para o mesmo contexto.")
        self.directory.mkdir(parents=True, exist_ok=True)
        content = json.dumps({"schema_version": PRONUNCIATION_SCHEMA_VERSION,
                              "voice_sha256": self.key, "entries": normalized},
                             ensure_ascii=False, sort_keys=True, indent=2)
        fd, temporary = tempfile.mkstemp(prefix=".pronunciation-", suffix=".tmp",
                                          dir=str(self.directory))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass


def apply_pronunciations(text: str, entries: Iterable[Mapping], *,
                         language: str = "portuguese") -> tuple[str, tuple[str, ...]]:
    """Return a spoken-only string and applied source terms; never mutates source."""
    source = str(text or "")
    if language != "portuguese":
        return source, ()
    active = [_entry(item) for item in entries if isinstance(item, Mapping)
              and item.get("enabled", True) is True
              and str(item.get("language", "portuguese")).casefold() in {"portuguese", "pt-br"}]
    # Match only against the original source. Applying replacements successively
    # can cascade (A -> B -> C) or change offsets when two rules overlap.
    candidates: list[tuple[int, int, int, dict]] = []
    for order, item in enumerate(active):
        flags = 0 if item["case_sensitive"] else re.IGNORECASE
        pattern = re.compile(r"(?<!\w)" + re.escape(item["original"]) + r"(?!\w)", flags)
        for match in pattern.finditer(source):
            context = item["context"]
            if context:
                # Context is local to this occurrence; the same word elsewhere
                # in a long script must not activate the override globally.
                nearby = source[max(0, match.start() - 100):min(len(source), match.end() + 100)]
                if context.casefold() not in nearby.casefold():
                    continue
            candidates.append((match.start(), match.end(), order, item))
    # Earliest occurrence wins; for overlaps prefer the longest term and then
    # the saved dictionary order. No replacement is searched again.
    candidates.sort(key=lambda hit: (hit[0], -(hit[1] - hit[0]), hit[2]))
    chosen: list[tuple[int, int, dict]] = []
    cursor = -1
    for start, end, _order, item in candidates:
        if start < cursor:
            continue
        chosen.append((start, end, item))
        cursor = end
    if not chosen:
        return source, ()
    pieces: list[str] = []
    applied: list[str] = []
    cursor = 0
    for start, end, item in chosen:
        pieces.extend((source[cursor:start], item["spoken_form"]))
        cursor = end
        if item["original"] not in applied:
            applied.append(item["original"])
    pieces.append(source[cursor:])
    return "".join(pieces), tuple(applied)

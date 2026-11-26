"""Read installed Pure C capabilities without loading model weights.

Help text is evidence that a flag is compiled into the executable, not proof
that the HTTP adapter accepts that flag per request. The manifest therefore
keeps CLI and currently-used HTTP capabilities separate.
"""
from __future__ import annotations

from hashlib import sha256
from functools import lru_cache
import math
from pathlib import Path
import re
import struct
import subprocess
from typing import Callable


# This build's request-level seed was confirmed by three real local syntheses:
# same seed => byte-identical PCM; changed seed => different PCM. Other builds
# must be revalidated instead of inheriting this capability by assumption.
_HTTP_SEED_VALIDATED_SHA256 = frozenset({
    "3a5f89d923bfdbea29327bd4111ecd651afa3ef448b2643b6ea8ad63dd907d13",
})


def _hash_file(path: Path) -> str:
    value = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


@lru_cache(maxsize=8)
def _seed_capability_for_file(path_text: str, size: int, mtime_ns: int) -> bool:
    del size, mtime_ns  # part of the cache key: invalidate after runtime updates
    try:
        return _hash_file(Path(path_text)) in _HTTP_SEED_VALIDATED_SHA256
    except OSError:
        return False


def supports_request_seed(executable: str | Path) -> bool:
    """Return true only for a Pure C binary whose request seed was tested."""
    binary = Path(executable).expanduser().resolve()
    try:
        stat = binary.stat()
    except OSError:
        return False
    return _seed_capability_for_file(str(binary), stat.st_size, stat.st_mtime_ns)


def _valid_emotion_direction(path: Path) -> bool:
    """Validate the upstream 1024-float raw direction format without NumPy."""
    if path.stem.removeprefix("dir_").casefold() not in {
            "ang", "disgust", "fear", "joy", "sad", "surprise"}:
        return False
    try:
        if path.stat().st_size != 1024 * 4:
            return False
        values = struct.iter_unpack("<f", path.read_bytes())
        norm_squared = 0.0
        for (value,) in values:
            if not math.isfinite(value):
                return False
            norm_squared += value * value
        return norm_squared > 1e-12
    except (OSError, struct.error):
        return False


def inspect_purec_capabilities(executable: str | Path, *,
                               runner: Callable = subprocess.run,
                               emotion_asset_dir: str | Path | None = None,
                               timeout: float = 8.0) -> dict:
    """Inspect CLI help and CPU caps; does not start a server or load a model."""
    binary = Path(executable).expanduser().resolve()
    if not binary.is_file():
        raise FileNotFoundError("O executável local Pure C não foi encontrado.")
    binary_hash = _hash_file(binary)

    def invoke(argument: str) -> str:
        try:
            result = runner([str(binary), argument], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"inspection-error: {type(exc).__name__}"
        return "\n".join((result.stdout or "", result.stderr or "")).strip()

    help_text = invoke("--help")
    caps_text = invoke("--caps")
    if help_text.startswith("inspection-error:"):
        raise RuntimeError("Não foi possível consultar os recursos do Pure C sem iniciar síntese.")
    flags = set(re.findall(r"(?<![\w-])--[a-z][a-z0-9-]*", help_text.casefold()))
    emotion_lines = [line.casefold() for line in help_text.splitlines()
                     if re.match(r"^\s*--emotion\s", line, re.IGNORECASE)
                     and "--emotion-strength" not in line.casefold()]
    emo_ref_lines = [line.casefold() for line in help_text.splitlines()
                     if re.match(r"^\s*--emo-ref\s", line, re.IGNORECASE)]
    emo_ref_text_lines = [line.casefold() for line in help_text.splitlines()
                          if re.match(r"^\s*--emo-ref-text\s", line, re.IGNORECASE)]
    # The binary is launched with cwd=its own directory by the app. Upstream
    # resolves shared 0.6B directions relative to presets/emovoice there.
    asset_dir = (Path(emotion_asset_dir).expanduser() if emotion_asset_dir else
                 binary.parent / "presets" / "emovoice")
    candidates = sorted(asset_dir.glob("dir_*.bin")) if asset_dir.is_dir() else []
    emotion_assets = [item for item in candidates if _valid_emotion_direction(item)]
    invalid_emotion_assets = [item.name for item in candidates
                              if not _valid_emotion_direction(item)]
    build_match = re.search(r"^\s*build:\s*(.+)$", caps_text, re.MULTILINE | re.IGNORECASE)
    build_id = build_match.group(1).strip() if build_match else "unknown"
    model_hint = "0.6B" if "0.6b" in help_text.casefold() else "unspecified"

    return {
        "schema_version": 1,
        "binary_sha256": binary_hash,
        "binary_size_bytes": binary.stat().st_size,
        "build_id": build_id,
        "model_hint": model_hint,
        "cli": {
            "xvector_clone": "--xvector-only" in flags and "--load-voice" in flags,
            "icl_reference": "--icl-frames" in flags or "--icl-only" in flags,
            "qvoice_profiles": ".qvoice" in help_text,
            "emotion_flag_advertised": "--emotion" in flags,
            "emotion_flag_is_06b": any("0.6b" in line and "1.7b" not in line
                                        for line in emotion_lines),
            "emotion_strength_advertised": "--emotion-strength" in flags,
            "emotion_by_example_advertised": (
                "--emo-ref" in flags and "--emo-ref-text" in flags),
            "emotion_by_example_needs_transcript": any(
                "required" in line for line in emo_ref_text_lines),
            "emotion_by_example_wav_constraints": (
                "24khz mono" if any("24khz mono" in line for line in emo_ref_lines)
                else None),
            "paralinguistic_compose_advertised": "--compose" in flags,
            "paralinguistic_tags_advertised": "tags:" in help_text.casefold(),
            "mixed_cpu_precision": ("Talker INT8 + Code Predictor INT4"
                                    if "--quant-mixed-cpu" in flags else None),
            "int8_precision": ("Talker INT8 + Code Predictor INT8"
                               if "--int8" in flags else None),
            "emotion_direction_files": [item.name for item in emotion_assets],
            "emotion_direction_files_invalid": invalid_emotion_assets,
        },
        "http_adapter": {
            "profile_is_loaded_at_server_start": True,
            "dynamic_voice_per_request": False,
            "emotion_per_request_validated": False,
            "emotion_by_example_per_request_validated": False,
            "seed_per_request_validated": binary_hash in _HTTP_SEED_VALIDATED_SHA256,
            "emotion_vectors_available": bool(emotion_assets),
            "paralinguistic_markers_validated": False,
        },
        "cpu_caps": caps_text,
        "evidence": "executable --help and --caps; no model/server was started",
    }

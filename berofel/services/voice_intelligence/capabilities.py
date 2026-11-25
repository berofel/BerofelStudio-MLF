"""Read installed Pure C capabilities without loading model weights.

Help text is evidence that a flag is compiled into the executable, not proof
that the HTTP adapter accepts that flag per request. The manifest therefore
keeps CLI and currently-used HTTP capabilities separate.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re
import subprocess
from typing import Callable


def _hash_file(path: Path) -> str:
    value = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def inspect_purec_capabilities(executable: str | Path, *,
                               runner: Callable = subprocess.run,
                               emotion_asset_dir: str | Path | None = None,
                               timeout: float = 8.0) -> dict:
    """Inspect CLI help and CPU caps; does not start a server or load a model."""
    binary = Path(executable).expanduser().resolve()
    if not binary.is_file():
        raise FileNotFoundError("O executável local Pure C não foi encontrado.")

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
    asset_dir = Path(emotion_asset_dir).expanduser() if emotion_asset_dir else None
    emotion_assets = sorted(asset_dir.glob("dir_*.bin")) if asset_dir and asset_dir.is_dir() else []
    build_match = re.search(r"^\s*build:\s*(.+)$", caps_text, re.MULTILINE | re.IGNORECASE)
    build_id = build_match.group(1).strip() if build_match else "unknown"
    model_hint = "0.6B" if "0.6b" in help_text.casefold() else "unspecified"

    return {
        "schema_version": 1,
        "binary_sha256": _hash_file(binary),
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
            "paralinguistic_compose_advertised": "--compose" in flags,
            "paralinguistic_tags_advertised": "tags:" in help_text.casefold(),
            "mixed_cpu_precision": ("Talker INT8 + Code Predictor INT4"
                                    if "--quant-mixed-cpu" in flags else None),
            "int8_precision": ("Talker INT8 + Code Predictor INT8"
                               if "--int8" in flags else None),
            "emotion_direction_files": [item.name for item in emotion_assets],
        },
        "http_adapter": {
            "profile_is_loaded_at_server_start": True,
            "dynamic_voice_per_request": False,
            "emotion_per_request_validated": False,
            "emotion_vectors_available": bool(emotion_assets),
            "paralinguistic_markers_validated": False,
        },
        "cpu_caps": caps_text,
        "evidence": "executable --help and --caps; no model/server was started",
    }

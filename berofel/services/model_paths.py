"""Caminhos estaveis dos modelos locais usados pelo aplicativo."""
import os
from pathlib import Path


def parakeet_tdt_model_dir() -> Path:
    """Parakeet TDT v3 ONNX INT8 files, installed outside the project tree."""
    local = os.environ.get("LOCALAPPDATA")
    root = Path(local) if local else Path.home() / ".berofelstudio"
    return root / "BFS" / "models" / "parakeet-tdt-v3-int8"


def silero_vad_model_dir() -> Path:
    """Silero VAD ONNX files, installed locally for the ASR and editor VAD."""
    local = os.environ.get("LOCALAPPDATA")
    root = Path(local) if local else Path.home() / ".berofelstudio"
    return root / "BFS" / "models" / "silero-vad-onnx"

"""Caminhos estaveis dos modelos locais usados pelo aplicativo."""
import os
from pathlib import Path


def whisper_model_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "BerofelStudio" / "models" / "whisper-base"
    return Path.home() / ".berofelstudio" / "models" / "whisper-base"


def parakeet_model_path() -> Path:
    """Optional Parakeet Ultra Q8 model, installed outside the project tree."""
    local = os.environ.get("LOCALAPPDATA")
    root = Path(local) if local else Path.home() / ".berofelstudio"
    return root / "BFS" / "models" / "parakeet-ultra" / "parakeet-ultra-Q8_0.gguf"


def transcribe_runtime_dir() -> Path:
    """Directory containing the pinned transcribe.cpp DLL and backend DLLs."""
    local = os.environ.get("LOCALAPPDATA")
    root = Path(local) if local else Path.home() / ".berofelstudio"
    return root / "BFS" / "tools" / "transcribe.cpp" / "0.4.2" / "runtime"


def transcribe_binding_wheel() -> Path:
    """Pinned, pure-Python binding wheel installed beside the native runtime."""
    return transcribe_runtime_dir().parent / "transcribe_cpp-0.4.2-py3-none-any.whl"

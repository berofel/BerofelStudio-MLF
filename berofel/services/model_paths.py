"""Caminhos estaveis dos modelos locais usados pelo aplicativo."""
import os
from pathlib import Path


def whisper_model_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "BerofelStudio" / "models" / "whisper-base"
    return Path.home() / ".berofelstudio" / "models" / "whisper-base"

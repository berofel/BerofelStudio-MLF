"""Baixa o modelo usado de fato pela análise de falas repetidas da alpha."""
from pathlib import Path
import os


def model_path() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return Path.home() / ".berofelstudio" / "models" / "whisper-base"
    return Path(local) / "BerofelStudio" / "models" / "whisper-base"


def main():
    from faster_whisper.utils import download_model

    target = model_path()
    target.mkdir(parents=True, exist_ok=True)
    print("Modelo Faster-Whisper Base:", target, flush=True)
    download_model("base", output_dir=str(target))
    if not (target / "model.bin").is_file() or not (target / "config.json").is_file():
        raise RuntimeError("Download do modelo incompleto.")
    print("Modelo de transcricao pronto para uso offline.", flush=True)


if __name__ == "__main__":
    main()

"""Instala e valida uma vez o Parakeet TDT v3 INT8 e Silero VAD ONNX local."""
from __future__ import annotations

import gc
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    from berofel.services.model_paths import parakeet_tdt_model_dir, silero_vad_model_dir
    from berofel.services.parakeet_asr import MODEL_NAME, make_session_options
    import onnxruntime as ort
    import onnx_asr
    from huggingface_hub import snapshot_download

    model_dir = parakeet_tdt_model_dir()
    vad_dir = silero_vad_model_dir()
    model_dir.mkdir(parents=True, exist_ok=True)
    vad_dir.mkdir(parents=True, exist_ok=True)
    print(f"Python {sys.version.split()[0]} · onnx-asr {importlib.metadata.version('onnx-asr')} · ONNX Runtime {ort.__version__}", flush=True)
    print("[1/3] Baixando/carregando Parakeet TDT v3 ONNX quantizado INT8 (CPU).", flush=True)
    print(f"Destino: {model_dir}", flush=True)
    required_model_files = ("config.json", "encoder-model.int8.onnx",
                            "decoder_joint-model.int8.onnx", "vocab.txt")
    # Normal startup/install validation stays offline if the complete pinned
    # model is already present. Only an incomplete first installation contacts HF.
    if not all((model_dir / name).is_file() for name in required_model_files):
        snapshot_download(
            "istupakov/parakeet-tdt-0.6b-v3-onnx", revision="8f23f0c",
            local_dir=model_dir, allow_patterns=list(required_model_files),
        )
    model = onnx_asr.load_model(
        MODEL_NAME, model_dir, quantization="int8",
        sess_options=make_session_options(4), providers=["CPUExecutionProvider"],
        preprocessor_config={"max_concurrent_workers": 1,
                             "use_numpy_preprocessors": True},
    ).with_timestamps()
    print("Parakeet carregado e validado com CPUExecutionProvider.", flush=True)
    del model
    gc.collect()
    model_files = sorted(p for p in model_dir.rglob("*") if p.is_file() and p.suffix.casefold() == ".onnx")
    if not model_files or not any("int8" in p.name.casefold() for p in model_files):
        raise RuntimeError("O carregamento não encontrou o conjunto ONNX INT8 esperado; instalação não foi marcada como concluída.")

    print("[2/3] Baixando/carregando Silero VAD ONNX para CPU.", flush=True)
    print(f"Destino: {vad_dir}", flush=True)
    required_vad_files = ("config.json", "silero_vad.onnx")
    if not all((vad_dir / name).is_file() for name in required_vad_files):
        snapshot_download(
            "istupakov/silero-vad-onnx", revision="b3e3ee3",
            local_dir=vad_dir, allow_patterns=list(required_vad_files),
        )
    vad = onnx_asr.load_vad(
        "silero", path=vad_dir, sess_options=make_session_options(1),
        providers=["CPUExecutionProvider"],
    )
    print("Silero VAD carregado e validado com CPUExecutionProvider.", flush=True)
    del vad
    gc.collect()
    if not any(p.is_file() and p.suffix.casefold() == ".onnx" for p in vad_dir.rglob("*")):
        raise RuntimeError("Silero VAD ONNX não foi localizado após o carregamento.")

    manifest = {
        "schema": 1,
        "model": MODEL_NAME,
        "quantization": "int8",
        "provider": "CPUExecutionProvider",
        "onnx_asr_version": importlib.metadata.version("onnx-asr"),
        "onnxruntime_version": ort.__version__,
        "model_files": [{"name": p.relative_to(model_dir).as_posix(), "size": p.stat().st_size}
                        for p in model_files],
    }
    temp_name = None
    try:
        # Creating temporary entries beside memory-mapped ONNX weights can be
        # stalled by Windows file scanning. Create on the same volume in the
        # models parent, then atomically replace the final manifest.
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=model_dir.parent,
                                         prefix=".install-", suffix=".tmp", delete=False) as stream:
            temp_name = stream.name
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        Path(temp_name).replace(model_dir / "berofel-install.json")
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)
    print("[3/3] Modelo e VAD instalados e carregados com CPU provider.", flush=True)
    print("Parakeet TDT 0.6B v3 INT8 pronto para uso offline.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

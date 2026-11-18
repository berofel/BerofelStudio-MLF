"""Valida a instalacao real, inclusive dependencias nativas no Windows."""
import argparse
import importlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))


def result(name: str, ok: bool, detail: str = "") -> bool:
    mark = "OK" if ok else "FALHOU"
    print(f"[{mark}] {name}" + (f" - {detail}" if detail else ""), flush=True)
    return ok


def check_executable(path: Path, name: str) -> bool:
    if not path.is_file():
        return result(name, False, "arquivo ausente")
    try:
        proc = subprocess.run([str(path), "-version"], capture_output=True, text=True,
                              timeout=15, errors="replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return result(name, False, str(exc))
    return result(name, proc.returncode == 0, (proc.stdout or proc.stderr).splitlines()[0][:140])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="exige todos os componentes da alpha")
    ap.add_argument("--quick", action="store_true", help="verificacoes rapidas para iniciar")
    ap.add_argument("--editor-only", action="store_true", help="ignora IA opcional")
    ap.add_argument("--ai", action="store_true", help="exige modelos e bibliotecas de transcricao")
    args = ap.parse_args()
    bad = 0
    print("=== BerofelStudio - diagnostico de instalacao ===", flush=True)
    bad += not result("Python", sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32,
                      sys.version.split()[0] + (" (64-bit)" if sys.maxsize > 2**32 else " (32-bit)"))
    core_modules = ("PySide6.QtCore", "PySide6.QtWidgets", "PySide6.QtMultimedia",
                    "PySide6.QtMultimediaWidgets", "imageio_ffmpeg", "PIL", "psutil", "zmq")
    ai_modules = ("numpy", "faster_whisper", "ctranslate2", "av", "onnxruntime")
    for module in core_modules + (ai_modules if args.ai and not args.editor_only else ()):
        try:
            importlib.import_module(module)
            ok, info = True, "importacao concluida"
        except Exception as exc:
            ok, info = False, f"{type(exc).__name__}: {exc}"
        if not result(module, ok, info):
            bad += 1
    ffmpeg = ROOT / "tools" / "ffmpeg" / "ffmpeg.exe"
    ffprobe = ROOT / "tools" / "ffmpeg" / "ffprobe.exe"
    if sys.platform == "win32" or args.strict:
        bad += not check_executable(ffmpeg, "FFmpeg completo")
        bad += not check_executable(ffprobe, "FFprobe completo")
        try:
            from berofel.services.ffmpeg import supports_filter
            live_eq=supports_filter("azmq",str(ffmpeg))
            result("FFmpeg azmq (EQ ao vivo)",live_eq,
                   "filtros atualizados sem reiniciar" if live_eq else
                   "indisponível; a prévia será reconstruída ao ajustar EQ")
        except Exception as exc:
            result("FFmpeg azmq (EQ ao vivo)",False,str(exc))
    if args.ai and not args.editor_only and not args.quick:
        try:
            from preparar_modelos import model_path
            model = model_path()
            valid = (model / "config.json").is_file() and (model / "model.bin").is_file()
            if args.strict:
                bad += not result("Whisper Base baixado", valid, str(model))
            else:
                result("Whisper Base baixado", valid, str(model))
        except Exception as exc:
            bad += not result("Whisper Base baixado", False, str(exc))
    if args.strict:
        rc = subprocess.run([sys.executable, "-m", "pip", "check"], capture_output=True,
                            text=True, timeout=60)
        bad += not result("pip check (dependencias transitivas)", rc.returncode == 0,
                          (rc.stdout or rc.stderr).strip()[:220])
    print("=== " + ("TUDO OK" if bad == 0 else f"{bad} problema(s) encontrado(s)") + " ===", flush=True)
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

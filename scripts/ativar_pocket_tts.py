"""Authorize and prepare Pocket TTS without a visible terminal or token arguments."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))


def main() -> int:
    # The GUI passes the token through stdin. Never print it, persist a copy, or
    # put it in process arguments; Hugging Face stores it using its own auth API.
    token = sys.stdin.readline(4097).strip()
    if not token or len(token) > 4096:
        print('[ERRO] Token vazio ou inválido.', flush=True)
        return 2
    try:
        from huggingface_hub import login
        login(token=token, add_to_git_credential=False)
    except Exception as exc:
        from berofel.services.pocket_tts_worker import activation_failure_message
        detail=activation_failure_message(exc).replace(token,'[redigido]')
        token = ''
        print(f'[ERRO] {detail}', flush=True)
        return 2
    token = ''

    from scripts.preparar_modelo_pocket import main as prepare_model
    return int(prepare_model())


if __name__ == '__main__':
    raise SystemExit(main())

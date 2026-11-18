"""Download explícito dos pesos públicos Qwen3-TTS para uso offline local."""
from __future__ import annotations
import os
from pathlib import Path
from huggingface_hub import snapshot_download

root=Path(os.environ['LOCALAPPDATA'])/'BFS'/'qwen3_tts'
model=root/'model'
model.mkdir(parents=True,exist_ok=True)
snapshot_download(repo_id='Qwen/Qwen3-TTS-12Hz-0.6B-Base',
    revision='main',local_dir=str(model),token=False)
required=tuple(model/name for name in (
    'config.json','model.safetensors','preprocessor_config.json',
    'tokenizer_config.json','vocab.json','merges.txt','speech_tokenizer/config.json',
    'speech_tokenizer/configuration.json','speech_tokenizer/model.safetensors',
    'speech_tokenizer/preprocessor_config.json'))
missing=[str(path) for path in required if not path.is_file()]
if missing:
    raise SystemExit('Download incompleto; arquivos ausentes: '+', '.join(missing))
print(f'Modelo Qwen3-TTS local pronto em: {model}')

"""Executa GUI e registra traceback caso a inicialização falhe."""
from pathlib import Path
import sys
import traceback
from datetime import datetime
root=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(root))
try:
    from main import main
    code=main()
    raise SystemExit(code)
except SystemExit:
    raise
except BaseException:
    logs=root/'logs';logs.mkdir(exist_ok=True)
    path=logs/('erro_abertura_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.log')
    info=traceback.format_exc()
    path.write_text(info,encoding='utf-8')
    print('ERRO AO ABRIR BEROFELSTUDIO:')
    print(info)
    print('Log salvo:',path)
    raise SystemExit(1)

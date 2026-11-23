"""Install the optional local VERO/Hunspell proofing data and Spylls runtime."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen


REVISION = '1e848fbddd7fd8e03fb696ecc03ee1068fab141c'
FILES = {
    'pt_BR.aff': '4664ad6fc893e5683c1140eab8c1e1faeca802d3',
    'pt_BR.dic': '849c1dcaf873e72e364f7a64b6f1f2a679bbb097',
}
LICENSE_NOTICE = (
    'VERO - dicionario pt-BR do projeto LibreOffice/dictionaries.\n'
    'Revisao upstream: ' + REVISION + '\n'
    'Licencas informadas pelo projeto: LGPLv3 e Mozilla Public License (MPL).\n'
    'Fonte: https://github.com/LibreOffice/dictionaries/tree/' + REVISION + '/pt_BR\n'
    'Os arquivos originais permanecem identificados e nao foram modificados.\n'
)


def _git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(data)).encode('ascii') + b'\0' + data).hexdigest()


def _download_checked(name: str, destination: Path) -> None:
    url = f'https://raw.githubusercontent.com/LibreOffice/dictionaries/{REVISION}/pt_BR/{name}'
    request = Request(url, headers={'User-Agent': 'BerofelStudio-spellcheck-installer/1'})
    size = 0
    with urlopen(request, timeout=45) as response, destination.open('wb') as out:
        while chunk := response.read(1024 * 1024):
            out.write(chunk)
            size += len(chunk)
    data = destination.read_bytes()
    actual = _git_blob_sha1(data)
    if actual != FILES[name]:
        destination.unlink(missing_ok=True)
        raise RuntimeError(f'Integridade inválida para {name}: {actual}')
    if size == 0:
        destination.unlink(missing_ok=True)
        raise RuntimeError(f'O arquivo {name} veio vazio.')


def _app_python() -> Path:
    local = Path(os.environ.get('LOCALAPPDATA', ''))
    installed = local / 'BFS' / 'venv' / 'Scripts' / 'python.exe'
    return installed if installed.is_file() else Path(sys.executable)


def install() -> Path:
    local_value = os.environ.get('LOCALAPPDATA', '').strip()
    if not local_value:
        raise RuntimeError('LOCALAPPDATA nao esta configurada.')
    local = Path(local_value)
    root = local / 'BFS' / 'dictionaries'
    target = root / f'pt_BR-{REVISION[:8]}'
    root.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if all((target / name).is_file()
               and _git_blob_sha1((target / name).read_bytes()) == digest
               for name, digest in FILES.items()):
            print(f'Dicionario ja instalado e verificado: {target}')
        else:
            raise RuntimeError(f'Pasta existente preservada, mas incompleta: {target}')
    else:
        with tempfile.TemporaryDirectory(prefix='.pt_BR-staging-', dir=root) as temp:
            staging = Path(temp)
            for name in FILES:
                _download_checked(name, staging / name)
            staging.joinpath('LICENSE_NOTICE.txt').write_text(LICENSE_NOTICE, encoding='utf-8')
            staging.replace(target)
            print(f'Dicionario VERO instalado e verificado: {target}')

    python = _app_python()
    has_spylls = subprocess.run(
        [str(python), '-c', 'import importlib.util,sys;sys.exit(0 if importlib.util.find_spec("spylls") else 1)'],
        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if not has_spylls:
        result = subprocess.run(
            [str(python), '-m', 'pip', 'install', '--disable-pip-version-check',
             '--no-input', '--only-binary=:all:', 'spylls==0.1.7'],
            check=False,
        )
        if result.returncode:
            raise RuntimeError(
                f'Falha instalando Spylls no ambiente local {python}. '
                f'O dicionario foi preservado em {target}.')
    print(f'Spylls instalado no ambiente local: {python}')
    print('Reinicie o Berofel Studio para habilitar Revisar ortografia.')
    return target


if __name__ == '__main__':
    try:
        install()
    except Exception as error:
        print(f'[ERRO] {error}', file=sys.stderr)
        raise SystemExit(1)

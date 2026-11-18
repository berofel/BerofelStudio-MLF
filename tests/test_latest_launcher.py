"""Regressão do launcher raiz: resolve o maior SemVer instalável no Windows."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

WORKSPACE=Path(__file__).resolve().parents[3]
LOCATOR=WORKSPACE/'LOCALIZAR_BEROFELSTUDIO.ps1'


@unittest.skipUnless(os.name=='nt','Localizador do launcher usa PowerShell no Windows.')
class LatestLauncherTests(unittest.TestCase):
    def _install(self,root,name,version,valid=True):
        app=root/name
        (app/'berofel'/'ui').mkdir(parents=True)
        (app/'ABRIR_BEROFELSTUDIO.bat').write_text('@echo off\n',encoding='utf-8')
        (app/'berofel'/'__init__.py').write_text(
            f"__version__ = '{version}'\n",encoding='utf-8')
        if valid:
            for relative in ('main.py','berofel/ui/studio_header.py',
                             'berofel/ui/library_panel.py','berofel/ui/preview_transport.py'):
                path=app/relative
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text('# fixture\n',encoding='utf-8')
        return app/'ABRIR_BEROFELSTUDIO.bat'

    def _locate(self,root):
        result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass',
            '-File',str(LOCATOR),'-SearchRoot',str(root)],capture_output=True,text=True,
            encoding='utf-8',errors='replace',timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        return Path(result.stdout.strip())

    def test_selects_highest_valid_version_and_orders_prereleases(self):
        with tempfile.TemporaryDirectory(prefix='BFS launcher ') as folder:
            root=Path(folder)
            self._install(root,'old','0.9.9')
            alpha=self._install(root,'alpha','0.10.0-alpha.1')
            self._install(root,'unknown','0.11.0-dev.1')
            self._install(root,'invalid','0.99.0',valid=False)
            self.assertEqual(self._locate(root),alpha)
            stable=self._install(root,'stable','0.10.0')
            self.assertEqual(self._locate(root),stable)

    def test_same_version_prefers_newer_module_even_if_version_file_is_older(self):
        with tempfile.TemporaryDirectory(prefix='BFS launcher same version ') as folder:
            root=Path(folder)
            older=self._install(root,'copy_a','0.10.0-alpha.1')
            newer=self._install(root,'copy_b','0.10.0-alpha.1')
            older_version=older.parent/'berofel'/'__init__.py'
            newer_version=newer.parent/'berofel'/'__init__.py'
            os.utime(older_version,(1_700_000_000,1_700_000_000))
            os.utime(newer_version,(1_690_000_000,1_690_000_000))
            newer_module=newer.parent/'berofel'/'ui'/'library_panel.py'
            os.utime(newer_module,(1_730_000_000,1_730_000_000))
            self.assertEqual(self._locate(root),newer)


if __name__=='__main__':unittest.main()

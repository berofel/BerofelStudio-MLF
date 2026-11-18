import os
import tempfile
import unittest
from pathlib import Path

from berofel.core.project import Project
from berofel.services.project_recovery import (load_project, newer_autosave,
    newer_autosave_project, write_autosave_snapshot)


class ProjectRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.original = Path(self.temp.name) / 'edit.berofel.json'
        Project(name='saved').save(str(self.original))
        self.backup = Path(str(self.original) + '.autosave')

    def write_backup(self, name='recovered'):
        Project(name=name).save(str(self.backup))
        os.utime(self.backup, ns=(self.original.stat().st_mtime_ns + 2_000_000,
                                  self.original.stat().st_mtime_ns + 2_000_000))

    def test_newer_autosave_is_recoverable_without_changing_save_target(self):
        self.write_backup()
        original_bytes = self.original.read_bytes()
        self.assertEqual(newer_autosave(self.original), self.backup)
        project = load_project(self.original, recover=True)
        self.assertEqual(project.name, 'recovered')
        self.assertEqual(Path(project.path), self.original.resolve())
        self.assertEqual(self.original.read_bytes(), original_bytes)

    def test_open_flow_can_reuse_the_validated_recovery_project(self):
        from unittest.mock import patch
        self.write_backup()
        loader=Project.load
        with patch.object(Project,'load',wraps=loader) as load_spy:
            backup,recovered=newer_autosave_project(self.original)
        self.assertEqual(backup,self.backup)
        self.assertEqual(recovered.name,'recovered')
        self.assertEqual(recovered.path,str(self.original.resolve()))
        self.assertEqual(load_spy.call_count,1)

    def test_identical_newer_autosave_is_not_offered(self):
        self.backup.write_bytes(self.original.read_bytes())
        stamp = self.original.stat().st_mtime_ns + 2_000_000
        os.utime(self.backup, ns=(stamp, stamp))
        self.assertIsNone(newer_autosave(self.original))

    def test_older_autosave_is_not_offered(self):
        self.write_backup()
        stamp = self.original.stat().st_mtime_ns - 2_000_000
        os.utime(self.backup, ns=(stamp, stamp))
        self.assertIsNone(newer_autosave(self.original))
        self.assertEqual(load_project(self.original, recover=True).name, 'saved')

    def test_corrupt_newer_autosave_is_not_offered_and_original_still_opens(self):
        self.backup.write_text('{truncated project json',encoding='utf-8')
        stamp=self.original.stat().st_mtime_ns+2_000_000
        os.utime(self.backup,ns=(stamp,stamp))
        original_bytes=self.original.read_bytes()
        self.assertIsNone(newer_autosave(self.original))
        project=load_project(self.original,recover=True)
        self.assertEqual(project.name,'saved')
        self.assertEqual(self.original.read_bytes(),original_bytes)

    def test_newer_but_unsupported_autosave_version_is_not_offered(self):
        self.backup.write_text('{"version":999,"clips":[]}',encoding='utf-8')
        stamp=self.original.stat().st_mtime_ns+2_000_000
        os.utime(self.backup,ns=(stamp,stamp))
        self.assertIsNone(newer_autosave(self.original))

    def test_snapshot_autosave_never_changes_the_live_project_path(self):
        project = Project(name='in memory', path=str(self.original))
        destination = write_autosave_snapshot(project, self.original)
        self.assertEqual(destination, self.backup.resolve())
        self.assertEqual(project.path, str(self.original))
        self.assertEqual(Project.load(str(destination)).name, 'in memory')

    def test_stale_snapshot_is_discarded_after_manual_save(self):
        snapshot = Project(name='stale snapshot')
        expected = self.original.stat().st_mtime_ns
        Project(name='new manual save').save(str(self.original))
        stamp = self.original.stat().st_mtime_ns + 2_000_000
        os.utime(self.original, ns=(stamp, stamp))
        self.assertIsNone(write_autosave_snapshot(
            snapshot, self.original, expected_mtime_ns=expected))
        self.assertFalse(self.backup.exists())


if __name__ == '__main__':
    unittest.main()

"""Offline contract tests for the PowerShell GitHub-release resolver."""
from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_latest_release.ps1"
NSIS_SCRIPT = ROOT / "installer" / "BerofelStudio.nsi"
POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")


class InstallerWindowContractTests(unittest.TestCase):
    def test_bootstrap_runs_hidden_and_streams_status_into_installer_log(self):
        source = NSIS_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("nsExec::ExecToLog", source)
        self.assertIn("-NonInteractive", source)
        self.assertIn("Preparando Python, bibliotecas, FFmpeg e testes locais em segundo plano", source)
        self.assertNotIn('ExecWait \'"$SYSDIR\\WindowsPowerShell\\v1.0\\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\\scripts\\instalar_windows.ps1"', source)

    def test_optional_powerShell_bootstraps_are_hidden(self):
        source = (ROOT / "scripts" / "instalar_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("-NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'instalar_ia.ps1')", source)
        self.assertIn("-NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'instalar_qwen3_tts_local.ps1')", source)


def release(version: str, *, draft: bool = False, include_assets: bool = True) -> dict:
    tag = f"v{version}"
    base = f"https://github.com/berofel/BerofelStudio-MLF/releases/download/{tag}/"
    exe = f"BerofelStudio-{version}-Setup-x64.exe"
    assets = ([
        {"name": exe, "browser_download_url": base + exe, "digest": None},
        {"name": exe + ".sha256", "browser_download_url": base + exe + ".sha256"},
    ] if include_assets else [])
    return {"tag_name": tag, "draft": draft, "prerelease": "-" in version, "assets": assets}


@unittest.skipUnless(POWERSHELL, "Windows PowerShell não está disponível")
class LatestInstallerTests(unittest.TestCase):
    def run_check(self, current: str, releases: list[dict], *,
                  include_prerelease: bool = False) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory(prefix="bfs_release_metadata_") as folder:
            metadata = Path(folder) / "releases.json"
            metadata.write_text(json.dumps(releases), encoding="utf-8")
            args = [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                    "-File", str(SCRIPT), "-CurrentVersion", current,
                    "-MetadataJsonPath", str(metadata)]
            if include_prerelease:
                args.append("-IncludePrerelease")
            args.append("-CheckOnly")
            return subprocess.run(
                args,
                cwd=ROOT, capture_output=True, text=True, timeout=20,
            )

    def run_checksum(self, payload: bytes, *, manifest_name: str | None = None,
                     manifest_hash: str | None = None) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory(prefix="bfs_installer_checksum_") as folder:
            package = Path(folder) / "BerofelStudio-0.10.0-alpha.3-Setup-x64.exe"
            checksum = Path(str(package) + ".sha256")
            package.write_bytes(payload)
            digest = manifest_hash or hashlib.sha256(payload).hexdigest()
            name = manifest_name or package.name
            checksum.write_text(f"{digest}  {name}\n", encoding="ascii")
            return subprocess.run(
                [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-File", str(SCRIPT), "-CurrentVersion", "0.10.0-alpha.3",
                 "-VerifyChecksumOnly", "-VerifyPackagePath", str(package),
                 "-VerifyChecksumPath", str(checksum)],
                cwd=ROOT, capture_output=True, text=True, timeout=20,
            )

    def test_newer_release_is_detected_without_downloading(self):
        result = self.run_check("0.10.0-alpha.2", [release("0.10.0-alpha.3")],
                                include_prerelease=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("STATUS=UPDATE_AVAILABLE VERSION=0.10.0-alpha.3", result.stdout)

    def test_current_version_does_not_offer_downgrade(self):
        result = self.run_check("0.10.0-alpha.4", [release("0.10.0-alpha.3")],
                                include_prerelease=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("STATUS=UP_TO_DATE VERSION=0.10.0-alpha.4", result.stdout)

    def test_stable_release_sorts_above_prerelease(self):
        result = self.run_check("0.10.0-alpha.9", [
            release("0.10.0-alpha.10"), release("0.10.0")], include_prerelease=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("STATUS=UPDATE_AVAILABLE VERSION=0.10.0", result.stdout)

    def test_draft_or_release_without_installer_is_ignored(self):
        result = self.run_check("0.10.0-alpha.2", [
            release("0.11.0", draft=True), release("0.10.0-alpha.3", include_assets=False)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("STATUS=NO_RELEASE_WITH_INSTALLER", result.stdout)

    def test_untrusted_asset_url_is_rejected(self):
        item = release("0.10.0-alpha.3")
        item["assets"][0]["browser_download_url"] = "https://evil.invalid/setup.exe"
        result = self.run_check("0.10.0-alpha.2", [item], include_prerelease=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("STATUS=UPDATE_CHECK_FAILED", result.stdout)

    def test_stable_installer_ignores_prerelease_channel(self):
        result = self.run_check("0.10.0", [release("0.11.0-alpha.1")])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("STATUS=NO_RELEASE_WITH_INSTALLER", result.stdout)

    def test_download_checksum_accepts_matching_package(self):
        result = self.run_checksum(b"BFS" * 400_000)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("STATUS=CHECKSUM_VALID", result.stdout)

    def test_download_checksum_rejects_modified_package(self):
        result = self.run_checksum(b"tampered" * 200_000,
                                   manifest_hash="0" * 64)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("STATUS=UPDATE_CHECK_FAILED", result.stdout)

    def test_download_checksum_rejects_filename_mismatch(self):
        result = self.run_checksum(b"BFS" * 400_000,
                                   manifest_name="different-installer.exe")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("STATUS=UPDATE_CHECK_FAILED", result.stdout)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ui_app.settings_store import resolve_mumu_adb_path, resolve_mumu_manager_path


class MuMuPathTests(unittest.TestCase):
    def test_resolves_current_nx_main_layout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = root / "nx_main" / "MuMuManager.exe"
            adb = root / "nx_main" / "adb.exe"
            manager.parent.mkdir()
            manager.touch()
            adb.touch()

            self.assertEqual(resolve_mumu_manager_path(root), manager)
            self.assertEqual(resolve_mumu_adb_path(root), adb)

    def test_resolves_mumu_player_12_shell_layout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "软件" / "emulator" / "MuMuPlayer-12.0"
            manager = root / "shell" / "MuMuManager.exe"
            adb = root / "shell" / "adb.exe"
            manager.parent.mkdir(parents=True)
            manager.touch()
            adb.touch()

            self.assertEqual(resolve_mumu_manager_path(root), manager)
            self.assertEqual(resolve_mumu_adb_path(root), adb)

    def test_accepts_shell_directory_itself(self):
        with tempfile.TemporaryDirectory() as temporary:
            shell = Path(temporary) / "shell"
            manager = shell / "MuMuManager.exe"
            shell.mkdir()
            manager.touch()

            self.assertEqual(resolve_mumu_manager_path(shell), manager)

    def test_missing_adb_returns_none(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertIsNone(resolve_mumu_adb_path(Path(temporary)))


if __name__ == "__main__":
    unittest.main()

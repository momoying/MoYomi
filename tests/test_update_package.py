from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


class UpdatePackageTests(unittest.TestCase):
    def test_release_tag_generates_matching_full_and_incremental_packages(self):
        project_root = Path(__file__).resolve().parents[1]
        builder = project_root / "tools" / "build_update_package.py"
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)

            def git(*args: str) -> None:
                subprocess.run(
                    ["git", *args], cwd=repo, check=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )

            git("init")
            git("config", "user.name", "Update Package Test")
            git("config", "user.email", "updates@example.invalid")
            (repo / "module").mkdir()
            (repo / "ui.py").write_text("old ui\n", encoding="utf-8")
            (repo / "requirements.txt").write_text("flet\n", encoding="utf-8")
            (repo / "module" / "updater.py").write_text("old updater\n", encoding="utf-8")
            old_template = "tasks/示例/res/商店.png"
            new_template = "module/res/common_ui/商店.png"
            (repo / old_template).parent.mkdir(parents=True)
            (repo / old_template).write_bytes(b"unchanged template")
            git("add", ".")
            git("commit", "-m", "base release")
            git("tag", "v1.6.3")

            (repo / "ui.py").write_text("new ui\n", encoding="utf-8")
            (repo / new_template).parent.mkdir(parents=True)
            (repo / old_template).rename(repo / new_template)
            git("add", "-A")
            git("commit", "-m", "next release")
            git("tag", "v1.6.4")

            output = repo / "dist"
            subprocess.run(
                [sys.executable, str(builder), "v1.6.4", str(output)],
                cwd=repo,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            with zipfile.ZipFile(output / "MoYomi-Full-v1.6.4.zip") as archive:
                version_path = next(
                    name for name in archive.namelist()
                    if name.endswith("/.moyomi-version.json")
                )
                full_version = json.loads(archive.read(version_path))
                wrapper = version_path.rsplit("/", 1)[0]
                self.assertEqual(archive.read(f"{wrapper}/{new_template}"), b"unchanged template")
                self.assertNotIn(f"{wrapper}/{old_template}", archive.namelist())
            self.assertEqual(full_version, {"version": "1.6.4", "tag": "v1.6.4"})

            with zipfile.ZipFile(output / "MoYomi-OTA-v1.6.3_v1.6.4.zip") as archive:
                manifest_path = next(
                    name for name in archive.namelist()
                    if name.endswith("/.moyomi-update.json")
                )
                version_path = next(
                    name for name in archive.namelist()
                    if name.endswith("/.moyomi-version.json")
                )
                manifest = json.loads(archive.read(manifest_path))
                ota_version = json.loads(archive.read(version_path))
                wrapper = version_path.rsplit("/", 1)[0]
                self.assertEqual(archive.read(f"{wrapper}/{new_template}"), b"unchanged template")
            self.assertEqual(manifest["from_version"], "1.6.3")
            self.assertEqual(manifest["to_version"], "1.6.4")
            self.assertEqual(manifest["kind"], "incremental-v2")
            self.assertEqual(manifest["deleted"], [old_template])
            self.assertEqual(manifest["base_files"], {
                "ui.py": hashlib.sha256(b"old ui\n").hexdigest(),
                "requirements.txt": hashlib.sha256(b"flet\n").hexdigest(),
                "module/updater.py": hashlib.sha256(b"old updater\n").hexdigest(),
                old_template: hashlib.sha256(b"unchanged template").hexdigest(),
            })
            self.assertEqual(ota_version, full_version)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import io
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from module import updater


class _Response:
    def __init__(self, data: bytes = b"", url: str = updater.LATEST_RELEASE_URL):
        self._stream = io.BytesIO(data)
        self._url = url
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def geturl(self) -> str:
        return self._url


def _write_release_zip(
    path: Path, files: dict[str, bytes], *, version: str = "1.6.4"
) -> None:
    required = {
        "ui.py": b"new ui",
        "requirements.txt": b"same requirements",
        "module/updater.py": b"new updater",
    }
    required.update(files)
    with zipfile.ZipFile(path, "w") as archive:
        for relative, data in required.items():
            archive.writestr(f"momoying-MoYomi-abcdef/{relative}", data)
        archive.writestr(
            "momoying-MoYomi-abcdef/.moyomi-version.json",
            json.dumps({"version": version, "tag": f"v{version}"}),
        )


def _write_ota_zip(
    path: Path,
    files: dict[str, bytes],
    *,
    deleted: tuple[str, ...] = (),
    from_version: str = "1.6.3",
    to_version: str = "1.6.4",
) -> None:
    wrapper = "momoying-MoYomi-v1.6.4"
    all_files = dict(files)
    version_file = json.dumps(
        {"version": to_version, "tag": f"v{to_version}"}
    ).encode("utf-8")
    all_files[".moyomi-version.json"] = version_file
    metadata = {
        "kind": "incremental",
        "from_version": from_version,
        "to_version": to_version,
        "deleted": list(deleted),
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in all_files.items()},
    }
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in all_files.items():
            archive.writestr(f"{wrapper}/{name}", data)
        archive.writestr(
            f"{wrapper}/.moyomi-update.json",
            json.dumps(metadata),
        )


class VersionTests(unittest.TestCase):
    def test_version_comparison(self):
        self.assertTrue(updater.is_newer_version("v1.6.2", "1.6.1"))
        self.assertFalse(updater.is_newer_version("v1.6.1", "1.6.1"))
        self.assertFalse(updater.is_newer_version("v1.5.9", "1.6.1"))
        self.assertIsNone(updater.parse_version("release-1.6.2"))

    def test_consuming_state_removes_legacy_installed_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            state_path = Path(temporary) / "update_state.json"
            updater._save_state(
                state_path,
                {"managed_files": ["ui.py"], "installed_version": "1.6.3"},
            )
            self.assertIsNone(updater.consume_update_result(state_path))
            state = updater._load_state(state_path)
            self.assertEqual(state, {"managed_files": ["ui.py"]})

    def test_check_returns_new_stable_release(self):
        release = updater.check_for_update(
            opener=lambda *_args, **_kwargs: _Response(
                url="https://github.com/momoying/MoYomi/releases/tag/v1.6.3"
            ),
            current_version="1.6.1",
        )
        self.assertIsNotNone(release)
        self.assertEqual(release.version, "1.6.3")
        self.assertEqual(
            release.ota_url,
            "https://github.com/momoying/MoYomi/releases/download/"
            "v1.6.3/MoYomi-OTA-v1.6.1_v1.6.3.zip",
        )
        self.assertEqual(
            release.full_url,
            "https://github.com/momoying/MoYomi/releases/download/"
            "v1.6.3/MoYomi-Full-v1.6.3.zip",
        )

    def test_installed_version_comes_from_release_metadata_not_update_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            version_path = base / ".moyomi-version.json"
            state_path = base / "config" / "update_state.json"
            state_path.parent.mkdir()
            state_path.write_text(
                json.dumps({"installed_version": "1.6.2"}), encoding="utf-8"
            )
            version_path.write_text(
                json.dumps({"version": "1.6.4", "tag": "v1.6.4"}),
                encoding="utf-8",
            )
            with mock.patch.object(updater, "VERSION_METADATA_PATH", version_path), mock.patch.object(
                updater, "UPDATE_STATE_PATH", state_path
            ):
                self.assertEqual(updater._installed_version(), "1.6.4")
                version_path.unlink()
                self.assertEqual(updater._installed_version(), "0.0.0")

    def test_check_ignores_same_version(self):
        same = updater.check_for_update(
            opener=lambda *_args, **_kwargs: _Response(
                url="https://github.com/momoying/MoYomi/releases/tag/v1.6.1"
            ),
            current_version="1.6.1",
        )
        self.assertIsNone(same)

    def test_unreleased_source_checkout_uses_full_package(self):
        release = updater.check_for_update(
            opener=lambda *_args, **_kwargs: _Response(
                url="https://github.com/momoying/MoYomi/releases/tag/v1.6.3"
            ),
            current_version="0.0.0",
        )
        self.assertIsNotNone(release)
        self.assertEqual(release.ota_url, "")
        self.assertTrue(release.full_url.endswith("MoYomi-Full-v1.6.3.zip"))

    def test_check_rejects_missing_release_and_bad_tag(self):
        with self.assertRaises(updater.UpdateError):
            updater.check_for_update(
                opener=lambda *_args, **_kwargs: _Response(
                    url="https://github.com/momoying/MoYomi/releases"
                )
            )
        with self.assertRaises(updater.UpdateError):
            updater.check_for_update(
                opener=lambda *_args, **_kwargs: _Response(
                    url=(
                        "https://github.com/momoying/MoYomi/releases/tag/"
                        "release-1.6.2"
                    )
                )
            )


class ArchiveTests(unittest.TestCase):
    def test_download_uses_ota_when_base_version_matches(self):
        release = updater.ReleaseInfo(
            version="1.6.4",
            tag_name="v1.6.4",
            name="v1.6.4",
            notes="",
            page_url="https://github.com/momoying/MoYomi/releases/tag/v1.6.4",
            ota_url="https://github.com/momoying/MoYomi/releases/download/v1.6.4/ota.zip",
            full_url="https://github.com/momoying/MoYomi/releases/download/v1.6.4/full.zip",
        )
        with tempfile.TemporaryDirectory() as temporary:
            ota_path = Path(temporary) / "ota.zip"
            _write_ota_zip(ota_path, {"changed.py": b"new"}, to_version="1.6.4")
            ota_bytes = ota_path.read_bytes()
        attempted = []

        def opener(request, **_kwargs):
            attempted.append(request.full_url)
            return _Response(ota_bytes, request.full_url)

        with mock.patch.object(updater, "APP_VERSION", "1.6.3"):
            prepared = updater.download_release(release, opener=opener)
        try:
            self.assertTrue(prepared.incremental)
            self.assertEqual(attempted, [release.ota_url])
            self.assertEqual(prepared.changed_files, 2)
        finally:
            import shutil

            shutil.rmtree(prepared.temporary_dir, ignore_errors=True)

    def test_download_falls_back_to_full_archive_when_ota_is_unavailable(self):
        release = updater.ReleaseInfo(
            version="1.6.4",
            tag_name="v1.6.4",
            name="v1.6.4",
            notes="",
            page_url="https://github.com/momoying/MoYomi/releases/tag/v1.6.4",
            ota_url="https://github.com/momoying/MoYomi/releases/download/v1.6.4/ota.zip",
            full_url="https://github.com/momoying/MoYomi/releases/download/v1.6.4/full.zip",
        )
        full_archive = io.BytesIO()
        with zipfile.ZipFile(full_archive, "w") as archive:
            archive.writestr("wrapper/ui.py", b"ui")
            archive.writestr("wrapper/requirements.txt", b"requirements")
            archive.writestr("wrapper/module/updater.py", b"updater")
            archive.writestr(
                "wrapper/.moyomi-version.json",
                json.dumps({"version": "1.6.4", "tag": "v1.6.4"}),
            )

        attempted = []

        def opener(request, **_kwargs):
            attempted.append(request.full_url)
            if request.full_url == release.ota_url:
                raise OSError("OTA not published")
            return _Response(full_archive.getvalue(), request.full_url)

        with mock.patch.object(updater, "APP_VERSION", "1.6.3"):
            prepared = updater.download_release(release, opener=opener)
        try:
            self.assertFalse(prepared.incremental)
            self.assertEqual(len(attempted), 2)
            self.assertEqual(attempted[0], release.ota_url)
            self.assertEqual(attempted[1], release.full_url)
        finally:
            import shutil

            shutil.rmtree(prepared.temporary_dir, ignore_errors=True)

    def test_download_does_not_fall_back_to_github_source_archive(self):
        release = updater.ReleaseInfo(
            version="1.6.4",
            tag_name="v1.6.4",
            name="v1.6.4",
            notes="",
            page_url="https://github.com/momoying/MoYomi/releases/tag/v1.6.4",
            ota_url="",
            full_url="https://github.com/momoying/MoYomi/releases/download/v1.6.4/MoYomi-Full-v1.6.4.zip",
        )
        source_archive = io.BytesIO()
        with zipfile.ZipFile(source_archive, "w") as archive:
            archive.writestr("wrapper/ui.py", b"ui")
            archive.writestr("wrapper/requirements.txt", b"requirements")
            archive.writestr("wrapper/module/updater.py", b"updater")

        with self.assertRaises(updater.UpdateError):
            updater.download_release(
                release,
                opener=lambda request, **_kwargs: _Response(
                    source_archive.getvalue(), request.full_url
                ),
            )

    def test_ota_archive_checks_manifest_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "ota.zip"
            _write_ota_zip(archive_path, {"changed.py": b"changed"})
            self.assertEqual(
                updater.validate_archive(archive_path),
                [".moyomi-version.json", "changed.py"],
            )

            wrapper = "momoying-MoYomi-v1.6.4"
            manifest = {
                "kind": "incremental",
                "from_version": "1.6.3",
                "to_version": "1.6.4",
                "deleted": [],
                "files": {"changed.py": hashlib.sha256(b"expected").hexdigest()},
            }
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(f"{wrapper}/changed.py", b"tampered")
                archive.writestr(f"{wrapper}/.moyomi-update.json", json.dumps(manifest))
            with self.assertRaises(updater.UpdateError):
                updater.validate_archive(archive_path)

    def test_archive_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "bad.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("wrapper/ui.py", b"ui")
                archive.writestr("wrapper/requirements.txt", b"requirements")
                archive.writestr("wrapper/module/updater.py", b"updater")
                archive.writestr("wrapper/../outside.py", b"bad")
            with self.assertRaises(updater.UpdateError):
                updater.validate_archive(archive_path)

    def test_archive_rejects_windows_backslash_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "bad-windows.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("wrapper/ui.py", b"ui")
                archive.writestr("wrapper/requirements.txt", b"requirements")
                archive.writestr("wrapper/module/updater.py", b"updater")
                archive.writestr("wrapper/..\\outside.py", b"bad")
            with self.assertRaises(updater.UpdateError):
                updater.validate_archive(archive_path)

    def test_apply_preserves_local_files_and_removes_managed_old_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "app"
            root.mkdir()
            (root / "ui.py").write_bytes(b"old ui")
            (root / "requirements.txt").write_bytes(b"same requirements")
            (root / "obsolete.py").write_bytes(b"obsolete")
            (root / "friend-note.txt").write_bytes(b"keep")
            (root / "config").mkdir()
            (root / "config" / "account.json").write_bytes(b"keep config")
            updater._save_state(
                root / "config" / "update_state.json",
                {
                    "managed_files": ["ui.py", "requirements.txt", "obsolete.py"],
                    "installed_version": "1.6.1",
                },
            )
            archive_path = base / "release.zip"
            _write_release_zip(
                archive_path,
                {
                    "new.py": b"new",
                    "config/account.json": b"must not replace",
                    "models/model.bin": b"must not replace",
                },
                version="1.6.2",
            )

            called = []
            success = updater.apply_update(
                archive_path,
                root,
                "python",
                "1.6.2",
                restart=False,
                requirements_installer=lambda *_args: called.append(True),
            )

            self.assertTrue(success)
            self.assertEqual((root / "ui.py").read_bytes(), b"new ui")
            self.assertFalse((root / "obsolete.py").exists())
            self.assertEqual((root / "friend-note.txt").read_bytes(), b"keep")
            self.assertEqual((root / "config" / "account.json").read_bytes(), b"keep config")
            self.assertFalse(called)
            self.assertFalse(
                "installed_version"
                in updater._load_state(root / "config" / "update_state.json")
            )

    def test_dependency_failure_rolls_back_program_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "app"
            (root / "module").mkdir(parents=True)
            (root / "config").mkdir()
            (root / "ui.py").write_bytes(b"old ui")
            (root / "requirements.txt").write_bytes(b"old requirements")
            (root / "module" / "updater.py").write_bytes(b"old updater")
            archive_path = base / "release.zip"
            _write_release_zip(
                archive_path,
                {"requirements.txt": b"new requirements", "new.py": b"new"},
                version="1.6.2",
            )

            def fail_install(*_args):
                raise updater.UpdateError("pip failed")

            success = updater.apply_update(
                archive_path,
                root,
                "python",
                "1.6.2",
                restart=False,
                requirements_installer=fail_install,
            )

            self.assertFalse(success)
            self.assertEqual((root / "ui.py").read_bytes(), b"old ui")
            self.assertEqual(
                (root / "requirements.txt").read_bytes(), b"old requirements"
            )
            self.assertFalse((root / "new.py").exists())
            state = updater._load_state(root / "config" / "update_state.json")
            self.assertEqual(state["last_result"]["status"], "error")

    def test_ota_updates_only_listed_files_and_deletes_removed_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "app"
            root.mkdir()
            (root / "changed.py").write_bytes(b"old")
            (root / "untouched.py").write_bytes(b"keep")
            (root / "removed.py").write_bytes(b"remove")
            (root / "requirements.txt").write_bytes(b"same requirements")
            updater._save_state(
                root / "config" / "update_state.json",
                {"managed_files": ["changed.py", "untouched.py", "removed.py", "requirements.txt"]},
            )
            archive_path = base / "ota.zip"
            _write_ota_zip(
                archive_path,
                {"changed.py": b"new"},
                deleted=("removed.py",),
            )
            installed = []
            success = updater.apply_update(
                archive_path,
                root,
                "python",
                "1.6.4",
                restart=False,
                requirements_installer=lambda *_args: installed.append(True),
            )

            self.assertTrue(success)
            self.assertEqual((root / "changed.py").read_bytes(), b"new")
            self.assertEqual((root / "untouched.py").read_bytes(), b"keep")
            self.assertFalse((root / "removed.py").exists())
            self.assertFalse(installed)


if __name__ == "__main__":
    unittest.main()

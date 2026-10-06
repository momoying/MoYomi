from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import ui
from module.diagnostics import ErrorScreenshotManager
from module.notifications import STATE_PATH


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _Backend:
    def __init__(self, *, cached=None, captured=None, fail_write=False):
        self.cached = cached
        self.captured = captured
        self.fail_write = fail_write
        self.capture_calls = 0
        self.saved_frames = []

    def get_last_screenshot(self):
        return self.cached

    def take_screenshot(self):
        self.capture_calls += 1
        return self.captured

    def save_screenshot(self, output_path, frame=None):
        if self.fail_write:
            raise OSError("disk unavailable")
        self.saved_frames.append(frame)
        path = Path(output_path)
        path.write_bytes(b"png")
        return str(path)


class ErrorScreenshotTests(unittest.TestCase):
    def test_cached_frame_is_preferred_and_filename_contains_context(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            backend = _Backend(cached="cached", captured="fresh")
            manager = ErrorScreenshotManager(
                backend=backend,
                directory=Path(temp_dir),
                keep_count=20,
            )
            saved = manager.save("merchant_task", "failed", attempt=2)

            self.assertIsNotNone(saved)
            self.assertEqual(backend.capture_calls, 0)
            self.assertEqual(backend.saved_frames, ["cached"])
            self.assertRegex(
                Path(saved).name,
                r"^merchant_task_failed_attempt_2_\d{8}_\d{6}_\d{3}\.png$",
            )

    def test_missing_cache_falls_back_to_live_capture(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            backend = _Backend(cached=None, captured="fresh")
            manager = ErrorScreenshotManager(
                backend=backend,
                directory=Path(temp_dir),
            )
            manager.save("task", "exception")
            self.assertEqual(backend.capture_calls, 1)
            self.assertEqual(backend.saved_frames, ["fresh"])

    def test_global_retention_and_zero_retention(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            backend = _Backend(cached="frame")
            manager = ErrorScreenshotManager(
                backend=backend,
                directory=directory,
                keep_count=2,
            )
            for index in range(3):
                path = directory / f"old_{index}.png"
                path.write_bytes(b"png")
                os.utime(path, (index + 1, index + 1))

            manager.prune()
            self.assertEqual(len(list(directory.glob("*.png"))), 2)
            self.assertIsNone(manager.save("task", "failed", keep_count=0))
            self.assertEqual(list(directory.glob("*.png")), [])

    def test_write_failure_is_non_fatal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            warnings = []
            manager = ErrorScreenshotManager(
                backend=_Backend(cached="frame", fail_write=True),
                directory=Path(temp_dir),
                warning=warnings.append,
            )
            self.assertIsNone(manager.save("task", "failed"))
            self.assertTrue(any("写入失败" in warning for warning in warnings))


class RuntimeMigrationTests(unittest.TestCase):
    def test_old_screenshot_setting_is_migrated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            path.write_text(
                json.dumps({"timeout_screenshot_keep_count": 7}),
                encoding="utf-8",
            )
            settings = ui.load_ui_settings(path)
            self.assertEqual(settings["error_screenshot_keep_count"], 7)
            self.assertNotIn("timeout_screenshot_keep_count", settings)

    def test_serverchan_state_is_under_config(self):
        self.assertEqual(
            STATE_PATH,
            PROJECT_ROOT / "config" / "serverchan_notification_state.json",
        )


if __name__ == "__main__":
    unittest.main()

import importlib.util
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

import flet as ft

from module import region_settings
from tasks.Account import sign
from ui_app import dashboard as dashboard_module
from ui_app.constants import DEFAULT_SETTINGS
from ui_app.dashboard import AssistantDashboard
from ui_app.pages import settings as settings_page
from ui_app.settings_store import load_ui_settings, save_ui_settings


class RegionSettingsTests(unittest.TestCase):
    def test_ui_region_fields_validate_save_and_reload(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            (root / "adb.exe").touch()
            (root / "MuMuManager.exe").touch()
            path = root / "ui_settings.json"
            settings = dict(DEFAULT_SETTINGS, adb_path=str(root / "adb.exe"), mumu_path=str(root))
            stack.enter_context(patch.object(dashboard_module, "load_ui_settings", return_value=settings))
            stack.enter_context(patch.object(dashboard_module, "discover_running_mumu_instances", return_value=[]))
            stack.enter_context(patch.object(dashboard_module, "get_serverchan_sendkey", return_value=""))
            for name in ("_configure_window", "_reload_task_settings_roles", "load_update_result",
                         "refresh_cards", "_refresh_schedule_summary", "append_log", "_safe_update"):
                stack.enter_context(patch.object(AssistantDashboard, name))
            stack.enter_context(patch.object(AssistantDashboard, "_build_layout", return_value=ft.Container()))
            dashboard = AssistantDashboard(Mock())
            panel = dashboard._build_global_settings_panel()
            rows = panel.content.controls[-1].controls
            self.assertTrue(any(
                isinstance(row, ft.Row)
                and row.controls == [dashboard.same_region_name, dashboard.cross_region_name]
                for row in rows
            ))
            self.assertEqual(dashboard.same_region_name.value, settings["same_region_name"])
            self.assertEqual(dashboard.cross_region_name.value, settings["cross_region_name"])
            for same, cross in ((" ", "夏之蝉"), ("春之樱", ""), ("春之樱", "春之樱")):
                dashboard.same_region_name.value = same
                dashboard.cross_region_name.value = cross
                self.assertIsNone(dashboard._read_settings_from_fields())
                self.assertTrue(dashboard.same_region_name.error_text or dashboard.cross_region_name.error_text)
            dashboard.same_region_name.value = " 春之樱 "
            dashboard.cross_region_name.value = " 夏之蝉 "
            dashboard._selected_mumu = lambda: {"index": "0", "adb_port": "127.0.0.1:16384"}
            with patch.object(settings_page, "save_ui_settings", side_effect=lambda data: save_ui_settings(data, path)):
                self.assertTrue(dashboard.save_settings())
            loaded = load_ui_settings(path)
            self.assertEqual(loaded["same_region_name"], "春之樱")
            self.assertEqual(loaded["cross_region_name"], "夏之蝉")
            self.assertIsNone(dashboard.same_region_name.error_text)
            self.assertIsNone(dashboard.cross_region_name.error_text)
            dashboard._set_global_settings_disabled(True)
            self.assertTrue(dashboard.same_region_name.disabled)
            self.assertTrue(dashboard.cross_region_name.disabled)

    def test_missing_or_invalid_names_stay_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ui_settings.json"
            self.assertEqual(
                region_settings.load_region_names(path),
                {"same": "", "cross": ""},
            )
            for content in ('{', '[]', '{}', '{"same_region_name": " ", "cross_region_name": 1}'):
                with self.subTest(content=content):
                    path.write_text(content, encoding="utf-8")
                    self.assertEqual(
                        region_settings.load_region_names(path),
                        {"same": "", "cross": ""},
                    )

    def test_empty_names_cannot_match_ocr_or_start_login(self):
        spec = importlib.util.spec_from_file_location("unconfigured_sign", sign.__file__)
        configured = importlib.util.module_from_spec(spec)
        with patch.object(region_settings, "load_region_names", return_value={"same": "", "cross": ""}):
            spec.loader.exec_module(configured)
        self.assertIsNone(configured.normalize_region(""))
        with (
            patch.object(configured, "_ocr_texts_in_region", return_value=[("任意区名", 0.99)]),
            patch.object(configured.utils, "connect_to_mumu") as connect,
            patch.object(configured, "report_failure") as failure,
            patch.object(configured, "print"),
        ):
            self.assertIsNone(configured._recognize_current_region(object())[0])
            self.assertEqual(configured._recognize_region_cards(object())[0], {})
            for region in ("same", "cross"):
                self.assertFalse(configured.run(region=region))
            connect.assert_not_called()
            self.assertEqual(failure.call_count, 2)

    def test_custom_names_drive_login_normalization_and_ocr(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ui_settings.json"
            path.write_text(json.dumps({
                "same_region_name": " 春之樱 ",
                "cross_region_name": "夏之蝉",
            }), encoding="utf-8")
            names = region_settings.load_region_names(path)
        spec = importlib.util.spec_from_file_location("configured_sign", sign.__file__)
        configured = importlib.util.module_from_spec(spec)
        with patch.object(region_settings, "load_region_names", return_value=names):
            spec.loader.exec_module(configured)
        self.assertEqual(configured.normalize_region("春之樱"), "same")
        self.assertEqual(configured.normalize_region("夏之蝉"), "cross")
        self.assertIsNone(configured.normalize_region("狐之宴"))
        with (
            patch.object(configured, "_ocr_texts_in_region", side_effect=[
                [("夏之蝉", 0.99)], [("春之樱", 0.99)], [("夏之蝉", 0.99)],
            ]),
            patch.object(configured.LOGGER, "match"),
        ):
            self.assertEqual(configured._recognize_current_region(object())[0], "cross")
            self.assertEqual(configured._recognize_region_cards(object())[0], {
                "left": "same", "right": "cross",
            })


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import importlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import main
import ui
from controller import scheduler, state_store, task_services
from ui_app.dashboard import AssistantDashboard
from ui_app.settings_store import load_ui_settings, save_ui_settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ControllerCompatibilityTests(unittest.TestCase):
    def test_root_main_reexports_controller_api(self):
        required = {
            "ControllerServices",
            "TaskWork",
            "WorkItem",
            "build_services",
            "build_work_queue",
            "build_weekly_work_queue",
            "load_state",
            "save_state",
            "load_weekly_state",
            "save_weekly_state",
            "run",
            "run_weekly",
            "_empty_system_state",
        }
        self.assertTrue(required.issubset(vars(main)))
        self.assertIs(main.load_state, state_store.load_state)
        self.assertIs(main.build_work_queue, scheduler.build_work_queue)
        self.assertIs(main.build_services, task_services.build_services)

    def test_controller_modules_import_independently(self):
        modules = (
            "controller.constants",
            "controller.types",
            "controller.state_store",
            "controller.scheduler",
            "controller.task_services",
            "controller.daily_runner",
            "controller.weekly_runner",
        )
        for name in modules:
            self.assertIsNotNone(importlib.import_module(name))

    def test_root_main_is_only_a_compatibility_entrypoint(self):
        self.assertLessEqual(len((PROJECT_ROOT / "main.py").read_text(encoding="utf-8").splitlines()), 30)


class UiCompatibilityTests(unittest.TestCase):
    def test_root_ui_reexports_existing_entrypoints(self):
        self.assertIs(ui.AssistantDashboard, AssistantDashboard)
        self.assertIs(ui.load_ui_settings, load_ui_settings)
        self.assertIs(ui.save_ui_settings, save_ui_settings)
        self.assertTrue(callable(ui.main))

    def test_settings_store_still_writes_and_loads_atomically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ui_settings.json"
            settings = dict(ui.DEFAULT_SETTINGS)
            settings["error_screenshot_keep_count"] = 9
            save_ui_settings(settings, path)
            self.assertEqual(load_ui_settings(path)["error_screenshot_keep_count"], 9)

    def test_ui_page_modules_import_independently(self):
        modules = (
            "ui_app.components",
            "ui_app.runtime",
            "ui_app.pages.layout",
            "ui_app.pages.daily",
            "ui_app.pages.tools",
            "ui_app.pages.settings",
            "ui_app.pages.theme",
            "ui_app.dashboard",
        )
        for name in modules:
            self.assertIsNotNone(importlib.import_module(name))

    def test_dashboard_can_build_with_page_mixins(self):
        class FakePage:
            def __init__(self):
                self.window = SimpleNamespace(
                    width=None,
                    height=None,
                    min_width=None,
                    min_height=None,
                )
                self.services = []
                self.controls = []

            def add(self, *controls):
                self.controls.extend(controls)

            def run_task(self, *_args, **_kwargs):
                return None

            def update(self):
                return None

        page = FakePage()
        with patch(
            "ui_app.dashboard.discover_running_mumu_instances",
            return_value=[],
        ):
            dashboard = AssistantDashboard(page)
        self.assertEqual(len(page.controls), 1)
        self.assertTrue(dashboard.cards)

    def test_root_ui_is_only_a_compatibility_entrypoint(self):
        self.assertLessEqual(len((PROJECT_ROOT / "ui.py").read_text(encoding="utf-8").splitlines()), 25)


class OcrModelPathTests(unittest.TestCase):
    def test_models_directory_was_renamed_without_losing_models(self):
        models = PROJECT_ROOT / "models"
        self.assertTrue(models.is_dir())
        self.assertFalse((PROJECT_ROOT / ("mod" + "le")).exists())
        expected = {
            "ch_PP-OCRv4_det_infer",
            "ch_PP-OCRv4_rec_infer",
            "ch_ppocr_mobile_v2.0_cls_infer",
        }
        self.assertTrue(expected.issubset({path.name for path in models.iterdir()}))

    def test_source_files_do_not_reference_old_model_directory(self):
        old_name = "mod" + "le"
        for base in (PROJECT_ROOT / "module", PROJECT_ROOT / "tasks"):
            for path in base.rglob("*.py"):
                self.assertNotIn(old_name, path.read_text(encoding="utf-8"), path)


if __name__ == "__main__":
    unittest.main()

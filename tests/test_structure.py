from __future__ import annotations

import unittest
import importlib
import inspect
import ast
import re
from pathlib import Path

import main
from module.base.assets import ClickAsset, ImageAsset
from module.base.device import TaskDevice


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _Backend:
    def __init__(self):
        self.clicked = None
        self.swiped = None

    def take_screenshot(self):
        return "frame"

    def adb_click(self, x, y):
        self.clicked = (x, y)
        return True

    def adb_swipe(self, start_x, start_y, end_x, end_y, duration_ms=800):
        self.swiped = (start_x, start_y, end_x, end_y, duration_ms)
        return True


class DeviceFacadeTests(unittest.TestCase):
    def test_screenshot_click_and_swipe_delegate_to_backend(self):
        backend = _Backend()
        device = TaskDevice(backend)

        self.assertEqual(device.screenshot(), "frame")
        self.assertTrue(device.click(12, 34))
        self.assertEqual(backend.clicked, (12, 34))
        self.assertTrue(device.swipe(1, 2, 3, 4, duration_ms=900))
        self.assertEqual(backend.swiped, (1, 2, 3, 4, 900))


class ProjectStructureTests(unittest.TestCase):
    def test_all_controller_modules_exist_in_new_structure(self):
        for path in main.MODULE_PATHS.values():
            self.assertTrue(path.is_file(), path)
            self.assertTrue({"module", "tasks"}.intersection(path.parts), path)

    def test_task_device_owns_low_level_screenshot_and_click_calls(self):
        forbidden = (
            "utils.take_screenshot(",
            "utils.crop_and_match(",
            "utils.adb_click(",
            "utils.adb_swipe(",
            "utils.adb_keyevent(",
            "utils.adb_back(",
        )
        for path in (PROJECT_ROOT / "tasks").rglob("*.py"):
            if path.name == "assets.py":
                continue
            source = path.read_text(encoding="utf-8")
            for call in forbidden:
                self.assertNotIn(call, source, f"{path}: {call}")

    def test_each_task_package_has_assets_module(self):
        task_files = {
            path.parent
            for path in (PROJECT_ROOT / "tasks").rglob("*.py")
            if path.name not in {"__init__.py", "assets.py"}
        }
        for task_dir in task_files:
            self.assertTrue((task_dir / "assets.py").is_file(), task_dir)

    def test_asset_classes_build_typed_image_rules(self):
        for path in (PROJECT_ROOT / "tasks").rglob("assets.py"):
            module_name = ".".join(path.relative_to(PROJECT_ROOT).with_suffix("").parts)
            assets_module = importlib.import_module(module_name)
            for _, cls in inspect.getmembers(assets_module, inspect.isclass):
                if cls.__module__ != module_name or not cls.__name__.endswith("Assets"):
                    continue
                templates = getattr(cls, "TEMPLATES", None)
                if templates:
                    self.assertTrue(cls.IMAGES, cls)

    def test_task_png_files_live_only_in_res_directories(self):
        for path in (PROJECT_ROOT / "tasks").rglob("*.png"):
            self.assertIn("res", path.relative_to(PROJECT_ROOT).parts, path)

    def test_all_declared_resources_exist_and_have_stable_names(self):
        asset_modules = [PROJECT_ROOT / "module" / "assets.py"]
        asset_modules.extend((PROJECT_ROOT / "tasks").rglob("assets.py"))
        for path in asset_modules:
            module_name = ".".join(path.relative_to(PROJECT_ROOT).with_suffix("").parts)
            assets_module = importlib.import_module(module_name)
            for _, cls in inspect.getmembers(assets_module, inspect.isclass):
                if cls.__module__ != module_name or not cls.__name__.endswith("Assets"):
                    continue
                for attr_name, asset in vars(cls).items():
                    if attr_name.startswith("I_") and isinstance(asset, ImageAsset):
                        self.assertTrue(asset.file.is_file(), asset.file)
                        self.assertRegex(asset.name, r"^[a-z0-9_]+$")
                    if attr_name.startswith("C_") and isinstance(asset, ClickAsset):
                        self.assertRegex(asset.name, r"^[a-z0-9_]+$")

    def test_every_resource_constant_has_a_chinese_comment(self):
        asset_modules = [PROJECT_ROOT / "module" / "assets.py"]
        asset_modules.extend((PROJECT_ROOT / "tasks").rglob("assets.py"))
        for path in asset_modules:
            source = path.read_text(encoding="utf-8")
            lines = source.splitlines()
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names = [target.id for target in targets if isinstance(target, ast.Name)]
                if not any(name.startswith(("I_", "C_")) for name in names):
                    continue
                previous = lines[node.lineno - 2].strip() if node.lineno > 1 else ""
                self.assertTrue(previous.startswith("#"), f"{path}:{node.lineno}")
                self.assertIsNotNone(
                    re.search(r"[\u4e00-\u9fff]", previous),
                    f"{path}:{node.lineno}",
                )


if __name__ == "__main__":
    unittest.main()

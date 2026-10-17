from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import flet as ft

from ui_app.dashboard import AssistantDashboard
from ui_app.window_layout import CANVAS_HEIGHT, CANVAS_WIDTH, fit_canvas, fit_window


class WindowScalingTests(unittest.TestCase):
    def test_initial_window_fits_work_area_at_different_resolutions_and_dpi(self):
        for physical_width, physical_height, dpi in (
            (1366, 728, 1), (1920, 1032, 1), (1920, 1032, 1.25),
            (1920, 1032, 1.5), (3840, 2080, 2),
        ):
            with self.subTest(screen=(physical_width, physical_height), dpi=dpi):
                width, height = fit_window((physical_width / dpi, physical_height / dpi))
                self.assertLessEqual(width * dpi, physical_width * 0.9 + 0.001)
                self.assertLessEqual(height * dpi, physical_height * 0.9 + 0.001)
                self.assertAlmostEqual(width / height, 1350 / 860)
        self.assertEqual(fit_window(None), (1350, 860))

    def test_canvas_keeps_proportions_and_centers_at_any_viewport(self):
        for width, height in ((1334, 821), (996, 606), (1920, 1032), (700, 1000)):
            with self.subTest(viewport=(width, height)):
                scale, left, top = fit_canvas(width, height)
                self.assertGreater(scale, 0)
                self.assertGreaterEqual(left, -0.001)
                self.assertGreaterEqual(top, -0.001)
                self.assertAlmostEqual(left * 2 + CANVAS_WIDTH * scale, width)
                self.assertAlmostEqual(top * 2 + CANVAS_HEIGHT * scale, height)
                self.assertTrue(abs(left) < 0.001 or abs(top) < 0.001)
        for width, height in ((0, 0), (-1, 500), (float("nan"), 500), (500, float("inf"))):
            self.assertIsNone(fit_canvas(width, height))

    def test_monitor_changes_clamp_normal_window_and_preserve_maximized_window(self):
        dashboard = object.__new__(AssistantDashboard)
        dashboard.page = SimpleNamespace(title="MoYomi", window=ft.Window())
        dashboard._safe_update = Mock()
        with patch("ui_app.pages.layout.windows_work_area", return_value=(1920, 1032)):
            dashboard._configure_window()
        self.assertAlmostEqual(dashboard.page.window.aspect_ratio, 1350 / 860)
        self.assertTrue(dashboard.page.window.maximizable)
        with patch("ui_app.pages.layout.windows_work_area", return_value=(1280, 688)):
            dashboard._fit_window_to_screen()
            width, height = dashboard.page.window.width, dashboard.page.window.height
            self.assertLess(height, 688)
            self.assertLessEqual(dashboard.page.window.min_height, height)
            dashboard.page.window.width = width - 20
            dashboard._fit_window_to_screen()
            self.assertEqual(dashboard.page.window.width, width - 20)
        dashboard.page.window.maximized = True
        with patch("ui_app.pages.layout.windows_work_area", return_value=(1000, 600)):
            dashboard._fit_window_to_screen()
        self.assertEqual(dashboard.page.window.width, width - 20)

    def test_scaling_preserves_hit_testing_and_does_not_change_design_size(self):
        dashboard = object.__new__(AssistantDashboard)
        dashboard.page = SimpleNamespace(title="MoYomi")
        dashboard._window_work_area = None
        dashboard._layout_surface = ft.Container(width=CANVAS_WIDTH, height=CANVAS_HEIGHT)
        dashboard._safe_update = Mock()
        with patch("ui_app.pages.layout.windows_work_area", return_value=None):
            dashboard._on_viewport_size_change(SimpleNamespace(width=996, height=606))
        surface = dashboard._layout_surface
        self.assertEqual((surface.width, surface.height), (CANVAS_WIDTH, CANVAS_HEIGHT))
        self.assertTrue(surface.scale.transform_hit_tests)
        self.assertIsNone(surface.scale.scale_x)
        self.assertIsNone(surface.scale.scale_y)
        self.assertAlmostEqual(surface.scale.scale, 606 / CANVAS_HEIGHT)


if __name__ == "__main__":
    unittest.main()

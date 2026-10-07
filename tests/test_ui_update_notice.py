from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import flet as ft

from module import updater
from ui_app.dashboard import AssistantDashboard


class UpdateNoticeTests(unittest.IsolatedAsyncioTestCase):
    def test_selected_mumu_port_appears_in_window_title(self):
        dashboard = object.__new__(AssistantDashboard)
        dashboard.page = SimpleNamespace(title="")
        dashboard.mumu_instances = [
            {"index": "0", "adb_port": "127.0.0.1:16384"}
        ]
        dashboard.mumu_instance = ft.Dropdown(value="0")
        dashboard.mumu_status = ft.Text()

        dashboard._update_mumu_status()

        self.assertIn("16384", dashboard.page.title)

    async def test_startup_update_stays_in_header_until_clicked(self):
        dashboard = object.__new__(AssistantDashboard)
        dashboard.page = SimpleNamespace(show_dialog=Mock())
        dashboard.running = False
        dashboard.tool_running = False
        dashboard.available_update = None
        dashboard.update_check_button = ft.Button()
        dashboard.update_status = ft.Text()
        dashboard.update_notice = ft.TextButton(visible=False)
        dashboard.update_dialog_title = ft.Text()
        dashboard.update_dialog_notes = ft.Text()
        dashboard.update_dialog_message = ft.Text()
        dashboard.update_progress = ft.ProgressRing()
        dashboard.update_install_button = ft.Button()
        dashboard.update_dialog = ft.AlertDialog()
        dashboard._safe_update = Mock()
        release = updater.ReleaseInfo(
            version="1.2.3",
            tag_name="v1.2.3",
            name="v1.2.3",
            notes="更新说明",
            page_url="https://github.com/momoying/MoYomi/releases/tag/v1.2.3",
            ota_url="",
            full_url="",
        )

        with patch.object(updater, "check_for_update", return_value=release):
            await dashboard._check_for_updates(silent=True)

        self.assertTrue(dashboard.update_notice.visible)
        self.assertIn("1.2.3", dashboard.update_notice.content)
        dashboard.page.show_dialog.assert_not_called()
        dashboard.show_available_update()
        dashboard.page.show_dialog.assert_called_once_with(dashboard.update_dialog)


if __name__ == "__main__":
    unittest.main()

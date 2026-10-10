from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import flet as ft

import main as controller
from controller.state_store import _empty_system_state
from ui_app.components import AccountCardView
from ui_app.pages.daily import DailyPageMixin


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 8, 12, 10, tzinfo=TZ)  # 周三


def state_with_accounts(*names: str) -> dict:
    return {
        "version": controller.STATUS_VERSION,
        "accounts": {
            name: {"systems": {"IOS": _empty_system_state()}}
            for name in names
        },
    }


class ManualDetectionTests(unittest.TestCase):
    def test_bounty_regions_are_independent_and_reset_returns_to_queue(self):
        state = state_with_accounts("角色一")
        role = state["accounts"]["角色一"]["systems"]["IOS"]
        role["cross_region_enabled"] = True

        controller.set_manual_detection_result(
            state, "角色一", "IOS", controller.BOUNTY_TASK,
            "sharing_magatama_collaboration", NOW,
        )
        self.assertFalse(controller.bounty_is_due(role, NOW))
        self.assertTrue(controller.bounty_is_due(role, NOW, controller.CROSS_REGION))

        controller.set_manual_detection_result(
            state, "角色一", "IOS", controller.BOUNTY_TASK,
            "normal_magatama_collaboration", NOW,
            region=controller.CROSS_REGION,
        )
        self.assertEqual(controller.combined_task_runs_due(controller.BOUNTY_TASK, role, NOW), 0)
        self.assertTrue(controller.bounty_is_due(role, NOW.replace(hour=18)))
        self.assertTrue(controller.bounty_is_due(role, NOW.replace(hour=18), controller.CROSS_REGION))

        controller.set_manual_detection_result(
            state, "角色一", "IOS", controller.BOUNTY_TASK, None, NOW,
            region=controller.CROSS_REGION,
        )
        self.assertFalse(controller.bounty_is_due(role, NOW))
        self.assertTrue(controller.bounty_is_due(role, NOW, controller.CROSS_REGION))
        self.assertEqual(
            controller.task_record_result(role, controller.BOUNTY_TASK),
            "sharing_magatama_collaboration",
        )

    def test_merchant_50_skips_others_and_last_50_reset_restores_them(self):
        state = state_with_accounts("甲", "乙", "丙")
        roles = {
            name: account["systems"]["IOS"]
            for name, account in state["accounts"].items()
        }

        controller.set_manual_detection_result(
            state, "甲", "IOS", controller.MERCHANT_TASK, "blue_ticket_50", NOW
        )
        self.assertFalse(controller.task_is_due(controller.MERCHANT_TASK, roles["甲"], NOW))
        for name in ("乙", "丙"):
            self.assertEqual(
                controller.task_record_result(roles[name], controller.MERCHANT_TASK),
                controller.MERCHANT_SKIPPED_RESULT,
            )

        controller.set_manual_detection_result(
            state, "乙", "IOS", controller.MERCHANT_TASK, "blue_ticket_50", NOW
        )
        controller.set_manual_detection_result(
            state, "甲", "IOS", controller.MERCHANT_TASK, None, NOW
        )
        self.assertEqual(
            controller.task_record_result(roles["丙"], controller.MERCHANT_TASK),
            controller.MERCHANT_SKIPPED_RESULT,
        )
        controller.set_manual_detection_result(
            state, "乙", "IOS", controller.MERCHANT_TASK, "blue_ticket_60", NOW
        )
        self.assertTrue(controller.task_is_due(controller.MERCHANT_TASK, roles["甲"], NOW))
        self.assertFalse(controller.task_is_due(controller.MERCHANT_TASK, roles["乙"], NOW))
        self.assertTrue(controller.task_is_due(controller.MERCHANT_TASK, roles["丙"], NOW))
        self.assertIsNone(controller.task_record_result(roles["丙"], controller.MERCHANT_TASK))
        self.assertTrue(
            controller.task_is_due(
                controller.MERCHANT_TASK, roles["乙"], NOW + timedelta(days=3)
            )
        )

    def test_dialog_choice_persists_and_reload_updates_card(self):
        state = state_with_accounts("角色一")
        role = state["accounts"]["角色一"]["systems"]["IOS"]
        role["cross_region_enabled"] = True
        dashboard = DailyPageMixin()
        dashboard.running = False
        dashboard.task_mode = controller.DAILY_MODE
        dashboard.refresh_cards = Mock(return_value=True)
        dashboard.append_log = Mock()
        dashboard.page = SimpleNamespace(show_dialog=Mock(), pop_dialog=Mock())
        card = AccountCardView(
            "角色一", "IOS", role, NOW,
            on_detection_open=dashboard._show_detection_dialog,
        )
        bounty_tile = card.task_views[controller.BOUNTY_TASK].control
        merchant_tile = card.task_views[controller.MERCHANT_TASK].control
        self.assertIsInstance(bounty_tile, ft.GestureDetector)
        self.assertIsInstance(merchant_tile, ft.GestureDetector)
        self.assertEqual(bounty_tile.col, 6)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "account_status.json"
            controller.save_state(state, path)
            with patch.object(controller, "STATUS_PATH", path), patch(
                "ui_app.pages.daily.datetime"
            ) as fake_datetime:
                fake_datetime.now.return_value = NOW
                bounty_tile.on_secondary_tap(None)
                self.assertIsNotNone(
                    dashboard.page.show_dialog.call_args,
                    dashboard.append_log.call_args_list,
                )
                dialog = dashboard.page.show_dialog.call_args.args[0]
                self.assertFalse(dialog.modal)
                self.assertEqual(dialog.actions, [])
                panels = dialog.content.controls
                self.assertEqual(len(panels), 2)
                self.assertEqual(
                    [panel.content.controls[0].value for panel in panels],
                    ["狐之宴", "砂狐乐园"],
                )
                self.assertEqual(len(panels[0].content.controls), 5)
                panels[0].content.controls[2].on_click(None)  # 同区现世勾协

                bounty_tile.on_secondary_tap(None)
                dialog = dashboard.page.show_dialog.call_args.args[0]
                dialog.content.controls[1].content.controls[3].on_click(None)

                merchant_tile.on_secondary_tap(None)
                dialog = dashboard.page.show_dialog.call_args.args[0]
                self.assertFalse(dialog.modal)
                self.assertEqual(dialog.actions, [])
                price_row = dialog.content.content.controls[1]
                self.assertEqual(len(price_row.controls), 5)
                price_row.controls[0].on_click(None)  # 50 蓝票

            loaded, _ = controller.load_state(path)
            saved_role = loaded["accounts"]["角色一"]["systems"]["IOS"]
            self.assertEqual(
                controller.task_record_result(saved_role, controller.BOUNTY_TASK),
                "sharing_magatama_collaboration",
            )
            self.assertEqual(
                controller.task_record_result(
                    saved_role, controller.BOUNTY_TASK, controller.CROSS_REGION
                ),
                "no_magatama_collaboration",
            )
            updated = AccountCardView("角色一", "IOS", saved_role, NOW)
            self.assertIn("现世勾（同）", updated.important_result_labels())
            self.assertIn("发现50蓝票", updated.important_result_labels())
            self.assertEqual(dashboard.refresh_cards.call_count, 3)
            self.assertEqual(dashboard.page.pop_dialog.call_count, 3)

    def test_save_failure_does_not_refresh_cards(self):
        dashboard = SimpleNamespace(
            running=False,
            task_mode=controller.DAILY_MODE,
            refresh_cards=Mock(),
            append_log=Mock(),
        )
        state = state_with_accounts("角色一")
        with patch.object(controller, "load_state", return_value=(state, False)), patch.object(
            controller, "save_state", side_effect=OSError("disk full")
        ):
            DailyPageMixin._set_manual_detection_result(
                dashboard, "角色一", "IOS", controller.BOUNTY_TASK,
                controller.SAME_REGION, "normal_magatama_collaboration"
            )
        dashboard.refresh_cards.assert_not_called()
        self.assertIn("disk full", dashboard.append_log.call_args.args[1])

    def test_running_controller_rejects_manual_change(self):
        dashboard = SimpleNamespace(
            running=True,
            task_mode=controller.DAILY_MODE,
            refresh_cards=Mock(),
            append_log=Mock(),
        )
        with patch.object(controller, "load_state") as load_state:
            DailyPageMixin._set_manual_detection_result(
                dashboard, "角色一", "IOS", controller.BOUNTY_TASK,
                controller.SAME_REGION, "normal_magatama_collaboration"
            )
        load_state.assert_not_called()
        dashboard.refresh_cards.assert_not_called()


if __name__ == "__main__":
    unittest.main()

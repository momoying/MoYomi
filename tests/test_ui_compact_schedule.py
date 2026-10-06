from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import main as controller
from controller import state_store
from ui_app.components import AccountCardView
from ui_app.constants import DEFAULT_SETTINGS
from ui_app.dashboard import AssistantDashboard
from ui_app.pages.daily import parse_one_shot_run_at
from ui_app.settings_store import load_ui_settings


TZ = timezone(timedelta(hours=8))


class AccountCardResultTests(unittest.TestCase):
    def test_card_keeps_original_full_three_column_layout(self):
        now = datetime(2026, 8, 12, 10, 0, tzinfo=TZ)  # 周三
        card = AccountCardView("角色一", "IOS", state_store._empty_system_state(), now)

        self.assertTrue(card.task_grid.visible)
        self.assertEqual(card.control.col["md"], 4)
        self.assertTrue(
            all(control.col == 6 for control in card.task_grid.controls)
        )

    def test_merchant_badge_is_hidden_outside_merchant_day(self):
        friday = datetime(2026, 8, 14, 10, 0, tzinfo=TZ)
        wednesday = datetime(2026, 8, 12, 10, 0, tzinfo=TZ)
        state = state_store._empty_system_state()

        friday_card = AccountCardView("角色一", "IOS", state, friday)
        wednesday_card = AccountCardView("角色一", "IOS", state, wednesday)

        self.assertFalse(
            friday_card.task_views[controller.MERCHANT_TASK].control.visible
        )
        self.assertTrue(
            wednesday_card.task_views[controller.MERCHANT_TASK].control.visible
        )

    def test_key_findings_remain_available_on_compact_card(self):
        now = datetime(2026, 8, 12, 10, 0, tzinfo=TZ)
        state = state_store._empty_system_state()
        state_store.record_task_completion(
            controller.BOUNTY_TASK,
            state,
            now,
            region=controller.SAME_REGION,
        )
        state_store.set_task_record_result(
            state,
            controller.BOUNTY_TASK,
            "sharing_magatama_collaboration",
            region=controller.SAME_REGION,
        )
        state_store.record_task_completion(controller.MERCHANT_TASK, state, now)
        state_store.set_task_record_result(
            state,
            controller.MERCHANT_TASK,
            "blue_ticket_50",
        )

        card = AccountCardView("角色一", "IOS", state, now)

        self.assertIn("现世勾协", card.important_result_labels())
        self.assertIn("发现50蓝票", card.important_result_labels())

    def test_unknown_merchant_price_is_shown_on_compact_card(self):
        now = datetime(2026, 8, 12, 10, 0, tzinfo=TZ)
        state = state_store._empty_system_state()
        state_store.record_task_completion(controller.MERCHANT_TASK, state, now)
        state_store.set_task_record_result(state, controller.MERCHANT_TASK, "unknown_price")

        card = AccountCardView("角色一", "IOS", state, now)

        merchant_view = card.task_views[controller.MERCHANT_TASK]
        self.assertEqual(merchant_view.status, "done")
        self.assertEqual(merchant_view.detail.value, "蓝票价格未知")


class OneShotAlarmTests(unittest.TestCase):
    def test_alarm_parses_exact_date_and_minute(self):
        now = datetime(2026, 8, 15, 5, 20, 30, tzinfo=TZ)

        candidate = parse_one_shot_run_at("2026-08-15", "05:30", now)

        self.assertEqual(candidate, datetime(2026, 8, 15, 5, 30, tzinfo=TZ))

    def test_current_minute_is_allowed_for_immediate_trigger(self):
        now = datetime(2026, 8, 12, 5, 30, 30, tzinfo=TZ)

        candidate = parse_one_shot_run_at("2026-08-12", "05:30", now)

        self.assertEqual(candidate, datetime(2026, 8, 12, 5, 30, tzinfo=TZ))

    def test_past_alarm_is_rejected(self):
        now = datetime(2026, 8, 15, 5, 31, tzinfo=TZ)

        with self.assertRaisesRegex(ValueError, "不能早于当前分钟"):
            parse_one_shot_run_at("2026-08-15", "05:30", now)

    def test_alarm_is_not_part_of_persistent_settings(self):
        self.assertFalse(
            any(key.startswith("scheduled_run_") for key in DEFAULT_SETTINGS)
        )

    def test_legacy_saved_schedule_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ui_settings.json"
            path.write_text(
                '{"scheduled_run_enabled": true, "scheduled_run_time": "05:30"}',
                encoding="utf-8",
            )

            loaded = load_ui_settings(path)

        self.assertFalse(
            any(key.startswith("scheduled_run_") for key in loaded)
        )


class OneShotAlarmRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_busy_alarm_is_cleared_without_persistence_or_retry(self):
        dashboard = AssistantDashboard.__new__(AssistantDashboard)
        dashboard._scheduled_run_at = datetime.now().astimezone()
        dashboard._scheduled_run_mode = controller.DAILY_MODE
        dashboard.running = True
        dashboard.tool_running = False
        dashboard.schedule_button = SimpleNamespace(
            content=None,
            bgcolor=None,
            color=None,
            tooltip=None,
        )
        logs = []
        dashboard.append_log = lambda level, message: logs.append((level, message))
        dashboard._safe_update = lambda: None

        sleep_calls = 0

        async def stop_after_trigger(_seconds):
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls >= 2:
                raise asyncio.CancelledError

        with patch("ui_app.pages.daily.asyncio.sleep", side_effect=stop_after_trigger):
            await dashboard._schedule_pump()

        self.assertIsNone(dashboard._scheduled_run_at)
        self.assertTrue(any("本次已取消" in message for _, message in logs))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import flet as ft
import main as controller
from controller import state_store
from ui_app.components import AccountCardView
from ui_app.constants import COLORS, DEFAULT_SETTINGS
from ui_app.dashboard import AssistantDashboard
from ui_app.pages.daily import DailyPageMixin, _task_availability, parse_one_shot_run_at
from ui_app.settings_store import load_ui_settings


TZ = timezone(timedelta(hours=8))


class AccountCardResultTests(unittest.TestCase):
    def test_overall_status_distinguishes_completed_unavailable_and_mixed(self):
        now = datetime(2026, 8, 14, 10, 0, tzinfo=TZ)
        card = AccountCardView("角色一", "IOS", state_store._empty_system_state(), now)

        for view in card.task_views.values():
            view.set_status("done", "已完成")
        card.refresh_overall()
        self.assertEqual(card.status_text.value, "当前任务全部完成")
        self.assertEqual(card.status_text.color, COLORS["done"])

        for view in card.task_views.values():
            view.set_status("disabled", "已禁用")
        card.refresh_overall()
        self.assertEqual(card.status_text.value, "当前无可执行任务")
        self.assertEqual(card.status_text.color, COLORS["muted"])

        next(iter(card.task_views.values())).set_status("done", "已完成")
        card.refresh_overall()
        self.assertEqual(card.status_text.value, "当前无待执行任务")
        self.assertEqual(card.status_text.color, COLORS["muted"])

    def test_empty_card_collapses_and_restores_with_visibility_switch(self):
        state = state_store._empty_system_state()
        state["task_enabled"] = {name: False for name in controller.TASK_ORDER}
        card = AccountCardView("角色一", "IOS", state, datetime(2026, 8, 14, 10, tzinfo=TZ))
        page = SimpleNamespace(
            cards={("角色一", "IOS"): card},
            single_task_mode=False,
            show_important_only=False,
            hide_unavailable_tasks=SimpleNamespace(value=True),
        )

        DailyPageMixin._apply_task_visibility(page)
        self.assertTrue(card.control.visible)
        self.assertFalse(card.task_grid.visible)
        self.assertFalse(card.task_divider.visible)
        self.assertEqual(card.status_text.value, "当前无可执行任务")

        page.hide_unavailable_tasks.value = False
        DailyPageMixin._apply_task_visibility(page)
        self.assertTrue(card.task_grid.visible)
        self.assertTrue(card.task_divider.visible)

    def test_card_keeps_original_three_column_layout_and_all_nine_tasks(self):
        now = datetime(2026, 8, 12, 10, 0, tzinfo=TZ)  # 周三
        card = AccountCardView("角色一", "IOS", state_store._empty_system_state(), now)

        self.assertTrue(card.task_grid.visible)
        self.assertEqual(card.control.col["md"], 4)
        self.assertEqual(len(card.task_views), 9)
        self.assertTrue(
            all(control.col == 6 for control in card.task_grid.controls)
        )

    def test_daily_layout_and_shared_navigation_build_with_flet_controls(self):
        dashboard = AssistantDashboard.__new__(AssistantDashboard)
        dashboard.single_task_mode = False
        dashboard.single_task_selector = ft.Dropdown()
        dashboard.task_mode_selector = ft.SegmentedButton(
            segments=[ft.Segment(value="daily", label="日常")], selected=["daily"]
        )
        dashboard.hide_unavailable_tasks = ft.Switch()
        dashboard.single_task_mode_switch = ft.Switch()
        dashboard.important_summary_text = ft.Text()
        dashboard.important_filter_button = ft.Button(content="只看有结果")
        dashboard.cards_grid = ft.ResponsiveRow()
        dashboard.summary_text = ft.Text()
        dashboard.refresh_button = ft.IconButton(icon=ft.Icons.REFRESH_ROUNDED)
        dashboard.schedule_button = ft.IconButton(icon=ft.Icons.SCHEDULE_ROUNDED)
        dashboard.start_button = ft.Button(content="开始")
        dashboard.log_view = ft.ListView()
        dashboard.nav_items = {}
        dashboard.active_section = "daily"

        body = dashboard._build_daily_page()
        navigation = dashboard._build_navigation()
        dashboard._apply_navigation_style()

        self.assertEqual(body.controls[1].width, 410)
        self.assertEqual(len(navigation.content.controls), 3)
        self.assertEqual(navigation.bgcolor, "#E6111827")
        self.assertEqual(
            dashboard.nav_items["daily"].content.color,
            COLORS["active"],
        )

    def test_important_results_use_compact_chips_with_rare_results_emphasized(self):
        now = datetime(2026, 8, 12, 10, 0, tzinfo=TZ)
        state = state_store._empty_system_state()
        state_store.record_task_completion(
            controller.BOUNTY_TASK, state, now, region=controller.SAME_REGION
        )
        state_store.set_task_record_result(
            state, controller.BOUNTY_TASK, "sharing_magatama_collaboration",
            region=controller.SAME_REGION,
        )
        state_store.record_task_completion(controller.MERCHANT_TASK, state, now)
        state_store.set_task_record_result(state, controller.MERCHANT_TASK, "blue_ticket_50")
        card = AccountCardView("角色一", "IOS", state, now)
        page = SimpleNamespace(
            cards={("角色一", "IOS"): card},
            single_task_mode=False,
            single_task_name=None,
            single_task_selector=SimpleNamespace(options=[]),
            task_mode=controller.DAILY_MODE,
            important_results_bar=ft.Container(),
            important_summary_text=ft.Text(),
            important_results_chips=ft.Row(),
            important_filter_button=ft.Button(),
            summary_text=ft.Text(),
            show_important_only=False,
        )

        DailyPageMixin._refresh_task_summary(page)

        self.assertFalse(page.important_summary_text.visible)
        self.assertEqual(len(page.important_results_chips.controls), 2)
        self.assertEqual(
            [chip.content.value for chip in page.important_results_chips.controls],
            ["现世勾协", "发现50蓝票"],
        )
        self.assertTrue(
            all(
                chip.bgcolor == COLORS["warning_bg"]
                for chip in page.important_results_chips.controls
            )
        )

    def test_merchant_follows_unavailable_visibility_setting(self):
        friday = datetime(2026, 8, 14, 10, 0, tzinfo=TZ)
        wednesday = datetime(2026, 8, 12, 10, 0, tzinfo=TZ)
        state = state_store._empty_system_state()

        friday_card = AccountCardView("角色一", "IOS", state, friday)
        wednesday_card = AccountCardView("角色一", "IOS", state, wednesday)
        merchant = friday_card.task_views[controller.MERCHANT_TASK]
        kirin = friday_card.task_views[controller.GUILD_KIRIN_TASK]
        self.assertEqual(merchant.status, "unavailable")
        self.assertEqual(merchant.detail.value, "今日未开放")
        self.assertTrue(merchant.control.visible)
        self.assertTrue(kirin.control.visible)
        self.assertTrue(
            wednesday_card.task_views[controller.MERCHANT_TASK].control.visible
        )

        page = SimpleNamespace(
            cards={("角色一", "IOS"): friday_card},
            single_task_mode=False,
            show_important_only=False,
            hide_unavailable_tasks=SimpleNamespace(value=True),
        )
        DailyPageMixin._apply_task_visibility(page)
        self.assertFalse(merchant.control.visible)
        self.assertFalse(kirin.control.visible)

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
    def test_availability_signature_changes_at_merchant_and_kirin_boundaries(self):
        self.assertEqual(
            _task_availability(datetime(2026, 8, 12, 5, 59, tzinfo=TZ)),
            (True, False),
        )
        self.assertEqual(
            _task_availability(datetime(2026, 8, 12, 6, 0, tzinfo=TZ)),
            (True, True),
        )
        self.assertEqual(
            _task_availability(datetime(2026, 8, 12, 23, 0, tzinfo=TZ)),
            (True, False),
        )
        self.assertEqual(
            _task_availability(datetime(2026, 8, 14, 23, 59, tzinfo=TZ)),
            (False, False),
        )
        self.assertEqual(
            _task_availability(datetime(2026, 8, 15, 0, 0, tzinfo=TZ)),
            (True, False),
        )

    async def test_availability_change_refreshes_after_run_finishes(self):
        dashboard = AssistantDashboard.__new__(AssistantDashboard)
        dashboard.task_mode = controller.DAILY_MODE
        dashboard.running = True
        dashboard._last_task_availability = (True, False)
        dashboard._scheduled_run_at = None
        refreshed = []
        dashboard.refresh_cards = lambda: refreshed.append(True) or True
        now = datetime(2026, 8, 12, 6, 0, tzinfo=TZ)
        sleep_calls = 0

        async def advance(_seconds):
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls == 2:
                self.assertEqual(refreshed, [])
                dashboard.running = False
            if sleep_calls == 4:
                raise asyncio.CancelledError

        with patch("ui_app.pages.daily.datetime") as clock, patch(
            "ui_app.pages.daily.asyncio.sleep", side_effect=advance
        ):
            clock.now.return_value = now
            await dashboard._schedule_pump()

        self.assertEqual(refreshed, [True])
        self.assertEqual(dashboard._last_task_availability, (True, True))

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

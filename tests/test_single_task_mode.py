from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from controller import daily_runner, state_store
from controller.constants import (
    BOUNTY_TASK,
    CONSIGNMENT_HOUSE_TASK,
    DAILY_MODE,
    GUILD_KIRIN_TASK,
    MAIL_TASK,
    MERCHANT_TASK,
    STATUS_VERSION,
    TASK_ORDER,
    WEEKLY_MODE,
)
from controller.scheduler import build_single_task_work_queue
from controller.types import ControllerServices
from ui_app.components import AccountCardView
from ui_app.dashboard import AssistantDashboard


NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)


def _state_for_accounts() -> dict:
    accounts = {}
    for account in ("due-one", "due-two", "disabled", "completed"):
        system = state_store._empty_system_state()
        system["task_enabled"] = {name: False for name in TASK_ORDER}
        system["task_enabled"][MAIL_TASK] = account != "disabled"
        if account == "completed":
            state_store.record_task_completion(MAIL_TASK, system, NOW)
        accounts[account] = {"systems": {"IOS": system}}
    return {"version": STATUS_VERSION, "accounts": accounts}


class SingleTaskQueueTests(unittest.TestCase):
    def test_queue_includes_only_enabled_due_targets_and_only_selected_task(self):
        queue = build_single_task_work_queue(_state_for_accounts(), NOW, MAIL_TASK)

        self.assertEqual(
            {(item.account_name, item.system) for item in queue},
            {("due-one", "IOS"), ("due-two", "IOS")},
        )
        self.assertTrue(
            all(
                len(item.tasks) == 1 and item.tasks[0].task_name == MAIL_TASK
                for item in queue
            )
        )

    def test_weekly_mode_accepts_its_existing_single_task(self):
        with patch.object(daily_runner, "run_weekly", return_value=True) as run_weekly:
            self.assertTrue(
                daily_runner.run(
                    task_mode=WEEKLY_MODE,
                    single_task_name=CONSIGNMENT_HOUSE_TASK,
                )
            )
        self.assertEqual(
            run_weekly.call_args.kwargs["single_task_name"],
            CONSIGNMENT_HOUSE_TASK,
        )

    def test_runner_executes_selected_task_once_for_each_eligible_account(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "accounts.json"
            state_store.save_state(_state_for_accounts(), path)
            ran = []
            services = ControllerServices(
                select_account=lambda account, _switch: account,
                exit_to_login=lambda: True,
                sign_in=lambda *_args: True,
                task_runners={MAIL_TASK: lambda: ran.append(MAIL_TASK) or True},
            )
            with patch.object(daily_runner, "maybe_send_detection_summary"):
                result = daily_runner.run(
                    status_path=path,
                    services=services,
                    now_provider=lambda: NOW,
                    single_task_name=MAIL_TASK,
                )

        self.assertTrue(result)
        self.assertEqual(ran, [MAIL_TASK, MAIL_TASK])


class SingleTaskCardTests(unittest.TestCase):
    def test_selector_hides_closed_and_globally_disabled_daily_tasks(self):
        system = state_store._empty_system_state()
        system["task_enabled"] = {name: False for name in TASK_ORDER}
        system["task_enabled"].update({
            MAIL_TASK: True,
            MERCHANT_TASK: True,
            GUILD_KIRIN_TASK: True,
        })
        system["cross_region_enabled"] = True
        state = {"accounts": {"account": {"systems": {"IOS": system}}}}
        dashboard = AssistantDashboard.__new__(AssistantDashboard)
        dashboard.task_mode = DAILY_MODE
        dashboard.single_task_mode = True
        dashboard.single_task_name = MERCHANT_TASK
        dashboard.running = False
        dashboard.single_task_selector = SimpleNamespace(value=MERCHANT_TASK)
        dashboard.start_button = SimpleNamespace(disabled=False)

        dashboard._refresh_single_task_options(
            state, datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
        )

        self.assertEqual(
            [option.key for option in dashboard.single_task_selector.options],
            [MAIL_TASK, BOUNTY_TASK, "liked"],
        )
        self.assertIsNone(dashboard.single_task_name)
        self.assertIsNone(dashboard.single_task_selector.value)
        self.assertTrue(dashboard.start_button.disabled)
        self.assertFalse(dashboard.single_task_selector.disabled)

        dashboard._refresh_single_task_options(state, NOW)
        self.assertIn(
            MERCHANT_TASK,
            [option.key for option in dashboard.single_task_selector.options],
        )

    def test_weekly_selector_keeps_consignment_with_active_account(self):
        dashboard = AssistantDashboard.__new__(AssistantDashboard)
        dashboard.task_mode = WEEKLY_MODE
        dashboard.single_task_mode = True
        dashboard.single_task_name = CONSIGNMENT_HOUSE_TASK
        dashboard.running = False
        dashboard.single_task_selector = SimpleNamespace(value=CONSIGNMENT_HOUSE_TASK)
        dashboard.start_button = SimpleNamespace(disabled=False)

        dashboard._refresh_single_task_options(_state_for_accounts(), NOW)

        self.assertEqual(
            [option.key for option in dashboard.single_task_selector.options],
            [CONSIGNMENT_HOUSE_TASK],
        )
        self.assertEqual(dashboard.single_task_name, CONSIGNMENT_HOUSE_TASK)
        self.assertFalse(dashboard.single_task_selector.disabled)

    def test_empty_selector_explains_why_selection_is_disabled(self):
        system = state_store._empty_system_state()
        system["task_enabled"] = {name: False for name in TASK_ORDER}
        state = {"accounts": {"account": {"systems": {"IOS": system}}}}
        dashboard = AssistantDashboard.__new__(AssistantDashboard)
        dashboard.task_mode = DAILY_MODE
        dashboard.single_task_mode = True
        dashboard.single_task_name = None
        dashboard.running = False
        dashboard.single_task_selector = SimpleNamespace(value=None)
        dashboard.start_button = SimpleNamespace(disabled=False)

        dashboard._refresh_single_task_options(state, NOW)

        self.assertEqual(dashboard.single_task_selector.options, [])
        self.assertTrue(dashboard.single_task_selector.disabled)
        self.assertEqual(dashboard.single_task_selector.hint_text, "当前无可选任务")
        self.assertTrue(dashboard.start_button.disabled)

        system["task_enabled"][MAIL_TASK] = True
        dashboard._refresh_single_task_options(state, NOW)
        self.assertFalse(dashboard.single_task_selector.disabled)
        self.assertEqual(dashboard.single_task_selector.hint_text, "请选择任务")

    def test_empty_selector_message_is_shown_in_account_area(self):
        dashboard = AssistantDashboard.__new__(AssistantDashboard)
        dashboard.task_mode = DAILY_MODE
        dashboard.single_task_mode = True
        dashboard.single_task_name = None
        dashboard.running = False
        dashboard.single_task_selector = SimpleNamespace(value=None, options=[])
        dashboard.start_button = SimpleNamespace(disabled=False)
        dashboard.cards = {}
        dashboard.cards_grid = SimpleNamespace(controls=[])
        dashboard.summary_text = SimpleNamespace(value="")
        dashboard.important_results_bar = SimpleNamespace(visible=True)
        dashboard.important_summary_text = SimpleNamespace(value="", color=None)
        dashboard.important_filter_button = SimpleNamespace(content=None, bgcolor=None)
        dashboard.show_important_only = False
        dashboard.hide_unavailable_tasks = SimpleNamespace(value=False)
        dashboard.append_log = lambda *_args: None
        daily_state = {"accounts": {}}

        with patch("ui_app.pages.daily.controller.load_state", return_value=(daily_state, False)):
            self.assertTrue(dashboard.refresh_cards(update=False))

        self.assertEqual(dashboard.summary_text.value, "当前无可选任务")
        self.assertEqual(
            dashboard.cards_grid.controls[0].content.value,
            "当前无可选任务",
        )

    def test_account_card_shows_only_selected_task(self):
        card = AccountCardView(
            "account",
            "IOS",
            state_store._empty_system_state(),
            NOW,
            single_task_name=MAIL_TASK,
        )

        self.assertEqual(list(card.task_views), [MAIL_TASK])

    def test_partial_daily_card_handles_bounty_and_merchant_lookups(self):
        from controller.constants import BOUNTY_TASK

        card = AccountCardView(
            "account",
            "IOS",
            state_store._empty_system_state(),
            NOW,
            single_task_name=BOUNTY_TASK,
        )

        self.assertEqual(card.important_result_labels(), [])

    def test_weekly_card_keeps_the_existing_consignment_task(self):
        weekly_state = state_store._empty_weekly_system_state()
        card = AccountCardView(
            "account",
            "IOS",
            weekly_state,
            NOW,
            task_mode=WEEKLY_MODE,
            single_task_name=CONSIGNMENT_HOUSE_TASK,
        )

        self.assertEqual(list(card.task_views), [CONSIGNMENT_HOUSE_TASK])

    def test_mode_toggle_requires_task_selection_before_start(self):
        dashboard = AssistantDashboard.__new__(AssistantDashboard)
        dashboard.running = False
        dashboard.task_mode = "daily"
        dashboard.single_task_mode = False
        dashboard.single_task_name = None
        dashboard.single_task_selector = SimpleNamespace(
            value=None,
            options=[],
        )
        dashboard.single_task_selector_panel = SimpleNamespace(visible=False)
        dashboard.single_task_mode_switch = SimpleNamespace(
            value=False,
            disabled=False,
        )
        dashboard.start_button = SimpleNamespace(disabled=False)
        dashboard.refresh_cards = lambda **_kwargs: True
        dashboard.append_log = lambda *_args: None
        dashboard._safe_update = lambda: None

        dashboard._set_single_task_mode(True)

        self.assertTrue(dashboard.single_task_selector_panel.visible)
        self.assertTrue(dashboard.start_button.disabled)
        self.assertTrue(dashboard.single_task_mode_switch.value)


if __name__ == "__main__":
    unittest.main()

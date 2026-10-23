"""中控执行回归：只用任务替身和临时状态文件，不连接模拟器。"""

import tempfile
import threading
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, Mock, call, patch

from controller import daily_runner, state_store, task_services, weekly_runner
from controller.constants import (
    BOUNTY_TASK,
    CONSIGNMENT_HOUSE_TASK,
    COOP_BATTLE_COMPLETED_RECOVERY_REQUIRED,
    COOP_REWARD_TASK,
    HEART_TEAM_BATTLES_COMPLETED_CLEANUP_FAILED,
    HEART_TEAM_TASK,
    MAIL_TASK,
    MERCHANT_TASK,
    STATUS_VERSION,
)
from controller.types import ControllerServices, TaskWork, WorkItem
from ui_app.components import AccountCardView
from ui_app.pages.daily import DailyPageMixin
from module.logging import TaskLogger
from module.task_execution import record_frame
from tasks.Mail import mail
from tasks.Account import sign
from tasks.CoopReward import coop_reward as coop
from tasks.Merchant import merchant
from module.base.device import TaskDevice


NOW = datetime(2026, 10, 7, 12, tzinfo=timezone(timedelta(hours=8)))


class ControllerExecutionTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(directory) / "daily.json"
        self.weekly_path = Path(directory) / "weekly.json"
        self.reset_state()
        self.events = []
        self.services = ControllerServices(
            select_account=lambda account, _: account,
            exit_to_login=lambda: True,
            sign_in=lambda *_: True,
            task_runners={},
        )
        self.screenshots = self.enterContext(patch.object(
            daily_runner, "capture_error_screenshot",
        ))
        self.enterContext(patch.object(weekly_runner, "capture_error_screenshot"))
        self.enterContext(patch.object(task_services, "capture_error_screenshot"))
        self.enterContext(patch.object(daily_runner, "print"))
        self.enterContext(patch.object(weekly_runner, "print"))
        self.enterContext(patch.object(
            daily_runner, "maybe_send_detection_summary",
            return_value=SimpleNamespace(status="disabled"),
        ))

    def reset_state(self):
        system_state = state_store._empty_system_state()
        state_store.set_heart_team_role(system_state, "leader")
        state_store.save_state({
            "version": STATUS_VERSION,
            "accounts": {"account": {"systems": {"IOS": system_state}}},
        }, self.path)

    def saved_system(self):
        state, _ = state_store.load_state(self.path)
        return state["accounts"]["account"]["systems"]["IOS"]

    def run_daily(self, tasks, **kwargs):
        queue = [WorkItem("account", "IOS", tuple(tasks))]
        with patch.object(daily_runner, "build_work_queue", return_value=queue):
            return daily_runner.run(
                status_path=self.path,
                services=self.services,
                now_provider=lambda: NOW,
                event_callback=self.events.append,
                **kwargs,
            )

    def test_member_reserve_warning_survives_reload_and_card_rebuild(self):
        state, _ = state_store.load_state(self.path)
        system = state["accounts"]["account"]["systems"]["IOS"]
        state_store.set_heart_team_role(system, "member")
        system["task_enabled"][HEART_TEAM_TASK] = True
        state_store.save_state(state, self.path)
        message = "一键预存后体力未满，但已达到最低要求：320/400（下限 200）"

        def runner(**kwargs):
            kwargs["on_warning"](message)
            return True

        self.services.task_runners[HEART_TEAM_TASK] = runner
        self.assertTrue(self.run_daily([TaskWork(HEART_TEAM_TASK, 1)]))
        saved = self.saved_system()
        self.assertEqual(saved[HEART_TEAM_TASK]["reserve_warning"], message)
        card = AccountCardView(
            "account", "IOS", saved, NOW, single_task_name=HEART_TEAM_TASK,
        )
        self.assertEqual(card.task_views[HEART_TEAM_TASK].status, "warning")
        self.assertEqual(card.status, "warning")
        self.assertIn("320/400", card.task_views[HEART_TEAM_TASK].detail.value)

        next_cycle = AccountCardView(
            "account", "IOS", saved, NOW + timedelta(days=3),
            single_task_name=HEART_TEAM_TASK,
        )
        self.assertEqual(next_cycle.task_views[HEART_TEAM_TASK].status, "pending")

        # 后续补满后必须覆盖旧警告，而不是永久保留黄色状态。
        self.services.task_runners[HEART_TEAM_TASK] = lambda **kwargs: True
        self.assertTrue(self.run_daily([TaskWork(HEART_TEAM_TASK, 1)]))
        replenished = self.saved_system()
        self.assertIsNone(replenished[HEART_TEAM_TASK]["reserve_warning"])
        card = AccountCardView(
            "account", "IOS", replenished, NOW, single_task_name=HEART_TEAM_TASK,
        )
        self.assertEqual(card.task_views[HEART_TEAM_TASK].status, "done")
        self.assertEqual(card.status, "done")

    def test_failure_recovers_and_retries_before_saving_completion(self):
        runner = Mock(side_effect=[RuntimeError("test failure"), True])
        self.services.task_runners[MAIL_TASK] = runner

        def recover(_):
            self.assertIsNone(state_store.task_record_time(self.saved_system(), MAIL_TASK))
            return True

        self.services.task_timeout_recovery = Mock(side_effect=recover)
        self.assertTrue(self.run_daily([TaskWork(MAIL_TASK, 1)]))
        self.assertEqual(runner.call_count, 2)
        self.services.task_timeout_recovery.assert_called_once_with(None)
        self.assertIsNotNone(state_store.task_record_time(self.saved_system(), MAIL_TASK))
        self.screenshots.assert_called_once_with(MAIL_TASK, "exception", attempt=1)
        self.assertIn("task_retried", [event["type"] for event in self.events])

    def test_exhausted_retry_never_saves_completion_or_starts_next_task(self):
        failed = Mock(return_value=False)
        next_task = Mock(return_value=True)
        self.services.task_runners = {MAIL_TASK: failed, "liked": next_task}
        self.services.task_timeout_recovery = Mock(return_value=True)
        self.assertFalse(self.run_daily([TaskWork(MAIL_TASK, 1), TaskWork("liked", 1)]))
        self.assertEqual(failed.call_count, 2)
        # 一次重试前恢复，一次重试耗尽后的收尾恢复。
        self.assertEqual(self.services.task_timeout_recovery.call_count, 2)
        next_task.assert_not_called()
        self.assertIsNone(state_store.task_record_time(self.saved_system(), MAIL_TASK))

    def test_completed_battles_are_saved_before_cleanup_even_if_cleanup_fails(self):
        for task, sentinel in (
            (COOP_REWARD_TASK, COOP_BATTLE_COMPLETED_RECOVERY_REQUIRED),
        ):
            for recovery_result in (True, False):
                with self.subTest(task=task, recovered=recovery_result):
                    self.reset_state()
                    runner = Mock(return_value=sentinel)
                    next_task = Mock(return_value=True)
                    self.services.task_runners = {task: runner, MAIL_TASK: next_task}
                    self.services.task_timeout_recovery = Mock(return_value=True)

                    def recover(_):
                        saved = self.saved_system()
                        self.assertIsNotNone(state_store.task_record_time(saved, task))
                        return recovery_result

                    recovery = Mock(side_effect=recover)
                    self.services.task_completion_recoveries = {task: recovery}
                    self.assertEqual(self.run_daily([
                        TaskWork(task, 1), TaskWork(MAIL_TASK, 1),
                    ]), recovery_result)
                    runner.assert_called_once()
                    recovery.assert_called_once_with(None)
                    self.services.task_timeout_recovery.assert_not_called()
                    self.assertEqual(next_task.call_count, int(recovery_result))

    def test_heart_cleanup_failure_saves_screenshot_and_stops_without_recovery(self):
        runner = Mock(return_value=HEART_TEAM_BATTLES_COMPLETED_CLEANUP_FAILED)
        next_task = Mock(return_value=True)
        recovery = Mock(return_value=True)
        self.services.task_runners = {HEART_TEAM_TASK: runner, MAIL_TASK: next_task}
        self.services.task_completion_recoveries = {HEART_TEAM_TASK: recovery}
        self.services.task_timeout_recovery = Mock(return_value=True)

        self.assertFalse(self.run_daily([
            TaskWork(HEART_TEAM_TASK, 1), TaskWork(MAIL_TASK, 1),
        ]))

        self.screenshots.assert_called_once_with(
            HEART_TEAM_TASK, "completion_cleanup_failed", attempt=1,
        )
        self.assertIsNotNone(state_store.task_record_time(self.saved_system(), HEART_TEAM_TASK))
        runner.assert_called_once()
        recovery.assert_not_called()
        self.services.task_timeout_recovery.assert_not_called()
        next_task.assert_not_called()

    def test_missing_completion_recovery_preserves_completion_without_retry(self):
        runner = Mock(return_value=HEART_TEAM_BATTLES_COMPLETED_CLEANUP_FAILED)
        self.services.task_runners[HEART_TEAM_TASK] = runner
        self.assertFalse(self.run_daily([TaskWork(HEART_TEAM_TASK, 1)]))
        runner.assert_called_once()
        self.assertIsNotNone(state_store.task_record_time(self.saved_system(), HEART_TEAM_TASK))

    def test_coop_card_uses_short_counts_and_keeps_original_target_after_resume(self):
        state, _ = state_store.load_state(self.path)
        system = state["accounts"]["account"]["systems"]["IOS"]
        state_store.set_battle_progress(system, COOP_REWARD_TASK, NOW, 5, 12)
        state_store.save_state(state, self.path)
        card = AccountCardView("account", "IOS", system, NOW, single_task_name=COOP_REWARD_TASK)
        view = card.task_views[COOP_REWARD_TASK]
        self.assertEqual(view.detail.value, "待打 7 场")
        self.services.task_runners[COOP_REWARD_TASK] = Mock(return_value=True)
        self.assertTrue(self.run_daily([TaskWork(COOP_REWARD_TASK, 7)]))
        starts = [event for event in self.events if event["type"] == "task_started"]
        self.assertEqual(
            [(event["battle_index"], event["battle_target"]) for event in starts],
            [(index, 12) for index in range(6, 13)],
        )
        page = SimpleNamespace(
            cards={("account", "IOS"): card},
            _apply_task_visibility=lambda: None, _refresh_task_summary=lambda: None,
        )
        DailyPageMixin._apply_controller_event(page, starts[0])
        self.assertEqual(view.detail.value, "第 6/12 场")
        progress = next(event for event in self.events if event["type"] == "task_battle_progress")
        DailyPageMixin._apply_controller_event(page, progress)
        self.assertEqual(view.detail.value, "6/12 场")
        completed = next(event for event in self.events if event["type"] == "task_completed")
        DailyPageMixin._apply_controller_event(page, completed)
        self.assertEqual((view.status, view.detail.value), ("done", "已完成"))
        refreshed = AccountCardView(
            "account", "IOS", self.saved_system(), NOW, single_task_name=COOP_REWARD_TASK,
        )
        self.assertEqual(refreshed.task_views[COOP_REWARD_TASK].detail.value, "已完成")

    def test_coop_intermediate_cleanup_saves_progress_and_reenters_next_battle(self):
        runner = Mock(side_effect=[COOP_BATTLE_COMPLETED_RECOVERY_REQUIRED, True])
        self.services.task_runners[COOP_REWARD_TASK] = runner

        def recover(_):
            saved = self.saved_system()
            self.assertEqual(state_store.battle_progress(saved, COOP_REWARD_TASK, NOW), (1, 2))
            self.assertIsNone(state_store.task_record_time(saved, COOP_REWARD_TASK))
            return True

        recovery = Mock(side_effect=recover)
        self.services.task_completion_recoveries[COOP_REWARD_TASK] = recovery
        self.assertTrue(self.run_daily([TaskWork(COOP_REWARD_TASK, 2)]))
        self.assertEqual(runner.call_args_list, [
            call(enable_bonus=True, disable_bonus_after=False, on_battle_completed=ANY),
            call(enable_bonus=True, disable_bonus_after=True, on_battle_completed=ANY),
        ])
        recovery.assert_called_once_with(None)
        self.assertEqual(state_store.battle_progress(self.saved_system(), COOP_REWARD_TASK, NOW), (2, 2))
        progress_events = [
            event for event in self.events
            if event["type"] == "task_battle_progress"
            and event["task"] == COOP_REWARD_TASK
        ]
        self.assertEqual(
            [(event["completed"], event["target"]) for event in progress_events],
            [(1, 2), (2, 2)],
        )

    def test_coop_failed_intermediate_cleanup_stops_with_saved_partial_progress(self):
        runner = Mock(return_value=COOP_BATTLE_COMPLETED_RECOVERY_REQUIRED)
        self.services.task_runners[COOP_REWARD_TASK] = runner
        self.services.task_completion_recoveries[COOP_REWARD_TASK] = Mock(return_value=False)
        self.assertFalse(self.run_daily([TaskWork(COOP_REWARD_TASK, 2)]))
        runner.assert_called_once()
        saved = self.saved_system()
        self.assertEqual(state_store.battle_progress(saved, COOP_REWARD_TASK, NOW), (1, 2))
        self.assertIsNone(state_store.task_record_time(saved, COOP_REWARD_TASK))

    def test_heart_retry_receives_saved_battle_progress(self):
        received = []

        def runner(*, role, completed_battles, on_battle_completed, on_warning=None):
            received.append(completed_battles)
            if len(received) == 1:
                on_battle_completed(3, 20)
                return False
            self.assertEqual(state_store.battle_progress(self.saved_system(), HEART_TEAM_TASK, NOW), (3, 20))
            return True

        self.services.task_runners[HEART_TEAM_TASK] = runner
        self.services.task_timeout_recovery = Mock(return_value=True)
        self.assertTrue(self.run_daily([TaskWork(HEART_TEAM_TASK, 1)]))
        self.assertEqual(received, [0, 3])
        progress_events = [
            event for event in self.events
            if event["type"] == "task_battle_progress"
        ]
        self.assertEqual(
            [(event["completed"], event["target"]) for event in progress_events],
            [(3, 20)],
        )

    def test_stop_between_coop_battles_keeps_progress_without_completion(self):
        stop = threading.Event()

        def runner(**_):
            stop.set()
            return True

        self.services.task_runners[COOP_REWARD_TASK] = Mock(side_effect=runner)
        self.assertFalse(self.run_daily([TaskWork(COOP_REWARD_TASK, 2)], stop_event=stop))
        self.services.task_runners[COOP_REWARD_TASK].assert_called_once()
        saved = self.saved_system()
        self.assertEqual(state_store.battle_progress(saved, COOP_REWARD_TASK, NOW), (1, 2))
        self.assertIsNone(state_store.task_record_time(saved, COOP_REWARD_TASK))
        self.screenshots.assert_not_called()
        self.assertEqual(self.events[-1]["type"], "controller_stopped")

    def test_coop_final_battle_is_saved_and_cleanup_finishes_after_stop_request(self):
        for cleanup_step in ("_disable_soul_bonus", "_return_to_courtyard"):
            with self.subTest(step=cleanup_step):
                self.reset_state()
                state, _ = state_store.load_state(self.path)
                state_store.set_battle_progress(
                    state["accounts"]["account"]["systems"]["IOS"], COOP_REWARD_TASK, NOW, 2, 3,
                )
                state_store.save_state(state, self.path)
                stop = threading.Event()
                self.events.clear()
                self.screenshots.reset_mock()
                self.services.task_runners[COOP_REWARD_TASK] = coop.run
                self.services.task_timeout_recovery = Mock(return_value=True)
                self.services.task_completion_recoveries[COOP_REWARD_TASK] = Mock(return_value=True)

                finished_steps = []

                def cleanup(step):
                    # 正式执行收尾之前，文件中的最后一场就应已落盘。
                    self.assertEqual(state_store.battle_progress(self.saved_system(), COOP_REWARD_TASK, NOW), (3, 3))
                    if step == cleanup_step:
                        stop.set()
                    coop.DEVICE.screenshot()
                    self.assertFalse(any(event["type"] == "controller_stopped" for event in self.events))
                    finished_steps.append(step)
                    return True

                with patch.object(coop.utils, "connect_to_mumu"), patch.object(
                    coop, "_prepare_soul_dungeon", return_value=True,
                ), patch.object(coop, "_wait_and_click", return_value=True), patch.object(
                    coop, "collect_battle_rewards", return_value=True,
                ) as battle, patch.object(coop, "_disable_soul_bonus", side_effect=lambda: cleanup("_disable_soul_bonus")), patch.object(
                    coop, "_return_to_courtyard", side_effect=lambda: cleanup("_return_to_courtyard"),
                ), patch.object(coop.DEVICE.backend, "take_screenshot", return_value=object()), patch("builtins.print"):
                    self.assertFalse(self.run_daily([TaskWork(COOP_REWARD_TASK, 1)], stop_event=stop))
                self.assertEqual(state_store.battle_progress(self.saved_system(), COOP_REWARD_TASK, NOW), (3, 3))
                battle.assert_called_once_with()
                self.screenshots.assert_not_called()
                self.services.task_timeout_recovery.assert_not_called()
                self.services.task_completion_recoveries[COOP_REWARD_TASK].assert_not_called()
                progress = [event["completed"] for event in self.events if event["type"] == "task_battle_progress"]
                self.assertEqual(progress, [3])
                self.assertEqual(finished_steps, ["_disable_soul_bonus", "_return_to_courtyard"])
                self.assertEqual(self.events[-1]["type"], "controller_stopped")

    def test_coop_failed_settlement_after_stop_request_does_not_increment_progress(self):
        stop = threading.Event()
        self.services.task_runners[COOP_REWARD_TASK] = coop.run

        def stop_before_settlement():
            stop.set()
            coop.DEVICE.screenshot()
            return False  # 真实结算失败，停止请求不能将其算作完成。

        with patch.object(coop.utils, "connect_to_mumu"), patch.object(
            coop, "_prepare_soul_dungeon", return_value=True,
        ), patch.object(coop, "_wait_and_click", return_value=True), patch.object(
            coop, "collect_battle_rewards", side_effect=stop_before_settlement,
        ), patch.object(coop.DEVICE.backend, "take_screenshot", return_value=object()), patch("builtins.print"):
            self.assertFalse(self.run_daily([TaskWork(COOP_REWARD_TASK, 1)], stop_event=stop))
        self.assertEqual(state_store.battle_progress(self.saved_system(), COOP_REWARD_TASK, NOW), (0, 0))
        self.screenshots.assert_not_called()

    def test_merchant_stop_request_during_detection_finishes_return_to_courtyard(self):
        stop = threading.Event()
        backend = SimpleNamespace(take_screenshot=Mock(return_value=object()), adb_click=Mock())
        device = TaskDevice(backend)
        detection_calls = 0
        finished = []

        def detect():
            nonlocal detection_calls
            detection_calls += 1
            if detection_calls == 2:
                stop.set()
                device.screenshot()
            return False, None

        def return_to_courtyard():
            self.assertTrue(stop.is_set())
            self.assertFalse(any(event["type"] == "controller_stopped" for event in self.events))
            device.click(10, 20)
            device.screenshot()
            finished.append("courtyard")
            return True

        next_task = Mock(return_value=True)
        self.services.task_runners = {MERCHANT_TASK: merchant.check_merchant, MAIL_TASK: next_task}
        with patch.object(merchant.utils, "connect_to_mumu"), patch.object(
            merchant, "_ensure_store_menu_expanded", return_value=True,
        ), patch.object(merchant, "_wait_and_click", return_value=True), patch.object(
            merchant, "_open_merchant_page", return_value=merchant.MerchantResult.NO_BLUE_TICKET,
        ), patch.object(merchant, "_detect_blue_ticket_price", side_effect=detect), patch.object(
            merchant, "_refresh_merchant_shop", return_value=merchant.RefreshState.REFRESHED,
        ), patch.object(merchant, "_return_to_courtyard", side_effect=return_to_courtyard), patch("builtins.print"):
            self.assertFalse(self.run_daily([TaskWork(MERCHANT_TASK, 1), TaskWork(MAIL_TASK, 1)], stop_event=stop))
        self.assertEqual(finished, ["courtyard"])
        backend.adb_click.assert_called_once_with(10, 20)
        self.assertIsNotNone(state_store.task_record_time(self.saved_system(), MERCHANT_TASK))
        next_task.assert_not_called()
        self.screenshots.assert_not_called()
        self.assertEqual(self.events[-1]["type"], "controller_stopped")

    def test_stop_request_during_account_action_finishes_call_and_skips_next_phase(self):
        for phase in ("select_account", "sign_in"):
            with self.subTest(phase=phase):
                stop = threading.Event()
                finished = []
                backend = SimpleNamespace(take_screenshot=Mock(return_value=object()))
                device = TaskDevice(backend)
                self.events.clear()
                self.screenshots.reset_mock()

                def finish_account_action(*_):
                    stop.set()
                    device.screenshot()
                    finished.append(phase)
                    return "account" if phase == "select_account" else True

                self.services.select_account = Mock(return_value="account")
                self.services.sign_in = Mock(return_value=True)
                setattr(self.services, phase, Mock(side_effect=finish_account_action))
                task = Mock(return_value=True)
                self.services.task_runners = {MAIL_TASK: task}
                self.assertFalse(self.run_daily([TaskWork(MAIL_TASK, 1)], stop_event=stop))
                self.assertEqual(finished, [phase])
                task.assert_not_called()
                if phase == "select_account":
                    self.services.sign_in.assert_not_called()
                    self.assertFalse(any(event["type"] == "account_phase" for event in self.events))
                self.screenshots.assert_not_called()
                self.assertEqual(self.events[-1]["type"], "controller_stopped")

    def test_coop_cleanup_exception_does_not_retry_a_completed_battle(self):
        self.services.task_runners[COOP_REWARD_TASK] = coop.run
        self.services.task_timeout_recovery = Mock(return_value=True)
        self.services.task_completion_recoveries[COOP_REWARD_TASK] = Mock(return_value=True)
        with patch.object(coop.utils, "connect_to_mumu"), patch.object(
            coop, "_prepare_soul_dungeon", return_value=True,
        ), patch.object(coop, "_wait_and_click", return_value=True), patch.object(
            coop, "collect_battle_rewards", return_value=True,
        ) as battle, patch.object(
            coop, "_disable_soul_bonus", side_effect=RuntimeError("bonus cleanup failed"),
        ), patch("builtins.print"):
            self.assertTrue(self.run_daily([TaskWork(COOP_REWARD_TASK, 1)]))
        battle.assert_called_once_with()
        self.assertEqual(state_store.battle_progress(self.saved_system(), COOP_REWARD_TASK, NOW), (1, 1))
        self.services.task_timeout_recovery.assert_not_called()
        self.services.task_completion_recoveries[COOP_REWARD_TASK].assert_called_once_with(None)

    def test_daily_and_weekly_share_runtime_settings_conversion(self):
        settings = {"screenshot_interval": 0.7, "recovery_retry_count": 3}
        self.services.task_runners = {
            MAIL_TASK: Mock(return_value=True),
            CONSIGNMENT_HOUSE_TASK: Mock(return_value="purchased"),
        }
        for module, task, extra in (
            (daily_runner, MAIL_TASK, {}),
            (weekly_runner, CONSIGNMENT_HOUSE_TASK, {"weekly_status_path": self.weekly_path}),
        ):
            with self.subTest(module=module.__name__):
                queue = [WorkItem("account", "IOS", (TaskWork(task, 1),))]
                queue_name = "build_work_queue" if module is daily_runner else "build_weekly_work_queue"
                entrypoint = module.run if module is daily_runner else module.run_weekly
                with patch.object(module, queue_name, return_value=queue), patch.object(
                    task_services, "build_services", return_value=self.services,
                ) as build:
                    self.assertTrue(entrypoint(
                        status_path=self.path, now_provider=lambda: NOW,
                        runtime_settings=settings, **extra,
                    ))
                    self.assertEqual(build.call_args.kwargs["screenshot_interval"], 0.7)
                    self.assertEqual(build.call_args.kwargs["recovery_retry_count"], 3)
                    self.assertEqual(build.call_args.kwargs["recovery_timeout_seconds"], 90.0)
        weekly, _ = state_store.load_weekly_state(self.weekly_path, state_store.load_state(self.path)[0])
        self.assertEqual(state_store.weekly_task_record(weekly, "account", "IOS")["result"], "purchased")


    def test_mail_stage_scene_is_saved_before_recovery_then_retry_succeeds(self):
        failure_frame = object()
        order = []
        calls = 0

        def claim():
            nonlocal calls
            calls += 1
            mail.LOGGER.set_stage("确认领取")
            record_frame(failure_frame)
            if calls == 1:
                mail.LOGGER.error("确认按钮", "未识别到确认按钮")
                return False
            return True

        def recover(_):
            order.append("recover")
            return True

        self.screenshots.side_effect = lambda *a, **k: order.append("screenshot")
        self.services.task_runners[MAIL_TASK] = mail.run
        self.services.task_timeout_recovery = recover
        with patch.object(mail.utils, "connect_to_mumu"), patch.object(
            mail, "_wait_for_mail_state", return_value=("unread", (1, 2, 3, 4)),
        ), patch.object(mail, "_click_until_disappears", return_value=True), patch.object(
            mail, "_claim_mail", side_effect=claim,
        ), patch.object(mail, "_close_mailbox", return_value=True), patch("builtins.print"):
            self.assertTrue(self.run_daily([TaskWork(MAIL_TASK, 1)]))
        self.assertEqual(order, ["screenshot", "recover"])
        self.assertEqual(calls, 2)
        self.screenshots.assert_called_once_with(MAIL_TASK, "确认领取", attempt=1, frame=failure_frame)
        self.assertTrue(any("确认领取" in event.get("message", "") for event in self.events))

    def test_weekly_uses_the_same_stage_and_retry_exhaustion_policy(self):
        failure_frame = object()
        logger = TaskLogger("寄售屋")

        def task():
            logger.set_stage("购买寄售券")
            record_frame(failure_frame)
            logger.error("购买", "购买确认超时")
            return "error"

        self.services.task_runners[CONSIGNMENT_HOUSE_TASK] = task
        self.services.task_recovery_retries = 0
        self.services.task_timeout_recovery = Mock(return_value=True)
        queue = [WorkItem("account", "IOS", (TaskWork(CONSIGNMENT_HOUSE_TASK, 1),))]
        with patch.object(weekly_runner, "build_weekly_work_queue", return_value=queue), patch("builtins.print"):
            self.assertFalse(weekly_runner.run_weekly(
                status_path=self.path, weekly_status_path=self.weekly_path,
                services=self.services, now_provider=lambda: NOW, event_callback=self.events.append,
            ))
        self.screenshots.assert_called_once_with(CONSIGNMENT_HOUSE_TASK, "购买寄售券", attempt=1, frame=failure_frame)
        self.services.task_timeout_recovery.assert_called_once_with(None)
        self.assertEqual(self.events[-1]["task_stage"], "购买寄售券")
        self.assertIn("购买确认超时", self.events[-1]["message"])

    def test_weekly_stop_finishes_current_purchase_and_preserves_result(self):
        stop = threading.Event()
        backend = SimpleNamespace(take_screenshot=Mock(return_value=object()))
        device = TaskDevice(backend)
        finished = []

        def purchase():
            stop.set()
            device.screenshot()
            finished.append("returned_to_courtyard")
            return "purchased"

        runner = Mock(side_effect=purchase)
        self.services.task_runners[CONSIGNMENT_HOUSE_TASK] = runner
        item = WorkItem("account", "IOS", (TaskWork(CONSIGNMENT_HOUSE_TASK, 1),))
        with patch.object(weekly_runner, "build_weekly_work_queue", return_value=[item, item]):
            self.assertFalse(weekly_runner.run_weekly(
                status_path=self.path, weekly_status_path=self.weekly_path,
                services=self.services, now_provider=lambda: NOW,
                event_callback=self.events.append, stop_event=stop,
            ))
        self.assertEqual(finished, ["returned_to_courtyard"])
        runner.assert_called_once()
        weekly, _ = state_store.load_weekly_state(self.weekly_path, state_store.load_state(self.path)[0])
        self.assertEqual(state_store.weekly_task_record(weekly, "account", "IOS")["result"], "purchased")
        self.assertEqual(self.events[-1]["type"], "controller_stopped")
        self.screenshots.assert_not_called()

    def test_login_failure_is_reported_once_with_system_selection_stage(self):
        frame = object()

        def select_system(*_):
            sign.LOGGER.error("系统按钮", "系统选择超时")
            sign._report_timeout("wait_ios", frame)
            return False

        self.services.sign_in = sign.run
        self.services.task_runners[MAIL_TASK] = Mock(return_value=True)
        with patch.dict(sign.REGION_NAMES, {"same": "测试同区"}), patch.object(sign.utils, "connect_to_mumu"), patch.object(
            sign, "_wait_and_select_system", side_effect=select_system,
        ), patch("builtins.print"):
            self.assertFalse(self.run_daily([TaskWork(MAIL_TASK, 1)]))
        self.screenshots.assert_called_once_with("account_sign", "登录及系统选择", frame=frame)
        self.services.task_runners[MAIL_TASK].assert_not_called()
        self.assertIn("登录及系统选择", self.events[-1]["message"])


class TaskResultTests(unittest.TestCase):
    def test_generic_recovery_adapter_respects_remaining_heart_timeout(self):
        common = SimpleNamespace(
            run=Mock(), check_bounty=Mock(), check_merchant=Mock(),
            check_consignment_house=Mock(), recover_to_courtyard=Mock(),
            select_account=Mock(), exit_to_login=Mock(),
        )
        generic = SimpleNamespace(recover_to_courtyard=Mock(return_value=True))
        heart = SimpleNamespace(
            run=Mock(),
            recover_to_courtyard=Mock(side_effect=lambda stop_event, timeout, fallback:
                                     fallback(stop_event, timeout=2.0)),
        )

        def load(name, path):
            if name == "task_timeout_recovery":
                return generic
            return heart if name == HEART_TEAM_TASK else common

        with patch.object(task_services, "_load_module", side_effect=load), patch.object(
            task_services, "configure_error_screenshots",
        ):
            services = task_services.build_services(recovery_timeout_seconds=60.0)

        self.assertTrue(services.task_failure_recoveries[HEART_TEAM_TASK](None))
        self.assertEqual(generic.recover_to_courtyard.call_args.kwargs["timeout"], 2.0)

    def test_cancelled_or_already_captured_recovery_does_not_save_extra_screenshot(self):
        stop = threading.Event()
        stop.set()
        with patch.object(task_services, "capture_error_screenshot") as capture:
            task_services._run_task_recovery(
                lambda _: SimpleNamespace(success=False, reason="已停止"), stop,
            )
            task_services._run_task_recovery(
                lambda _: SimpleNamespace(success=False, screenshot="existing.png"), None,
            )
        capture.assert_not_called()

    def test_heart_team_member_warning_is_a_completed_warning_result(self):
        message = "一键预存后体力未满：320/400"

        def runner(**kwargs):
            kwargs["on_warning"](message)
            return True

        outcome = task_services._invoke_task_runner(
            HEART_TEAM_TASK,
            runner,
            1,
            1,
            {HEART_TEAM_TASK: {"role": "member"}},
        )

        self.assertTrue(outcome.completed)
        self.assertEqual(outcome.warning, message)

    def test_only_recorded_coop_completion_allows_reward_handling(self):
        task_module = SimpleNamespace(
            run=Mock(), check_bounty=Mock(), check_merchant=Mock(),
            check_consignment_house=Mock(), recover_to_courtyard=Mock(),
            select_account=Mock(), exit_to_login=Mock(),
        )
        timeout_recovery = SimpleNamespace(recover_to_courtyard=Mock(return_value=True))

        def load(name, path):
            return timeout_recovery if name == "task_timeout_recovery" else task_module

        with patch.object(task_services, "_load_module", side_effect=load), patch.object(
            task_services, "configure_error_screenshots"
        ):
            services = task_services.build_services()

        services.task_timeout_recovery()
        services.task_failure_recoveries[COOP_REWARD_TASK]()
        services.task_completion_recoveries[COOP_REWARD_TASK]()
        calls = timeout_recovery.recover_to_courtyard.call_args_list
        self.assertEqual(len(calls), 3)
        self.assertNotIn("allow_completed_reward", calls[0].kwargs)
        self.assertNotIn("allow_completed_reward", calls[1].kwargs)
        self.assertTrue(calls[2].kwargs["allow_completed_reward"])

    def test_detection_results_are_validated_including_unknown_price(self):
        for task, value, completed in (
            (BOUNTY_TASK, "no_magatama_collaboration", True),
            (BOUNTY_TASK, "invalid", False),
            (MERCHANT_TASK, "unknown_price", True),
            (MERCHANT_TASK, "invalid", False),
            (CONSIGNMENT_HOUSE_TASK, "already_purchased", True),
            (CONSIGNMENT_HOUSE_TASK, "purchased", True),
            (CONSIGNMENT_HOUSE_TASK, "error", False),
        ):
            with self.subTest(task=task, value=value):
                outcome = task_services._invoke_task_runner(
                    task, lambda: SimpleNamespace(value=value), 1, 1, {},
                )
                self.assertEqual(outcome.completed, completed)
                self.assertEqual(outcome.result, value)
                self.assertIsNone(outcome.recovery_reason)


if __name__ == "__main__":
    unittest.main()

"""中控执行回归：只用任务替身和临时状态文件，不连接模拟器。"""

import tempfile
import threading
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

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
            (HEART_TEAM_TASK, HEART_TEAM_BATTLES_COMPLETED_CLEANUP_FAILED),
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

    def test_missing_completion_recovery_preserves_completion_without_retry(self):
        runner = Mock(return_value=HEART_TEAM_BATTLES_COMPLETED_CLEANUP_FAILED)
        self.services.task_runners[HEART_TEAM_TASK] = runner
        self.assertFalse(self.run_daily([TaskWork(HEART_TEAM_TASK, 1)]))
        runner.assert_called_once()
        self.assertIsNotNone(state_store.task_record_time(self.saved_system(), HEART_TEAM_TASK))

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
            call(enable_bonus=True, disable_bonus_after=False),
            call(enable_bonus=True, disable_bonus_after=True),
        ])
        recovery.assert_called_once_with(None)
        self.assertEqual(state_store.battle_progress(self.saved_system(), COOP_REWARD_TASK, NOW), (2, 2))

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

        def runner(*, role, completed_battles, on_battle_completed):
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


class TaskResultTests(unittest.TestCase):
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

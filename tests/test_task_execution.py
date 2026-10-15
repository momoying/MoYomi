"""阶段、现场、取消和独立工具入口的回归；不连接模拟器。"""

import queue
import threading
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from module import automation, recovery, startup
from module.base.device import TaskDevice
from module.logging import TaskLogger
from module.task_execution import current_stage, record_frame, run_task_call
from controller import task_services
from ui_app.pages.tools import ToolsPageMixin
from ui_app.settings_store import DEFAULT_SETTINGS


class ExecutionReportTests(unittest.TestCase):
    def test_stage_and_reason_are_reported_without_parsing_rendered_logs(self):
        logger = TaskLogger("领取邮件")
        frame = object()

        def task():
            logger.set_stage("确认领取")
            record_frame(frame)
            logger.error("确认按钮", "未识别到确认按钮")
            return False

        with patch("builtins.print") as output:
            result, report = run_task_call(task)
        self.assertFalse(result)
        self.assertEqual(report.stage, "确认领取")
        self.assertEqual(report.reason, "未识别到确认按钮")
        self.assertIs(report.frame, frame)
        output.assert_called_once()
        self.assertIn("[领取邮件/确认领取]", output.call_args.args[0])
        self.assertIsNone(current_stage())

    def test_failed_frame_is_frozen_before_following_cleanup_changes_the_image(self):
        frame = np.zeros((2, 2, 3), dtype=np.uint8)
        logger = TaskLogger("任务")

        def task():
            logger.set_stage("业务阶段")
            record_frame(frame)
            logger.error("确认", "确认失败")
            frame[:] = 255
            record_frame(np.ones_like(frame))
            return False

        with patch("builtins.print"):
            _, report = run_task_call(task)
        self.assertEqual(int(report.frame.max()), 0)

    def test_next_call_and_next_stage_do_not_inherit_handled_errors(self):
        logger = TaskLogger("任务")

        def handled():
            logger.set_stage("寻找入口")
            logger.error("入口", "暂时未找到")
            logger.set_stage("返回庭院")
            return True

        with patch("builtins.print"):
            _, first = run_task_call(handled)
            _, second = run_task_call(lambda: True)
        self.assertEqual(first.stage, "返回庭院")
        self.assertIsNone(first.reason)
        self.assertIsNone(second.stage)
        self.assertIsNone(second.reason)

    def test_exception_keeps_stage_and_frame(self):
        logger = TaskLogger("任务")
        frame = object()

        def task():
            logger.set_stage("读取体力")
            record_frame(frame)
            raise RuntimeError("OCR unavailable")

        with patch("builtins.print"):
            _, report = run_task_call(task)
        self.assertEqual(report.stage, "读取体力")
        self.assertIn("OCR unavailable", report.reason)
        self.assertIs(report.frame, frame)

    def test_stop_during_capture_prevents_matching_and_clicking(self):
        stop = threading.Event()
        backend = SimpleNamespace(adb_click=Mock())

        def capture():
            stop.set()
            return object()

        backend.take_screenshot = capture
        device = TaskDevice(backend)
        matched = Mock()

        def task():
            frame = device.screenshot()
            matched(frame)
            device.click(1, 2)

        _, report = run_task_call(task, stop_event=stop)
        self.assertTrue(report.cancelled)
        self.assertIsNone(report.exception)
        matched.assert_not_called()
        backend.adb_click.assert_not_called()

    def test_deferred_stop_finishes_current_call_including_device_cleanup(self):
        stop = threading.Event()
        backend = SimpleNamespace(take_screenshot=Mock(return_value=object()), adb_click=Mock())
        device = TaskDevice(backend)
        steps = []

        def task():
            steps.append("detect")
            stop.set()
            device.screenshot()
            device.click(10, 20)
            steps.append("return_to_courtyard")
            return True

        value, report = run_task_call(task, stop_event=stop, finish_current=True)
        self.assertTrue(value)
        self.assertFalse(report.cancelled)
        self.assertIsNone(report.exception)
        self.assertEqual(steps, ["detect", "return_to_courtyard"])
        backend.adb_click.assert_called_once_with(10, 20)

    def test_deferred_stop_does_not_start_a_call_if_stop_is_already_requested(self):
        stop = threading.Event()
        stop.set()
        runner = Mock(return_value=True)
        _, report = run_task_call(runner, stop_event=stop, finish_current=True)
        self.assertTrue(report.cancelled)
        runner.assert_not_called()

    def test_recovery_reports_frame_and_controller_saves_only_once(self):
        frame = object()
        attempt = recovery._RecoveryAttempt(False, "按钮没有生效", frame, "stalled_action")
        with patch.object(recovery, "_attempt_recovery_to_courtyard", return_value=attempt), patch.object(
            recovery, "capture_error_screenshot",
        ) as local_capture, patch.object(task_services, "capture_error_screenshot") as capture:
            success, _ = task_services._run_task_recovery(recovery.recover_to_courtyard, None)
        self.assertFalse(success)
        local_capture.assert_not_called()
        capture.assert_called_once_with("task_recovery", "stalled_action", frame=frame)

    def test_startup_recovery_inside_execution_only_reports_its_scene(self):
        frame = object()
        with patch.object(startup, "capture_error_screenshot") as capture, patch("builtins.print"):
            result, report = run_task_call(lambda: startup._blocked("未知界面", frame))
        self.assertFalse(result.success)
        self.assertIs(result.frame, frame)
        self.assertIs(report.frame, frame)
        capture.assert_not_called()

    def test_explicit_warning_does_not_turn_cleanup_failure_into_an_error(self):
        logger = TaskLogger("任务")
        with patch("builtins.print") as output:
            _, report = run_task_call(lambda: logger.legacy_print("[WARN] 已完成，但未能退出"))
        self.assertIn("[WARN]", output.call_args.args[0])
        self.assertIsNone(report.reason)


class ToolReportTests(unittest.TestCase):
    def test_tool_failure_exception_and_stop_use_the_same_reporting_boundary(self):
        for mode in ("failure", "exception", "stopped", "stopped_exception"):
            with self.subTest(mode=mode), ExitStack() as stack:
                stop, frame = threading.Event(), object()
                logger = TaskLogger("剧情跳过")

                def task(stop_event):
                    logger.set_stage("准备战斗")
                    record_frame(frame)
                    if mode.startswith("stopped"):
                        stop_event.set()
                        if mode == "stopped_exception":
                            raise RuntimeError("capture ended after stop")
                    elif mode == "exception":
                        raise RuntimeError("prepare exception")
                    else:
                        logger.error("准备", "准备点击未生效")
                    return False

                dashboard = SimpleNamespace(
                    settings=dict(DEFAULT_SETTINGS), tool_stop_event=stop,
                    append_tool_log=Mock(), _report_ui_exception=Mock(), ui_queue=queue.Queue(),
                    _load_tool_module=lambda _: SimpleNamespace(run=task),
                )
                stack.enter_context(patch.object(automation, "configure_runtime_paths"))
                stack.enter_context(patch.object(automation, "configure_mumu_target", return_value=True))
                stack.enter_context(patch("module.diagnostics.configure_error_screenshots"))
                capture = stack.enter_context(patch("module.diagnostics.capture_error_screenshot"))
                ToolsPageMixin._tool_worker(dashboard, "story_skip")
                event, payload = dashboard.ui_queue.get_nowait()
                self.assertEqual(event, "tool_finished")
                if mode.startswith("stopped"):
                    capture.assert_not_called()
                    self.assertTrue(payload["success"])
                    self.assertTrue(payload["stopped"])
                    dashboard._report_ui_exception.assert_not_called()
                else:
                    capture.assert_called_once_with("story_skip", "准备战斗", frame=frame)
                    self.assertFalse(payload["success"])
                if mode == "exception":
                    dashboard._report_ui_exception.assert_called_once()


if __name__ == "__main__":
    unittest.main()

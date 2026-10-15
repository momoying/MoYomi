"""日志精简回归：验证正常输出和调试信息，不连接模拟器。"""

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from module import automation
from module.logging import TaskLogger
from module.task_execution import run_task_call


class TaskLoggingTests(unittest.TestCase):
    def logger(self):
        logger = TaskLogger("协战奖励")
        logger.debug_enabled = False
        return logger

    def test_normal_challenge_has_one_action_and_no_confirmation_noise(self):
        logger = self.logger()
        output = io.StringIO()
        rect = (1144, 587, 1237, 682)

        def task():
            logger.set_stage("发起协战挑战")
            logger.match("challenge", "challenge", 1.0, 0.9, rect)
            with patch.object(automation, "take_screenshot", return_value=object()), patch.object(
                automation, "crop_and_match", return_value=(0.2, rect)
            ):
                self.assertTrue(automation.click_template_until_disappears(
                    (0, 0), (1280, 720), "challenge.png", rect,
                    post_click_delay=0,
                    click_callback=lambda r: logger.click("挑战", "挑战", r, (1176, 638)),
                    log_callback=lambda message: logger.message("挑战", message),
                ))
            logger.set_stage("战斗及奖励结算")
            logger.legacy_print("战斗胜利")
            return True

        with redirect_stdout(output):
            result, report = run_task_call(task)
        lines = output.getvalue().splitlines()
        self.assertTrue(result)
        self.assertEqual(report.stage, "战斗及奖励结算")
        self.assertIsNone(report.reason)
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].endswith("[协战奖励/挑战] 点击 挑战 (1176, 638)"))
        self.assertTrue(lines[1].endswith("[协战奖励/结算] 战斗胜利"))

    def test_debug_keeps_vision_and_confirmation_details(self):
        with patch.dict("os.environ", {"MOYOMI_LOG_LEVEL": "DEBUG"}):
            logger = TaskLogger("协战奖励")
        output = io.StringIO()
        rect = (10, 20, 30, 40)
        with redirect_stdout(output):
            logger.match("challenge", "challenge", 0.99, 0.9, rect)
            logger.click("challenge", "挑战", rect, (20, 30))
            logger.message("challenge", "[DEBUG] 挑战点击后仍可见，匹配分数 0.990")
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertIn("[DEBUG]", lines[0])
        self.assertIn("分数=0.990", lines[0])
        self.assertIn("区域=(10, 20, 30, 40)", lines[1])
        self.assertIn("[DEBUG]", lines[2])

    def test_hidden_debug_does_not_hide_timeout_or_change_failure_report(self):
        logger = self.logger()
        output = io.StringIO()

        def task():
            logger.set_stage("发起协战挑战")
            logger.message("挑战", "[DEBUG] 暂时未能确认点击")
            return automation.click_template_until_disappears(
                (0, 0), (1280, 720), "challenge.png", (10, 20, 30, 40),
                timeout=0, label="挑战",
                log_callback=lambda message: logger.message("挑战", message),
            )

        with redirect_stdout(output):
            result, report = run_task_call(task)
        self.assertFalse(result)
        self.assertEqual(report.stage, "发起协战挑战")
        self.assertEqual(report.reason, "挑战点击后未在 0 秒内消失")
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        self.assertIn("[ERROR] [协战奖励/挑战]", output.getvalue())

    def test_legacy_messages_do_not_invent_or_repeat_scenes(self):
        logger = self.logger()
        output = io.StringIO()
        with redirect_stdout(output):
            logger.legacy_print("当前账号进度已保存")
            logger.info("协战奖励", "完成 5/12 场")
            logger.legacy_print("[WARN] 已完成，但未能退出")
        lines = output.getvalue().splitlines()
        self.assertTrue(lines[0].endswith("[协战奖励] 当前账号进度已保存"))
        self.assertTrue(lines[1].endswith("[协战奖励] 完成 5/12 场"))
        self.assertIn("[WARN] [协战奖励]", lines[2])


if __name__ == "__main__":
    unittest.main()

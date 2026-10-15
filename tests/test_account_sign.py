"""登录阶段回归：系统弹窗优先，背景登录按钮不能触发误点击。"""

import unittest
from contextlib import ExitStack
from unittest.mock import patch

import cv2
import numpy as np

from tasks.Account import sign


class AccountSignTests(unittest.TestCase):
    def test_system_selection_takes_priority_over_login(self):
        rect = (500, 350, 570, 410)
        for system in ("ios", "android"):
            with self.subTest(system=system), ExitStack() as stack:
                stack.enter_context(patch.object(sign, "_take_frame", return_value=object()))
                stack.enter_context(patch.object(
                    sign, "_match", return_value=(1.0, rect),
                ))
                click = stack.enter_context(patch.object(sign, "_click_region"))
                stack.enter_context(patch.object(sign.time, "sleep"))
                stack.enter_context(patch.object(sign, "print"))
                self.assertTrue(sign._wait_and_select_system(system, 5.0))
                click.assert_called_once_with(rect, f"{'IOS' if system == 'ios' else 'Android'} 系统")

    def test_other_system_blocks_background_login_click(self):
        rect = (500, 350, 570, 410)
        with ExitStack() as stack:
            stack.enter_context(patch.object(sign, "_take_frame", return_value=object()))
            stack.enter_context(patch.object(
                sign, "_match",
                side_effect=lambda frame, name: (0.49, None) if name == "ios" else (1.0, rect),
            ))
            stack.enter_context(patch.object(sign.time, "monotonic", side_effect=[0, 0, 6]))
            click = stack.enter_context(patch.object(sign, "_click_region"))
            stack.enter_context(patch.object(sign, "_report_timeout"))
            stack.enter_context(patch.object(sign, "print"))
            self.assertFalse(sign._wait_and_select_system("ios", 5.0))
            click.assert_not_called()

    def test_unverified_system_cannot_succeed_from_enter_game_ocr(self):
        with ExitStack() as stack:
            stack.enter_context(patch.object(sign, "_take_frame", return_value=object()))
            stack.enter_context(patch.object(sign, "_match", return_value=(0.49, None)))
            stack.enter_context(patch.object(sign, "_recognize_current_region", return_value=("same", ["狐之宴"])))
            stack.enter_context(patch.object(sign, "_ocr_texts_in_region", return_value=[("进入游戏", 0.99)]))
            stack.enter_context(patch.object(sign.time, "monotonic", side_effect=[0, 0, 6]))
            click = stack.enter_context(patch.object(sign, "_click_region"))
            save = stack.enter_context(patch.object(sign, "_report_timeout"))
            stack.enter_context(patch.object(sign, "print"))
            self.assertFalse(sign._wait_and_select_system("ios", 5.0))
            click.assert_not_called()
            save.assert_called_once()

    def test_dimmed_login_does_not_override_real_system_templates(self):
        # 构造回归画面验证算法和控制流，不作为朋友现场截图。
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        template = cv2.imread(sign.TEMPLATES["login"])
        frame[418:474, 407:885] = cv2.convertScaleAbs(template, alpha=0.5)
        for name, x in (("ios", 540), ("android", 675)):
            template = cv2.imread(sign.TEMPLATES[name])
            h, w = template.shape[:2]
            frame[350:350 + h, x:x + w] = template
        with patch.object(sign.LOGGER, "match"):
            for name in ("ios", "android"):
                score, rect = sign._match(frame, name)
                self.assertGreater(score, 0.99)
                self.assertIsNotNone(rect)
            score, rect = sign._match(frame, "login")
            self.assertGreater(score, 0.99)
            self.assertIsNone(rect)
        with (
            patch.object(sign, "_take_frame", return_value=frame),
            patch.object(sign, "_click_region") as click,
            patch.object(sign.time, "sleep"),
            patch.object(sign.LOGGER, "match"),
            patch.object(sign, "print"),
        ):
            self.assertTrue(sign._wait_and_select_system("ios", 5.0))
            self.assertEqual(click.call_args.args[1], "IOS 系统")

    def test_login_retry_records_system_scores_and_matching_frame(self):
        frame, rect = object(), (407, 418, 885, 474)
        with ExitStack() as stack:
            stack.enter_context(patch.object(sign, "_take_frame", return_value=frame))
            stack.enter_context(patch.object(
                sign, "_match",
                side_effect=lambda frame, name: (1.0, rect) if name == "login" else (0.49, None),
            ))
            stack.enter_context(patch.object(sign.time, "monotonic", side_effect=[0, 0, 1, 6]))
            stack.enter_context(patch.object(sign.time, "sleep"))
            click = stack.enter_context(patch.object(sign, "_click_region"))
            report = stack.enter_context(patch.object(sign, "_report_timeout"))
            log = stack.enter_context(patch.object(sign, "print"))
            self.assertFalse(sign._wait_and_select_system("ios", 5.0))
            self.assertEqual(click.call_count, 2)
            report.assert_called_once_with("wait_ios", frame)
            self.assertIn("当前帧 IOS 分数 0.490", log.call_args_list[0].args[0])

    def test_enter_game_ocr_accepts_split_text_and_rejects_low_confidence(self):
        cases = (
            ([("进 入", 0.98), ("游戏", 0.99)], 0.99),
            ([("进入游戏", 0.59)], None),
            ([("其他文字", 0.99)], None),
            ([], None),
        )
        for texts, expected in cases:
            with self.subTest(texts=texts), patch.object(sign, "_ocr_texts_in_region", return_value=texts):
                confidence, raw_texts = sign._recognize_enter_game(object())
                self.assertEqual(confidence, expected)
                self.assertEqual(raw_texts, [text for text, _ in texts])

    def test_enter_game_click_waits_for_two_absent_frames(self):
        with ExitStack() as stack:
            stack.enter_context(patch.object(sign, "_take_frame", return_value=object()))
            stack.enter_context(patch.object(sign, "_match", return_value=(0.2, None)))
            ocr = stack.enter_context(patch.object(
                sign, "_ocr_texts_in_region", side_effect=[[("进入游戏", 0.99)], [], []],
            ))
            click = stack.enter_context(patch.object(sign, "_click_region"))
            stack.enter_context(patch.object(sign.time, "sleep"))
            stack.enter_context(patch.object(sign.LOGGER, "match"))
            stack.enter_context(patch.object(sign, "print"))
            self.assertTrue(sign._wait_and_enter_game("ios", 5.0))
            click.assert_called_once_with(sign.ENTER_GAME_CLICK_REGION, "进入游戏")
            self.assertEqual(ocr.call_count, 3)

    def test_enter_game_timeout_reports_actual_ocr_texts(self):
        with ExitStack() as stack:
            stack.enter_context(patch.object(sign, "_take_frame", return_value=object()))
            stack.enter_context(patch.object(sign, "_match", return_value=(0.2, None)))
            stack.enter_context(patch.object(sign, "_ocr_texts_in_region", return_value=[("游戈", 0.9)]))
            stack.enter_context(patch.object(sign.time, "monotonic", side_effect=[0, 0, 6]))
            stack.enter_context(patch.object(sign, "_report_timeout"))
            log = stack.enter_context(patch.object(sign, "print"))
            self.assertFalse(sign._wait_and_enter_game("ios", 5.0))
            self.assertIn("游戈", log.call_args.args[0])


if __name__ == "__main__":
    unittest.main()

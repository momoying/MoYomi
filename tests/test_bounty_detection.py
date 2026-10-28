"""新版悬赏页回归：真实截图识别、同卡奖励关联和退出流程。"""

import unittest
from pathlib import Path
from unittest.mock import patch

import cv2

from module import recovery, startup
from tasks.Bounty import bounty


class BountyDetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures = Path(__file__).parent / "fixtures"
        cls.frames = {
            name: cv2.imread(str(fixtures / f"bounty_{name}.png"))
            for name in ("cooperation", "sharing")
        }
        for name, frame in cls.frames.items():
            if frame is None:
                raise AssertionError(f"Missing bounty fixture: {name}")

    def setUp(self):
        self.enterContext(patch.object(bounty, "print"))
        self.enterContext(patch.object(bounty.LOGGER, "match"))

    def scene(self, markers=(), rewards=()):
        # 从真实页面移除标记、奖励，再移动原图像素构造不同卡位组合。
        frame = self.frames["sharing"].copy()
        frame[105:165, 90:1200] = 0
        frame[530:610, 90:1200] = 0
        offsets = (0, 283, 565, 848)
        for name, column in markers:
            left = 311 + offsets[column]
            frame[121:149, left:left + 28] = self.frames[name][121:149, 311:339]
        for column in rewards:
            left = 230 + offsets[column]
            frame[534:607, left:left + 73] = self.frames["sharing"][534:607, 230:303]
        return frame

    def test_real_screenshots_distinguish_collaboration_types(self):
        for name, frame in self.frames.items():
            with self.subTest(name=name):
                found, kind, _, _, magatama_score = bounty.detect_magatama_collaboration(frame)
                self.assertTrue(found)
                self.assertEqual(kind, name)
                self.assertGreaterEqual(magatama_score, bounty.MATCH_THRESHOLD)

    def test_each_marker_finds_its_reward_in_all_four_columns(self):
        for name in self.frames:
            for column in range(4):
                with self.subTest(name=name, column=column):
                    frame = self.scene(((name, column),), (column,))
                    found, kind, *_ = bounty.detect_magatama_collaboration(frame)
                    self.assertTrue(found)
                    self.assertEqual(kind, name)

    def test_adjacent_card_reward_does_not_count(self):
        for name in self.frames:
            for column, neighbor in ((0, 1), (1, 0), (1, 2), (2, 1), (2, 3), (3, 2)):
                with self.subTest(name=name, column=column, neighbor=neighbor):
                    frame = self.scene(((name, column),), (neighbor,))
                    found, kind, *_ = bounty.detect_magatama_collaboration(frame)
                    self.assertFalse(found)
                    self.assertIsNone(kind)

    def test_rewards_without_markers_and_markers_without_rewards_do_not_count(self):
        for frame in (
            self.scene(rewards=(0, 1, 2, 3)),
            self.scene((("cooperation", 0), ("sharing", 3))),
        ):
            found, kind, *_ = bounty.detect_magatama_collaboration(frame)
            self.assertFalse(found)
            self.assertIsNone(kind)

    def test_sharing_has_priority_over_normal_collaboration(self):
        frame = self.scene((("cooperation", 0), ("sharing", 3)), (0, 3))
        self.assertEqual(bounty.detect_magatama_collaboration(frame)[:2], (True, "sharing"))

    def test_all_exit_routes_match_and_click_inside_the_button(self):
        for name, frame in self.frames.items():
            with self.subTest(name=name):
                score, rect = bounty._match(frame, "back")
                self.assertGreaterEqual(score, bounty.MATCH_THRESHOLD)
                self.assertEqual(rect, (1218, 73, 1253, 110))
                self.assertEqual(startup._match(frame, "bounty_close")[1], rect)
                self.assertEqual(recovery._match_state(frame, "bounty_close")[1], rect)
                self.assertEqual(recovery._detect_state(frame)[0], "bounty_close")
                with patch.object(bounty.DEVICE, "click") as click, patch.object(
                    bounty.utils, "take_screenshot", return_value=frame * 0,
                ), patch.object(bounty.time, "sleep"):
                    self.assertTrue(bounty._click_and_confirm("back", "退出", rect, 1.0))
                click.assert_called_once()
                x, y = click.call_args.args
                self.assertTrue(rect[0] < x < rect[2] and rect[1] < y < rect[3])

    def test_check_bounty_returns_structured_result_only_after_successful_exit(self):
        for name, expected in (
            ("cooperation", bounty.BountyResult.NORMAL_MAGATAMA_COLLABORATION),
            ("sharing", bounty.BountyResult.SHARING_MAGATAMA_COLLABORATION),
        ):
            for exit_succeeded in (True, False):
                with self.subTest(name=name, exit_succeeded=exit_succeeded):
                    frame = self.frames[name]
                    with patch.object(bounty.utils, "connect_to_mumu"), patch.object(
                        bounty, "_wait_for_template", return_value=(frame, (1218, 73, 1253, 110), 0.99),
                    ), patch.object(bounty, "_click_and_confirm", return_value=True), patch.object(
                        bounty, "_take_frame", return_value=frame,
                    ), patch.object(bounty, "_wait_and_click", return_value=exit_succeeded) as leave:
                        result = bounty.check_bounty()
                    self.assertEqual(result, expected if exit_succeeded else bounty.BountyResult.ERROR)
                    leave.assert_called_once_with("back", "悬赏页退出按钮", bounty.BACK_WAIT_SECONDS)


if __name__ == "__main__":
    unittest.main()

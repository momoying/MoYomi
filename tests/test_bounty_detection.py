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
        cls.lower_frames = {
            name: cv2.imread(str(fixtures / f"bounty_lower_{name}.png"))
            for name in ("cooperation", "magatama")
        }
        for name, frame in {**cls.frames, **cls.lower_frames}.items():
            if frame is None:
                raise AssertionError(f"Missing bounty fixture: {name}")

    def setUp(self):
        self.enterContext(patch.object(bounty, "print"))
        self.enterContext(patch.object(bounty.LOGGER, "match"))

    def scene(self, markers=(), rewards=(), offsets=(0, 268, 536, 804)):
        # 从真实页面移除标记、奖励，再移动原图像素构造不同卡位组合。
        frame = self.lower_frames["magatama"].copy()
        frame[220:370, 100:1260] = 0
        frame[530:610, 90:1200] = 0
        for name, column in markers:
            left = 133 + offsets[column]
            # 暂无新版“享”截图，只用旧“享”验证定位逻辑，不作为新版外观证据。
            marker = (
                self.lower_frames["cooperation"][308:336, 133:161]
                if name == "cooperation" else self.frames["sharing"][121:149, 311:339]
            )
            frame[308:336, left:left + 28] = marker
        for column in rewards:
            left = 250 + offsets[column]
            frame[525:595, left:left + 70] = self.lower_frames["magatama"][525:595, 250:320]
        return frame

    def test_latest_screenshots_reuse_marker_magatama_and_back_templates(self):
        score, matches = bounty._find_all_matches(self.lower_frames["cooperation"], "cooperation")
        self.assertGreaterEqual(score, bounty.MATCH_THRESHOLD)
        self.assertEqual([rect for _, rect in matches], [(133, 308, 161, 336)])
        score, rect = bounty.DEVICE.match(
            (118, 530), (368, 610), bounty.TEMPLATES["magatama"],
            frame=self.lower_frames["magatama"],
        )
        self.assertGreaterEqual(score, bounty.MATCH_THRESHOLD)
        self.assertEqual(rect, (265, 533, 308, 575))
        # 第一张有协无勾玉，第二张有勾玉无协，两张均不应报勾协。
        for frame in self.lower_frames.values():
            self.assertEqual(bounty.detect_magatama_collaboration(frame)[:2], (False, None))

    def test_relocated_markers_distinguish_collaboration_types(self):
        for name in self.frames:
            with self.subTest(name=name):
                frame = self.scene(((name, 0),), (0,))
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

    def test_centered_three_card_positions_do_not_require_four_fixed_slots(self):
        for name in self.frames:
            for column in range(3):
                with self.subTest(name=name, column=column):
                    frame = self.scene(((name, column),), (column,), offsets=(134, 402, 670))
                    self.assertEqual(bounty.detect_magatama_collaboration(frame)[:2], (True, name))

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
        for name, frame in self.lower_frames.items():
            with self.subTest(name=name):
                score, rect = bounty._match(frame, "back")
                self.assertGreaterEqual(score, bounty.MATCH_THRESHOLD)
                self.assertEqual(rect, (1196, 90, 1231, 127))
                self.assertEqual(startup._match(frame, "bounty_close")[1], rect)
                self.assertEqual(recovery._match_state(frame, "bounty_close")[1], rect)
                # 新图的关闭按钮也命中好友模板；保留公共恢复的保守歧义判定。
                self.assertEqual(recovery._detect_state(frame)[0], "ambiguous")
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
                    frame = self.scene(((name, 0),), (0,))
                    with patch.object(bounty.utils, "connect_to_mumu"), patch.object(
                        bounty, "_wait_for_template", return_value=(frame, (1196, 90, 1231, 127), 0.99),
                    ), patch.object(bounty, "_click_and_confirm", return_value=True), patch.object(
                        bounty, "_take_frame", return_value=frame,
                    ), patch.object(bounty, "_wait_and_click", return_value=exit_succeeded) as leave:
                        result = bounty.check_bounty()
                    self.assertEqual(result, expected if exit_succeeded else bounty.BountyResult.ERROR)
                    leave.assert_called_once_with("back", "悬赏页退出按钮", bounty.BACK_WAIT_SECONDS)


if __name__ == "__main__":
    unittest.main()

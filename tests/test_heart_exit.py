"""同心队退出回归：真实弹窗模板匹配、单次点击和失败停止。"""

import unittest
import threading
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from module.assets import CommonUIAssets, StartupAssets
from module import recovery
from tasks.Exp.assets import ExpMonsterAssets
from tasks.HeartTeam import heart_team as heart
from tasks.Mail.assets import MailAssets
from tasks.Merchant.assets import MerchantAssets


class HeartExitTests(unittest.TestCase):
    def setUp(self):
        self.clock = 0.0
        self.enterContext(patch.object(heart.time, "monotonic", side_effect=lambda: self.clock))
        self.enterContext(patch.object(heart.time, "sleep", side_effect=self.advance))
        self.enterContext(patch.object(heart, "print"))

    def advance(self, seconds):
        self.clock += seconds

    def test_latest_confirm_matches_reported_exit_dialog_and_all_normal_confirm_routes(self):
        crop = cv2.imread(str(Path(__file__).parent / "fixtures" / "heart_exit_confirm.png"))
        self.assertIsNotNone(crop)
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        frame[350:520, 600:900] = crop
        score, rect = heart._match(frame, "confirm")
        self.assertIsNotNone(rect)
        self.assertGreaterEqual(score, heart.ASSETS.I_CONFIRM.threshold)
        self.assertEqual(recovery._detect_state(frame)[0], "exit_confirm")
        for asset in (
            heart.ASSETS.I_CONFIRM,
            heart.ASSETS.I_RESERVE_CONFIRM,
            StartupAssets.I_EXIT_CONFIRM,
            ExpMonsterAssets.I_EXIT_CONFIRM,
            MerchantAssets.I_CONFIRM,
            MailAssets.I_CONFIRM,
        ):
            self.assertEqual(asset.file, CommonUIAssets.I_CONFIRM.file)

    def test_confirm_that_remains_visible_is_not_clicked_again(self):
        rect = (660, 402, 850, 476)
        self.enterContext(patch.object(heart, "_take_frame", return_value=object()))
        self.enterContext(patch.object(heart, "_match", return_value=(0.95, rect)))
        click = self.enterContext(patch.object(heart, "_click_rect"))

        self.assertFalse(heart._click_and_confirm("confirm", "退出确认", rect, 2.0))
        click.assert_called_once_with(rect, "退出确认")

    def test_normal_exit_handles_both_confirm_dialogs_with_one_click_each(self):
        state = ["challenge"]
        actions = []
        visible = {
            "challenge": "back",
            "panel_confirm": "confirm",
            "gathering": "exit_team",
            "gather_confirm": "confirm",
            "courtyard": "main",
        }
        next_state = {
            "challenge": "panel_confirm",
            "panel_confirm": "gathering",
            "gathering": "gather_confirm",
            "gather_confirm": "courtyard",
        }

        def click(rect, label):
            actions.append(visible[state[0]])
            state[0] = next_state[state[0]]

        self.enterContext(patch.object(heart, "_take_frame", side_effect=lambda **kwargs: state[0]))
        self.enterContext(patch.object(
            heart, "_match", side_effect=lambda frame, name:
            (0.95, (20, 20, 70, 70)) if name == visible[frame] else (0.0, None),
        ))
        self.enterContext(patch.object(heart, "_click_rect", side_effect=click))
        self.enterContext(patch.object(heart, "_click_exit_team_center", side_effect=click))

        self.assertTrue(heart._leave_team_to_courtyard())
        self.assertEqual(actions, ["back", "confirm", "exit_team", "confirm"])
        self.assertEqual(state[0], "courtyard")

    def test_recovery_stops_after_one_back_click_when_no_confirm_or_page_change(self):
        rect = (26, 15, 75, 64)
        self.enterContext(patch.object(heart, "_take_frame", return_value=object()))
        self.enterContext(patch.object(
            heart, "_match",
            side_effect=lambda frame, name: (0.98, rect) if name == "back" else (0.0, None),
        ))
        click = self.enterContext(patch.object(heart, "_click_rect"))

        self.assertFalse(heart.recover_after_completed_battles(timeout=20.0))
        click.assert_called_once_with(rect, "战后恢复/左上角返回")
        self.assertLess(self.clock, 20.0)

    def test_exit_x_is_clicked_once_when_confirm_does_not_appear(self):
        rect = (820, 20, 885, 85)
        click = self.enterContext(patch.object(heart, "_click_exit_team_center"))
        self.enterContext(patch.object(heart, "_template_appears", return_value=False))

        self.assertFalse(heart._click_exit_team_until_confirm(exit_rect=rect, label="退出集结"))
        click.assert_called_once_with(rect, "退出集结")

    def test_recovery_exit_steps_share_outer_deadline(self):
        state = ["gathering"]
        actions = []
        visible = {"gathering": "exit_team", "dialog": "confirm", "missing_back": None}

        def click_x(*args):
            actions.append("exit_team")
            state[0] = "dialog"

        def click_confirm(*args):
            actions.append("confirm")
            state[0] = "missing_back"

        self.enterContext(patch.object(heart, "_take_frame", side_effect=lambda **kwargs: state[0]))
        self.enterContext(patch.object(
            heart, "_match", side_effect=lambda frame, name:
            (0.95, (20, 20, 70, 70)) if name == visible[frame] else (0.0, None),
        ))
        self.enterContext(patch.object(heart, "_click_exit_team_center", side_effect=click_x))
        self.enterContext(patch.object(heart, "_click_rect", side_effect=click_confirm))

        self.assertFalse(heart.recover_after_completed_battles(timeout=2.0))
        self.assertEqual(actions, ["exit_team", "confirm"])
        self.assertLessEqual(self.clock, 2.0)

    def test_recovery_stops_inside_exit_steps_without_clicking_confirm(self):
        stop = threading.Event()
        self.enterContext(patch.object(heart, "_take_frame", return_value=object()))
        self.enterContext(patch.object(
            heart, "_match", side_effect=lambda frame, name:
            (0.95, (20, 20, 70, 70)) if name in {"exit_team", "confirm"} else (0.0, None),
        ))
        # 从已识别的退出叉号进入内部流程，点击后立即收到停止请求。
        self.enterContext(patch.object(heart, "_click_exit_team_center", side_effect=lambda *args: stop.set()))
        click = self.enterContext(patch.object(heart, "_click_rect"))
        self.assertFalse(heart._exit_gathering_to_courtyard(
            exit_rect=(20, 20, 70, 70), deadline=2.0, stop_event=stop,
        ))
        click.assert_not_called()
        self.assertEqual(self.clock, 0.0)

    def test_generic_fallback_receives_only_remaining_timeout(self):
        self.enterContext(patch.object(heart, "_take_frame", return_value=object()))
        self.enterContext(patch.object(heart, "_match", return_value=(0.0, None)))
        fallback = self.enterContext(patch.object(heart, "recover_to_courtyard", return_value=False))

        self.assertFalse(heart.recover_after_completed_battles(timeout=5.0, fallback=fallback))
        fallback.assert_called_once_with(None, timeout=2.0)

    def test_expired_deadline_does_not_start_an_exit_click(self):
        click = self.enterContext(patch.object(heart, "_click_exit_team_center"))
        self.assertFalse(heart._exit_gathering_to_courtyard(
            exit_rect=(20, 20, 70, 70), deadline=0.0,
        ))
        click.assert_not_called()


if __name__ == "__main__":
    unittest.main()

"""任务超时恢复的页面识别与安全动作。"""

import threading
import unittest
from unittest.mock import patch

import numpy as np

from module import recovery


class RecoveryScenarioTests(unittest.TestCase):
    def setUp(self):
        self.clock = 0.0
        self.templates = {}
        self.frames = []
        self.screenshot_index = 0
        self.clicks = []
        self.backs = []
        self.saved = []
        self.match_score = 0.99

        self.path_by_name = {
            name: str(spec.path) for name, spec in recovery.StartupAssets.SPECS.items()
        }
        self.path_by_name.update({
            name: str(asset.file) for name, asset in recovery.RecoveryAssets.IMAGES.items()
        })
        self.path_by_name.update({
            name: str(spec.path) for name, spec in recovery.ACTION_SPECS
        })
        self.patches = [
            patch.object(recovery.DEVICE, "match", side_effect=self.match),
            patch.object(recovery.DEVICE, "screenshot", side_effect=self.screenshot),
            patch.object(recovery.DEVICE, "click", side_effect=lambda x, y: self.clicks.append((x, y))),
            patch.object(recovery.DEVICE, "back", side_effect=self.back),
            patch.object(recovery, "_save_failure_screenshot", side_effect=self.save),
            patch.object(recovery.time, "monotonic", side_effect=lambda: self.clock),
            patch.object(recovery.time, "sleep", side_effect=self.sleep),
            patch.object(recovery.LOGGER, "match"),
            patch.object(recovery.LOGGER, "info"),
            patch.object(recovery.LOGGER, "error"),
            patch.object(recovery.LOGGER, "click"),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def frame(self, *names):
        code = (len(self.templates) + 1) * 10
        image = np.full((72, 128, 3), code, dtype=np.uint8)
        self.templates[code] = {self.path_by_name[name] for name in names}
        return image

    def match(self, start, end, path, *, frame):
        names = self.templates.get(int(frame[0, 0, 0]), set())
        return (self.match_score, (10, 10, 30, 30)) if path in names else (0.0, None)

    def screenshot(self):
        frame = self.frames[min(self.screenshot_index, len(self.frames) - 1)]
        self.screenshot_index += 1
        return frame

    def back(self):
        self.backs.append(True)
        return True

    def save(self, frame, stage, keep_count):
        self.saved.append((frame, stage, keep_count))
        return f"{stage}.png"

    def sleep(self, seconds):
        self.clock += seconds

    def recover(self, frames, *, timeout=10, unknown_grace=1, **kwargs):
        self.frames = frames
        return recovery.recover_to_courtyard(
            timeout=timeout, unknown_grace=unknown_grace, **kwargs
        )

    def test_recovery_action_priority_unchanged(self):
        self.assertEqual(
            [name for name, _ in recovery.ACTION_SPECS],
            ["courtyard", "back", "close_pink", "close_red", "phone_bind_cancel", "phone_bind", "coop_reward"],
        )

    def test_overlay_over_courtyard_is_handled_before_success(self):
        overlay = self.frame("main", "phone_bind_cancel")
        main = self.frame("main")
        result = self.recover([overlay, overlay, main, main])
        self.assertTrue(result.success)
        self.assertEqual(len(self.clicks), 1)
        self.assertEqual(self.backs, [])

    def test_unclassified_close_button_over_courtyard_is_handled(self):
        covered = self.frame("main", "close_pink")
        main = self.frame("main")
        result = self.recover([covered, covered, main, main])
        self.assertTrue(result.success)
        self.assertEqual(len(self.clicks), 1)

    def test_direct_close_button_over_courtyard_is_handled(self):
        covered = self.frame("main", "friend_close")
        main = self.frame("main")
        result = self.recover([covered, covered, main, main])
        self.assertTrue(result.success)
        self.assertEqual(len(self.clicks), 1)

    def test_room_return_then_exit_confirmation(self):
        room = self.frame("prepare_button", "ready_room", "exp_back")
        confirm = self.frame("room_exit_confirm", "prepare_button", "exp_back")
        main = self.frame("main")
        result = self.recover([room, room, confirm, confirm, main, main])
        self.assertTrue(result.success)
        self.assertEqual(len(self.clicks), 2)
        self.assertEqual(self.backs, [])

    def test_room_uses_confirmed_generic_return_when_room_button_missing(self):
        room = self.frame("prepare_button", "courtyard")
        confirm = self.frame("room_exit_confirm", "prepare_button")
        main = self.frame("main")
        result = self.recover([room, room, confirm, confirm, main, main])
        self.assertTrue(result.success)
        self.assertEqual(len(self.clicks), 2)

    def test_room_does_not_press_return_again_while_waiting_for_confirmation(self):
        room = self.frame("prepare_button", "exp_back")
        result = self.recover([room], unknown_grace=1)
        self.assertFalse(result.success)
        self.assertEqual(self.saved[-1][1], "room_exit_confirm_missing")
        self.assertEqual(len(self.clicks), 1)

    def test_known_pages_return_one_layer_at_a_time(self):
        challenge = self.frame("coop_challenge", "back", "close_pink", "courtyard")
        dungeon = self.frame("coop_dungeon_card")
        friend = self.frame("friend_close")
        main = self.frame("main")
        result = self.recover([challenge, challenge, dungeon, dungeon, friend, friend, main, main])
        self.assertTrue(result.success)
        self.assertEqual(len(self.clicks), 2)
        self.assertEqual(len(self.backs), 1)

    def test_battle_waits_without_clicking(self):
        battle = self.frame("battle", "back")
        result = self.recover([battle], timeout=2)
        self.assertFalse(result.success)
        self.assertEqual(self.saved[-1][1], "timeout")
        self.assertEqual(self.clicks, [])
        self.assertEqual(self.backs, [])

    def test_unrecorded_settlement_stops_without_collecting(self):
        settlement = self.frame("coop_settlement", "back")
        result = self.recover([settlement])
        self.assertFalse(result.success)
        self.assertEqual(self.saved[-1][1], "settlement_unrecorded")
        self.assertEqual(result.screenshot, "settlement_unrecorded.png")
        self.assertEqual(self.clicks, [])

    def test_completed_coop_reward_uses_safe_area(self):
        reward = self.frame("coop_settlement")
        main = self.frame("main")
        result = self.recover([reward, reward, main, main], allow_completed_reward=True)
        self.assertTrue(result.success)
        self.assertEqual(len(self.clicks), 1)
        self.assertEqual(self.backs, [])

    def test_login_page_stops(self):
        result = self.recover([self.frame("login", "back")])
        self.assertFalse(result.success)
        self.assertEqual(self.saved[-1][1], "account_page")
        self.assertEqual(self.clicks, [])

    def test_unknown_page_uses_grace_period_and_never_clicks(self):
        result = self.recover([self.frame()], unknown_grace=1)
        self.assertFalse(result.success)
        self.assertEqual(self.saved[-1][1], "unknown")
        self.assertGreaterEqual(self.clock, 1)
        self.assertEqual(self.clicks, [])

    def test_recovery_decision_does_not_save_screenshot(self):
        self.frames = [self.frame()]
        attempt = recovery._attempt_recovery_to_courtyard(timeout=3, unknown_grace=1)
        self.assertFalse(attempt.success)
        self.assertEqual(attempt.failure_code, "unknown")
        self.assertEqual(self.saved, [])

    def test_screenshot_failure_does_not_change_recovery_outcome(self):
        frame = self.frame()
        with patch.object(recovery, "_save_failure_screenshot", side_effect=OSError("disk")), patch.object(
            recovery.LOGGER, "warning"
        ):
            result = self.recover([frame], unknown_grace=1)
        self.assertFalse(result.success)
        self.assertIn("无法确认页面", result.reason)
        self.assertIsNone(result.screenshot)

    def test_unknown_page_uses_stable_legacy_buttons_in_priority_order(self):
        first = self.frame("courtyard", "back", "close_pink", "close_red")
        second = self.frame("back", "close_pink", "close_red")
        third = self.frame("close_pink", "close_red")
        fourth = self.frame("close_red")
        main = self.frame("main")
        result = self.recover([
            first, first, second, second, third, third, fourth, fourth, main, main
        ])
        self.assertTrue(result.success)
        self.assertEqual(len(self.clicks), 4)
        self.assertEqual(self.backs, [])

    def test_unknown_button_keeps_existing_match_threshold(self):
        self.match_score = 0.82
        back = self.frame("back")
        main = self.frame("main")
        result = self.recover([back, back, main, main])
        self.assertTrue(result.success)
        self.assertEqual(len(self.clicks), 1)

    def test_unknown_button_must_remain_visible_on_second_frame(self):
        result = self.recover([self.frame("back"), self.frame()], unknown_grace=1)
        self.assertFalse(result.success)
        self.assertEqual(self.saved[-1][1], "unknown")
        self.assertEqual(self.clicks, [])

    def test_ambiguous_pages_stop(self):
        result = self.recover([self.frame("coop_challenge", "merchant_page")])
        self.assertFalse(result.success)
        self.assertEqual(self.saved[-1][1], "ambiguous")
        self.assertEqual(self.clicks, [])

    def test_ambiguous_pages_can_use_stable_generic_return(self):
        ambiguous = self.frame("coop_challenge", "merchant_page", "courtyard")
        main = self.frame("main")
        result = self.recover([ambiguous, ambiguous, main, main])
        self.assertTrue(result.success)
        self.assertEqual(len(self.clicks), 1)

    def test_ambiguous_overlays_stop_even_with_generic_return(self):
        result = self.recover([self.frame("room_exit_confirm", "sign_in_close", "courtyard")])
        self.assertFalse(result.success)
        self.assertEqual(self.saved[-1][1], "ambiguous_overlay")
        self.assertEqual(self.clicks, [])

    def test_repeated_action_stops_after_three_ineffective_clicks(self):
        page = self.frame("coop_challenge", "back")
        result = self.recover([page])
        self.assertFalse(result.success)
        self.assertEqual(self.saved[-1][1], "stalled")
        self.assertEqual(len(self.clicks), 3)

    def test_action_limit_stops_even_when_pages_keep_changing(self):
        pages = [self.frame("coop_challenge", "back") for _ in range(13)]
        frames = [frame for page in pages for frame in (page, page)]
        result = self.recover(frames, timeout=30)
        self.assertFalse(result.success)
        self.assertEqual(self.saved[-1][1], "action_limit")
        self.assertEqual(len(self.clicks), recovery.MAX_RECOVERY_ACTIONS)

    def test_stop_request_prevents_screenshot_or_action(self):
        class Stop:
            def is_set(self):
                return True

        result = self.recover([self.frame("coop_challenge", "back")], stop_event=Stop())
        self.assertFalse(result.success)
        self.assertIn("用户请求停止", result.reason)
        self.assertEqual(self.screenshot_index, 0)
        self.assertEqual(self.clicks, [])

    def test_stop_after_confirmation_prevents_click(self):
        stop = threading.Event()
        page = self.frame("coop_challenge", "back")
        self.frames = [page, page]

        def screenshot_then_stop():
            frame = self.screenshot()
            if self.screenshot_index == 2:
                stop.set()
            return frame

        with patch.object(recovery.DEVICE, "screenshot", side_effect=screenshot_then_stop):
            result = recovery.recover_to_courtyard(stop_event=stop)
        self.assertFalse(result.success)
        self.assertEqual(self.clicks, [])


if __name__ == "__main__":
    unittest.main()

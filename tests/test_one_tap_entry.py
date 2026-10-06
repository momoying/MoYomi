"""一键日常只在确认页面加载并连续两帧缺少按钮后切换页签。"""

import unittest
from unittest.mock import call, patch

from tasks.OneTapDaily import one_tap_daily as daily


class OneTapEntryTests(unittest.TestCase):
    def test_header_wait_matches_only_the_task_page_title(self):
        frame = object()
        with (
            patch.object(daily, "_take_frame", return_value=frame),
            patch.object(daily, "_match", return_value=(0.91, (1, 2, 3, 4))) as match,
            patch.object(daily, "print"),
        ):
            self.assertTrue(daily._wait_for_task_header(2))
        match.assert_called_once_with(frame, "task_header")

    def test_first_missing_frame_followed_by_button_does_not_treat_page_as_special(self):
        frames = [object(), object()]
        matches = [(0.3, None), (0.94, (1, 2, 3, 4))]
        with (
            patch.object(daily, "_take_frame", side_effect=frames) as take_frame,
            patch.object(daily, "_match", side_effect=matches) as match,
            patch.object(daily.time, "sleep") as sleep,
        ):
            rect, score = daily._find_initial_one_tap(2)

        self.assertEqual(rect, (1, 2, 3, 4))
        self.assertEqual(score, 0.94)
        self.assertEqual(take_frame.call_count, 2)
        self.assertEqual(match.call_args_list, [
            call(frames[0], "one_tap"), call(frames[1], "one_tap"),
        ])
        sleep.assert_called_once_with(daily.SCREENSHOT_INTERVAL)

    def test_only_two_missing_frames_allow_clicking_daily_tab(self):
        with (
            patch.object(daily, "_take_frame", side_effect=[object(), object()]),
            patch.object(daily, "_match", side_effect=[(0.4, None), (0.5, None)]),
            patch.object(daily.time, "sleep") as sleep,
            patch.object(daily.time, "monotonic", return_value=0),
        ):
            self.assertEqual(daily._find_initial_one_tap(2), (None, 0.5))
        sleep.assert_called_once_with(daily.SCREENSHOT_INTERVAL)

    def test_daily_page_skips_tab_click_when_one_tap_is_already_visible(self):
        rect = (1, 2, 3, 4)
        with (
            patch.object(daily, "_find_initial_one_tap", return_value=(rect, 0.95)),
            patch.object(daily, "_click_rect") as click,
            patch.object(daily, "_wait_for_one_tap") as wait,
        ):
            self.assertEqual(daily._ensure_daily_one_tap(100), rect)
        click.assert_not_called()
        wait.assert_not_called()

    def test_special_page_clicks_daily_and_waits_for_one_tap(self):
        rect = (5, 6, 7, 8)
        with (
            patch.object(daily, "_find_initial_one_tap", return_value=(None, 0.5)),
            patch.object(daily, "_click_rect") as click,
            patch.object(daily.time, "sleep") as sleep,
            patch.object(daily.time, "monotonic", return_value=0),
            patch.object(daily, "_wait_for_one_tap", return_value=(rect, 0.93)) as wait,
            patch.object(daily, "print"),
        ):
            self.assertEqual(daily._ensure_daily_one_tap(100), rect)
        click.assert_called_once_with(daily.DAILY_TAB_CLICK_REGION, "日常标签")
        sleep.assert_called_once_with(daily.POST_ACTION_DELAY_SECONDS)
        wait.assert_called_once_with(daily.ONE_TAP_WAIT_SECONDS)

    def test_switch_failure_does_not_return_a_claim_button(self):
        with (
            patch.object(daily, "_find_initial_one_tap", return_value=(None, None)),
            patch.object(daily, "_click_rect"),
            patch.object(daily.time, "sleep"),
            patch.object(daily.time, "monotonic", return_value=0),
            patch.object(daily, "_wait_for_one_tap", return_value=(None, None)),
            patch.object(daily, "print"),
        ):
            self.assertIsNone(daily._ensure_daily_one_tap(100))


if __name__ == "__main__":
    unittest.main()

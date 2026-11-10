"""截图回放与模拟设备验证，不连接或操作真实模拟器。"""

import asyncio
from contextlib import ExitStack
import itertools
from pathlib import Path
import queue
import threading
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import Mock, patch

import cv2
import numpy as np

from module.task_execution import TaskCancelled, run_task_call
from tasks.SuperOni import super_oni as task
from tasks.SuperOni.assets import SuperOniAssets as A
from ui_app.constants import DEFAULT_SETTINGS, TOOL_LABELS
from ui_app.pages.tools import ToolsPageMixin
from ui_app.runtime import UiRuntimeMixin


FIXTURES = Path(__file__).parent / "fixtures" / "super_oni"


def screenshot(name):
    return cv2.imread(str(FIXTURES / (name + ".png")))


def ocr_result(text, confidence=.99):
    return [[(text, confidence)]]


class SuperOniVisionTests(TestCase):
    def test_real_screenshots_match_only_their_page(self):
        for page, positives in (("awakening", {"awakening", "floor_one", "challenge"}),
                                ("victory", {"victory"}), ("reward", {"reward"})):
            frame = screenshot(page)
            found = {name for name in ("awakening", "floor_one", "challenge", "victory", "reward", "failed")
                     if task._matches(frame, A.IMAGES[name]) is not None}
            self.assertEqual(found, positives)

    def test_lock_and_bonus_states_use_the_supplied_screenshots(self):
        self.assertEqual(task._formation_state(screenshot("awakening"))[0], "unlocked")
        self.assertEqual(task._formation_state(screenshot("awakening_locked"))[0], "locked")
        for name, expected in (("bonus_off", False), ("bonus_on", True)):
            frame = screenshot(name)
            row = task._matches(frame, A.I_AWAKENING_BONUS)
            self.assertIsNotNone(row)
            self.assertIs(task._bonus_state(frame, row), expected)
            self.assertIsNone(task._awakening_challenge(frame))
            # 下面的经验加成仍是红色，不能影响觉醒加成的判断。
            self.assertEqual(row[1], 137)
            unknown = frame.copy()
            left, top, right, bottom = task._bonus_time_rect(row)
            unknown[top:bottom, left:right] = 0
            self.assertIsNone(task._bonus_state(unknown, row))
        shifted = screenshot("bonus_off")
        strip = shifted[137:170, 431:886].copy()
        shifted[130:175, 420:900] = 200
        shifted[300:333, 431:886] = strip
        row = task._matches(shifted, A.I_AWAKENING_BONUS)
        self.assertEqual(row[1], 300)
        self.assertIs(task._bonus_state(shifted, row), False)

    def test_only_full_confident_valid_counts_are_accepted(self):
        for text, expected in (("0/50", 0), ("1/50", 1), ("49 / 50", 49), ("50/50", 50),
                               ("５０／５０", 50), ("51/50", None), ("50/60", None),
                               ("50", None), ("999", None), ("150/50", None), ("1/5O", None)):
            with self.subTest(text=text):
                self.assertEqual(task.parse_ticket_count(ocr_result(text)), expected)
        self.assertIsNone(task.parse_ticket_count(ocr_result("50/50", .5)))
        self.assertIsNone(task.parse_ticket_count(ocr_result("50/50", float("nan"))))
        self.assertIsNone(task.parse_ticket_count([[('49/50', .99), ('50/50', .99)]]))
        self.assertIsNone(task.parse_ticket_count(None))

    def test_ocr_is_confined_to_enlarged_upper_right_counter(self):
        engine = Mock()
        engine.ocr.return_value = ocr_result("1/50")
        self.assertEqual(task.read_tickets(screenshot("reward"), engine), 1)
        image = engine.ocr.call_args.args[0]
        self.assertEqual(image.shape[:2], (120, 352))
        self.assertEqual(engine.ocr.call_args.kwargs, {"cls": False, "det": False})


class SuperOniFlowTests(TestCase):
    def replay(self, frames, counts, *, event=None, setup=None, manage_bonus=False):
        with ExitStack() as stack:
            engine = Mock()
            engine.ocr.side_effect = [ocr_result(value) for value in counts]
            stack.enter_context(patch.object(task, "local_ocr", return_value=engine))
            connect = stack.enter_context(patch.object(task.utils, "connect_to_mumu", return_value=True))
            capture = stack.enter_context(patch.object(task.DEVICE, "screenshot", side_effect=frames))
            click = stack.enter_context(patch.object(task.DEVICE, "click", return_value=True))
            wait = stack.enter_context(patch.object(task, "_wait"))
            stack.enter_context(patch.object(task.random, "randint", side_effect=lambda low, high: high))
            if not manage_bonus:
                # 原有战斗回放单独验证领奖循环，完整启动与收尾由下方新回放覆盖。
                stack.enter_context(patch.object(task, "_prepare", side_effect=lambda frame, *_: frame))
                stack.enter_context(patch.object(task, "_set_bonus", side_effect=lambda frame, *_: frame))
            if setup is not None:
                setup(stack, click)
            updates = []
            interval = task.utils.config["screenshot_speed"]
            result, report = run_task_call(lambda: task.run(stop_event=event, progress_callback=updates.append), stop_event=event)
            self.assertIsNone(report.exception)
            self.assertEqual(task.utils.config["screenshot_speed"], interval)
            return SimpleNamespace(result=result, report=report, updates=updates, click=click,
                                   capture=capture, engine=engine, wait=wait, connect=connect)

    def test_repeat_from_49_to_50_then_return_before_stopping(self):
        a, v, r = (screenshot(name) for name in ("awakening", "victory", "reward"))
        # 每局：挑战、胜利连点 3 下、读票两次、左右空白点 2 下、返回觉醒。
        out = self.replay([a, v, v, v, r, r, r, a, v, v, v, r, r, r, a],
                          ["49/50", "49/50", "50/50", "50/50"])
        self.assertTrue(out.result)
        self.assertEqual(out.updates[-1], {"stage": "已刷满，已关闭觉醒加成，已返回觉醒一层", "tickets": 50, "attempts": 2})
        self.assertEqual(out.capture.call_count, 15)
        self.assertEqual(out.click.call_count, 12)
        self.assertEqual(out.engine.ocr.call_count, 4)
        self.assertTrue(any(update['tickets'] == 49 for update in out.updates))
        self.assertTrue(all(.1 <= call.args[0] <= .2 for call in out.wait.call_args_list))
        for index, call in enumerate(out.click.call_args_list):
            x, y = call.args
            if index % 6 == 0:
                self.assertTrue(1144 <= x <= 1232 and 590 <= y <= 642)
            elif index % 6 <= 3:
                self.assertTrue(360 <= x <= 930 and 585 <= y <= 665)
            else:
                self.assertTrue((90 <= x <= 330 or 970 <= x <= 1210) and 550 <= y <= 620)

    def test_start_on_full_reward_returns_without_any_challenge(self):
        r, a = screenshot("reward"), screenshot("awakening")
        out = self.replay([r, r, a], ["50/50", "50/50"])
        self.assertTrue(out.result)
        self.assertEqual(out.updates[-1]["attempts"], 0)
        self.assertEqual(out.updates[-1]["tickets"], 50)
        self.assertEqual(out.click.call_count, 1)

    def test_victory_clicks_stop_as_soon_as_chest_appears(self):
        v, r, a = (screenshot(name) for name in ("victory", "reward", "awakening"))
        out = self.replay([v, r, r, a], ["50/50", "50/50"])
        self.assertTrue(out.result)
        self.assertEqual(out.click.call_count, 2)  # 胜利一次、OCR 后关闭奖励一次。
        self.assertEqual(out.engine.ocr.call_count, 2)

    def test_invalid_or_unstable_ocr_leaves_reward_open(self):
        r = screenshot("reward")
        for values in (["bad"] * 11, ["49/50", "50/50"] * 11):
            with self.subTest(values=values):
                out = self.replay([r] * len(values), values)
                self.assertFalse(out.result)
                self.assertIn("OCR", out.report.reason)
                out.click.assert_not_called()
                self.assertEqual(out.wait.call_count, 10)
                self.assertTrue(all(call.args[0] == 2 for call in out.wait.call_args_list))

    def test_announcement_obstruction_retries_then_reads_counter_before_dismissal(self):
        r, a = screenshot("reward"), screenshot("awakening")
        notice = screenshot("reward_notice")
        self.assertIsNotNone(task._matches(notice, A.I_REWARD))
        out = self.replay([notice, notice, r, r, a], ["公告", "", "50/50", "50/50"])
        self.assertTrue(out.result)
        self.assertEqual(out.wait.call_args_list[:2], [((2.0, None),), ((2.0, None),)])
        self.assertEqual(out.engine.ocr.call_count, 4)
        self.assertEqual(out.click.call_count, 1)

    def test_stop_during_ocr_retry_prevents_more_reads_or_clicks(self):
        event = threading.Event()

        def stop_during_wait(stack, click):
            def stop(seconds, stop_event):
                self.assertEqual(seconds, 2)
                self.assertIs(stop_event, event)
                event.set()
                raise TaskCancelled()
            stack.enter_context(patch.object(task, '_wait', side_effect=stop))

        out = self.replay([screenshot('reward')], ['公告'], event=event, setup=stop_during_wait)
        self.assertTrue(out.report.cancelled)
        out.click.assert_not_called()
        self.assertEqual(out.engine.ocr.call_count, 1)

    def test_unconfirmed_wrong_number_is_not_published_or_kept_as_previous_count(self):
        r, a, v = (screenshot(name) for name in ("reward", "awakening", "victory"))
        out = self.replay([r, r, r, r, a, v, r, r, a],
                          ["50/50", "49/50", "49/50", "49/50", "50/50", "50/50"])
        self.assertTrue(out.result)
        numbers = [item['tickets'] for item in out.updates if item['tickets'] is not None]
        self.assertEqual(numbers[0], 49)

    def test_full_count_does_not_succeed_until_awakening_returns(self):
        r = screenshot("reward")
        out = self.replay([r] * 8, ["50/50", "50/50"])
        self.assertFalse(out.result)
        self.assertIn("仍未关闭", out.report.reason)
        self.assertEqual(out.updates[-1]["attempts"], 0)

    def test_wrong_floor_and_missing_screenshots_time_out_without_click(self):
        wrong_floor = screenshot("awakening")
        wrong_floor[85:165, 80:245] = 0
        for frame in (wrong_floor, None):
            def timeout(stack, click):
                stack.enter_context(patch.object(task.time, "monotonic", side_effect=[0, 0, 100]))
            out = self.replay([frame], [], setup=timeout)
            self.assertFalse(out.result)
            self.assertIn("觉醒一层", out.report.reason)
            out.click.assert_not_called()

    def test_stop_during_victory_prevents_further_clicks(self):
        event = threading.Event()
        def stop_after_click(stack, click):
            click.side_effect = lambda *args: event.set() or True
            stack.enter_context(patch.object(task.DEVICE, "screenshot", return_value=screenshot("victory")))
        out = self.replay([], [], event=event, setup=stop_after_click)
        self.assertTrue(out.report.cancelled)
        self.assertEqual(out.click.call_count, 1)
        out.engine.ocr.assert_not_called()

    def test_failed_battle_and_wrong_resolution_stop_without_click(self):
        failed = np.zeros((720, 1280, 3), dtype=np.uint8)
        template = cv2.imread(A.I_FAILED.path)
        height, width = template.shape[:2]
        failed[40:40 + height, 350:350 + width] = template
        for frame, reason in ((failed, "挑战失败"), (np.zeros((360, 640, 3), dtype=np.uint8), "1280×720")):
            out = self.replay([frame], [])
            self.assertFalse(out.result)
            self.assertIn(reason, out.report.reason)
            out.click.assert_not_called()

    def test_complete_run_locks_enables_bonus_and_disables_it_after_full_return(self):
        u, l, off, on, v, r = (screenshot(name) for name in (
            "awakening", "awakening_locked", "bonus_off", "bonus_on", "victory", "reward"))
        out = self.replay([u, l, off, on, l, v, v, v, r, r, r, l, on, off, l],
                          ["50/50", "50/50"], manage_bonus=True)
        self.assertTrue(out.result)
        self.assertEqual(out.updates[-1]["tickets"], 50)
        self.assertEqual(out.updates[-1]["attempts"], 1)
        self.assertIn("已关闭觉醒加成", out.updates[-1]["stage"])
        self.assertEqual(out.capture.call_count, 15)
        self.assertEqual(out.click.call_count, 13)
        points = [call.args for call in out.click.call_args_list]
        self.assertTrue(697 <= points[0][0] <= 732 and 652 <= points[0][1] <= 686)
        self.assertTrue(524 <= points[1][0] <= 559 and 28 <= points[1][1] <= 76)
        for index in (2, 11):
            self.assertTrue(772 <= points[index][0] <= 886 and 140 <= points[index][1] <= 170)
        self.assertTrue(1144 <= points[4][0] <= 1232 and 590 <= points[4][1] <= 642)

    def test_existing_lock_and_enabled_bonus_are_not_toggled_at_start(self):
        l, off, on, v, r = (screenshot(name) for name in (
            "awakening_locked", "bonus_off", "bonus_on", "victory", "reward"))
        out = self.replay([l, on, l, v, r, r, l, on, off, l],
                          ["50/50", "50/50"], manage_bonus=True)
        self.assertTrue(out.result)
        points = [call.args for call in out.click.call_args_list]
        self.assertFalse(any(690 <= x <= 740 and 645 <= y <= 695 for x, y in points))
        timer_clicks = [(x, y) for x, y in points if 772 <= x <= 886 and 140 <= y <= 170]
        self.assertEqual(len(timer_clicks), 1)  # 只有刷满后的关闭操作。

    def test_preparation_occurs_once_across_multiple_battles(self):
        l, off, on, v, r = (screenshot(name) for name in (
            "awakening_locked", "bonus_off", "bonus_on", "victory", "reward"))
        out = self.replay([l, off, on, l, v, r, r, l, v, r, r, l, on, off, l],
                          ["49/50", "49/50", "50/50", "50/50"], manage_bonus=True)
        self.assertTrue(out.result)
        self.assertEqual(out.updates[-1]["attempts"], 2)
        lantern_clicks = [call for call in out.click.call_args_list
                          if 524 <= call.args[0] <= 559 and 28 <= call.args[1] <= 76]
        self.assertEqual(len(lantern_clicks), 2)  # 启动一次，结束一次。

    def test_start_with_bonus_panel_open_dismisses_it_before_checking_lock(self):
        l, off, on, v, r = (screenshot(name) for name in (
            "awakening_locked", "bonus_off", "bonus_on", "victory", "reward"))
        out = self.replay([on, l, v, r, r, l, on, off, l],
                          ["50/50", "50/50"], manage_bonus=True)
        self.assertTrue(out.result)
        x, y = out.click.call_args_list[0].args
        self.assertTrue((255 <= x <= 335 or 945 <= x <= 1050) and 190 <= y <= 490)

    def test_unconfirmed_lock_or_bonus_prevents_any_challenge(self):
        u, l, off = (screenshot(name) for name in ("awakening", "awakening_locked", "bonus_off"))
        # 点锁后一直未锁上；或开启后一直没变黄。
        for frames in ([u] * 4, [l, off, off, off, off]):
            out = self.replay(frames, [], manage_bonus=True)
            self.assertFalse(out.result)
            self.assertIn("未开始挑战", out.report.reason)
            self.assertFalse(any(1144 <= call.args[0] <= 1232 and 590 <= call.args[1] <= 642
                                 for call in out.click.call_args_list))

    def test_unknown_timer_color_does_not_toggle_or_start_battle(self):
        unknown = screenshot("bonus_off")
        unknown[140:170, 772:886] = 0
        def timeout(stack, click):
            stack.enter_context(patch.object(task, "PAGE_TIMEOUT", .1))
            stack.enter_context(patch.object(task.time, "monotonic", side_effect=itertools.count(0, .01)))
        out = self.replay(itertools.repeat(unknown), [], setup=timeout, manage_bonus=True)
        self.assertFalse(out.result)
        out.click.assert_not_called()

    def test_full_reward_with_already_disabled_bonus_only_dismisses_panel(self):
        l, off, r = (screenshot(name) for name in ("awakening_locked", "bonus_off", "reward"))
        out = self.replay([r, r, l, off, l], ["50/50", "50/50"], manage_bonus=True)
        self.assertTrue(out.result)
        self.assertEqual(out.updates[-1]["attempts"], 0)
        self.assertFalse(any(772 <= call.args[0] <= 886 and 140 <= call.args[1] <= 170
                             for call in out.click.call_args_list))

    def test_full_count_is_not_success_if_bonus_cannot_be_disabled(self):
        l, on, r = (screenshot(name) for name in ("awakening_locked", "bonus_on", "reward"))
        out = self.replay([r, r, l, on, on, on, on], ["50/50", "50/50"], manage_bonus=True)
        self.assertFalse(out.result)
        self.assertIn("未能确认觉醒加成关闭", out.report.reason)
        self.assertEqual(out.updates[-1]["attempts"], 0)


class SuperOniUiTests(IsolatedAsyncioTestCase):
    def test_start_worker_and_finish_use_live_progress_callback(self):
        ui = ToolsPageMixin()
        ui.settings = dict(DEFAULT_SETTINGS)
        ui.active_tool = "super_oni"
        ui.tool_running = ui.running = False
        ui.tool_stop_event = threading.Event()
        ui.ui_queue = queue.Queue()
        ui.page = SimpleNamespace(run_thread=Mock())
        for name in ("_safe_update", "append_tool_log", "_append_tool_log_now", "_report_ui_exception",
                     "_set_global_settings_disabled"):
            setattr(ui, name, Mock())
        ui.save_settings = Mock(return_value=True)
        ui.mumu_instances = [{"index": "0", "name": "测试模拟器", "adb_port": "127.0.0.1:16384"}]
        for name in ("tool_status", "tool_start_button", "start_button", "refresh_button",
                     "secret_attempts_field", "market_refresh_count_field", "running_badge", "running_badge_text"):
            setattr(ui, name, SimpleNamespace(disabled=False))
        ui._build_baigui_controls()
        ui._build_super_oni_controls()
        ui.start_selected_tool()
        self.assertTrue(ui.tool_running)
        ui.page.run_thread.assert_called_once_with(ui._tool_worker, "super_oni")
        self.assertIn("未识别", ui.super_oni_progress.value)

        def run(**kwargs):
            self.assertIs(kwargs["stop_event"], ui.tool_stop_event)
            kwargs["progress_callback"]({"tickets": 50, "attempts": 3, "stage": "已刷满，已返回觉醒一层"})
            return True

        ui._load_tool_module = Mock(return_value=SimpleNamespace(run=run))
        backend = SimpleNamespace(configure_runtime_paths=Mock(), configure_mumu_target=Mock(return_value=True),
                                  reset_screenshot_backend=Mock())
        with patch("ui_app.tool_sessions.automation.create_session", return_value=backend):
            ui._tool_worker("super_oni")
        kind, progress = ui.ui_queue.get_nowait()
        self.assertEqual(kind, "super_oni_progress")
        ui._apply_super_oni_progress(progress)
        kind, log = ui.ui_queue.get_nowait()
        self.assertEqual(kind, "tool_log")
        kind, instance_result = ui.ui_queue.get_nowait()
        self.assertEqual(kind, "super_oni_result")
        ui._apply_super_oni_result(instance_result)
        kind, finished = ui.ui_queue.get_nowait()
        self.assertEqual(kind, "tool_finished")
        ui._apply_tool_finished(**finished)
        self.assertFalse(ui.tool_running)
        self.assertFalse(ui.tool_start_button.disabled)
        self.assertIn("50/50", ui.tool_status.value)
        self.assertIn("已返回觉醒一层", ui.tool_status.value)
        self.assertIn("50 / 50", ui.super_oni_progress.value)

    async def test_real_progress_queue_updates_tickets_and_keeps_baigui_last(self):
        class Dashboard(ToolsPageMixin, UiRuntimeMixin):
            pass
        ui = Dashboard()
        ui.active_tool = "super_oni"
        ui.settings = dict(DEFAULT_SETTINGS)
        ui._build_super_oni_controls()
        ui.ui_queue = queue.Queue()
        ui.page = SimpleNamespace(update=Mock())
        ui.ui_queue.put(("super_oni_progress", {"tickets": 50, "attempts": 12, "stage": "已刷满，已返回觉醒一层"}))
        pump = asyncio.create_task(ui._ui_update_pump())
        await asyncio.sleep(.06)
        pump.cancel()
        await pump
        self.assertIn("50 / 50", ui.super_oni_progress.value)
        self.assertIn("12 次", ui.super_oni_progress.value)
        self.assertIn("已返回觉醒一层", ui.super_oni_progress.value)
        ui.page.update.assert_called()
        self.assertEqual(list(TOOL_LABELS)[-2:], ["super_oni", "baigui"])

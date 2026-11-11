"""并行任务使用模拟设备和同步栅栏，不访问真实 MuMu。"""

from concurrent.futures import ThreadPoolExecutor
import queue
import threading
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import numpy as np

from module import automation
from module.task_execution import record_frame, report_failure
from ui_app.constants import DEFAULT_SETTINGS
from ui_app.pages.tools import ToolsPageMixin
from ui_app.tool_sessions import run_super_oni_targets


TARGETS = [
    {"index": "0", "name": "模拟器甲", "adb_port": "127.0.0.1:16384"},
    {"index": "1", "name": "模拟器乙", "adb_port": "127.0.0.1:16416"},
]


class DeviceSessionTests(TestCase):
    def test_parallel_capture_input_and_configuration_stay_on_their_own_devices(self):
        original = (automation.adb_port, dict(automation.config), automation.get_last_screenshot())
        sessions = [automation.create_session(), automation.create_session()]
        frames = [np.full((10, 15, 3), value, np.uint8) for value in (10, 200)]
        barrier = threading.Barrier(2)
        for session, target, frame in zip(sessions, TARGETS, frames):
            session.connect_to_mumu = Mock(return_value=True)
            self.assertTrue(session.configure_mumu_target(target['adb_port'], target['index']))
            session.config['screenshot_speed'] = 0
            session._get_mumu_capture = Mock(return_value=SimpleNamespace(
                capture_frame=lambda frame=frame: (barrier.wait(timeout=3), frame)[1]))
        with ThreadPoolExecutor(max_workers=2) as pool:
            captured = list(pool.map(lambda session: session.take_screenshot(), sessions))
        for frame, result, session in zip(frames, captured, sessions):
            self.assertIs(frame, result)
            self.assertIs(session.get_last_screenshot(), frame)
        with patch.object(automation.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as command:
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(lambda item: item[1].adb_click(100 + item[0], 200 + item[0]), enumerate(sessions)))
        commands = [call.args[0] for call in command.call_args_list]
        self.assertEqual({(args[2], tuple(args[-2:])) for args in commands},
                         {('127.0.0.1:16384', ('100', '200')), ('127.0.0.1:16416', ('101', '201'))})
        self.assertEqual(automation.adb_port, original[0])
        self.assertEqual(automation.config, original[1])
        self.assertIs(automation.get_last_screenshot(), original[2])
        self.assertIsNot(sessions[0].config, sessions[1].config)
        self.assertIsNot(sessions[0]._template_cache, sessions[1]._template_cache)


class ParallelToolTests(TestCase):
    def run_pair(self, *, fail_first=False, cancel=False, bonus=None):
        events = queue.Queue()
        stop = threading.Event()
        barrier = threading.Barrier(2)
        real_factory = automation.create_session
        sessions = []
        frames = {str(index): np.full((8, 12, 3), index + 1, np.uint8) for index in range(2)}

        def factory():
            backend = real_factory()
            backend.configure_runtime_paths = Mock()
            backend.connect_to_mumu = Mock(return_value=True)
            backend.reset_screenshot_backend = Mock(wraps=backend.reset_screenshot_backend)
            sessions.append(backend)
            return backend

        def load_tool(_name):
            task = SimpleNamespace()

            def run(*, stop_event, progress_callback, enable_bonus=True):
                self.assertIs(stop_event, stop)
                index = task.utils.config['mumu_index']
                self.assertIs(enable_bonus, bonus[int(index)] if bonus is not None else True)
                self.assertEqual(task.DEVICE.backend.adb_port, TARGETS[int(index)]['adb_port'])
                record_frame(frames[index])
                barrier.wait(timeout=3)  # 确认两个线程都已进入任务后才继续。
                for tickets in (1, 1, 2, 2):
                    progress_callback({'tickets': tickets, 'attempts': tickets + 1, 'stage': '战斗中'})
                if cancel:
                    stop.set()
                if fail_first and index == '0':
                    report_failure('实例甲识别失败', frame=frames[index])
                    return False
                progress_callback({'tickets': 50, 'attempts': 10, 'stage': '完成'})
                return True

            task.run = run
            return task

        with patch('ui_app.tool_sessions.automation.create_session', side_effect=factory), \
             patch('ui_app.tool_sessions.ErrorScreenshotManager') as screenshots:
            targets = [dict(target, enable_bonus=bonus[i]) for i, target in enumerate(TARGETS)] if bonus is not None else TARGETS
            summary = run_super_oni_targets(dict(DEFAULT_SETTINGS), targets, stop, load_tool,
                                            lambda kind, payload: events.put((kind, payload)))
        items = []
        while not events.empty():
            items.append(events.get_nowait())
        return summary, items, sessions, screenshots, frames

    def test_two_threads_report_separate_results_and_only_changed_ticket_logs(self):
        summary, events, sessions, screenshots, _ = self.run_pair()
        self.assertTrue(summary['success'])
        progress = [item for kind, item in events if kind == 'super_oni_progress']
        for index in ('0', '1'):
            self.assertEqual([item['tickets'] for item in progress if item['instance_index'] == index], [1, 2, 50])
        self.assertEqual(len([item for kind, item in events if kind == 'tool_log']), 6)
        results = [item for kind, item in events if kind == 'super_oni_result']
        self.assertEqual({item['instance_index'] for item in results}, {'0', '1'})
        self.assertTrue(all(item['success'] for item in results))
        self.assertTrue(all(session.reset_screenshot_backend.call_count >= 1 for session in sessions))
        screenshots.assert_not_called()

    def test_threads_receive_independent_bonus_choices(self):
        for choices in ([False, True], [True, False]):
            summary, *_ = self.run_pair(bonus=choices)
            self.assertTrue(summary['success'])

    def test_one_failure_does_not_cancel_the_other_and_screenshot_uses_failed_device_frame(self):
        summary, events, sessions, screenshots, frames = self.run_pair(fail_first=True)
        self.assertFalse(summary['success'])
        results = {item['instance_index']: item for kind, item in events if kind == 'super_oni_result'}
        self.assertFalse(results['0']['success'])
        self.assertTrue(results['1']['success'])
        self.assertEqual(results['1']['tickets'], 50)
        self.assertFalse(results['1']['stopped'])
        screenshots.assert_called_once()
        saved = screenshots.return_value.save.call_args
        self.assertEqual(saved.args[0], 'super_oni_mumu_0')
        np.testing.assert_array_equal(saved.kwargs['frame'], frames['0'])
        failed_backend = next(session for session in sessions if session.config['mumu_index'] == '0')
        self.assertIs(screenshots.call_args.kwargs['backend'], failed_backend)

    def test_group_stop_cancels_both_without_failure_screenshots(self):
        summary, events, _, screenshots, _ = self.run_pair(cancel=True)
        self.assertTrue(summary['stopped'])
        results = [item for kind, item in events if kind == 'super_oni_result']
        self.assertTrue(all(item['stopped'] for item in results))
        screenshots.assert_not_called()

    def test_duplicate_targets_are_rejected_before_connecting(self):
        with patch('ui_app.tool_sessions.automation.create_session') as factory:
            with self.assertRaisesRegex(ValueError, '不能重复'):
                run_super_oni_targets({}, [TARGETS[0], TARGETS[0]], threading.Event(), Mock(), Mock())
            factory.assert_not_called()


class ParallelToolUiTests(TestCase):
    def dashboard(self):
        ui = ToolsPageMixin()
        ui.settings = dict(DEFAULT_SETTINGS)
        ui.mumu_instances = list(TARGETS)
        ui.active_tool = 'super_oni'
        ui.tool_running = ui.running = False
        ui.tool_stop_event = threading.Event()
        ui.ui_queue = queue.Queue()
        ui.page = SimpleNamespace(run_thread=Mock())
        ui.save_settings = Mock(return_value=True)
        ui.append_tool_log = ui._append_tool_log_now = ui._set_global_settings_disabled = Mock()
        for name in ("tool_status", "tool_start_button", "start_button", "refresh_button",
                     "secret_attempts_field", "market_refresh_count_field", "running_badge", "running_badge_text"):
            setattr(ui, name, SimpleNamespace(disabled=False))
        ui._safe_update = Mock()
        ui._build_super_oni_controls()
        return ui

    def drain(self, ui):
        while not ui.ui_queue.empty():
            kind, payload = ui.ui_queue.get_nowait()
            if kind == 'super_oni_progress':
                ui._apply_super_oni_progress(payload)
            elif kind == 'super_oni_result':
                ui._apply_super_oni_result(payload)
            elif kind == 'super_oni_finished':
                ui._apply_super_oni_finished(**payload)

    def test_buttons_start_slots_separately_and_preserve_running_results(self):
        ui = self.dashboard()
        ui.super_oni_primary_start.on_click(None)
        self.assertEqual(set(ui._super_oni_runs), {0})
        self.assertTrue(ui.super_oni_primary.disabled)
        self.assertFalse(ui.super_oni_secondary.disabled)
        ui._apply_super_oni_progress({'instance_index': '0', 'tickets': 12})
        first_progress = ui.super_oni_progress.value
        ui.super_oni_secondary.value = '1'
        ui._on_super_oni_instance_changed()
        self.assertEqual(ui.super_oni_progress.value, first_progress)
        self.assertFalse(ui.super_oni_secondary_start.disabled)
        ui.super_oni_secondary_bonus.value = False
        ui.super_oni_secondary_start.on_click(None)
        self.assertEqual(set(ui._super_oni_runs), {0, 1})
        self.assertEqual(ui.super_oni_progress.value, first_progress)
        self.assertEqual(ui.page.run_thread.call_count, 2)
        jobs = [call.args for call in ui.page.run_thread.call_args_list]
        self.assertEqual([job[1] for job in jobs], [0, 1])
        self.assertEqual([job[2]['enable_bonus'] for job in jobs], [True, False])
        self.assertIsNot(jobs[0][3], jobs[1][3])
        ui._start_super_oni_slots((0,))
        self.assertEqual(ui.page.run_thread.call_count, 2)

    def test_second_slot_can_start_first_with_its_own_bonus_choice(self):
        ui = self.dashboard()
        ui.super_oni_primary_bonus.value = True
        ui.super_oni_secondary.value = '1'
        ui.super_oni_secondary_bonus.value = False
        ui._on_super_oni_instance_changed()
        ui.super_oni_secondary_start.on_click(None)
        self.assertEqual(set(ui._super_oni_runs), {1})
        self.assertFalse(ui.super_oni_primary_start.disabled)
        self.assertFalse(ui.super_oni_primary.disabled)
        self.assertFalse(ui._super_oni_runs[1]['target']['enable_bonus'])
        self.assertIn('等待启动', ui.super_oni_progress.value)

    def test_individual_stop_restart_and_old_events_do_not_affect_other_slot(self):
        ui = self.dashboard()
        ui.super_oni_secondary.value = '1'
        ui.start_selected_tool()
        first, second = (ui._super_oni_runs[slot]['stop_event'] for slot in (0, 1))
        ui.super_oni_primary_start.on_click(None)
        self.assertTrue(first.is_set())
        self.assertFalse(second.is_set())
        self.assertFalse(ui.tool_stop_event.is_set())
        ui._apply_super_oni_finished(0, first, {'success': True, 'stopped': True})
        self.assertTrue(ui.tool_running)
        self.assertTrue(ui.start_button.disabled)
        self.assertFalse(ui.super_oni_primary_start.disabled)
        ui.super_oni_primary_start.on_click(None)
        new_run = ui._super_oni_runs[0]['stop_event']
        self.assertIsNot(new_run, first)
        ui._apply_super_oni_progress({'slot': 0, 'run_token': first, 'instance_index': '0', 'tickets': 49})
        self.assertNotIn('49 / 50', ui.super_oni_progress.value)
        ui._apply_super_oni_finished(0, first, {'success': False, 'stopped': False})
        self.assertIs(ui._super_oni_runs[0]['stop_event'], new_run)
        self.assertFalse(second.is_set())

    def test_all_start_and_all_stop_wait_for_both_before_unlocking(self):
        ui = self.dashboard()
        ui.super_oni_secondary.value = '1'
        ui.start_selected_tool()
        self.assertEqual(ui.page.run_thread.call_count, 2)
        events = [ui._super_oni_runs[slot]['stop_event'] for slot in (0, 1)]
        ui.stop_selected_tool()
        self.assertTrue(all(event.is_set() for event in events))
        self.assertTrue(ui.super_oni_primary_start.disabled)
        self.assertTrue(ui.super_oni_secondary_start.disabled)
        ui._apply_super_oni_finished(1, events[1], {'success': True, 'stopped': True})
        self.assertTrue(ui.tool_running)
        ui._apply_super_oni_finished(0, events[0], {'success': True, 'stopped': True})
        self.assertFalse(ui.tool_running)
        self.assertFalse(ui.start_button.disabled)
        self.assertFalse(ui.super_oni_primary_start.disabled)
        self.assertFalse(ui.super_oni_secondary_start.disabled)
        self.assertEqual(ui.tool_start_button.content, '全部启动')
        ui.start_selected_tool()
        self.assertEqual(ui.page.run_thread.call_count, 4)
        self.assertFalse(ui.tool_stop_event.is_set())

    def test_simultaneous_start_requests_only_launch_one_worker_for_same_device(self):
        ui = self.dashboard()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: ui._start_super_oni_slots((0,)), range(2)))
        ui.page.run_thread.assert_called_once()

    def test_worker_dispatch_failure_releases_slot_and_reports_error(self):
        ui = self.dashboard()
        ui.page.run_thread.side_effect = OSError('线程启动失败')
        ui._start_super_oni_slots((0,))
        self.assertFalse(ui.tool_running)
        self.assertEqual(ui._super_oni_runs, {})
        self.assertIn('线程启动失败', ui.super_oni_progress.value)
        self.assertFalse(ui.super_oni_primary_start.disabled)

    def test_real_workers_can_start_later_and_stop_independently(self):
        ui = self.dashboard()
        started = [threading.Event(), threading.Event()]
        finish_second = threading.Event()
        sessions = []
        real_factory = automation.create_session

        def factory():
            backend = real_factory()
            backend.configure_runtime_paths = Mock()
            backend.connect_to_mumu = Mock(return_value=True)
            backend.reset_screenshot_backend = Mock()
            sessions.append(backend)
            return backend

        def load(_name):
            task = SimpleNamespace()
            def run(*, stop_event, progress_callback, enable_bonus):
                slot = int(task.utils.config['mumu_index'])
                self.assertIs(enable_bonus, slot == 0)
                progress_callback({'tickets': slot + 1, 'attempts': 1, 'stage': '战斗中'})
                started[slot].set()
                if slot == 0:
                    self.assertTrue(stop_event.wait(5))
                else:
                    self.assertTrue(finish_second.wait(5))
                    self.assertFalse(stop_event.is_set())
                    progress_callback({'tickets': 50, 'attempts': 2, 'stage': '完成'})
                return True
            task.run = run
            return task

        ui._load_tool_module = load
        futures = []
        with patch('ui_app.tool_sessions.automation.create_session', side_effect=factory), \
             ThreadPoolExecutor(max_workers=2) as pool:
            def dispatch(worker, *args):
                future = pool.submit(worker, *args)
                futures.append(future)
                return future
            ui.page.run_thread = dispatch
            try:
                ui.super_oni_primary_start.on_click(None)
                self.assertTrue(started[0].wait(5))
                ui.super_oni_secondary.value = '1'
                ui.super_oni_secondary_bonus.value = False
                ui._on_super_oni_instance_changed()
                ui.super_oni_secondary_start.on_click(None)
                self.assertTrue(started[1].wait(5))
                ui.super_oni_primary_start.on_click(None)
                futures[0].result(timeout=5)
                self.drain(ui)
                self.assertTrue(ui.tool_running)
                self.assertIn('已安全停止', ui.super_oni_progress.value)
                self.assertIn('2 / 50', ui.super_oni_secondary_progress.value)
                finish_second.set()
                futures[1].result(timeout=5)
                self.drain(ui)
                self.assertFalse(ui.tool_running)
                self.assertIn('50 / 50', ui.super_oni_secondary_progress.value)
                self.assertIn('已刷满', ui.super_oni_secondary_progress.value)
                self.assertEqual({session.adb_port for session in sessions}, {t['adb_port'] for t in TARGETS})
                self.assertTrue(all(session.reset_screenshot_backend.called for session in sessions))
            finally:
                for run in ui._super_oni_runs.values():
                    run['stop_event'].set()
                finish_second.set()

    def test_optional_second_instance_duplicate_validation_and_independent_results(self):
        ui = self.dashboard()
        self.assertEqual(len(ui._selected_super_oni_targets()), 1)
        ui.super_oni_secondary.value = '0'
        with self.assertRaisesRegex(ValueError, '同一个'):
            ui._selected_super_oni_targets()
        self.assertIsNotNone(ui.super_oni_secondary.error_text)
        ui.super_oni_secondary.value = '1'
        ui._on_super_oni_instance_changed()
        self.assertEqual(len(ui._selected_super_oni_targets()), 2)
        ui._apply_super_oni_progress({'instance_index': '0', 'instance_name': '模拟器甲', 'tickets': 3})
        ui._apply_super_oni_progress({'instance_index': '1', 'instance_name': '模拟器乙', 'tickets': 40})
        self.assertIn('3 / 50', ui.super_oni_progress.value)
        self.assertIn('40 / 50', ui.super_oni_secondary_progress.value)
        ui._apply_super_oni_result({'instance_index': '0', 'instance_name': '模拟器甲', 'tickets': 3,
                                    'success': False, 'stopped': False, 'reason': '识别失败'})
        self.assertIn('识别失败', ui.super_oni_progress.value)
        self.assertIn('40 / 50', ui.super_oni_secondary_progress.value)

    def test_start_with_duplicate_instances_does_not_launch_worker(self):
        ui = self.dashboard()
        ui.super_oni_secondary.value = ui.super_oni_primary.value
        ui.tool_status = SimpleNamespace()
        ui.page = SimpleNamespace(run_thread=Mock())
        ui.start_selected_tool()
        self.assertFalse(ui.tool_running)
        ui.page.run_thread.assert_not_called()

    def test_selectors_exclude_each_other_and_release_disabled_second_instance(self):
        ui = self.dashboard()
        self.assertEqual({item.key for item in ui.super_oni_secondary.options}, {'', '1'})
        ui.super_oni_secondary.value = '1'
        ui._on_super_oni_instance_changed()
        self.assertEqual({item.key for item in ui.super_oni_primary.options}, {'0'})
        self.assertEqual({item.key for item in ui.super_oni_secondary.options}, {'', '1'})
        ui.super_oni_secondary.value = ''
        ui._on_super_oni_instance_changed()
        self.assertEqual({item.key for item in ui.super_oni_primary.options}, {'0', '1'})
        ui.super_oni_primary.value = '1'
        ui._on_super_oni_instance_changed()
        self.assertEqual({item.key for item in ui.super_oni_secondary.options}, {'', '0'})

    def test_restoring_duplicates_or_refreshing_removed_instance_keeps_choices_distinct(self):
        ui = self.dashboard()
        ui.settings['super_oni_instances'] = ['0', '0']
        ui._build_super_oni_controls()
        self.assertEqual(ui.super_oni_secondary.value, '')
        ui.super_oni_secondary.value = '1'
        ui._on_super_oni_instance_changed()
        ui.mumu_instances = [TARGETS[1]]
        ui._refresh_super_oni_options()
        self.assertEqual(ui.super_oni_primary.value, '1')
        self.assertEqual(ui.super_oni_secondary.value, '')
        self.assertEqual({item.key for item in ui.super_oni_secondary.options}, {''})

    def test_alias_with_the_same_adb_address_is_excluded(self):
        ui = self.dashboard()
        ui.mumu_instances.append(dict(TARGETS[0], index='2', name='重复地址'))
        ui._refresh_super_oni_options()
        self.assertEqual({item.key for item in ui.super_oni_secondary.options}, {'', '1'})

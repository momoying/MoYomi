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
    def run_pair(self, *, fail_first=False, cancel=False):
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

            def run(*, stop_event, progress_callback):
                self.assertIs(stop_event, stop)
                index = task.utils.config['mumu_index']
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
            summary = run_super_oni_targets(dict(DEFAULT_SETTINGS), TARGETS, stop, load_tool,
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
        ui._safe_update = Mock()
        ui._build_super_oni_controls()
        return ui

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

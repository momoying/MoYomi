from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import flet as ft
import main as controller
from ui_app.pages.settings import SettingsPageMixin
from ui_app.pages.tools import ToolsPageMixin
from ui_app.constants import DEFAULT_SETTINGS


class CustomChoicesTests(TestCase):
    def test_all_cross_region_daily_tasks_execute_and_preserve_same_region_records(self):
        now = datetime.fromisoformat('2026-11-11T12:00:00+08:00')
        root = controller._empty_system_state()
        root['task_enabled'] = dict.fromkeys(controller.TASK_ORDER, False)
        root['cross_region_enabled'] = True
        root['cross_region_task_enabled'] = dict.fromkeys(controller.TASK_ORDER, True)
        cross = controller.cross_region_task_state(root, controller.HEART_TEAM_TASK)
        controller.set_heart_team_role(cross, 'leader')
        state = {'version': controller.STATUS_VERSION, 'accounts': {'a': {'systems': {'IOS': root}}}}
        queue = controller.build_work_queue(state, now)
        self.assertEqual({task.task_name for item in queue for task in item.tasks}, set(controller.TASK_ORDER))
        self.assertTrue(all(item.region == controller.CROSS_REGION for item in queue))
        calls, sign_ins = [], []
        def runner(task):
            def run(**kwargs):
                calls.append(task)
                if task == controller.BOUNTY_TASK:
                    return 'no_magatama_collaboration'
                if task == controller.MERCHANT_TASK:
                    return 'no_blue_ticket'
                return True
            return run
        services = controller.ControllerServices(
            select_account=lambda account, _exit: account, exit_to_login=lambda: True,
            sign_in=lambda system, region: sign_ins.append(region) or True,
            task_runners={task: runner(task) for task in controller.TASK_ORDER}, task_recovery_retries=0)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'accounts.json'
            controller.save_state(state, path)
            with patch('builtins.print'):
                self.assertTrue(controller.run(status_path=path, services=services, now_provider=lambda: now))
            loaded, _ = controller.load_state(path)
        saved = loaded['accounts']['a']['systems']['IOS']
        self.assertEqual(set(calls), set(controller.TASK_ORDER))
        self.assertTrue(all(region == controller.CROSS_REGION for region in sign_ins))
        for task in controller.TASK_ORDER:
            self.assertIsNone(controller.task_record_time(saved, task), task)
            self.assertIsNotNone(controller.task_record_time(saved, task, controller.CROSS_REGION), task)
        self.assertEqual(controller.build_work_queue(loaded, now), [])
        saved['task_enabled'] = dict.fromkeys(controller.TASK_ORDER, True)
        controller.set_heart_team_role(saved, 'leader')
        same_queue = controller.build_work_queue(loaded, now)
        self.assertEqual({task.task_name for item in same_queue for task in item.tasks}, set(controller.TASK_ORDER))
        self.assertTrue(all(item.region == controller.SAME_REGION for item in same_queue))

    def test_cross_region_choices_round_trip_and_control_each_accounts_queue(self):
        state = {'version': controller.STATUS_VERSION, 'accounts': {
            account: {'systems': {system: controller._empty_system_state() for system in ('IOS', 'Android')}}
            for account in ('a', 'b')}}
        for account in state['accounts'].values():
            for role in account['systems'].values():
                role['task_enabled'] = dict.fromkeys(controller.TASK_ORDER, False)
        ui = SettingsPageMixin()
        ui.running = False
        ui.task_settings_state = state
        ui.task_settings_role = ft.Dropdown(value=json.dumps(['a', 'IOS']))
        ui.task_settings_checks = {task: ft.Checkbox() for task in controller.TASK_ORDER}
        ui.cross_region_enabled = ft.Switch()
        ui.cross_region_task_checks = {task: ft.Checkbox() for task in controller.TASK_ORDER}
        ui.cross_region_heart_role = ft.Dropdown(value='none')
        ui.cross_region_tasks_control = ft.Column()
        ui.heart_team_role_setting = ft.Dropdown(value='none')
        ui.task_settings_message = ft.Text()
        ui._safe_update = ui.refresh_cards = Mock()
        ui._apply_task_settings_selection()
        self.assertFalse(ui.cross_region_tasks_control.visible)
        ui.cross_region_enabled.value = True
        ui._on_cross_region_setting_changed()
        self.assertTrue(ui.cross_region_tasks_control.visible)
        ui.cross_region_task_checks['liked'].value = False
        ui.cross_region_task_checks[controller.BOUNTY_TASK].value = True
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'accounts.json'
            controller.save_state(state, path)
            with patch.object(controller, 'STATUS_PATH', path):
                self.assertTrue(ui.save_task_settings())
            loaded, _ = controller.load_state(path)
            choices = loaded['accounts']['a']['systems']['IOS']['cross_region_task_enabled']
            self.assertFalse(choices['liked'])
            self.assertTrue(choices[controller.BOUNTY_TASK])
            self.assertFalse(loaded['accounts']['a']['systems']['Android']['cross_region_enabled'])
            self.assertFalse(loaded['accounts']['b']['systems']['IOS']['cross_region_enabled'])
        ui.task_settings_state = loaded
        ui.task_settings_role.value = json.dumps(['b', 'IOS'])
        ui._apply_task_settings_selection()
        self.assertFalse(ui.cross_region_tasks_control.visible)
        ui.task_settings_role.value = json.dumps(['a', 'IOS'])
        ui._apply_task_settings_selection()
        self.assertTrue(ui.cross_region_tasks_control.visible)
        self.assertFalse(ui.cross_region_task_checks['liked'].value)
        queue = controller.build_work_queue(loaded, datetime.fromisoformat('2026-11-11T12:00:00+08:00'))
        self.assertEqual([(item.account_name, item.system, item.region, [t.task_name for t in item.tasks]) for item in queue],
                         [('a', 'IOS', controller.CROSS_REGION, [controller.BOUNTY_TASK])])
        role = loaded['accounts']['a']['systems']['IOS']
        role['cross_region_task_enabled'][controller.BOUNTY_TASK] = False
        self.assertEqual(controller.build_work_queue(loaded, datetime.now().astimezone()), [])
        self.assertFalse(controller.combined_task_is_enabled(role, controller.BOUNTY_TASK))

    def test_legacy_cross_region_choices_default_to_enabled(self):
        role = {'cross_region_enabled': True}
        self.assertTrue(all(controller.cross_region_task_is_enabled(role, task) for task in controller.CROSS_REGION_TASKS))

    def test_thread_bonus_choices_are_saved_loaded_and_attached_to_correct_target(self):
        class UI(ToolsPageMixin, SettingsPageMixin):
            pass
        ui = UI()
        ui.settings = dict(DEFAULT_SETTINGS)
        ui.mumu_instances = [dict(index=str(i), name=f'MuMu{i}', adb_port=f'127.0.0.1:{16384+32*i}') for i in range(2)]
        ui._build_super_oni_controls()
        ui.super_oni_secondary.value = '1'
        ui.super_oni_primary_bonus.value = False
        ui.super_oni_secondary_bonus.value = True
        targets = ui._selected_super_oni_targets()
        self.assertEqual([target['enable_bonus'] for target in targets], [False, True])
        ui.serverchan_enabled = SimpleNamespace(value=False)
        ui._read_settings_from_fields = Mock(return_value=dict(DEFAULT_SETTINGS))
        ui.settings_message = ft.Text()
        ui._safe_update = Mock()
        with patch('ui_app.pages.settings.save_ui_settings') as save:
            self.assertTrue(ui.save_settings())
        saved = deepcopy(save.call_args.args[0])
        self.assertEqual(saved['super_oni_bonus'], [False, True])
        ui.settings = saved
        ui._build_super_oni_controls()
        self.assertFalse(ui.super_oni_primary_bonus.value)
        self.assertTrue(ui.super_oni_secondary_bonus.value)
        ui._set_super_oni_controls_disabled(True)
        self.assertTrue(ui.super_oni_primary_bonus.disabled)
        self.assertTrue(ui.super_oni_secondary_bonus.disabled)

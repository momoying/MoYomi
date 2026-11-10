"""模拟发行包不含百鬼目录，验证首次导入、设置与完整界面仍能启动。"""

from pathlib import Path
import subprocess
import sys
from unittest import TestCase


class OptionalToolTests(TestCase):
    def test_startup_without_baigui_package(self):
        script = r'''
import importlib.abc
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

class MissingBaigui(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'tasks.Baigui' or fullname.startswith('tasks.Baigui.'):
            raise ModuleNotFoundError('Baigui excluded from release')

sys.meta_path.insert(0, MissingBaigui())
original_is_file = Path.is_file
def is_file(path):
    return False if 'Baigui' in path.parts else original_is_file(path)

with patch.object(Path, 'is_file', is_file):
    import ui
    from ui_app.constants import TOOL_LABELS, TOOL_MODULE_PATHS, TOOL_DESCRIPTIONS
    assert all('baigui' not in registry for registry in (TOOL_LABELS, TOOL_MODULE_PATHS, TOOL_DESCRIPTIONS))
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'settings.json'
        ui.save_ui_settings({'baigui_nickname': ' 本人 ', 'log_max_lines': 123}, path)
        settings = ui.load_ui_settings(path)
        assert settings['baigui_nickname'] == '本人'
        assert settings['log_max_lines'] == 123

    class Page:
        def __init__(self):
            self.window = SimpleNamespace(width=None, height=None, min_width=None, min_height=None)
            self.services, self.controls = [], []
        def add(self, *controls): self.controls.extend(controls)
        def run_task(self, *args, **kwargs): pass
        def update(self): pass

    page = Page()
    with patch('ui_app.dashboard.discover_running_mumu_instances', return_value=[]):
        dashboard = ui.AssistantDashboard(page)
    assert len(page.controls) == 1
    assert 'baigui' not in dashboard.tool_nav_items
    assert 'super_oni' in dashboard.tool_nav_items
    dashboard._baigui_settings_values()
    assert not any(name == 'tasks.Baigui' or name.startswith('tasks.Baigui.') for name in sys.modules)
print('Startup without Baigui passed')
'''
        result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

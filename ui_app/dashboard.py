"""组合各页面 mixin 的 Flet 主面板。"""

from __future__ import annotations

import queue
import threading
from datetime import datetime, timedelta
from typing import Any, Optional

import flet as ft

import main as controller

from module.appearance import DEFAULT_ACCENT
from module.notifications import get_serverchan_sendkey
from module import updater
from ui_app.components import *
from ui_app.constants import *
from ui_app.pages.daily import DailyPageMixin
from ui_app.pages.layout import LayoutMixin
from ui_app.pages.settings import SettingsPageMixin
from ui_app.pages.theme import ThemePageMixin
from ui_app.pages.tools import ToolsPageMixin
from ui_app.runtime import UiRuntimeMixin
from ui_app.settings_store import *


class AssistantDashboard(
    DailyPageMixin,
    ToolsPageMixin,
    SettingsPageMixin,
    ThemePageMixin,
    UiRuntimeMixin,
    LayoutMixin,
):
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.settings = load_ui_settings()
        saved_palette = self.settings.get("monet_palette", {})
        self._monet_palette_path = (
            str(self.settings.get("wallpaper_path", "")) if saved_palette else ""
        )
        if self.settings.get("monet_enabled") and saved_palette:
            COLORS["active"] = str(saved_palette.get("primary", DEFAULT_ACCENT))
            COLORS["panel"] = str(saved_palette.get("surface", COLORS["panel"]))
            COLORS["panel_alt"] = str(
                saved_palette.get("surface_variant", COLORS["panel_alt"])
            )
            COLORS["border"] = str(saved_palette.get("outline", COLORS["border"]))
        self.stop_event = threading.Event()
        self.tool_stop_event = threading.Event()
        self.running = False
        self.tool_running = False
        self.active_section = "daily"
        self.task_mode = controller.DAILY_MODE
        self.show_important_only = False
        self._scheduled_run_at: Optional[datetime] = None
        self._scheduled_run_mode = controller.DAILY_MODE
        self.active_settings_section = "global"
        self.active_tool = "story_skip"
        self.current_key: Optional[tuple[str, str]] = None
        self.cards: dict[tuple[str, str], AccountCardView] = {}
        self.ui_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.tool_log_sequence = 0
        self._reported_ui_errors: set[tuple[str, str, str]] = set()
        self.nav_items: dict[str, ft.Container] = {}
        self.tool_nav_items: dict[str, ft.Container] = {}
        self.settings_nav_items: dict[str, ft.Container] = {}

        self.page.title = "MoYomi"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = COLORS["page"]
        self.page.padding = 0
        self.page.theme = ft.Theme(
            font_family="Microsoft YaHei UI",
            color_scheme_seed=COLORS["active"],
        )
        self.page.window.width = 1350
        self.page.window.height = 860
        self.page.window.min_width = 1350
        self.page.window.min_height = 860

        self.summary_text = ft.Text(size=12, color=COLORS["muted"])
        self.running_badge_text = ft.Text(
            "正在运行",
            size=11,
            color=COLORS["active"],
        )
        self.running_badge = ft.Container(
            visible=False,
            bgcolor=COLORS["active_bg"],
            border_radius=999,
            padding=ft.Padding.symmetric(horizontal=10, vertical=5),
            content=ft.Row(
                [
                    ft.ProgressRing(width=14, height=14, stroke_width=2, color=COLORS["active"]),
                    self.running_badge_text,
                ],
                tight=True,
                spacing=7,
            ),
        )
        self.start_button = ft.Button(
            content="开始",
            icon=ft.Icons.PLAY_ARROW_ROUNDED,
            bgcolor=COLORS["active"],
            color="#07111F",
            on_click=self.toggle_daily_run,
        )
        self.refresh_button = ft.IconButton(
            icon=ft.Icons.REFRESH_ROUNDED,
            icon_color=COLORS["muted"],
            tooltip="重新读取账号状态",
            on_click=self.refresh_status,
        )
        self.schedule_button = ft.Button(
            content="设置定时",
            icon=ft.Icons.SCHEDULE_ROUNDED,
            tooltip="设置仅在本次应用运行期间有效的单次定时",
            on_click=self.open_schedule_dialog,
        )
        self.important_summary_text = ft.Text(
            size=11,
            color=COLORS["muted"],
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self.important_filter_button = ft.Button(
            content="只看有结果",
            icon=ft.Icons.FILTER_ALT_ROUNDED,
            tooltip="只显示发现勾协或蓝票的角色",
            on_click=self.toggle_important_filter,
        )
        self.hide_unavailable_tasks = ft.Switch(
            value=bool(self.settings.get("hide_unavailable_tasks", False)),
            active_color=COLORS["active"],
            width=58,
            height=32,
            on_change=self._on_hide_unavailable_changed,
        )
        self.task_mode_selector = ft.SegmentedButton(
            segments=[
                ft.Segment(value=controller.DAILY_MODE, label="日常"),
                ft.Segment(value=controller.WEEKLY_MODE, label="周常"),
            ],
            selected=[controller.DAILY_MODE],
            show_selected_icon=False,
            on_change=self._on_task_mode_changed,
        )

        default_alarm = datetime.now().astimezone() + timedelta(minutes=1)
        self.schedule_date_field = ft.TextField(
            label="执行日期",
            value=default_alarm.strftime("%Y-%m-%d"),
            hint_text="2026-08-15",
            dense=True,
            width=190,
            on_change=self._on_schedule_draft_changed,
        )
        self.schedule_time_field = ft.TextField(
            label="执行时间（24 小时制）",
            value=default_alarm.strftime("%H:%M"),
            hint_text="05:30",
            dense=True,
            width=190,
            on_change=self._on_schedule_draft_changed,
        )
        self.schedule_mode_selector = ft.SegmentedButton(
            segments=[
                ft.Segment(value=controller.DAILY_MODE, label="日常"),
                ft.Segment(value=controller.WEEKLY_MODE, label="周常"),
            ],
            selected=[controller.DAILY_MODE],
            show_selected_icon=False,
            on_change=self._on_schedule_draft_changed,
        )
        self.schedule_message = ft.Text(size=11, color=COLORS["muted"])
        self.cancel_schedule_button = ft.TextButton(
            content="取消定时",
            visible=False,
            on_click=self.cancel_schedule,
        )
        self.schedule_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("单次定时执行"),
            content=ft.Column(
                [
                    ft.Row(
                        [
                            self.schedule_date_field,
                            self.schedule_time_field,
                        ],
                        spacing=12,
                    ),
                    ft.Text("执行内容", size=11, color=COLORS["muted"]),
                    self.schedule_mode_selector,
                    self.schedule_message,
                ],
                spacing=12,
                tight=True,
                width=500,
            ),
            actions=[
                ft.TextButton(content="取消", on_click=self.close_schedule_dialog),
                self.cancel_schedule_button,
                ft.Button(content="设置定时", on_click=self.save_schedule),
            ],
        )

        self.cards_grid = ft.ResponsiveRow(
            expand=True,
            columns=12,
            spacing=14,
            run_spacing=14,
            scroll=ft.ScrollMode.AUTO,
        )
        self.adb_file_picker = ft.FilePicker()
        self.mumu_directory_picker = ft.FilePicker()
        self.wallpaper_file_picker = ft.FilePicker()
        self.page.services.extend(
            [
                self.adb_file_picker,
                self.mumu_directory_picker,
                self.wallpaper_file_picker,
            ]
        )
        self.adb_path_field = ft.TextField(
            label="ADB 路径",
            value=str(self.settings["adb_path"]),
            hint_text="请选择 adb.exe",
            border_radius=10,
            dense=True,
            expand=True,
        )
        self.adb_path_button = ft.IconButton(
            icon=ft.Icons.FOLDER_OPEN_ROUNDED,
            tooltip="选择 adb.exe",
            on_click=self.pick_adb_path,
        )
        self.mumu_path_field = ft.TextField(
            label="MuMu 路径",
            value=str(self.settings["mumu_path"]),
            hint_text="请选择 MuMu 安装根目录",
            border_radius=10,
            dense=True,
            expand=True,
        )
        self.mumu_path_button = ft.IconButton(
            icon=ft.Icons.FOLDER_OPEN_ROUNDED,
            tooltip="选择 MuMu 安装目录",
            on_click=self.pick_mumu_path,
        )
        self.mumu_instances = discover_running_mumu_instances(
            resolve_mumu_manager_path(self.mumu_path_field.value)
        )
        saved_index = str(self.settings.get("mumu_index") or "")
        saved_address = str(self.settings.get("adb_port") or "")
        selected_index = next(
            (
                item["index"]
                for item in self.mumu_instances
                if item["index"] == saved_index
                or item["adb_port"] == saved_address
            ),
            None,
        )
        if selected_index is None and len(self.mumu_instances) == 1:
            selected_index = self.mumu_instances[0]["index"]
        self.mumu_instance = ft.Dropdown(
            label="MuMu 模拟器",
            hint_text="请选择正在运行的实例",
            value=selected_index,
            options=self._mumu_dropdown_options(),
            leading_icon=ft.Icons.SMARTPHONE_ROUNDED,
            dense=True,
            border_radius=10,
            expand=True,
            on_select=self._on_mumu_selected,
        )
        self.mumu_refresh_button = ft.IconButton(
            icon=ft.Icons.SYNC_ROUNDED,
            icon_color=COLORS["muted"],
            tooltip="重新扫描 MuMu 实例",
            on_click=self.refresh_mumu_instances,
        )
        self.mumu_status = ft.Text(size=10, color=COLORS["muted"])
        self._update_mumu_status()
        self.screenshot_interval = ft.TextField(
            label="截图间隔（秒）",
            value=str(self.settings["screenshot_interval"]),
            keyboard_type=ft.KeyboardType.NUMBER,
            border_radius=10,
            dense=True,
            expand=True,
        )
        self.battle_detection_interval = ft.TextField(
            label="战斗检测间隔（秒）",
            value=str(self.settings["battle_detection_interval"]),
            keyboard_type=ft.KeyboardType.NUMBER,
            border_radius=10,
            dense=True,
            expand=True,
        )
        self.recovery_retry_count = ft.TextField(
            label="任务恢复重试次数",
            value=str(self.settings["recovery_retry_count"]),
            keyboard_type=ft.KeyboardType.NUMBER,
            border_radius=10,
            dense=True,
            expand=True,
        )
        self.recovery_timeout_seconds = ft.TextField(
            label="恢复最长时间（秒）",
            value=str(self.settings["recovery_timeout_seconds"]),
            keyboard_type=ft.KeyboardType.NUMBER,
            border_radius=10,
            dense=True,
            expand=True,
        )
        self.recovery_unknown_grace_seconds = ft.TextField(
            label="未知界面容忍时间（秒）",
            value=str(self.settings["recovery_unknown_grace_seconds"]),
            keyboard_type=ft.KeyboardType.NUMBER,
            border_radius=10,
            dense=True,
            expand=True,
        )
        self.error_screenshot_keep_count = ft.TextField(
            label="报错截图保留数量",
            value=str(self.settings["error_screenshot_keep_count"]),
            keyboard_type=ft.KeyboardType.NUMBER,
            border_radius=10,
            dense=True,
            expand=True,
        )
        self.log_max_lines = ft.TextField(
            label="日志行数",
            value=str(self.settings["log_max_lines"]),
            keyboard_type=ft.KeyboardType.NUMBER,
            border_radius=10,
            dense=True,
            expand=True,
        )
        self.global_setting_controls = [
            self.adb_path_field,
            self.adb_path_button,
            self.mumu_path_field,
            self.mumu_path_button,
            self.mumu_instance,
            self.mumu_refresh_button,
            self.screenshot_interval,
            self.battle_detection_interval,
            self.recovery_retry_count,
            self.recovery_timeout_seconds,
            self.recovery_unknown_grace_seconds,
            self.error_screenshot_keep_count,
            self.log_max_lines,
        ]
        self.settings_message = ft.Text(size=11, color=COLORS["muted"])
        self.serverchan_enabled = ft.Switch(
            label="使用 Server酱 推送",
            value=bool(self.settings.get("serverchan_enabled", False)),
            active_color=COLORS["active"],
            on_change=self._on_serverchan_enabled_changed,
        )
        self.serverchan_sendkey = ft.TextField(
            label="Server酱 SendKey / API",
            hint_text=(
                "环境变量已配置；留空不会修改"
                if get_serverchan_sendkey()
                else "输入 SendKey 后点击保存 API"
            ),
            password=True,
            can_reveal_password=True,
            dense=True,
            border_radius=10,
            expand=True,
        )
        self.serverchan_save_key_button = ft.Button(
            content="保存 API",
            icon=ft.Icons.KEY_ROUNDED,
            on_click=self.save_serverchan_key,
        )
        self.serverchan_clear_key_button = ft.Button(
            content="清除 API",
            icon=ft.Icons.DELETE_OUTLINE_ROUNDED,
            on_click=self.clear_serverchan_key,
        )
        self.serverchan_status = ft.Text(size=11, color=COLORS["muted"])
        self._refresh_serverchan_status()
        self.available_update: Optional[updater.ReleaseInfo] = None
        self.update_status = ft.Text(
            f"当前版本 {updater.APP_VERSION}",
            size=11,
            color=COLORS["muted"],
        )
        self.update_progress = ft.ProgressRing(
            width=16,
            height=16,
            stroke_width=2,
            visible=False,
            color=COLORS["active"],
        )
        self.update_check_button = ft.Button(
            content="检查更新",
            icon=ft.Icons.SYSTEM_UPDATE_ALT_ROUNDED,
            on_click=self.check_for_updates,
        )
        self.update_dialog_title = ft.Text("发现新版本")
        self.update_dialog_notes = ft.Text(
            size=12,
            color=COLORS["muted"],
            selectable=True,
        )
        self.update_dialog_message = ft.Text(size=11, color=COLORS["muted"])
        self.update_install_button = ft.Button(
            content="立即更新",
            icon=ft.Icons.DOWNLOAD_ROUNDED,
            on_click=self.install_available_update,
        )
        self.update_dialog = ft.AlertDialog(
            modal=True,
            title=self.update_dialog_title,
            content=ft.Column(
                [
                    self.update_dialog_notes,
                    ft.Row(
                        [self.update_progress, self.update_dialog_message],
                        spacing=8,
                    ),
                ],
                spacing=12,
                tight=True,
                width=520,
                scroll=ft.ScrollMode.AUTO,
            ),
            actions=[
                ft.TextButton(content="稍后", on_click=self.close_update_dialog),
                ft.TextButton(content="打开发布页", on_click=self.open_release_page),
                self.update_install_button,
            ],
        )
        self.wallpaper_path_field = ft.TextField(
            label="壁纸图片",
            value=str(self.settings.get("wallpaper_path", "")),
            hint_text="选择 PNG、JPG、JPEG、WebP 或 BMP 图片",
            read_only=True,
            border_radius=10,
            dense=True,
            expand=True,
        )
        self.wallpaper_path_button = ft.IconButton(
            icon=ft.Icons.FOLDER_OPEN_ROUNDED,
            tooltip="选择壁纸图片",
            on_click=self.pick_wallpaper_path,
        )
        self.wallpaper_opacity = ft.Slider(
            min=0,
            max=100,
            divisions=100,
            value=float(self.settings.get("wallpaper_opacity", 0.46)) * 100,
            label="{value}%",
            active_color=COLORS["active"],
            on_change=self.preview_wallpaper_settings,
        )
        self.wallpaper_blur = ft.Slider(
            min=0,
            max=30,
            divisions=30,
            value=float(self.settings.get("wallpaper_blur", 4.0)),
            label="{value}px",
            active_color=COLORS["active"],
            on_change=self.preview_wallpaper_settings,
        )
        self.wallpaper_fit = ft.Dropdown(
            label="背景填充模式",
            value=str(self.settings.get("wallpaper_fit", "cover")),
            options=[
                ft.DropdownOption(key="none", text="无拉伸"),
                ft.DropdownOption(key="fill", text="拉伸填充"),
                ft.DropdownOption(key="contain", text="等比适应"),
                ft.DropdownOption(key="cover", text="等比适应（裁剪）"),
            ],
            dense=True,
            border_radius=10,
            on_select=self.preview_wallpaper_settings,
        )
        self.monet_enabled = ft.Switch(
            label="莫奈取色",
            value=bool(self.settings.get("monet_enabled", True)),
            active_color=COLORS["active"],
            on_change=self._on_monet_changed,
        )
        self.wallpaper_message = ft.Text(size=11, color=COLORS["muted"])
        self.monet_palette_row = ft.Row(spacing=8)
        self._refresh_monet_palette_preview()
        self.global_setting_controls.extend(
            [
                self.wallpaper_path_field,
                self.wallpaper_path_button,
                self.wallpaper_opacity,
                self.wallpaper_blur,
                self.wallpaper_fit,
                self.monet_enabled,
                self.serverchan_enabled,
                self.serverchan_sendkey,
                self.serverchan_save_key_button,
                self.serverchan_clear_key_button,
                self.update_check_button,
            ]
        )
        self.task_settings_state: Optional[dict[str, Any]] = None
        self.task_settings_role = ft.Dropdown(
            label="账号 / 系统角色",
            hint_text="请选择需要配置的角色",
            options=[],
            dense=True,
            border_radius=10,
            expand=True,
            on_select=self._on_task_settings_role_selected,
        )
        self.task_settings_checks = {
            task_name: ft.Checkbox(
                label=controller.TASK_LABELS[task_name],
                value=True,
            )
            for task_name in UI_TASK_ORDER
        }
        self.cross_region_enabled = ft.Switch(
            label="启用跨区账号（砂狐乐园）",
            value=False,
            active_color=COLORS["active"],
            on_change=self._on_cross_region_setting_changed,
        )
        self.heart_team_role_setting = ft.Dropdown(
            label="同心队身份",
            hint_text="请选择当前角色在同心队中的身份",
            value="none",
            options=[
                ft.DropdownOption(key="none", text="未配置"),
                ft.DropdownOption(key="leader", text="队长"),
                ft.DropdownOption(key="member", text="成员"),
            ],
            dense=True,
            border_radius=10,
            on_select=self._on_heart_team_role_selected,
        )
        self.task_settings_message = ft.Text(size=11, color=COLORS["muted"])
        self.log_view = ft.ListView(expand=True, spacing=5, auto_scroll=True, padding=2)
        self.tool_log_view = ft.ListView(
            expand=True,
            spacing=5,
            auto_scroll=True,
            padding=2,
        )
        self.tool_status = ft.Text(
            "等待启动",
            size=12,
            color=COLORS["muted"],
        )
        self.tool_description = ft.Text(
            TOOL_DESCRIPTIONS[self.active_tool],
            size=12,
            color=COLORS["muted"],
        )
        self.secret_attempts_field = ft.TextField(
            label="协战次数",
            value=str(self.settings.get("secret_battle_attempts", 0)),
            hint_text="每次点击挑战消耗 1 次",
            keyboard_type=ft.KeyboardType.NUMBER,
            border_radius=10,
            dense=True,
        )
        self.secret_attempts_control = ft.Column(
            [
                self.secret_attempts_field,
                ft.Text(
                    "获得黑蛋或手动停止后保留剩余次数，可继续修改后再次使用。",
                    size=11,
                    color=COLORS["muted"],
                ),
            ],
            spacing=5,
            visible=False,
        )
        self.tool_start_button = ft.Button(
            content="开始",
            icon=ft.Icons.PLAY_ARROW_ROUNDED,
            bgcolor=COLORS["active"],
            color="#07111F",
            on_click=self.toggle_selected_tool,
        )

        self._reload_task_settings_roles(update=False)
        self.page.add(self._build_layout())
        self.load_update_result()
        self.refresh_cards()
        self._refresh_schedule_summary()
        self.append_log("INFO", "中控台已启动，等待执行")
        self.page.run_task(self._ui_update_pump)
        self.page.run_task(self._schedule_pump)
        self.page.run_task(self._startup_update_check)

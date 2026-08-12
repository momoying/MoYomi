"""Flet desktop dashboard for the Daily task controller."""

from __future__ import annotations

import asyncio
import io
import importlib.util
import json
import os
import queue
import re
import subprocess
import sys
import threading
import traceback
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

import flet as ft


HELPER_DIR = Path(__file__).resolve().parent
if str(HELPER_DIR) not in sys.path:
    sys.path.insert(0, str(HELPER_DIR))

import main as controller
from Core.appearance import DEFAULT_ACCENT, extract_monet_palette
from Core.notifications import (
    clear_project_sendkey,
    get_serverchan_sendkey,
    set_project_sendkey,
)


CONFIG_DIR = HELPER_DIR / "config"
SETTINGS_PATH = CONFIG_DIR / "ui_settings.json"
TOOLS_DIR = HELPER_DIR / "Tools"
TOOL_MODULE_PATHS = {
    "story_skip": TOOLS_DIR / "StorySkip" / "StorySkip.py",
    "secret_battle": TOOLS_DIR / "SecretBattle" / "SecretBattle.py",
}
TOOL_LABELS = {
    "story_skip": "剧情跳过",
    "secret_battle": "一键秘闻",
}
TOOL_DESCRIPTIONS = {
    "story_skip": (
        "自动识别并处理剧情跳过、对话气泡、挑战、"
        "战斗准备和战斗奖励。每帧最多点击一个最高优先级目标。"
    ),
    "secret_battle": (
        "重复挑战当前秘闻层；获得黑蛋、协战次数耗尽或挑战失败时自动停止。\n"
        "鹿丸可过：红叶，雨女，大天狗，海坊主，青行灯，吸血姬，彼岸花，清姬，雪童子，青蛙瓷器，犬神，河童"
    ),
}
DEFAULT_ADB_PATH = r"D:\Program Files\Netease\MuMu\nx_main\adb.exe"
DEFAULT_MUMU_PATH = r"D:\Program Files\Netease\MuMu"
MUMU_MANAGER_PATH = Path(DEFAULT_MUMU_PATH) / "nx_main" / "MuMuManager.exe"
DEFAULT_SETTINGS = {
    "screenshot_interval": 0.5,
    "battle_detection_interval": 2.0,
    "log_max_lines": 300,
    "recovery_retry_count": 1,
    "recovery_timeout_seconds": 90.0,
    "recovery_unknown_grace_seconds": 10.0,
    "timeout_screenshot_keep_count": 20,
    "adb_path": DEFAULT_ADB_PATH,
    "mumu_path": DEFAULT_MUMU_PATH,
    "mumu_index": None,
    "adb_port": None,
    "secret_battle_attempts": 0,
    "wallpaper_path": "",
    "wallpaper_opacity": 0.46,
    "wallpaper_blur": 4.0,
    "wallpaper_fit": "cover",
    "monet_enabled": True,
    "monet_palette": {},
    "hide_unavailable_tasks": False,
    "serverchan_enabled": False,
}

COLORS = {
    "page": "#090E1A",
    "panel": "#111827",
    "panel_alt": "#151E2E",
    "border": "#263247",
    "text": "#E6EDF7",
    "muted": "#8997AC",
    "pending": "#64748B",
    "pending_bg": "#202A3A",
    "done": "#39D98A",
    "done_bg": "#123728",
    "active": "#4DA3FF",
    "active_bg": "#153A63",
    "error": "#FF647C",
    "error_bg": "#4A1D29",
    "warning": "#F6C85F",
    "warning_bg": "#443719",
}
BASE_COLORS = dict(COLORS)

TASK_HIGHLIGHT_STYLES = {
    "default": {
        "colors": ("#302A4A", "#263C50", "#45303F"),
        "border": "#D8B4FE",
        "width": 2,
    },
    "bounty_normal": {
        "colors": ("#283C55", "#2F5265", "#3B4668"),
        "border": "#93C5FD",
        "width": 2,
    },
    "bounty_sharing": {
        "colors": ("#7C2D12", "#BE123C", "#6D28D9"),
        "border": "#FFD166",
        "width": 3,
    },
    "merchant_50": {
        "colors": ("#6D28D9", "#087EA4", "#B45309"),
        "border": "#FFD166",
        "width": 3,
    },
    "merchant_70": {
        "colors": ("#40308A", "#176B87", "#256D85"),
        "border": "#67E8F9",
        "width": 2,
    },
    "merchant_80": {
        "colors": ("#1E3A5F", "#274C77", "#315E79"),
        "border": "#60A5FA",
        "width": 2,
    },
    "merchant_90": {
        "colors": ("#222936", "#2D3544"),
        "border": "#64748B",
        "width": 1,
    },
}
MERCHANT_HIGHLIGHT_STYLES = {
    "blue_ticket_50": "merchant_50",
    "blue_ticket_70": "merchant_70",
    "blue_ticket_80": "merchant_80",
    "blue_ticket_90": "merchant_90",
}
BOUNTY_HIGHLIGHT_STYLES = {
    "normal_magatama_collaboration": "bounty_normal",
    "sharing_magatama_collaboration": "bounty_sharing",
}

TASK_ICONS = {
    "mail_collected": ft.Icons.MAIL_ROUNDED,
    "liked": ft.Icons.THUMB_UP_ROUNDED,
    "coop_reward_completed": ft.Icons.HANDSHAKE_ROUNDED,
    "experience_monster_completed": ft.Icons.AUTO_AWESOME_ROUNDED,
    "one_tap_daily_completed": ft.Icons.DONE_ALL_ROUNDED,
    "bounty_checked": ft.Icons.SEARCH_ROUNDED,
    "merchant_checked": ft.Icons.STOREFRONT_ROUNDED,
    "guild_kirin_completed": ft.Icons.PETS_ROUNDED,
    controller.HEART_TEAM_TASK: ft.Icons.GROUPS_ROUNDED,
    controller.CONSIGNMENT_HOUSE_TASK: ft.Icons.SELL_ROUNDED,
}

UI_TASK_ORDER = (
    "mail_collected",
    "one_tap_daily_completed",
    "bounty_checked",
    "merchant_checked",
    "liked",
    "coop_reward_completed",
    "experience_monster_completed",
    "guild_kirin_completed",
    controller.HEART_TEAM_TASK,
)
WEEKLY_UI_TASK_ORDER = (controller.CONSIGNMENT_HOUSE_TASK,)


def load_ui_settings(path: Path = SETTINGS_PATH) -> dict[str, Any]:
    settings = dict(DEFAULT_SETTINGS)
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return settings
    if isinstance(raw, dict):
        settings.update(raw)
    try:
        settings["screenshot_interval"] = min(
            10.0,
            max(0.1, float(settings["screenshot_interval"])),
        )
        settings["log_max_lines"] = min(
            2000,
            max(50, int(settings["log_max_lines"])),
        )
        settings["secret_battle_attempts"] = max(
            0,
            int(settings.get("secret_battle_attempts", 0)),
        )
        settings["battle_detection_interval"] = min(
            10.0,
            max(0.1, float(settings["battle_detection_interval"])),
        )
        settings["recovery_retry_count"] = min(
            5,
            max(0, int(settings["recovery_retry_count"])),
        )
        settings["recovery_timeout_seconds"] = min(
            600.0,
            max(10.0, float(settings["recovery_timeout_seconds"])),
        )
        settings["recovery_unknown_grace_seconds"] = min(
            60.0,
            max(1.0, float(settings["recovery_unknown_grace_seconds"])),
        )
        settings["timeout_screenshot_keep_count"] = min(
            500,
            max(0, int(settings["timeout_screenshot_keep_count"])),
        )
    except (TypeError, ValueError):
        return dict(DEFAULT_SETTINGS)
    settings["adb_path"] = str(settings.get("adb_path") or DEFAULT_ADB_PATH)
    settings["mumu_path"] = str(settings.get("mumu_path") or DEFAULT_MUMU_PATH)
    settings["wallpaper_path"] = str(settings.get("wallpaper_path") or "")
    try:
        settings["wallpaper_opacity"] = min(
            1.0, max(0.0, float(settings.get("wallpaper_opacity", 0.46)))
        )
        settings["wallpaper_blur"] = min(
            30.0, max(0.0, float(settings.get("wallpaper_blur", 4.0)))
        )
    except (TypeError, ValueError):
        settings["wallpaper_opacity"] = 0.46
        settings["wallpaper_blur"] = 4.0
    if settings.get("wallpaper_fit") not in {"none", "fill", "contain", "cover"}:
        settings["wallpaper_fit"] = "cover"
    settings["monet_enabled"] = bool(settings.get("monet_enabled", True))
    settings["hide_unavailable_tasks"] = bool(
        settings.get("hide_unavailable_tasks", False)
    )
    settings["serverchan_enabled"] = bool(
        settings.get("serverchan_enabled", False)
    )
    if not isinstance(settings.get("monet_palette"), dict):
        settings["monet_palette"] = {}
    return settings


def resolve_mumu_manager_path(mumu_path: str | Path) -> Path:
    """由 MuMu 安装根目录定位实例管理程序。"""
    return Path(mumu_path) / "nx_main" / "MuMuManager.exe"


def discover_running_mumu_instances(
    manager_path: Path = MUMU_MANAGER_PATH,
) -> list[dict[str, str]]:
    """通过 MuMuManager 获取正在运行实例及其真实 ADB 地址。"""
    manager_path = Path(manager_path)
    if not manager_path.is_file():
        return []
    try:
        result = subprocess.run(
            [str(manager_path), "info", "-v", "all"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if result.returncode != 0:
            return []
        output = result.stdout.strip()
        first_brace = output.find("{")
        last_brace = output.rfind("}")
        if first_brace < 0 or last_brace < first_brace:
            return []
        raw = json.loads(output[first_brace : last_brace + 1])
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
        return []

    instances: list[dict[str, str]] = []
    for item in raw.values() if isinstance(raw, dict) else ():
        if not isinstance(item, dict) or not item.get("is_android_started"):
            continue
        host = str(item.get("adb_host_ip") or "").strip()
        port = item.get("adb_port")
        if not host or port in (None, ""):
            continue
        index = str(item.get("index", "")).strip()
        address = f"{host}:{port}"
        instances.append(
            {
                "index": index,
                "name": str(item.get("name") or f"MuMu 实例 {index}"),
                "adb_port": address,
            }
        )
    return sorted(instances, key=lambda item: int(item["index"]))


def save_ui_settings(settings: dict[str, Any], path: Path = SETTINGS_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_path, path)


class LineWriter(io.TextIOBase):
    """Convert controller/task print output into UI log lines."""

    def __init__(self, callback: Callable[[str], None]) -> None:
        self.callback = callback
        self.buffer = ""

    def writable(self) -> bool:
        return True

    def write(self, value: str) -> int:
        self.buffer += str(value).replace("\r\n", "\n").replace("\r", "\n")
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line.strip():
                self.callback(line.rstrip())
        return len(value)

    def flush(self) -> None:
        if self.buffer.strip():
            self.callback(self.buffer.rstrip())
        self.buffer = ""


class TaskStatusView:
    def __init__(
        self,
        task_name: str,
        due_count: int,
        completed_detail: Optional[str] = None,
        available: bool = True,
        enabled: bool = True,
    ) -> None:
        self.task_name = task_name
        self.status = (
            "disabled"
            if not enabled
            else ("unavailable" if not available else ("pending" if due_count else "done"))
        )
        self.highlighted = False
        self.highlight_style = "default"
        self.icon = ft.Icon(TASK_ICONS[task_name], size=16)
        self.title = ft.Text(
            controller.TASK_LABELS[task_name],
            size=12,
            weight=ft.FontWeight.W_600,
            color=COLORS["text"],
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        detail = "待执行" + (f" ×{due_count}" if due_count > 1 else "")
        if not enabled:
            detail = "已禁用"
        elif not available:
            detail = "今日未开放"
        self.detail = ft.Text(
            detail
            if (due_count or not available or not enabled)
            else (completed_detail or "当前周期已完成"),
            size=10,
            color=COLORS["muted"],
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self.control = ft.Container(
            padding=ft.Padding.symmetric(horizontal=9, vertical=8),
            border_radius=10,
            content=ft.Row(
                [
                    self.icon,
                    ft.Column([self.title, self.detail], spacing=1, expand=True),
                ],
                spacing=7,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )
        self.set_status(self.status, self.detail.value)

    def set_status(self, status: str, detail: str) -> None:
        self.status = status
        styles = {
            "done": (ft.Icons.CHECK_CIRCLE_ROUNDED, COLORS["done"], COLORS["done_bg"]),
            "active": (ft.Icons.SYNC_ROUNDED, COLORS["active"], COLORS["active_bg"]),
            "error": (ft.Icons.ERROR_ROUNDED, COLORS["error"], COLORS["error_bg"]),
            "warning": (ft.Icons.PAUSE_CIRCLE_ROUNDED, COLORS["warning"], COLORS["warning_bg"]),
            "unavailable": (
                TASK_ICONS[self.task_name],
                "#566174",
                "#171E2A",
            ),
            "disabled": (
                ft.Icons.BLOCK_ROUNDED,
                "#566174",
                "#171E2A",
            ),
            "pending": (
                TASK_ICONS[self.task_name],
                COLORS["pending"],
                COLORS["pending_bg"],
            ),
        }
        icon, color, background = styles[status]
        self.icon.icon = icon
        self.icon.color = color
        self.title.color = (
            color
            if status in {"unavailable", "disabled"}
            else COLORS["text"]
        )
        self.detail.value = detail
        self.detail.color = color if status in {"active", "error", "warning"} else COLORS["muted"]
        show_highlight = self.highlighted and status == "done"
        highlight = TASK_HIGHLIGHT_STYLES[self.highlight_style]
        if show_highlight:
            self.icon.color = highlight["border"]
            self.detail.color = highlight["border"]
        self.control.bgcolor = None if show_highlight else background
        self.control.gradient = (
            ft.LinearGradient(
                begin=ft.Alignment.TOP_LEFT,
                end=ft.Alignment.BOTTOM_RIGHT,
                colors=list(highlight["colors"]),
            )
            if show_highlight
            else None
        )
        self.control.border = ft.Border.all(
            highlight["width"] if show_highlight else 1,
            highlight["border"] if show_highlight else color,
        )

    def set_highlight(self, enabled: bool, style: str = "default") -> None:
        self.highlighted = enabled
        self.highlight_style = style if enabled else "default"
        self.set_status(self.status, self.detail.value)


class AccountCardView:
    def __init__(
        self,
        account: str,
        system: str,
        system_state: dict[str, Any],
        now: datetime,
        task_mode: str = controller.DAILY_MODE,
    ) -> None:
        self.account = account
        self.system = system
        self.status = "pending"
        self.status_text = ft.Text(size=11, color=COLORS["muted"])
        self.task_views: dict[str, TaskStatusView] = {}

        task_order = (
            WEEKLY_UI_TASK_ORDER
            if task_mode == controller.WEEKLY_MODE
            else UI_TASK_ORDER
        )
        for task_name in task_order:
            if task_mode == controller.WEEKLY_MODE:
                record = system_state[controller.CONSIGNMENT_HOUSE_TASK]
                enabled = True
                due_count = int(controller.weekly_consignment_is_due(record, now))
                available = True
            else:
                enabled = controller.combined_task_is_enabled(system_state, task_name)
                due_count = (
                    controller.combined_task_runs_due(task_name, system_state, now)
                    if enabled
                    else 0
                )
                available = controller.task_is_available(task_name, now)
            completed_detail = None
            if task_name == controller.BOUNTY_TASK:
                completed_detail = controller.combined_bounty_detail(system_state)
            elif task_name == controller.MERCHANT_TASK:
                completed_detail = controller.MERCHANT_RESULT_DETAILS.get(
                    controller.task_record_result(
                        system_state,
                        controller.MERCHANT_TASK,
                    ),
                    "当前周期已检查",
                )
            elif task_name == controller.HEART_TEAM_TASK:
                role = controller.heart_team_role(system_state)
                role_label = controller.HEART_TEAM_ROLE_DETAILS.get(
                    role,
                    "身份未配置",
                )
                completed_detail = (
                    f"{role_label} · "
                    + (
                        "本轮补存已完成"
                        if role == "member"
                        else "今日战斗已完成"
                    )
                )
            elif task_name == controller.CONSIGNMENT_HOUSE_TASK:
                completed_detail = (
                    "本周购买完成"
                    if record.get("result") == controller.CONSIGNMENT_PURCHASED
                    else "本周已购买"
                )
            task_view = TaskStatusView(
                task_name,
                due_count,
                completed_detail=completed_detail,
                available=available,
                enabled=enabled,
            )
            if task_name == controller.BOUNTY_TASK:
                bounty_style = BOUNTY_HIGHLIGHT_STYLES.get(
                    controller.combined_bounty_highlight_result(system_state)
                )
                task_view.set_highlight(
                    due_count == 0 and bounty_style is not None,
                    bounty_style or "default",
                )
            elif task_name == controller.MERCHANT_TASK:
                merchant_style = MERCHANT_HIGHLIGHT_STYLES.get(
                    controller.task_record_result(
                        system_state,
                        controller.MERCHANT_TASK,
                    )
                )
                task_view.set_highlight(
                    due_count == 0 and merchant_style is not None,
                    merchant_style or "default",
                )
            self.task_views[task_name] = task_view

        system_icon = (
            ft.Icons.PHONE_IPHONE_ROUNDED
            if system == "IOS"
            else ft.Icons.ANDROID_ROUNDED
        )
        system_color = "#A78BFA" if system == "IOS" else "#65D68A"
        system_badge = ft.Container(
            bgcolor=f"{system_color}22",
            border=ft.Border.all(1, f"{system_color}66"),
            border_radius=999,
            padding=ft.Padding.symmetric(horizontal=9, vertical=4),
            content=ft.Row(
                [
                    ft.Icon(system_icon, color=system_color, size=14),
                    ft.Text(system, color=system_color, size=11, weight=ft.FontWeight.BOLD),
                ],
                spacing=5,
                tight=True,
            ),
        )
        task_grid = ft.ResponsiveRow(
            [self.task_views[name].control for name in task_order],
            columns=12,
            spacing=8,
            run_spacing=8,
        )
        for control in task_grid.controls:
            control.col = 12 if task_mode == controller.WEEKLY_MODE else 6

        self.control = ft.Container(
            col={"xs": 12, "sm": 6, "md": 4},
            bgcolor=COLORS["panel_alt"],
            border_radius=16,
            padding=14,
            border=ft.Border.all(1, COLORS["border"]),
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Container(
                                width=38,
                                height=38,
                                border_radius=12,
                                bgcolor="#24324A",
                                alignment=ft.Alignment.CENTER,
                                content=ft.Icon(
                                    ft.Icons.PERSON_ROUNDED,
                                    color="#B7C8E2",
                                    size=22,
                                ),
                            ),
                            ft.Column(
                                [
                                    ft.Text(
                                        account,
                                        size=14,
                                        weight=ft.FontWeight.BOLD,
                                        color=COLORS["text"],
                                        overflow=ft.TextOverflow.ELLIPSIS,
                                    ),
                                    self.status_text,
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            system_badge,
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Divider(height=4, color="transparent"),
                    task_grid,
                ],
                spacing=8,
            ),
        )
        self.refresh_overall()

    def set_phase(self, status: str, text: str) -> None:
        self.status = status
        self.status_text.value = text
        self.status_text.color = COLORS.get(status, COLORS["muted"])
        border_color = COLORS.get(status, COLORS["border"])
        border_width = 2 if status in {"active", "error"} else 1
        self.control.border = ft.Border.all(border_width, border_color)

    def refresh_overall(self) -> None:
        task_statuses = {view.status for view in self.task_views.values()}
        if "error" in task_statuses:
            self.set_phase("error", "执行失败")
        elif "active" in task_statuses:
            self.set_phase("active", "正在执行")
        elif task_statuses <= {"done", "unavailable", "disabled"}:
            self.set_phase("done", "当前任务全部完成")
        else:
            self.set_phase("pending", "等待进入队列")


class AssistantDashboard:
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
        self.page.window.width = 1420
        self.page.window.height = 880
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
        self.hide_unavailable_tasks = ft.Switch(
            value=bool(self.settings.get("hide_unavailable_tasks", False)),
            active_color=COLORS["active"],
            width=58,
            height=32,
            on_change=self._on_hide_unavailable_changed,
        )
        self.weekly_mode_switch = ft.Switch(
            value=False,
            active_color=COLORS["active"],
            width=58,
            height=32,
            on_change=self._on_task_mode_changed,
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
        self.timeout_screenshot_keep_count = ft.TextField(
            label="超时截图保留数量",
            value=str(self.settings["timeout_screenshot_keep_count"]),
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
            self.timeout_screenshot_keep_count,
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
        self.refresh_cards()
        self.append_log("INFO", "中控台已启动，等待执行")
        self.page.run_task(self._ui_update_pump)

    def _panel(
        self,
        title: str,
        icon: str,
        content: ft.Control,
        expand: Any = None,
        subtitle: Optional[ft.Control] = None,
        actions: Optional[ft.Control] = None,
        heading_extra: Optional[ft.Control] = None,
        compact_heading: bool = False,
    ) -> ft.Container:
        title_controls: list[ft.Control] = [
            ft.Text(
                title,
                size=15,
                weight=ft.FontWeight.BOLD,
                color=COLORS["text"],
            )
        ]
        if subtitle is not None:
            title_controls.append(subtitle)
        heading_leading: list[ft.Control] = [
            ft.Icon(icon, size=18, color=COLORS["active"]),
            ft.Column(title_controls, spacing=1),
        ]
        if heading_extra is not None:
            heading_leading.append(heading_extra)
        heading = ft.Row(
            [
                ft.Row(
                    heading_leading,
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                actions or ft.Container(),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        return ft.Container(
            bgcolor=f"#DD{COLORS['panel'].lstrip('#')}",
            border=ft.Border.all(1, COLORS["border"]),
            border_radius=16,
            padding=(
                ft.Padding(left=16, top=7, right=16, bottom=16)
                if compact_heading
                else 16
            ),
            expand=expand,
            content=ft.Column(
                [
                    heading,
                    ft.Divider(
                        height=2 if compact_heading else 10,
                        color=COLORS["border"],
                    ),
                    content,
                ],
                expand=True,
                spacing=3 if compact_heading else 8,
            ),
        )

    def _build_layout(self) -> ft.Control:
        wallpaper_path = str(self.settings.get("wallpaper_path", ""))
        wallpaper_file = Path(wallpaper_path)
        self.wallpaper_image = ft.Image(
            src=wallpaper_file.read_bytes() if wallpaper_file.is_file() else b"",
            fit=self._wallpaper_box_fit(),
            opacity=float(self.settings.get("wallpaper_opacity", 0.46)),
            visible=bool(wallpaper_path and wallpaper_file.is_file()),
            expand=True,
        )
        self.wallpaper_blur_layer = ft.Container(
            blur=float(self.settings.get("wallpaper_blur", 4.0)),
            visible=self.wallpaper_image.visible,
            expand=True,
            ignore_interactions=True,
        )
        header = ft.Container(
            padding=ft.Padding.symmetric(horizontal=24, vertical=14),
            bgcolor="#E60D1422",
            border=ft.Border(bottom=ft.BorderSide(1, COLORS["border"])),
            content=ft.Row(
                [
                    ft.Row(
                        [
                            ft.Container(
                                width=42,
                                height=42,
                                border_radius=12,
                                bgcolor=COLORS["active_bg"],
                                alignment=ft.Alignment.CENTER,
                                content=ft.Icon(ft.Icons.DASHBOARD_ROUNDED, color=COLORS["active"]),
                            ),
                            ft.Column(
                                [
                                    ft.Text(
                                        "我要摆烂",
                                        size=20,
                                        weight=ft.FontWeight.BOLD,
                                        color=COLORS["text"],
                                    ),
                                    ft.Text(
                                        "MoYomi",
                                        size=11,
                                        color=COLORS["muted"],
                                    ),
                                ],
                                spacing=1,
                            ),
                        ],
                        spacing=12,
                    ),
                    self.running_badge,
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
        )

        self.section_pages = {
            "daily": self._build_daily_page(),
            "tools": self._build_tools_page(),
            "settings": self._build_settings_page(),
        }
        self.content_host = ft.Container(
            content=self.section_pages["daily"],
            padding=18,
            expand=True,
        )
        navigation = self._build_navigation()
        self._apply_navigation_style()

        foreground = ft.Column(
            [header, navigation, self.content_host],
            spacing=0,
            expand=True,
        )
        return ft.Stack(
            [self.wallpaper_image, self.wallpaper_blur_layer, foreground],
            fit=ft.StackFit.EXPAND,
            expand=True,
        )

    def _build_navigation(self) -> ft.Container:
        labels = (
            ("daily", "一键长草"),
            ("tools", "小工具"),
            ("settings", "设置"),
        )
        controls = []
        for key, label in labels:
            item = ft.Container(
                data=key,
                height=48,
                expand=True,
                alignment=ft.Alignment.CENTER,
                content=ft.Text(
                    label,
                    size=15,
                    weight=ft.FontWeight.W_600,
                    color=COLORS["text"],
                ),
                border=ft.Border(
                    bottom=ft.BorderSide(3, "transparent"),
                ),
                on_click=self._on_navigation_click,
            )
            self.nav_items[key] = item
            controls.append(item)
        return ft.Container(
            bgcolor="#E6111827",
            border=ft.Border(bottom=ft.BorderSide(1, COLORS["border"])),
            content=ft.Row(controls, spacing=0),
        )

    def _apply_navigation_style(self) -> None:
        for key, item in self.nav_items.items():
            selected = key == self.active_section
            item.content.color = COLORS["active"] if selected else COLORS["text"]
            item.border = ft.Border(
                bottom=ft.BorderSide(
                    3,
                    COLORS["active"] if selected else "transparent",
                )
            )

    def _on_navigation_click(self, event: Any) -> None:
        section = str(event.control.data)
        self._show_section(section)

    def _show_section(self, section: str, update: bool = True) -> None:
        if section not in self.section_pages:
            return
        self.active_section = section
        self.content_host.content = self.section_pages[section]
        self._apply_navigation_style()
        if update:
            self._safe_update()

    def _build_daily_page(self) -> ft.Control:
        task_filter = ft.Row(
            [
                ft.Column(
                    [
                        ft.Text(
                            "周常任务",
                            size=12,
                            color=COLORS["muted"],
                            text_align=ft.TextAlign.CENTER,
                        ),
                        self.weekly_mode_switch,
                    ],
                    spacing=1,
                    tight=True,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(width=1, height=46, bgcolor=COLORS["border"]),
                ft.Column(
                    [
                        ft.Text(
                            "隐藏不可用任务",
                            size=12,
                            color=COLORS["muted"],
                            text_align=ft.TextAlign.CENTER,
                        ),
                        self.hide_unavailable_tasks,
                    ],
                    spacing=1,
                    tight=True,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            spacing=8,
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        accounts_panel = self._panel(
            "账号 / 角色状态",
            ft.Icons.GROUP_ROUNDED,
            self.cards_grid,
            expand=True,
            subtitle=self.summary_text,
            heading_extra=task_filter,
            compact_heading=True,
            actions=ft.Row(
                [
                    self.refresh_button,
                    self.start_button,
                ],
                spacing=10,
            ),
        )
        log_panel = self._panel(
            "日常 / 周常任务日志",
            ft.Icons.TERMINAL_ROUNDED,
            self.log_view,
            expand=True,
        )
        body = ft.Row(
            [
                accounts_panel,
                ft.Container(log_panel, width=410),
            ],
            spacing=14,
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        return body

    def _build_tool_selector(self) -> ft.Container:
        controls = []
        for key, label in TOOL_LABELS.items():
            item = ft.Container(
                data=key,
                padding=ft.Padding.symmetric(horizontal=20, vertical=10),
                border_radius=8,
                bgcolor="#171E2A",
                content=ft.Text(label, size=13, color=COLORS["text"]),
                on_click=self._on_tool_selected,
            )
            self.tool_nav_items[key] = item
            controls.append(item)
        self._apply_tool_navigation_style()
        return ft.Container(
            bgcolor="#20232B",
            border_radius=10,
            padding=4,
            content=ft.Row(controls, spacing=4, scroll=ft.ScrollMode.AUTO),
        )

    def _apply_tool_navigation_style(self) -> None:
        for key, item in self.tool_nav_items.items():
            selected = key == self.active_tool
            item.bgcolor = COLORS["active_bg"] if selected else "#171E2A"
            item.content.color = COLORS["active"] if selected else COLORS["text"]
            item.border = ft.Border.all(
                1,
                COLORS["active"] if selected else "transparent",
            )

    def _on_tool_selected(self, event: Any) -> None:
        if self.tool_running:
            return
        tool_name = str(event.control.data)
        if tool_name not in TOOL_MODULE_PATHS:
            return
        self.active_tool = tool_name
        self._apply_tool_navigation_style()
        self.tool_title.value = TOOL_LABELS[tool_name]
        self.tool_description.value = TOOL_DESCRIPTIONS[tool_name]
        self.secret_attempts_control.visible = tool_name == "secret_battle"
        self.tool_start_button.content = "开始"
        self._safe_update()

    def _build_tools_page(self) -> ft.Control:
        self.tool_title = ft.Text(
            TOOL_LABELS[self.active_tool],
            size=18,
            weight=ft.FontWeight.BOLD,
            color=COLORS["text"],
        )
        selector = self._build_tool_selector()
        tool_card = self._panel(
            "工具控制",
            ft.Icons.BUILD_ROUNDED,
            ft.Column(
                [
                    self.tool_title,
                    self.tool_description,
                    self.secret_attempts_control,
                    ft.Divider(height=8, color=COLORS["border"]),
                    ft.Row(
                        [
                            ft.Icon(
                                ft.Icons.INFO_OUTLINE_ROUNDED,
                                size=16,
                                color=COLORS["active"],
                            ),
                            self.tool_status,
                        ],
                        spacing=7,
                    ),
                ],
                spacing=12,
            ),
            actions=self.tool_start_button,
        )
        tool_log_panel = self._panel(
            "小工具日志",
            ft.Icons.TERMINAL_ROUNDED,
            self.tool_log_view,
            expand=True,
        )
        content = ft.Row(
            [
                ft.Container(tool_card, width=440),
                tool_log_panel,
            ],
            spacing=14,
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        return ft.Column([selector, content], spacing=14, expand=True)

    def _build_settings_page(self) -> ft.Control:
        self.settings_sections = {
            "global": self._build_global_settings_panel(),
            "tasks": self._build_task_settings_panel(),
            "wallpaper": self._build_wallpaper_settings_panel(),
        }
        self.settings_content_host = ft.Container(
            content=self.settings_sections[self.active_settings_section],
            expand=True,
        )
        return ft.Row(
            [
                self._build_settings_navigation(),
                ft.VerticalDivider(width=1, color=COLORS["border"]),
                ft.Column(
                    [self.settings_content_host],
                    expand=True,
                    scroll=ft.ScrollMode.AUTO,
                ),
            ],
            spacing=14,
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

    def _build_settings_navigation(self) -> ft.Container:
        entries = (
            ("global", "全局设置", ft.Icons.SETTINGS_ROUNDED),
            ("tasks", "任务设置", ft.Icons.TUNE_ROUNDED),
            ("wallpaper", "壁纸设置", ft.Icons.WALLPAPER_ROUNDED),
        )
        controls: list[ft.Control] = []
        for key, label, icon in entries:
            item = ft.Container(
                data=key,
                height=48,
                border_radius=10,
                padding=ft.Padding.symmetric(horizontal=12),
                content=ft.Row(
                    [
                        ft.Icon(icon, size=19),
                        ft.Text(label, size=14, weight=ft.FontWeight.W_600),
                    ],
                    spacing=10,
                ),
                on_click=self._on_settings_navigation_click,
            )
            self.settings_nav_items[key] = item
            controls.append(item)
        self._apply_settings_navigation_style()
        return ft.Container(
            width=210,
            padding=10,
            bgcolor="#C9111827",
            border=ft.Border.all(1, COLORS["border"]),
            border_radius=14,
            content=ft.Column(controls, spacing=4),
        )

    def _apply_settings_navigation_style(self) -> None:
        for key, item in self.settings_nav_items.items():
            selected = key == self.active_settings_section
            item.bgcolor = COLORS["active_bg"] if selected else "transparent"
            item.border = ft.Border.all(
                1, COLORS["active"] if selected else "transparent"
            )
            for control in item.content.controls:
                control.color = COLORS["active"] if selected else COLORS["text"]

    def _on_settings_navigation_click(self, event: Any) -> None:
        section = str(event.control.data)
        if section not in self.settings_sections:
            return
        self.active_settings_section = section
        self.settings_content_host.content = self.settings_sections[section]
        self._apply_settings_navigation_style()
        self._safe_update()

    def _build_global_settings_panel(self) -> ft.Control:
        settings_content = ft.Column(
            [
                ft.Text("运行路径", size=12, weight=ft.FontWeight.BOLD),
                ft.Row(
                    [self.adb_path_field, self.adb_path_button],
                    spacing=4,
                ),
                ft.Row(
                    [self.mumu_path_field, self.mumu_path_button],
                    spacing=4,
                ),
                ft.Row(
                    [self.mumu_instance, self.mumu_refresh_button],
                    spacing=4,
                ),
                self.mumu_status,
                ft.Divider(height=10, color=COLORS["border"]),
                ft.Text("检测参数", size=12, weight=ft.FontWeight.BOLD),
                ft.Row(
                    [
                        self.screenshot_interval,
                        self.battle_detection_interval,
                        self.log_max_lines,
                    ],
                    spacing=8,
                ),
                ft.Divider(height=10, color=COLORS["border"]),
                ft.Text("超时恢复", size=12, weight=ft.FontWeight.BOLD),
                ft.Row(
                    [
                        self.recovery_retry_count,
                        self.timeout_screenshot_keep_count,
                    ],
                    spacing=8,
                ),
                ft.Row(
                    [
                        self.recovery_timeout_seconds,
                        self.recovery_unknown_grace_seconds,
                    ],
                    spacing=8,
                ),
                ft.Text(
                    "截图保留数量填 0 表示不保留；任务恢复重试次数填 0 表示失败后不恢复。",
                    size=11,
                    color=COLORS["muted"],
                ),
                ft.Divider(height=10, color=COLORS["border"]),
                ft.Text("推送设置", size=12, weight=ft.FontWeight.BOLD),
                self.serverchan_enabled,
                ft.Row(
                    [
                        self.serverchan_sendkey,
                        self.serverchan_save_key_button,
                        self.serverchan_clear_key_button,
                    ],
                    spacing=8,
                ),
                self.serverchan_status,
                ft.Text(
                    "仅在当前检测时段的悬赏与开放的奸商检测全部结束后推送一次；普通任务结束不推送。",
                    size=11,
                    color=COLORS["muted"],
                ),
                ft.Row(
                    [
                        self.settings_message,
                        ft.Button(
                            content="保存",
                            icon=ft.Icons.SAVE_ROUNDED,
                            on_click=self.save_settings,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
            ],
            spacing=8,
        )
        return self._panel(
            "全局设置",
            ft.Icons.SETTINGS_ROUNDED,
            settings_content,
        )

    def _build_task_settings_panel(self) -> ft.Control:
        task_checks = ft.ResponsiveRow(
            [
                ft.Container(
                    checkbox,
                    col={"sm": 6, "md": 6},
                )
                for checkbox in self.task_settings_checks.values()
            ],
            columns=12,
            spacing=4,
            run_spacing=2,
        )
        task_settings_content = ft.Column(
            [
                self.task_settings_role,
                ft.Text(
                    "每个账号的 IOS / Android 独立保存；关闭后不会进入执行队列。",
                    size=11,
                    color=COLORS["muted"],
                ),
                self.cross_region_enabled,
                ft.Text(
                    "每个账号及系统均可独立启用；砂狐乐园固定执行悬赏检测和两位跨区好友点赞。",
                    size=11,
                    color=COLORS["muted"],
                ),
                ft.Divider(height=10, color=COLORS["border"]),
                task_checks,
                self.heart_team_role_setting,
                ft.Text(
                    "队长负责战斗；成员补存会保留随机登录顺序，并在全部角色任务结束后统一收尾执行。",
                    size=11,
                    color=COLORS["muted"],
                ),
                ft.Row(
                    [
                        ft.Button(
                            content="全选",
                            icon=ft.Icons.SELECT_ALL_ROUNDED,
                            on_click=lambda _event: self._set_all_task_settings(True),
                        ),
                        ft.Button(
                            content="清空",
                            icon=ft.Icons.DESELECT_ROUNDED,
                            on_click=lambda _event: self._set_all_task_settings(False),
                        ),
                    ],
                    spacing=8,
                ),
                ft.Row(
                    [
                        self.task_settings_message,
                        ft.Button(
                            content="保存任务设置",
                            icon=ft.Icons.SAVE_ROUNDED,
                            bgcolor=COLORS["active"],
                            color="#07111F",
                            on_click=self.save_task_settings,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
            ],
            spacing=8,
        )
        return self._panel(
            "任务设置",
            ft.Icons.TUNE_ROUNDED,
            task_settings_content,
            actions=ft.IconButton(
                icon=ft.Icons.REFRESH_ROUNDED,
                icon_color=COLORS["muted"],
                tooltip="重新读取账号与任务设置",
                on_click=self.refresh_task_settings,
            ),
        )

    def _build_wallpaper_settings_panel(self) -> ft.Control:
        content = ft.Column(
            [
                ft.Text("背景图片", size=12, weight=ft.FontWeight.BOLD),
                ft.Row(
                    [self.wallpaper_path_field, self.wallpaper_path_button],
                    spacing=4,
                ),
                ft.Text("背景不透明度", size=12, color=COLORS["muted"]),
                self.wallpaper_opacity,
                ft.Text("背景模糊半径", size=12, color=COLORS["muted"]),
                self.wallpaper_blur,
                self.wallpaper_fit,
                ft.Divider(height=10, color=COLORS["border"]),
                self.monet_enabled,
                ft.Text(
                    "开启后会从壁纸提取主色，生成界面强调色和深色表面色。",
                    size=11,
                    color=COLORS["muted"],
                ),
                self.monet_palette_row,
                ft.Row(
                    [
                        ft.Button(
                            content="清除壁纸",
                            icon=ft.Icons.DELETE_OUTLINE_ROUNDED,
                            on_click=self.clear_wallpaper,
                        ),
                        ft.Row(
                            [
                                self.wallpaper_message,
                                ft.Button(
                                    content="保存壁纸设置",
                                    icon=ft.Icons.SAVE_ROUNDED,
                                    bgcolor=COLORS["active"],
                                    color="#07111F",
                                    on_click=self.save_wallpaper_settings,
                                ),
                            ],
                            spacing=10,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
            ],
            spacing=10,
        )
        return self._panel(
            "壁纸设置",
            ft.Icons.WALLPAPER_ROUNDED,
            content,
        )

    @staticmethod
    def _task_role_key(account: str, system: str) -> str:
        return json.dumps([account, system], ensure_ascii=False)

    @staticmethod
    def _parse_task_role_key(value: Any) -> Optional[tuple[str, str]]:
        try:
            parsed = json.loads(str(value))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if (
            not isinstance(parsed, list)
            or len(parsed) != 2
            or not all(isinstance(item, str) for item in parsed)
        ):
            return None
        return parsed[0], parsed[1]

    def _reload_task_settings_roles(self, update: bool = True) -> bool:
        current_value = self.task_settings_role.value
        try:
            state, migrated = controller.load_state(controller.STATUS_PATH)
            if migrated:
                controller.save_state(state, controller.STATUS_PATH)
        except Exception as exc:
            self.task_settings_state = None
            self.task_settings_role.options = []
            self.task_settings_role.value = None
            self.task_settings_message.value = f"读取账号状态失败：{exc}"
            self.task_settings_message.color = COLORS["error"]
            for checkbox in self.task_settings_checks.values():
                checkbox.disabled = True
            self.cross_region_enabled.disabled = True
            self.cross_region_enabled.value = False
            self.heart_team_role_setting.disabled = True
            self.heart_team_role_setting.value = "none"
            if update:
                self._safe_update()
            return False

        options: list[ft.DropdownOption] = []
        keys: list[str] = []
        for account, account_state in state["accounts"].items():
            for system in account_state["systems"]:
                key = self._task_role_key(account, system)
                keys.append(key)
                options.append(
                    ft.DropdownOption(
                        key=key,
                        text=f"{account} · {system}",
                    )
                )

        selected = current_value if current_value in keys else (keys[0] if keys else None)
        self.task_settings_state = state
        self.task_settings_role.options = options
        self.task_settings_role.value = selected
        self.task_settings_message.value = ""
        self._apply_task_settings_selection()
        if update:
            self._safe_update()
        return True

    def _apply_task_settings_selection(self) -> None:
        role = self._parse_task_role_key(self.task_settings_role.value)
        system_state = None
        if role is not None and self.task_settings_state is not None:
            account, system = role
            account_state = self.task_settings_state.get("accounts", {}).get(
                account,
                {},
            )
            system_state = account_state.get("systems", {}).get(system)
        for task_name, checkbox in self.task_settings_checks.items():
            checkbox.disabled = system_state is None
            checkbox.value = (
                controller.task_is_enabled(system_state, task_name)
                if isinstance(system_state, dict)
                else False
            )
        self.cross_region_enabled.disabled = system_state is None
        self.cross_region_enabled.value = bool(
            isinstance(system_state, dict)
            and controller.cross_region_is_enabled(system_state)
        )
        self.heart_team_role_setting.disabled = system_state is None
        selected_heart_role = (
            controller.heart_team_role(system_state)
            if isinstance(system_state, dict)
            else None
        )
        self.heart_team_role_setting.value = selected_heart_role or "none"
        heart_checkbox = self.task_settings_checks[controller.HEART_TEAM_TASK]
        if selected_heart_role not in controller.HEART_TEAM_ROLES:
            heart_checkbox.value = False
            heart_checkbox.disabled = True

    def _on_task_settings_role_selected(self, _event: Any = None) -> None:
        self.task_settings_message.value = ""
        self._apply_task_settings_selection()
        self._safe_update()

    def _on_cross_region_setting_changed(self, _event: Any = None) -> None:
        self.task_settings_message.value = "尚未保存"
        self.task_settings_message.color = COLORS["warning"]
        self._safe_update()

    def _on_heart_team_role_selected(self, _event: Any = None) -> None:
        heart_checkbox = self.task_settings_checks[controller.HEART_TEAM_TASK]
        has_role = (
            self.heart_team_role_setting.value
            in controller.HEART_TEAM_ROLES
        )
        heart_checkbox.disabled = not has_role
        if not has_role:
            heart_checkbox.value = False
        self.task_settings_message.value = "尚未保存"
        self.task_settings_message.color = COLORS["warning"]
        self._safe_update()

    def _set_all_task_settings(self, enabled: bool) -> None:
        if self.task_settings_role.value is None:
            return
        for checkbox in self.task_settings_checks.values():
            checkbox.value = enabled
        if (
            self.heart_team_role_setting.value
            not in controller.HEART_TEAM_ROLES
        ):
            self.task_settings_checks[controller.HEART_TEAM_TASK].value = False
        self.task_settings_message.value = "尚未保存"
        self.task_settings_message.color = COLORS["warning"]
        self._safe_update()

    def refresh_task_settings(self, _event: Any = None) -> None:
        if self.running:
            self.task_settings_message.value = "一键长草运行中，暂不能刷新"
            self.task_settings_message.color = COLORS["warning"]
            self._safe_update()
            return
        self._reload_task_settings_roles()

    def save_task_settings(self, _event: Any = None) -> bool:
        if self.running:
            self.task_settings_message.value = "一键长草运行中，暂不能修改"
            self.task_settings_message.color = COLORS["warning"]
            self._safe_update()
            return False
        role = self._parse_task_role_key(self.task_settings_role.value)
        if role is None:
            self.task_settings_message.value = "请先选择账号和系统角色"
            self.task_settings_message.color = COLORS["error"]
            self._safe_update()
            return False

        account, system = role
        try:
            state, _ = controller.load_state(controller.STATUS_PATH)
            system_state = state["accounts"][account]["systems"][system]
            system_state["cross_region_enabled"] = bool(
                self.cross_region_enabled.value
            )
            selected_heart_role = str(self.heart_team_role_setting.value)
            controller.set_heart_team_role(
                system_state,
                selected_heart_role
                if selected_heart_role in controller.HEART_TEAM_ROLES
                else None,
            )
            system_state["task_enabled"] = {
                task_name: bool(checkbox.value)
                for task_name, checkbox in self.task_settings_checks.items()
            }
            controller.save_state(state, controller.STATUS_PATH)
        except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
            self.task_settings_message.value = f"保存失败：{exc}"
            self.task_settings_message.color = COLORS["error"]
            self._safe_update()
            return False

        self.task_settings_state = state
        self.task_settings_message.value = f"{account} · {system} 已保存"
        self.task_settings_message.color = COLORS["done"]
        self.refresh_cards(update=False)
        self._safe_update()
        return True

    def _safe_update(self) -> None:
        try:
            self.page.update()
        except Exception as exc:
            self._report_ui_exception("刷新页面", exc)

    def _report_ui_exception(self, context: str, exc: BaseException) -> None:
        """将 UI 无法展示的异常回退到启动控制台，并抑制重复刷屏。"""
        signature = (context, type(exc).__name__, str(exc))
        reported = getattr(self, "_reported_ui_errors", None)
        if reported is None:
            reported = set()
            self._reported_ui_errors = reported
        if signature in reported:
            return
        if len(reported) >= 100:
            reported.clear()
        reported.add(signature)

        stream = sys.__stderr__ or sys.stderr
        if stream is None:
            return
        try:
            timestamp = datetime.now().strftime("%H:%M:%S")
            stream.write(
                f"{timestamp} [ERROR] [UI/{context}] "
                f"{type(exc).__name__}: {exc}\n"
            )
            traceback.print_exception(
                type(exc),
                exc,
                exc.__traceback__,
                file=stream,
            )
            stream.flush()
        except Exception:
            # 控制台可能已随窗口关闭；异常上报本身不能影响 UI 工作线程。
            return

    def _append_ui_event_error(self, event_type: str, exc: BaseException) -> None:
        """尽量在 UI 内显示事件异常；失败时仍保留控制台 traceback。"""
        self._report_ui_exception(f"处理事件 {event_type}", exc)
        try:
            self._append_log_now(
                "ERROR",
                f"UI 事件处理失败（{event_type}）："
                f"{type(exc).__name__}: {exc}",
            )
        except Exception as render_exc:
            self._report_ui_exception("显示 UI 异常", render_exc)

    def append_log(self, level: str, message: str) -> None:
        """任意线程只入队，不直接修改 Flet 控件。"""
        if not message.strip():
            return
        self.ui_queue.put(("log", (level, message)))

    def _append_log_now(self, level: str, message: str) -> None:
        """仅由页面事件循环调用。"""
        standardized = re.match(
            r"^\d{2}:\d{2}:\d{2} \[(INFO|WARN|ERROR|SUCCESS|VISION|ACTION)\] ",
            message,
        )
        if standardized:
            level = standardized.group(1)
        elif "[ERROR]" in message:
            level = "ERROR"
        color = {
            "ERROR": COLORS["error"],
            "WARN": COLORS["warning"],
            "SUCCESS": COLORS["done"],
            "VISION": COLORS["active"],
            "ACTION": COLORS["done"],
        }.get(level, COLORS["muted"])
        rendered = message
        if not standardized:
            timestamp = datetime.now().strftime("%H:%M:%S")
            rendered = f"{timestamp} [{level}] [UI/运行] {message}"
        self.log_view.controls.append(
            ft.Text(
                rendered,
                size=11,
                color=color,
                font_family="Consolas",
                selectable=True,
            )
        )
        maximum = int(self.settings.get("log_max_lines", 300))
        if len(self.log_view.controls) > maximum:
            del self.log_view.controls[: len(self.log_view.controls) - maximum]

    def append_tool_log(self, level: str, message: str) -> None:
        if message.strip():
            self.ui_queue.put(("tool_log", (level, message)))

    def _append_tool_log_now(self, level: str, message: str) -> None:
        standardized = re.match(
            r"^\d{2}:\d{2}:\d{2} \[(INFO|WARN|ERROR|SUCCESS|VISION|ACTION)\] ",
            message,
        )
        if standardized:
            level = standardized.group(1)
        else:
            inline_level = re.match(
                r"^\[(INFO|WARN|ERROR|SUCCESS|VISION|ACTION)\]\s*(.*)$",
                message,
                flags=re.DOTALL,
            )
            if inline_level:
                level = inline_level.group(1)
                message = inline_level.group(2)
            elif "[ERROR]" in message:
                level = "ERROR"
        color = {
            "ERROR": COLORS["error"],
            "WARN": COLORS["warning"],
            "SUCCESS": COLORS["done"],
            "VISION": COLORS["active"],
            "ACTION": COLORS["done"],
        }.get(level, COLORS["muted"])
        rendered = message
        logged_at = datetime.now()
        if not standardized:
            timestamp = logged_at.strftime("%H:%M:%S")
            rendered = f"{timestamp} [{level}] [小工具/运行] {message}"
        else:
            parsed_time = datetime.strptime(message[:8], "%H:%M:%S").time()
            logged_at = datetime.combine(logged_at.date(), parsed_time)
            now = datetime.now()
            if logged_at - now > timedelta(hours=12):
                logged_at -= timedelta(days=1)
            elif now - logged_at > timedelta(hours=12):
                logged_at += timedelta(days=1)

        self.tool_log_sequence += 1
        control = ft.Text(
            rendered,
            size=11,
            color=color,
            font_family="Consolas",
            selectable=True,
        )
        control.data = (logged_at.timestamp(), self.tool_log_sequence)
        self.tool_log_view.controls.append(control)
        self.tool_log_view.controls.sort(
            key=lambda item: item.data
            if isinstance(item.data, tuple)
            else (float("inf"), 0)
        )
        maximum = int(self.settings.get("log_max_lines", 300))
        if len(self.tool_log_view.controls) > maximum:
            del self.tool_log_view.controls[
                : len(self.tool_log_view.controls) - maximum
            ]

    async def _ui_update_pump(self) -> None:
        """在 Flet 页面事件循环中消费日志/状态，避免工作线程直接刷 UI。"""
        while True:
            try:
                changed = False
                # 限制单次处理量，避免大量 OCR 输出时卡住页面循环。
                for _ in range(100):
                    try:
                        event_type, payload = self.ui_queue.get_nowait()
                    except queue.Empty:
                        break

                    changed = True
                    try:
                        if event_type == "log":
                            level, message = payload
                            self._append_log_now(level, message)
                        elif event_type == "tool_log":
                            level, message = payload
                            self._append_tool_log_now(level, message)
                        elif event_type == "controller_event":
                            self._apply_controller_event(payload)
                        elif event_type == "worker_finished":
                            self._apply_worker_finished(**payload)
                        elif event_type == "tool_finished":
                            self._apply_tool_finished(**payload)
                        elif event_type == "secret_attempts":
                            self._apply_secret_attempts(payload)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        # 单条坏事件不能终止整个日志泵；继续处理后续日志。
                        self._append_ui_event_error(str(event_type), exc)

                if changed:
                    try:
                        self.page.update()
                    except Exception as exc:
                        # 会话短暂断开或控件刷新失败时保留消费循环。
                        self._report_ui_exception("刷新日志面板", exc)
                await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                # 兜住循环自身的意外错误，避免日志通道永久静默。
                self._report_ui_exception("日志刷新循环", exc)
                await asyncio.sleep(0.1)

    def refresh_cards(self, update: bool = True) -> bool:
        try:
            daily_state, migrated = controller.load_state(controller.STATUS_PATH)
            if migrated:
                controller.save_state(daily_state, controller.STATUS_PATH)
            if self.task_mode == controller.WEEKLY_MODE:
                state, weekly_migrated = controller.load_weekly_state(
                    controller.WEEKLY_STATUS_PATH,
                    daily_state,
                )
                if weekly_migrated or not controller.WEEKLY_STATUS_PATH.is_file():
                    controller.save_weekly_state(
                        state,
                        controller.WEEKLY_STATUS_PATH,
                    )
                active_accounts = daily_state["accounts"]
            else:
                state = daily_state
                active_accounts = daily_state["accounts"]
        except Exception as exc:
            self.append_log("ERROR", f"无法读取账号状态：{exc}")
            return False

        now = datetime.now().astimezone()
        self.cards.clear()
        self.cards_grid.controls.clear()
        for account, account_state in active_accounts.items():
            for system in account_state["systems"]:
                system_state = state["accounts"][account]["systems"][system]
                card = AccountCardView(
                    account,
                    system,
                    system_state,
                    now,
                    task_mode=self.task_mode,
                )
                self.cards[(account, system)] = card
                self.cards_grid.controls.append(card.control)
        self._apply_task_visibility()
        self._refresh_task_summary()
        if update:
            self._safe_update()
        return True

    def _refresh_task_summary(self) -> None:
        unfinished_statuses = {"pending", "active", "warning", "error"}
        due_systems = sum(
            any(
                view.status in unfinished_statuses
                for view in card.task_views.values()
            )
            for card in self.cards.values()
        )
        self.summary_text.value = (
            f"{len(self.cards)} 个角色 · {due_systems} 个待执行"
        )

    def refresh_status(self, _event: Any = None) -> None:
        if self.running:
            return
        if self.refresh_cards():
            status_file = (
                "config/weekly_account_status.json"
                if self.task_mode == controller.WEEKLY_MODE
                else "config/account_status.json"
            )
            self.append_log("INFO", f"已重新读取 {status_file}")

    def _refresh_serverchan_status(self) -> None:
        configured = bool(get_serverchan_sendkey())
        self.serverchan_status.value = (
            "SENDKEY 已保存"
            if configured
            else "尚未配置。请到 https://sct.ftqq.com 免费获取（每天 5 条额度）"
        )
        self.serverchan_status.color = (
            COLORS["done"] if configured else COLORS["warning"]
        )
        self.serverchan_sendkey.hint_text = (
            "环境变量已配置；留空不会修改"
            if configured
            else "输入 SendKey 后点击保存 API"
        )

    def _on_serverchan_enabled_changed(self, _event: Any = None) -> None:
        self.settings["serverchan_enabled"] = bool(self.serverchan_enabled.value)
        self._refresh_serverchan_status()
        try:
            save_ui_settings(self.settings)
        except OSError as exc:
            self.serverchan_status.value = f"保存推送开关失败：{exc}"
            self.serverchan_status.color = COLORS["error"]
        self._safe_update()

    def save_serverchan_key(self, _event: Any = None) -> bool:
        send_key = str(self.serverchan_sendkey.value or "").strip()
        if not send_key:
            self.serverchan_status.value = "请输入 SendKey"
            self.serverchan_status.color = COLORS["error"]
            self._safe_update()
            return False
        try:
            set_project_sendkey(send_key)
        except (OSError, ValueError) as exc:
            self.serverchan_status.value = f"保存 API 失败：{exc}"
            self.serverchan_status.color = COLORS["error"]
            self._safe_update()
            return False
        finally:
            send_key = ""
        self.serverchan_sendkey.value = ""
        self._refresh_serverchan_status()
        self._safe_update()
        return True

    def clear_serverchan_key(self, _event: Any = None) -> None:
        try:
            clear_project_sendkey()
        except OSError:
            self.serverchan_status.value = "清除 API 失败，请检查系统权限"
            self.serverchan_status.color = COLORS["error"]
            self._safe_update()
            return
        self.serverchan_sendkey.value = ""
        self._refresh_serverchan_status()
        self._safe_update()

    def _apply_task_visibility(self) -> None:
        hide_unavailable = bool(self.hide_unavailable_tasks.value)
        for card in self.cards.values():
            for task_view in card.task_views.values():
                task_view.control.visible = not (
                    hide_unavailable
                    and task_view.status in {"unavailable", "disabled"}
                )

    def _on_hide_unavailable_changed(self, _event: Any = None) -> None:
        self._apply_task_visibility()
        self.settings["hide_unavailable_tasks"] = bool(
            self.hide_unavailable_tasks.value
        )
        try:
            save_ui_settings(self.settings)
        except OSError as exc:
            self.append_log("ERROR", f"保存任务显示设置失败：{exc}")
        self._safe_update()

    def _on_task_mode_changed(self, _event: Any = None) -> None:
        if self.running:
            return
        self.task_mode = (
            controller.WEEKLY_MODE
            if self.weekly_mode_switch.value
            else controller.DAILY_MODE
        )
        self.refresh_cards(update=False)
        label = "周常" if self.task_mode == controller.WEEKLY_MODE else "日常"
        self.append_log("INFO", f"已切换到{label}任务")
        self._safe_update()

    def _wallpaper_box_fit(self) -> ft.BoxFit:
        value = (
            str(self.wallpaper_fit.value)
            if hasattr(self, "wallpaper_fit")
            else str(self.settings.get("wallpaper_fit", "cover"))
        )
        return {
            "none": ft.BoxFit.NONE,
            "contain": ft.BoxFit.CONTAIN,
            "fill": ft.BoxFit.FILL,
        }.get(value, ft.BoxFit.COVER)

    def _refresh_monet_palette_preview(self) -> None:
        palette = self.settings.get("monet_palette", {})
        colors = [
            ("主色", str(palette.get("primary"))),
            ("辅助色", str(palette.get("secondary"))),
            ("表面色", str(palette.get("surface_variant"))),
            ("边框色", str(palette.get("outline"))),
        ]
        self.monet_palette_row.controls = [
            ft.Column(
                [
                    ft.Container(
                        width=30,
                        height=30,
                        border_radius=8,
                        bgcolor=color,
                        border=ft.Border.all(1, "#66FFFFFF"),
                        tooltip=color,
                    ),
                    ft.Text(label, size=10, color=COLORS["muted"]),
                ],
                spacing=3,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            )
            for label, color in colors
            if color and color != "None"
        ]
        self.monet_palette_row.visible = bool(self.monet_palette_row.controls)

    def _apply_monet_palette(self, palette: dict[str, str]) -> None:
        if not palette:
            return
        COLORS["active"] = str(palette.get("primary", DEFAULT_ACCENT))
        COLORS["panel"] = str(palette.get("surface", COLORS["panel"]))
        COLORS["panel_alt"] = str(
            palette.get("surface_variant", COLORS["panel_alt"])
        )
        COLORS["border"] = str(palette.get("outline", COLORS["border"]))
        self.page.theme = ft.Theme(
            font_family="Microsoft YaHei UI",
            color_scheme_seed=COLORS["active"],
        )
        self.wallpaper_opacity.active_color = COLORS["active"]
        self.wallpaper_blur.active_color = COLORS["active"]
        self.monet_enabled.active_color = COLORS["active"]
        self.hide_unavailable_tasks.active_color = COLORS["active"]
        self.serverchan_enabled.active_color = COLORS["active"]
        self.start_button.bgcolor = COLORS["active"]
        self.tool_start_button.bgcolor = COLORS["active"]
        self._apply_navigation_style()
        self._apply_settings_navigation_style()

    def _apply_default_palette(self) -> None:
        COLORS.update(BASE_COLORS)
        self.page.theme = ft.Theme(
            font_family="Microsoft YaHei UI",
            color_scheme_seed=COLORS["active"],
        )
        self.wallpaper_opacity.active_color = COLORS["active"]
        self.wallpaper_blur.active_color = COLORS["active"]
        self.monet_enabled.active_color = COLORS["active"]
        self.hide_unavailable_tasks.active_color = COLORS["active"]
        self.serverchan_enabled.active_color = COLORS["active"]
        self.start_button.bgcolor = COLORS["active"]
        self.tool_start_button.bgcolor = COLORS["active"]

    def _sync_wallpaper_preview_settings(self) -> None:
        self.settings.update(
            {
                "wallpaper_path": str(self.wallpaper_path_field.value or ""),
                "wallpaper_opacity": float(self.wallpaper_opacity.value or 0) / 100.0,
                "wallpaper_blur": float(self.wallpaper_blur.value or 0),
                "wallpaper_fit": str(self.wallpaper_fit.value or "cover"),
                "monet_enabled": bool(self.monet_enabled.value),
            }
        )

    def _rebuild_theme_layout(self) -> None:
        if not self.page.controls:
            return
        active_section = self.active_section
        self.refresh_cards(update=False)
        self.page.controls[0] = self._build_layout()
        self._show_section(active_section, update=False)

    async def pick_wallpaper_path(self, _event: Any = None) -> None:
        current = Path(str(self.wallpaper_path_field.value or "")).expanduser()
        initial_directory = current.parent if current.parent.is_dir() else None
        selected = await self.wallpaper_file_picker.pick_files(
            dialog_title="选择壁纸图片",
            initial_directory=(str(initial_directory) if initial_directory else None),
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["png", "jpg", "jpeg", "webp", "bmp"],
            allow_multiple=False,
        )
        if not selected or not selected[0].path:
            return
        self.wallpaper_path_field.value = selected[0].path
        self.wallpaper_message.value = "预览中，保存后保留"
        self.wallpaper_message.color = COLORS["warning"]
        if self.monet_enabled.value:
            try:
                palette = extract_monet_palette(selected[0].path)
                self.settings["monet_palette"] = palette
                self._monet_palette_path = selected[0].path
                self._apply_monet_palette(palette)
                self._refresh_monet_palette_preview()
            except (OSError, ValueError) as exc:
                self.wallpaper_message.value = f"取色失败：{exc}"
                self.wallpaper_message.color = COLORS["error"]
        self._sync_wallpaper_preview_settings()
        self._rebuild_theme_layout()
        self.preview_wallpaper_settings()

    def preview_wallpaper_settings(self, _event: Any = None) -> None:
        if not hasattr(self, "wallpaper_image"):
            return
        path = str(self.wallpaper_path_field.value or "")
        wallpaper_file = Path(path)
        visible = bool(path and wallpaper_file.is_file())
        self.wallpaper_image.src = wallpaper_file.read_bytes() if visible else b""
        self.wallpaper_image.visible = visible
        self.wallpaper_image.opacity = float(self.wallpaper_opacity.value or 0) / 100.0
        self.wallpaper_image.fit = self._wallpaper_box_fit()
        self.wallpaper_blur_layer.blur = float(self.wallpaper_blur.value or 0)
        self.wallpaper_blur_layer.visible = visible
        self._safe_update()

    def _on_monet_changed(self, _event: Any = None) -> None:
        path = str(self.wallpaper_path_field.value or "")
        if self.monet_enabled.value and path and Path(path).is_file():
            try:
                palette = (
                    dict(self.settings.get("monet_palette", {}))
                    if self._monet_palette_path == path
                    else extract_monet_palette(path)
                )
                self.settings["monet_palette"] = palette
                self._monet_palette_path = path
                self._apply_monet_palette(palette)
                self._refresh_monet_palette_preview()
                self.wallpaper_message.value = "已自动从壁纸取色"
                self.wallpaper_message.color = COLORS["done"]
            except (OSError, ValueError) as exc:
                self.wallpaper_message.value = f"取色失败：{exc}"
                self.wallpaper_message.color = COLORS["error"]
        elif not self.monet_enabled.value:
            self.settings["monet_palette"] = {}
            self._monet_palette_path = ""
            self._apply_default_palette()
            self._refresh_monet_palette_preview()
        self._sync_wallpaper_preview_settings()
        self._rebuild_theme_layout()
        self.preview_wallpaper_settings()

    def clear_wallpaper(self, _event: Any = None) -> None:
        self.wallpaper_path_field.value = ""
        self.settings["monet_palette"] = {}
        self._monet_palette_path = ""
        self._refresh_monet_palette_preview()
        self.wallpaper_message.value = "壁纸已从预览移除，点击保存后生效"
        self.wallpaper_message.color = COLORS["warning"]
        self.preview_wallpaper_settings()

    def save_wallpaper_settings(self, _event: Any = None) -> bool:
        path = str(self.wallpaper_path_field.value or "").strip()
        if path and not Path(path).is_file():
            self.wallpaper_message.value = "请选择有效的图片文件"
            self.wallpaper_message.color = COLORS["error"]
            self._safe_update()
            return False
        palette: dict[str, str] = {}
        if path and self.monet_enabled.value:
            try:
                palette = (
                    dict(self.settings.get("monet_palette", {}))
                    if self._monet_palette_path == path
                    else extract_monet_palette(path)
                )
            except (OSError, ValueError) as exc:
                self.wallpaper_message.value = f"取色失败：{exc}"
                self.wallpaper_message.color = COLORS["error"]
                self._safe_update()
                return False
        self.settings.update(
            {
                "wallpaper_path": path,
                "wallpaper_opacity": float(self.wallpaper_opacity.value or 0) / 100.0,
                "wallpaper_blur": float(self.wallpaper_blur.value or 0),
                "wallpaper_fit": str(self.wallpaper_fit.value or "cover"),
                "monet_enabled": bool(self.monet_enabled.value),
                "monet_palette": palette,
            }
        )
        try:
            save_ui_settings(self.settings)
        except OSError as exc:
            self.wallpaper_message.value = f"保存失败：{exc}"
            self.wallpaper_message.color = COLORS["error"]
            self._safe_update()
            return False
        if palette:
            self._apply_monet_palette(palette)
        else:
            self._apply_default_palette()
        self._refresh_monet_palette_preview()
        self._rebuild_theme_layout()
        self.preview_wallpaper_settings()
        self.wallpaper_message.value = "已保存"
        self.wallpaper_message.color = COLORS["done"]
        self._safe_update()
        return True

    async def pick_adb_path(self, _event: Any = None) -> None:
        current = Path(str(self.adb_path_field.value or DEFAULT_ADB_PATH))
        initial_directory = current.parent if current.parent.is_dir() else None
        selected = await self.adb_file_picker.pick_files(
            dialog_title="选择 adb.exe",
            initial_directory=(
                str(initial_directory)
                if initial_directory is not None
                else None
            ),
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["exe"],
            allow_multiple=False,
        )
        if selected and selected[0].path:
            self.adb_path_field.value = selected[0].path
            self.settings_message.value = ""
            self._safe_update()

    async def pick_mumu_path(self, _event: Any = None) -> None:
        current = str(self.mumu_path_field.value or DEFAULT_MUMU_PATH)
        initial_directory = current if Path(current).is_dir() else None
        selected = await self.mumu_directory_picker.get_directory_path(
            dialog_title="选择 MuMu 安装根目录",
            initial_directory=initial_directory,
        )
        if selected:
            self.mumu_path_field.value = selected
            self.refresh_mumu_instances()

    def _mumu_dropdown_options(self) -> list[ft.DropdownOption]:
        return [
            ft.DropdownOption(
                key=item["index"],
                text=f'{item["name"]} · 实例 {item["index"]}',
            )
            for item in self.mumu_instances
        ]

    def _selected_mumu(self) -> Optional[dict[str, str]]:
        selected_index = str(self.mumu_instance.value or "")
        return next(
            (
                item
                for item in self.mumu_instances
                if item["index"] == selected_index
            ),
            None,
        )

    def _update_mumu_status(self) -> None:
        selected = self._selected_mumu()
        if selected is not None:
            self.mumu_status.value = (
                f'ADB {selected["adb_port"]} · 截图与输入使用实例 {selected["index"]}'
            )
            self.mumu_status.color = COLORS["done"]
        elif self.mumu_instances:
            self.mumu_status.value = f"检测到 {len(self.mumu_instances)} 个运行实例，请选择一个"
            self.mumu_status.color = COLORS["warning"]
        else:
            self.mumu_status.value = "未检测到正在运行的 MuMu 模拟器"
            self.mumu_status.color = COLORS["error"]

    def _on_mumu_selected(self, _event: Any = None) -> None:
        self._update_mumu_status()
        self.settings_message.value = ""
        self._safe_update()

    def refresh_mumu_instances(self, _event: Any = None) -> None:
        if self.running:
            return
        current_index = str(self.mumu_instance.value or "")
        manager_path = resolve_mumu_manager_path(
            str(self.mumu_path_field.value or DEFAULT_MUMU_PATH)
        )
        self.mumu_instances = discover_running_mumu_instances(manager_path)
        available_indexes = {item["index"] for item in self.mumu_instances}
        if current_index in available_indexes:
            selected_index: Optional[str] = current_index
        elif len(self.mumu_instances) == 1:
            selected_index = self.mumu_instances[0]["index"]
        else:
            selected_index = None
        self.mumu_instance.options = self._mumu_dropdown_options()
        self.mumu_instance.value = selected_index
        self._update_mumu_status()
        self.settings_message.value = "已重新扫描"
        self.settings_message.color = COLORS["muted"]
        self._safe_update()

    def _read_settings_from_fields(self) -> Optional[dict[str, Any]]:
        adb_path = Path(str(self.adb_path_field.value or "").strip()).expanduser()
        mumu_path = Path(
            str(self.mumu_path_field.value or "").strip()
        ).expanduser()
        if not adb_path.is_file():
            self.settings_message.value = "请选择有效的 adb.exe"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return None
        if not mumu_path.is_dir():
            self.settings_message.value = "请选择有效的 MuMu 安装目录"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return None
        if not resolve_mumu_manager_path(mumu_path).is_file():
            self.settings_message.value = "MuMu 目录中未找到 MuMuManager.exe"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return None
        selected_mumu = self._selected_mumu()
        if selected_mumu is None:
            self.settings_message.value = "请先选择 MuMu 实例"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return None
        try:
            interval = float(str(self.screenshot_interval.value).strip())
            battle_interval = float(
                str(self.battle_detection_interval.value).strip()
            )
            max_lines = int(str(self.log_max_lines.value).strip())
            secret_attempts = int(str(self.secret_attempts_field.value).strip())
            recovery_retries = int(
                str(self.recovery_retry_count.value).strip()
            )
            recovery_timeout = float(
                str(self.recovery_timeout_seconds.value).strip()
            )
            unknown_grace = float(
                str(self.recovery_unknown_grace_seconds.value).strip()
            )
            screenshot_keep_count = int(
                str(self.timeout_screenshot_keep_count.value).strip()
            )
        except ValueError:
            self.settings_message.value = "参数必须是数字"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return None
        if not 0.1 <= interval <= 10:
            self.settings_message.value = "截图间隔需为 0.1–10"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return None
        if not 0.1 <= battle_interval <= 10:
            self.settings_message.value = "战斗检测间隔需为 0.1–10"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return None
        if not 50 <= max_lines <= 2000:
            self.settings_message.value = "日志行数需为 50–2000"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return None
        if secret_attempts < 0:
            self.settings_message.value = "协战次数不能小于 0"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return None
        if not 0 <= recovery_retries <= 5:
            self.settings_message.value = "任务恢复重试次数需为 0–5"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return None
        if not 10 <= recovery_timeout <= 600:
            self.settings_message.value = "恢复最长时间需为 10–600 秒"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return None
        if not 1 <= unknown_grace <= 60:
            self.settings_message.value = "未知界面容忍时间需为 1–60 秒"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return None
        if unknown_grace > recovery_timeout:
            self.settings_message.value = "未知界面容忍时间不能超过恢复最长时间"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return None
        if not 0 <= screenshot_keep_count <= 500:
            self.settings_message.value = "超时截图保留数量需为 0–500"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return None
        return {
            "screenshot_interval": interval,
            "battle_detection_interval": battle_interval,
            "log_max_lines": max_lines,
            "recovery_retry_count": recovery_retries,
            "recovery_timeout_seconds": recovery_timeout,
            "recovery_unknown_grace_seconds": unknown_grace,
            "timeout_screenshot_keep_count": screenshot_keep_count,
            "adb_path": str(adb_path),
            "mumu_path": str(mumu_path),
            "mumu_index": selected_mumu["index"],
            "adb_port": selected_mumu["adb_port"],
            "secret_battle_attempts": secret_attempts,
            "wallpaper_path": str(self.wallpaper_path_field.value or ""),
            "wallpaper_opacity": float(self.wallpaper_opacity.value or 0) / 100.0,
            "wallpaper_blur": float(self.wallpaper_blur.value or 0),
            "wallpaper_fit": str(self.wallpaper_fit.value or "cover"),
            "monet_enabled": bool(self.monet_enabled.value),
            "monet_palette": dict(self.settings.get("monet_palette", {})),
            "hide_unavailable_tasks": bool(self.hide_unavailable_tasks.value),
            "serverchan_enabled": bool(self.serverchan_enabled.value),
        }

    def save_settings(self, _event: Any = None) -> bool:
        if self.serverchan_enabled.value:
            pending_key = str(self.serverchan_sendkey.value or "").strip()
            if pending_key and not self.save_serverchan_key():
                return False
            if not get_serverchan_sendkey():
                self.settings_message.value = (
                    "启用推送前请配置 SERVERCHAN_SENDKEY；可到 https://sct.ftqq.com 免费获取"
                )
                self.settings_message.color = COLORS["error"]
                self._safe_update()
                return False
        settings = self._read_settings_from_fields()
        if settings is None:
            return False
        try:
            save_ui_settings(settings)
        except OSError as exc:
            self.settings_message.value = f"保存失败：{exc}"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return False
        self.settings = settings
        self.settings_message.value = "已保存"
        self.settings_message.color = COLORS["done"]
        self._safe_update()
        return True

    def _set_global_settings_disabled(self, disabled: bool) -> None:
        for control in self.global_setting_controls:
            control.disabled = disabled

    def _load_tool_module(self, tool_name: str):
        path = TOOL_MODULE_PATHS[tool_name]
        if not path.is_file():
            raise FileNotFoundError(f"小工具脚本不存在：{path}")
        module_name = f"yyshelper_tool_{tool_name}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法加载小工具：{path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    def start_selected_tool(self, _event: Any = None) -> None:
        if self.tool_running:
            return
        if self.running:
            self.append_tool_log("ERROR", "一键长草正在运行，不能同时启动小工具")
            return
        if self.active_tool == "secret_battle":
            try:
                attempts = int(str(self.secret_attempts_field.value).strip())
            except ValueError:
                attempts = 0
            if attempts <= 0:
                self.tool_status.value = "请填写大于 0 的协战次数"
                self.tool_status.color = COLORS["warning"]
                self.append_tool_log("WARN", "协战次数为 0，请先填写可用次数")
                self._safe_update()
                return
        if not self.save_settings():
            self.tool_status.value = "请先在设置页选择可用的 MuMu 实例"
            self.tool_status.color = COLORS["error"]
            self._show_section("settings")
            return

        self.tool_stop_event.clear()
        self.tool_running = True
        self.tool_start_button.content = "停止"
        self.tool_start_button.icon = ft.Icons.STOP_ROUNDED
        self.tool_start_button.bgcolor = COLORS["error_bg"]
        self.tool_start_button.color = COLORS["error"]
        self.start_button.disabled = True
        self.refresh_button.disabled = True
        self.secret_attempts_field.disabled = True
        self._set_global_settings_disabled(True)
        self.running_badge.visible = True
        self.running_badge_text.value = f"{TOOL_LABELS[self.active_tool]}运行中"
        self.tool_status.value = f"{TOOL_LABELS[self.active_tool]}正在运行"
        self.tool_status.color = COLORS["active"]
        self.append_tool_log(
            "INFO",
            f"准备启动{TOOL_LABELS[self.active_tool]}",
        )
        self._safe_update()
        self.page.run_thread(self._tool_worker, self.active_tool)

    def stop_selected_tool(self, _event: Any = None) -> None:
        if not self.tool_running:
            return
        self.tool_stop_event.set()
        self.tool_start_button.disabled = True
        self.tool_start_button.content = "停止中"
        self.tool_status.value = "正在等待当前截图步骤结束"
        self.tool_status.color = COLORS["warning"]
        self.append_tool_log("WARN", "已请求安全停止小工具")
        self._safe_update()

    def toggle_selected_tool(self, event: Any = None) -> None:
        if self.tool_running:
            self.stop_selected_tool(event)
        else:
            self.start_selected_tool(event)

    def _tool_worker(self, tool_name: str) -> None:
        writer = LineWriter(lambda line: self.append_tool_log("INFO", line))
        success = False
        previous_interval: Optional[float] = None
        try:
            from Core import automation

            automation.configure_runtime_paths(
                str(self.settings["adb_path"]),
                str(self.settings["mumu_path"]),
            )
            if not automation.configure_mumu_target(
                str(self.settings["adb_port"]),
                str(self.settings["mumu_index"]),
            ):
                raise OSError(f"无法连接 MuMu ADB：{self.settings['adb_port']}")
            previous_interval = automation.config.get("screenshot_speed", 0.5)
            module = self._load_tool_module(tool_name)
            battle_interval = float(self.settings["battle_detection_interval"])
            if hasattr(module, "BATTLE_SCREENSHOT_INTERVAL"):
                module.BATTLE_SCREENSHOT_INTERVAL = battle_interval
            if tool_name == "secret_battle" and hasattr(
                module,
                "SCREENSHOT_INTERVAL",
            ):
                module.SCREENSHOT_INTERVAL = battle_interval
            with redirect_stdout(writer), redirect_stderr(writer):
                if tool_name == "secret_battle":
                    result = module.run(
                        stop_event=self.tool_stop_event,
                        attempts=int(self.settings["secret_battle_attempts"]),
                        attempts_callback=self._queue_secret_attempts,
                    )
                else:
                    result = module.run(stop_event=self.tool_stop_event)
                success = bool(result)
        except Exception as exc:
            self.append_tool_log(
                "ERROR",
                f"{TOOL_LABELS.get(tool_name, tool_name)}发生异常：{exc}",
            )
            self._report_ui_exception(
                f"小工具线程 {TOOL_LABELS.get(tool_name, tool_name)}",
                exc,
            )
        finally:
            if previous_interval is not None:
                try:
                    from Core import automation

                    automation.config["screenshot_speed"] = previous_interval
                except Exception:
                    pass
            writer.flush()
            self.ui_queue.put(
                (
                    "tool_finished",
                    {
                        "success": success,
                        "stopped": self.tool_stop_event.is_set(),
                        "tool_name": tool_name,
                    },
                )
            )

    def _queue_secret_attempts(self, remaining: int) -> None:
        self.ui_queue.put(("secret_attempts", max(0, int(remaining))))

    def _apply_secret_attempts(self, remaining: int) -> None:
        remaining = max(0, int(remaining))
        self.secret_attempts_field.value = str(remaining)
        self.settings["secret_battle_attempts"] = remaining
        try:
            save_ui_settings(self.settings)
        except OSError as exc:
            self._append_tool_log_now("ERROR", f"保存剩余协战次数失败：{exc}")

    def _apply_tool_finished(
        self,
        success: bool,
        stopped: bool,
        tool_name: str,
    ) -> None:
        self.tool_running = False
        self.tool_start_button.disabled = False
        self.tool_start_button.content = "开始"
        self.tool_start_button.icon = ft.Icons.PLAY_ARROW_ROUNDED
        self.tool_start_button.bgcolor = COLORS["active"]
        self.tool_start_button.color = "#07111F"
        self.start_button.disabled = False
        self.refresh_button.disabled = False
        self.secret_attempts_field.disabled = False
        self._set_global_settings_disabled(False)
        self.running_badge.visible = False
        label = TOOL_LABELS.get(tool_name, tool_name)
        if stopped and success:
            self.tool_status.value = "已安全停止"
            self.tool_status.color = COLORS["done"]
            self._append_tool_log_now("SUCCESS", f"{label}已安全停止")
        elif success:
            self.tool_status.value = "运行结束"
            self.tool_status.color = COLORS["done"]
            self._append_tool_log_now("SUCCESS", f"{label}运行结束")
        else:
            self.tool_status.value = "执行失败"
            self.tool_status.color = COLORS["error"]

    def start_run(self, _event: Any = None) -> None:
        if self.running:
            return
        if self.tool_running:
            self.append_log("ERROR", "小工具正在运行，不能同时启动一键长草")
            return
        if not self.save_settings():
            self._show_section("settings")
            return
        if not self.refresh_cards():
            return
        self.stop_event.clear()
        self.running = True
        self.current_key = None
        self.start_button.content = "停止"
        self.start_button.icon = ft.Icons.STOP_ROUNDED
        self.start_button.bgcolor = COLORS["error_bg"]
        self.start_button.color = COLORS["error"]
        self.refresh_button.disabled = True
        self.weekly_mode_switch.disabled = True
        self._set_global_settings_disabled(True)
        self.tool_start_button.disabled = True
        self.running_badge.visible = True
        mode_label = "周常" if self.task_mode == controller.WEEKLY_MODE else "日常"
        self.running_badge_text.value = f"{mode_label}任务运行中"
        self.settings_message.value = ""
        self.append_log("INFO", f"开始生成{mode_label}待执行队列")
        self._safe_update()
        self.page.run_thread(self._controller_worker)

    def request_stop(self, _event: Any = None) -> None:
        if not self.running:
            return
        self.stop_event.set()
        self.start_button.disabled = True
        self.start_button.content = "停止中"
        if self.current_key in self.cards:
            self.cards[self.current_key].set_phase("warning", "等待当前步骤结束")
        self.append_log("WARN", "已请求安全停止，当前登录或任务阶段结束后生效")
        self._safe_update()

    def toggle_daily_run(self, event: Any = None) -> None:
        if self.running:
            self.request_stop(event)
        else:
            self.start_run(event)

    def _controller_worker(self) -> None:
        writer = LineWriter(lambda line: self.append_log("INFO", line))
        success = False
        try:
            with redirect_stdout(writer), redirect_stderr(writer):
                success = controller.run(
                    event_callback=self.handle_controller_event,
                    stop_event=self.stop_event,
                    runtime_settings=self.settings,
                    task_mode=self.task_mode,
                )
        except Exception as exc:
            self.append_log("ERROR", f"中控未捕获异常：{exc}")
            self._report_ui_exception("中控后台线程", exc)
        finally:
            writer.flush()
            self.ui_queue.put(
                (
                    "worker_finished",
                    {
                        "success": success,
                        "stopped": self.stop_event.is_set(),
                    },
                )
            )

    def _apply_worker_finished(
        self,
        success: bool,
        stopped: bool,
    ) -> None:
        """在 UI 事件循环中收尾，避免工作线程跨线程修改控件。"""
        self.running = False
        self.start_button.disabled = False
        self.start_button.content = "开始"
        self.start_button.icon = ft.Icons.PLAY_ARROW_ROUNDED
        self.start_button.bgcolor = COLORS["active"]
        self.start_button.color = "#07111F"
        self.refresh_button.disabled = False
        if hasattr(self, "weekly_mode_switch"):
            self.weekly_mode_switch.disabled = False
        self._set_global_settings_disabled(False)
        self.tool_start_button.disabled = False
        self.running_badge.visible = False
        # 无论成功、停止还是失败，都从持久化状态重建卡片。失败事件会
        # 临时修改任务图标和卡片边框；若不重建，这些运行态控件会一直
        # 残留，后续刷新布局时看起来像错位或卡住。
        self.current_key = None
        self.refresh_cards(update=False)
        if success:
            self._append_log_now("SUCCESS", "本轮到期任务已处理完成")
        elif stopped:
            self._append_log_now("WARN", "本轮任务已停止")
        else:
            self._append_log_now(
                "ERROR",
                "本轮执行失败，运行态界面已复位；错误详情请查看上方日志",
            )

    def handle_controller_event(self, event: dict[str, Any]) -> None:
        """中控回调在工作线程执行，只负责将状态事件入队。"""
        self.ui_queue.put(("controller_event", event))

    def _apply_controller_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        account = event.get("account")
        system = event.get("system")
        key = (account, system) if account and system else None
        card = self.cards.get(key) if key else None

        if event_type == "queue_built":
            queue = event.get("queue", [])
            self._append_log_now("INFO", f"待执行队列共 {len(queue)} 个账号/系统")
        elif event_type == "account_started" and card is not None:
            self.current_key = key
            card.set_phase("active", "正在切换账号")
        elif event_type == "account_phase" and card is not None:
            card.set_phase("active", "正在登录游戏")
        elif event_type == "task_started" and card is not None:
            task_name = event["task"]
            run_index = event.get("run_index", 1)
            run_count = event.get("run_count", 1)
            detail = "正在执行"
            if run_count > 1:
                detail += f" · {run_index}/{run_count}"
            card.task_views[task_name].set_status("active", detail)
            if task_name in {controller.BOUNTY_TASK, controller.MERCHANT_TASK}:
                card.task_views[task_name].set_highlight(False)
            card.set_phase("active", f"正在执行：{controller.TASK_LABELS[task_name]}")
        elif event_type == "task_completed" and card is not None:
            task_name = event["task"]
            detail = event.get("detail") or "本轮已完成"
            card.task_views[task_name].set_status("done", detail)
            if task_name == controller.BOUNTY_TASK:
                bounty_style = BOUNTY_HIGHLIGHT_STYLES.get(event.get("result"))
                card.task_views[task_name].set_highlight(
                    bounty_style is not None,
                    bounty_style or "default",
                )
            elif task_name == controller.MERCHANT_TASK:
                merchant_style = MERCHANT_HIGHLIGHT_STYLES.get(event.get("result"))
                card.task_views[task_name].set_highlight(
                    merchant_style is not None,
                    merchant_style or "default",
                )
            card.refresh_overall()
        elif event_type == "error":
            message = str(event.get("message", "未知错误"))
            if card is not None:
                task_name = event.get("task")
                if task_name in card.task_views:
                    card.task_views[task_name].set_status("error", message)
                    location = controller.TASK_LABELS[task_name]
                else:
                    location = {
                        "startup_recovery": "启动界面恢复",
                        "select_account": "切换账号",
                        "sign_in": "登录",
                        "load_modules": "加载任务模块",
                    }.get(event.get("phase"), "中控")
                card.set_phase("error", f"卡在：{location}")
            self._append_log_now("ERROR", message)
        elif event_type == "controller_stopped" and card is not None:
            card.set_phase("warning", "已安全停止")
        self._apply_task_visibility()
        self._refresh_task_summary()


def main(page: ft.Page) -> None:
    AssistantDashboard(page)


if __name__ == "__main__":
    ft.run(main)

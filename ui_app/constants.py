"""UI 共享常量、样式与仓库路径。"""

from __future__ import annotations

from pathlib import Path

import flet as ft

import main as controller


ROOT_DIR = Path(__file__).resolve().parents[1]
HELPER_DIR = ROOT_DIR
CONFIG_DIR = ROOT_DIR / "config"
SETTINGS_PATH = CONFIG_DIR / "ui_settings.json"
TOOLS_DIR = ROOT_DIR / "tasks"
TOOL_MODULE_PATHS = {
    "story_skip": TOOLS_DIR / "StorySkip" / "story_skip.py",
    "secret_battle": TOOLS_DIR / "SecretBattle" / "secret_battle.py",
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
    "error_screenshot_keep_count": 20,
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

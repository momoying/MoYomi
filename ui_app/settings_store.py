"""UI 设置持久化与 MuMu 实例发现。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from module.mumu import discover_running_mumu_instances as _discover_running_mumu_instances
from module.mumu import resolve_mumu_manager_path
from ui_app.constants import *


_LEGACY_SCHEDULE_KEYS = (
    "scheduled_run_enabled",
    "scheduled_run_time",
    "scheduled_run_mode",
    "scheduled_run_weekdays",
    "scheduled_run_last_triggered_at",
)


def resolve_mumu_adb_path(mumu_path: str | Path) -> Path | None:
    """在已选择的 MuMu 安装目录中查找配套 adb.exe。"""
    root = Path(mumu_path).expanduser()
    candidates = (
        root / "nx_main" / "adb.exe",
        root / "shell" / "adb.exe",
        root / "adb.exe",
    )
    return next((path for path in candidates if path.is_file()), None)


def save_ui_settings(settings: dict[str, Any], path: Path = SETTINGS_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_path, path)


def load_ui_settings(path: Path = SETTINGS_PATH) -> dict[str, Any]:
    settings = dict(DEFAULT_SETTINGS)
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return settings
    if isinstance(raw, dict):
        if (
            "error_screenshot_keep_count" not in raw
            and "timeout_screenshot_keep_count" in raw
        ):
            raw["error_screenshot_keep_count"] = raw[
                "timeout_screenshot_keep_count"
            ]
        settings.update(raw)
    for key in _LEGACY_SCHEDULE_KEYS:
        settings.pop(key, None)
    settings.pop("timeout_screenshot_keep_count", None)
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
        settings["market_sniper_refresh_count"] = max(
            0,
            int(settings.get("market_sniper_refresh_count", 0)),
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
        settings["error_screenshot_keep_count"] = min(
            500,
            max(0, int(settings["error_screenshot_keep_count"])),
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
    settings["baigui_preset_name"] = DEFAULT_SETTINGS["baigui_preset_name"]
    nickname = settings.get("baigui_nickname")
    settings["baigui_nickname"] = nickname.strip() if isinstance(nickname, str) else ""
    settings.pop("baigui_stop_mode", None)
    settings.pop("baigui_match_limit", None)
    if type(settings.get("baigui_return_home")) is not bool:
        settings["baigui_return_home"] = True
    if not isinstance(settings.get("monet_palette"), dict):
        settings["monet_palette"] = {}
    return settings


def discover_running_mumu_instances(
    manager_path: Path = MUMU_MANAGER_PATH,
) -> list[dict[str, str]]:
    return _discover_running_mumu_instances(manager_path) or []

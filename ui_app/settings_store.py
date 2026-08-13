"""UI 设置持久化与 MuMu 实例发现。"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from ui_app.constants import *


def resolve_mumu_manager_path(mumu_path: str | Path) -> Path:
    """由 MuMu 安装根目录定位实例管理程序。"""
    return Path(mumu_path) / "nx_main" / "MuMuManager.exe"


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
    if not isinstance(settings.get("monet_palette"), dict):
        settings["monet_palette"] = {}
    return settings


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

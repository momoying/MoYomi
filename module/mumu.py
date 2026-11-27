"""MuMuManager instance discovery shared by the UI and device backend."""

import json
import subprocess
from pathlib import Path


def resolve_mumu_manager_path(mumu_path: str | Path) -> Path:
    """兼容新版 nx_main 与 MuMu 12 旧版 shell 安装结构。"""
    root = Path(mumu_path).expanduser()
    candidates = (
        root / "nx_main" / "MuMuManager.exe",
        root / "shell" / "MuMuManager.exe",
        root / "MuMuManager.exe",
    )
    return next((path for path in candidates if path.is_file()), candidates[0])


def discover_running_mumu_instances(
    manager_path: Path,
) -> list[dict[str, str]] | None:
    """通过 MuMuManager 获取正在运行实例及其真实 ADB 地址。"""
    manager_path = Path(manager_path)
    if not manager_path.is_file():
        return None
    try:
        result = subprocess.run(
            [str(manager_path), "info", "-v", "all"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
        )
        if result.returncode != 0:
            return None
        output = result.stdout.strip()
        first_brace = output.find("{")
        last_brace = output.rfind("}")
        if first_brace < 0 or last_brace < first_brace:
            return None
        raw = json.loads(output[first_brace : last_brace + 1])
    except (OSError, subprocess.SubprocessError, ValueError):
        return None

    if not isinstance(raw, dict):
        return None
    instances: list[dict[str, str]] = []
    for item in raw.values():
        if not isinstance(item, dict) or not item.get("is_android_started"):
            continue
        host = str(item.get("adb_host_ip") or "").strip()
        port = item.get("adb_port")
        if not host or port in (None, ""):
            continue
        index = str(item.get("index", "")).strip()
        if not index.isdecimal():
            continue
        address = f"{host}:{port}"
        instances.append(
            {
                "index": index,
                "name": str(item.get("name") or f"MuMu 实例 {index}"),
                "adb_port": address,
            }
        )
    return sorted(instances, key=lambda item: int(item["index"]))

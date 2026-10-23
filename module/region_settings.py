"""登录与中控共用的区名配置。"""

from __future__ import annotations

import json
from pathlib import Path


SETTINGS_PATH = Path(__file__).resolve().parents[1] / "config" / "ui_settings.json"


def load_region_names(path: Path = SETTINGS_PATH) -> dict[str, str]:
    names = {"same": "", "cross": ""}
    try:
        settings = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return names
    if isinstance(settings, dict):
        for region in names:
            value = settings.get(f"{region}_region_name")
            if isinstance(value, str) and value.strip():
                names[region] = value.strip()
    return names

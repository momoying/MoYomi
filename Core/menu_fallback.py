"""庭院活动限定菜单的公共兜底点击。"""

from __future__ import annotations

import random
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Tuple

CORE_DIR = Path(__file__).resolve().parent
HELPER_DIR = CORE_DIR.parent
DAILY_DIR = HELPER_DIR / "Daily"
PROJECT_ROOT = HELPER_DIR
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Core import game_automation as utils

if TYPE_CHECKING:
    from Core.task_logging import TaskLogger


MAIN_TEMPLATE = DAILY_DIR / "CoopReward" / "explore.png"
MAIN_SEARCH_REGION = ((500, 80), (800, 280))
MAIN_THRESHOLD = 0.80

# 普通卷轴与活动限定小狐狸在 1280x720 下共有的可点击核心区域。
MENU_SAFE_CLICK_REGION = (1205, 645, 1245, 685)

Rect = Tuple[int, int, int, int]


def try_open_activity_menu_once(frame, logger: "TaskLogger") -> bool:
    """仅在确认处于庭院时点击一次活动菜单/卷轴共有区域。"""
    score, matched_rect = utils.crop_and_match(
        MAIN_SEARCH_REGION[0],
        MAIN_SEARCH_REGION[1],
        str(MAIN_TEMPLATE),
        frame=frame,
    )
    if score is None or matched_rect is None or score < MAIN_THRESHOLD:
        return False

    search_rect = (
        MAIN_SEARCH_REGION[0][0],
        MAIN_SEARCH_REGION[0][1],
        MAIN_SEARCH_REGION[1][0],
        MAIN_SEARCH_REGION[1][1],
    )
    logger.match(
        "菜单兜底",
        "explore",
        score,
        MAIN_THRESHOLD,
        MENU_SAFE_CLICK_REGION,
        search_region=search_rect,
    )

    left, top, right, bottom = MENU_SAFE_CLICK_REGION
    x = random.randint(left, right)
    y = random.randint(top, bottom)
    logger.click(
        "菜单兜底",
        "活动小狐狸/普通卷轴共有区域",
        MENU_SAFE_CLICK_REGION,
        (x, y),
    )
    utils.adb_click(x, y)
    return True

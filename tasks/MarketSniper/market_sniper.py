"""在当前寄售屋藏品页查找并购买第一件上架商品。"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from module import automation as utils
from module.base.device import TaskDevice
from module.logging import TaskLogger
from tasks.MarketSniper.assets import MarketSniperAssets


ASSETS = MarketSniperAssets
TEMPLATES = ASSETS.TEMPLATES
REGIONS = ASSETS.REGIONS
THRESHOLDS = ASSETS.MATCH_THRESHOLDS
LOGGER = TaskLogger("抢商品")
DEVICE = TaskDevice(utils, LOGGER)
print = LOGGER.legacy_print

SCREENSHOT_INTERVAL = 0.5
PAGE_WAIT_SECONDS = 15.0
DIALOG_WAIT_SECONDS = 12.0

Rect = Tuple[int, int, int, int]


def _stopped(stop_event) -> bool:
    return stop_event is not None and stop_event.is_set()


def _take_frame(stop_event=None):
    if _stopped(stop_event):
        return None
    frame = DEVICE.screenshot()
    if frame is None:
        time.sleep(SCREENSHOT_INTERVAL)
    return frame


def _match(frame, name: str):
    top_left, bottom_right = REGIONS[name]
    score, rect = DEVICE.match(
        top_left,
        bottom_right,
        TEMPLATES[name],
        frame=frame,
    )
    if score is None or rect is None or score < THRESHOLDS[name]:
        return score, None
    LOGGER.match(
        name,
        name,
        score,
        THRESHOLDS[name],
        rect,
        search_region=(top_left[0], top_left[1], bottom_right[0], bottom_right[1]),
    )
    return score, rect


def _click_random(region: Rect, label: str) -> None:
    DEVICE.click_rect(region, label=label, inset=5)


def _wait_or_stop(stop_event, seconds: float) -> bool:
    if stop_event is None:
        time.sleep(seconds)
        return False
    return stop_event.wait(seconds)


def _listing_state(frame: object) -> tuple[Optional[str], Optional[Rect], Optional[float]]:
    empty_score, empty_rect = _match(frame, "empty_listing")
    if empty_rect is not None:
        return "empty", empty_rect, empty_score

    row_score, row_rect = _match(frame, "listing_row_corner")
    if row_rect is not None:
        return "listed", row_rect, row_score
    return None, None, None


def _wait_for_listing(stop_event, timeout: float):
    """要求列表状态连续两帧一致，过滤刷新和页面转场动画。"""
    deadline = time.monotonic() + timeout
    previous_state = None
    consecutive = 0
    best_score = None
    while time.monotonic() < deadline and not _stopped(stop_event):
        frame = _take_frame(stop_event)
        if frame is None:
            continue
        state, rect, score = _listing_state(frame)
        if score is not None and (best_score is None or score > best_score):
            best_score = score
        if state is None:
            previous_state, consecutive = None, 0
        elif state == previous_state:
            consecutive += 1
        else:
            previous_state, consecutive = state, 1
        if state is not None and consecutive >= 2:
            label = "无商品" if state == "empty" else "有商品"
            print(f"已连续两帧确认{label}")
            return state, rect
        time.sleep(SCREENSHOT_INTERVAL)
    if not _stopped(stop_event):
        print(
            f"[ERROR] 等待寄售列表超时，最高匹配分数 "
            f"{_score_text(best_score)}"
        )
    return None, None


def _score_text(score: Optional[float]) -> str:
    return "无" if score is None else f"{score:.3f}"


def _wait_for_template(name: str, stop_event, timeout: float, *, visible: bool):
    """连续两帧确认模板出现或消失。"""
    deadline = time.monotonic() + timeout
    consecutive = 0
    best_score = None
    while time.monotonic() < deadline and not _stopped(stop_event):
        frame = _take_frame(stop_event)
        if frame is None:
            continue
        score, rect = _match(frame, name)
        if score is not None and (best_score is None or score > best_score):
            best_score = score
        present = rect is not None
        if present == visible:
            consecutive += 1
        else:
            consecutive = 0
        if consecutive >= 2:
            return rect, True
        time.sleep(SCREENSHOT_INTERVAL)
    if not _stopped(stop_event):
        expectation = "出现" if visible else "关闭"
        print(
            f"[ERROR] 购买弹窗未能确认{expectation}，最高匹配分数 "
            f"{_score_text(best_score)}"
        )
    return None, False


def _first_row_rect(corner_rect: Rect) -> Rect:
    """将行角锚点换算为第一行卡片区域，卡片位置可随列表移动。"""
    _, row_top, _, _ = corner_rect
    return (578, row_top + 2, 1077, row_top + 91)


def _buy_first_listing(row_corner: Rect, stop_event) -> bool:
    row_rect = _first_row_rect(row_corner)
    print("发现寄售商品，随机点击当前列表第一行")
    _click_random(row_rect, "第一行寄售商品")
    dialog_rect, opened = _wait_for_template(
        "quantity_minus", stop_event, DIALOG_WAIT_SECONDS, visible=True,
    )
    if not opened or dialog_rect is None:
        return False
    if _stopped(stop_event):
        return False

    print("购买弹窗已打开，只点击一次购买按钮")
    _click_random(ASSETS.PURCHASE_REGION, "购买商品")
    _, closed = _wait_for_template(
        "quantity_minus", stop_event, DIALOG_WAIT_SECONDS, visible=False,
    )
    if not closed:
        return False
    print("购买弹窗已关闭，抢购流程完成")
    return True


def run(refresh_count: int, stop_event=None) -> bool:
    """最多刷新指定次数；发现商品后只购买第一行的一件并结束。"""
    try:
        refresh_count = int(refresh_count)
    except (TypeError, ValueError):
        print("[ERROR] 刷新次数必须是正整数")
        return False
    if refresh_count <= 0:
        print("[ERROR] 刷新次数必须大于 0")
        return False

    utils.connect_to_mumu()
    print(f"开始抢商品，最多刷新 {refresh_count} 次")
    _click_random(ASSETS.COLLECTION_PREVIEW_REGION, "藏品预览")
    state, row_corner = _wait_for_listing(stop_event, PAGE_WAIT_SECONDS)
    if state is None:
        return False

    refreshes = 0
    while not _stopped(stop_event):
        if state == "listed":
            return _buy_first_listing(row_corner, stop_event)
        if refreshes >= refresh_count:
            print(f"已刷新 {refreshes} 次，仍无寄售商品，本次抢购结束")
            return True

        delay = random.uniform(5.0, 6.0)
        print(
            f"暂无寄售商品，{delay:.1f} 秒后进行第 "
            f"{refreshes + 1}/{refresh_count} 次刷新"
        )
        if _wait_or_stop(stop_event, delay):
            return False
        _click_random(ASSETS.REFRESH_REGION, "刷新寄售列表")
        refreshes += 1
        state, row_corner = _wait_for_listing(stop_event, PAGE_WAIT_SECONDS)
        if state is None:
            return False

    print("抢商品已停止")
    return False

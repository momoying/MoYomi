"""寄售屋周常：检查并购买每周寄售券。"""

from __future__ import annotations

import random
import sys
import time
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple


SCRIPT_DIR = Path(__file__).resolve().parent
WEEKLY_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = WEEKLY_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from module import automation as utils
from module.base.device import TaskDevice
from module.logging import TaskLogger
from module.menu import try_open_activity_menu_once


from tasks.ConsignmentHouse.assets import ConsignmentHouseAssets

ASSETS = ConsignmentHouseAssets
TEMPLATES = ASSETS.TEMPLATES
REGIONS = ASSETS.REGIONS
MATCH_THRESHOLDS = ASSETS.MATCH_THRESHOLDS
EXCHANGE_ACTIVE_MARGIN = ASSETS.EXCHANGE_ACTIVE_MARGIN

LOGGER = TaskLogger("寄售屋")
DEVICE = TaskDevice(utils, LOGGER)
print = LOGGER.legacy_print

SCREENSHOT_INTERVAL = 0.5
utils.config["screenshot_speed"] = SCREENSHOT_INTERVAL




# 亮灯模板对暗灯实测仍有约 0.93 的相关度，必须同时要求亮模板领先。
PAGE_CONFIRM_FRAMES = 2
TRANSITION_RETRY_INTERVAL_SECONDS = 2.5
MAX_TRANSITION_CLICKS = 4
MENU_WAIT_SECONDS = 15.0
ENTRY_WAIT_SECONDS = 15.0
PAGE_WAIT_SECONDS = 15.0
TICKET_DETECTION_SECONDS = 5.0
DIALOG_WAIT_SECONDS = 12.0
REWARD_WAIT_SECONDS = 20.0
RETURN_WAIT_SECONDS = 20.0

Rect = Tuple[int, int, int, int]


class ConsignmentHouseResult(str, Enum):
    ALREADY_PURCHASED = "already_purchased"
    PURCHASED = "purchased"
    ERROR = "error"


def _score_text(score: Optional[float]) -> str:
    return "无" if score is None else f"{score:.3f}"


def _take_frame():
    frame = DEVICE.screenshot()
    if frame is None:
        print("[WARN] 截图失败，等待下一帧")
        time.sleep(SCREENSHOT_INTERVAL)
    return frame


def _raw_match(frame, name: str) -> Tuple[Optional[float], Optional[Rect]]:
    top_left, bottom_right = REGIONS[name]
    return DEVICE.match(
        top_left,
        bottom_right,
        TEMPLATES[name],
        frame=frame,
    )


def _match(frame, name: str) -> Tuple[Optional[float], Optional[Rect]]:
    score, rect = _raw_match(frame, name)
    threshold = MATCH_THRESHOLDS[name]
    if score is None or rect is None or score < threshold:
        return score, None
    top_left, bottom_right = REGIONS[name]
    LOGGER.match(
        name,
        name,
        score,
        threshold,
        rect,
        search_region=(top_left[0], top_left[1], bottom_right[0], bottom_right[1]),
    )
    return score, rect


def _click_rect(rect: Rect, label: str) -> None:
    left, top, right, bottom = rect
    margin_x = max(1, (right - left) // 4)
    margin_y = max(1, (bottom - top) // 4)
    x = random.randint(left + margin_x, right - margin_x)
    y = random.randint(top + margin_y, bottom - margin_y)
    LOGGER.click(label, label, rect, (x, y))
    DEVICE.click(x, y)


def _wait_for_template(
    name: str,
    label: str,
    timeout: float,
) -> Tuple[Optional[object], Optional[Rect], Optional[float]]:
    deadline = time.monotonic() + timeout
    best_score: Optional[float] = None
    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        score, rect = _match(frame, name)
        if score is not None and (best_score is None or score > best_score):
            best_score = score
        if rect is not None:
            print(f"识别到{label}，匹配分数 {score:.3f}")
            return frame, rect, score
    print(
        f"[ERROR] 未识别到{label}，最高匹配分数 {_score_text(best_score)}，"
        f"要求 {MATCH_THRESHOLDS[name]:.2f}"
    )
    return None, None, best_score


def _click_and_wait_disappear(
    name: str,
    label: str,
    rect: Rect,
    timeout: float,
) -> bool:
    top_left, bottom_right = REGIONS[name]
    return DEVICE.click_until_disappears(
        top_left,
        bottom_right,
        TEMPLATES[name],
        rect,
        threshold=MATCH_THRESHOLDS[name],
        timeout=timeout,
        label=label,
        click_callback=lambda current_rect: _click_rect(current_rect, label),
        log_callback=lambda message: LOGGER.message(label, message),
    )


def _ensure_store_menu_expanded() -> bool:
    """确认庭院后寻找商店，不可见时使用卷轴与活动菜单兜底。"""
    deadline = time.monotonic() + MENU_WAIT_SECONDS
    best_main: Optional[float] = None
    best_store: Optional[float] = None
    best_scroll: Optional[float] = None
    fallback_clicked = False

    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        main_score, main_rect = _match(frame, "main")
        if main_score is not None and (best_main is None or main_score > best_main):
            best_main = main_score
        if main_rect is None:
            continue

        store_score, store_rect = _match(frame, "store_entry")
        if store_score is not None and (best_store is None or store_score > best_store):
            best_store = store_score
        if store_rect is not None:
            print(f"商店入口已经显示，匹配分数 {store_score:.3f}")
            return True

        scroll_score, scroll_rect = _match(frame, "menu_scroll")
        if scroll_score is not None and (best_scroll is None or scroll_score > best_scroll):
            best_scroll = scroll_score
        if scroll_rect is not None:
            remaining = max(0.1, deadline - time.monotonic())
            if not _click_and_wait_disappear(
                "menu_scroll",
                "展开功能栏卷轴",
                scroll_rect,
                remaining,
            ):
                return False
            continue

        if not fallback_clicked and try_open_activity_menu_once(frame, LOGGER):
            fallback_clicked = True
            print("未识别到普通卷轴，已点击活动菜单共有区域")
            time.sleep(SCREENSHOT_INTERVAL)

    print(
        "[ERROR] 未能显示商店入口，探索/商店/卷轴最高分 "
        f"{_score_text(best_main)}/{_score_text(best_store)}/"
        f"{_score_text(best_scroll)}"
    )
    return False


def _exchange_is_active(
    active_score: Optional[float],
    inactive_score: Optional[float],
) -> bool:
    return (
        active_score is not None
        and inactive_score is not None
        and active_score >= MATCH_THRESHOLDS["exchange_active"]
        and active_score - inactive_score >= EXCHANGE_ACTIVE_MARGIN
    )


def _wait_for_exchange_active(
    timeout: float,
    *,
    exchange_rect: Optional[Rect] = None,
) -> bool:
    """连续多帧确认兑换页；传入暗灯区域时会在未切页时有限补点。"""
    deadline = time.monotonic() + timeout
    best_active: Optional[float] = None
    best_inactive: Optional[float] = None
    consecutive_active = 0
    click_count = 0
    next_retry_at = time.monotonic()
    while time.monotonic() < deadline:
        now = time.monotonic()
        if (
            exchange_rect is not None
            and click_count < MAX_TRANSITION_CLICKS
            and now >= next_retry_at
        ):
            _click_rect(exchange_rect, "兑换灯笼")
            click_count += 1
            next_retry_at = now + TRANSITION_RETRY_INTERVAL_SECONDS

        frame = _take_frame()
        if frame is None:
            continue
        active_score, active_rect = _raw_match(frame, "exchange_active")
        inactive_score, inactive_rect = _raw_match(frame, "exchange_inactive")
        if active_score is not None and (
            best_active is None or active_score > best_active
        ):
            best_active = active_score
        if inactive_score is not None and (
            best_inactive is None or inactive_score > best_inactive
        ):
            best_inactive = inactive_score
        if _exchange_is_active(active_score, inactive_score) and active_rect is not None:
            consecutive_active += 1
        else:
            consecutive_active = 0
            # 使用最新识别到的暗灯区域补点，避免界面轻微位移后仍点旧坐标。
            if (
                inactive_rect is not None
                and inactive_score is not None
                and inactive_score >= MATCH_THRESHOLDS["exchange_inactive"]
            ):
                exchange_rect = inactive_rect

        if consecutive_active >= PAGE_CONFIRM_FRAMES:
            top_left, bottom_right = REGIONS["exchange_active"]
            LOGGER.match(
                "兑换页",
                "exchange_active",
                active_score,
                MATCH_THRESHOLDS["exchange_active"],
                active_rect,
                search_region=(
                    top_left[0], top_left[1], bottom_right[0], bottom_right[1]
                ),
            )
            print(
                "兑换灯笼已亮起，亮/暗模板分数 "
                f"{active_score:.3f}/{inactive_score:.3f}，"
                f"连续确认 {consecutive_active} 帧"
            )
            return True
        time.sleep(SCREENSHOT_INTERVAL)

    print(
        "[ERROR] 未能确认兑换灯笼亮起，亮/暗模板最高分 "
        f"{_score_text(best_active)}/{_score_text(best_inactive)}，"
        f"已点击 {click_count} 次"
    )
    return False


def _find_ticket(timeout: float) -> Tuple[bool, Optional[Rect]]:
    """返回（检测是否可靠完成，寄售券区域）；可靠且无区域才代表已购买。"""
    deadline = time.monotonic() + timeout
    best_score: Optional[float] = None
    valid_exchange_frames = 0
    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        active_score, _ = _raw_match(frame, "exchange_active")
        inactive_score, _ = _raw_match(frame, "exchange_inactive")
        if not _exchange_is_active(active_score, inactive_score):
            print("[WARN] 寄售券检测期间未能持续确认兑换页，等待下一帧")
            time.sleep(SCREENSHOT_INTERVAL)
            continue
        valid_exchange_frames += 1
        score, rect = _match(frame, "consignment_ticket")
        if score is not None and (best_score is None or score > best_score):
            best_score = score
        if rect is not None:
            print(f"识别到未购买的 100 寄售券，匹配分数 {score:.3f}")
            return True, rect
        time.sleep(SCREENSHOT_INTERVAL)
    if valid_exchange_frames == 0:
        print("[ERROR] 检测期内没有获得可确认兑换页的有效截图")
        return False, None
    print(
        "连续 5 秒未识别到寄售券，按本周已经购买处理；"
        f"有效帧 {valid_exchange_frames}，最高匹配分数 {_score_text(best_score)}"
    )
    return True, None


def _open_purchase_dialog(ticket_rect: Rect) -> bool:
    """有限补点寄售券，并以最大数量按钮连续出现确认弹窗已打开。"""
    deadline = time.monotonic() + DIALOG_WAIT_SECONDS
    next_retry_at = time.monotonic()
    click_count = 0
    consecutive_dialog = 0
    best_max: Optional[float] = None

    while time.monotonic() < deadline:
        now = time.monotonic()
        if click_count < MAX_TRANSITION_CLICKS and now >= next_retry_at:
            _click_rect(ticket_rect, "100 寄售券")
            click_count += 1
            next_retry_at = now + TRANSITION_RETRY_INTERVAL_SECONDS

        frame = _take_frame()
        if frame is None:
            continue
        max_score, max_rect = _match(frame, "max_quantity")
        if max_score is not None and (best_max is None or max_score > best_max):
            best_max = max_score

        if max_rect is not None:
            consecutive_dialog += 1
            # 已经看到弹窗后禁止补点商品，等待下一帧完成连续确认。
            next_retry_at = deadline
        else:
            consecutive_dialog = 0

        if consecutive_dialog >= PAGE_CONFIRM_FRAMES:
            print(
                "寄售券购买弹窗已连续确认 "
                f"{consecutive_dialog} 帧，最大数量按钮分数 {max_score:.3f}"
            )
            return True
        time.sleep(SCREENSHOT_INTERVAL)

    print(
        "[ERROR] 未能确认寄售券购买弹窗，最大数量按钮最高分 "
        f"{_score_text(best_max)}，"
        f"已点击寄售券 {click_count} 次"
    )
    return False


def _click_reward_blank() -> None:
    """随机点击奖励面板左右空白区，避开底部商店栏和右侧兑换标签。"""
    safe_regions = (
        (40, 250, 220, 560),
        (1060, 170, 1160, 560),
    )
    rect = random.choice(safe_regions)
    _click_rect(rect, "奖励界面空白处")


def _dismiss_reward() -> bool:
    _, reward_rect, _ = _wait_for_template(
        "reward", "获得奖励", REWARD_WAIT_SECONDS
    )
    if reward_rect is None:
        return False
    top_left, bottom_right = REGIONS["reward"]
    return DEVICE.click_until_disappears(
        top_left,
        bottom_right,
        TEMPLATES["reward"],
        reward_rect,
        threshold=MATCH_THRESHOLDS["reward"],
        timeout=REWARD_WAIT_SECONDS,
        label="关闭获得奖励",
        click_callback=lambda _current_rect: _click_reward_blank(),
        log_callback=lambda message: LOGGER.message("获得奖励", message),
    )


def _return_to_courtyard() -> bool:
    _, back_rect, _ = _wait_for_template(
        "courtyard_back", "返回庭院标志", RETURN_WAIT_SECONDS
    )
    if back_rect is None or not _click_and_wait_disappear(
        "courtyard_back", "返回庭院", back_rect, RETURN_WAIT_SECONDS
    ):
        return False
    _, main_rect, _ = _wait_for_template(
        "main", "庭院探索灯笼", RETURN_WAIT_SECONDS
    )
    return main_rect is not None


def _purchase_ticket() -> bool:
    _, max_rect, _ = _wait_for_template(
        "max_quantity", "最大数量按钮", DIALOG_WAIT_SECONDS
    )
    if max_rect is None:
        return False
    # 初始数量为 1，此时价格显示 10，不能用价格 100 的购买模板确认弹窗。
    # 先点击最大数量，再等待价格变为 100；点击偶尔未生效时有限补点最大按钮。
    deadline = time.monotonic() + DIALOG_WAIT_SECONDS
    next_retry_at = time.monotonic()
    click_count = 0
    purchase_rect: Optional[Rect] = None
    best_purchase: Optional[float] = None
    while time.monotonic() < deadline:
        now = time.monotonic()
        if click_count < MAX_TRANSITION_CLICKS and now >= next_retry_at:
            _click_rect(max_rect, "最大数量按钮")
            click_count += 1
            next_retry_at = now + TRANSITION_RETRY_INTERVAL_SECONDS

        frame = _take_frame()
        if frame is None:
            continue
        purchase_score, current_purchase_rect = _match(frame, "purchase")
        if purchase_score is not None and (
            best_purchase is None or purchase_score > best_purchase
        ):
            best_purchase = purchase_score
        if current_purchase_rect is not None:
            purchase_rect = current_purchase_rect
            break
        # 弹窗仍在时刷新最大按钮位置，兼容轻微的画面缩放或偏移。
        _, current_max_rect = _match(frame, "max_quantity")
        if current_max_rect is not None:
            max_rect = current_max_rect
        time.sleep(SCREENSHOT_INTERVAL)

    if purchase_rect is None:
        print(
            "[ERROR] 点击最大数量后未识别到价格 100 的购买按钮，"
            f"最高分 {_score_text(best_purchase)}，已点击最大按钮 {click_count} 次"
        )
        return False
    if not _click_and_wait_disappear(
        "purchase",
        "购买按钮",
        purchase_rect,
        DIALOG_WAIT_SECONDS,
    ):
        return False
    return _dismiss_reward()


def check_consignment_house() -> ConsignmentHouseResult:
    """进入商店和兑换页 → 检查寄售券 → 按需购买 → 确认退出。"""
    utils.connect_to_mumu()
    print("开始寄售屋周常检测")

    # 1. 展开商店入口并进入寄售屋。
    if not _ensure_store_menu_expanded():
        return ConsignmentHouseResult.ERROR
    _, store_rect, _ = _wait_for_template(
        "store_entry", "商店入口", ENTRY_WAIT_SECONDS
    )
    if store_rect is None or not _click_and_wait_disappear(
        "store_entry", "商店入口", store_rect, ENTRY_WAIT_SECONDS
    ):
        return ConsignmentHouseResult.ERROR

    _, consignment_rect, _ = _wait_for_template(
        "consignment_entry", "寄售屋入口", PAGE_WAIT_SECONDS
    )
    if consignment_rect is None:
        return ConsignmentHouseResult.ERROR
    # 寄售屋图标进入后仍保留在底栏，不能等待模板消失。
    _click_rect(consignment_rect, "寄售屋入口")

    # 2. 确认兑换灯笼激活后才检查商品，避免把页面未加载当成已购买。
    _, exchange_rect, _ = _wait_for_template(
        "exchange_inactive", "未选中的兑换灯笼", PAGE_WAIT_SECONDS
    )
    if exchange_rect is None:
        return ConsignmentHouseResult.ERROR
    if not _wait_for_exchange_active(
        PAGE_WAIT_SECONDS,
        exchange_rect=exchange_rect,
    ):
        return ConsignmentHouseResult.ERROR

    # 3. 区分检测失败和商品已售罄；已购买也必须返回庭院。
    detection_ok, ticket_rect = _find_ticket(TICKET_DETECTION_SECONDS)
    if not detection_ok:
        return ConsignmentHouseResult.ERROR
    if ticket_rect is None:
        if not _return_to_courtyard():
            return ConsignmentHouseResult.ERROR
        print("本周寄售券已经购买，已返回庭院")
        return ConsignmentHouseResult.ALREADY_PURCHASED

    # 4. 打开购买弹窗，选择最大数量并领取奖励。
    if not _open_purchase_dialog(ticket_rect):
        return ConsignmentHouseResult.ERROR
    if not _purchase_ticket():
        return ConsignmentHouseResult.ERROR
    # 5. 复核兑换页，再返回庭院后报告购买成功。
    # 奖励消失后回到兑换页，此时商品位置会变化；无需再次定位寄售券。
    if not _wait_for_exchange_active(PAGE_WAIT_SECONDS):
        return ConsignmentHouseResult.ERROR
    if not _return_to_courtyard():
        return ConsignmentHouseResult.ERROR
    print("寄售券购买成功，已返回庭院")
    return ConsignmentHouseResult.PURCHASED


def run() -> bool:
    return check_consignment_house() is not ConsignmentHouseResult.ERROR


if __name__ == "__main__":
    try:
        result = check_consignment_house()
    except KeyboardInterrupt:
        print("任务已由用户中止")
        result = ConsignmentHouseResult.ERROR
    raise SystemExit(0 if result is not ConsignmentHouseResult.ERROR else 1)

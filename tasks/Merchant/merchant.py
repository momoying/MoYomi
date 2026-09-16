"""阴阳师奸商检测：记录蓝票价格；仅无蓝票时刷新，重点寻找最低价 50。"""

from __future__ import annotations

import random
import sys
import time
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
DAILY_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = DAILY_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from module import automation as utils
from module.base.device import TaskDevice
from module.menu import try_open_activity_menu_once
from module.logging import TaskLogger


from tasks.Merchant.assets import MerchantAssets

ASSETS = MerchantAssets
TEMPLATES = ASSETS.TEMPLATES
REGIONS = ASSETS.REGIONS
PRICE_TEMPLATES = ASSETS.PRICE_TEMPLATES
MATCH_THRESHOLDS = ASSETS.MATCH_THRESHOLDS
BLUE_TICKET_TEMPLATE_THRESHOLDS = ASSETS.BLUE_TICKET_TEMPLATE_THRESHOLDS
PRICE_SEARCH_OFFSET = ASSETS.PRICE_SEARCH_OFFSET
PRICE_DIGIT_LEFT = ASSETS.PRICE_DIGIT_LEFT
PRICE_MATCH_THRESHOLD = ASSETS.PRICE_MATCH_THRESHOLD
PRICE_WIN_MARGIN = ASSETS.PRICE_WIN_MARGIN
POPULAR_FALLBACK_THRESHOLD = ASSETS.POPULAR_FALLBACK_THRESHOLD
REFRESH_RED_VALUE_THRESHOLD = ASSETS.REFRESH_RED_VALUE_THRESHOLD
REFRESH_RED_MIN_PIXELS = ASSETS.REFRESH_RED_MIN_PIXELS
_TEMPLATE_CACHE = ASSETS._TEMPLATE_CACHE

LOGGER = TaskLogger("奸商检测")
DEVICE = TaskDevice(utils, LOGGER)
print = LOGGER.legacy_print


SCREENSHOT_INTERVAL = 0.5
utils.config["screenshot_speed"] = SCREENSHOT_INTERVAL






# 50/60/80/90 模板左侧带有价格共有的勾玉图标，70 模板已经只保留数字。
# 分类时统一只比较数字，避免公共图标把不同价格的相关系数拉得过近。
# 刷新按钮可用时箭头是亮红色，使用后整个按钮会明显变暗。
# 两张实测样本的红色像素亮度中位数约为 184/111，取中间值留出余量。

MENU_WAIT_SECONDS = 15.0
ENTRY_WAIT_SECONDS = 15.0
PAGE_WAIT_SECONDS = 15.0
DETECTION_WAIT_SECONDS = 3.0
CONFIRM_WAIT_SECONDS = 12.0
RETURN_WAIT_SECONDS = 20.0

Rect = Tuple[int, int, int, int]


class MerchantResult(str, Enum):
    BLUE_TICKET_50 = "blue_ticket_50"
    BLUE_TICKET_60 = "blue_ticket_60"
    BLUE_TICKET_70 = "blue_ticket_70"
    BLUE_TICKET_80 = "blue_ticket_80"
    BLUE_TICKET_90 = "blue_ticket_90"
    NO_BLUE_TICKET = "no_blue_ticket"
    ERROR = "error"


class RefreshState(str, Enum):
    AVAILABLE = "available"
    USED = "used"
    REFRESHED = "refreshed"
    ERROR = "error"




def _score_text(score: Optional[float]) -> str:
    return "无" if score is None else f"{score:.3f}"


def _match(frame, name: str) -> Tuple[Optional[float], Optional[Rect]]:
    top_left, bottom_right = REGIONS[name]
    threshold = MATCH_THRESHOLDS[name]
    score, rect = DEVICE.match(
        top_left,
        bottom_right,
        TEMPLATES[name],
        frame=frame,
    )
    if score is None or rect is None or score < threshold:
        return score, None
    LOGGER.match(
        name,
        name,
        score,
        threshold,
        rect,
        search_region=(top_left[0], top_left[1], bottom_right[0], bottom_right[1]),
    )
    return score, rect


def _match_refresh_state(
    frame,
) -> Tuple[RefreshState, Optional[Rect], Optional[float], Optional[float]]:
    """先用模板定位按钮，再按红色箭头亮度区分可刷新/已刷新。"""
    name = "refresh"
    top_left, bottom_right = REGIONS[name]
    score, rect = DEVICE.match(
        top_left,
        bottom_right,
        TEMPLATES[name],
        frame=frame,
    )
    if score is None or rect is None or score < MATCH_THRESHOLDS[name]:
        return RefreshState.ERROR, None, score, None

    LOGGER.match(
        "刷新状态",
        name,
        score,
        MATCH_THRESHOLDS[name],
        rect,
        search_region=(top_left[0], top_left[1], bottom_right[0], bottom_right[1]),
    )

    left, top, right, bottom = rect
    button = frame[top:bottom, left:right]
    if button.size == 0:
        return RefreshState.ERROR, None, score, None
    hsv = cv2.cvtColor(button, cv2.COLOR_BGR2HSV)
    hue, saturation, value = cv2.split(hsv)
    red_mask = (
        ((hue <= 12) | (hue >= 170))
        & (saturation >= 45)
        & (value >= 60)
    )
    if int(np.count_nonzero(red_mask)) < REFRESH_RED_MIN_PIXELS:
        print("[WARN] 刷新按钮内红色像素不足，无法判断按钮状态")
        return RefreshState.ERROR, None, score, None

    red_value = float(np.median(value[red_mask]))
    state = (
        RefreshState.AVAILABLE
        if red_value >= REFRESH_RED_VALUE_THRESHOLD
        else RefreshState.USED
    )
    return state, rect, score, red_value


def _wait_for_refresh_state(
    label: str,
    timeout: float,
) -> Tuple[RefreshState, Optional[Rect]]:
    deadline = time.monotonic() + timeout
    best_score: Optional[float] = None
    last_red_value: Optional[float] = None
    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        state, rect, score, red_value = _match_refresh_state(frame)
        if score is not None and (best_score is None or score > best_score):
            best_score = score
        if red_value is not None:
            last_red_value = red_value
        if state is not RefreshState.ERROR:
            state_text = "可刷新" if state is RefreshState.AVAILABLE else "今日已刷新"
            print(
                f"识别到{label}：{state_text}，模板分数 {_score_text(score)}，"
                f"红色亮度 {red_value:.1f}/{REFRESH_RED_VALUE_THRESHOLD:.1f}"
            )
            return state, rect

    print(
        f"[ERROR] 未识别到{label}，模板最高分 {_score_text(best_score)}，"
        f"最近红色亮度 {_score_text(last_red_value)}"
    )
    return RefreshState.ERROR, None


def _load_cv_template(path: str):
    template = _TEMPLATE_CACHE.get(path)
    if template is None:
        template = cv2.imread(path)
        if template is None:
            raise FileNotFoundError(f"识图模板不存在或无法读取: {path}")
        _TEMPLATE_CACHE[path] = template
    return template


def _rect_iou(first: Rect, second: Rect) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0, right - left) * max(0, bottom - top)
    if intersection == 0:
        return 0.0
    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    return intersection / float(first_area + second_area - intersection)


def _find_blue_ticket_rects(frame) -> list[Tuple[Rect, float]]:
    """用普通/特惠两种图标模板找出当前货架上的全部蓝票。"""
    top_left, bottom_right = REGIONS["blue_ticket"]
    crop = frame[
        top_left[1] : bottom_right[1],
        top_left[0] : bottom_right[0],
    ]
    candidates: list[Tuple[Rect, float, str]] = []

    for name, threshold in BLUE_TICKET_TEMPLATE_THRESHOLDS.items():
        template = _load_cv_template(TEMPLATES[name])
        template_height, template_width = template.shape[:2]
        if crop.shape[0] < template_height or crop.shape[1] < template_width:
            continue
        scores = cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED)
        local_maxima = scores == cv2.dilate(scores, np.ones((3, 3), np.uint8))
        rows, columns = np.where((scores >= threshold) & local_maxima)
        for row, column in zip(rows.tolist(), columns.tolist()):
            rect = (
                top_left[0] + column,
                top_left[1] + row,
                top_left[0] + column + template_width,
                top_left[1] + row + template_height,
            )
            candidates.append((rect, float(scores[row, column]), name))

    accepted: list[Tuple[Rect, float]] = []
    for rect, score, name in sorted(candidates, key=lambda item: item[1], reverse=True):
        if any(_rect_iou(rect, existing_rect) >= 0.35 for existing_rect, _ in accepted):
            continue
        accepted.append((rect, score))
        LOGGER.match(
            "blue_ticket",
            name,
            score,
            BLUE_TICKET_TEMPLATE_THRESHOLDS[name],
            rect,
            search_region=(
                top_left[0],
                top_left[1],
                bottom_right[0],
                bottom_right[1],
            ),
        )
    return accepted


def _classify_blue_ticket_price(frame, ticket_rect: Rect) -> Tuple[Optional[str], dict[str, float]]:
    """只在蓝票图标下方的小区域比较 50/60/70/80/90 五种价格。"""
    offset_left, offset_top, offset_right, offset_bottom = PRICE_SEARCH_OFFSET
    search_left = max(0, ticket_rect[0] + offset_left)
    search_top = max(0, ticket_rect[1] + offset_top)
    search_right = min(frame.shape[1], ticket_rect[0] + offset_right)
    search_bottom = min(frame.shape[0], ticket_rect[1] + offset_bottom)
    price_region = frame[search_top:search_bottom, search_left:search_right]

    scores: dict[str, float] = {}
    for price, path in PRICE_TEMPLATES.items():
        full_template = _load_cv_template(path)
        template = full_template[:, PRICE_DIGIT_LEFT[price]:]
        if (
            price_region.shape[0] < template.shape[0]
            or price_region.shape[1] < template.shape[1]
        ):
            scores[price] = -1.0
            continue
        match_scores = cv2.matchTemplate(
            price_region,
            template,
            cv2.TM_CCOEFF_NORMED,
        )
        scores[price] = float(cv2.minMaxLoc(match_scores)[1])

    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_price, best_score = ordered[0]
    runner_up_score = ordered[1][1]
    score_text = "/".join(f"{price}={score:.3f}" for price, score in sorted(scores.items()))
    print(f"蓝票价格分类：{score_text}")
    if (
        best_score < PRICE_MATCH_THRESHOLD
        or best_score - runner_up_score < PRICE_WIN_MARGIN
    ):
        print(
            "[WARN] 蓝票价格分类置信度不足，"
            f"最高分 {best_score:.3f}，领先 {best_score - runner_up_score:.3f}"
        )
        return None, scores
    return best_price, scores


def _take_frame():
    frame = DEVICE.screenshot()
    if frame is None:
        print("[WARN] 截图失败，等待下一帧")
        time.sleep(SCREENSHOT_INTERVAL)
    return frame


def _click_rect(rect: Rect, label: str) -> None:
    left, top, right, bottom = rect
    margin_x = max(1, (right - left) // 4)
    margin_y = max(1, (bottom - top) // 4)
    x = random.randint(left + margin_x, right - margin_x)
    y = random.randint(top + margin_y, bottom - margin_y)
    LOGGER.click(label, label, rect, (x, y))
    DEVICE.click(x, y)


def _click_and_confirm(name: str, label: str, rect: Rect, timeout: float) -> bool:
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


def _wait_for_template(
    name: str,
    label: str,
    timeout: float,
) -> Tuple[Optional[object], Optional[Rect], Optional[float]]:
    deadline = time.monotonic() + timeout
    best_score: Optional[float] = None
    last_frame = None
    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame
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


def _wait_and_click(name: str, label: str, timeout: float) -> bool:
    _, rect, _ = _wait_for_template(name, label, timeout)
    if rect is None:
        return False
    return _click_and_confirm(name, label, rect, timeout)


def _ensure_store_menu_expanded() -> bool:
    """确认庭院后寻找商店；不可见时依次尝试卷轴和活动菜单兜底。"""
    deadline = time.monotonic() + MENU_WAIT_SECONDS
    last_frame = None
    best_main: Optional[float] = None
    best_store: Optional[float] = None
    best_scroll: Optional[float] = None
    fallback_clicked = False

    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame

        main_score, main_rect = _match(frame, "main")
        if main_score is not None and (best_main is None or main_score > best_main):
            best_main = main_score
        if main_rect is None:
            continue

        store_score, store_rect = _match(frame, "store_entry")
        if store_score is not None and (
            best_store is None or store_score > best_store
        ):
            best_store = store_score
        if store_rect is not None:
            print(f"商店入口已经显示，匹配分数 {store_score:.3f}")
            return True

        scroll_score, scroll_rect = _match(frame, "menu_scroll")
        if scroll_score is not None and (
            best_scroll is None or scroll_score > best_scroll
        ):
            best_scroll = scroll_score
        if scroll_rect is not None:
            print(f"识别到右下角卷轴，匹配分数 {scroll_score:.3f}")
            remaining = max(0.1, deadline - time.monotonic())
            if not _click_and_confirm(
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


def _wait_for_shop_landing() -> Tuple[str, Optional[Rect]]:
    deadline = time.monotonic() + PAGE_WAIT_SECONDS
    best_popular: Optional[float] = None
    best_merchant: Optional[float] = None
    best_shop_back: Optional[float] = None

    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue

        merchant_score, merchant_rect = _match(frame, "merchant_entry")
        if merchant_score is not None and (
            best_merchant is None or merchant_score > best_merchant
        ):
            best_merchant = merchant_score
        if merchant_rect is not None:
            print(f"已进入商店街，识别到神秘商店，匹配分数 {merchant_score:.3f}")
            return "merchant", merchant_rect

        shop_back_score, shop_back_rect = _match(frame, "shop_back")
        if shop_back_score is not None and (
            best_shop_back is None or shop_back_score > best_shop_back
        ):
            best_shop_back = shop_back_score

        popular_score, popular_rect = _match(frame, "popular_marker")
        if popular_score is not None and (
            best_popular is None or popular_score > best_popular
        ):
            best_popular = popular_score
        if popular_rect is not None:
            print(
                f"进入了热门推荐页，匹配分数 {popular_score:.3f}，"
                "将点击左上角退出键"
            )
            return "popular", shop_back_rect

        # 标题发生轻微 UI 变化时，必须同时看到左上角退出键
        # 才允许以较低的标题分数进入热门推荐兜底分支。
        if (
            popular_score is not None
            and popular_score >= POPULAR_FALLBACK_THRESHOLD
            and shop_back_rect is not None
        ):
            print(
                "[WARN] 热门推荐标题未达标准阈值，但与左上角"
                f"退出键组合确认，分数 {popular_score:.3f}/"
                f"{shop_back_score:.3f}"
            )
            return "popular", shop_back_rect

    print(
        "[ERROR] 点击商店后未识别落点，热门推荐/"
        "左上退出/神秘商店最高分 "
        f"{_score_text(best_popular)}/{_score_text(best_shop_back)}/"
        f"{_score_text(best_merchant)}"
    )
    return "error", None


def _open_merchant_page() -> MerchantResult:
    landing, landing_rect = _wait_for_shop_landing()
    merchant_rect = landing_rect if landing == "merchant" else None
    if landing == "popular":
        back_rect = landing_rect
        if back_rect is None:
            _, back_rect, _ = _wait_for_template(
                "shop_back",
                "热门推荐左上角退出键",
                PAGE_WAIT_SECONDS,
            )
        if back_rect is None:
            return MerchantResult.ERROR
        # 商店街也存在同一个左上返回键，因此只点一次，
        # 不能等待该模板消失，否则会继续退回庭院。
        _click_rect(back_rect, "退出热门推荐")
        time.sleep(1.0)
        _, merchant_rect, _ = _wait_for_template(
            "merchant_entry",
            "返回商店街后的神秘商店入口",
            PAGE_WAIT_SECONDS,
        )
        if merchant_rect is None:
            return MerchantResult.ERROR
    elif landing == "error":
        return MerchantResult.ERROR

    if merchant_rect is None:
        return MerchantResult.ERROR
    if not _click_and_confirm(
        "merchant_entry",
        "神秘商店入口",
        merchant_rect,
        PAGE_WAIT_SECONDS,
    ):
        return MerchantResult.ERROR
    refresh_state, _ = _wait_for_refresh_state(
        "神秘商店刷新状态",
        PAGE_WAIT_SECONDS,
    )
    if refresh_state is RefreshState.ERROR:
        return MerchantResult.ERROR
    return MerchantResult.NO_BLUE_TICKET


def _detect_blue_ticket_price(
    timeout: float = DETECTION_WAIT_SECONDS,
) -> Tuple[bool, Optional[str]]:
    """返回（是否看见蓝票，当前页面最低蓝票价格）。"""
    deadline = time.monotonic() + timeout
    saw_blue_ticket = False
    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        tickets = _find_blue_ticket_rects(frame)
        saw_blue_ticket = saw_blue_ticket or bool(tickets)
        detected_prices: list[str] = []
        for ticket_rect, ticket_score in tickets:
            price, _ = _classify_blue_ticket_price(frame, ticket_rect)
            if price == "50":
                print(
                    "检测到最低价 50 蓝票，"
                    f"蓝票图标匹配分数 {ticket_score:.3f}，停止继续刷新"
                )
                return True, "50"
            if price is not None:
                detected_prices.append(price)
        if detected_prices:
            best_price = min(detected_prices, key=int)
            print(f"检测到 {best_price} 蓝票，为防止蓝票被刷新，保留当前商店")
            return True, best_price

    if saw_blue_ticket:
        print("[ERROR] 看见蓝票图标，但价格分类置信度不足；为保护蓝票不会刷新")
        return True, None
    print("当前货架没有识别到蓝票")
    return False, None


def _refresh_merchant_shop() -> RefreshState:
    refresh_state, refresh_rect = _wait_for_refresh_state(
        "神秘商店刷新状态",
        PAGE_WAIT_SECONDS,
    )
    if refresh_state is RefreshState.ERROR or refresh_rect is None:
        return RefreshState.ERROR
    if refresh_state is RefreshState.USED:
        print("神秘商店今天已经刷新过，本账号不再刷新")
        return RefreshState.USED

    _click_rect(refresh_rect, "刷新神秘商店")

    _, confirm_rect, _ = _wait_for_template(
        "confirm",
        "刷新确认键",
        CONFIRM_WAIT_SECONDS,
    )
    if confirm_rect is None:
        return RefreshState.ERROR
    if not _click_and_confirm(
        "confirm",
        "刷新确认键",
        confirm_rect,
        CONFIRM_WAIT_SECONDS,
    ):
        return RefreshState.ERROR

    time.sleep(1.0)
    final_state, _ = _wait_for_refresh_state(
        "刷新后的神秘商店页面",
        PAGE_WAIT_SECONDS,
    )
    if final_state is not RefreshState.USED:
        print("[ERROR] 刷新确认后未识别到今日已刷新标志")
        return RefreshState.ERROR
    return RefreshState.REFRESHED


def _return_to_courtyard() -> bool:
    if not _wait_and_click(
        "courtyard_back",
        "返回庭院",
        RETURN_WAIT_SECONDS,
    ):
        return False
    _, main_rect, _ = _wait_for_template(
        "main",
        "庭院探索灯笼",
        RETURN_WAIT_SECONDS,
    )
    return main_rect is not None


def check_merchant() -> MerchantResult:
    """进入神秘商店 → 检测蓝票价格 → 无蓝票时尝试刷新 → 退出并返回结果。"""
    utils.connect_to_mumu()
    print("开始奸商检测")

    # 1. 展开商店入口并确认进入神秘商店页。
    if not _ensure_store_menu_expanded():
        return MerchantResult.ERROR
    if not _wait_and_click("store_entry", "商店入口", ENTRY_WAIT_SECONDS):
        return MerchantResult.ERROR

    page_result = _open_merchant_page()
    if page_result is MerchantResult.ERROR:
        return page_result

    # 2. 先检测现有商品；有蓝票但价格不明属于识别失败。
    saw_blue_ticket, blue_ticket_price = _detect_blue_ticket_price()
    if saw_blue_ticket and blue_ticket_price is None:  # 有蓝票，但价格分类失败
        return MerchantResult.ERROR
    # 3. 仅没有蓝票时尝试刷新；真正刷新成功后才重新识别。
    if not saw_blue_ticket:
        refresh_state = _refresh_merchant_shop()
        if refresh_state is RefreshState.ERROR:
            return MerchantResult.ERROR
        if refresh_state is RefreshState.REFRESHED:
            saw_blue_ticket, blue_ticket_price = _detect_blue_ticket_price()
            if saw_blue_ticket and blue_ticket_price is None:
                return MerchantResult.ERROR

    # 4. 返回庭院后输出价格结果，避免页面残留影响下一任务。
    if not _return_to_courtyard():
        return MerchantResult.ERROR
    if blue_ticket_price == "50":
        return MerchantResult.BLUE_TICKET_50
    if blue_ticket_price == "60":
        return MerchantResult.BLUE_TICKET_60
    if blue_ticket_price == "70":
        return MerchantResult.BLUE_TICKET_70
    if blue_ticket_price == "80":
        return MerchantResult.BLUE_TICKET_80
    if blue_ticket_price == "90":
        return MerchantResult.BLUE_TICKET_90
    return MerchantResult.NO_BLUE_TICKET


def run() -> bool:
    return check_merchant() is not MerchantResult.ERROR


if __name__ == "__main__":
    try:
        success = run()
    except KeyboardInterrupt:
        print("任务已由用户中止")
        success = False
    raise SystemExit(0 if success else 1)

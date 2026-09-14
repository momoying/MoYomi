
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
from module.menu import try_open_activity_menu_once
from module.logging import TaskLogger


from tasks.Like.assets import LikeAssets

ASSETS = LikeAssets
TEMPLATES = ASSETS.TEMPLATES
REGIONS = ASSETS.REGIONS
MATCH_THRESHOLD = ASSETS.MATCH_THRESHOLD
FRIEND_STATE_THRESHOLD = ASSETS.FRIEND_STATE_THRESHOLD
FRIEND_HEADER_CLICK_REGION = ASSETS.FRIEND_HEADER_CLICK_REGION
CROSS_REGION_HEADER_CLICK_REGION = ASSETS.CROSS_REGION_HEADER_CLICK_REGION
CROSS_REGION_FRIEND_CLICK_REGIONS = ASSETS.CROSS_REGION_FRIEND_CLICK_REGIONS

LOGGER = TaskLogger("好友点赞")
DEVICE = TaskDevice(utils, LOGGER)
print = LOGGER.legacy_print


SCREENSHOT_INTERVAL = 0.5
utils.config["screenshot_speed"] = SCREENSHOT_INTERVAL




MAIN_WAIT_SECONDS = 20.0
MENU_WAIT_SECONDS = 12.0
FRIEND_PAGE_WAIT_SECONDS = 12.0
SWITCH_WAIT_SECONDS = 8.0
LIKE_WAIT_SECONDS = 20.0
LIKED_WAIT_SECONDS = 10.0
BACK_WAIT_SECONDS = 10.0

Rect = Tuple[int, int, int, int]



def _threshold(name: str) -> float:
    if name in {"friend_collapsed", "friend_expanded"}:
        return FRIEND_STATE_THRESHOLD
    return MATCH_THRESHOLD


def _match(frame, name: str) -> Tuple[Optional[float], Optional[Rect]]:
    top_left, bottom_right = REGIONS[name]
    threshold = _threshold(name)
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


def _score_text(score: Optional[float]) -> str:
    return "无" if score is None else f"{score:.3f}"


def _click_rect(rect: Rect, label: str) -> None:
    left, top, right, bottom = rect
    margin_x = max(1, (right - left) // 4)
    margin_y = max(1, (bottom - top) // 4)
    x = random.randint(left + margin_x, right - margin_x)
    y = random.randint(top + margin_y, bottom - margin_y)
    LOGGER.click(label, label, rect, (x, y))
    DEVICE.click(x, y)


def _click_region(rect: Rect, label: str) -> None:
    left, top, right, bottom = rect
    x = random.randint(left, right)
    y = random.randint(top, bottom)
    LOGGER.click(label, label, rect, (x, y))
    DEVICE.click(x, y)


def _click_and_confirm(name: str, label: str, rect: Rect, timeout: float) -> bool:
    top_left, bottom_right = REGIONS[name]
    return DEVICE.click_until_disappears(
        top_left,
        bottom_right,
        TEMPLATES[name],
        rect,
        threshold=_threshold(name),
        timeout=timeout,
        label=label,
        click_callback=lambda current_rect: _click_rect(current_rect, label),
        log_callback=lambda message: LOGGER.message(label, message),
    )


def _take_frame():
    frame = DEVICE.screenshot()
    if frame is None:
        print("[WARN] 截图失败，等待下一帧")
        time.sleep(SCREENSHOT_INTERVAL)
    return frame


def _wait_and_click(name: str, label: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    last_frame = None
    best_score: Optional[float] = None

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
            if _click_and_confirm(name, label, rect, timeout):
                return True
            return False

    print(
        f"[ERROR] {timeout:.0f} 秒内未识别到{label}，"
        f"最高匹配分数 {_score_text(best_score)}，要求 {_threshold(name):.2f}"
    )
    return False


def _ensure_friend_menu_expanded() -> bool:
    """确认庭院后寻找好友；不可见时依次尝试卷轴和兜底坐标。"""
    deadline = time.monotonic() + MENU_WAIT_SECONDS
    last_frame = None
    best_main_score: Optional[float] = None
    best_friend_score: Optional[float] = None
    best_scroll_score: Optional[float] = None
    fallback_clicked = False

    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame

        main_score, main_rect = _match(frame, "main")
        if main_score is not None and (
            best_main_score is None or main_score > best_main_score
        ):
            best_main_score = main_score
        if main_rect is None:
            continue

        friend_score, friend_rect = _match(frame, "friend")
        if friend_score is not None and (
            best_friend_score is None or friend_score > best_friend_score
        ):
            best_friend_score = friend_score
        if friend_rect is not None:
            print(f"好友入口已显示，功能栏无需展开，匹配分数 {friend_score:.3f}")
            return True

        scroll_score, scroll_rect = _match(frame, "menu_scroll")
        if scroll_score is not None and (
            best_scroll_score is None or scroll_score > best_scroll_score
        ):
            best_scroll_score = scroll_score
        if scroll_rect is not None:
            print(f"识别到右下角卷轴，功能栏处于折叠状态，匹配分数 {scroll_score:.3f}")
            remaining = max(0.1, deadline - time.monotonic())
            if _click_and_confirm("menu_scroll", "展开功能栏卷轴", scroll_rect, remaining):
                print("右侧功能栏已展开")
                return True
            return False

        if not fallback_clicked and try_open_activity_menu_once(frame, LOGGER):
            fallback_clicked = True
            print("未识别到普通卷轴，已在庭院点击一次活动菜单共有区域")
            time.sleep(SCREENSHOT_INTERVAL)
            continue

    print(
        "[ERROR] 未在庭院找到好友入口、右下角卷轴或活动菜单，"
        f"探索灯笼最高分 {_score_text(best_main_score)}，"
        f"好友最高分 {_score_text(best_friend_score)}，"
        f"卷轴最高分 {_score_text(best_scroll_score)}"
    )
    return False


def _detect_active_category(frame) -> Tuple[Optional[str], Optional[float], Optional[float]]:
    """根据固定位置的好友栏箭头判断当前展开的是好友还是跨区好友。"""
    collapsed_score, collapsed_rect = _match(frame, "friend_collapsed")
    expanded_score, expanded_rect = _match(frame, "friend_expanded")

    if collapsed_rect is not None and expanded_rect is None:
        return "cross_region", collapsed_score, expanded_score
    if expanded_rect is not None and collapsed_rect is None:
        return "friend", collapsed_score, expanded_score
    if collapsed_rect is not None and expanded_rect is not None:
        if (collapsed_score or 0.0) > (expanded_score or 0.0):
            return "cross_region", collapsed_score, expanded_score
        return "friend", collapsed_score, expanded_score
    return None, collapsed_score, expanded_score


def _wait_for_active_category(
    expected: Optional[str] = None,
    timeout: float = FRIEND_PAGE_WAIT_SECONDS,
) -> Optional[str]:
    deadline = time.monotonic() + timeout
    last_frame = None
    best_collapsed_score: Optional[float] = None
    best_expanded_score: Optional[float] = None

    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame

        active, collapsed_score, expanded_score = _detect_active_category(frame)
        if collapsed_score is not None and (
            best_collapsed_score is None or collapsed_score > best_collapsed_score
        ):
            best_collapsed_score = collapsed_score
        if expanded_score is not None and (
            best_expanded_score is None or expanded_score > best_expanded_score
        ):
            best_expanded_score = expanded_score

        if active is not None and (expected is None or active == expected):
            label = "好友" if active == "friend" else "跨区好友"
            print(
                f"当前展开的是{label}栏，好友栏未展开/展开分数 "
                f"{_score_text(collapsed_score)}/{_score_text(expanded_score)}"
            )
            return active

    expected_text = "" if expected is None else (
        "好友" if expected == "friend" else "跨区好友"
    )
    print(
        f"[ERROR] 未确认{expected_text}栏展开状态，好友栏未展开/展开最高分 "
        f"{_score_text(best_collapsed_score)}/{_score_text(best_expanded_score)}，"
        f"要求 {FRIEND_STATE_THRESHOLD:.2f}"
    )
    return None


def _switch_category(target: str) -> bool:
    """点击目标栏右半侧，并逐帧确认好友栏箭头已经切换。"""
    if target == "friend":
        label = "展开好友栏"
        click_region = FRIEND_HEADER_CLICK_REGION
    else:
        label = "展开跨区好友栏"
        click_region = CROSS_REGION_HEADER_CLICK_REGION

    deadline = time.monotonic() + SWITCH_WAIT_SECONDS
    attempts = 0
    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        active, _, _ = _detect_active_category(frame)
        if active == target:
            print(f"{label}成功")
            return True

        if attempts >= 3:
            time.sleep(SCREENSHOT_INTERVAL)
            continue

        attempts += 1
        _click_region(click_region, label)
        print(f"已点击{label}右半侧，第 {attempts}/3 次")
        time.sleep(SCREENSHOT_INTERVAL if attempts == 1 else 1.0)

    print(f"[ERROR] 点击 {attempts} 次后仍未确认{label}")
    return False


def _like_cross_region_friends() -> bool:
    """按列表顺序选择并点赞两位跨区好友。"""
    for index, click_region in enumerate(CROSS_REGION_FRIEND_CLICK_REGIONS, start=1):
        label = f"选择第 {index} 位跨区好友"
        _click_region(click_region, label)
        print(f"已点击第 {index} 位跨区好友")

        # 等待右侧好友资料和点赞状态完成切换，避免误读上一位的 Liked。
        time.sleep(1.0)
        if not _like_current_category("cross_region", friend_number=index):
            return False
    return True


def _like_current_category(category: str, friend_number: Optional[int] = None) -> bool:
    """处理当前栏的点赞；红色 Liked 表示已经点过并直接跳过。"""
    category_label = "好友" if category == "friend" else "跨区好友"
    if friend_number is not None:
        category_label = f"{category_label}第 {friend_number} 位"
    deadline = time.monotonic() + LIKE_WAIT_SECONDS
    last_frame = None
    best_like_score: Optional[float] = None
    best_liked_score: Optional[float] = None

    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame

        liked_score, liked_rect = _match(frame, "liked")
        if liked_score is not None and (
            best_liked_score is None or liked_score > best_liked_score
        ):
            best_liked_score = liked_score
        if liked_rect is not None:
            print(
                f"{category_label}已经是 Liked 状态，跳过点击，"
                f"匹配分数 {liked_score:.3f}"
            )
            return True

        like_score, like_rect = _match(frame, "like")
        if like_score is not None and (
            best_like_score is None or like_score > best_like_score
        ):
            best_like_score = like_score
        if like_rect is not None:
            print(f"识别到{category_label}白色 Like，匹配分数 {like_score:.3f}")
            if not _click_and_confirm(
                "like",
                f"{category_label} Like",
                like_rect,
                LIKE_WAIT_SECONDS,
            ):
                return False
            return _wait_for_liked(category_label)

    print(
        f"[ERROR] 未识别到{category_label} Like 或 Liked，"
        f"Like 最高分 {_score_text(best_like_score)}，"
        f"Liked 最高分 {_score_text(best_liked_score)}"
    )
    return False


def _wait_for_liked(category_label: str) -> bool:
    deadline = time.monotonic() + LIKED_WAIT_SECONDS
    last_frame = None
    best_score: Optional[float] = None

    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame

        score, rect = _match(frame, "liked")
        if score is not None and (best_score is None or score > best_score):
            best_score = score
        if rect is not None:
            print(
                f"{category_label}点赞成功，图标已变为红色 Liked，"
                f"匹配分数 {score:.3f}"
            )
            return True

    print(
        f"[ERROR] {category_label}点赞后未出现 Liked，最高匹配分数 "
        f"{_score_text(best_score)}"
    )
    return False


def _wait_for_main(timeout: float = MAIN_WAIT_SECONDS) -> bool:
    """只以探索灯笼作为已经返回庭院的确认标准。"""
    deadline = time.monotonic() + timeout
    last_frame = None
    best_score: Optional[float] = None
    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame
        score, rect = _match(frame, "main")
        if score is not None and (best_score is None or score > best_score):
            best_score = score
        if rect is not None:
            print(f"已返回庭院，探索灯笼匹配分数 {score:.3f}")
            return True

    print(
        "[ERROR] 返回后未识别到庭院探索灯笼，"
        f"最高匹配分数 {_score_text(best_score)}"
    )
    return False


def run(cross_region_only: bool = False) -> bool:
    """进入好友页 → 确定类别顺序 → 分栏点赞并确认 → 返回庭院。"""
    utils.connect_to_mumu()
    mode_label = "仅跨区好友" if cross_region_only else "普通与跨区好友"
    print(f"开始好友点赞任务（{mode_label}），截图间隔 0.5 秒")

    # 1. 展开庭院菜单并进入好友页面。
    if not _ensure_friend_menu_expanded():
        return False
    if not _wait_and_click("friend", "好友", MAIN_WAIT_SECONDS):
        return False

    # 2. 普通模式先处理当前展开栏；跨区模式仅处理跨区好友。
    first_category = _wait_for_active_category()
    if first_category is None:
        return False
    if cross_region_only:
        categories = ("cross_region",)
    else:
        second_category = "cross_region" if first_category == "friend" else "friend"
        categories = (first_category, second_category)

    # 3. 必要时切换类别，等待已点赞标志确认成功后才处理下一栏。
    for index, category in enumerate(categories):
        if index == 0 and category != first_category:
            if not _switch_category(category):
                return False
        if index > 0 and not _switch_category(category):
            return False
        if category == "cross_region":
            liked = _like_cross_region_friends()
        else:
            liked = _like_current_category(category)
        if not liked:
            return False

    # 4. 关闭好友页，并以主界面标志确认返回庭院。
    if not _wait_and_click("back", "返回", BACK_WAIT_SECONDS):
        return False
    if not _wait_for_main():
        return False

    print("好友点赞任务完成，已返回庭院")
    return True


if __name__ == "__main__":
    try:
        success = run()
    except KeyboardInterrupt:
        print("任务已由用户中止")
        success = False

    raise SystemExit(0 if success else 1)

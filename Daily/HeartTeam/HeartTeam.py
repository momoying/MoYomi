"""阴阳师日常任务：同心队。

队长负责集结并完成当天战斗；成员进入预存页，按当前预存体力缺口
重复执行一键预存。界面模板以 1280x720 分辨率制作。
"""

from __future__ import annotations

import math
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import cv2


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Core import automation as utils
from Core.menu import try_open_activity_menu_once
from Core.logging import TaskLogger


LOGGER = TaskLogger("同心队")
print = LOGGER.legacy_print

SCREENSHOT_INTERVAL = 0.5
utils.config["screenshot_speed"] = SCREENSHOT_INTERVAL
BATTLES_COMPLETED_CLEANUP_FAILED = "battles_completed_cleanup_failed"

TEMPLATES = {
    "main": str(SCRIPT_DIR.parent / "CoopReward" / "explore.png"),
    "team": str(SCRIPT_DIR / "team.png"),
    "menu_scroll": str(SCRIPT_DIR / "menu_scroll.png"),
    "heart_team": str(SCRIPT_DIR / "heart_team.png"),
    "rally": str(SCRIPT_DIR / "rally.png"),
    "confirmed": str(SCRIPT_DIR / "confirmed.png"),
    "dungeon": str(SCRIPT_DIR / "dungeon.png"),
    "awakening_type": str(SCRIPT_DIR / "awakening_type.png"),
    "first_level_selected": str(SCRIPT_DIR / "first_level_selected.png"),
    "first_level_option": str(SCRIPT_DIR / "first_level_option.png"),
    "create": str(SCRIPT_DIR / "create.png"),
    "challenge": str(SCRIPT_DIR / "challenge.png"),
    "victory_transition": str(SCRIPT_DIR / "victory_transition.png"),
    "reward": str(SCRIPT_DIR / "reward.png"),
    "back": str(SCRIPT_DIR / "back.png"),
    "exit_team": str(SCRIPT_DIR / "exit_team.png"),
    # 队长退出集结和成员确认预存使用相同的公用确定按钮。
    "confirm": str(SCRIPT_DIR / "confirm.png"),
    "reserve": str(SCRIPT_DIR / "reserve.png"),
    "one_click_reserve": str(SCRIPT_DIR / "one_click_reserve.png"),
}

REGIONS = {
    "main": ((500, 80), (800, 280)),
    "team": ((300, 560), (600, 710)),
    "menu_scroll": ((1100, 540), (1280, 720)),
    "heart_team": ((0, 520), (190, 720)),
    "rally": ((1030, 540), (1280, 720)),
    "dungeon": ((900, 540), (1110, 720)),
    "awakening_type": ((390, 110), (650, 195)),
    "first_level_selected": ((500, 110), (680, 195)),
    "first_level_option": ((390, 170), (590, 570)),
    "create": ((760, 520), (990, 660)),
    "challenge": ((1100, 500), (1280, 720)),
    "victory_transition": ((180, 20), (1080, 420)),
    "reward": ((350, 300), (900, 680)),
    "back": ((0, 0), (120, 105)),
    "exit_team": ((690, 0), (850, 135)),
    "confirm": ((600, 350), (900, 520)),
    "reserve": ((850, 150), (1040, 610)),
    "one_click_reserve": ((1120, 470), (1280, 700)),
}

MATCH_THRESHOLD = 0.80
MATCH_THRESHOLDS = {
    "challenge": 0.85,
    "victory_transition": 0.90,
    "reward": 0.90,
    "back": 0.90,
    "exit_team": 0.90,
    "confirm": 0.90,
    "reserve": 0.90,
    "one_click_reserve": 0.90,
}
MENU_WAIT_SECONDS = 15.0
PAGE_WAIT_SECONDS = 20.0
RALLY_POPUP_LOAD_SECONDS = 1.5
MEMBER_CONFIRM_WAIT_SECONDS = 5.0
MEMBER_CONFIRM_ATTEMPTS = 3
AWAKENING_RALLY_BUTTON = (398, 309, 884, 376)
AWAKENING_CATEGORY_BUTTON = (145, 270, 365, 330)
CREATE_TEAM_BUTTON = (982, 595, 1160, 662)
CREATE_TEAM_RETRY_INTERVAL = 1.0
CREATE_TEAM_CLICK_ATTEMPTS = 3
DUNGEON_PAGE_LOAD_SECONDS = 1.5
MAX_LEVEL_SCROLLS = 5
LEVEL_LIST_BOUNDS = (400, 170, 575, 570)
LEVEL_OPTION_VERTICAL_PADDING = 8
BATTLE_SCREENSHOT_INTERVAL = 2.0
BATTLE_WAIT_SECONDS = 300.0
RETURN_WAIT_SECONDS = 30.0
EXIT_TEAM_CLICK_ATTEMPTS = 3
EXIT_TEAM_CONFIRM_APPEAR_SECONDS = 4.0
EXIT_TEAM_CENTER_JITTER = 4
MONDAY_THURSDAY_BATTLE_COUNT = 20
FRIDAY_SUNDAY_BATTLE_COUNT = 30
VICTORY_TRANSITION_CLICK_AREA = (1030, 540, 1250, 700)
VICTORY_TRANSITION_CLICK_COUNT = (2, 3)
VICTORY_TRANSITION_CLICK_INTERVAL = (0.1, 0.3)
REWARD_BLANK_AREAS = {
    "左侧": (15, 420, 90, 650),
    "右侧": (1190, 350, 1270, 650),
}
STAMINA_TEXT_REGION = (930, 410, 1100, 495)
STAMINA_OCR_SCALE = 3
STAMINA_OCR_MIN_CONFIDENCE = 0.55
STAMINA_READ_SECONDS = 15.0
MAX_MEMBER_RESERVE_CLICKS = 6
MEMBER_SLOTS = (
    {
        "label": "队友1",
        "avatar": (545, 202, 630, 292),
        "confirmed": (592, 245, 632, 285),
    },
    {
        "label": "队友2",
        "avatar": (650, 202, 735, 292),
        "confirmed": (697, 245, 737, 285),
    },
)
Rect = Tuple[int, int, int, int]
_ocr_engine = None


def _score_text(score: Optional[float]) -> str:
    return "无" if score is None else f"{score:.3f}"


def _take_frame():
    frame = utils.take_screenshot()
    if frame is None:
        print("[WARN] 截图失败，等待下一帧")
        time.sleep(SCREENSHOT_INTERVAL)
    return frame


def _match(frame, name: str) -> Tuple[Optional[float], Optional[Rect]]:
    top_left, bottom_right = REGIONS[name]
    threshold = MATCH_THRESHOLDS.get(name, MATCH_THRESHOLD)
    score, rect = utils.crop_and_match(
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
        search_region=(
            top_left[0],
            top_left[1],
            bottom_right[0],
            bottom_right[1],
        ),
    )
    return score, rect


def _safe_randint(first: int, second: int, inset: int = 0) -> int:
    """在坐标区间内取随机值，同时兼容反向和极窄区间。"""
    low, high = sorted((int(first), int(second)))
    safe_inset = min(max(0, int(inset)), (high - low) // 2)
    return random.randint(low + safe_inset, high - safe_inset)


def _click_rect(rect: Rect, label: str) -> None:
    left, top, right, bottom = rect
    margin_x = max(1, (right - left) // 4)
    margin_y = max(1, (bottom - top) // 4)
    x = _safe_randint(left, right, margin_x)
    y = _safe_randint(top, bottom, margin_y)
    LOGGER.click(label, label, rect, (x, y))
    utils.adb_click(x, y)


def _click_random_region(region: Rect, label: str) -> None:
    left, top, right, bottom = region
    x = _safe_randint(left, right)
    y = _safe_randint(top, bottom)
    LOGGER.click(label, label, region, (x, y))
    utils.adb_click(x, y)


def _match_confirmed(
    frame,
    label: str,
    region: Rect,
) -> Tuple[Optional[float], Optional[Rect]]:
    left, top, right, bottom = region
    score, rect = utils.crop_and_match(
        (left, top),
        (right, bottom),
        TEMPLATES["confirmed"],
        frame=frame,
    )
    if score is None or rect is None or score < MATCH_THRESHOLD:
        return score, None
    LOGGER.match(
        f"{label}确认",
        "confirmed",
        score,
        MATCH_THRESHOLD,
        rect,
        search_region=region,
    )
    return score, rect


def _click_and_confirm(
    name: str,
    label: str,
    rect: Rect,
    timeout: float,
) -> bool:
    top_left, bottom_right = REGIONS[name]
    threshold = MATCH_THRESHOLDS.get(name, MATCH_THRESHOLD)
    return utils.click_template_until_disappears(
        top_left,
        bottom_right,
        TEMPLATES[name],
        rect,
        threshold=threshold,
        timeout=timeout,
        label=label,
        click_callback=lambda current_rect: _click_rect(current_rect, label),
        log_callback=lambda message: LOGGER.message(label, message),
    )


def _ensure_team_menu_expanded() -> bool:
    """复用经验妖怪的庭院组队入口和菜单兜底策略。"""
    deadline = time.monotonic() + MENU_WAIT_SECONDS
    best_main_score: Optional[float] = None
    best_team_score: Optional[float] = None
    best_scroll_score: Optional[float] = None
    fallback_clicked = False

    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue

        main_score, main_rect = _match(frame, "main")
        if main_score is not None and (
            best_main_score is None or main_score > best_main_score
        ):
            best_main_score = main_score
        if main_rect is None:
            continue

        team_score, team_rect = _match(frame, "team")
        if team_score is not None and (
            best_team_score is None or team_score > best_team_score
        ):
            best_team_score = team_score
        if team_rect is not None:
            print(f"组队入口已显示，匹配分数 {team_score:.3f}")
            return True

        scroll_score, scroll_rect = _match(frame, "menu_scroll")
        if scroll_score is not None and (
            best_scroll_score is None or scroll_score > best_scroll_score
        ):
            best_scroll_score = scroll_score
        if scroll_rect is not None:
            print(
                "识别到右下角卷轴，功能栏处于折叠状态，"
                f"匹配分数 {scroll_score:.3f}"
            )
            remaining = max(0.1, deadline - time.monotonic())
            return _click_and_confirm(
                "menu_scroll",
                "展开功能栏卷轴",
                scroll_rect,
                remaining,
            )

        if not fallback_clicked and try_open_activity_menu_once(frame, LOGGER):
            fallback_clicked = True
            print("未识别到普通卷轴，已点击一次活动菜单共有区域")
            time.sleep(SCREENSHOT_INTERVAL)

    print(
        "[ERROR] 未在庭院找到组队入口、右下角卷轴或活动菜单，"
        f"探索灯笼最高分 {_score_text(best_main_score)}，"
        f"组队最高分 {_score_text(best_team_score)}，"
        f"卷轴最高分 {_score_text(best_scroll_score)}"
    )
    return False


def _wait_and_click(
    name: str,
    label: str,
    timeout: float,
    confirm_disappears: bool = True,
) -> bool:
    deadline = time.monotonic() + timeout
    best_score: Optional[float] = None

    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        score, rect = _match(frame, name)
        if score is not None and (best_score is None or score > best_score):
            best_score = score
        if rect is None:
            continue

        print(f"识别到{label}，匹配分数 {score:.3f}")
        if not confirm_disappears:
            _click_rect(rect, label)
            return True
        remaining = max(0.1, deadline - time.monotonic())
        return _click_and_confirm(name, label, rect, remaining)

    print(
        f"[ERROR] {timeout:.0f} 秒内未识别到{label}，"
        f"最高匹配分数 {_score_text(best_score)}"
    )
    return False


def _ensure_member_confirmed(slot: dict[str, object]) -> bool:
    label = str(slot["label"])
    avatar_region = slot["avatar"]
    confirmed_region = slot["confirmed"]
    if not (
        isinstance(avatar_region, tuple)
        and isinstance(confirmed_region, tuple)
    ):
        return False
    best_score: Optional[float] = None

    for attempt in range(1, MEMBER_CONFIRM_ATTEMPTS + 1):
        frame = _take_frame()
        if frame is None:
            continue
        score, confirmed_rect = _match_confirmed(
            frame,
            label,
            confirmed_region,
        )
        if score is not None and (best_score is None or score > best_score):
            best_score = score
        if confirmed_rect is not None:
            print(f"{label}已经确认，匹配分数 {score:.3f}")
            return True

        print(
            f"{label}尚未确认，第 {attempt}/{MEMBER_CONFIRM_ATTEMPTS} 次点击头像"
        )
        _click_random_region(avatar_region, f"{label}头像")
        deadline = time.monotonic() + MEMBER_CONFIRM_WAIT_SECONDS
        while time.monotonic() < deadline:
            current = _take_frame()
            if current is None:
                continue
            current_score, confirmed_rect = _match_confirmed(
                current,
                label,
                confirmed_region,
            )
            if current_score is not None and (
                best_score is None or current_score > best_score
            ):
                best_score = current_score
            if confirmed_rect is not None:
                print(f"{label}确认成功，匹配分数 {current_score:.3f}")
                return True

    print(
        f"[ERROR] {label}点击头像后仍未出现确认标志，"
        f"最高匹配分数 {_score_text(best_score)}"
    )
    return False


def _confirm_members_and_select_dungeon() -> bool:
    """确认两名队友，选择觉醒副本集结，再点击组队页副本入口。"""
    print(f"等待集结口号窗口加载 {RALLY_POPUP_LOAD_SECONDS:g} 秒")
    time.sleep(RALLY_POPUP_LOAD_SECONDS)
    for slot in MEMBER_SLOTS:
        if not _ensure_member_confirmed(slot):
            return False

    print("两名队友均已确认，随机点击“觉醒副本，集结！”按钮")
    _click_random_region(AWAKENING_RALLY_BUTTON, "觉醒副本集结")
    if not _wait_and_click(
        "dungeon",
        "副本",
        PAGE_WAIT_SECONDS,
        confirm_disappears=False,
    ):
        return False
    return True


def _ensure_awakening_type() -> bool:
    """确认当前为觉醒业火轮；不是时点击左侧对应副本分类。"""
    print(f"等待副本选择页加载 {DUNGEON_PAGE_LOAD_SECONDS:g} 秒")
    time.sleep(DUNGEON_PAGE_LOAD_SECONDS)
    frame = _take_frame()
    if frame is None:
        return False
    score, type_rect = _match(frame, "awakening_type")
    if type_rect is not None:
        print(f"当前已经是觉醒业火轮，匹配分数 {score:.3f}")
        return True

    print("当前不是觉醒业火轮，点击左侧觉醒业火轮分类")
    _click_random_region(AWAKENING_CATEGORY_BUTTON, "觉醒业火轮分类")
    deadline = time.monotonic() + PAGE_WAIT_SECONDS
    best_score = score
    while time.monotonic() < deadline:
        current = _take_frame()
        if current is None:
            continue
        current_score, type_rect = _match(current, "awakening_type")
        if current_score is not None and (
            best_score is None or current_score > best_score
        ):
            best_score = current_score
        if type_rect is not None:
            print(f"已切换到觉醒业火轮，匹配分数 {current_score:.3f}")
            return True
    print(
        "[ERROR] 点击觉醒业火轮分类后未识别到顶部标志，"
        f"最高匹配分数 {_score_text(best_score)}"
    )
    return False


def _wait_for_first_level_selected(timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    best_score: Optional[float] = None
    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        score, selected_rect = _match(frame, "first_level_selected")
        if score is not None and (best_score is None or score > best_score):
            best_score = score
        if selected_rect is not None:
            print(f"已选中业火轮一层，顶部匹配分数 {score:.3f}")
            return True
    print(
        "[ERROR] 点击一层后顶部未出现“壹层”标志，"
        f"最高匹配分数 {_score_text(best_score)}"
    )
    return False


def _scroll_levels_toward_first() -> None:
    """将层数列表向顶部滚动；坐标和距离在安全范围内随机。"""
    x = random.randint(445, 535)
    start_y = random.randint(220, 285)
    distance = random.randint(190, 265)
    end_y = min(545, start_y + distance)
    duration = random.randint(450, 750)
    LOGGER.message(
        "层数选择",
        f"层数栏向顶部滚动 ({x}, {start_y}) -> ({x}, {end_y})，"
        f"时长 {duration}ms",
    )
    utils.adb_swipe(x, start_y, x, end_y, duration)


def _ensure_first_level() -> bool:
    """确认一层；未选中时滚动层数栏并点击“壹层”整行。"""
    frame = _take_frame()
    if frame is None:
        return False
    score, selected_rect = _match(frame, "first_level_selected")
    if selected_rect is not None:
        print(f"当前已经选中业火轮一层，匹配分数 {score:.3f}")
        return True

    best_option_score: Optional[float] = None
    for scroll_index in range(MAX_LEVEL_SCROLLS + 1):
        current = frame if scroll_index == 0 else _take_frame()
        if current is None:
            continue
        option_score, option_rect = _match(current, "first_level_option")
        if option_score is not None and (
            best_option_score is None or option_score > best_option_score
        ):
            best_option_score = option_score
        if option_rect is not None:
            left, top, right, bottom = option_rect
            list_left, list_top, list_right, list_bottom = LEVEL_LIST_BOUNDS
            row_region = (
                list_left,
                max(list_top, top - LEVEL_OPTION_VERTICAL_PADDING),
                list_right,
                min(list_bottom, bottom + LEVEL_OPTION_VERTICAL_PADDING),
            )
            print(
                "识别到未选中的业火轮一层，"
                f"匹配分数 {option_score:.3f}，点击实际所在行 {row_region}"
            )
            _click_random_region(row_region, "业火轮一层")
            return _wait_for_first_level_selected(PAGE_WAIT_SECONDS)
        if scroll_index < MAX_LEVEL_SCROLLS:
            print(
                f"层数栏未找到一层，第 {scroll_index + 1}/"
                f"{MAX_LEVEL_SCROLLS} 次向顶部滚动"
            )
            _scroll_levels_toward_first()
            time.sleep(SCREENSHOT_INTERVAL)

    print(
        "[ERROR] 层数栏滚动后仍未识别到业火轮一层，"
        f"最高匹配分数 {_score_text(best_option_score)}"
    )
    return False


def _create_team_with_retry(timeout: float = PAGE_WAIT_SECONDS) -> bool:
    """重复点击创建队伍，直到确认框出现并被成功关闭。"""
    deadline = time.monotonic() + timeout
    attempts = 0
    best_create_score: Optional[float] = None
    best_page_score: Optional[float] = None
    last_click_time = float("-inf")

    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue

        create_score, create_rect = _match(frame, "create")
        if create_score is not None and (
            best_create_score is None or create_score > best_create_score
        ):
            best_create_score = create_score
        if create_rect is not None:
            print(
                "创建队伍确认框已经出现，"
                f"匹配分数 {create_score:.3f}"
            )
            remaining = max(0.1, deadline - time.monotonic())
            # _click_and_confirm 会在点击后重新识别；按钮仍在就再次点击。
            return _click_and_confirm(
                "create",
                "创建",
                create_rect,
                remaining,
            )

        page_score, page_rect = _match(frame, "first_level_selected")
        if page_score is not None and (
            best_page_score is None or page_score > best_page_score
        ):
            best_page_score = page_score
        now = time.monotonic()
        if page_rect is not None and attempts >= CREATE_TEAM_CLICK_ATTEMPTS:
            print(
                f"[ERROR] 创建队伍连续点击 {CREATE_TEAM_CLICK_ATTEMPTS} 次后"
                "仍未出现确认框"
            )
            return False
        if (
            page_rect is not None
            and now - last_click_time >= CREATE_TEAM_RETRY_INTERVAL
        ):
            attempts += 1
            print(
                "仍在副本选择界面，第 "
                f"{attempts}/{CREATE_TEAM_CLICK_ATTEMPTS} 次点击创建队伍"
            )
            _click_random_region(CREATE_TEAM_BUTTON, "创建队伍")
            last_click_time = time.monotonic()

    print(
        "[ERROR] 创建队伍点击后确认框未出现，"
        f"已点击 {attempts} 次，创建按钮最高分 "
        f"{_score_text(best_create_score)}，副本页最高分 "
        f"{_score_text(best_page_score)}"
    )
    return False


def _configure_and_create_team() -> bool:
    """选择业火轮一层，重复确认创建队伍操作已生效。"""
    if not _ensure_awakening_type():
        return False
    if not _ensure_first_level():
        return False

    print("副本与层数选择完成，开始点击右下角创建队伍")
    return _create_team_with_retry()


def battle_target_count(now: Optional[datetime] = None) -> int:
    """周一至周四 20 场，周五至周日 30 场。"""
    current = now or datetime.now().astimezone()
    return (
        FRIDAY_SUNDAY_BATTLE_COUNT
        if current.weekday() >= 4
        else MONDAY_THURSDAY_BATTLE_COUNT
    )


def _rapid_click_victory_transition() -> int:
    """同一场胜利过渡只调用一次，右下角快速随机点击 2～3 次。"""
    click_count = random.randint(*VICTORY_TRANSITION_CLICK_COUNT)
    left, top, right, bottom = VICTORY_TRANSITION_CLICK_AREA
    print(f"快速跳过胜利过渡，本轮随机点击 {click_count} 次")
    for click_index in range(1, click_count + 1):
        x = random.randint(left, right)
        y = random.randint(top, bottom)
        LOGGER.click(
            "胜利过渡",
            f"右下安全区域 {click_index}/{click_count}",
            VICTORY_TRANSITION_CLICK_AREA,
            (x, y),
        )
        utils.adb_click(x, y)
        if click_index < click_count:
            interval = random.uniform(*VICTORY_TRANSITION_CLICK_INTERVAL)
            print(f"第 {click_index} 次连点后等待 {interval:.3f} 秒")
            time.sleep(interval)
    return click_count


def _click_random_reward_side() -> None:
    side, region = random.choice(tuple(REWARD_BLANK_AREAS.items()))
    _click_random_region(region, f"奖励页{side}安全空白区域")


def collect_battle_rewards(timeout: Optional[float] = None) -> bool:
    """处理一场胜利过渡和奖励页；每场最多触发一轮快速连点。"""
    previous_interval = utils.config.get("screenshot_speed", SCREENSHOT_INTERVAL)
    utils.config["screenshot_speed"] = BATTLE_SCREENSHOT_INTERVAL
    wait_seconds = BATTLE_WAIT_SECONDS if timeout is None else max(0.1, timeout)
    deadline = time.monotonic() + wait_seconds
    best_transition_score: Optional[float] = None
    best_reward_score: Optional[float] = None
    transition_clicked = False
    reward_seen = False

    print(
        f"战斗进行中，每 {BATTLE_SCREENSHOT_INTERVAL:g} 秒检查一次"
        "胜利过渡和奖励"
    )
    try:
        while time.monotonic() < deadline:
            frame = _take_frame()
            if frame is None:
                continue

            transition_score, transition_rect = _match(
                frame,
                "victory_transition",
            )
            if transition_score is not None and (
                best_transition_score is None
                or transition_score > best_transition_score
            ):
                best_transition_score = transition_score
            if transition_rect is not None:
                if not transition_clicked:
                    print(
                        "识别到同心队胜利过渡，"
                        f"匹配分数 {transition_score:.3f}"
                    )
                    _rapid_click_victory_transition()
                    transition_clicked = True
                time.sleep(SCREENSHOT_INTERVAL)
                continue

            reward_score, reward_rect = _match(frame, "reward")
            if reward_score is not None and (
                best_reward_score is None or reward_score > best_reward_score
            ):
                best_reward_score = reward_score
            if reward_rect is not None:
                if not reward_seen:
                    print(
                        "进入同心队奖励页，"
                        f"匹配分数 {reward_score:.3f}"
                    )
                    reward_seen = True
                _click_random_reward_side()
                time.sleep(SCREENSHOT_INTERVAL)
                continue

            if reward_seen:
                print("奖励模板已经消失，本场结算完成")
                return True

        print(
            "[ERROR] 等待同心队胜利超时，过渡/奖励最高分 "
            f"{_score_text(best_transition_score)}/"
            f"{_score_text(best_reward_score)}"
        )
        return False
    finally:
        utils.config["screenshot_speed"] = previous_interval


def _run_battles() -> bool | str:
    target_count = battle_target_count()
    print(f"本日同心队计划战斗 {target_count} 场")
    for battle_index in range(1, target_count + 1):
        print(f"准备第 {battle_index}/{target_count} 场同心队战斗")
        if not _wait_and_click("challenge", "挑战", PAGE_WAIT_SECONDS):
            return False
        if not collect_battle_rewards():
            return False
        if not _wait_for_template(
            "challenge",
            "挑战界面",
            RETURN_WAIT_SECONDS,
        ):
            if battle_index == target_count:
                print(
                    "[ERROR] 最后一场奖励已经领取，但未能重新识别挑战界面；"
                    "战斗目标仍按完成处理，交由中控执行战后专属恢复"
                )
                return BATTLES_COMPLETED_CLEANUP_FAILED
            return False
        print(f"[SUCCESS] 第 {battle_index}/{target_count} 场战斗完成")
    return True


def _wait_for_template(name: str, label: str, timeout: float) -> bool:
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
            return True
    print(
        f"[ERROR] {timeout:.0f} 秒内未识别到{label}，"
        f"最高匹配分数 {_score_text(best_score)}"
    )
    return False


def _template_appears(name: str, timeout: float) -> bool:
    """静默等待可选页面标志，用于存在两种正常返回路径的场景。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        _score, rect = _match(frame, name)
        if rect is not None:
            return True
    return False


def _get_ocr_engine():
    """按需加载项目内置 PaddleOCR，避免队长流程承担初始化开销。"""
    global _ocr_engine
    if _ocr_engine is not None:
        return _ocr_engine

    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    from paddleocr import PaddleOCR

    model_dir = PROJECT_ROOT / "modle"
    _ocr_engine = PaddleOCR(
        det_model_dir=str(model_dir / "ch_PP-OCRv4_det_infer"),
        rec_model_dir=str(model_dir / "ch_PP-OCRv4_rec_infer"),
        cls_model_dir=str(model_dir / "ch_ppocr_mobile_v2.0_cls_infer"),
        lang="ch",
        show_log=False,
        use_gpu=False,
    )
    return _ocr_engine


def _read_reserved_stamina(frame) -> Optional[tuple[int, int]]:
    """OCR 预存页的“当前体力/上限”，例如 376/400。"""
    left, top, right, bottom = STAMINA_TEXT_REGION
    crop = frame[top:bottom, left:right]
    if crop.size == 0:
        return None
    enlarged = cv2.resize(
        crop,
        None,
        fx=STAMINA_OCR_SCALE,
        fy=STAMINA_OCR_SCALE,
        interpolation=cv2.INTER_CUBIC,
    )
    result = _get_ocr_engine().ocr(enlarged, cls=False)
    if not result or not result[0]:
        return None

    candidates: list[tuple[str, float]] = []
    for line in result[0]:
        try:
            _, (text, confidence) = line
            confidence = float(confidence)
        except (TypeError, ValueError, IndexError):
            continue
        if confidence < STAMINA_OCR_MIN_CONFIDENCE:
            continue
        normalized = (
            str(text)
            .replace(" ", "")
            .replace("O", "0")
            .replace("o", "0")
            .replace("／", "/")
        )
        candidates.append((normalized, confidence))

    joined = "".join(text for text, _confidence in candidates)
    match = re.search(r"(\d{1,3})/(\d{1,3})", joined)
    if match is None:
        LOGGER.message(
            "预存体力OCR",
            "未解析出体力数值，"
            f"识别文字={joined or '无'}，"
            "最高置信度="
            f"{max((confidence for _, confidence in candidates), default=0.0):.3f}",
        )
        return None
    current, maximum = (int(value) for value in match.groups())
    if maximum <= 0 or current < 0 or current > maximum:
        return None
    LOGGER.message(
        "预存体力OCR",
        f"识别结果={current}/{maximum}，最高置信度="
        f"{max((confidence for _, confidence in candidates), default=0.0):.3f}",
    )
    return current, maximum


def _wait_for_reserved_stamina(
    timeout: float = STAMINA_READ_SECONDS,
) -> Optional[tuple[int, int]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        value = _read_reserved_stamina(frame)
        if value is not None:
            return value
    print(f"[ERROR] {timeout:.0f} 秒内未能识别预存体力数值")
    return None


def _return_member_to_courtyard() -> bool:
    """从预存页逐层返回；每次只点一次，避免连续穿透多个页面。"""
    for step in range(1, 5):
        if _template_appears("main", 2.0):
            print("成员补存完成，已返回庭院")
            return True
        if not _wait_and_click(
            "back",
            f"成员补存返回（第 {step} 次）",
            PAGE_WAIT_SECONDS,
            confirm_disappears=False,
        ):
            return False
        time.sleep(1.0)
    if _template_appears("main", PAGE_WAIT_SECONDS):
        print("成员补存完成，已返回庭院")
        return True
    print("[ERROR] 成员补存完成后未能返回庭院")
    return False


def _run_member_reserve() -> bool:
    """根据预存体力缺口，每差 100 点执行一次一键预存并逐次确认。"""
    if not _wait_and_click("reserve", "成员预存入口", PAGE_WAIT_SECONDS):
        return False
    stamina = _wait_for_reserved_stamina()
    if stamina is None:
        return False
    current, maximum = stamina
    missing = maximum - current
    click_count = math.ceil(missing / 100)
    if click_count > MAX_MEMBER_RESERVE_CLICKS:
        print(
            f"[ERROR] 预存体力缺口 {missing} 异常，"
            f"所需点击 {click_count} 次超过安全上限"
        )
        return False
    print(
        f"当前预存体力 {current}/{maximum}，缺口 {missing}，"
        f"需要一键预存 {click_count} 次"
    )
    for index in range(1, click_count + 1):
        if not _wait_and_click(
            "one_click_reserve",
            f"一键预存（第 {index}/{click_count} 次）",
            PAGE_WAIT_SECONDS,
            confirm_disappears=False,
        ):
            return False
        if not _wait_and_click(
            "confirm",
            f"确认预存（第 {index}/{click_count} 次）",
            PAGE_WAIT_SECONDS,
        ):
            return False
        time.sleep(SCREENSHOT_INTERVAL)

    final_stamina = _wait_for_reserved_stamina()
    if final_stamina is None:
        return False
    final_current, final_maximum = final_stamina
    if final_current != final_maximum:
        print(
            "[ERROR] 一键预存次数执行完毕但体力仍未满："
            f"{final_current}/{final_maximum}"
        )
        return False
    print(f"[SUCCESS] 成员预存体力已补满：{final_current}/{final_maximum}")
    return _return_member_to_courtyard()


def _click_exit_team_center(rect: Rect, label: str, attempt: int) -> None:
    """点击顶部退出集结叉号中心，避免小模板边缘落点无效。"""
    left, top, right, bottom = rect
    center_x = (left + right) // 2
    center_y = (top + bottom) // 2
    x = _safe_randint(
        max(left, center_x - EXIT_TEAM_CENTER_JITTER),
        min(right, center_x + EXIT_TEAM_CENTER_JITTER),
    )
    y = _safe_randint(
        max(top, center_y - EXIT_TEAM_CENTER_JITTER),
        min(bottom, center_y + EXIT_TEAM_CENTER_JITTER),
    )
    click_label = f"{label}（第 {attempt}/{EXIT_TEAM_CLICK_ATTEMPTS} 次）"
    LOGGER.click(click_label, label, rect, (x, y))
    utils.adb_click(x, y)


def _click_exit_team_until_confirm(
    *,
    exit_rect: Optional[Rect],
    label: str,
) -> bool:
    """点击退出集结叉号；只有确认弹窗出现才视为点击生效。"""
    current_rect = exit_rect
    best_score: Optional[float] = None
    for attempt in range(1, EXIT_TEAM_CLICK_ATTEMPTS + 1):
        if current_rect is None:
            deadline = time.monotonic() + RETURN_WAIT_SECONDS
            while time.monotonic() < deadline:
                frame = _take_frame()
                if frame is None:
                    continue
                score, matched_rect = _match(frame, "exit_team")
                if score is not None and (
                    best_score is None or score > best_score
                ):
                    best_score = score
                if matched_rect is not None:
                    current_rect = matched_rect
                    break
            if current_rect is None:
                print(
                    "[ERROR] 未识别到顶部退出组队按钮，"
                    f"最高匹配分数 {_score_text(best_score)}"
                )
                return False

        _click_exit_team_center(current_rect, label, attempt)
        if _template_appears("confirm", EXIT_TEAM_CONFIRM_APPEAR_SECONDS):
            print(f"{label}点击已生效，退出确认框已经出现")
            return True

        print(
            f"[WARN] {label}第 {attempt}/{EXIT_TEAM_CLICK_ATTEMPTS} 次点击后"
            "未出现确认框，重新识别并点击按钮中心"
        )
        current_rect = None

    print(
        f"[ERROR] {label}连续点击 {EXIT_TEAM_CLICK_ATTEMPTS} 次"
        "仍未出现确认框"
    )
    return False


def _exit_gathering_to_courtyard(
    *,
    exit_rect: Optional[Rect] = None,
    label_prefix: str = "",
) -> bool:
    """退出仍在进行的同心队集结，并保证最终停留在庭院。"""
    prefix = f"{label_prefix}" if label_prefix else ""
    if not _click_exit_team_until_confirm(
        exit_rect=exit_rect,
        label=f"{prefix}退出组队",
    ):
        return False
    if not _wait_and_click(
        "confirm",
        f"{prefix}退出组队确认",
        RETURN_WAIT_SECONDS,
    ):
        return False
    if _template_appears("main", 5.0):
        print(f"{prefix}确认退出组队后已经在庭院")
        return True
    print(f"{prefix}确认退出组队后仍在集结页，继续点击左上角返回")
    if not _wait_and_click(
        "back",
        f"{prefix}集结页返回",
        RETURN_WAIT_SECONDS,
    ):
        return False
    if not _wait_for_template("main", "庭院探索灯笼", RETURN_WAIT_SECONDS):
        return False
    print(f"{prefix}已退出同心队并返回庭院")
    return True


def _cleanup_stale_gathering_before_start() -> bool:
    """重试任务前清除全局恢复未解除的同心队集结状态。"""
    frame = _take_frame()
    if frame is None:
        return False
    score, exit_rect = _match(frame, "exit_team")
    if exit_rect is None:
        return True
    print(
        "[WARN] 进入同心队前检测到残留集结状态，"
        f"匹配分数 {score:.3f}，先退出集结再重新开始任务"
    )
    return _exit_gathering_to_courtyard(
        exit_rect=exit_rect,
        label_prefix="重试前清理/",
    )


def recover_after_completed_battles(
    stop_event=None,
    *,
    timeout: float = 90.0,
) -> bool:
    """战斗已完成但退出失败时，从任意退出阶段解除组队并回到庭院。"""
    deadline = time.monotonic() + max(1.0, float(timeout))
    action_count = 0
    print("开始同心队战后专属恢复：解除组队并返回庭院")

    while time.monotonic() < deadline:
        if stop_event is not None and stop_event.is_set():
            print("[WARN] 用户请求停止，取消同心队战后恢复")
            return False

        frame = _take_frame()
        if frame is None:
            continue

        # 确认框可能覆盖在返回键或退出集结按钮上，必须优先处理。
        _confirm_score, confirm_rect = _match(frame, "confirm")
        if confirm_rect is not None:
            remaining = max(0.1, deadline - time.monotonic())
            if not _click_and_confirm(
                "confirm",
                "战后恢复/退出确认",
                confirm_rect,
                remaining,
            ):
                return False
            action_count += 1
            time.sleep(SCREENSHOT_INTERVAL)
            continue

        # 庭院也可能仍显示同心队集结横幅，因此要先解除集结，再判定成功。
        _exit_score, exit_rect = _match(frame, "exit_team")
        if exit_rect is not None:
            if not _click_exit_team_until_confirm(
                exit_rect=exit_rect,
                label="战后恢复/退出组队",
            ):
                return False
            action_count += 1
            continue

        _main_score, main_rect = _match(frame, "main")
        if main_rect is not None:
            print(
                "[SUCCESS] 同心队战后恢复完成，已解除组队并回到庭院，"
                f"共执行 {action_count} 次操作"
            )
            return True

        _back_score, back_rect = _match(frame, "back")
        if back_rect is not None:
            _click_rect(back_rect, "战后恢复/左上角返回")
            action_count += 1
            time.sleep(1.0)
            continue

        time.sleep(SCREENSHOT_INTERVAL)

    print(f"[ERROR] 同心队战后恢复超过 {timeout:.0f} 秒仍未回到无组队状态的庭院")
    return False


def _leave_team_to_courtyard() -> bool:
    """挑战页返回集结页，退出组队，再由左上角返回庭院。"""
    print("战斗场数已经完成，开始退出同心队")
    # 返回按钮在确认弹窗的半透明遮罩后仍会保持高分；这里只点击一次，
    # 随即转而等待确认按钮，不能使用“等待返回按钮消失”的通用逻辑。
    if not _wait_and_click(
        "back",
        "挑战页返回",
        RETURN_WAIT_SECONDS,
        confirm_disappears=False,
    ):
        return False
    if not _wait_and_click(
        "confirm",
        "确认退出组队面板",
        RETURN_WAIT_SECONDS,
    ):
        return False
    return _exit_gathering_to_courtyard()


def run(role: str = "leader") -> bool | str:
    """执行同心队队长战斗或成员预存流程。"""
    if role not in {"leader", "member"}:
        print("[ERROR] 未配置有效的同心队身份")
        return False

    utils.connect_to_mumu()
    print(f"开始同心队{'队长' if role == 'leader' else '成员'}流程")
    if not _cleanup_stale_gathering_before_start():
        print("[ERROR] 未能清理上一次异常遗留的同心队集结状态")
        return False
    if not _ensure_team_menu_expanded():
        return False
    if not _wait_and_click("team", "组队", PAGE_WAIT_SECONDS):
        return False
    if not _wait_and_click("heart_team", "同心队", PAGE_WAIT_SECONDS):
        return False
    if role == "member":
        return _run_member_reserve()

    if not _wait_and_click(
        "rally",
        "集结",
        PAGE_WAIT_SECONDS,
        confirm_disappears=False,
    ):
        return False
    if not _confirm_members_and_select_dungeon():
        return False
    if not _configure_and_create_team():
        return False
    battle_result = _run_battles()
    if battle_result == BATTLES_COMPLETED_CLEANUP_FAILED:
        return BATTLES_COMPLETED_CLEANUP_FAILED
    if not battle_result:
        return False
    try:
        cleanup_succeeded = _leave_team_to_courtyard()
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        cleanup_succeeded = False
        print(f"[ERROR] 同心队战后退出发生异常：{exc}")
    if not cleanup_succeeded:
        print(
            "[ERROR] 同心队目标场数已经完成，但退出组队流程失败；"
            "交由中控写入完成时间后执行专属恢复"
        )
        return BATTLES_COMPLETED_CLEANUP_FAILED
    print("[SUCCESS] 同心队目标场数全部完成并已返回庭院")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if run() is True else 1)

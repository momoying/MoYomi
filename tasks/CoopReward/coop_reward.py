from __future__ import annotations

import random
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

import cv2


SCRIPT_DIR = Path(__file__).resolve().parent
DAILY_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = DAILY_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from module import automation as utils
from module.base.device import TaskDevice
from module.logging import TaskLogger


from tasks.CoopReward.assets import CoopRewardAssets

ASSETS = CoopRewardAssets
TEMPLATES = ASSETS.TEMPLATES
REGIONS = ASSETS.REGIONS
MATCH_THRESHOLDS = ASSETS.MATCH_THRESHOLDS
MAX_FLOOR_SWIPES = ASSETS.MAX_FLOOR_SWIPES
MAX_BONUS_SWIPES = ASSETS.MAX_BONUS_SWIPES
FLOOR_LIST_SWIPE = ASSETS.FLOOR_LIST_SWIPE
BONUS_SWIPE_X_RANGE = ASSETS.BONUS_SWIPE_X_RANGE
BONUS_SWIPE_START_Y_RANGE = ASSETS.BONUS_SWIPE_START_Y_RANGE
BONUS_SWIPE_END_Y_RANGE = ASSETS.BONUS_SWIPE_END_Y_RANGE
BONUS_SWIPE_DURATION_RANGE = ASSETS.BONUS_SWIPE_DURATION_RANGE
BONUS_ACTIVE_MIN_YELLOW_RATIO = ASSETS.BONUS_ACTIVE_MIN_YELLOW_RATIO
FINISH_BLANK_AREAS = ASSETS.FINISH_BLANK_AREAS
VICTORY_TRANSITION_CLICK_AREA = ASSETS.VICTORY_TRANSITION_CLICK_AREA
REWARD_RECOVERY_BUTTONS = ASSETS.REWARD_RECOVERY_BUTTONS
BONUS_PANEL_BLANK_AREAS = ASSETS.BONUS_PANEL_BLANK_AREAS

LOGGER = TaskLogger("协战奖励")
DEVICE = TaskDevice(utils, LOGGER)
print = LOGGER.legacy_print
BATTLE_COMPLETED_RECOVERY_REQUIRED = "battle_completed_recovery_required"


SCREENSHOT_INTERVAL = 0.5
BATTLE_SCREENSHOT_INTERVAL = 2.0
utils.config["screenshot_speed"] = SCREENSHOT_INTERVAL





ENTRY_WAIT_SECONDS = 20.0
EXPLORE_MAX_ATTEMPTS = 20
FLOOR_WAIT_SECONDS = 30.0
FORMATION_WAIT_SECONDS = 15.0
BONUS_WAIT_SECONDS = 20.0
BONUS_DISMISS_WAIT_SECONDS = 8.0
CHALLENGE_WAIT_SECONDS = 15.0
BATTLE_WAIT_SECONDS = 300.0
REWARD_STALL_SECONDS = 5.0
REWARD_RECOVERY_WAIT_SECONDS = 15.0
RETURN_WAIT_SECONDS = 30.0
MAX_STATE_CLICKS = 3

VICTORY_TRANSITION_CLICK_COUNT = (2, 3)
VICTORY_TRANSITION_CLICK_INTERVAL = (0.1, 0.3)

Rect = Tuple[int, int, int, int]


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


def _score_text(score: Optional[float]) -> str:
    return "无" if score is None else f"{score:.3f}"


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


def _wait_and_click(
    name: str,
    label: str,
    timeout: float,
    max_attempts: Optional[int] = None,
) -> bool:
    deadline = time.monotonic() + timeout
    last_frame = None
    best_score: Optional[float] = None
    attempts = 0

    while (
        attempts < max_attempts
        if max_attempts is not None
        else time.monotonic() < deadline
    ):
        attempts += 1
        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame
        score, rect = _match(frame, name)
        if score is not None and (best_score is None or score > best_score):
            best_score = score
        if rect is None:
            continue

        print(f"识别到{label}，匹配分数 {score:.3f}")
        remaining = (
            timeout
            if max_attempts is not None
            else max(0.1, deadline - time.monotonic())
        )
        if _click_and_confirm(name, label, rect, remaining):
            return True
        break

    print(
        f"[ERROR] 未能进入{label}，最高匹配分数 {_score_text(best_score)}，"
        f"要求 {MATCH_THRESHOLDS[name]:.2f}，共检测 {attempts} 次"
    )
    return False


def _floor10_state(
    frame,
) -> Tuple[str, Optional[float], Optional[float], Optional[Rect]]:
    active_score, active_rect = _match(frame, "floor10_active")
    inactive_score, inactive_rect = _match(frame, "floor10_inactive")

    if active_rect is not None and (
        inactive_rect is None or (active_score or 0.0) > (inactive_score or 0.0)
    ):
        return "active", active_score, inactive_score, active_rect
    if inactive_rect is not None:
        return "inactive", active_score, inactive_score, inactive_rect
    return "missing", active_score, inactive_score, None


def _ensure_floor10_active() -> bool:
    deadline = time.monotonic() + FLOOR_WAIT_SECONDS
    last_frame = None
    swipes = 0
    clicks = 0
    best_active: Optional[float] = None
    best_inactive: Optional[float] = None

    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame

        state, active_score, inactive_score, rect = _floor10_state(frame)
        if active_score is not None and (
            best_active is None or active_score > best_active
        ):
            best_active = active_score
        if inactive_score is not None and (
            best_inactive is None or inactive_score > best_inactive
        ):
            best_inactive = inactive_score

        if state == "active":
            print(
                "御魂十层已经选中，选中/未选中模板分数 "
                f"{_score_text(active_score)}/{_score_text(inactive_score)}"
            )
            return True

        if state == "inactive" and rect is not None:
            if clicks >= MAX_STATE_CLICKS:
                break
            clicks += 1
            print(
                f"识别到未选中的御魂十层，第 {clicks}/{MAX_STATE_CLICKS} 次点击"
            )
            _click_rect(rect, "选择御魂十层")
            time.sleep(SCREENSHOT_INTERVAL if clicks == 1 else 1.0)
            continue

        if swipes >= MAX_FLOOR_SWIPES:
            break
        swipes += 1
        start_x, start_y, end_x, end_y = FLOOR_LIST_SWIPE
        LOGGER.message(
            "选择御魂十层",
            f"左侧层数栏向下浏览，第 {swipes}/{MAX_FLOOR_SWIPES} 次，"
            f"滑动 ({start_x}, {start_y}) -> ({end_x}, {end_y})",
        )
        DEVICE.swipe(start_x, start_y, end_x, end_y, duration_ms=800)
        time.sleep(0.8)

    print(
        "[ERROR] 未能选中御魂十层，选中/未选中模板最高分 "
        f"{_score_text(best_active)}/{_score_text(best_inactive)}，"
        f"已滑动 {swipes} 次、点击 {clicks} 次"
    )
    return False


def _formation_state(
    frame,
) -> Tuple[str, Optional[float], Optional[float], Optional[Rect]]:
    locked_score, locked_rect = _match(frame, "formation_locked")
    unlocked_score, unlocked_rect = _match(frame, "formation_unlocked")
    if locked_rect is not None and (
        unlocked_rect is None or (locked_score or 0.0) > (unlocked_score or 0.0)
    ):
        return "locked", locked_score, unlocked_score, locked_rect
    if unlocked_rect is not None:
        return "unlocked", locked_score, unlocked_score, unlocked_rect
    return "missing", locked_score, unlocked_score, None


def _ensure_formation_locked() -> bool:
    deadline = time.monotonic() + FORMATION_WAIT_SECONDS
    last_frame = None
    clicks = 0
    best_locked: Optional[float] = None
    best_unlocked: Optional[float] = None

    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame

        state, locked_score, unlocked_score, rect = _formation_state(frame)
        if locked_score is not None and (
            best_locked is None or locked_score > best_locked
        ):
            best_locked = locked_score
        if unlocked_score is not None and (
            best_unlocked is None or unlocked_score > best_unlocked
        ):
            best_unlocked = unlocked_score

        if state == "locked":
            print(
                "阵容已经上锁，锁定/未锁定模板分数 "
                f"{_score_text(locked_score)}/{_score_text(unlocked_score)}"
            )
            return True
        if state == "unlocked" and rect is not None and clicks < MAX_STATE_CLICKS:
            clicks += 1
            print(f"阵容尚未上锁，第 {clicks}/{MAX_STATE_CLICKS} 次点击锁定")
            _click_rect(rect, "锁定阵容")
            time.sleep(SCREENSHOT_INTERVAL if clicks == 1 else 1.0)
            continue
        time.sleep(SCREENSHOT_INTERVAL)

    print(
        "[ERROR] 未能确认阵容上锁，锁定/未锁定模板最高分 "
        f"{_score_text(best_locked)}/{_score_text(best_unlocked)}"
    )
    return False


def _open_bonus_panel() -> bool:
    deadline = time.monotonic() + BONUS_WAIT_SECONDS
    last_frame = None
    best_lantern: Optional[float] = None
    best_start: Optional[float] = None
    best_row: Optional[float] = None
    clicks = 0

    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame

        start_score, start_rect = _match(frame, "bonus_start")
        if start_score is not None and (
            best_start is None or start_score > best_start
        ):
            best_start = start_score
        if start_rect is not None:
            print(f"加成面板已经打开，开始按钮匹配分数 {start_score:.3f}")
            return True

        row_score, row_rect = _match(frame, "soul_bonus")
        if row_score is not None and (
            best_row is None or row_score > best_row
        ):
            best_row = row_score
        if row_rect is not None:
            print(f"加成面板已经打开，御魂加成行匹配分数 {row_score:.3f}")
            return True

        lantern_score, lantern_rect = _match(frame, "bonus_lantern")
        if lantern_score is not None and (
            best_lantern is None or lantern_score > best_lantern
        ):
            best_lantern = lantern_score
        if lantern_rect is None:
            continue
        if clicks >= MAX_STATE_CLICKS:
            break

        clicks += 1
        print(f"识别到加成灯笼，第 {clicks}/{MAX_STATE_CLICKS} 次点击")
        _click_rect(lantern_rect, "打开加成面板")
        time.sleep(SCREENSHOT_INTERVAL if clicks == 1 else 1.0)

    print(
        "[ERROR] 未能打开加成面板，加成灯笼/开始按钮/加成行最高分 "
        f"{_score_text(best_lantern)}/{_score_text(best_start)}/"
        f"{_score_text(best_row)}"
    )
    return False


def _bonus_button_match(
    frame,
    row_rect: Rect,
    name: str,
    label: str,
) -> Tuple[Optional[float], Optional[Rect]]:
    _, top, right, bottom = row_rect
    top_left = (right + 80, top)
    bottom_right = (min(1280, right + 150), bottom)
    score, rect = DEVICE.match(
        top_left,
        bottom_right,
        TEMPLATES[name],
        frame=frame,
    )
    threshold = MATCH_THRESHOLDS[name]
    if score is None or rect is None or score < threshold:
        return score, None
    LOGGER.match(
        label,
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


def _bonus_start_match(
    frame,
    row_rect: Rect,
) -> Tuple[Optional[float], Optional[Rect]]:
    return _bonus_button_match(frame, row_rect, "bonus_start", "开启御魂加成")


def _bonus_control_state(
    frame,
    row_rect: Rect,
) -> Tuple[bool, float, float]:
    """用计时条颜色判断御魂加成是否处于开启状态。"""
    _, top, right, bottom = row_rect
    left = right + 5
    upper = top + 3
    right_edge = min(1280, right + 140)
    lower = bottom - 3
    roi = frame[upper:lower, left:right_edge]
    if roi.size == 0:
        return False, 0.0, 0.0

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    yellow_mask = (
        (hsv[:, :, 0] >= 12)
        & (hsv[:, :, 0] <= 40)
        & (hsv[:, :, 1] >= 80)
        & (hsv[:, :, 2] >= 100)
    )
    red_mask = (
        ((hsv[:, :, 0] <= 8) | (hsv[:, :, 0] >= 170))
        & (hsv[:, :, 1] >= 80)
        & (hsv[:, :, 2] >= 80)
    )
    yellow_ratio = float(yellow_mask.mean())
    red_ratio = float(red_mask.mean())
    return (
        yellow_ratio >= BONUS_ACTIVE_MIN_YELLOW_RATIO,
        yellow_ratio,
        red_ratio,
    )


def _bonus_control_click_rect(row_rect: Rect) -> Rect:
    _, top, right, bottom = row_rect
    return (
        right + 95,
        top + 6,
        min(1280, right + 140),
        bottom - 5,
    )


def _click_bonus_start_and_confirm(row_rect: Rect) -> bool:
    for attempt in range(1, MAX_STATE_CLICKS + 1):
        frame = _take_frame()
        if frame is None:
            continue
        score, start_rect = _bonus_start_match(frame, row_rect)
        if start_rect is None:
            print("御魂加成开始按钮已消失，加成已经开启")
            return True

        print(
            f"点击御魂加成开始按钮，第 {attempt}/{MAX_STATE_CLICKS} 次，"
            f"匹配分数 {score:.3f}"
        )
        _click_rect(start_rect, "开启御魂加成")
        time.sleep(SCREENSHOT_INTERVAL if attempt == 1 else 1.0)

        confirm_frame = _take_frame()
        if confirm_frame is None:
            continue
        _, confirmed_rect = _bonus_start_match(confirm_frame, row_rect)
        if confirmed_rect is None:
            print("御魂加成开始按钮已消失，加成开启成功")
            return True
        if attempt == 1:
            time.sleep(1.0)
            delayed_frame = _take_frame()
            if delayed_frame is not None:
                _, delayed_rect = _bonus_start_match(delayed_frame, row_rect)
                if delayed_rect is None:
                    print("延迟确认御魂加成已经开启")
                    return True

    print("[ERROR] 点击后御魂加成开始按钮仍然存在")
    return False


def _click_bonus_stop_and_confirm(row_rect: Rect) -> bool:
    for attempt in range(1, MAX_STATE_CLICKS + 1):
        frame = _take_frame()
        if frame is None:
            continue
        _, current_row = _match(frame, "soul_bonus")
        if current_row is None:
            print("御魂加成行已消失，加成面板已经关闭")
            return True
        active, yellow_ratio, red_ratio = _bonus_control_state(frame, current_row)
        if not active:
            print(
                "御魂加成计时条已恢复关闭状态，黄色/红色占比 "
                f"{yellow_ratio:.3f}/{red_ratio:.3f}"
            )
            return True

        print(
            f"点击御魂加成关闭按钮，第 {attempt}/{MAX_STATE_CLICKS} 次，"
            f"黄色/红色占比 {yellow_ratio:.3f}/{red_ratio:.3f}"
        )
        _click_rect(_bonus_control_click_rect(current_row), "关闭御魂加成")
        time.sleep(SCREENSHOT_INTERVAL if attempt == 1 else 1.0)

        confirm_frame = _take_frame()
        if confirm_frame is None:
            continue
        _, confirmed_row = _match(confirm_frame, "soul_bonus")
        if confirmed_row is None:
            print("御魂加成行已消失，加成关闭成功")
            return True
        confirmed_active, confirmed_yellow, confirmed_red = _bonus_control_state(
            confirm_frame,
            confirmed_row,
        )
        if not confirmed_active:
            print(
                "御魂加成计时条已恢复关闭状态，黄色/红色占比 "
                f"{confirmed_yellow:.3f}/{confirmed_red:.3f}"
            )
            return True
        if attempt == 1:
            time.sleep(1.0)
            delayed_frame = _take_frame()
            if delayed_frame is not None:
                _, delayed_row = _match(delayed_frame, "soul_bonus")
                if delayed_row is None:
                    print("延迟确认御魂加成行已消失")
                    return True
                delayed_active, delayed_yellow, delayed_red = _bonus_control_state(
                    delayed_frame,
                    delayed_row,
                )
                if not delayed_active:
                    print(
                        "延迟确认御魂加成已经关闭，黄色/红色占比 "
                        f"{delayed_yellow:.3f}/{delayed_red:.3f}"
                    )
                    return True

    print("[ERROR] 点击后御魂加成仍处于黄色计时状态")
    return False


def _random_swipe_bonus_list(swipe_index: int) -> None:
    start_x = random.randint(*BONUS_SWIPE_X_RANGE)
    start_y = random.randint(*BONUS_SWIPE_START_Y_RANGE)
    end_x = max(
        BONUS_SWIPE_X_RANGE[0],
        min(BONUS_SWIPE_X_RANGE[1], start_x + random.randint(-25, 25)),
    )
    end_y = random.randint(*BONUS_SWIPE_END_Y_RANGE)
    duration_ms = random.randint(*BONUS_SWIPE_DURATION_RANGE)
    LOGGER.message(
        "寻找御魂加成",
        f"第 {swipe_index}/{MAX_BONUS_SWIPES} 次随机滑动 "
        f"({start_x}, {start_y}) -> ({end_x}, {end_y})，"
        f"时长 {duration_ms}ms",
    )
    DEVICE.swipe(
        start_x,
        start_y,
        end_x,
        end_y,
        duration_ms=duration_ms,
    )
    time.sleep(random.uniform(0.7, 1.1))


def _dismiss_bonus_panel() -> bool:
    deadline = time.monotonic() + BONUS_DISMISS_WAIT_SECONDS
    last_frame = None
    clicks = 0
    best_score: Optional[float] = None

    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame
        score, row_rect = _match(frame, "soul_bonus")
        if score is not None and (best_score is None or score > best_score):
            best_score = score
        if row_rect is None:
            print("御魂加成行已消失，加成面板关闭成功")
            return True
        if clicks >= MAX_STATE_CLICKS:
            break

        clicks += 1
        side, blank_rect = random.choice(tuple(BONUS_PANEL_BLANK_AREAS.items()))
        print(
            f"点击加成框{side}空白区域关闭面板，"
            f"第 {clicks}/{MAX_STATE_CLICKS} 次"
        )
        _click_rect(blank_rect, f"关闭加成面板-{side}空白区域")
        time.sleep(SCREENSHOT_INTERVAL if clicks == 1 else 1.0)

    print(
        "[ERROR] 未能关闭加成面板，御魂加成行最高分 "
        f"{_score_text(best_score)}，已点击 {clicks} 次"
    )
    return False


def _enable_soul_bonus() -> bool:
    if not _open_bonus_panel():
        return False

    deadline = time.monotonic() + BONUS_WAIT_SECONDS
    last_frame = None
    best_score: Optional[float] = None
    swipes = 0

    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame
        score, row_rect = _match(frame, "soul_bonus")
        if score is not None and (best_score is None or score > best_score):
            best_score = score

        if row_rect is not None:
            print(f"识别到八岐大蛇御魂加成，匹配分数 {score:.3f}")
            start_score, start_rect = _bonus_start_match(frame, row_rect)
            if start_rect is None:
                print(
                    "御魂加成行已找到且开始按钮不存在，"
                    f"判定加成正在生效（按钮分数 {_score_text(start_score)}）"
                )
                return _dismiss_bonus_panel()
            if _click_bonus_start_and_confirm(row_rect):
                print("御魂加成已开启")
                return _dismiss_bonus_panel()
            break

        if swipes >= MAX_BONUS_SWIPES:
            break
        swipes += 1
        _random_swipe_bonus_list(swipes)

    print(
        "[ERROR] 未能开启八岐大蛇御魂加成，模板最高分 "
        f"{_score_text(best_score)}，已滑动 {swipes} 次"
    )
    return False


def _disable_soul_bonus() -> bool:
    if not _open_bonus_panel():
        return False

    deadline = time.monotonic() + BONUS_WAIT_SECONDS
    last_frame = None
    best_score: Optional[float] = None
    highest_yellow_ratio = 0.0
    swipes = 0

    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame
        score, row_rect = _match(frame, "soul_bonus")
        if score is not None and (best_score is None or score > best_score):
            best_score = score

        if row_rect is not None:
            print(f"识别到八岐大蛇御魂加成，匹配分数 {score:.3f}")
            active, yellow_ratio, red_ratio = _bonus_control_state(frame, row_rect)
            highest_yellow_ratio = max(highest_yellow_ratio, yellow_ratio)
            if active:
                print(
                    "御魂加成处于开启状态，黄色/红色占比 "
                    f"{yellow_ratio:.3f}/{red_ratio:.3f}"
                )
                if _click_bonus_stop_and_confirm(row_rect):
                    print("御魂加成已关闭")
                    return _dismiss_bonus_panel()
                break

            print(
                "御魂加成已经处于关闭状态，无需再次点击，"
                f"黄色/红色占比 {yellow_ratio:.3f}/{red_ratio:.3f}"
            )
            return _dismiss_bonus_panel()

        if swipes >= MAX_BONUS_SWIPES:
            break
        swipes += 1
        _random_swipe_bonus_list(swipes)

    print(
        "[ERROR] 未能关闭八岐大蛇御魂加成，加成行最高分/黄色最高占比 "
        f"{_score_text(best_score)}/{highest_yellow_ratio:.3f}，"
        f"已滑动 {swipes} 次"
    )
    return False


def _click_random_finish_side() -> None:
    side, rect = random.choice(tuple(FINISH_BLANK_AREAS.items()))
    left, top, right, bottom = rect
    x = random.randint(left, right)
    y = random.randint(top, bottom)
    LOGGER.click("战斗结算", f"{side}空白区域", rect, (x, y))
    DEVICE.click(x, y)


def _rapid_click_victory_transition() -> int:
    """在胜利过渡页右下角快速随机点击 2～3 次。"""
    click_count = random.randint(*VICTORY_TRANSITION_CLICK_COUNT)
    left, top, right, bottom = VICTORY_TRANSITION_CLICK_AREA
    print(f"快速跳过胜利过渡页，本次随机点击 {click_count} 次")
    for click_index in range(1, click_count + 1):
        x = random.randint(left, right)
        y = random.randint(top, bottom)
        LOGGER.click(
            "胜利过渡",
            f"右下角快速点击 {click_index}/{click_count}",
            VICTORY_TRANSITION_CLICK_AREA,
            (x, y),
        )
        DEVICE.click(x, y)
        if click_index < click_count:
            interval = random.uniform(*VICTORY_TRANSITION_CLICK_INTERVAL)
            print(f"快速点击间隔 {interval:.3f} 秒")
            time.sleep(interval)
    return click_count


def _try_reward_stall_recovery(frame) -> Optional[str]:
    """全屏检查两种交叉剑按钮，点击匹配分数最高的一个。"""
    best_match: Optional[tuple[float, Rect, str]] = None
    for name, label in REWARD_RECOVERY_BUTTONS:
        score, rect = _match(frame, name)
        if score is None or rect is None:
            continue
        if best_match is None or score > best_match[0]:
            best_match = (score, rect, label)

    if best_match is None:
        return None

    score, rect, label = best_match
    print(f"特殊恢复识别到{label}，全屏匹配分数 {score:.3f}，执行点击")
    _click_rect(rect, f"奖励未出现特殊恢复/{label}")
    return label


def collect_battle_rewards(
    initial_frame=None,
    timeout: Optional[float] = None,
) -> bool | str:
    """识别胜利过渡和奖励结算，快速跳过后返回御魂挑战页。"""
    previous_interval = utils.config.get("screenshot_speed", SCREENSHOT_INTERVAL)
    utils.config["screenshot_speed"] = BATTLE_SCREENSHOT_INTERVAL
    wait_seconds = BATTLE_WAIT_SECONDS if timeout is None else max(0.1, timeout)
    deadline = time.monotonic() + wait_seconds
    last_frame = None
    best_score: Optional[float] = None
    best_transition_score: Optional[float] = None
    transition_clicked = False
    transition_seen_at: Optional[float] = None
    win_seen = False
    reward_recovery_attempted = False
    reward_recovery_deadline: Optional[float] = None
    reward_cleared_at: Optional[float] = None
    post_reward_recovery_attempted = False
    post_reward_recovery_deadline: Optional[float] = None
    frame = initial_frame

    print(f"战斗进行中，每 {BATTLE_SCREENSHOT_INTERVAL:g} 秒检查一次胜利结算")
    try:
        while time.monotonic() < deadline:
            if frame is None:
                frame = _take_frame()
            if frame is None:
                continue
            last_frame = frame
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
                        "识别到协战胜利过渡页，"
                        f"匹配分数 {transition_score:.3f}"
                    )
                    _rapid_click_victory_transition()
                    transition_clicked = True
                    transition_seen_at = time.monotonic()

            score, rect = _match(frame, "win")
            if score is not None and (best_score is None or score > best_score):
                best_score = score

            if rect is not None:
                if not win_seen:
                    print(f"识别到协战胜利结算，匹配分数 {score:.3f}")
                    win_seen = True
                _click_random_finish_side()
                time.sleep(SCREENSHOT_INTERVAL)
                frame = None
                continue

            now = time.monotonic()
            if win_seen:
                challenge_score, challenge_rect = _match(frame, "challenge")
                if challenge_rect is not None:
                    print(
                        "奖励领取完成，已返回御魂挑战页，"
                        f"挑战按钮匹配分数 {challenge_score:.3f}"
                    )
                    return True

                if reward_cleared_at is None:
                    reward_cleared_at = now
                    print(
                        "胜利奖励模板已消失，等待返回御魂挑战页；"
                        f"超过 {REWARD_STALL_SECONDS:g} 秒将执行特殊恢复"
                    )

                if (
                    not post_reward_recovery_attempted
                    and now - reward_cleared_at >= REWARD_STALL_SECONDS
                ):
                    post_reward_recovery_attempted = True
                    print(
                        "[WARN] 奖励领取完成后仍未返回挑战页，"
                        "开始全屏检查特殊恢复按钮"
                    )
                    recovered_by = _try_reward_stall_recovery(frame)
                    if recovered_by is None:
                        print(
                            "[ERROR] 奖励领取后的特殊恢复未识别到"
                            "红色或粉色交叉剑按钮，"
                            "交由中控执行正常超时恢复"
                        )
                        return BATTLE_COMPLETED_RECOVERY_REQUIRED
                    post_reward_recovery_deadline = (
                        time.monotonic() + REWARD_RECOVERY_WAIT_SECONDS
                    )
                    print(
                        f"奖励领取后已点击{recovered_by}，最多再等待 "
                        f"{REWARD_RECOVERY_WAIT_SECONDS:g} 秒返回挑战页"
                    )

                if (
                    post_reward_recovery_deadline is not None
                    and time.monotonic() >= post_reward_recovery_deadline
                ):
                    print(
                        "[ERROR] 奖励领取后点击特殊恢复按钮，"
                        "仍未返回挑战页，交由中控执行正常超时恢复"
                    )
                    return BATTLE_COMPLETED_RECOVERY_REQUIRED

                frame = None
                time.sleep(SCREENSHOT_INTERVAL)
                continue

            if (
                transition_clicked
                and transition_seen_at is not None
                and not reward_recovery_attempted
                and now - transition_seen_at >= REWARD_STALL_SECONDS
            ):
                reward_recovery_attempted = True
                print(
                    "[WARN] 已识别到协战胜利，但 "
                    f"{REWARD_STALL_SECONDS:g} 秒仍未出现奖励，"
                    "开始全屏检查特殊恢复按钮"
                )
                recovered_by = _try_reward_stall_recovery(frame)
                if recovered_by is None:
                    print(
                        "[ERROR] 特殊恢复未识别到红色或粉色交叉剑按钮，"
                        "交由中控执行正常超时恢复"
                    )
                    return False
                reward_recovery_deadline = (
                    time.monotonic() + REWARD_RECOVERY_WAIT_SECONDS
                )
                print(
                    f"已点击{recovered_by}，最多再等待 "
                    f"{REWARD_RECOVERY_WAIT_SECONDS:g} 秒出现奖励"
                )

            if (
                reward_recovery_deadline is not None
                and time.monotonic() >= reward_recovery_deadline
            ):
                print(
                    "[ERROR] 点击特殊恢复按钮后仍未出现奖励，"
                    "交由中控执行正常超时恢复"
                )
                return False

            frame = None
            if transition_rect is not None:
                time.sleep(SCREENSHOT_INTERVAL)

        print(
            "[ERROR] 等待协战胜利超时，过渡页/奖励页最高分 "
            f"{_score_text(best_transition_score)}/{_score_text(best_score)}"
        )
        if win_seen:
            print(
                "[WARN] 本场奖励界面已经出现，战斗场次按完成记录，"
                "交由中控执行专属退场恢复"
            )
            return BATTLE_COMPLETED_RECOVERY_REQUIRED
        return False
    finally:
        utils.config["screenshot_speed"] = previous_interval


def _return_to_courtyard() -> bool:
    deadline = time.monotonic() + RETURN_WAIT_SECONDS
    last_frame = None
    best_main_score: Optional[float] = None
    best_back_score: Optional[float] = None
    back_clicked = False

    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame
        score, rect = _match(frame, "main")
        if score is not None and (
            best_main_score is None or score > best_main_score
        ):
            best_main_score = score
        if rect is not None:
            print(f"已返回庭院，探索灯笼匹配分数 {score:.3f}")
            return True

        if back_clicked:
            continue

        back_score, back_rect = _match(frame, "courtyard_back")
        if back_score is not None and (
            best_back_score is None or back_score > best_back_score
        ):
            best_back_score = back_score
        if back_rect is None:
            time.sleep(SCREENSHOT_INTERVAL)
            continue

        print(f"识别到左上角返回庭院按钮，匹配分数 {back_score:.3f}")
        remaining = max(0.1, deadline - time.monotonic())
        if not _click_and_confirm(
            "courtyard_back",
            "返回庭院",
            back_rect,
            remaining,
        ):
            return False
        back_clicked = True

    print(
        "[ERROR] 返回庭院超时，探索灯笼/返回庭院按钮最高分 "
        f"{_score_text(best_main_score)}/{_score_text(best_back_score)}"
    )
    return False


def _prepare_soul_dungeon() -> bool:
    """从庭院进入御魂十层 → 确认层数和锁阵 → 开启御魂加成。"""
    # 1. 逐页确认进入副本；恢复回庭院后也必须从探索入口重走。
    if not _wait_and_click(
        "main",
        "探索",
        ENTRY_WAIT_SECONDS,
        max_attempts=EXPLORE_MAX_ATTEMPTS,
    ):
        return False
    if not _wait_and_click("soul_entry", "御魂入口", ENTRY_WAIT_SECONDS):
        return False
    if not _wait_and_click("dungeon_card", "八岐大蛇副本", ENTRY_WAIT_SECONDS):
        return False
    # 2. 确认层数和锁阵后才开启加成，连续场次复用这组配置。
    if not _ensure_floor10_active():
        return False
    if not _ensure_formation_locked():
        return False
    if not _enable_soul_bonus():
        return False
    return True


def run(
    enable_bonus: bool = True,
    disable_bonus_after: bool = False,
) -> bool | str:
    """准备御魂十层 → 挑战并结算 → 最后一场关闭加成并退出。"""
    utils.connect_to_mumu()
    print("开始协战奖励任务")

    # 1. 首场或恢复后走完整准备；连续场次复用当前挑战页。
    if enable_bonus:
        if not _prepare_soul_dungeon():
            return False
    else:
        print("继续下一场挑战")

    # 2. 发起挑战并结算；已结算但退出失败必须保留专用状态，避免重打。
    if not _wait_and_click("challenge", "挑战", CHALLENGE_WAIT_SECONDS):
        return False
    battle_result = collect_battle_rewards()
    if battle_result == BATTLE_COMPLETED_RECOVERY_REQUIRED:
        print(
            "[WARN] 本场协战已经结算，但未能回到挑战页；"
            "保留本场进度并交由中控执行专属退场恢复"
        )
        return BATTLE_COMPLETED_RECOVERY_REQUIRED
    if not battle_result:
        return False

    # 3. 仅最后一场关闭加成并返回庭院；收尾失败交给中控恢复。
    if disable_bonus_after:
        if not _disable_soul_bonus():
            print(
                "[WARN] 本账号最后一场协战已经结算，但关闭加成失败；"
                "按任务完成但退场失败处理"
            )
            return BATTLE_COMPLETED_RECOVERY_REQUIRED
        if not _return_to_courtyard():
            print(
                "[WARN] 本账号最后一场协战已经结算，但返回庭院失败；"
                "按任务完成但退场失败处理"
            )
            return BATTLE_COMPLETED_RECOVERY_REQUIRED
        print("本账号协战场次全部完成，已关闭加成并返回庭院")
    else:
        print("本场协战完成，保留在御魂十层挑战页面")
    return True


if __name__ == "__main__":
    try:
        success = run()
    except KeyboardInterrupt:
        print("任务已由用户中止")
        success = False

    raise SystemExit(0 if success else 1)

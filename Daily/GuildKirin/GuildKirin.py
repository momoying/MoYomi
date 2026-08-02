"""寮麒麟：从主界面进入阴阳寮狩猎战，完成一次挑战并安全返回。"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path
from typing import Iterable, Optional, Tuple


SCRIPT_DIR = Path(__file__).resolve().parent
DAILY_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = DAILY_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Core import game_automation as utils
from Core.menu_fallback import try_open_activity_menu_once
from Core.task_logging import TaskLogger


LOGGER = TaskLogger("寮麒麟")
print = LOGGER.legacy_print


SCREENSHOT_INTERVAL = 0.5
utils.config["screenshot_speed"] = SCREENSHOT_INTERVAL

TEMPLATES = {
    "main": str(DAILY_DIR / "CoopReward" / "explore.png"),
    "guild_entry": str(SCRIPT_DIR / "guild_entry.png"),
    "menu_scroll": str(SCRIPT_DIR / "menu_scroll.png"),
    "hunting_entry": str(SCRIPT_DIR / "hunting_entry.png"),
    "challenge": str(SCRIPT_DIR / "challenge.png"),
    "already_challenged": str(SCRIPT_DIR / "already_challenged.png"),
    "prepare": str(SCRIPT_DIR / "prepare.png"),
    "win": str(SCRIPT_DIR / "win.png"),
    "defeat": str(SCRIPT_DIR / "defeat.png"),
    "hunt_back": str(SCRIPT_DIR / "hunt_back.png"),
    "guild_back": str(SCRIPT_DIR / "guild_back.png"),
}

REGIONS = {
    "main": ((500, 80), (800, 280)),
    "guild_entry": ((450, 560), (680, 720)),
    "menu_scroll": ((1100, 540), (1280, 720)),
    "hunting_entry": ((0, 210), (260, 350)),
    "challenge": ((1040, 500), (1280, 720)),
    "already_challenged": ((1040, 500), (1280, 720)),
    "prepare": ((1040, 480), (1280, 720)),
    "win": ((200, 20), (1050, 380)),
    "defeat": ((250, 0), (700, 350)),
    "hunt_back": ((0, 0), (130, 110)),
    "guild_back": ((0, 0), (130, 110)),
}

MATCH_THRESHOLDS = {
    "main": 0.80,
    "guild_entry": 0.80,
    "menu_scroll": 0.80,
    "hunting_entry": 0.82,
    "challenge": 0.82,
    "already_challenged": 0.82,
    "prepare": 0.82,
    "win": 0.82,
    # 使用失败结算左侧的灰色鼓面和固定云纹，不依赖右侧角色位置。
    "defeat": 0.75,
    "hunt_back": 0.80,
    "guild_back": 0.80,
}

MENU_WAIT_SECONDS = 12.0
PAGE_WAIT_SECONDS = 20.0
PREPARE_WAIT_SECONDS = 30.0
BATTLE_WAIT_SECONDS = 200.0
BATTLE_CHECK_INTERVAL_SECONDS = 3.0
ACTION_CONFIRM_SECONDS = 12.0
RETURN_WAIT_SECONDS = 20.0

FAILURE_BLANK_AREAS = {
    "左侧": (20, 300, 180, 650),
    "右侧": (1100, 300, 1260, 650),
}

VICTORY_BLANK_AREAS = {
    "左下": (40, 560, 320, 680),
    "右下": (960, 560, 1240, 680),
}

Rect = Tuple[int, int, int, int]


def _match(frame, name: str) -> Tuple[Optional[float], Optional[Rect]]:
    top_left, bottom_right = REGIONS[name]
    score, rect = utils.crop_and_match(
        top_left,
        bottom_right,
        TEMPLATES[name],
        frame=frame,
    )
    threshold = MATCH_THRESHOLDS[name]
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


def _take_frame():
    frame = utils.take_screenshot()
    if frame is None:
        print("[WARN] 寮麒麟截图失败，等待下一帧")
        time.sleep(SCREENSHOT_INTERVAL)
    return frame


def _click_rect(rect: Rect, label: str) -> None:
    left, top, right, bottom = rect
    margin_x = max(1, (right - left) // 4)
    margin_y = max(1, (bottom - top) // 4)
    x = random.randint(left + margin_x, right - margin_x)
    y = random.randint(top + margin_y, bottom - margin_y)
    LOGGER.click(label, label, rect, (x, y))
    utils.adb_click(x, y)


def _click_and_confirm(name: str, label: str, rect: Rect, timeout: float) -> bool:
    top_left, bottom_right = REGIONS[name]
    return utils.click_template_until_disappears(
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


def _wait_for_any(
    names: Iterable[str],
    timeout: float,
) -> Tuple[Optional[object], Optional[str], Optional[Rect], Optional[float]]:
    names = tuple(names)
    deadline = time.monotonic() + timeout
    best_scores: dict[str, Optional[float]] = {name: None for name in names}
    last_frame = None

    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame
        for name in names:
            score, rect = _match(frame, name)
            if score is not None and (
                best_scores[name] is None or score > best_scores[name]
            ):
                best_scores[name] = score
            if rect is not None:
                return frame, name, rect, score

    details = "，".join(
        f"{name} {'无' if score is None else f'{score:.3f}'}"
        for name, score in best_scores.items()
    )
    print(f"[ERROR] {timeout:.0f} 秒内未识别到目标模板：{details}")
    return last_frame, None, None, None


def _wait_and_click(name: str, label: str, timeout: float) -> bool:
    _, matched_name, rect, score = _wait_for_any((name,), timeout)
    if matched_name is None or rect is None:
        return False
    print(f"识别到{label}，匹配分数 {score:.3f}")
    if not _click_and_confirm(name, label, rect, timeout):
        return False
    return True


def _ensure_guild_menu_expanded() -> bool:
    deadline = time.monotonic() + MENU_WAIT_SECONDS
    last_frame = None
    fallback_clicked = False

    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame
        guild_score, guild_rect = _match(frame, "guild_entry")
        if guild_rect is not None:
            print(f"阴阳寮入口已显示，匹配分数 {guild_score:.3f}")
            return True

        scroll_score, scroll_rect = _match(frame, "menu_scroll")
        if scroll_rect is not None:
            print(f"功能栏未展开，识别到卷轴 {scroll_score:.3f}")
            remaining = max(0.1, deadline - time.monotonic())
            if _click_and_confirm(
                "menu_scroll",
                "展开功能栏卷轴",
                scroll_rect,
                remaining,
            ):
                continue
            return False

        if not fallback_clicked and try_open_activity_menu_once(frame, LOGGER):
            fallback_clicked = True
            print("未识别到普通卷轴，已在庭院点击一次活动菜单共有区域")
            time.sleep(SCREENSHOT_INTERVAL)
            continue

    print("[ERROR] 未识别到阴阳寮入口、菜单卷轴或活动菜单")
    return False


def _wait_for_hunting_status() -> Optional[str]:
    _, name, _, score = _wait_for_any(
        ("already_challenged", "challenge"),
        PAGE_WAIT_SECONDS,
    )
    if name is None:
        return None
    label = "已挑战" if name == "already_challenged" else "挑战"
    print(f"狩猎战状态：{label}，匹配分数 {score:.3f}")
    return name


def _wait_for_battle_result() -> Optional[Tuple[str, Rect]]:
    deadline = time.monotonic() + BATTLE_WAIT_SECONDS
    last_frame = None
    best_scores: dict[str, Optional[float]] = {
        "win": None,
        "defeat": None,
    }
    print("寮麒麟战斗进行中，每 3 秒检查一次胜利或失败结算，最长等待 200 秒")

    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame
        for name, label in (("win", "胜利"), ("defeat", "失败")):
            score, rect = _match(frame, name)
            if score is not None and (
                best_scores[name] is None or score > best_scores[name]
            ):
                best_scores[name] = score
            if rect is not None:
                print(f"识别到寮麒麟战斗{label}，匹配分数 {score:.3f}")
                return name, rect
        time.sleep(BATTLE_CHECK_INTERVAL_SECONDS)

    details = "，".join(
        f"{name} {'无' if score is None else f'{score:.3f}'}"
        for name, score in best_scores.items()
    )
    print(f"[ERROR] 准备后 200 秒内未识别到寮麒麟结算：{details}")
    return None


def _close_battle_result(result_name: str, result_rect: Rect) -> bool:
    def click_random_side(_current_rect: Rect) -> None:
        areas = (
            VICTORY_BLANK_AREAS
            if result_name == "win"
            else FAILURE_BLANK_AREAS
        )
        side, region = random.choice(tuple(areas.items()))
        label = "胜利" if result_name == "win" else "失败"
        _click_rect(region, f"{label}结算{side}空白区域")

    top_left, bottom_right = REGIONS[result_name]
    label = "胜利" if result_name == "win" else "失败"
    return utils.click_template_until_disappears(
        top_left,
        bottom_right,
        TEMPLATES[result_name],
        result_rect,
        threshold=MATCH_THRESHOLDS[result_name],
        timeout=ACTION_CONFIRM_SECONDS,
        label=f"寮麒麟{label}结算",
        click_callback=click_random_side,
        log_callback=lambda message: LOGGER.message(f"{label}结算", message),
    )


def _click_back_once_and_wait(
    back_name: str,
    back_label: str,
    next_names: Iterable[str],
) -> bool:
    _, _, back_rect, score = _wait_for_any((back_name,), PAGE_WAIT_SECONDS)
    if back_rect is None:
        return False
    print(f"识别到{back_label}，匹配分数 {score:.3f}，只点击一次")
    _click_rect(back_rect, back_label)
    time.sleep(SCREENSHOT_INTERVAL)
    _, next_name, _, next_score = _wait_for_any(next_names, RETURN_WAIT_SECONDS)
    if next_name is None:
        return False
    print(f"{back_label}生效，分数 {next_score:.3f}")
    return True


def _return_to_main() -> bool:
    if not _click_back_once_and_wait(
        "hunt_back",
        "狩猎战退出",
        ("hunting_entry",),
    ):
        return False
    return _click_back_once_and_wait(
        "guild_back",
        "阴阳寮退出",
        ("main", "guild_entry", "menu_scroll"),
    )


def run() -> bool:
    utils.connect_to_mumu()
    print("开始寮麒麟任务")

    if not _ensure_guild_menu_expanded():
        return False
    if not _wait_and_click("guild_entry", "阴阳寮", PAGE_WAIT_SECONDS):
        return False
    if not _wait_and_click("hunting_entry", "狩猎战", PAGE_WAIT_SECONDS):
        return False

    status = _wait_for_hunting_status()
    if status is None:
        return False

    if status == "challenge":
        if not _wait_and_click("challenge", "挑战", PAGE_WAIT_SECONDS):
            return False
        if not _wait_and_click("prepare", "准备", PREPARE_WAIT_SECONDS):
            return False
        battle_result = _wait_for_battle_result()
        if battle_result is None:
            return False
        result_name, result_rect = battle_result
        if not _close_battle_result(result_name, result_rect):
            return False
        if _wait_for_hunting_status() != "already_challenged":
            print("[ERROR] 战斗结算后未确认已挑战状态")
            return False
    else:
        print("当前寮麒麟已经挑战过，跳过战斗")

    if not _return_to_main():
        return False
    print("寮麒麟任务完成，已返回主界面")
    return True


if __name__ == "__main__":
    try:
        success = run()
    except KeyboardInterrupt:
        print("寮麒麟任务已由用户中止")
        success = False
    raise SystemExit(0 if success else 1)

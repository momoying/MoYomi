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

from module import automation as utils
from module.base.device import TaskDevice
from module.menu import try_open_activity_menu_once
from module.logging import TaskLogger


from tasks.GuildKirin.assets import GuildKirinAssets

ASSETS = GuildKirinAssets
TEMPLATES = ASSETS.TEMPLATES
REGIONS = ASSETS.REGIONS
MATCH_THRESHOLDS = ASSETS.MATCH_THRESHOLDS
FAILURE_BLANK_AREAS = ASSETS.FAILURE_BLANK_AREAS
VICTORY_BLANK_AREAS = ASSETS.VICTORY_BLANK_AREAS

LOGGER = TaskLogger("寮麒麟")
DEVICE = TaskDevice(utils, LOGGER)
print = LOGGER.legacy_print


SCREENSHOT_INTERVAL = 0.5
utils.config["screenshot_speed"] = SCREENSHOT_INTERVAL




MENU_WAIT_SECONDS = 12.0
PAGE_WAIT_SECONDS = 20.0
PREPARE_WAIT_SECONDS = 30.0
BATTLE_WAIT_SECONDS = 200.0
BATTLE_CHECK_INTERVAL_SECONDS = 3.0
ACTION_CONFIRM_SECONDS = 12.0
RETURN_WAIT_SECONDS = 20.0



Rect = Tuple[int, int, int, int]


def _match(frame, name: str) -> Tuple[Optional[float], Optional[Rect]]:
    top_left, bottom_right = REGIONS[name]
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
        name,
        name,
        score,
        threshold,
        rect,
        search_region=(top_left[0], top_left[1], bottom_right[0], bottom_right[1]),
    )
    return score, rect


def _take_frame():
    frame = DEVICE.screenshot()
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
    return DEVICE.click_until_disappears(
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


def _challenge_and_confirm_completion() -> bool:
    """挑战并准备 → 等待战斗结算 → 关闭结果 → 复核已挑战标志。"""
    # 1. 挑战和准备逐步确认，进入战斗后等待胜负结果。
    if not _wait_and_click("challenge", "挑战", PAGE_WAIT_SECONDS):
        return False
    if not _wait_and_click("prepare", "准备", PREPARE_WAIT_SECONDS):
        return False
    battle_result = _wait_for_battle_result()
    if battle_result is None:
        return False
    # 2. 关闭结算并复核狩猎页，不能仅凭战斗结果窗口报告任务完成。
    result_name, result_rect = battle_result
    if not _close_battle_result(result_name, result_rect):
        return False
    if _wait_for_hunting_status() != "already_challenged":
        print("[ERROR] 战斗结算后未确认已挑战状态")
        return False
    return True


def run() -> bool:
    """进入狩猎战 → 按需挑战并确认完成 → 返回庭院。"""
    utils.connect_to_mumu()
    print("开始寮麒麟任务")

    # 1. 从庭院展开阴阳寮入口，逐页进入狩猎战。
    if not _ensure_guild_menu_expanded():
        return False
    if not _wait_and_click("guild_entry", "阴阳寮", PAGE_WAIT_SECONDS):
        return False
    if not _wait_and_click("hunting_entry", "狩猎战", PAGE_WAIT_SECONDS):
        return False

    # 2. 已挑战则跳过战斗；识别失败仍按失败处理。
    status = _wait_for_hunting_status()
    if status is None:
        return False

    if status == "challenge":
        if not _challenge_and_confirm_completion():
            return False
    else:
        print("当前寮麒麟已经挑战过，跳过战斗")

    # 3. 无论本次是否战斗，都确认回到主界面后才报告成功。
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

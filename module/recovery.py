"""任务超时恢复：从未知任务页面逐步返回庭院。"""

from __future__ import annotations

import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import cv2


CORE_DIR = Path(__file__).resolve().parent
HELPER_DIR = CORE_DIR.parent
PROJECT_ROOT = HELPER_DIR
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from module import automation as utils
from module.base.device import TaskDevice
from module.assets import RecoveryAssets, RecoveryMatchSpec as MatchSpec, StartupAssets
from module.diagnostics import capture_error_screenshot, prune_error_screenshots
from module.logging import TaskLogger


ASSETS = RecoveryAssets
MATCH_THRESHOLD = ASSETS.MATCH_THRESHOLD
FULL_SCREEN = ASSETS.FULL_SCREEN
COURTYARD_REGION = ASSETS.COURTYARD_REGION
COURTYARD_TEMPLATE = ASSETS.COURTYARD_TEMPLATE
COOP_REWARD_TEMPLATE = ASSETS.COOP_REWARD_TEMPLATE
COOP_REWARD_SAFE_AREAS = ASSETS.COOP_REWARD_SAFE_AREAS
ACTION_SPECS = ASSETS.ACTION_SPECS
LOGGER = TaskLogger("超时恢复")
DEVICE = TaskDevice(utils, LOGGER)
print = LOGGER.legacy_print

SCREENSHOT_INTERVAL = 0.8
UNKNOWN_STATE_GRACE_SECONDS = 10.0
RECOVERY_TIMEOUT_SECONDS = 90.0
SCREENSHOT_KEEP_COUNT = 20
POST_CLICK_DELAY_SECONDS = 1.2
MAX_STALLED_CLICKS = 3
MAX_RECOVERY_ACTIONS = 12

OVERLAY_STATES = (
    "room_exit_confirm", "heart_exit_confirm", "phone_bind_cancel",
    "phone_bind", "sign_in_close",
)
ACCOUNT_STATES = ("login", "account_list", "ios", "android")
ROOM_STATES = ("prepare_button", "ready_room")
PAGE_STATES = (
    "main", *ROOM_STATES, "coop_challenge", "coop_dungeon_card",
    "coop_soul_entry", "merchant_page", "merchant_town", "merchant_popular",
)
# daily_back 是通用左上角箭头，在麒麟挑战页也会命中，不能单独证明页面身份。
DIRECT_CLOSE_STATES = ("friend_close", "bounty_close")
RETURN_STATES = {
    "coop_challenge", "coop_dungeon_card", "coop_soul_entry",
    "merchant_page", "merchant_town", "merchant_popular",
}
UNKNOWN_ACTION_REGIONS = {
    "courtyard": StartupAssets.I_COURTYARD_BACK.region,
    "back": StartupAssets.I_EXP_BACK.region,
    "close_pink": FULL_SCREEN,
    "close_red": FULL_SCREEN,
}

Rect = Tuple[int, int, int, int]


@dataclass(frozen=True)
class RecoveryResult:
    success: bool
    reason: str
    screenshot: Optional[str] = None


@dataclass(frozen=True)
class _RecoveryAttempt:
    """恢复决策的结果；现场留图由外层策略处理。"""

    success: bool
    reason: str
    frame: object = None
    failure_code: Optional[str] = None



# 仅已记录完成的协战收尾可点奖励安全区；已知页面的通用按钮沿用原优先级。


def _match(
    frame,
    name: str,
    spec: MatchSpec,
    region=FULL_SCREEN,
) -> tuple[Optional[float], Optional[Rect]]:
    score, rect = DEVICE.match(
        region[0],
        region[1],
        str(spec.path),
        frame=frame,
    )
    if score is None or rect is None or score < spec.threshold:
        return score, None
    LOGGER.match(
        name,
        spec.path.stem,
        score,
        spec.threshold,
        rect,
        search_region=(
            region[0][0],
            region[0][1],
            region[1][0],
            region[1][1],
        ),
    )
    return score, rect


def _is_courtyard(frame) -> bool:
    spec = MatchSpec(COURTYARD_TEMPLATE, "庭院探索灯笼")
    _, rect = _match(frame, "庭院首页", spec, COURTYARD_REGION)
    return rect is not None


def _match_state(frame, name: str) -> tuple[Optional[float], Optional[Rect]]:
    """复用启动恢复的页面模板与搜索区域。"""
    if name in StartupAssets.SPECS:
        state = StartupAssets.SPECS[name]
        return _match(frame, name, MatchSpec(state.path, name, state.threshold), state.region)
    asset = RecoveryAssets.image(name)
    return _match(frame, name, MatchSpec(asset.file, name, asset.threshold), asset.region)


def _detect_state(frame) -> tuple[str, Optional[float], Optional[Rect]]:
    """危险状态先于弹窗；底层页面命中冲突时停止猜测。"""
    for name in ("settlement", "coop_settlement", "coop_reward", "battle"):
        score, rect = _match_state(frame, name)
        if rect is not None:
            return ("coop_reward" if name == "coop_settlement" else name), score, rect

    overlays = [(name, *(_match_state(frame, name))) for name in OVERLAY_STATES]
    overlays = [(name, score, rect) for name, score, rect in overlays if rect is not None]
    if overlays:
        # 手机绑定的两个按钮可能同时出现，先取消当前引导。
        if {name for name, _, _ in overlays} <= {"phone_bind", "phone_bind_cancel"}:
            return next((entry for entry in overlays if entry[0] == "phone_bind_cancel"), overlays[0])
        return overlays[0] if len(overlays) == 1 else ("ambiguous_overlay", None, None)

    for name in ACCOUNT_STATES:
        score, rect = _match_state(frame, name)
        if rect is not None:
            return name, score, rect

    pages = [(name, *(_match_state(frame, name))) for name in PAGE_STATES]
    pages = [(name, score, rect) for name, score, rect in pages if rect is not None]
    # 准备按钮和房间标记可能同时出现，属于同一个准备房。
    if len(pages) > 1 and {entry[0] for entry in pages} <= set(ROOM_STATES):
        return pages[0]
    if len(pages) > 1:
        return "ambiguous", None, None
    if pages:
        if pages[0][0] == "main":
            close_buttons = [(name, *(_match_state(frame, name))) for name in DIRECT_CLOSE_STATES]
            close_buttons = [entry for entry in close_buttons if entry[2] is not None]
            if len(close_buttons) > 1:
                return "ambiguous", None, None
            if close_buttons:
                return close_buttons[0]
        return pages[0]
    close_buttons = [(name, *(_match_state(frame, name))) for name in DIRECT_CLOSE_STATES]
    close_buttons = [(name, score, rect) for name, score, rect in close_buttons if rect is not None]
    if len(close_buttons) > 1:
        return "ambiguous", None, None
    if close_buttons:
        return close_buttons[0]
    return "unknown", None, None


def _same_view(previous, current) -> bool:
    """忽略轻微画面动画，判断重复点击后页面是否仍停在原处。"""
    if not hasattr(previous, "shape") or not hasattr(current, "shape"):
        return False
    if previous.shape != current.shape:
        return False
    before = cv2.resize(previous, (64, 36))
    after = cv2.resize(current, (64, 36))
    return all(value < 3.0 for value in cv2.mean(cv2.absdiff(before, after))[:3])


def find_highest_priority_action(
    frame,
    allowed: set[str] | None = None,
) -> tuple[Optional[str], Optional[MatchSpec], Optional[float], Optional[Rect]]:
    """仅在已确认页面内，按原有优先级选取允许的操作。"""
    for name, spec in ACTION_SPECS:
        if allowed is not None and name not in allowed:
            continue
        score, rect = _match(frame, name, spec)
        if rect is not None:
            return name, spec, score, rect
    return None, None, None, None


def find_unknown_action(
    frame,
) -> tuple[Optional[str], Optional[MatchSpec], Optional[float], Optional[Rect]]:
    """未知页只尝试旧恢复图片中的返回、关闭按钮。"""
    for name, spec in ACTION_SPECS:
        if name not in UNKNOWN_ACTION_REGIONS:
            continue
        score, rect = _match(frame, name, spec, UNKNOWN_ACTION_REGIONS[name])
        if rect is not None:
            return name, spec, score, rect
    return None, None, None, None


def _stable_unknown_action(first, second):
    before = find_unknown_action(first)
    after = find_unknown_action(second)
    before_rect, after_rect = before[3], after[3]
    if (
        before[0] is not None
        and before[0] == after[0]
        and before_rect is not None
        and after_rect is not None
        and max(abs(a - b) for a, b in zip(before_rect, after_rect)) <= 12
    ):
        return after
    return None


def _click_rect(rect: Rect, label: str) -> None:
    left, top, right, bottom = rect
    margin_x = max(1, (right - left) // 4)
    margin_y = max(1, (bottom - top) // 4)
    x = random.randint(left + margin_x, right - margin_x)
    y = random.randint(top + margin_y, bottom - margin_y)
    LOGGER.click(label, label, rect, (x, y))
    DEVICE.click(x, y)


def _click_coop_reward_safe_area(score: float) -> None:
    side, rect = random.choice(tuple(COOP_REWARD_SAFE_AREAS.items()))
    LOGGER.info(
        "协战奖励",
        f"识别到协战奖励袋，匹配分数 {score:.3f}，点击{side}安全区领取",
    )
    _click_rect(rect, f"协战奖励/{side}安全区")


def prune_failure_screenshots(keep_count: int = SCREENSHOT_KEEP_COUNT) -> int:
    """兼容旧调用：清理统一报错截图目录。"""
    return prune_error_screenshots(keep_count)


def _save_failure_screenshot(
    frame,
    stage: str,
    keep_count: int,
) -> Optional[str]:
    return capture_error_screenshot(
        "task_recovery",
        stage,
        frame=frame,
        keep_count=keep_count,
    )


def _attempt_recovery_to_courtyard(
    stop_event=None,
    *,
    timeout: float = RECOVERY_TIMEOUT_SECONDS,
    unknown_grace: float = UNKNOWN_STATE_GRACE_SECONDS,
    allow_completed_reward: bool = False,
) -> _RecoveryAttempt:
    """识别并复核当前页面，每轮最多执行一次该页面允许的动作。"""
    deadline = time.monotonic() + timeout
    unknown_since: Optional[float] = None
    last_frame = None
    click_count = 0
    last_action_name = None
    last_action_frame = None
    stalled_clicks = 0
    pending_frame = None
    room_confirm_since: Optional[float] = None
    LOGGER.info("运行", "开始按页面状态执行任务超时恢复")

    def stopped() -> bool:
        return stop_event is not None and stop_event.is_set()

    def wait(seconds: float) -> None:
        remaining = deadline - time.monotonic()
        if not stopped() and remaining > 0:
            delay = min(seconds, remaining)
            if stop_event is None:
                time.sleep(delay)
            else:
                stop_event.wait(delay)

    def blocked(frame, code: str, reason: str) -> _RecoveryAttempt:
        LOGGER.error("运行", reason)
        return _RecoveryAttempt(False, reason, frame, code)

    while time.monotonic() < deadline:
        if stopped():
            return _RecoveryAttempt(False, "用户请求停止，已取消超时恢复")

        frame = pending_frame
        pending_frame = None
        if frame is None:
            frame = DEVICE.screenshot()
        if frame is None:
            if unknown_since is None:
                unknown_since = time.monotonic()
            if time.monotonic() - unknown_since >= unknown_grace:
                return blocked(last_frame, "screenshot_failed", "连续无法获取游戏截图，超时恢复终止")
            wait(SCREENSHOT_INTERVAL)
            continue

        last_frame = frame
        state, score, rect = _detect_state(frame)
        if state == "ambiguous_overlay":
            return blocked(frame, "ambiguous_overlay", "同时识别到不同弹窗，超时恢复终止")
        if state in {"unknown", "ambiguous"}:
            if unknown_since is None:
                unknown_since = time.monotonic()
                LOGGER.info("等待界面", "页面无法确定，复核返回庭院、返回和关闭按钮")
        else:
            unknown_since = None
        # 第二张截图复核当前状态；变化中不点击，将新画面交给下一轮。
        if stopped() or time.monotonic() >= deadline:
            break
        confirmed = DEVICE.screenshot()
        if confirmed is None:
            wait(SCREENSHOT_INTERVAL)
            continue
        last_frame = confirmed
        confirmed_state, confirmed_score, confirmed_rect = _detect_state(confirmed)
        if state != confirmed_state:
            pending_frame = confirmed
            wait(SCREENSHOT_INTERVAL)
            continue
        score, rect = confirmed_score, confirmed_rect

        if state in {"settlement", "coop_reward"} and not (
            state == "coop_reward" and allow_completed_reward
        ):
            return blocked(confirmed, "settlement_unrecorded", "检测到未记录完成的结算，留图停止以免重复记账")
        if state in ACCOUNT_STATES:
            return blocked(confirmed, "account_page", f"检测到{state}页面，无法作为庭院恢复成功")
        if state == "battle":
            wait(SCREENSHOT_INTERVAL)
            continue
        if state in ROOM_STATES and room_confirm_since is not None:
            if time.monotonic() - room_confirm_since >= unknown_grace:
                return blocked(confirmed, "room_exit_confirm_missing", "已点击准备房返回，但未出现退出确认弹窗")
            wait(SCREENSHOT_INTERVAL)
            continue
        if state not in ROOM_STATES:
            room_confirm_since = None

        fallback_action = None
        if state == "main":
            # 有未归类的按钮覆盖时不把底层庭院误判为完成。
            button, _, _, _ = find_highest_priority_action(confirmed)
            if button is None:
                reason = f"已恢复到庭院，共点击 {click_count} 次"
                LOGGER.info("运行", f"[SUCCESS] {reason}")
                return _RecoveryAttempt(True, reason)
            fallback_action = _stable_unknown_action(frame, confirmed)
            if fallback_action is None:
                return blocked(confirmed, "courtyard_obstructed", f"庭院上仍识别到{button}按钮，无法确认已安全返回")

        if state in {"unknown", "ambiguous"}:
            fallback_action = _stable_unknown_action(frame, confirmed)
            if fallback_action is None and time.monotonic() - unknown_since < unknown_grace:
                wait(SCREENSHOT_INTERVAL)
                continue
            if fallback_action is None:
                return blocked(confirmed, state, f"连续 {unknown_grace:.0f} 秒无法确认页面或稳定的返回、关闭按钮，超时恢复终止")

        if click_count >= MAX_RECOVERY_ACTIONS:
            return blocked(confirmed, "action_limit", f"已执行 {MAX_RECOVERY_ACTIONS} 次恢复动作，仍未回到庭院")

        action_name = state
        action_score = score
        action_rect = rect
        use_back = False
        if fallback_action is not None:
            action_name, _, action_score, action_rect = fallback_action
        elif state in ROOM_STATES:
            action_name = "exp_back"
            action_score, action_rect = _match_state(confirmed, "exp_back")
            if action_rect is None:
                room_fallback = _stable_unknown_action(frame, confirmed)
                if room_fallback is None:
                    return blocked(confirmed, "room_back_missing", "检测到准备房但未找到返回按钮")
                action_name, _, action_score, action_rect = room_fallback
        elif state in RETURN_STATES:
            action_name, _, action_score, action_rect = find_highest_priority_action(
                confirmed, {"courtyard", "back", "close_pink", "close_red"}
            )
            if action_rect is None:
                action_name = f"{state}/android_back"
                use_back = True
        elif state == "coop_reward":
            action_name = "coop_reward"
        elif state not in OVERLAY_STATES and state not in DIRECT_CLOSE_STATES:
            pending_frame = confirmed
            wait(SCREENSHOT_INTERVAL)
            continue

        if action_name == last_action_name and _same_view(last_action_frame, confirmed):
            stalled_clicks += 1
        else:
            stalled_clicks = 0
        if stalled_clicks >= MAX_STALLED_CLICKS:
            return blocked(confirmed, "stalled", f"连续 {MAX_STALLED_CLICKS} 次执行{action_name}后界面未变化，超时恢复终止")
        if stopped() or time.monotonic() >= deadline:
            break
        if use_back:
            if not DEVICE.back():
                return blocked(confirmed, "back_failed", f"{state}页面返回失败")
        elif state == "coop_reward":
            _click_coop_reward_safe_area(score)
        else:
            _click_rect(action_rect, f"{action_name}（匹配分数 {action_score:.3f}）")
        click_count += 1
        if state in {"unknown", "ambiguous"}:
            unknown_since = None
        if state in ROOM_STATES:
            room_confirm_since = time.monotonic()
        last_action_name = action_name
        last_action_frame = confirmed.copy() if hasattr(confirmed, "copy") else confirmed
        wait(POST_CLICK_DELAY_SECONDS)

    if stopped():
        return _RecoveryAttempt(False, "用户请求停止，已取消超时恢复")
    return blocked(last_frame, "timeout", f"超时恢复运行超过 {timeout:.0f} 秒，仍未回到庭院")


def recover_to_courtyard(
    stop_event=None,
    *,
    timeout: float = RECOVERY_TIMEOUT_SECONDS,
    unknown_grace: float = UNKNOWN_STATE_GRACE_SECONDS,
    screenshot_keep_count: int = SCREENSHOT_KEEP_COUNT,
    allow_completed_reward: bool = False,
) -> RecoveryResult:
    """执行恢复；失败现场按统一截图策略保存，不参与恢复判断。"""
    attempt = _attempt_recovery_to_courtyard(
        stop_event=stop_event,
        timeout=timeout,
        unknown_grace=unknown_grace,
        allow_completed_reward=allow_completed_reward,
    )
    screenshot = None
    if attempt.failure_code is not None:
        try:
            screenshot = _save_failure_screenshot(
                attempt.frame, attempt.failure_code, screenshot_keep_count
            )
        except Exception as exc:
            LOGGER.warning("留图", f"保存恢复失败现场出错：{exc}")
    return RecoveryResult(attempt.success, attempt.reason, screenshot)


if __name__ == "__main__":
    result = recover_to_courtyard()
    raise SystemExit(0 if result.success else 1)

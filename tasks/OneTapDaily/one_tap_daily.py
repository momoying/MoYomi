"""阴阳师一键日常任务：打开任务列表并点击“一键完成”。"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

import cv2


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from module import automation as utils
from module.base.device import TaskDevice
from module.logging import TaskLogger


from tasks.OneTapDaily.assets import OneTapDailyAssets

ASSETS = OneTapDailyAssets
TEMPLATES = ASSETS.TEMPLATES
REGIONS = ASSETS.REGIONS
MATCH_THRESHOLD = ASSETS.MATCH_THRESHOLD
BACK_MIN_SATURATION_RATIO = ASSETS.BACK_MIN_SATURATION_RATIO
BACK_MIN_BRIGHTNESS_RATIO = ASSETS.BACK_MIN_BRIGHTNESS_RATIO
REWARD_OUTSIDE_RIGHT_REGIONS = ASSETS.REWARD_OUTSIDE_RIGHT_REGIONS
DAILY_TAB_CLICK_REGION = ASSETS.DAILY_TAB_CLICK_REGION

LOGGER = TaskLogger("一键日常")
DEVICE = TaskDevice(utils, LOGGER)
print = LOGGER.legacy_print


SCREENSHOT_INTERVAL = 0.5
utils.config["screenshot_speed"] = SCREENSHOT_INTERVAL


MAIN_WAIT_SECONDS = 20.0
ONE_TAP_WAIT_SECONDS = 10.0
ONE_TAP_MAX_CLICKS = 3
MAX_CLAIM_ROUNDS = 2
POST_ONE_TAP_TIMEOUT_SECONDS = 20.0
COMPLETION_VERIFY_SECONDS = 4.0
STATE_CONFIRM_SECONDS = 12.0
REWARD_CONFIRM_SECONDS = 12.0
REWARD_READY_DELAY_SECONDS = 2.0
REWARD_RETRY_DELAY_SECONDS = 3.0
POST_ACTION_DELAY_SECONDS = 1.0
MAX_BACK_CLICKS = 3

# “领取成功”奖励册外侧、屏幕最右边的空白区。旧范围在奖励册右页
# 内部（x 约 850～930），游戏不会把那里当作关闭弹窗的外部区域。
# 进入庭院事务后偶尔默认停在“特殊”页，点击右上“日常”标签切换。

Rect = Tuple[int, int, int, int]


def _match(frame, name: str) -> Tuple[Optional[float], Optional[Rect]]:
    top_left, bottom_right = REGIONS[name]
    score, rect = DEVICE.match(
        top_left,
        bottom_right,
        TEMPLATES[name],
        frame=frame,
    )
    if score is None or rect is None or score < MATCH_THRESHOLD:
        return score, None
    LOGGER.match(
        name,
        name,
        score,
        MATCH_THRESHOLD,
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


def _click_and_confirm(name: str, label: str, rect: Rect, timeout: float) -> bool:
    top_left, bottom_right = REGIONS[name]
    return DEVICE.click_until_disappears(
        top_left,
        bottom_right,
        TEMPLATES[name],
        rect,
        threshold=MATCH_THRESHOLD,
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

    score_text = "无" if best_score is None else f"{best_score:.3f}"
    print(f"[ERROR] {timeout:.0f} 秒内未识别到{label}，最高匹配分数 {score_text}")
    return False


def _wait_for_one_tap(
    timeout: float,
) -> Tuple[Optional[Rect], Optional[float]]:
    deadline = time.monotonic() + timeout
    best_score: Optional[float] = None
    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        score, rect = _match(frame, "one_tap")
        if score is not None and (best_score is None or score > best_score):
            best_score = score
        if rect is not None:
            return rect, score
    return None, best_score


def _back_color_metrics(frame, rect: Rect) -> Tuple[float, float, float, float]:
    """返回当前按钮和正常模板的平均 HSV 饱和度、亮度。"""
    left, top, right, bottom = rect
    current = frame[top:bottom, left:right]
    template = cv2.imread(TEMPLATES["back"])
    if current.size == 0 or template is None:
        return 0.0, 0.0, 1.0, 1.0
    current_hsv = cv2.cvtColor(current, cv2.COLOR_BGR2HSV)
    template_hsv = cv2.cvtColor(template, cv2.COLOR_BGR2HSV)
    return (
        float(current_hsv[:, :, 1].mean()),
        float(current_hsv[:, :, 2].mean()),
        float(template_hsv[:, :, 1].mean()),
        float(template_hsv[:, :, 2].mean()),
    )


def _back_is_active(frame, rect: Rect) -> bool:
    current_s, current_v, template_s, template_v = _back_color_metrics(frame, rect)
    active = (
        current_s >= template_s * BACK_MIN_SATURATION_RATIO
        and current_v >= template_v * BACK_MIN_BRIGHTNESS_RATIO
    )
    if not active:
        print(
            "返回按钮当前为灰暗状态，暂不点击："
            f"饱和度 {current_s:.1f}/{template_s:.1f}，"
            f"亮度 {current_v:.1f}/{template_v:.1f}"
        )
    return active


def _close_reward_success(rect: Rect, timeout: float) -> bool:
    click_index = 0

    def click_next_blank(_current_rect: Rect) -> None:
        nonlocal click_index
        region = REWARD_OUTSIDE_RIGHT_REGIONS[
            click_index % len(REWARD_OUTSIDE_RIGHT_REGIONS)
        ]
        click_index += 1
        _click_rect(region, f"领取成功弹窗右侧外部空白区域 {click_index}")

    print(f"等待 {REWARD_READY_DELAY_SECONDS:g} 秒，让奖励界面完成动画")
    time.sleep(REWARD_READY_DELAY_SECONDS)
    top_left, bottom_right = REGIONS["reward_success"]
    return DEVICE.click_until_disappears(
        top_left,
        bottom_right,
        TEMPLATES["reward_success"],
        rect,
        threshold=MATCH_THRESHOLD,
        timeout=timeout,
        label="领取成功弹窗",
        click_callback=click_next_blank,
        still_visible_delay=REWARD_RETRY_DELAY_SECONDS,
        log_callback=lambda message: LOGGER.message("领取奖励", message),
    )


def _complete_one_tap_and_exit() -> bool:
    """按领取判断、领奖处理、安全退出三个阶段完成一键日常。"""
    deadline = time.monotonic() + POST_ONE_TAP_TIMEOUT_SECONDS
    initial_wait = min(ONE_TAP_WAIT_SECONDS, max(0.1, deadline - time.monotonic()))
    one_tap_rect, best_one_tap_score = _wait_for_one_tap(initial_wait)

    if one_tap_rect is None:
        score_text = (
            "无" if best_one_tap_score is None else f"{best_one_tap_score:.3f}"
        )
        print(
            f"未识别到一键完成，最高分 {score_text}，"
            "尝试点击右上“日常”标签"
        )
        _click_rect(DAILY_TAB_CLICK_REGION, "日常标签")
        time.sleep(POST_ACTION_DELAY_SECONDS)
        retry_wait = min(
            ONE_TAP_WAIT_SECONDS,
            max(0.1, deadline - time.monotonic()),
        )
        one_tap_rect, retry_score = _wait_for_one_tap(retry_wait)
        if retry_score is not None and (
            best_one_tap_score is None or retry_score > best_one_tap_score
        ):
            best_one_tap_score = retry_score
        if one_tap_rect is None:
            score_text = (
                "无"
                if best_one_tap_score is None
                else f"{best_one_tap_score:.3f}"
            )
            print(
                f"[ERROR] 点击“日常”标签后仍未识别到一键完成，"
                f"最高分 {score_text}"
            )
            return False

    phase = "claim"
    claim_round = 1
    one_tap_clicks = 1
    completion_check_deadline: Optional[float] = None
    back_clicks = 0
    loading_logged = False
    back_exhausted_logged = False
    print("识别到一键完成")
    _click_rect(one_tap_rect, "一键完成")
    print(
        f"第 {claim_round}/{MAX_CLAIM_ROUNDS} 轮领取："
        f"第 1/{ONE_TAP_MAX_CLICKS} 次点击一键完成"
    )
    time.sleep(POST_ACTION_DELAY_SECONDS)

    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        # 返回主界面后任务列表入口重新出现，说明退出真正成功。
        task_score, task_rect = _match(frame, "task_list")
        main_score, main_rect = _match(frame, "main")
        if task_rect is not None or main_rect is not None:
            ready_score = task_score if task_rect is not None else main_score
            print(f"已退出一键日常并回到主界面，匹配分数 {ready_score:.3f}")
            return True

        # 签到和奖励弹窗在所有阶段都优先处理。
        sign_score, sign_rect = _match(frame, "sign_in_close")
        if sign_rect is not None:
            print(f"识别到每日签到关闭按钮，匹配分数 {sign_score:.3f}")
            remaining = min(STATE_CONFIRM_SECONDS, max(0.1, deadline - time.monotonic()))
            if not _click_and_confirm(
                "sign_in_close",
                "每日签到关闭按钮",
                sign_rect,
                remaining,
            ):
                return False
            phase = "loading"
            loading_logged = False
            back_clicks = 0
            back_exhausted_logged = False
            continue

        reward_score, reward_rect = _match(frame, "reward_success")
        if reward_rect is not None:
            print(f"识别到领取成功弹窗，匹配分数 {reward_score:.3f}")
            remaining = min(REWARD_CONFIRM_SECONDS, max(0.1, deadline - time.monotonic()))
            if not _close_reward_success(reward_rect, remaining):
                return False
            if claim_round < MAX_CLAIM_ROUNDS:
                phase = "verify_completion"
                completion_check_deadline = min(
                    deadline,
                    time.monotonic() + COMPLETION_VERIFY_SECONDS,
                )
                print("第 1 轮奖励领取结束，检查顶部任务是否已完成")
            else:
                phase = "exit"
                print("第 2 轮奖励领取结束，准备退出一键日常")
            back_clicks = 0
            back_exhausted_logged = False
            continue

        if phase == "verify_completion":
            completed_score, completed_rect = _match(frame, "completed")
            if completed_rect is not None:
                print(
                    f"顶部任务已完成，匹配分数 {completed_score:.3f}，"
                    "无需再次领取"
                )
                phase = "exit"
                continue
            if (
                completion_check_deadline is not None
                and time.monotonic() < completion_check_deadline
            ):
                time.sleep(SCREENSHOT_INTERVAL)
                continue

            second_score, second_rect = _match(frame, "one_tap")
            if second_rect is None:
                print(
                    "[ERROR] 顶部任务未识别为已完成，"
                    "同时未找到可供第二轮领取的一键完成按钮"
                )
                return False
            claim_round += 1
            one_tap_clicks = 1
            phase = "claim"
            completion_check_deadline = None
            loading_logged = False
            print(
                f"顶部任务尚未完成，一键完成匹配分数 {second_score:.3f}，"
                "开始第 2 轮领取"
            )
            _click_rect(second_rect, "一键完成")
            time.sleep(POST_ACTION_DELAY_SECONDS)
            continue

        back_score, back_rect = _match(frame, "back")

        if phase == "claim":
            # 点击被游戏接受后背景会变灰。此后绝不再点击一键完成或返回，
            # 只等待可能出现的签到和最终奖励弹窗。
            if back_rect is not None and not _back_is_active(frame, back_rect):
                phase = "loading"
                print("页面已变灰，一键领取已生效，等待签到或奖励界面")
                continue

            one_tap_score, current_one_tap_rect = _match(frame, "one_tap")
            if current_one_tap_rect is None:
                phase = "loading"
                print("一键完成按钮已消失，等待签到或奖励界面")
                continue

            if one_tap_clicks < ONE_TAP_MAX_CLICKS:
                one_tap_clicks += 1
                print(
                    f"第 {claim_round}/{MAX_CLAIM_ROUNDS} 轮领取："
                    f"页面未变灰且一键完成仍可见，"
                    f"匹配分数 {one_tap_score:.3f}，"
                    f"第 {one_tap_clicks}/{ONE_TAP_MAX_CLICKS} 次补点"
                )
                _click_rect(current_one_tap_rect, "一键完成")
                time.sleep(POST_ACTION_DELAY_SECONDS)
                continue

            # 三次点击后，只有确认页面仍是正常颜色，才判定本轮无奖励。
            if back_rect is not None and _back_is_active(frame, back_rect):
                phase = "exit"
                print("连续点击一键完成 3 次后页面仍未变灰，按本轮没有可领取奖励处理")
            else:
                time.sleep(SCREENSHOT_INTERVAL)
                continue

        if phase == "loading":
            if not loading_logged:
                print("奖励发放处理中，暂停点击并持续等待弹窗")
                loading_logged = True
            time.sleep(SCREENSHOT_INTERVAL)
            continue

        if phase == "exit" and back_rect is not None:
            if not _back_is_active(frame, back_rect):
                time.sleep(SCREENSHOT_INTERVAL)
                continue
            if back_clicks < MAX_BACK_CLICKS:
                back_clicks += 1
                print(
                    f"返回按钮颜色正常，匹配分数 {back_score:.3f}，"
                    f"第 {back_clicks}/{MAX_BACK_CLICKS} 次点击"
                )
                _click_rect(back_rect, "返回")
                time.sleep(POST_ACTION_DELAY_SECONDS)
                continue
            if not back_exhausted_logged:
                print("返回按钮连续点击 3 次仍未退出，停止点击并继续等待主界面")
                back_exhausted_logged = True

        time.sleep(SCREENSHOT_INTERVAL)

    print("[ERROR] 一键日常状态处理超时，仍未成功退出")
    return False


def run() -> bool:
    utils.connect_to_mumu()
    print("开始一键日常任务")
    if not _wait_and_click("task_list", "任务列表", MAIN_WAIT_SECONDS):
        return False
    if not _complete_one_tap_and_exit():
        return False
    print("一键日常任务完成，已确认返回主界面")
    return True


if __name__ == "__main__":
    try:
        success = run()
    except KeyboardInterrupt:
        print("任务已由用户中止")
        success = False

    raise SystemExit(0 if success else 1)

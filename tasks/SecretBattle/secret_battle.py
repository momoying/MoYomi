"""自动重复挑战当前秘闻层，直到获得黑蛋或协战次数耗尽。"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path
from typing import Callable, Optional, Tuple


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from module import automation as utils
from module.base.device import TaskDevice


DEVICE = TaskDevice(utils)


from tasks.SecretBattle.assets import SecretBattleAssets

ASSETS = SecretBattleAssets
CHALLENGE_TEMPLATE = ASSETS.CHALLENGE_TEMPLATE
CHALLENGE_REGION = ASSETS.CHALLENGE_REGION
CHALLENGE_THRESHOLD = ASSETS.CHALLENGE_THRESHOLD
OBTAINED_TEMPLATE = ASSETS.OBTAINED_TEMPLATE
OBTAINED_REGION = ASSETS.OBTAINED_REGION
OBTAINED_THRESHOLD = ASSETS.OBTAINED_THRESHOLD
REWARD_TEMPLATE = ASSETS.REWARD_TEMPLATE
REWARD_REGION = ASSETS.REWARD_REGION
REWARD_THRESHOLD = ASSETS.REWARD_THRESHOLD
FAILED_TEMPLATE = ASSETS.FAILED_TEMPLATE
FAILED_REGION = ASSETS.FAILED_REGION
FAILED_THRESHOLD = ASSETS.FAILED_THRESHOLD
PREPARE_TEMPLATE = ASSETS.PREPARE_TEMPLATE
PREPARE_REGION = ASSETS.PREPARE_REGION
PREPARE_THRESHOLD = ASSETS.PREPARE_THRESHOLD
BLANK_AREAS = ASSETS.BLANK_AREAS

SCREENSHOT_INTERVAL = 2.0
BATTLE_TIMEOUT_SECONDS = 300
UNKNOWN_PAGE_LIMIT = 20







Rect = Tuple[int, int, int, int]
Point = Tuple[int, int]
AttemptsCallback = Callable[[int], None]


def _match(
    frame,
    template: Path,
    region: Tuple[Point, Point],
    threshold: float,
) -> Tuple[Optional[float], Optional[Rect]]:
    score, rect = DEVICE.match(
        region[0],
        region[1],
        str(template),
        frame=frame,
    )
    if score is None or rect is None or score < threshold:
        return score, None
    return score, rect


def _random_inner_point(rect: Rect) -> Point:
    left, top, right, bottom = rect
    width = max(1, right - left)
    height = max(1, bottom - top)
    margin_x = min(max(3, width // 5), max(0, (width - 1) // 2))
    margin_y = min(max(3, height // 5), max(0, (height - 1) // 2))
    return (
        random.randint(left + margin_x, max(left + margin_x, right - 1 - margin_x)),
        random.randint(top + margin_y, max(top + margin_y, bottom - 1 - margin_y)),
    )


def _click_blank() -> None:
    side, area = random.choice(tuple(BLANK_AREAS.items()))
    left, top, right, bottom = area
    x = random.randint(left, right)
    y = random.randint(top, bottom)
    print(f"[ACTION] 点击{side}空白区域 ({x}, {y})，返回挑战界面")
    DEVICE.click(x, y)


def run(
    stop_event=None,
    attempts: int = 0,
    attempts_callback: Optional[AttemptsCallback] = None,
) -> bool:
    """执行当前秘闻层；每次实际点击挑战后消耗一次协战次数。"""
    remaining = int(attempts)
    if remaining <= 0:
        print("[ERROR] 协战次数为 0，请先在工具控制中填写可用次数")
        return False
    if not utils.connect_to_mumu():
        raise RuntimeError("无法连接 MuMu ADB，请检查设置中的模拟器实例")

    utils.config["screenshot_speed"] = SCREENSHOT_INTERVAL
    print(f"[INFO] 一键秘闻已启动，当前可用协战次数：{remaining}")

    state = "challenge"
    unknown_frames = 0
    battle_started_at = 0.0

    while stop_event is None or not stop_event.is_set():
        frame = DEVICE.screenshot()
        if frame is None:
            print("[WARN] 截图失败，等待下一次检测")
            continue

        if state == "challenge":
            obtained_score, obtained_rect = _match(
                frame,
                OBTAINED_TEMPLATE,
                OBTAINED_REGION,
                OBTAINED_THRESHOLD,
            )
            if obtained_rect is not None:
                print(
                    "[SUCCESS] 检测到黑蛋已获得标志，"
                    f"匹配分数 {obtained_score:.3f}，任务完成"
                )
                return True

            if remaining <= 0:
                print("[INFO] 协战次数已用完，一键秘闻自动停止")
                return True

            challenge_score, challenge_rect = _match(
                frame,
                CHALLENGE_TEMPLATE,
                CHALLENGE_REGION,
                CHALLENGE_THRESHOLD,
            )
            if challenge_rect is None:
                unknown_frames += 1
                if unknown_frames >= UNKNOWN_PAGE_LIMIT:
                    print("[ERROR] 长时间未识别到挑战按钮或黑蛋已获得标志，任务终止")
                    return False
                continue

            unknown_frames = 0
            x, y = _random_inner_point(challenge_rect)
            DEVICE.click(x, y)
            remaining -= 1
            if attempts_callback is not None:
                attempts_callback(remaining)
            print(
                "[ACTION] 识别并点击挑战，"
                f"匹配分数 {challenge_score:.3f}，剩余协战次数：{remaining}"
            )
            state = "battle"
            battle_started_at = time.monotonic()
            continue

        failed_score, failed_rect = _match(
            frame,
            FAILED_TEMPLATE,
            FAILED_REGION,
            FAILED_THRESHOLD,
        )
        if failed_rect is not None:
            print(
                "[ERROR] 挑战失败，"
                f"匹配分数 {failed_score:.3f}，一键秘闻已终止"
            )
            return False

        prepare_score, prepare_rect = _match(
            frame,
            PREPARE_TEMPLATE,
            PREPARE_REGION,
            PREPARE_THRESHOLD,
        )
        if prepare_rect is not None:
            x, y = _random_inner_point(prepare_rect)
            DEVICE.click(x, y)
            print(
                "[ACTION] 识别并点击准备，"
                f"匹配分数 {prepare_score:.3f}"
            )
            continue

        reward_score, reward_rect = _match(
            frame,
            REWARD_TEMPLATE,
            REWARD_REGION,
            REWARD_THRESHOLD,
        )
        if reward_rect is not None:
            print(f"[SUCCESS] 检测到战斗奖励，匹配分数 {reward_score:.3f}")
            _click_blank()
            time.sleep(random.uniform(0.3,0.5))
            _click_blank()
            state = "challenge"
            unknown_frames = 0
            continue

        if time.monotonic() - battle_started_at >= BATTLE_TIMEOUT_SECONDS:
            print("[ERROR] 战斗超过 300 秒仍未识别到成功或失败界面，任务终止")
            return False

    print("[INFO] 一键秘闻已安全停止")
    return True


if __name__ == "__main__":
    try:
        run(attempts=1)
    except KeyboardInterrupt:
        print("\n[INFO] 一键秘闻已停止")

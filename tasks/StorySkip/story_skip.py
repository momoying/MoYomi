"""独立剧情跳过脚本"""

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


DEVICE = TaskDevice(utils)


from tasks.StorySkip.assets import StoryAction, StorySkipAssets

ASSETS = StorySkipAssets
BATTLE_PREPARE_TEMPLATE = ASSETS.BATTLE_PREPARE_TEMPLATE
BATTLE_PREPARE_THRESHOLD = ASSETS.BATTLE_PREPARE_THRESHOLD
BATTLE_PREPARE_REGION = ASSETS.BATTLE_PREPARE_REGION
BATTLE_REWARD_TEMPLATE = ASSETS.BATTLE_REWARD_TEMPLATE
BATTLE_REWARD_THRESHOLD = ASSETS.BATTLE_REWARD_THRESHOLD
BATTLE_REWARD_REGION = ASSETS.BATTLE_REWARD_REGION
BATTLE_REWARD_BLANK_AREAS = ASSETS.BATTLE_REWARD_BLANK_AREAS
ACTIONS = ASSETS.ACTIONS

SCREENSHOT_INTERVAL = 1
BATTLE_SCREENSHOT_INTERVAL = 3.0
utils.config["screenshot_speed"] = SCREENSHOT_INTERVAL


Rect = Tuple[int, int, int, int]
Point = Tuple[int, int]


def _match(frame, action: StoryAction) -> Tuple[Optional[float], Optional[Rect]]:
    score, rect = DEVICE.match(
        action.top_left,
        action.bottom_right,
        str(action.template),
        frame=frame,
    )
    if score is None or rect is None or score < action.threshold:
        return score, None
    return score, rect


def _random_inner_point(rect: Rect) -> Point:
    """在识别框内部随机落点，避开按钮边缘。"""
    left, top, right, bottom = rect
    width = max(1, right - left)
    height = max(1, bottom - top)
    margin_x = min(max(2, width // 5), max(0, (width - 1) // 2))
    margin_y = min(max(2, height // 5), max(0, (height - 1) // 2))
    x1, x2 = left + margin_x, right - 1 - margin_x
    y1, y2 = top + margin_y, bottom - 1 - margin_y
    if x1 > x2:
        x1, x2 = left, max(left, right - 1)
    if y1 > y2:
        y1, y2 = top, max(top, bottom - 1)
    return random.randint(x1, x2), random.randint(y1, y2)


def process_frame(frame, *, perform_click: bool = True) -> Optional[str]:
    """处理一帧；只返回并点击这一帧中优先级最高的动作。"""
    for action in ACTIONS:
        score, rect = _match(frame, action)
        if rect is None:
            continue

        x, y = _random_inner_point(rect)
        print(f"识别到{action.label}，匹配分数 {score:.3f}，点击 ({x}, {y})")
        if perform_click:
            DEVICE.click(x, y)
        return action.key

    return None


def process_challenge_confirmation_frame(
    frame, *, perform_click: bool = True
) -> bool:
    """确认挑战标志是否仍在；仍在时按最新匹配框重试点击。"""
    challenge_action = next(action for action in ACTIONS if action.key == "challenge")
    score, rect = _match(frame, challenge_action)
    if rect is None:
        return False

    x, y = _random_inner_point(rect)
    print(
        f"挑战标志点击后仍可见，匹配分数 {score:.3f}，"
        f"重新点击 ({x}, {y})"
    )
    if perform_click:
        DEVICE.click(x, y)
    return True


def process_battle_frame(frame, *, perform_click: bool = True) -> bool:
    """识别战斗奖励；每次只随机点击左、右其中一侧的安全区域。"""
    score, rect = DEVICE.match(
        BATTLE_REWARD_REGION[0],
        BATTLE_REWARD_REGION[1],
        str(BATTLE_REWARD_TEMPLATE),
        frame=frame,
    )
    if score is None or rect is None or score < BATTLE_REWARD_THRESHOLD:
        return False

    side, area = random.choice(tuple(BATTLE_REWARD_BLANK_AREAS.items()))
    left, top, right, bottom = area
    x = random.randint(left, right)
    y = random.randint(top, bottom)
    print(f"识别到战斗奖励，匹配分数 {score:.3f}，点击{side}空白区域 ({x}, {y})")
    if perform_click:
        DEVICE.click(x, y)
    return True


def process_battle_prepare_frame(frame, *, perform_click: bool = True) -> bool:
    """全屏识别并点击准备按钮。"""
    score, rect = DEVICE.match(
        BATTLE_PREPARE_REGION[0],
        BATTLE_PREPARE_REGION[1],
        str(BATTLE_PREPARE_TEMPLATE),
        frame=frame,
    )
    if score is None or rect is None or score < BATTLE_PREPARE_THRESHOLD:
        return False

    x, y = _random_inner_point(rect)
    print(f"识别到准备，匹配分数 {score:.3f}，点击 ({x}, {y})")
    if perform_click:
        DEVICE.click(x, y)
    return True


def run(stop_event=None) -> bool:
    """持续处理剧情；设置 stop_event 后在下一轮截图前安全退出。"""
    if not utils.connect_to_mumu():
        raise RuntimeError(
            "无法连接 MuMu ADB，无法执行点击；请检查 cfg.txt 中的 adb_path 和 adb_port"
        )

    if stop_event is None:
        print("剧情跳过脚本已启动，按 Ctrl+C 停止")
    else:
        print("剧情跳过工具已启动，可在小工具页面安全停止")
    print(
        "优先级：确认跳过 > 三点气泡 > 对话跳过 > "
        "右上剧情跳过 > 挑战 > 天眼 > 未知问号标志"
    )

    challenge_pending = False
    in_battle = False
    battle_phase = "prepare"
    prepare_clicked = False
    reward_clicked = False

    while stop_event is None or not stop_event.is_set():
        frame = DEVICE.screenshot()
        if frame is None:
            print("[WARN] 截图失败，等待下一次检测")
            interval = BATTLE_SCREENSHOT_INTERVAL if in_battle else SCREENSHOT_INTERVAL
            time.sleep(interval)
            continue

        if challenge_pending:
            challenge_visible = process_challenge_confirmation_frame(frame)
            if not challenge_visible:
                challenge_pending = False
                in_battle = True
                battle_phase = "prepare"
                prepare_clicked = False
                reward_clicked = False
                utils.config["screenshot_speed"] = BATTLE_SCREENSHOT_INTERVAL
                print("挑战标志已消失，确认进入战斗；截屏间隔调整为 3 秒")
            continue

        if in_battle:
            if battle_phase == "prepare":
                prepare_visible = process_battle_prepare_frame(frame)
                if prepare_visible:
                    prepare_clicked = True
                elif prepare_clicked:
                    battle_phase = "reward"
                    print("准备按钮已消失，开始等待战斗奖励")
                continue

            reward_visible = process_battle_frame(frame)
            if reward_visible:
                reward_clicked = True
            elif reward_clicked:
                print("战斗奖励界面已消失，恢复普通剧情检测")
                in_battle = False
                reward_clicked = False
                utils.config["screenshot_speed"] = SCREENSHOT_INTERVAL
            continue

        action = process_frame(frame)
        if action == "challenge":
            challenge_pending = True
            print("已点击挑战，等待下一张截图确认挑战标志消失")

    print("剧情跳过脚本已安全停止")
    return True


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\n剧情跳过脚本已停止")
    except Exception as exc:
        print(f"[ERROR] {exc}")
        raise SystemExit(1)

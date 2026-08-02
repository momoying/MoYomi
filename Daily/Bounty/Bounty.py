"""阴阳师悬赏检测：从主界面进入悬赏封印，检查所有格子的勾玉协作并退出。"""

from __future__ import annotations

import random
import sys
import time
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple

import cv2


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Core import automation as utils
from Core.logging import TaskLogger


LOGGER = TaskLogger("悬赏检测")
print = LOGGER.legacy_print


SCREENSHOT_INTERVAL = 0.5
utils.config["screenshot_speed"] = SCREENSHOT_INTERVAL

TEMPLATES = {
    "bounty": str(SCRIPT_DIR / "bounty.png"),
    "back": str(SCRIPT_DIR / "back.png"),
    "cooperation": str(SCRIPT_DIR / "cooperation.png"),
    "sharing": str(SCRIPT_DIR / "sharing.png"),
    "magatama": str(SCRIPT_DIR / "magatama.png"),
}

REGIONS = {
    # 主界面左中部的“封”字悬赏入口。
    "bounty": ((180, 240), (400, 430)),
    # 悬赏页右上角红色关闭按钮。
    "back": ((1050, 60), (1250, 210)),
    # 搜索整排悬赏卡的“协”标记，不假设它出现在第几格。
    "cooperation": ((100, 220), (1260, 370)),
    # 现世协作使用同一位置的“享”标记。
    "sharing": ((100, 220), (1260, 370)),
}

# “协”位于卡牌左边；根据它反推同一卡牌的水平范围，
# 再只在该卡牌底部奖励区查找勾玉。
CARD_LEFT_OFFSET_FROM_COOPERATION = 30
CARD_WIDTH = 290
REWARD_TOP = 470
REWARD_BOTTOM = 610
MAX_VISIBLE_CARDS = 6

MATCH_THRESHOLD = 0.82
ENTRY_WAIT_SECONDS = 8.0
PAGE_WAIT_SECONDS = 12.0
DETECTION_WAIT_SECONDS = 3.0
BACK_WAIT_SECONDS = 10.0

Rect = Tuple[int, int, int, int]


class BountyResult(str, Enum):
    NORMAL_MAGATAMA_COLLABORATION = "normal_magatama_collaboration"
    SHARING_MAGATAMA_COLLABORATION = "sharing_magatama_collaboration"
    NO_MAGATAMA_COLLABORATION = "no_magatama_collaboration"
    ERROR = "error"


def _score_text(score: Optional[float]) -> str:
    return "无" if score is None else f"{score:.3f}"


def _match(frame, name: str) -> Tuple[Optional[float], Optional[Rect]]:
    top_left, bottom_right = REGIONS[name]
    score, rect = utils.crop_and_match(
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


def _find_all_matches(
    frame,
    name: str,
    threshold: float = MATCH_THRESHOLD,
) -> Tuple[Optional[float], list[Tuple[float, Rect]]]:
    """找出搜索区内所有独立的模板命中，并抑制同一图标周围的重复峰值。"""
    top_left, bottom_right = REGIONS[name]
    x1, y1 = top_left
    x2, y2 = bottom_right
    crop = frame[y1:y2, x1:x2]
    template = cv2.imread(TEMPLATES[name])
    if template is None or crop.size == 0:
        return None, []

    template_height, template_width = template.shape[:2]
    crop_height, crop_width = crop.shape[:2]
    if template_height > crop_height or template_width > crop_width:
        return None, []

    scores = cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED)
    best_score = float(cv2.minMaxLoc(scores)[1])
    working_scores = scores.copy()
    matches: list[Tuple[float, Rect]] = []

    while len(matches) < MAX_VISIBLE_CARDS:
        _, score, _, location = cv2.minMaxLoc(working_scores)
        if score < threshold:
            break

        local_x, local_y = location
        left = x1 + local_x
        top = y1 + local_y
        rect = (left, top, left + template_width, top + template_height)
        matches.append((float(score), rect))

        # 一个图标会在相邻像素产生多个高分峰，清掉以最佳点为中心的模板尺寸邻域。
        suppress_left = max(0, local_x - template_width)
        suppress_top = max(0, local_y - template_height)
        suppress_right = min(working_scores.shape[1], local_x + template_width + 1)
        suppress_bottom = min(working_scores.shape[0], local_y + template_height + 1)
        working_scores[suppress_top:suppress_bottom, suppress_left:suppress_right] = -1.0

    matches.sort(key=lambda match: match[1][0])
    for score, rect in matches:
        LOGGER.match(
            name,
            name,
            score,
            threshold,
            rect,
            search_region=(x1, y1, x2, y2),
        )
    return best_score, matches


def _take_frame():
    frame = utils.take_screenshot()
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
    utils.adb_click(x, y)


def _click_and_confirm(name: str, label: str, rect: Rect, timeout: float) -> bool:
    top_left, bottom_right = REGIONS[name]
    return utils.click_template_until_disappears(
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


def _wait_for_template(
    name: str,
    label: str,
    timeout: float,
) -> Tuple[Optional[object], Optional[Rect], Optional[float]]:
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
            return frame, rect, score

    return None, None, best_score


def _wait_and_click(name: str, label: str, timeout: float) -> bool:
    _, rect, best_score = _wait_for_template(name, label, timeout)
    if rect is None:
        print(
            f"[ERROR] {timeout:.0f} 秒内未识别到{label}，"
            f"最高匹配分数 {_score_text(best_score)}"
        )
        return False
    return _click_and_confirm(name, label, rect, timeout)


def detect_magatama_collaboration(
    frame,
) -> Tuple[
    bool,
    Optional[str],
    Optional[float],
    Optional[float],
    Optional[float],
]:
    """遍历“协”和“享”格子，仅当同一格奖励区有勾玉才返回真。"""
    cooperation_best_score, cooperation_matches = _find_all_matches(
        frame,
        "cooperation",
    )
    sharing_best_score, sharing_matches = _find_all_matches(
        frame,
        "sharing",
    )
    best_magatama_score: Optional[float] = None

    marker_groups = (
        # “享”比“协”更稀有且结果需要单独展示，优先判断更具体的模板。
        ("sharing", "现世协作（享）", sharing_matches),
        ("cooperation", "普通协作（协）", cooperation_matches),
    )
    for marker_name, marker_label, marker_matches in marker_groups:
        for marker_score, marker_rect in marker_matches:
            card_left = max(0, marker_rect[0] - CARD_LEFT_OFFSET_FROM_COOPERATION)
            card_right = min(frame.shape[1], card_left + CARD_WIDTH)
            magatama_score, magatama_rect = utils.crop_and_match(
                (card_left, REWARD_TOP),
                (card_right, REWARD_BOTTOM),
                TEMPLATES["magatama"],
                frame=frame,
            )
            if magatama_score is not None and (
                best_magatama_score is None
                or magatama_score > best_magatama_score
            ):
                best_magatama_score = magatama_score
            if (
                magatama_score is not None
                and magatama_rect is not None
                and magatama_score >= MATCH_THRESHOLD
            ):
                print(
                    f"识别到{marker_label}且同格存在勾玉："
                    f"标记 {marker_score:.3f}，勾玉 {magatama_score:.3f}"
                )
                return (
                    True,
                    marker_name,
                    cooperation_best_score,
                    sharing_best_score,
                    magatama_score,
                )

    return (
        False,
        None,
        cooperation_best_score,
        sharing_best_score,
        best_magatama_score,
    )


def _check_all_bounties() -> Optional[str]:
    deadline = time.monotonic() + DETECTION_WAIT_SECONDS
    best_cooperation_score: Optional[float] = None
    best_sharing_score: Optional[float] = None
    best_magatama_score: Optional[float] = None

    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        (
            found,
            marker_name,
            cooperation_score,
            sharing_score,
            magatama_score,
        ) = detect_magatama_collaboration(frame)
        if cooperation_score is not None and (
            best_cooperation_score is None or cooperation_score > best_cooperation_score
        ):
            best_cooperation_score = cooperation_score
        if sharing_score is not None and (
            best_sharing_score is None or sharing_score > best_sharing_score
        ):
            best_sharing_score = sharing_score
        if magatama_score is not None and (
            best_magatama_score is None or magatama_score > best_magatama_score
        ):
            best_magatama_score = magatama_score
        if found:
            kind = "现世勾玉协作" if marker_name == "sharing" else "普通勾玉协作"
            print(f"有勾玉协作：{kind}")
            return marker_name

    print("没有勾玉协作")
    print(
        "所有格子匹配分数："
        f"协 {_score_text(best_cooperation_score)}，"
        f"享 {_score_text(best_sharing_score)}，"
        f"协/享格内勾玉 {_score_text(best_magatama_score)}"
    )
    return None


def check_bounty() -> BountyResult:
    """执行检测并返回可供中控使用的结构化结果。"""
    utils.connect_to_mumu()
    print("开始检测悬赏")

    _, entry_rect, best_score = _wait_for_template(
        "bounty",
        "悬赏入口",
        ENTRY_WAIT_SECONDS,
    )
    if entry_rect is None:
        print(
            f"[ERROR] 未识别到恒定存在的悬赏入口，"
            f"最高匹配分数 {_score_text(best_score)}"
        )
        return BountyResult.ERROR

    if not _click_and_confirm(
        "bounty",
        "悬赏入口",
        entry_rect,
        PAGE_WAIT_SECONDS,
    ):
        return BountyResult.ERROR
    _, page_back_rect, page_score = _wait_for_template(
        "back",
        "悬赏页退出按钮",
        PAGE_WAIT_SECONDS,
    )
    if page_back_rect is None:
        print(
            f"[ERROR] 进入后未识别到悬赏页，"
            f"退出按钮最高匹配分数 {_score_text(page_score)}"
        )
        return BountyResult.ERROR

    collaboration_kind = _check_all_bounties()

    if not _wait_and_click("back", "悬赏页退出按钮", BACK_WAIT_SECONDS):
        return BountyResult.ERROR
    print("已退出悬赏页")

    if collaboration_kind == "sharing":
        return BountyResult.SHARING_MAGATAMA_COLLABORATION
    if collaboration_kind == "cooperation":
        return BountyResult.NORMAL_MAGATAMA_COLLABORATION
    return BountyResult.NO_MAGATAMA_COLLABORATION


def run() -> bool:
    return check_bounty() is not BountyResult.ERROR


if __name__ == "__main__":
    try:
        success = run()
    except KeyboardInterrupt:
        print("任务已由用户中止")
        success = False
    raise SystemExit(0 if success else 1)

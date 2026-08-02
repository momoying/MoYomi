"""领取邮件：每天 06:00 刷新后检查一次，有红点时领取全部附件。"""

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
from Core.task_logging import TaskLogger


LOGGER = TaskLogger("领取邮件")
print = LOGGER.legacy_print


SCREENSHOT_INTERVAL = 0.5
utils.config["screenshot_speed"] = SCREENSHOT_INTERVAL

TEMPLATES = {
    "main": str(DAILY_DIR / "CoopReward" / "explore.png"),
    "mail_unread": str(SCRIPT_DIR / "mail_unread.png"),
    "mail_normal": str(SCRIPT_DIR / "mail_normal.png"),
    "claim_all": str(SCRIPT_DIR / "claim_all.png"),
    "mark_all_read": str(SCRIPT_DIR / "mark_all_read.png"),
    "confirm": str(SCRIPT_DIR / "confirm.png"),
    "reward": str(SCRIPT_DIR / "reward.png"),
    "close": str(SCRIPT_DIR / "close.png"),
}

REGIONS = {
    "main": ((500, 80), (800, 280)),
    # 庭院顶部右侧的系统邮箱，不是展开功能栏中的邮件入口。
    "mail_unread": ((1080, 0), (1210, 100)),
    "mail_normal": ((1080, 0), (1210, 100)),
    "claim_all": ((0, 520), (230, 720)),
    "mark_all_read": ((140, 560), (340, 690)),
    "confirm": ((600, 480), (930, 670)),
    "reward": ((300, 30), (950, 280)),
    "close": ((1080, 20), (1270, 210)),
}

MATCH_THRESHOLDS = {
    "main": 0.80,
    # 两个邮箱模板仅相差红点，交叉分数约 0.894，因此阈值必须高于它。
    "mail_unread": 0.95,
    "mail_normal": 0.95,
    "claim_all": 0.86,
    "mark_all_read": 0.86,
    "confirm": 0.86,
    "reward": 0.86,
    "close": 0.86,
}

MAIN_WAIT_SECONDS = 10.0
MAIL_PAGE_WAIT_SECONDS = 10.0
CONFIRM_WAIT_SECONDS = 10.0
REWARD_WAIT_SECONDS = 10.0
ACTION_CONFIRM_SECONDS = 12.0
RETURN_WAIT_SECONDS = 10.0
CONFIRM_RETRY_SECONDS = 2.0
REWARD_READY_SECONDS = 2.0
REWARD_RETRY_SECONDS = 3.0

# 奖励板位于屏幕中央；每次随机选择一侧，只点击一边。
REWARD_BLANK_AREAS = {
    "左侧": (40, 250, 190, 620),
    "右侧": (1060, 250, 1160, 620),
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
        LOGGER.warning("截图", "截图失败，等待下一帧")
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
    LOGGER.error("识别超时", f"{timeout:.0f} 秒内未识别到目标模板：{details}")
    return last_frame, None, None, None


def _click_until_disappears(
    name: str,
    label: str,
    rect: Rect,
    timeout: float = ACTION_CONFIRM_SECONDS,
    *,
    still_visible_delay: float = 1.0,
) -> bool:
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
        still_visible_delay=still_visible_delay,
        log_callback=lambda message: LOGGER.message(label, message),
    )


def _wait_for_mail_state() -> Tuple[Optional[str], Optional[Rect]]:
    deadline = time.monotonic() + MAIN_WAIT_SECONDS
    last_frame = None
    best_unread: Optional[float] = None
    best_normal: Optional[float] = None

    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame
        _, main_rect = _match(frame, "main")
        if main_rect is None:
            continue

        # 必须先判红点；普通模板与红点模板高度相似。
        unread_score, unread_rect = _match(frame, "mail_unread")
        if unread_score is not None and (
            best_unread is None or unread_score > best_unread
        ):
            best_unread = unread_score
        if unread_rect is not None:
            return "unread", unread_rect

        normal_score, normal_rect = _match(frame, "mail_normal")
        if normal_score is not None and (
            best_normal is None or normal_score > best_normal
        ):
            best_normal = normal_score
        if normal_rect is not None:
            return "normal", normal_rect

    LOGGER.error(
        "庭院首页",
        "未确认邮箱状态，"
        f"红点最高分={'无' if best_unread is None else f'{best_unread:.3f}'}，"
        f"普通最高分={'无' if best_normal is None else f'{best_normal:.3f}'}",
    )
    return None, None


def _claim_mail() -> bool:
    _, action, action_rect, score = _wait_for_any(
        ("claim_all", "mark_all_read"),
        MAIL_PAGE_WAIT_SECONDS,
    )
    if action is None or action_rect is None:
        return False
    if action == "mark_all_read":
        LOGGER.info(
            "一键已读",
            f"邮箱没有可领取附件，识别到一键已读，匹配分数 {score:.3f}",
        )
        # 点击后按钮可能仍保留在页面上，不能以“模板消失”作为成功条件。
        # 后续统一识别右上角关闭按钮并退出邮箱。
        _click_rect(action_rect, "一键已读")
        LOGGER.info("一键已读", "已点击一键已读，准备识别退出键")
        return True

    claim_rect = action_rect
    LOGGER.info("一键领取", f"识别到可用的一键领取，匹配分数 {score:.3f}，只点击一次")
    # 点击后按钮会变灰，灰色按钮不再参与后续状态判断。
    _click_rect(claim_rect, "一键领取")

    _, _, confirm_rect, score = _wait_for_any(("confirm",), CONFIRM_WAIT_SECONDS)
    if confirm_rect is None:
        return False
    LOGGER.info("领取确认", f"识别到确定按钮，匹配分数 {score:.3f}")
    if not _click_until_disappears(
        "confirm",
        "领取确认",
        confirm_rect,
        ACTION_CONFIRM_SECONDS,
        still_visible_delay=CONFIRM_RETRY_SECONDS,
    ):
        return False

    LOGGER.info("领取奖励", "领取处理中，等待获得奖励界面")
    _, _, reward_rect, score = _wait_for_any(("reward",), REWARD_WAIT_SECONDS)
    if reward_rect is None:
        return False
    LOGGER.info("领取奖励", f"识别到获得奖励，匹配分数 {score:.3f}")
    time.sleep(REWARD_READY_SECONDS)

    def click_random_side(_current_rect: Rect) -> None:
        side, region = random.choice(tuple(REWARD_BLANK_AREAS.items()))
        _click_rect(region, f"获得奖励{side}空白区域")

    top_left, bottom_right = REGIONS["reward"]
    if not utils.click_template_until_disappears(
        top_left,
        bottom_right,
        TEMPLATES["reward"],
        reward_rect,
        threshold=MATCH_THRESHOLDS["reward"],
        timeout=ACTION_CONFIRM_SECONDS,
        label="获得奖励",
        click_callback=click_random_side,
        still_visible_delay=REWARD_RETRY_SECONDS,
        log_callback=lambda message: LOGGER.message("领取奖励", message),
    ):
        return False
    return True


def _close_mailbox() -> bool:
    _, _, close_rect, score = _wait_for_any(("close",), MAIL_PAGE_WAIT_SECONDS)
    if close_rect is None:
        return False
    LOGGER.info("退出邮箱", f"识别到邮箱关闭按钮，匹配分数 {score:.3f}")
    if not _click_until_disappears("close", "退出邮箱", close_rect):
        return False
    _, name, _, _ = _wait_for_any(("main",), RETURN_WAIT_SECONDS)
    return name == "main"


def run() -> bool:
    utils.connect_to_mumu()
    LOGGER.info("启动", "开始领取邮件任务")

    mail_state, mail_rect = _wait_for_mail_state()
    if mail_state is None or mail_rect is None:
        return False
    if mail_state == "normal":
        LOGGER.info("邮件检查", "邮箱没有红点，本刷新周期无邮件需要领取")
        return True

    LOGGER.info("邮件检查", "检测到邮箱红点，进入邮箱领取附件")
    if not _click_until_disappears("mail_unread", "进入邮箱", mail_rect):
        return False
    if not _claim_mail():
        return False
    if not _close_mailbox():
        return False

    LOGGER.info("完成", "邮件领取完成，已返回庭院首页")
    return True


if __name__ == "__main__":
    try:
        success = run()
    except KeyboardInterrupt:
        LOGGER.warning("中止", "领取邮件任务已由用户中止")
        success = False
    raise SystemExit(0 if success else 1)

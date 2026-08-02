"""任务超时恢复：从未知任务页面逐步返回庭院。"""

from __future__ import annotations

import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple


CORE_DIR = Path(__file__).resolve().parent
HELPER_DIR = CORE_DIR.parent
PROJECT_ROOT = HELPER_DIR
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Core import game_automation as utils
from Core.task_logging import TaskLogger


LOGGER = TaskLogger("超时恢复")
print = LOGGER.legacy_print

ASSET_DIR = CORE_DIR / "task_timeout_recovery_assets"
SCREENSHOT_DIR = HELPER_DIR / "task_timeout_recovery_screenshots"
SCREENSHOT_INTERVAL = 0.8
MATCH_THRESHOLD = 0.80
UNKNOWN_STATE_GRACE_SECONDS = 10.0
RECOVERY_TIMEOUT_SECONDS = 90.0
SCREENSHOT_KEEP_COUNT = 20
POST_CLICK_DELAY_SECONDS = 1.2

Rect = Tuple[int, int, int, int]
FULL_SCREEN = ((0, 0), (1280, 720))
COURTYARD_REGION = ((500, 80), (800, 280))


@dataclass(frozen=True)
class MatchSpec:
    path: Path
    label: str
    threshold: float = MATCH_THRESHOLD


@dataclass(frozen=True)
class RecoveryResult:
    success: bool
    reason: str
    screenshot: Optional[str] = None


COURTYARD_TEMPLATE = HELPER_DIR / "Daily" / "CoopReward" / "explore.png"

# 用户指定的全屏识别优先级：2 > 4 > 1 > 3。
ACTION_SPECS = (
    ("courtyard", MatchSpec(ASSET_DIR / "courtyard.png", "返回庭院按钮")),
    ("back", MatchSpec(ASSET_DIR / "back.png", "返回按钮")),
    ("close_pink", MatchSpec(ASSET_DIR / "close_pink.png", "粉色关闭按钮")),
    ("close_red", MatchSpec(ASSET_DIR / "close_red.png", "红色关闭按钮")),
)


def _match(
    frame,
    name: str,
    spec: MatchSpec,
    region=FULL_SCREEN,
) -> tuple[Optional[float], Optional[Rect]]:
    score, rect = utils.crop_and_match(
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


def find_highest_priority_action(
    frame,
) -> tuple[Optional[str], Optional[MatchSpec], Optional[float], Optional[Rect]]:
    """在一张截图中按 2、4、1、3 的顺序返回首个命中的按钮。"""
    for name, spec in ACTION_SPECS:
        score, rect = _match(frame, name, spec)
        if rect is not None:
            return name, spec, score, rect
    return None, None, None, None


def _click_rect(rect: Rect, label: str) -> None:
    left, top, right, bottom = rect
    margin_x = max(1, (right - left) // 4)
    margin_y = max(1, (bottom - top) // 4)
    x = random.randint(left + margin_x, right - margin_x)
    y = random.randint(top + margin_y, bottom - margin_y)
    LOGGER.click(label, label, rect, (x, y))
    utils.adb_click(x, y)


def prune_failure_screenshots(keep_count: int = SCREENSHOT_KEEP_COUNT) -> int:
    """只保留最新的指定数量截图，返回本次删除数量。"""
    keep_count = max(0, int(keep_count))
    if not SCREENSHOT_DIR.is_dir():
        return 0
    screenshots = sorted(
        SCREENSHOT_DIR.glob("*.png"),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    removed = 0
    for path in screenshots[keep_count:]:
        try:
            path.unlink()
            removed += 1
        except OSError as exc:
            LOGGER.warning("截图清理", f"无法删除旧截图 {path.name}：{exc}")
    return removed


def _save_failure_screenshot(
    frame,
    stage: str,
    keep_count: int,
) -> Optional[str]:
    keep_count = max(0, int(keep_count))
    if keep_count == 0:
        prune_failure_screenshots(0)
        return None
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    milliseconds = int((time.time() % 1) * 1000)
    timestamp = time.strftime("%Y%m%d_%H%M%S") + f"_{milliseconds:03d}"
    output = SCREENSHOT_DIR / f"{stage}_{timestamp}.png"
    saved = utils.save_screenshot(str(output), frame=frame)
    prune_failure_screenshots(keep_count)
    return str(saved) if saved else None


def recover_to_courtyard(
    stop_event=None,
    *,
    timeout: float = RECOVERY_TIMEOUT_SECONDS,
    unknown_grace: float = UNKNOWN_STATE_GRACE_SECONDS,
    screenshot_keep_count: int = SCREENSHOT_KEEP_COUNT,
) -> RecoveryResult:
    """
    全屏识别安全返回按钮，直到检测到庭院探索灯笼。

    只在连续 ``unknown_grace`` 秒没有识别到庭院或四个按钮时判定未知；
    即使一直能识别并操作，整个恢复也不会超过 ``timeout`` 秒。
    """
    started_at = time.monotonic()
    unknown_since: Optional[float] = None
    last_frame = None
    click_count = 0
    LOGGER.info(
        "运行",
        "开始任务超时恢复，按钮优先级：返回庭院 > 返回 > 粉色关闭 > 红色关闭"
    )

    while time.monotonic() - started_at < timeout:
        if stop_event is not None and stop_event.is_set():
            return RecoveryResult(False, "用户请求停止，已取消超时恢复")

        frame = utils.take_screenshot()
        if frame is None:
            if unknown_since is None:
                unknown_since = time.monotonic()
            if time.monotonic() - unknown_since >= unknown_grace:
                return RecoveryResult(False, "连续无法获取游戏截图，超时恢复终止")
            time.sleep(SCREENSHOT_INTERVAL)
            continue

        last_frame = frame
        _, spec, score, rect = find_highest_priority_action(frame)
        if spec is not None and score is not None and rect is not None:
            unknown_since = None
            _click_rect(rect, f"{spec.label}（匹配分数 {score:.3f}）")
            click_count += 1
            time.sleep(POST_CLICK_DELAY_SECONDS)
            continue

        # 弹窗可能覆盖在庭院上且仍露出探索灯笼，因此先确认没有恢复按钮。
        if _is_courtyard(frame):
            reason = f"已恢复到庭院，共点击 {click_count} 次"
            LOGGER.info("运行", f"[SUCCESS] {reason}")
            return RecoveryResult(True, reason)

        if unknown_since is None:
            unknown_since = time.monotonic()
            LOGGER.info(
                "等待界面",
                f"当前未识别到恢复按钮，最多等待 {unknown_grace:.0f} 秒"
            )
        elif time.monotonic() - unknown_since >= unknown_grace:
            screenshot = _save_failure_screenshot(
                last_frame,
                "unknown",
                screenshot_keep_count,
            )
            reason = (
                f"连续 {unknown_grace:.0f} 秒未识别到庭院或恢复按钮，超时恢复终止"
            )
            LOGGER.error("运行", reason)
            return RecoveryResult(False, reason, screenshot)

        time.sleep(SCREENSHOT_INTERVAL)

    screenshot = _save_failure_screenshot(
        last_frame,
        "timeout",
        screenshot_keep_count,
    )
    reason = f"超时恢复运行超过 {timeout:.0f} 秒，仍未回到庭院"
    LOGGER.error("运行", reason)
    return RecoveryResult(False, reason, screenshot)


if __name__ == "__main__":
    result = recover_to_courtyard()
    raise SystemExit(0 if result.success else 1)

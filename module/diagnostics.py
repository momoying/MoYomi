"""统一保存任务、恢复和独立工具的报错现场截图。"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from module import automation
from module.logging import TaskLogger


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ERROR_SCREENSHOT_DIR = PROJECT_ROOT / "error_screenshots"
DEFAULT_KEEP_COUNT = 20
LOGGER = TaskLogger("报错截图")


def _slug(value: object, fallback: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or fallback


class ErrorScreenshotManager:
    """从最近缓存帧保存错误现场，并按全局数量清理旧图。"""

    def __init__(
        self,
        *,
        backend: Any = automation,
        directory: Path = ERROR_SCREENSHOT_DIR,
        keep_count: int = DEFAULT_KEEP_COUNT,
        warning: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.backend = backend
        self.directory = Path(directory)
        self.keep_count = max(0, int(keep_count))
        self.warning = warning or (
            lambda message: LOGGER.warning("保存现场", message)
        )

    def configure(self, keep_count: int) -> None:
        self.keep_count = max(0, int(keep_count))
        self.prune()

    def _warn(self, message: str) -> None:
        if self.warning is not None:
            try:
                self.warning(message)
            except Exception:
                pass

    def prune(self, keep_count: Optional[int] = None) -> int:
        keep = self.keep_count if keep_count is None else max(0, int(keep_count))
        if not self.directory.is_dir():
            return 0
        try:
            screenshots = sorted(
                self.directory.glob("*.png"),
                key=lambda path: (path.stat().st_mtime_ns, path.name),
                reverse=True,
            )
        except OSError as exc:
            self._warn(f"无法读取报错截图目录：{exc}")
            return 0

        removed = 0
        for path in screenshots[keep:]:
            try:
                path.unlink()
                removed += 1
            except OSError as exc:
                self._warn(f"无法删除旧报错截图 {path.name}：{exc}")
        return removed

    def _latest_frame(self):
        try:
            frame = self.backend.get_last_screenshot()
        except Exception as exc:
            self._warn(f"无法读取最近截图缓存：{exc}")
            frame = None
        if frame is not None:
            return frame
        try:
            return self.backend.take_screenshot()
        except Exception as exc:
            self._warn(f"无法获取报错现场截图：{exc}")
            return None

    def save(
        self,
        task: str,
        stage: str,
        *,
        attempt: int = 1,
        frame=None,
        keep_count: Optional[int] = None,
    ) -> Optional[str]:
        """保存一张错误现场；显式帧为空时优先使用最近缓存帧。"""
        keep = self.keep_count if keep_count is None else max(0, int(keep_count))
        if keep == 0:
            self.prune(0)
            return None

        current_frame = frame if frame is not None else self._latest_frame()
        if current_frame is None:
            self._warn("无法取得游戏画面，未保存报错截图")
            return None

        task_slug = _slug(task, "task")
        stage_slug = _slug(stage, "error")
        attempt_number = max(1, int(attempt))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = (
            f"{task_slug}_{stage_slug}_attempt_{attempt_number}_{timestamp}.png"
        )
        output = self.directory / filename
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            saved = self.backend.save_screenshot(str(output), frame=current_frame)
        except Exception as exc:
            self._warn(f"报错截图写入失败：{exc}")
            return None
        if not saved:
            self._warn(f"报错截图写入失败：{output.name}")
            return None
        self.prune(keep)
        return str(saved)


ERROR_SCREENSHOTS = ErrorScreenshotManager()


def configure_error_screenshots(keep_count: int) -> None:
    ERROR_SCREENSHOTS.configure(keep_count)


def prune_error_screenshots(keep_count: Optional[int] = None) -> int:
    return ERROR_SCREENSHOTS.prune(keep_count)


def capture_error_screenshot(
    task: str,
    stage: str,
    *,
    attempt: int = 1,
    frame=None,
    keep_count: Optional[int] = None,
) -> Optional[str]:
    return ERROR_SCREENSHOTS.save(
        task,
        stage,
        attempt=attempt,
        frame=frame,
        keep_count=keep_count,
    )

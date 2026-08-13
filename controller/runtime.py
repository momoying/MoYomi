"""中控日志与事件发送基础能力。"""

from __future__ import annotations

from typing import Any, Optional

from module.logging import TaskLogger
from controller.types import EventCallback


LOGGER = TaskLogger("中控")
print = LOGGER.legacy_print


def _emit_event(
    callback: Optional[EventCallback],
    event_type: str,
    **payload: Any,
) -> None:
    if callback is not None:
        callback({"type": event_type, **payload})

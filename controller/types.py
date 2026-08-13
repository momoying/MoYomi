"""中控使用的数据结构与回调类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from controller.constants import SAME_REGION


@dataclass
class ControllerServices:
    select_account: Callable[[str, bool], Optional[str]]
    exit_to_login: Callable[[], bool]
    sign_in: Callable[[str, str], bool]
    task_runners: dict[str, Callable[..., Any]]
    startup_recovery: Optional[Callable[[], Any]] = None
    task_timeout_recovery: Optional[Callable[[Any], Any]] = None
    task_recovery_retries: int = 1
    task_failure_recoveries: dict[str, Callable[[Any], Any]] = field(
        default_factory=dict
    )
    task_completion_recoveries: dict[str, Callable[[Any], Any]] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class TaskWork:
    task_name: str
    run_count: int


@dataclass(frozen=True)
class WorkItem:
    account_name: str
    system: str
    tasks: tuple[TaskWork, ...]
    region: str = SAME_REGION


EventCallback = Callable[[dict[str, Any]], None]

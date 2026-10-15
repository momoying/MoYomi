"""单次任务调用的阶段和失败现场；恢复、重试及截图由调用方安排。"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


class TaskCancelled(Exception):
    """用户停止当前调用，不属于任务失败。"""


@dataclass
class ExecutionReport:
    stage: Optional[str] = None
    reason: Optional[str] = None
    frame: Any = field(default=None, repr=False, compare=False)
    failure_frame: Any = field(default=None, repr=False, compare=False)
    exception: Optional[Exception] = field(default=None, repr=False, compare=False)
    cancelled: bool = False
    stop_event: Any = field(default=None, repr=False, compare=False)


_CURRENT: ContextVar[Optional[ExecutionReport]] = ContextVar("task_execution", default=None)


def in_task_call() -> bool:
    return _CURRENT.get() is not None


def current_stage() -> Optional[str]:
    report = _CURRENT.get()
    return report.stage if report is not None else None


def set_stage(stage: str) -> None:
    report = _CURRENT.get()
    if report is not None:
        report.stage = stage
        report.reason = None
        report.failure_frame = None


def record_frame(frame: Any) -> None:
    report = _CURRENT.get()
    if report is not None and frame is not None:
        report.frame = frame


def report_failure(reason: Optional[str] = None, *, frame: Any = None) -> None:
    report = _CURRENT.get()
    if report is not None:
        record_frame(frame)
        if reason:
            report.reason = reason
        if report.reason and report.frame is not None:
            copy = getattr(report.frame, "copy", None)
            report.failure_frame = copy() if callable(copy) else report.frame


def check_stopped() -> None:
    report = _CURRENT.get()
    if report is not None and report.stop_event is not None and report.stop_event.is_set():
        raise TaskCancelled()


def run_task_call(runner: Callable[..., Any], *args, stop_event=None, finish_current: bool = False, **kwargs):
    """保留原任务返回值，并独立报告本次调用的阶段、原因和最后有效帧。"""
    # 日常/周常等调用完成后再停；持续运行的小工具仍可在设备步骤间中止。
    report = ExecutionReport(stop_event=None if finish_current else stop_event)
    token = _CURRENT.set(report)
    value = None
    try:
        if stop_event is not None and stop_event.is_set():
            raise TaskCancelled()
        check_stopped()
        value = runner(*args, **kwargs)
        check_stopped()
    except TaskCancelled:
        report.cancelled = True
        report.reason = "用户请求停止"
    except Exception as exc:
        report.exception = exc
        report_failure(f"{type(exc).__name__}: {exc}")
    finally:
        if not finish_current and stop_event is not None and stop_event.is_set():
            report.cancelled = True
            report.reason = "用户请求停止"
        if report.failure_frame is not None:
            report.frame = report.failure_frame
        _CURRENT.reset(token)
    return value, report

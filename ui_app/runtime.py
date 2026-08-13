"""UI 日志、事件队列和安全刷新。"""

from __future__ import annotations

import asyncio
import importlib.util
import queue
import re
import sys
import threading
import traceback
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

import flet as ft

import main as controller
from module.appearance import DEFAULT_ACCENT, extract_monet_palette
from module.notifications import clear_project_sendkey, get_serverchan_sendkey, set_project_sendkey
from ui_app.constants import *
from ui_app.settings_store import *
from ui_app.components import *


class UiRuntimeMixin:
    def _safe_update(self) -> None:
        try:
            self.page.update()
        except Exception as exc:
            self._report_ui_exception("刷新页面", exc)


    def _report_ui_exception(self, context: str, exc: BaseException) -> None:
        """将 UI 无法展示的异常回退到启动控制台，并抑制重复刷屏。"""
        signature = (context, type(exc).__name__, str(exc))
        reported = getattr(self, "_reported_ui_errors", None)
        if reported is None:
            reported = set()
            self._reported_ui_errors = reported
        if signature in reported:
            return
        if len(reported) >= 100:
            reported.clear()
        reported.add(signature)

        stream = sys.__stderr__ or sys.stderr
        if stream is None:
            return
        try:
            timestamp = datetime.now().strftime("%H:%M:%S")
            stream.write(
                f"{timestamp} [ERROR] [UI/{context}] "
                f"{type(exc).__name__}: {exc}\n"
            )
            traceback.print_exception(
                type(exc),
                exc,
                exc.__traceback__,
                file=stream,
            )
            stream.flush()
        except Exception:
            # 控制台可能已随窗口关闭；异常上报本身不能影响 UI 工作线程。
            return


    def _append_ui_event_error(self, event_type: str, exc: BaseException) -> None:
        """尽量在 UI 内显示事件异常；失败时仍保留控制台 traceback。"""
        self._report_ui_exception(f"处理事件 {event_type}", exc)
        try:
            self._append_log_now(
                "ERROR",
                f"UI 事件处理失败（{event_type}）："
                f"{type(exc).__name__}: {exc}",
            )
        except Exception as render_exc:
            self._report_ui_exception("显示 UI 异常", render_exc)


    def append_log(self, level: str, message: str) -> None:
        """任意线程只入队，不直接修改 Flet 控件。"""
        if not message.strip():
            return
        self.ui_queue.put(("log", (level, message)))


    def _append_log_now(self, level: str, message: str) -> None:
        """仅由页面事件循环调用。"""
        standardized = re.match(
            r"^\d{2}:\d{2}:\d{2} \[(INFO|WARN|ERROR|SUCCESS|VISION|ACTION)\] ",
            message,
        )
        if standardized:
            level = standardized.group(1)
        elif "[ERROR]" in message:
            level = "ERROR"
        color = {
            "ERROR": COLORS["error"],
            "WARN": COLORS["warning"],
            "SUCCESS": COLORS["done"],
            "VISION": COLORS["active"],
            "ACTION": COLORS["done"],
        }.get(level, COLORS["muted"])
        rendered = message
        if not standardized:
            timestamp = datetime.now().strftime("%H:%M:%S")
            rendered = f"{timestamp} [{level}] [UI/运行] {message}"
        self.log_view.controls.append(
            ft.Text(
                rendered,
                size=11,
                color=color,
                font_family="Consolas",
                selectable=True,
            )
        )
        maximum = int(self.settings.get("log_max_lines", 300))
        if len(self.log_view.controls) > maximum:
            del self.log_view.controls[: len(self.log_view.controls) - maximum]


    def append_tool_log(self, level: str, message: str) -> None:
        if message.strip():
            self.ui_queue.put(("tool_log", (level, message)))


    def _append_tool_log_now(self, level: str, message: str) -> None:
        standardized = re.match(
            r"^\d{2}:\d{2}:\d{2} \[(INFO|WARN|ERROR|SUCCESS|VISION|ACTION)\] ",
            message,
        )
        if standardized:
            level = standardized.group(1)
        else:
            inline_level = re.match(
                r"^\[(INFO|WARN|ERROR|SUCCESS|VISION|ACTION)\]\s*(.*)$",
                message,
                flags=re.DOTALL,
            )
            if inline_level:
                level = inline_level.group(1)
                message = inline_level.group(2)
            elif "[ERROR]" in message:
                level = "ERROR"
        color = {
            "ERROR": COLORS["error"],
            "WARN": COLORS["warning"],
            "SUCCESS": COLORS["done"],
            "VISION": COLORS["active"],
            "ACTION": COLORS["done"],
        }.get(level, COLORS["muted"])
        rendered = message
        logged_at = datetime.now()
        if not standardized:
            timestamp = logged_at.strftime("%H:%M:%S")
            rendered = f"{timestamp} [{level}] [小工具/运行] {message}"
        else:
            parsed_time = datetime.strptime(message[:8], "%H:%M:%S").time()
            logged_at = datetime.combine(logged_at.date(), parsed_time)
            now = datetime.now()
            if logged_at - now > timedelta(hours=12):
                logged_at -= timedelta(days=1)
            elif now - logged_at > timedelta(hours=12):
                logged_at += timedelta(days=1)

        self.tool_log_sequence += 1
        control = ft.Text(
            rendered,
            size=11,
            color=color,
            font_family="Consolas",
            selectable=True,
        )
        control.data = (logged_at.timestamp(), self.tool_log_sequence)
        self.tool_log_view.controls.append(control)
        self.tool_log_view.controls.sort(
            key=lambda item: item.data
            if isinstance(item.data, tuple)
            else (float("inf"), 0)
        )
        maximum = int(self.settings.get("log_max_lines", 300))
        if len(self.tool_log_view.controls) > maximum:
            del self.tool_log_view.controls[
                : len(self.tool_log_view.controls) - maximum
            ]


    async def _ui_update_pump(self) -> None:
        """在 Flet 页面事件循环中消费日志/状态，避免工作线程直接刷 UI。"""
        while True:
            try:
                changed = False
                # 限制单次处理量，避免大量 OCR 输出时卡住页面循环。
                for _ in range(100):
                    try:
                        event_type, payload = self.ui_queue.get_nowait()
                    except queue.Empty:
                        break

                    changed = True
                    try:
                        if event_type == "log":
                            level, message = payload
                            self._append_log_now(level, message)
                        elif event_type == "tool_log":
                            level, message = payload
                            self._append_tool_log_now(level, message)
                        elif event_type == "controller_event":
                            self._apply_controller_event(payload)
                        elif event_type == "worker_finished":
                            self._apply_worker_finished(**payload)
                        elif event_type == "tool_finished":
                            self._apply_tool_finished(**payload)
                        elif event_type == "secret_attempts":
                            self._apply_secret_attempts(payload)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        # 单条坏事件不能终止整个日志泵；继续处理后续日志。
                        self._append_ui_event_error(str(event_type), exc)

                if changed:
                    try:
                        self.page.update()
                    except Exception as exc:
                        # 会话短暂断开或控件刷新失败时保留消费循环。
                        self._report_ui_exception("刷新日志面板", exc)
                await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                # 兜住循环自身的意外错误，避免日志通道永久静默。
                self._report_ui_exception("日志刷新循环", exc)
                await asyncio.sleep(0.1)

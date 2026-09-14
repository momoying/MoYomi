"""UI 可复用视图组件。"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any, Callable, Optional

import flet as ft

import main as controller
from ui_app.constants import *


class LineWriter(io.TextIOBase):
    """Convert controller/task print output into UI log lines."""

    def __init__(self, callback: Callable[[str], None]) -> None:
        self.callback = callback
        self.buffer = ""

    def writable(self) -> bool:
        return True

    def write(self, value: str) -> int:
        self.buffer += str(value).replace("\r\n", "\n").replace("\r", "\n")
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line.strip():
                self.callback(line.rstrip())
        return len(value)

    def flush(self) -> None:
        if self.buffer.strip():
            self.callback(self.buffer.rstrip())
        self.buffer = ""


class AccountCardView:
    def __init__(
        self,
        account: str,
        system: str,
        system_state: dict[str, Any],
        now: datetime,
        task_mode: str = controller.DAILY_MODE,
    ) -> None:
        self.account = account
        self.system = system
        self.task_mode = task_mode
        self.status = "pending"
        self.status_text = ft.Text(size=11, color=COLORS["muted"])
        self.task_views: dict[str, TaskStatusView] = {}

        task_order = (
            WEEKLY_UI_TASK_ORDER
            if task_mode == controller.WEEKLY_MODE
            else UI_TASK_ORDER
        )
        for task_name in task_order:
            if task_mode == controller.WEEKLY_MODE:
                record = system_state[controller.CONSIGNMENT_HOUSE_TASK]
                enabled = True
                due_count = int(controller.weekly_consignment_is_due(record, now))
                available = True
            else:
                enabled = controller.combined_task_is_enabled(system_state, task_name)
                due_count = (
                    controller.combined_task_runs_due(task_name, system_state, now)
                    if enabled
                    else 0
                )
                available = controller.task_is_available(task_name, now)
            completed_detail = None
            if task_name == controller.BOUNTY_TASK:
                completed_detail = controller.combined_bounty_detail(system_state)
            elif task_name == controller.MERCHANT_TASK:
                completed_detail = controller.MERCHANT_RESULT_DETAILS.get(
                    controller.task_record_result(
                        system_state,
                        controller.MERCHANT_TASK,
                    ),
                    "当前周期已检查",
                )
            elif task_name == controller.HEART_TEAM_TASK:
                role = controller.heart_team_role(system_state)
                role_label = controller.HEART_TEAM_ROLE_DETAILS.get(
                    role,
                    "身份未配置",
                )
                completed_detail = (
                    f"{role_label} · "
                    + (
                        "本轮补存已完成"
                        if role == "member"
                        else "今日战斗已完成"
                    )
                )
            elif task_name == controller.CONSIGNMENT_HOUSE_TASK:
                completed_detail = (
                    "本周购买完成"
                    if record.get("result") == controller.CONSIGNMENT_PURCHASED
                    else "本周已购买"
                )
            task_view = TaskStatusView(
                task_name,
                due_count,
                completed_detail=completed_detail,
                available=available,
                enabled=enabled,
            )
            if task_name == controller.BOUNTY_TASK:
                bounty_style = BOUNTY_HIGHLIGHT_STYLES.get(
                    controller.combined_bounty_highlight_result(system_state)
                )
                task_view.set_highlight(
                    due_count == 0 and bounty_style is not None,
                    bounty_style or "default",
                )
            elif task_name == controller.MERCHANT_TASK:
                merchant_style = MERCHANT_HIGHLIGHT_STYLES.get(
                    controller.task_record_result(
                        system_state,
                        controller.MERCHANT_TASK,
                    )
                )
                task_view.set_highlight(
                    due_count == 0 and merchant_style is not None,
                    merchant_style or "default",
                )
                if task_view.status == "unavailable":
                    task_view.control.visible = False
            self.task_views[task_name] = task_view

        system_icon = (
            ft.Icons.PHONE_IPHONE_ROUNDED
            if system == "IOS"
            else ft.Icons.ANDROID_ROUNDED
        )
        system_color = "#A78BFA" if system == "IOS" else "#65D68A"
        system_badge = ft.Container(
            bgcolor=f"{system_color}22",
            border=ft.Border.all(1, f"{system_color}66"),
            border_radius=999,
            padding=ft.Padding.symmetric(horizontal=9, vertical=4),
            content=ft.Row(
                [
                    ft.Icon(system_icon, color=system_color, size=14),
                    ft.Text(
                        system,
                        color=system_color,
                        size=11,
                        weight=ft.FontWeight.BOLD,
                    ),
                ],
                spacing=5,
                tight=True,
            ),
        )
        self.task_grid = ft.ResponsiveRow(
            [self.task_views[name].control for name in task_order],
            columns=12,
            spacing=8,
            run_spacing=8,
        )
        for control in self.task_grid.controls:
            control.col = 12 if task_mode == controller.WEEKLY_MODE else 6

        self.control = ft.Container(
            col={"xs": 12, "sm": 6, "md": 4},
            bgcolor=COLORS["panel_alt"],
            border_radius=16,
            padding=14,
            border=ft.Border.all(1, COLORS["border"]),
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Container(
                                width=38,
                                height=38,
                                border_radius=12,
                                bgcolor="#24324A",
                                alignment=ft.Alignment.CENTER,
                                content=ft.Icon(
                                    ft.Icons.PERSON_ROUNDED,
                                    color="#B7C8E2",
                                    size=22,
                                ),
                            ),
                            ft.Column(
                                [
                                    ft.Text(
                                        account,
                                        size=14,
                                        weight=ft.FontWeight.BOLD,
                                        color=COLORS["text"],
                                        overflow=ft.TextOverflow.ELLIPSIS,
                                    ),
                                    self.status_text,
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            system_badge,
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Divider(height=4, color="transparent"),
                    self.task_grid,
                ],
                spacing=8,
            ),
        )
        self.refresh_overall()

    def refresh_key_results(self) -> None:
        """保持关键任务展示状态与任务开放时间同步。"""
        if self.task_mode != controller.DAILY_MODE:
            return
        merchant = self.task_views[controller.MERCHANT_TASK]
        if merchant.status == "unavailable":
            merchant.control.visible = False

    def important_result_labels(self) -> list[str]:
        """返回当前可见、值得用户关注的悬赏与奸商结果。"""
        if self.task_mode != controller.DAILY_MODE:
            return []
        labels: list[str] = []
        for task_name in (controller.BOUNTY_TASK, controller.MERCHANT_TASK):
            view = self.task_views[task_name]
            if not view.control.visible or view.status != "done" or not view.highlighted:
                continue
            labels.append(str(view.detail.value))
        return labels

    def set_phase(self, status: str, text: str) -> None:
        self.status = status
        self.status_text.value = text
        self.status_text.color = COLORS.get(status, COLORS["muted"])
        border_color = COLORS.get(status, COLORS["border"])
        border_width = 2 if status in {"active", "error"} else 1
        self.control.border = ft.Border.all(border_width, border_color)

    def refresh_overall(self) -> None:
        task_statuses = {view.status for view in self.task_views.values()}
        if "error" in task_statuses:
            self.set_phase("error", "执行失败")
        elif "active" in task_statuses:
            self.set_phase("active", "正在执行")
        elif task_statuses <= {"done", "unavailable", "disabled"}:
            self.set_phase("done", "当前任务全部完成")
        else:
            self.set_phase("pending", "等待进入队列")


class TaskStatusView:
    def __init__(
        self,
        task_name: str,
        due_count: int,
        completed_detail: Optional[str] = None,
        available: bool = True,
        enabled: bool = True,
    ) -> None:
        self.task_name = task_name
        self.status = (
            "disabled"
            if not enabled
            else ("unavailable" if not available else ("pending" if due_count else "done"))
        )
        self.highlighted = False
        self.highlight_style = "default"
        self.icon = ft.Icon(TASK_ICONS[task_name], size=16)
        self.title = ft.Text(
            controller.TASK_LABELS[task_name],
            size=12,
            weight=ft.FontWeight.W_600,
            color=COLORS["text"],
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        detail = "待执行" + (f" ×{due_count}" if due_count > 1 else "")
        if not enabled:
            detail = "已禁用"
        elif not available:
            detail = "今日未开放"
        self.detail = ft.Text(
            detail
            if (due_count or not available or not enabled)
            else (completed_detail or "当前周期已完成"),
            size=10,
            color=COLORS["muted"],
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self.control = ft.Container(
            padding=ft.Padding.symmetric(horizontal=9, vertical=8),
            border_radius=10,
            content=ft.Row(
                [
                    self.icon,
                    ft.Column([self.title, self.detail], spacing=1, expand=True),
                ],
                spacing=7,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )
        self.set_status(self.status, self.detail.value)

    def set_status(self, status: str, detail: str) -> None:
        self.status = status
        styles = {
            "done": (ft.Icons.CHECK_CIRCLE_ROUNDED, COLORS["done"], COLORS["done_bg"]),
            "active": (ft.Icons.SYNC_ROUNDED, COLORS["active"], COLORS["active_bg"]),
            "error": (ft.Icons.ERROR_ROUNDED, COLORS["error"], COLORS["error_bg"]),
            "warning": (ft.Icons.PAUSE_CIRCLE_ROUNDED, COLORS["warning"], COLORS["warning_bg"]),
            "unavailable": (
                TASK_ICONS[self.task_name],
                "#566174",
                "#171E2A",
            ),
            "disabled": (
                ft.Icons.BLOCK_ROUNDED,
                "#566174",
                "#171E2A",
            ),
            "pending": (
                TASK_ICONS[self.task_name],
                COLORS["pending"],
                COLORS["pending_bg"],
            ),
        }
        icon, color, background = styles[status]
        self.icon.icon = icon
        self.icon.color = color
        self.title.color = (
            color
            if status in {"unavailable", "disabled"}
            else COLORS["text"]
        )
        self.detail.value = detail
        self.detail.color = color if status in {"active", "error", "warning"} else COLORS["muted"]
        show_highlight = self.highlighted and status == "done"
        highlight = TASK_HIGHLIGHT_STYLES[self.highlight_style]
        if show_highlight:
            self.icon.color = highlight["border"]
            self.detail.color = highlight["border"]
        self.control.bgcolor = None if show_highlight else background
        self.control.gradient = (
            ft.LinearGradient(
                begin=ft.Alignment.TOP_LEFT,
                end=ft.Alignment.BOTTOM_RIGHT,
                colors=list(highlight["colors"]),
            )
            if show_highlight
            else None
        )
        self.control.border = ft.Border.all(
            highlight["width"] if show_highlight else 1,
            highlight["border"] if show_highlight else color,
        )

    def set_highlight(self, enabled: bool, style: str = "default") -> None:
        self.highlighted = enabled
        self.highlight_style = style if enabled else "default"
        self.set_status(self.status, self.detail.value)

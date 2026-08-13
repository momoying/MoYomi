"""日常任务页面与中控事件处理。"""

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


class DailyPageMixin:
    def _build_daily_page(self) -> ft.Control:
        task_filter = ft.Row(
            [
                ft.Column(
                    [
                        ft.Text(
                            "周常任务",
                            size=12,
                            color=COLORS["muted"],
                            text_align=ft.TextAlign.CENTER,
                        ),
                        self.weekly_mode_switch,
                    ],
                    spacing=1,
                    tight=True,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(width=1, height=46, bgcolor=COLORS["border"]),
                ft.Column(
                    [
                        ft.Text(
                            "隐藏不可用任务",
                            size=12,
                            color=COLORS["muted"],
                            text_align=ft.TextAlign.CENTER,
                        ),
                        self.hide_unavailable_tasks,
                    ],
                    spacing=1,
                    tight=True,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            spacing=8,
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        accounts_panel = self._panel(
            "账号 / 角色状态",
            ft.Icons.GROUP_ROUNDED,
            self.cards_grid,
            expand=True,
            subtitle=self.summary_text,
            heading_extra=task_filter,
            compact_heading=True,
            actions=ft.Row(
                [
                    self.refresh_button,
                    self.start_button,
                ],
                spacing=10,
            ),
        )
        log_panel = self._panel(
            "日常 / 周常任务日志",
            ft.Icons.TERMINAL_ROUNDED,
            self.log_view,
            expand=True,
        )
        body = ft.Row(
            [
                accounts_panel,
                ft.Container(log_panel, width=410),
            ],
            spacing=14,
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        return body


    def refresh_cards(self, update: bool = True) -> bool:
        try:
            daily_state, migrated = controller.load_state(controller.STATUS_PATH)
            if migrated:
                controller.save_state(daily_state, controller.STATUS_PATH)
            if self.task_mode == controller.WEEKLY_MODE:
                state, weekly_migrated = controller.load_weekly_state(
                    controller.WEEKLY_STATUS_PATH,
                    daily_state,
                )
                if weekly_migrated or not controller.WEEKLY_STATUS_PATH.is_file():
                    controller.save_weekly_state(
                        state,
                        controller.WEEKLY_STATUS_PATH,
                    )
                active_accounts = daily_state["accounts"]
            else:
                state = daily_state
                active_accounts = daily_state["accounts"]
        except Exception as exc:
            self.append_log("ERROR", f"无法读取账号状态：{exc}")
            return False

        now = datetime.now().astimezone()
        self.cards.clear()
        self.cards_grid.controls.clear()
        for account, account_state in active_accounts.items():
            for system in account_state["systems"]:
                system_state = state["accounts"][account]["systems"][system]
                card = AccountCardView(
                    account,
                    system,
                    system_state,
                    now,
                    task_mode=self.task_mode,
                )
                self.cards[(account, system)] = card
                self.cards_grid.controls.append(card.control)
        self._apply_task_visibility()
        self._refresh_task_summary()
        if update:
            self._safe_update()
        return True


    def _refresh_task_summary(self) -> None:
        unfinished_statuses = {"pending", "active", "warning", "error"}
        due_systems = sum(
            any(
                view.status in unfinished_statuses
                for view in card.task_views.values()
            )
            for card in self.cards.values()
        )
        self.summary_text.value = (
            f"{len(self.cards)} 个角色 · {due_systems} 个待执行"
        )


    def refresh_status(self, _event: Any = None) -> None:
        if self.running:
            return
        if self.refresh_cards():
            status_file = (
                "config/weekly_account_status.json"
                if self.task_mode == controller.WEEKLY_MODE
                else "config/account_status.json"
            )
            self.append_log("INFO", f"已重新读取 {status_file}")


    def _apply_task_visibility(self) -> None:
        hide_unavailable = bool(self.hide_unavailable_tasks.value)
        for card in self.cards.values():
            for task_view in card.task_views.values():
                task_view.control.visible = not (
                    hide_unavailable
                    and task_view.status in {"unavailable", "disabled"}
                )


    def _on_hide_unavailable_changed(self, _event: Any = None) -> None:
        self._apply_task_visibility()
        self.settings["hide_unavailable_tasks"] = bool(
            self.hide_unavailable_tasks.value
        )
        try:
            save_ui_settings(self.settings)
        except OSError as exc:
            self.append_log("ERROR", f"保存任务显示设置失败：{exc}")
        self._safe_update()


    def _on_task_mode_changed(self, _event: Any = None) -> None:
        if self.running:
            return
        self.task_mode = (
            controller.WEEKLY_MODE
            if self.weekly_mode_switch.value
            else controller.DAILY_MODE
        )
        self.refresh_cards(update=False)
        label = "周常" if self.task_mode == controller.WEEKLY_MODE else "日常"
        self.append_log("INFO", f"已切换到{label}任务")
        self._safe_update()


    def start_run(self, _event: Any = None) -> None:
        if self.running:
            return
        if self.tool_running:
            self.append_log("ERROR", "小工具正在运行，不能同时启动一键长草")
            return
        if not self.save_settings():
            self._show_section("settings")
            return
        if not self.refresh_cards():
            return
        self.stop_event.clear()
        self.running = True
        self.current_key = None
        self.start_button.content = "停止"
        self.start_button.icon = ft.Icons.STOP_ROUNDED
        self.start_button.bgcolor = COLORS["error_bg"]
        self.start_button.color = COLORS["error"]
        self.refresh_button.disabled = True
        self.weekly_mode_switch.disabled = True
        self._set_global_settings_disabled(True)
        self.tool_start_button.disabled = True
        self.running_badge.visible = True
        mode_label = "周常" if self.task_mode == controller.WEEKLY_MODE else "日常"
        self.running_badge_text.value = f"{mode_label}任务运行中"
        self.settings_message.value = ""
        self.append_log("INFO", f"开始生成{mode_label}待执行队列")
        self._safe_update()
        self.page.run_thread(self._controller_worker)


    def request_stop(self, _event: Any = None) -> None:
        if not self.running:
            return
        self.stop_event.set()
        self.start_button.disabled = True
        self.start_button.content = "停止中"
        if self.current_key in self.cards:
            self.cards[self.current_key].set_phase("warning", "等待当前步骤结束")
        self.append_log("WARN", "已请求安全停止，当前登录或任务阶段结束后生效")
        self._safe_update()


    def toggle_daily_run(self, event: Any = None) -> None:
        if self.running:
            self.request_stop(event)
        else:
            self.start_run(event)


    def _controller_worker(self) -> None:
        writer = LineWriter(lambda line: self.append_log("INFO", line))
        success = False
        try:
            with redirect_stdout(writer), redirect_stderr(writer):
                success = controller.run(
                    event_callback=self.handle_controller_event,
                    stop_event=self.stop_event,
                    runtime_settings=self.settings,
                    task_mode=self.task_mode,
                )
        except Exception as exc:
            self.append_log("ERROR", f"中控未捕获异常：{exc}")
            self._report_ui_exception("中控后台线程", exc)
        finally:
            writer.flush()
            self.ui_queue.put(
                (
                    "worker_finished",
                    {
                        "success": success,
                        "stopped": self.stop_event.is_set(),
                    },
                )
            )


    def _apply_worker_finished(
        self,
        success: bool,
        stopped: bool,
    ) -> None:
        """在 UI 事件循环中收尾，避免工作线程跨线程修改控件。"""
        self.running = False
        self.start_button.disabled = False
        self.start_button.content = "开始"
        self.start_button.icon = ft.Icons.PLAY_ARROW_ROUNDED
        self.start_button.bgcolor = COLORS["active"]
        self.start_button.color = "#07111F"
        self.refresh_button.disabled = False
        if hasattr(self, "weekly_mode_switch"):
            self.weekly_mode_switch.disabled = False
        self._set_global_settings_disabled(False)
        self.tool_start_button.disabled = False
        self.running_badge.visible = False
        # 无论成功、停止还是失败，都从持久化状态重建卡片。失败事件会
        # 临时修改任务图标和卡片边框；若不重建，这些运行态控件会一直
        # 残留，后续刷新布局时看起来像错位或卡住。
        self.current_key = None
        self.refresh_cards(update=False)
        if success:
            self._append_log_now("SUCCESS", "本轮到期任务已处理完成")
        elif stopped:
            self._append_log_now("WARN", "本轮任务已停止")
        else:
            self._append_log_now(
                "ERROR",
                "本轮执行失败，运行态界面已复位；错误详情请查看上方日志",
            )


    def handle_controller_event(self, event: dict[str, Any]) -> None:
        """中控回调在工作线程执行，只负责将状态事件入队。"""
        self.ui_queue.put(("controller_event", event))


    def _apply_controller_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        account = event.get("account")
        system = event.get("system")
        key = (account, system) if account and system else None
        card = self.cards.get(key) if key else None

        if event_type == "queue_built":
            queue = event.get("queue", [])
            self._append_log_now("INFO", f"待执行队列共 {len(queue)} 个账号/系统")
        elif event_type == "account_started" and card is not None:
            self.current_key = key
            card.set_phase("active", "正在切换账号")
        elif event_type == "account_phase" and card is not None:
            card.set_phase("active", "正在登录游戏")
        elif event_type == "task_started" and card is not None:
            task_name = event["task"]
            run_index = event.get("run_index", 1)
            run_count = event.get("run_count", 1)
            detail = "正在执行"
            if run_count > 1:
                detail += f" · {run_index}/{run_count}"
            card.task_views[task_name].set_status("active", detail)
            if task_name in {controller.BOUNTY_TASK, controller.MERCHANT_TASK}:
                card.task_views[task_name].set_highlight(False)
            card.set_phase("active", f"正在执行：{controller.TASK_LABELS[task_name]}")
        elif event_type == "task_completed" and card is not None:
            task_name = event["task"]
            detail = event.get("detail") or "本轮已完成"
            card.task_views[task_name].set_status("done", detail)
            if task_name == controller.BOUNTY_TASK:
                bounty_style = BOUNTY_HIGHLIGHT_STYLES.get(event.get("result"))
                card.task_views[task_name].set_highlight(
                    bounty_style is not None,
                    bounty_style or "default",
                )
            elif task_name == controller.MERCHANT_TASK:
                merchant_style = MERCHANT_HIGHLIGHT_STYLES.get(event.get("result"))
                card.task_views[task_name].set_highlight(
                    merchant_style is not None,
                    merchant_style or "default",
                )
            card.refresh_overall()
        elif event_type == "error":
            message = str(event.get("message", "未知错误"))
            if card is not None:
                task_name = event.get("task")
                if task_name in card.task_views:
                    card.task_views[task_name].set_status("error", message)
                    location = controller.TASK_LABELS[task_name]
                else:
                    location = {
                        "startup_recovery": "启动界面恢复",
                        "select_account": "切换账号",
                        "sign_in": "登录",
                        "load_modules": "加载任务模块",
                    }.get(event.get("phase"), "中控")
                card.set_phase("error", f"卡在：{location}")
            self._append_log_now("ERROR", message)
        elif event_type == "controller_stopped" and card is not None:
            card.set_phase("warning", "已安全停止")
        self._apply_task_visibility()
        self._refresh_task_summary()

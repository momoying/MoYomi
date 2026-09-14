"""日常任务页面与中控事件处理。"""

from __future__ import annotations

import asyncio
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
from typing import Any

import flet as ft

import main as controller

from ui_app.components import *
from ui_app.constants import *
from ui_app.settings_store import *


def parse_one_shot_run_at(
    date_text: str,
    time_text: str,
    now: datetime,
) -> datetime:
    """解析分钟级单次闹钟；当前分钟仍允许立即触发。"""
    if now.tzinfo is None:
        now = now.astimezone()
    try:
        parsed = datetime.strptime(
            f"{date_text.strip()} {time_text.strip()}",
            "%Y-%m-%d %H:%M",
        )
    except ValueError as exc:
        raise ValueError("日期或时间格式不正确") from exc
    scheduled_at = parsed.replace(tzinfo=now.tzinfo)
    if scheduled_at < now.replace(second=0, microsecond=0):
        raise ValueError("闹钟时间不能早于当前分钟")
    return scheduled_at


class DailyPageMixin:
    def _build_daily_page(self) -> ft.Control:
        task_filter = ft.Row(
            [
                ft.Column(
                    [
                        ft.Text(
                            "任务类型",
                            size=12,
                            color=COLORS["muted"],
                            text_align=ft.TextAlign.CENTER,
                        ),
                        self.task_mode_selector,
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
        self.important_results_bar = ft.Container(
            bgcolor="#AA171E2A",
            border=ft.Border.all(1, COLORS["border"]),
            border_radius=12,
            padding=ft.Padding.symmetric(horizontal=12, vertical=8),
            content=ft.Row(
                [
                    ft.Row(
                        [
                            ft.Icon(
                                ft.Icons.AUTO_AWESOME_ROUNDED,
                                size=16,
                                color=COLORS["warning"],
                            ),
                            self.important_summary_text,
                        ],
                        spacing=7,
                        expand=True,
                    ),
                    self.important_filter_button,
                ],
                spacing=8,
            ),
        )
        accounts_content = ft.Column(
            [self.important_results_bar, self.cards_grid],
            spacing=10,
            expand=True,
        )
        accounts_panel = self._panel(
            "账号 / 角色状态",
            ft.Icons.GROUP_ROUNDED,
            accounts_content,
            expand=True,
            subtitle=self.summary_text,
            heading_extra=task_filter,
            compact_heading=True,
            actions=ft.Row(
                [
                    self.refresh_button,
                    self.schedule_button,
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
        if hasattr(self, "important_results_bar"):
            self.important_results_bar.visible = (
                self.task_mode == controller.DAILY_MODE
            )
        important_results = Counter(
            label
            for card in self.cards.values()
            for label in card.important_result_labels()
        )
        if important_results:
            rendered = " · ".join(
                f"{label} ×{count}" if count > 1 else label
                for label, count in important_results.items()
            )
            self.important_summary_text.value = f"重要结果：{rendered}"
            self.important_summary_text.color = COLORS["warning"]
        else:
            merchant_open = controller.task_is_available(
                controller.MERCHANT_TASK,
                datetime.now().astimezone(),
            )
            scope = "悬赏和奸商" if merchant_open else "悬赏"
            self.important_summary_text.value = f"当前没有需要关注的{scope}结果"
            self.important_summary_text.color = COLORS["muted"]
        self.important_filter_button.content = (
            "显示全部" if self.show_important_only else "只看有结果"
        )
        self.important_filter_button.bgcolor = (
            COLORS["active_bg"] if self.show_important_only else None
        )


    def toggle_important_filter(self, _event: Any = None) -> None:
        if self.task_mode != controller.DAILY_MODE:
            return
        self.show_important_only = not self.show_important_only
        self._apply_task_visibility()
        self._refresh_task_summary()
        self._safe_update()


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
            card.control.visible = not self.show_important_only or bool(
                card.important_result_labels()
            )
            for task_name, task_view in card.task_views.items():
                merchant_closed = (
                    task_name == controller.MERCHANT_TASK
                    and task_view.status == "unavailable"
                )
                task_view.control.visible = not merchant_closed and not (
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
        selected = list(self.task_mode_selector.selected)
        self.task_mode = selected[0] if selected else controller.DAILY_MODE
        if self.task_mode == controller.WEEKLY_MODE:
            self.show_important_only = False
        self.refresh_cards(update=False)
        label = "周常" if self.task_mode == controller.WEEKLY_MODE else "日常"
        self.append_log("INFO", f"已切换到{label}任务")
        self._safe_update()


    def open_schedule_dialog(self, _event: Any = None) -> None:
        if self._scheduled_run_at is not None:
            draft = self._scheduled_run_at
            self.schedule_mode_selector.selected = [self._scheduled_run_mode]
        else:
            draft = datetime.now().astimezone() + timedelta(minutes=1)
            self.schedule_mode_selector.selected = [self.task_mode]
        self.schedule_date_field.value = draft.strftime("%Y-%m-%d")
        self.schedule_time_field.value = draft.strftime("%H:%M")
        self.cancel_schedule_button.visible = self._scheduled_run_at is not None
        self.schedule_message.value = (
            self._schedule_alarm_text()
            if self._scheduled_run_at is not None
            else "设置后仅在本次应用运行期间有效"
        )
        self.schedule_message.color = COLORS["muted"]
        self.page.show_dialog(self.schedule_dialog)


    def close_schedule_dialog(self, _event: Any = None) -> None:
        self.page.pop_dialog()


    def _on_schedule_draft_changed(self, _event: Any = None) -> None:
        self.schedule_message.value = "闹钟尚未设置"
        self.schedule_message.color = COLORS["warning"]
        self._safe_update()


    def save_schedule(self, _event: Any = None) -> None:
        try:
            scheduled_at = parse_one_shot_run_at(
                str(self.schedule_date_field.value or ""),
                str(self.schedule_time_field.value or ""),
                datetime.now().astimezone(),
            )
        except ValueError as exc:
            self.schedule_message.value = (
                f"{exc}；请使用 YYYY-MM-DD 和 HH:MM 格式"
            )
            self.schedule_message.color = COLORS["error"]
            self._safe_update()
            return
        selected_modes = list(self.schedule_mode_selector.selected)
        self._scheduled_run_mode = (
            selected_modes[0] if selected_modes else controller.DAILY_MODE
        )
        self._scheduled_run_at = scheduled_at
        self._refresh_schedule_summary()
        self.close_schedule_dialog()
        self.append_log("INFO", f"单次闹钟已设置：{self._schedule_alarm_text()}")
        self._safe_update()


    def _schedule_alarm_text(self) -> str:
        if self._scheduled_run_at is None:
            return "当前没有单次闹钟"
        mode = (
            "周常"
            if self._scheduled_run_mode == controller.WEEKLY_MODE
            else "日常"
        )
        return f"{self._scheduled_run_at:%Y-%m-%d %H:%M} · {mode}"


    def _refresh_schedule_summary(self) -> None:
        if self._scheduled_run_at is not None:
            self.schedule_button.content = f"闹钟 {self._scheduled_run_at:%m-%d %H:%M}"
            self.schedule_button.bgcolor = COLORS["active_bg"]
            self.schedule_button.color = COLORS["active"]
            self.schedule_button.tooltip = self._schedule_alarm_text()
        else:
            self.schedule_button.content = "设置定时"
            self.schedule_button.bgcolor = None
            self.schedule_button.color = None
            self.schedule_button.tooltip = "设置仅在本次应用运行期间有效的单次闹钟"


    def cancel_schedule(self, _event: Any = None) -> None:
        had_alarm = self._scheduled_run_at is not None
        self._scheduled_run_at = None
        self._refresh_schedule_summary()
        self.close_schedule_dialog()
        if had_alarm:
            self.append_log("INFO", "单次闹钟已取消")
        self._safe_update()


    async def _schedule_pump(self) -> None:
        """在应用存活期间触发一次内存闹钟，触发后立即清除。"""
        await asyncio.sleep(1)
        while True:
            try:
                now = datetime.now().astimezone()
                scheduled_at = self._scheduled_run_at
                if scheduled_at is None or now < scheduled_at:
                    await asyncio.sleep(5)
                    continue

                schedule_mode = self._scheduled_run_mode
                # 单次闹钟一到点便失效，无论后续能否真正启动任务。
                self._scheduled_run_at = None
                self._refresh_schedule_summary()

                if self.running or self.tool_running:
                    self.append_log("WARN", "单次闹钟到点，但当前已有任务运行，本次已取消")
                    self._safe_update()
                    await asyncio.sleep(5)
                    continue

                self.task_mode = schedule_mode
                self.task_mode_selector.selected = [schedule_mode]
                self.refresh_cards(update=False)
                mode_label = "周常" if schedule_mode == controller.WEEKLY_MODE else "日常"
                self.append_log("INFO", f"单次闹钟已触发：{mode_label}")
                self.start_run()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                self._report_ui_exception("定时执行", exc)
                self.append_log("ERROR", f"定时执行异常：{exc}")
            await asyncio.sleep(5)


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
        self.task_mode_selector.disabled = True
        self.schedule_button.disabled = True
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
        if hasattr(self, "task_mode_selector"):
            self.task_mode_selector.disabled = False
        if hasattr(self, "schedule_button"):
            self.schedule_button.disabled = False
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
        if card is not None:
            card.refresh_key_results()
        self._apply_task_visibility()
        self._refresh_task_summary()

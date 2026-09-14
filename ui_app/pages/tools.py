"""独立工具页面与运行线程。"""

from __future__ import annotations

import importlib.util
import sys
from contextlib import redirect_stderr, redirect_stdout
from typing import Any, Optional

import flet as ft

from ui_app.components import *
from ui_app.constants import *
from ui_app.settings_store import *


class ToolsPageMixin:
    def _build_tool_selector(self) -> ft.Container:
        controls = []
        for key, label in TOOL_LABELS.items():
            item = ft.Container(
                data=key,
                padding=ft.Padding.symmetric(horizontal=20, vertical=10),
                border_radius=8,
                bgcolor="#171E2A",
                content=ft.Text(label, size=13, color=COLORS["text"]),
                on_click=self._on_tool_selected,
            )
            self.tool_nav_items[key] = item
            controls.append(item)
        self._apply_tool_navigation_style()
        return ft.Container(
            bgcolor="#20232B",
            border_radius=10,
            padding=4,
            content=ft.Row(controls, spacing=4, scroll=ft.ScrollMode.AUTO),
        )


    def _apply_tool_navigation_style(self) -> None:
        for key, item in self.tool_nav_items.items():
            selected = key == self.active_tool
            item.bgcolor = COLORS["active_bg"] if selected else "#171E2A"
            item.content.color = COLORS["active"] if selected else COLORS["text"]
            item.border = ft.Border.all(
                1,
                COLORS["active"] if selected else "transparent",
            )


    def _on_tool_selected(self, event: Any) -> None:
        if self.tool_running:
            return
        tool_name = str(event.control.data)
        if tool_name not in TOOL_MODULE_PATHS:
            return
        self.active_tool = tool_name
        self._apply_tool_navigation_style()
        self.tool_title.value = TOOL_LABELS[tool_name]
        self.tool_description.value = TOOL_DESCRIPTIONS[tool_name]
        self.secret_attempts_control.visible = tool_name == "secret_battle"
        self.tool_start_button.content = "开始"
        self._safe_update()


    def _build_tools_page(self) -> ft.Control:
        self.tool_title = ft.Text(
            TOOL_LABELS[self.active_tool],
            size=18,
            weight=ft.FontWeight.BOLD,
            color=COLORS["text"],
        )
        selector = self._build_tool_selector()
        tool_card = self._panel(
            "工具控制",
            ft.Icons.BUILD_ROUNDED,
            ft.Column(
                [
                    self.tool_title,
                    self.tool_description,
                    self.secret_attempts_control,
                    ft.Divider(height=8, color=COLORS["border"]),
                    ft.Row(
                        [
                            ft.Icon(
                                ft.Icons.INFO_OUTLINE_ROUNDED,
                                size=16,
                                color=COLORS["active"],
                            ),
                            self.tool_status,
                        ],
                        spacing=7,
                    ),
                ],
                spacing=12,
            ),
            actions=self.tool_start_button,
        )
        tool_log_panel = self._panel(
            "小工具日志",
            ft.Icons.TERMINAL_ROUNDED,
            self.tool_log_view,
            expand=True,
        )
        content = ft.Row(
            [
                ft.Container(tool_card, width=440),
                tool_log_panel,
            ],
            spacing=14,
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        return ft.Column([selector, content], spacing=14, expand=True)


    def _load_tool_module(self, tool_name: str):
        path = TOOL_MODULE_PATHS[tool_name]
        if not path.is_file():
            raise FileNotFoundError(f"小工具脚本不存在：{path}")
        module_name = f"yyshelper_tool_{tool_name}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法加载小工具：{path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module


    def start_selected_tool(self, _event: Any = None) -> None:
        if self.tool_running:
            return
        if self.running:
            self.append_tool_log("ERROR", "一键长草正在运行，不能同时启动小工具")
            return
        if self.active_tool == "secret_battle":
            try:
                attempts = int(str(self.secret_attempts_field.value).strip())
            except ValueError:
                attempts = 0
            if attempts <= 0:
                self.tool_status.value = "请填写大于 0 的协战次数"
                self.tool_status.color = COLORS["warning"]
                self.append_tool_log("WARN", "协战次数为 0，请先填写可用次数")
                self._safe_update()
                return
        if not self.save_settings():
            self.tool_status.value = "请先在设置页选择可用的 MuMu 实例"
            self.tool_status.color = COLORS["error"]
            self._show_section("settings")
            return

        self.tool_stop_event.clear()
        self.tool_running = True
        self.tool_start_button.content = "停止"
        self.tool_start_button.icon = ft.Icons.STOP_ROUNDED
        self.tool_start_button.bgcolor = COLORS["error_bg"]
        self.tool_start_button.color = COLORS["error"]
        self.start_button.disabled = True
        self.refresh_button.disabled = True
        self.secret_attempts_field.disabled = True
        self._set_global_settings_disabled(True)
        self.running_badge.visible = True
        self.running_badge_text.value = f"{TOOL_LABELS[self.active_tool]}运行中"
        self.tool_status.value = f"{TOOL_LABELS[self.active_tool]}正在运行"
        self.tool_status.color = COLORS["active"]
        self.append_tool_log(
            "INFO",
            f"准备启动{TOOL_LABELS[self.active_tool]}",
        )
        self._safe_update()
        self.page.run_thread(self._tool_worker, self.active_tool)


    def stop_selected_tool(self, _event: Any = None) -> None:
        if not self.tool_running:
            return
        self.tool_stop_event.set()
        self.tool_start_button.disabled = True
        self.tool_start_button.content = "停止中"
        self.tool_status.value = "正在等待当前截图步骤结束"
        self.tool_status.color = COLORS["warning"]
        self.append_tool_log("WARN", "已请求安全停止小工具")
        self._safe_update()


    def toggle_selected_tool(self, event: Any = None) -> None:
        if self.tool_running:
            self.stop_selected_tool(event)
        else:
            self.start_selected_tool(event)


    def _tool_worker(self, tool_name: str) -> None:
        writer = LineWriter(lambda line: self.append_tool_log("INFO", line))
        success = False
        failure_stage = "failed"
        previous_interval: Optional[float] = None
        try:
            from module import automation
            from module.diagnostics import configure_error_screenshots

            configure_error_screenshots(
                int(self.settings["error_screenshot_keep_count"])
            )

            automation.configure_runtime_paths(
                str(self.settings["adb_path"]),
                str(self.settings["mumu_path"]),
            )
            if not automation.configure_mumu_target(
                str(self.settings["adb_port"]),
                str(self.settings["mumu_index"]),
            ):
                raise OSError(f"无法连接 MuMu ADB：{self.settings['adb_port']}")
            previous_interval = automation.config.get("screenshot_speed", 0.5)
            module = self._load_tool_module(tool_name)
            battle_interval = float(self.settings["battle_detection_interval"])
            if hasattr(module, "BATTLE_SCREENSHOT_INTERVAL"):
                module.BATTLE_SCREENSHOT_INTERVAL = battle_interval
            if tool_name == "secret_battle" and hasattr(
                module,
                "SCREENSHOT_INTERVAL",
            ):
                module.SCREENSHOT_INTERVAL = battle_interval
            with redirect_stdout(writer), redirect_stderr(writer):
                if tool_name == "secret_battle":
                    result = module.run(
                        stop_event=self.tool_stop_event,
                        attempts=int(self.settings["secret_battle_attempts"]),
                        attempts_callback=self._queue_secret_attempts,
                    )
                else:
                    result = module.run(stop_event=self.tool_stop_event)
                success = bool(result)
        except Exception as exc:
            failure_stage = "exception"
            self.append_tool_log(
                "ERROR",
                f"{TOOL_LABELS.get(tool_name, tool_name)}发生异常：{exc}",
            )
            self._report_ui_exception(
                f"小工具线程 {TOOL_LABELS.get(tool_name, tool_name)}",
                exc,
            )
        finally:
            if not success and not self.tool_stop_event.is_set():
                try:
                    from module.diagnostics import capture_error_screenshot

                    capture_error_screenshot(tool_name, failure_stage)
                except Exception as exc:
                    self.append_tool_log("ERROR", f"报错截图保存失败：{exc}")
            if previous_interval is not None:
                try:
                    from module import automation

                    automation.config["screenshot_speed"] = previous_interval
                except Exception:
                    pass
            writer.flush()
            self.ui_queue.put(
                (
                    "tool_finished",
                    {
                        "success": success,
                        "stopped": self.tool_stop_event.is_set(),
                        "tool_name": tool_name,
                    },
                )
            )


    def _queue_secret_attempts(self, remaining: int) -> None:
        self.ui_queue.put(("secret_attempts", max(0, int(remaining))))


    def _apply_secret_attempts(self, remaining: int) -> None:
        remaining = max(0, int(remaining))
        self.secret_attempts_field.value = str(remaining)
        self.settings["secret_battle_attempts"] = remaining
        try:
            save_ui_settings(self.settings)
        except OSError as exc:
            self._append_tool_log_now("ERROR", f"保存剩余协战次数失败：{exc}")


    def _apply_tool_finished(
        self,
        success: bool,
        stopped: bool,
        tool_name: str,
    ) -> None:
        self.tool_running = False
        self.tool_start_button.disabled = False
        self.tool_start_button.content = "开始"
        self.tool_start_button.icon = ft.Icons.PLAY_ARROW_ROUNDED
        self.tool_start_button.bgcolor = COLORS["active"]
        self.tool_start_button.color = "#07111F"
        self.start_button.disabled = False
        self.refresh_button.disabled = False
        self.secret_attempts_field.disabled = False
        self._set_global_settings_disabled(False)
        self.running_badge.visible = False
        label = TOOL_LABELS.get(tool_name, tool_name)
        if stopped and success:
            self.tool_status.value = "已安全停止"
            self.tool_status.color = COLORS["done"]
            self._append_tool_log_now("SUCCESS", f"{label}已安全停止")
        elif success:
            self.tool_status.value = "运行结束"
            self.tool_status.color = COLORS["done"]
            self._append_tool_log_now("SUCCESS", f"{label}运行结束")
        else:
            self.tool_status.value = "执行失败"
            self.tool_status.color = COLORS["error"]

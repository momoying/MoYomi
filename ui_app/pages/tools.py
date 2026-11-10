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
    def _build_super_oni_controls(self):
        saved = self.settings.get("super_oni_instances", [])
        saved = saved if isinstance(saved, list) else []
        self.super_oni_primary = ft.Dropdown(
            label="模拟器 1", value=str(saved[0]) if saved else None, dense=True,
            on_select=self._on_super_oni_instance_changed, expand=True,
        )
        self.super_oni_secondary = ft.Dropdown(
            label="模拟器 2（可选）", value=str(saved[1]) if len(saved) > 1 else "", dense=True,
            on_select=self._on_super_oni_instance_changed,
        )
        self.super_oni_refresh = ft.IconButton(
            icon=ft.Icons.SYNC_ROUNDED, tooltip="刷新正在运行的 MuMu 实例",
            on_click=self._refresh_super_oni_instances,
        )
        self.super_oni_progress = ft.Text(
            "已获得：未识别 / 50 张\n本次挑战：0 次\n阶段：等待启动",
            size=12, color=COLORS["muted"],
        )
        self.super_oni_secondary_progress = ft.Text(size=12, color=COLORS["muted"], visible=False)
        self._refresh_super_oni_options()
        self.super_oni_options_control = ft.Column(
            [ft.Row([self.super_oni_primary, self.super_oni_refresh]), self.super_oni_secondary,
             self.super_oni_progress, self.super_oni_secondary_progress,
             ft.Text("启动时自动检查阵容上锁并开启觉醒加成；支持中途继续，刷满后关闭加成并返回觉醒一层。",
                     size=12, color=COLORS["muted"])],
            spacing=8, visible=False,
        )
        return self.super_oni_options_control

    def _refresh_super_oni_options(self):
        instances = getattr(self, "mumu_instances", [])
        indexes = {str(item["index"]) for item in instances}
        if self.super_oni_primary.value not in indexes:
            preferred = str(self.settings.get("mumu_index"))
            self.super_oni_primary.value = preferred if preferred in indexes else str(instances[0]["index"]) if instances else None
        primary = next((item for item in instances if str(item["index"]) == self.super_oni_primary.value), None)
        secondary = next((item for item in instances if str(item["index"]) == self.super_oni_secondary.value), None)
        if secondary is None or primary is not None and secondary["adb_port"] == primary["adb_port"]:
            self.super_oni_secondary.value = ""
        for field, other in ((self.super_oni_primary, self.super_oni_secondary),
                             (self.super_oni_secondary, self.super_oni_primary)):
            selected = next((item for item in instances if str(item["index"]) == other.value), None)
            field.options = ([ft.DropdownOption(key="", text="不启用")] if field is self.super_oni_secondary else []) + [
                ft.DropdownOption(key=str(item["index"]), text=f'{item["name"]} · 实例 {item["index"]}')
                for item in instances if selected is None or item["adb_port"] != selected["adb_port"]
            ]
        self._reset_super_oni_results()

    def _refresh_super_oni_instances(self, _event=None):
        if self.tool_running:
            return
        root = getattr(getattr(self, "mumu_path_field", None), "value", None) or self.settings["mumu_path"]
        self.mumu_instances = discover_running_mumu_instances(resolve_mumu_manager_path(root))
        if hasattr(self, "mumu_instance"):
            self.mumu_instance.options = self._mumu_dropdown_options()
            self._update_mumu_status()
        self._refresh_super_oni_options()
        self._safe_update()

    def _on_super_oni_instance_changed(self, _event=None):
        if getattr(self, "tool_running", False):
            return
        self.super_oni_primary.error_text = None
        self.super_oni_secondary.error_text = None
        self._refresh_super_oni_options()
        self._safe_update()

    def _reset_super_oni_results(self, stage="等待启动"):
        self._super_oni_rows = {}
        for field, control in ((self.super_oni_primary, self.super_oni_progress),
                               (self.super_oni_secondary, self.super_oni_secondary_progress)):
            index = str(field.value or "")
            item = next((item for item in getattr(self, "mumu_instances", []) if str(item["index"]) == index), None)
            control.visible = field is self.super_oni_primary or item is not None
            label = f'{item["name"]} · 实例 {index}\n' if item else ""
            control.value = label + f"已获得：未识别 / 50 张\n本次挑战：0 次\n阶段：{stage}"
            control.color = COLORS["muted"]
            if index:
                self._super_oni_rows[index] = control

    def _selected_super_oni_targets(self):
        indexes = [str(field.value or "") for field in (self.super_oni_primary, self.super_oni_secondary)]
        self.super_oni_primary.error_text = None
        self.super_oni_secondary.error_text = None
        if not indexes[0]:
            self.super_oni_primary.error_text = "请选择正在运行的实例"
            raise ValueError("请至少选择一个 MuMu 实例")
        if indexes[1] and indexes[0] == indexes[1]:
            self.super_oni_secondary.error_text = "两个模拟器不能相同"
            raise ValueError("两个模拟器不能选择同一个实例")
        targets = []
        for index in filter(None, indexes):
            target = next((item for item in getattr(self, "mumu_instances", []) if str(item["index"]) == index), None)
            if target is None:
                raise ValueError("所选 MuMu 实例已不可用，请刷新实例列表")
            targets.append(dict(target))
        if len({item["adb_port"] for item in targets}) != len(targets):
            raise ValueError("所选实例的 ADB 地址重复，请刷新实例列表")
        return targets

    def _set_super_oni_controls_disabled(self, disabled):
        for name in ("super_oni_primary", "super_oni_secondary", "super_oni_refresh"):
            control = getattr(self, name, None)
            if control is not None:
                control.disabled = disabled

    def _apply_super_oni_progress(self, progress):
        if self.active_tool != "super_oni":
            return
        tickets = progress.get("tickets")
        count = "未识别" if tickets is None else str(tickets)
        index = str(progress.get("instance_index", ""))
        control = getattr(self, "_super_oni_rows", {}).get(index, self.super_oni_progress)
        label = f'{progress["instance_name"]}\n' if progress.get("instance_name") else ""
        control.value = (label + f"已获得：{count} / 50 张\n"
                                         f"本次挑战：{progress.get('attempts', 0)} 次\n"
                                         f"阶段：{progress.get('stage', '等待启动')}")

    def _apply_super_oni_result(self, result):
        stage = ("已安全停止" if result["stopped"] else "已刷满，已关闭加成并返回觉醒一层"
                 if result["success"] else "失败：" + str(result.get("reason") or "执行失败"))
        self._apply_super_oni_progress(dict(result, stage=stage))
        control = self._super_oni_rows.get(str(result["instance_index"]))
        if control is not None:
            control.color = COLORS["done"] if result["success"] else COLORS["error"]

    def _build_baigui_controls(self):
        self.baigui_preset_field = ft.TextField(
            label="阵容", value="六级金鱼姬（荒川）", read_only=True, dense=True,
        )
        self.baigui_nickname_field = ft.TextField(
            label="当前账号完整游戏昵称", value=self.settings.get("baigui_nickname", ""), dense=True,
            helper="用于定位本人血量；留空时无法触发低血策略。", helper_max_lines=2,
        )
        self.baigui_return_home_field = ft.Checkbox(
            label="完成后返回庭院", value=self.settings.get("baigui_return_home", True),
        )
        self.baigui_progress = ft.Text("阶段：未确认 · 回目：未确认\n本局：未完成 · 周币：未确认\n血量：未确认 · 经营：未确认", size=12, color=COLORS["muted"])
        self.baigui_options_control = ft.Column(
            [self.baigui_preset_field, ft.Text("每次完成一局后停止", size=12, color=COLORS["muted"]),
             self.baigui_nickname_field, self.baigui_return_home_field, self.baigui_progress], spacing=8, visible=False,
        )
        return self.baigui_options_control

    def _baigui_settings_values(self):
        if type(self.baigui_return_home_field.value) is not bool:
            raise ValueError("返回庭院必须为勾选状态")
        return {"baigui_preset_name": DEFAULT_SETTINGS["baigui_preset_name"], "baigui_return_home": self.baigui_return_home_field.value,
                "baigui_nickname": str(self.baigui_nickname_field.value or "").strip()}

    def _set_baigui_controls_disabled(self, disabled):
        for name in ('baigui_preset_field', 'baigui_nickname_field', 'baigui_return_home_field'):
            control = getattr(self, name, None)
            if control is not None:
                control.disabled = disabled

    def _apply_baigui_progress(self, progress):
        if self.active_tool != "baigui":
            return
        def value(key):
            item = progress.get(key)
            return "未确认" if item is None else str(item)
        completed = progress.get('completed_matches')
        match_status = '已完成' if type(completed) is int and completed == 1 else '未完成' if type(completed) is int and completed == 0 else '未确认'
        late = progress.get('late_game')
        mode = '低血不留本金' if late is True else '保留50金币' if late is False else '未确认'
        self.baigui_progress.value = (f"阶段：{value('stage')} · 回目：{value('round')}\n"
                                      f"本局：{match_status} · 周币：{value('weekly')}\n"
                                      f"血量：{value('life')} · 经营：{mode}")

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
        if tool_name not in TOOL_LABELS:
            return
        self.active_tool = tool_name
        self._apply_tool_navigation_style()
        self.tool_title.value = TOOL_LABELS[tool_name]
        self.tool_description.value = TOOL_DESCRIPTIONS[tool_name]
        self.secret_attempts_control.visible = tool_name == "secret_battle"
        self.market_refresh_count_control.visible = tool_name == "market_sniper"
        self.super_oni_options_control.visible = tool_name == "super_oni"
        self.baigui_options_control.visible = tool_name == "baigui"
        self.tool_start_button.content = "开始"
        self.tool_start_button.disabled = False
        if tool_name == "super_oni":
            self.tool_status.value = "请停留在觉醒一层界面，游戏将自动上阵"
            self.tool_status.color = COLORS["muted"]
        elif tool_name == "baigui":
            from tasks.Baigui.baigui import availability
            status = availability()
            self.tool_start_button.disabled = not status["ready"]
            self.tool_status.value = status["reason"]
            self.tool_status.color = COLORS["warning"]
        else:
            self.tool_status.value = "等待启动"
            self.tool_status.color = COLORS["muted"]
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
                    self.market_refresh_count_control,
                    self._build_super_oni_controls(),
                    self._build_baigui_controls(),
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
                scroll=ft.ScrollMode.AUTO,
                expand=True,
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
        # 临时模块名用于每次重新加载，包路径仍须保留，供运行期相对导入使用。
        module.__package__ = '.'.join(path.parent.relative_to(ROOT_DIR).parts)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module


    def start_selected_tool(self, _event: Any = None) -> None:
        if self.tool_running:
            return
        if self.running:
            self.append_tool_log("ERROR", "一键长草正在运行，不能同时启动小工具")
            return
        if self.active_tool == "super_oni":
            try:
                self._super_oni_targets = self._selected_super_oni_targets()
            except ValueError as exc:
                self.tool_status.value = str(exc)
                self.tool_status.color = COLORS["warning"]
                self._safe_update()
                return
            primary = getattr(self, "mumu_instance", None)
            if primary is not None and str(primary.value) not in {str(item["index"]) for item in self.mumu_instances}:
                primary.value = self._super_oni_targets[0]["index"]
        if self.active_tool == "baigui":
            from tasks.Baigui.baigui import availability
            status = availability()
            if not status["ready"]:
                self.tool_status.value = status["reason"]
                self.tool_status.color = COLORS["warning"]
                self._safe_update()
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
        if self.active_tool == "market_sniper":
            try:
                refresh_count = int(str(self.market_refresh_count_field.value).strip())
            except ValueError:
                refresh_count = 0
            if refresh_count <= 0:
                self.tool_status.value = "请填写大于 0 的刷新次数"
                self.tool_status.color = COLORS["warning"]
                self.append_tool_log("WARN", "刷新次数需大于 0")
                self._safe_update()
                return
        if not self.save_settings():
            self.tool_status.value = "请先在设置页选择可用的 MuMu 实例"
            self.tool_status.color = COLORS["error"]
            self._show_section("settings")
            return

        self.tool_stop_event.clear()
        if self.active_tool == "super_oni":
            self._reset_super_oni_results("运行中")
        if self.active_tool == 'baigui':
            self._apply_baigui_progress({'stage': '启动检查', 'completed_matches': 0})
        self.tool_running = True
        self.tool_start_button.content = "停止"
        self.tool_start_button.icon = ft.Icons.STOP_ROUNDED
        self.tool_start_button.bgcolor = COLORS["error_bg"]
        self.tool_start_button.color = COLORS["error"]
        self.start_button.disabled = True
        self.refresh_button.disabled = True
        self.secret_attempts_field.disabled = True
        self.market_refresh_count_field.disabled = True
        self._set_baigui_controls_disabled(True)
        self._set_super_oni_controls_disabled(True)
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
        if tool_name == "super_oni":
            from ui_app.tool_sessions import run_super_oni_targets

            try:
                result = run_super_oni_targets(
                    dict(self.settings), self._super_oni_targets, self.tool_stop_event,
                    self._load_tool_module, lambda kind, payload: self.ui_queue.put((kind, payload)),
                )
            except Exception as exc:
                result = {"success": False, "stopped": self.tool_stop_event.is_set(),
                          "tool_name": tool_name, "reason": str(exc)}
                self.append_tool_log("ERROR", f"超鬼王刷票启动失败：{exc}")
            self.ui_queue.put(("tool_finished", result))
            return
        from module.task_execution import ExecutionReport, run_task_call

        writer = LineWriter(lambda line: self.append_tool_log("INFO", line))
        success = False
        failure_reason = None
        failure_stage = "failed"
        report = ExecutionReport(stage="初始化工具")
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
            if tool_name == "market_sniper" and hasattr(
                module,
                "SCREENSHOT_INTERVAL",
            ):
                module.SCREENSHOT_INTERVAL = float(
                    self.settings["screenshot_interval"]
                )
            with redirect_stdout(writer), redirect_stderr(writer):
                if tool_name == "secret_battle":
                    runner = lambda: module.run(
                        stop_event=self.tool_stop_event, attempts=int(self.settings["secret_battle_attempts"]),
                        attempts_callback=self._queue_secret_attempts,
                    )
                elif tool_name == "market_sniper":
                    runner = lambda: module.run(
                        refresh_count=int(self.settings["market_sniper_refresh_count"]),
                        stop_event=self.tool_stop_event,
                    )
                elif tool_name == "baigui":
                    runner = lambda: module.run(
                        stop_event=self.tool_stop_event,
                        preset_name=self.settings["baigui_preset_name"], return_home=self.settings["baigui_return_home"],
                        nickname=self.settings.get("baigui_nickname", ""),
                        progress_callback=lambda progress: self.ui_queue.put(("baigui_progress", dict(progress))),
                    )
                else:
                    runner = lambda: module.run(stop_event=self.tool_stop_event)
                result, report = run_task_call(runner, stop_event=self.tool_stop_event)
                if report.exception is not None and not report.cancelled:
                    raise report.exception
                success = bool(getattr(result, "completed", result)) or report.cancelled
                if not success:
                    failure_reason = report.reason or '执行失败'
                    self.append_tool_log("ERROR", f"{TOOL_LABELS.get(tool_name, tool_name)}/{report.stage or '执行'}：{report.reason or '执行失败'}")
        except Exception as exc:
            failure_stage = "exception"
            if self.tool_stop_event.is_set():
                success = True
            else:
                failure_reason = str(exc)
                self.append_tool_log(
                    "ERROR",
                    f"{TOOL_LABELS.get(tool_name, tool_name)}/{report.stage or '初始化'}发生异常：{exc}",
                )
                self._report_ui_exception(
                    f"小工具线程 {TOOL_LABELS.get(tool_name, tool_name)}",
                    exc,
                )
        finally:
            if not success and not self.tool_stop_event.is_set():
                try:
                    from module.diagnostics import capture_error_screenshot

                    capture_error_screenshot(
                        tool_name, report.stage or failure_stage,
                        **({"frame": report.frame} if report.frame is not None else {}),
                    )
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
                        "reason": failure_reason,
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
        reason: str | None = None,
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
        self.market_refresh_count_field.disabled = False
        self._set_baigui_controls_disabled(False)
        self._set_super_oni_controls_disabled(False)
        self._set_global_settings_disabled(False)
        self.running_badge.visible = False
        label = TOOL_LABELS.get(tool_name, tool_name)
        if stopped and success:
            self.tool_status.value = "已安全停止"
            self.tool_status.color = COLORS["done"]
            self._append_tool_log_now("SUCCESS", f"{label}已安全停止")
        elif success:
            self.tool_status.value = "已刷满 50/50，已关闭觉醒加成，已返回觉醒一层" if tool_name == "super_oni" else "运行结束"
            self.tool_status.color = COLORS["done"]
            self._append_tool_log_now("SUCCESS", f"{label}运行结束")
        else:
            self.tool_status.value = "执行失败" + (f"：{reason}" if reason else "")
            self.tool_status.color = COLORS["error"]

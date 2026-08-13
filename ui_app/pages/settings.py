"""全局、任务、通知与模拟器设置页面。"""

from __future__ import annotations

import asyncio
import importlib.util
import json
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


class SettingsPageMixin:
    def _build_settings_page(self) -> ft.Control:
        self.settings_sections = {
            "global": self._build_global_settings_panel(),
            "tasks": self._build_task_settings_panel(),
            "wallpaper": self._build_wallpaper_settings_panel(),
        }
        self.settings_content_host = ft.Container(
            content=self.settings_sections[self.active_settings_section],
            expand=True,
        )
        return ft.Row(
            [
                self._build_settings_navigation(),
                ft.VerticalDivider(width=1, color=COLORS["border"]),
                ft.Column(
                    [self.settings_content_host],
                    expand=True,
                    scroll=ft.ScrollMode.AUTO,
                ),
            ],
            spacing=14,
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )


    def _build_settings_navigation(self) -> ft.Container:
        entries = (
            ("global", "全局设置", ft.Icons.SETTINGS_ROUNDED),
            ("tasks", "任务设置", ft.Icons.TUNE_ROUNDED),
            ("wallpaper", "壁纸设置", ft.Icons.WALLPAPER_ROUNDED),
        )
        controls: list[ft.Control] = []
        for key, label, icon in entries:
            item = ft.Container(
                data=key,
                height=48,
                border_radius=10,
                padding=ft.Padding.symmetric(horizontal=12),
                content=ft.Row(
                    [
                        ft.Icon(icon, size=19),
                        ft.Text(label, size=14, weight=ft.FontWeight.W_600),
                    ],
                    spacing=10,
                ),
                on_click=self._on_settings_navigation_click,
            )
            self.settings_nav_items[key] = item
            controls.append(item)
        self._apply_settings_navigation_style()
        return ft.Container(
            width=210,
            padding=10,
            bgcolor="#C9111827",
            border=ft.Border.all(1, COLORS["border"]),
            border_radius=14,
            content=ft.Column(controls, spacing=4),
        )


    def _apply_settings_navigation_style(self) -> None:
        for key, item in self.settings_nav_items.items():
            selected = key == self.active_settings_section
            item.bgcolor = COLORS["active_bg"] if selected else "transparent"
            item.border = ft.Border.all(
                1, COLORS["active"] if selected else "transparent"
            )
            for control in item.content.controls:
                control.color = COLORS["active"] if selected else COLORS["text"]


    def _on_settings_navigation_click(self, event: Any) -> None:
        section = str(event.control.data)
        if section not in self.settings_sections:
            return
        self.active_settings_section = section
        self.settings_content_host.content = self.settings_sections[section]
        self._apply_settings_navigation_style()
        self._safe_update()


    def _build_global_settings_panel(self) -> ft.Control:
        settings_content = ft.Column(
            [
                ft.Text("运行路径", size=12, weight=ft.FontWeight.BOLD),
                ft.Row(
                    [self.adb_path_field, self.adb_path_button],
                    spacing=4,
                ),
                ft.Row(
                    [self.mumu_path_field, self.mumu_path_button],
                    spacing=4,
                ),
                ft.Row(
                    [self.mumu_instance, self.mumu_refresh_button],
                    spacing=4,
                ),
                self.mumu_status,
                ft.Divider(height=10, color=COLORS["border"]),
                ft.Text("检测参数", size=12, weight=ft.FontWeight.BOLD),
                ft.Row(
                    [
                        self.screenshot_interval,
                        self.battle_detection_interval,
                        self.log_max_lines,
                    ],
                    spacing=8,
                ),
                ft.Divider(height=10, color=COLORS["border"]),
                ft.Text("超时恢复", size=12, weight=ft.FontWeight.BOLD),
                ft.Row(
                    [
                        self.recovery_retry_count,
                        self.error_screenshot_keep_count,
                    ],
                    spacing=8,
                ),
                ft.Row(
                    [
                        self.recovery_timeout_seconds,
                        self.recovery_unknown_grace_seconds,
                    ],
                    spacing=8,
                ),
                ft.Text(
                    "截图保留数量填 0 表示不保留；任务恢复重试次数填 0 表示失败后不恢复。",
                    size=11,
                    color=COLORS["muted"],
                ),
                ft.Divider(height=10, color=COLORS["border"]),
                ft.Text("推送设置", size=12, weight=ft.FontWeight.BOLD),
                self.serverchan_enabled,
                ft.Row(
                    [
                        self.serverchan_sendkey,
                        self.serverchan_save_key_button,
                        self.serverchan_clear_key_button,
                    ],
                    spacing=8,
                ),
                self.serverchan_status,
                ft.Text(
                    "仅在当前检测时段的悬赏与开放的奸商检测全部结束后推送一次；普通任务结束不推送。",
                    size=11,
                    color=COLORS["muted"],
                ),
                ft.Row(
                    [
                        self.settings_message,
                        ft.Button(
                            content="保存",
                            icon=ft.Icons.SAVE_ROUNDED,
                            on_click=self.save_settings,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
            ],
            spacing=8,
        )
        return self._panel(
            "全局设置",
            ft.Icons.SETTINGS_ROUNDED,
            settings_content,
        )


    def _build_task_settings_panel(self) -> ft.Control:
        task_checks = ft.ResponsiveRow(
            [
                ft.Container(
                    checkbox,
                    col={"sm": 6, "md": 6},
                )
                for checkbox in self.task_settings_checks.values()
            ],
            columns=12,
            spacing=4,
            run_spacing=2,
        )
        task_settings_content = ft.Column(
            [
                self.task_settings_role,
                ft.Text(
                    "每个账号的 IOS / Android 独立保存；关闭后不会进入执行队列。",
                    size=11,
                    color=COLORS["muted"],
                ),
                self.cross_region_enabled,
                ft.Text(
                    "每个账号及系统均可独立启用；砂狐乐园固定执行悬赏检测和两位跨区好友点赞。",
                    size=11,
                    color=COLORS["muted"],
                ),
                ft.Divider(height=10, color=COLORS["border"]),
                task_checks,
                self.heart_team_role_setting,
                ft.Text(
                    "队长负责战斗；成员补存会保留随机登录顺序，并在全部角色任务结束后统一收尾执行。",
                    size=11,
                    color=COLORS["muted"],
                ),
                ft.Row(
                    [
                        ft.Button(
                            content="全选",
                            icon=ft.Icons.SELECT_ALL_ROUNDED,
                            on_click=lambda _event: self._set_all_task_settings(True),
                        ),
                        ft.Button(
                            content="清空",
                            icon=ft.Icons.DESELECT_ROUNDED,
                            on_click=lambda _event: self._set_all_task_settings(False),
                        ),
                    ],
                    spacing=8,
                ),
                ft.Row(
                    [
                        self.task_settings_message,
                        ft.Button(
                            content="保存任务设置",
                            icon=ft.Icons.SAVE_ROUNDED,
                            bgcolor=COLORS["active"],
                            color="#07111F",
                            on_click=self.save_task_settings,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
            ],
            spacing=8,
        )
        return self._panel(
            "任务设置",
            ft.Icons.TUNE_ROUNDED,
            task_settings_content,
            actions=ft.IconButton(
                icon=ft.Icons.REFRESH_ROUNDED,
                icon_color=COLORS["muted"],
                tooltip="重新读取账号与任务设置",
                on_click=self.refresh_task_settings,
            ),
        )


    @staticmethod
    def _task_role_key(account: str, system: str) -> str:
        return json.dumps([account, system], ensure_ascii=False)


    @staticmethod
    def _parse_task_role_key(value: Any) -> Optional[tuple[str, str]]:
        try:
            parsed = json.loads(str(value))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if (
            not isinstance(parsed, list)
            or len(parsed) != 2
            or not all(isinstance(item, str) for item in parsed)
        ):
            return None
        return parsed[0], parsed[1]


    def _reload_task_settings_roles(self, update: bool = True) -> bool:
        current_value = self.task_settings_role.value
        try:
            state, migrated = controller.load_state(controller.STATUS_PATH)
            if migrated:
                controller.save_state(state, controller.STATUS_PATH)
        except Exception as exc:
            self.task_settings_state = None
            self.task_settings_role.options = []
            self.task_settings_role.value = None
            self.task_settings_message.value = f"读取账号状态失败：{exc}"
            self.task_settings_message.color = COLORS["error"]
            for checkbox in self.task_settings_checks.values():
                checkbox.disabled = True
            self.cross_region_enabled.disabled = True
            self.cross_region_enabled.value = False
            self.heart_team_role_setting.disabled = True
            self.heart_team_role_setting.value = "none"
            if update:
                self._safe_update()
            return False

        options: list[ft.DropdownOption] = []
        keys: list[str] = []
        for account, account_state in state["accounts"].items():
            for system in account_state["systems"]:
                key = self._task_role_key(account, system)
                keys.append(key)
                options.append(
                    ft.DropdownOption(
                        key=key,
                        text=f"{account} · {system}",
                    )
                )

        selected = current_value if current_value in keys else (keys[0] if keys else None)
        self.task_settings_state = state
        self.task_settings_role.options = options
        self.task_settings_role.value = selected
        self.task_settings_message.value = ""
        self._apply_task_settings_selection()
        if update:
            self._safe_update()
        return True


    def _apply_task_settings_selection(self) -> None:
        role = self._parse_task_role_key(self.task_settings_role.value)
        system_state = None
        if role is not None and self.task_settings_state is not None:
            account, system = role
            account_state = self.task_settings_state.get("accounts", {}).get(
                account,
                {},
            )
            system_state = account_state.get("systems", {}).get(system)
        for task_name, checkbox in self.task_settings_checks.items():
            checkbox.disabled = system_state is None
            checkbox.value = (
                controller.task_is_enabled(system_state, task_name)
                if isinstance(system_state, dict)
                else False
            )
        self.cross_region_enabled.disabled = system_state is None
        self.cross_region_enabled.value = bool(
            isinstance(system_state, dict)
            and controller.cross_region_is_enabled(system_state)
        )
        self.heart_team_role_setting.disabled = system_state is None
        selected_heart_role = (
            controller.heart_team_role(system_state)
            if isinstance(system_state, dict)
            else None
        )
        self.heart_team_role_setting.value = selected_heart_role or "none"
        heart_checkbox = self.task_settings_checks[controller.HEART_TEAM_TASK]
        if selected_heart_role not in controller.HEART_TEAM_ROLES:
            heart_checkbox.value = False
            heart_checkbox.disabled = True


    def _on_task_settings_role_selected(self, _event: Any = None) -> None:
        self.task_settings_message.value = ""
        self._apply_task_settings_selection()
        self._safe_update()


    def _on_cross_region_setting_changed(self, _event: Any = None) -> None:
        self.task_settings_message.value = "尚未保存"
        self.task_settings_message.color = COLORS["warning"]
        self._safe_update()


    def _on_heart_team_role_selected(self, _event: Any = None) -> None:
        heart_checkbox = self.task_settings_checks[controller.HEART_TEAM_TASK]
        has_role = (
            self.heart_team_role_setting.value
            in controller.HEART_TEAM_ROLES
        )
        heart_checkbox.disabled = not has_role
        if not has_role:
            heart_checkbox.value = False
        self.task_settings_message.value = "尚未保存"
        self.task_settings_message.color = COLORS["warning"]
        self._safe_update()


    def _set_all_task_settings(self, enabled: bool) -> None:
        if self.task_settings_role.value is None:
            return
        for checkbox in self.task_settings_checks.values():
            checkbox.value = enabled
        if (
            self.heart_team_role_setting.value
            not in controller.HEART_TEAM_ROLES
        ):
            self.task_settings_checks[controller.HEART_TEAM_TASK].value = False
        self.task_settings_message.value = "尚未保存"
        self.task_settings_message.color = COLORS["warning"]
        self._safe_update()


    def refresh_task_settings(self, _event: Any = None) -> None:
        if self.running:
            self.task_settings_message.value = "一键长草运行中，暂不能刷新"
            self.task_settings_message.color = COLORS["warning"]
            self._safe_update()
            return
        self._reload_task_settings_roles()


    def save_task_settings(self, _event: Any = None) -> bool:
        if self.running:
            self.task_settings_message.value = "一键长草运行中，暂不能修改"
            self.task_settings_message.color = COLORS["warning"]
            self._safe_update()
            return False
        role = self._parse_task_role_key(self.task_settings_role.value)
        if role is None:
            self.task_settings_message.value = "请先选择账号和系统角色"
            self.task_settings_message.color = COLORS["error"]
            self._safe_update()
            return False

        account, system = role
        try:
            state, _ = controller.load_state(controller.STATUS_PATH)
            system_state = state["accounts"][account]["systems"][system]
            system_state["cross_region_enabled"] = bool(
                self.cross_region_enabled.value
            )
            selected_heart_role = str(self.heart_team_role_setting.value)
            controller.set_heart_team_role(
                system_state,
                selected_heart_role
                if selected_heart_role in controller.HEART_TEAM_ROLES
                else None,
            )
            system_state["task_enabled"] = {
                task_name: bool(checkbox.value)
                for task_name, checkbox in self.task_settings_checks.items()
            }
            controller.save_state(state, controller.STATUS_PATH)
        except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
            self.task_settings_message.value = f"保存失败：{exc}"
            self.task_settings_message.color = COLORS["error"]
            self._safe_update()
            return False

        self.task_settings_state = state
        self.task_settings_message.value = f"{account} · {system} 已保存"
        self.task_settings_message.color = COLORS["done"]
        self.refresh_cards(update=False)
        self._safe_update()
        return True


    def _refresh_serverchan_status(self) -> None:
        configured = bool(get_serverchan_sendkey())
        self.serverchan_status.value = (
            "SENDKEY 已保存"
            if configured
            else "尚未配置。请到 https://sct.ftqq.com 免费获取（每天 5 条额度）"
        )
        self.serverchan_status.color = (
            COLORS["done"] if configured else COLORS["warning"]
        )
        self.serverchan_sendkey.hint_text = (
            "环境变量已配置；留空不会修改"
            if configured
            else "输入 SendKey 后点击保存 API"
        )


    def _on_serverchan_enabled_changed(self, _event: Any = None) -> None:
        self.settings["serverchan_enabled"] = bool(self.serverchan_enabled.value)
        self._refresh_serverchan_status()
        try:
            save_ui_settings(self.settings)
        except OSError as exc:
            self.serverchan_status.value = f"保存推送开关失败：{exc}"
            self.serverchan_status.color = COLORS["error"]
        self._safe_update()


    def save_serverchan_key(self, _event: Any = None) -> bool:
        send_key = str(self.serverchan_sendkey.value or "").strip()
        if not send_key:
            self.serverchan_status.value = "请输入 SendKey"
            self.serverchan_status.color = COLORS["error"]
            self._safe_update()
            return False
        try:
            set_project_sendkey(send_key)
        except (OSError, ValueError) as exc:
            self.serverchan_status.value = f"保存 API 失败：{exc}"
            self.serverchan_status.color = COLORS["error"]
            self._safe_update()
            return False
        finally:
            send_key = ""
        self.serverchan_sendkey.value = ""
        self._refresh_serverchan_status()
        self._safe_update()
        return True


    def clear_serverchan_key(self, _event: Any = None) -> None:
        try:
            clear_project_sendkey()
        except OSError:
            self.serverchan_status.value = "清除 API 失败，请检查系统权限"
            self.serverchan_status.color = COLORS["error"]
            self._safe_update()
            return
        self.serverchan_sendkey.value = ""
        self._refresh_serverchan_status()
        self._safe_update()


    async def pick_adb_path(self, _event: Any = None) -> None:
        current = Path(str(self.adb_path_field.value or DEFAULT_ADB_PATH))
        initial_directory = current.parent if current.parent.is_dir() else None
        selected = await self.adb_file_picker.pick_files(
            dialog_title="选择 adb.exe",
            initial_directory=(
                str(initial_directory)
                if initial_directory is not None
                else None
            ),
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["exe"],
            allow_multiple=False,
        )
        if selected and selected[0].path:
            self.adb_path_field.value = selected[0].path
            self.settings_message.value = ""
            self._safe_update()


    async def pick_mumu_path(self, _event: Any = None) -> None:
        current = str(self.mumu_path_field.value or DEFAULT_MUMU_PATH)
        initial_directory = current if Path(current).is_dir() else None
        selected = await self.mumu_directory_picker.get_directory_path(
            dialog_title="选择 MuMu 安装根目录",
            initial_directory=initial_directory,
        )
        if selected:
            self.mumu_path_field.value = selected
            self.refresh_mumu_instances()


    def _mumu_dropdown_options(self) -> list[ft.DropdownOption]:
        return [
            ft.DropdownOption(
                key=item["index"],
                text=f'{item["name"]} · 实例 {item["index"]}',
            )
            for item in self.mumu_instances
        ]


    def _selected_mumu(self) -> Optional[dict[str, str]]:
        selected_index = str(self.mumu_instance.value or "")
        return next(
            (
                item
                for item in self.mumu_instances
                if item["index"] == selected_index
            ),
            None,
        )


    def _update_mumu_status(self) -> None:
        selected = self._selected_mumu()
        if selected is not None:
            self.mumu_status.value = (
                f'ADB {selected["adb_port"]} · 截图与输入使用实例 {selected["index"]}'
            )
            self.mumu_status.color = COLORS["done"]
        elif self.mumu_instances:
            self.mumu_status.value = f"检测到 {len(self.mumu_instances)} 个运行实例，请选择一个"
            self.mumu_status.color = COLORS["warning"]
        else:
            self.mumu_status.value = "未检测到正在运行的 MuMu 模拟器"
            self.mumu_status.color = COLORS["error"]


    def _on_mumu_selected(self, _event: Any = None) -> None:
        self._update_mumu_status()
        self.settings_message.value = ""
        self._safe_update()


    def refresh_mumu_instances(self, _event: Any = None) -> None:
        if self.running:
            return
        current_index = str(self.mumu_instance.value or "")
        manager_path = resolve_mumu_manager_path(
            str(self.mumu_path_field.value or DEFAULT_MUMU_PATH)
        )
        self.mumu_instances = discover_running_mumu_instances(manager_path)
        available_indexes = {item["index"] for item in self.mumu_instances}
        if current_index in available_indexes:
            selected_index: Optional[str] = current_index
        elif len(self.mumu_instances) == 1:
            selected_index = self.mumu_instances[0]["index"]
        else:
            selected_index = None
        self.mumu_instance.options = self._mumu_dropdown_options()
        self.mumu_instance.value = selected_index
        self._update_mumu_status()
        self.settings_message.value = "已重新扫描"
        self.settings_message.color = COLORS["muted"]
        self._safe_update()


    def _read_settings_from_fields(self) -> Optional[dict[str, Any]]:
        adb_path = Path(str(self.adb_path_field.value or "").strip()).expanduser()
        mumu_path = Path(
            str(self.mumu_path_field.value or "").strip()
        ).expanduser()
        if not adb_path.is_file():
            self.settings_message.value = "请选择有效的 adb.exe"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return None
        if not mumu_path.is_dir():
            self.settings_message.value = "请选择有效的 MuMu 安装目录"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return None
        if not resolve_mumu_manager_path(mumu_path).is_file():
            self.settings_message.value = "MuMu 目录中未找到 MuMuManager.exe"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return None
        selected_mumu = self._selected_mumu()
        if selected_mumu is None:
            self.settings_message.value = "请先选择 MuMu 实例"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return None
        try:
            interval = float(str(self.screenshot_interval.value).strip())
            battle_interval = float(
                str(self.battle_detection_interval.value).strip()
            )
            max_lines = int(str(self.log_max_lines.value).strip())
            secret_attempts = int(str(self.secret_attempts_field.value).strip())
            recovery_retries = int(
                str(self.recovery_retry_count.value).strip()
            )
            recovery_timeout = float(
                str(self.recovery_timeout_seconds.value).strip()
            )
            unknown_grace = float(
                str(self.recovery_unknown_grace_seconds.value).strip()
            )
            screenshot_keep_count = int(
                str(self.error_screenshot_keep_count.value).strip()
            )
        except ValueError:
            self.settings_message.value = "参数必须是数字"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return None
        if not 0.1 <= interval <= 10:
            self.settings_message.value = "截图间隔需为 0.1–10"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return None
        if not 0.1 <= battle_interval <= 10:
            self.settings_message.value = "战斗检测间隔需为 0.1–10"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return None
        if not 50 <= max_lines <= 2000:
            self.settings_message.value = "日志行数需为 50–2000"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return None
        if secret_attempts < 0:
            self.settings_message.value = "协战次数不能小于 0"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return None
        if not 0 <= recovery_retries <= 5:
            self.settings_message.value = "任务恢复重试次数需为 0–5"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return None
        if not 10 <= recovery_timeout <= 600:
            self.settings_message.value = "恢复最长时间需为 10–600 秒"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return None
        if not 1 <= unknown_grace <= 60:
            self.settings_message.value = "未知界面容忍时间需为 1–60 秒"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return None
        if unknown_grace > recovery_timeout:
            self.settings_message.value = "未知界面容忍时间不能超过恢复最长时间"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return None
        if not 0 <= screenshot_keep_count <= 500:
            self.settings_message.value = "报错截图保留数量需为 0–500"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return None
        return {
            "screenshot_interval": interval,
            "battle_detection_interval": battle_interval,
            "log_max_lines": max_lines,
            "recovery_retry_count": recovery_retries,
            "recovery_timeout_seconds": recovery_timeout,
            "recovery_unknown_grace_seconds": unknown_grace,
            "error_screenshot_keep_count": screenshot_keep_count,
            "adb_path": str(adb_path),
            "mumu_path": str(mumu_path),
            "mumu_index": selected_mumu["index"],
            "adb_port": selected_mumu["adb_port"],
            "secret_battle_attempts": secret_attempts,
            "wallpaper_path": str(self.wallpaper_path_field.value or ""),
            "wallpaper_opacity": float(self.wallpaper_opacity.value or 0) / 100.0,
            "wallpaper_blur": float(self.wallpaper_blur.value or 0),
            "wallpaper_fit": str(self.wallpaper_fit.value or "cover"),
            "monet_enabled": bool(self.monet_enabled.value),
            "monet_palette": dict(self.settings.get("monet_palette", {})),
            "hide_unavailable_tasks": bool(self.hide_unavailable_tasks.value),
            "serverchan_enabled": bool(self.serverchan_enabled.value),
        }


    def save_settings(self, _event: Any = None) -> bool:
        if self.serverchan_enabled.value:
            pending_key = str(self.serverchan_sendkey.value or "").strip()
            if pending_key and not self.save_serverchan_key():
                return False
            if not get_serverchan_sendkey():
                self.settings_message.value = (
                    "启用推送前请配置 SERVERCHAN_SENDKEY；可到 https://sct.ftqq.com 免费获取"
                )
                self.settings_message.color = COLORS["error"]
                self._safe_update()
                return False
        settings = self._read_settings_from_fields()
        if settings is None:
            return False
        try:
            save_ui_settings(settings)
        except OSError as exc:
            self.settings_message.value = f"保存失败：{exc}"
            self.settings_message.color = COLORS["error"]
            self._safe_update()
            return False
        self.settings = settings
        self.settings_message.value = "已保存"
        self.settings_message.color = COLORS["done"]
        self._safe_update()
        return True


    def _set_global_settings_disabled(self, disabled: bool) -> None:
        for control in self.global_setting_controls:
            control.disabled = disabled

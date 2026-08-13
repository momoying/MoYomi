"""应用外壳与主导航。"""

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


class LayoutMixin:
    def _panel(
        self,
        title: str,
        icon: str,
        content: ft.Control,
        expand: Any = None,
        subtitle: Optional[ft.Control] = None,
        actions: Optional[ft.Control] = None,
        heading_extra: Optional[ft.Control] = None,
        compact_heading: bool = False,
    ) -> ft.Container:
        title_controls: list[ft.Control] = [
            ft.Text(
                title,
                size=15,
                weight=ft.FontWeight.BOLD,
                color=COLORS["text"],
            )
        ]
        if subtitle is not None:
            title_controls.append(subtitle)
        heading_leading: list[ft.Control] = [
            ft.Icon(icon, size=18, color=COLORS["active"]),
            ft.Column(title_controls, spacing=1),
        ]
        if heading_extra is not None:
            heading_leading.append(heading_extra)
        heading = ft.Row(
            [
                ft.Row(
                    heading_leading,
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                actions or ft.Container(),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        return ft.Container(
            bgcolor=f"#DD{COLORS['panel'].lstrip('#')}",
            border=ft.Border.all(1, COLORS["border"]),
            border_radius=16,
            padding=(
                ft.Padding(left=16, top=7, right=16, bottom=16)
                if compact_heading
                else 16
            ),
            expand=expand,
            content=ft.Column(
                [
                    heading,
                    ft.Divider(
                        height=2 if compact_heading else 10,
                        color=COLORS["border"],
                    ),
                    content,
                ],
                expand=True,
                spacing=3 if compact_heading else 8,
            ),
        )


    def _build_layout(self) -> ft.Control:
        wallpaper_path = str(self.settings.get("wallpaper_path", ""))
        wallpaper_file = Path(wallpaper_path)
        self.wallpaper_image = ft.Image(
            src=wallpaper_file.read_bytes() if wallpaper_file.is_file() else b"",
            fit=self._wallpaper_box_fit(),
            opacity=float(self.settings.get("wallpaper_opacity", 0.46)),
            visible=bool(wallpaper_path and wallpaper_file.is_file()),
            expand=True,
        )
        self.wallpaper_blur_layer = ft.Container(
            blur=float(self.settings.get("wallpaper_blur", 4.0)),
            visible=self.wallpaper_image.visible,
            expand=True,
            ignore_interactions=True,
        )
        header = ft.Container(
            padding=ft.Padding.symmetric(horizontal=24, vertical=14),
            bgcolor="#E60D1422",
            border=ft.Border(bottom=ft.BorderSide(1, COLORS["border"])),
            content=ft.Row(
                [
                    ft.Row(
                        [
                            ft.Container(
                                width=42,
                                height=42,
                                border_radius=12,
                                bgcolor=COLORS["active_bg"],
                                alignment=ft.Alignment.CENTER,
                                content=ft.Icon(ft.Icons.DASHBOARD_ROUNDED, color=COLORS["active"]),
                            ),
                            ft.Column(
                                [
                                    ft.Text(
                                        "我要摆烂",
                                        size=20,
                                        weight=ft.FontWeight.BOLD,
                                        color=COLORS["text"],
                                    ),
                                    ft.Text(
                                        "MoYomi",
                                        size=11,
                                        color=COLORS["muted"],
                                    ),
                                ],
                                spacing=1,
                            ),
                        ],
                        spacing=12,
                    ),
                    self.running_badge,
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
        )

        self.section_pages = {
            "daily": self._build_daily_page(),
            "tools": self._build_tools_page(),
            "settings": self._build_settings_page(),
        }
        self.content_host = ft.Container(
            content=self.section_pages["daily"],
            padding=18,
            expand=True,
        )
        navigation = self._build_navigation()
        self._apply_navigation_style()

        foreground = ft.Column(
            [header, navigation, self.content_host],
            spacing=0,
            expand=True,
        )
        return ft.Stack(
            [self.wallpaper_image, self.wallpaper_blur_layer, foreground],
            fit=ft.StackFit.EXPAND,
            expand=True,
        )


    def _build_navigation(self) -> ft.Container:
        labels = (
            ("daily", "一键长草"),
            ("tools", "小工具"),
            ("settings", "设置"),
        )
        controls = []
        for key, label in labels:
            item = ft.Container(
                data=key,
                height=48,
                expand=True,
                alignment=ft.Alignment.CENTER,
                content=ft.Text(
                    label,
                    size=15,
                    weight=ft.FontWeight.W_600,
                    color=COLORS["text"],
                ),
                border=ft.Border(
                    bottom=ft.BorderSide(3, "transparent"),
                ),
                on_click=self._on_navigation_click,
            )
            self.nav_items[key] = item
            controls.append(item)
        return ft.Container(
            bgcolor="#E6111827",
            border=ft.Border(bottom=ft.BorderSide(1, COLORS["border"])),
            content=ft.Row(controls, spacing=0),
        )


    def _apply_navigation_style(self) -> None:
        for key, item in self.nav_items.items():
            selected = key == self.active_section
            item.content.color = COLORS["active"] if selected else COLORS["text"]
            item.border = ft.Border(
                bottom=ft.BorderSide(
                    3,
                    COLORS["active"] if selected else "transparent",
                )
            )


    def _on_navigation_click(self, event: Any) -> None:
        section = str(event.control.data)
        self._show_section(section)


    def _show_section(self, section: str, update: bool = True) -> None:
        if section not in self.section_pages:
            return
        self.active_section = section
        self.content_host.content = self.section_pages[section]
        self._apply_navigation_style()
        if update:
            self._safe_update()

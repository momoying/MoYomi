"""应用外壳与主导航。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import flet as ft

from ui_app.components import *
from ui_app.constants import *
from ui_app.window_layout import (
    CANVAS_HEIGHT, CANVAS_WIDTH, WINDOW_HEIGHT, WINDOW_WIDTH,
    fit_canvas, fit_window, windows_work_area,
)


class LayoutMixin:
    def _configure_window(self) -> None:
        self._window_work_area = None
        self.page.window.aspect_ratio = WINDOW_WIDTH / WINDOW_HEIGHT
        self.page.window.alignment = ft.Alignment.CENTER
        self.page.window.on_event = self._on_window_event
        self.page.on_media_change = self._on_display_metrics_change
        self._fit_window_to_screen(initial=True)

    def _fit_window_to_screen(self, *, initial: bool = False) -> None:
        work_area = windows_work_area(self.page.title)
        if not initial and work_area == self._window_work_area:
            return
        self._window_work_area = work_area
        width, height = fit_window(work_area)
        window = self.page.window
        window.min_width, window.min_height = min(800, width), min(520, height)
        if initial:
            window.width, window.height = width, height
        elif not window.maximized and not window.full_screen and not window.minimized:
            scale = min(1.0, width / window.width, height / window.height)
            window.width, window.height = window.width * scale, window.height * scale
        if not initial:
            self._safe_update()

    def _on_window_event(self, event: ft.WindowEvent) -> None:
        if event.type in {ft.WindowEventType.MOVED, ft.WindowEventType.FOCUS, ft.WindowEventType.RESTORE}:
            self._fit_window_to_screen()

    def _on_display_metrics_change(self, _event: Any) -> None:
        self._fit_window_to_screen()

    def _on_viewport_size_change(self, event: ft.LayoutSizeChangeEvent) -> None:
        fitted = fit_canvas(event.width, event.height)
        if fitted is None:
            return
        scale, left, top = fitted
        surface = self._layout_surface
        surface.scale = ft.Scale(scale=scale, alignment=ft.Alignment.TOP_LEFT, transform_hit_tests=True)
        surface.left, surface.top = left, top
        self._fit_window_to_screen()
        self._safe_update()

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
                    ft.Row(
                        [self.update_notice, self.running_badge],
                        spacing=10,
                    ),
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
        content = ft.Stack(
            [self.wallpaper_image, self.wallpaper_blur_layer, foreground],
            fit=ft.StackFit.EXPAND,
            expand=True,
        )
        self._layout_surface = ft.Container(
            content=content,
            width=CANVAS_WIDTH,
            height=CANVAS_HEIGHT,
            left=0,
            top=0,
            scale=ft.Scale(scale=1, alignment=ft.Alignment.TOP_LEFT, transform_hit_tests=True),
        )
        return ft.Stack(
            [self._layout_surface],
            expand=True,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            on_size_change=self._on_viewport_size_change,
            size_change_interval=50,
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

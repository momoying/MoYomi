"""壁纸与莫奈主题设置。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import flet as ft

from module.appearance import DEFAULT_ACCENT, extract_monet_palette
from ui_app.components import *
from ui_app.constants import *
from ui_app.settings_store import *


class ThemePageMixin:
    def _build_wallpaper_settings_panel(self) -> ft.Control:
        content = ft.Column(
            [
                ft.Text("背景图片", size=12, weight=ft.FontWeight.BOLD),
                ft.Row(
                    [self.wallpaper_path_field, self.wallpaper_path_button],
                    spacing=4,
                ),
                ft.Text("背景不透明度", size=12, color=COLORS["muted"]),
                self.wallpaper_opacity,
                ft.Text("背景模糊半径", size=12, color=COLORS["muted"]),
                self.wallpaper_blur,
                self.wallpaper_fit,
                ft.Divider(height=10, color=COLORS["border"]),
                self.monet_enabled,
                ft.Text(
                    "开启后会从壁纸提取主色，生成界面强调色和深色表面色。",
                    size=11,
                    color=COLORS["muted"],
                ),
                self.monet_palette_row,
                ft.Row(
                    [
                        ft.Button(
                            content="清除壁纸",
                            icon=ft.Icons.DELETE_OUTLINE_ROUNDED,
                            on_click=self.clear_wallpaper,
                        ),
                        ft.Row(
                            [
                                self.wallpaper_message,
                                ft.Button(
                                    content="保存壁纸设置",
                                    icon=ft.Icons.SAVE_ROUNDED,
                                    bgcolor=COLORS["active"],
                                    color="#07111F",
                                    on_click=self.save_wallpaper_settings,
                                ),
                            ],
                            spacing=10,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
            ],
            spacing=10,
        )
        return self._panel(
            "壁纸设置",
            ft.Icons.WALLPAPER_ROUNDED,
            content,
        )


    def _wallpaper_box_fit(self) -> ft.BoxFit:
        value = (
            str(self.wallpaper_fit.value)
            if hasattr(self, "wallpaper_fit")
            else str(self.settings.get("wallpaper_fit", "cover"))
        )
        return {
            "none": ft.BoxFit.NONE,
            "contain": ft.BoxFit.CONTAIN,
            "fill": ft.BoxFit.FILL,
        }.get(value, ft.BoxFit.COVER)


    def _refresh_monet_palette_preview(self) -> None:
        palette = self.settings.get("monet_palette", {})
        colors = [
            ("主色", str(palette.get("primary"))),
            ("辅助色", str(palette.get("secondary"))),
            ("表面色", str(palette.get("surface_variant"))),
            ("边框色", str(palette.get("outline"))),
        ]
        self.monet_palette_row.controls = [
            ft.Column(
                [
                    ft.Container(
                        width=30,
                        height=30,
                        border_radius=8,
                        bgcolor=color,
                        border=ft.Border.all(1, "#66FFFFFF"),
                        tooltip=color,
                    ),
                    ft.Text(label, size=10, color=COLORS["muted"]),
                ],
                spacing=3,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            )
            for label, color in colors
            if color and color != "None"
        ]
        self.monet_palette_row.visible = bool(self.monet_palette_row.controls)


    def _apply_monet_palette(self, palette: dict[str, str]) -> None:
        if not palette:
            return
        COLORS["active"] = str(palette.get("primary", DEFAULT_ACCENT))
        COLORS["panel"] = str(palette.get("surface", COLORS["panel"]))
        COLORS["panel_alt"] = str(
            palette.get("surface_variant", COLORS["panel_alt"])
        )
        COLORS["border"] = str(palette.get("outline", COLORS["border"]))
        self.page.theme = ft.Theme(
            font_family="Microsoft YaHei UI",
            color_scheme_seed=COLORS["active"],
        )
        self.wallpaper_opacity.active_color = COLORS["active"]
        self.wallpaper_blur.active_color = COLORS["active"]
        self.monet_enabled.active_color = COLORS["active"]
        self.hide_unavailable_tasks.active_color = COLORS["active"]
        self.serverchan_enabled.active_color = COLORS["active"]
        self.start_button.bgcolor = COLORS["active"]
        self.tool_start_button.bgcolor = COLORS["active"]
        self._apply_navigation_style()
        self._apply_settings_navigation_style()


    def _apply_default_palette(self) -> None:
        COLORS.update(BASE_COLORS)
        self.page.theme = ft.Theme(
            font_family="Microsoft YaHei UI",
            color_scheme_seed=COLORS["active"],
        )
        self.wallpaper_opacity.active_color = COLORS["active"]
        self.wallpaper_blur.active_color = COLORS["active"]
        self.monet_enabled.active_color = COLORS["active"]
        self.hide_unavailable_tasks.active_color = COLORS["active"]
        self.serverchan_enabled.active_color = COLORS["active"]
        self.start_button.bgcolor = COLORS["active"]
        self.tool_start_button.bgcolor = COLORS["active"]


    def _sync_wallpaper_preview_settings(self) -> None:
        self.settings.update(
            {
                "wallpaper_path": str(self.wallpaper_path_field.value or ""),
                "wallpaper_opacity": float(self.wallpaper_opacity.value or 0) / 100.0,
                "wallpaper_blur": float(self.wallpaper_blur.value or 0),
                "wallpaper_fit": str(self.wallpaper_fit.value or "cover"),
                "monet_enabled": bool(self.monet_enabled.value),
            }
        )


    def _rebuild_theme_layout(self) -> None:
        if not self.page.controls:
            return
        active_section = self.active_section
        self.refresh_cards(update=False)
        self.page.controls[0] = self._build_layout()
        self._show_section(active_section, update=False)


    async def pick_wallpaper_path(self, _event: Any = None) -> None:
        current = Path(str(self.wallpaper_path_field.value or "")).expanduser()
        initial_directory = current.parent if current.parent.is_dir() else None
        selected = await self.wallpaper_file_picker.pick_files(
            dialog_title="选择壁纸图片",
            initial_directory=(str(initial_directory) if initial_directory else None),
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["png", "jpg", "jpeg", "webp", "bmp"],
            allow_multiple=False,
        )
        if not selected or not selected[0].path:
            return
        self.wallpaper_path_field.value = selected[0].path
        self.wallpaper_message.value = "预览中，保存后保留"
        self.wallpaper_message.color = COLORS["warning"]
        if self.monet_enabled.value:
            try:
                palette = extract_monet_palette(selected[0].path)
                self.settings["monet_palette"] = palette
                self._monet_palette_path = selected[0].path
                self._apply_monet_palette(palette)
                self._refresh_monet_palette_preview()
            except (OSError, ValueError) as exc:
                self.wallpaper_message.value = f"取色失败：{exc}"
                self.wallpaper_message.color = COLORS["error"]
        self._sync_wallpaper_preview_settings()
        self._rebuild_theme_layout()
        self.preview_wallpaper_settings()


    def preview_wallpaper_settings(self, _event: Any = None) -> None:
        if not hasattr(self, "wallpaper_image"):
            return
        path = str(self.wallpaper_path_field.value or "")
        wallpaper_file = Path(path)
        visible = bool(path and wallpaper_file.is_file())
        self.wallpaper_image.src = wallpaper_file.read_bytes() if visible else b""
        self.wallpaper_image.visible = visible
        self.wallpaper_image.opacity = float(self.wallpaper_opacity.value or 0) / 100.0
        self.wallpaper_image.fit = self._wallpaper_box_fit()
        self.wallpaper_blur_layer.blur = float(self.wallpaper_blur.value or 0)
        self.wallpaper_blur_layer.visible = visible
        self._safe_update()


    def _on_monet_changed(self, _event: Any = None) -> None:
        path = str(self.wallpaper_path_field.value or "")
        if self.monet_enabled.value and path and Path(path).is_file():
            try:
                palette = (
                    dict(self.settings.get("monet_palette", {}))
                    if self._monet_palette_path == path
                    else extract_monet_palette(path)
                )
                self.settings["monet_palette"] = palette
                self._monet_palette_path = path
                self._apply_monet_palette(palette)
                self._refresh_monet_palette_preview()
                self.wallpaper_message.value = "已自动从壁纸取色"
                self.wallpaper_message.color = COLORS["done"]
            except (OSError, ValueError) as exc:
                self.wallpaper_message.value = f"取色失败：{exc}"
                self.wallpaper_message.color = COLORS["error"]
        elif not self.monet_enabled.value:
            self.settings["monet_palette"] = {}
            self._monet_palette_path = ""
            self._apply_default_palette()
            self._refresh_monet_palette_preview()
        self._sync_wallpaper_preview_settings()
        self._rebuild_theme_layout()
        self.preview_wallpaper_settings()


    def clear_wallpaper(self, _event: Any = None) -> None:
        self.wallpaper_path_field.value = ""
        self.settings["monet_palette"] = {}
        self._monet_palette_path = ""
        self._refresh_monet_palette_preview()
        self.wallpaper_message.value = "壁纸已从预览移除，点击保存后生效"
        self.wallpaper_message.color = COLORS["warning"]
        self.preview_wallpaper_settings()


    def save_wallpaper_settings(self, _event: Any = None) -> bool:
        path = str(self.wallpaper_path_field.value or "").strip()
        if path and not Path(path).is_file():
            self.wallpaper_message.value = "请选择有效的图片文件"
            self.wallpaper_message.color = COLORS["error"]
            self._safe_update()
            return False
        palette: dict[str, str] = {}
        if path and self.monet_enabled.value:
            try:
                palette = (
                    dict(self.settings.get("monet_palette", {}))
                    if self._monet_palette_path == path
                    else extract_monet_palette(path)
                )
            except (OSError, ValueError) as exc:
                self.wallpaper_message.value = f"取色失败：{exc}"
                self.wallpaper_message.color = COLORS["error"]
                self._safe_update()
                return False
        self.settings.update(
            {
                "wallpaper_path": path,
                "wallpaper_opacity": float(self.wallpaper_opacity.value or 0) / 100.0,
                "wallpaper_blur": float(self.wallpaper_blur.value or 0),
                "wallpaper_fit": str(self.wallpaper_fit.value or "cover"),
                "monet_enabled": bool(self.monet_enabled.value),
                "monet_palette": palette,
            }
        )
        try:
            save_ui_settings(self.settings)
        except OSError as exc:
            self.wallpaper_message.value = f"保存失败：{exc}"
            self.wallpaper_message.color = COLORS["error"]
            self._safe_update()
            return False
        if palette:
            self._apply_monet_palette(palette)
        else:
            self._apply_default_palette()
        self._refresh_monet_palette_preview()
        self._rebuild_theme_layout()
        self.preview_wallpaper_settings()
        self.wallpaper_message.value = "已保存"
        self.wallpaper_message.color = COLORS["done"]
        self._safe_update()
        return True

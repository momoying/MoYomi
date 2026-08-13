"""MoYomi Flet 界面兼容入口。"""

from __future__ import annotations

import flet as ft

from ui_app import *
from ui_app import __all__


def main(page: ft.Page) -> None:
    AssistantDashboard(page)


__all__ = [*__all__, "main"]


if __name__ == "__main__":
    ft.run(main)

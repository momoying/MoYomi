"""截图、识图和设备手势的面向对象入口。"""

from __future__ import annotations

import random
from typing import Any, Optional

from module.base.assets import ClickAsset, ImageAsset, Rect


class TaskDevice:
    """把任务使用的截图、识图、点击和滑动收敛到一个对象。

    ``backend`` 保持为可注入依赖，现有测试仍可替换底层函数；同时任务代码
    不再直接散落调用 ADB 和截图函数。
    """

    def __init__(self, backend: Any, logger: Any = None):
        self.backend = backend
        self.logger = logger

    def screenshot(self):
        return self.backend.take_screenshot()

    def last_screenshot(self):
        return self.backend.get_last_screenshot()

    def save_screenshot(self, output_path: str, frame=None):
        return self.backend.save_screenshot(output_path, frame=frame)

    def match(
        self,
        top_left,
        bottom_right,
        template_path,
        screenshot_path=None,
        frame=None,
    ):
        return self.backend.crop_and_match(
            top_left,
            bottom_right,
            template_path,
            screenshot_path=screenshot_path,
            frame=frame,
        )

    def match_asset(self, asset: ImageAsset, *, frame=None):
        return self.match(*asset.region, asset.path, frame=frame)

    @staticmethod
    def random_point(rect: Rect, *, inset: int = 5) -> tuple[int, int]:
        left, top, right, bottom = rect
        safe_inset = max(0, int(inset))
        min_x, max_x = left + safe_inset, right - safe_inset
        min_y, max_y = top + safe_inset, bottom - safe_inset
        if min_x > max_x:
            min_x, max_x = left, right
        if min_y > max_y:
            min_y, max_y = top, bottom
        return random.randint(min_x, max_x), random.randint(min_y, max_y)

    def click(
        self,
        x: int,
        y: int,
        *,
        label: Optional[str] = None,
        rect: Optional[Rect] = None,
        stage: Optional[str] = None,
    ):
        if self.logger is not None and label and rect is not None:
            self.logger.click(stage or label, label, rect, (int(x), int(y)))
        return self.backend.adb_click(int(x), int(y))

    def click_rect(
        self,
        rect: Rect,
        *,
        label: str,
        stage: Optional[str] = None,
        inset: int = 5,
    ) -> tuple[int, int]:
        point = self.random_point(rect, inset=inset)
        self.click(*point, label=label, rect=rect, stage=stage)
        return point

    def click_asset(
        self,
        asset: ClickAsset,
        *,
        stage: Optional[str] = None,
        inset: int = 5,
    ) -> tuple[int, int]:
        return self.click_rect(
            asset.area,
            label=asset.name or stage or "固定区域",
            stage=stage,
            inset=inset,
        )

    def click_until_disappears(self, *args, **kwargs):
        return self.backend.click_template_until_disappears(*args, **kwargs)

    def swipe(self, start_x, start_y, end_x, end_y, duration_ms=800):
        return self.backend.adb_swipe(
            start_x,
            start_y,
            end_x,
            end_y,
            duration_ms=duration_ms,
        )

    def keyevent(self, keycode):
        return self.backend.adb_keyevent(keycode)

    def back(self):
        return self.backend.adb_back()

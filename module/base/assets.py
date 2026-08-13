"""任务图片和固定点击区域的声明对象。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Mapping, Optional, Tuple


Point = Tuple[int, int]
Rect = Tuple[int, int, int, int]
SearchRegion = Tuple[Point, Point]


@dataclass(frozen=True)
class ImageAsset:
    """一张模板图片及其匹配参数。"""

    file: Path
    region: Optional[SearchRegion] = None
    threshold: float = 0.80
    name: str = ""

    @property
    def path(self) -> str:
        return str(self.file)


@dataclass(frozen=True)
class ClickAsset:
    """不依赖模板识别的固定点击区域。"""

    area: Rect
    name: str = ""


class TaskAssets:
    """按名称集中管理任务所需的图片和点击区域。"""

    IMAGES: ClassVar[Mapping[str, ImageAsset]] = {}
    CLICKS: ClassVar[Mapping[str, ClickAsset]] = {}

    def __init_subclass__(cls, **kwargs) -> None:
        """扫描独立资源常量并生成任务代码使用的兼容映射。"""
        super().__init_subclass__(**kwargs)
        images = {
            asset.name: asset
            for attr_name, asset in vars(cls).items()
            if attr_name.startswith("I_") and isinstance(asset, ImageAsset)
        }
        cls.IMAGES = images
        cls.TEMPLATES = {name: asset.path for name, asset in images.items()}
        cls.REGIONS = {
            name: asset.region
            for name, asset in images.items()
            if asset.region is not None
        }
        cls.MATCH_THRESHOLDS = {
            name: asset.threshold for name, asset in images.items()
        }

        clicks = {
            asset.name: asset
            for attr_name, asset in vars(cls).items()
            if attr_name.startswith("C_") and isinstance(asset, ClickAsset)
        }
        cls.CLICKS = clicks

    @classmethod
    def image(cls, name: str) -> ImageAsset:
        return cls.IMAGES[name]

    @classmethod
    def click(cls, name: str) -> ClickAsset:
        return cls.CLICKS[name]

    @classmethod
    def templates(cls) -> dict[str, str]:
        return {name: asset.path for name, asset in cls.IMAGES.items()}

    @classmethod
    def regions(cls) -> dict[str, SearchRegion]:
        return {
            name: asset.region
            for name, asset in cls.IMAGES.items()
            if asset.region is not None
        }

    @classmethod
    def thresholds(cls, *, default: Optional[float] = None) -> dict[str, float]:
        values = {name: asset.threshold for name, asset in cls.IMAGES.items()}
        if default is None:
            return values
        return {name: value for name, value in values.items() if value != default}

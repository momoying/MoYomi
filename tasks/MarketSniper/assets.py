"""寄售屋抢购小工具的识别资源和点击区域。"""

from __future__ import annotations

from pathlib import Path

from module.base.assets import ClickAsset, ImageAsset, TaskAssets


ASSET_DIR = Path(__file__).resolve().parent
RES_DIR = ASSET_DIR / "res"


class MarketSniperAssets(TaskAssets):
    # 无寄售商品提示
    I_EMPTY_LISTING = ImageAsset(
        file=RES_DIR / "empty_listing.png",
        region=((550, 450), (1080, 600)),
        threshold=0.90,
        name="empty_listing",
    )

    # 列表卡片右上角，用于定位当前第一行
    I_LISTING_ROW_CORNER = ImageAsset(
        file=RES_DIR / "listing_row_corner.png",
        region=((1000, 245), (1090, 620)),
        threshold=0.92,
        name="listing_row_corner",
    )

    # 商品购买弹窗中的减号按钮，用于确认弹窗状态
    I_QUANTITY_MINUS = ImageAsset(
        file=RES_DIR / "quantity_minus.png",
        region=((420, 430), (850, 650)),
        threshold=0.90,
        name="quantity_minus",
    )

    # 大幅藏品预览、刷新按钮、购买按钮的安全点击区域
    C_COLLECTION_PREVIEW = ClickAsset(
        area=(145, 182, 536, 413),
        name="collection_preview",
    )
    # 寄售屋刷新按钮的安全点击区域
    C_REFRESH = ClickAsset(
        area=(1034, 600, 1089, 648),
        name="refresh",
    )
    # 商品购买弹窗确认按钮的安全点击区域
    C_PURCHASE = ClickAsset(
        area=(552, 550, 729, 612),
        name="purchase",
    )

    COLLECTION_PREVIEW_REGION = C_COLLECTION_PREVIEW.area
    REFRESH_REGION = C_REFRESH.area
    PURCHASE_REGION = C_PURCHASE.area

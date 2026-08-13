"""本任务的图片、识别区域和固定操作坐标。"""

from __future__ import annotations

from pathlib import Path

from module.base.assets import ClickAsset, ImageAsset, TaskAssets


ASSET_DIR = Path(__file__).resolve().parent
RES_DIR = ASSET_DIR / "res"
TASKS_DIR = ASSET_DIR.parent
PROJECT_ROOT = ASSET_DIR.parents[1]
MODULE_RES_DIR = PROJECT_ROOT / "module" / "res"


class MerchantAssets(TaskAssets):
    # 庭院主界面
    I_MAIN = ImageAsset(
        file=TASKS_DIR / "CoopReward" / "res" / "explore.png",
        region=((500, 80), (800, 280)),
        threshold=0.8,
        name='main',
    )

    # 商店入口
    I_STORE_ENTRY = ImageAsset(
        file=RES_DIR / "store_entry.png",
        region=((550, 560), (850, 720)),
        threshold=0.88,
        name='store_entry',
    )

    # 功能菜单卷轴
    I_MENU_SCROLL = ImageAsset(
        file=RES_DIR / "menu_scroll.png",
        region=((1100, 540), (1280, 720)),
        threshold=0.8,
        name='menu_scroll',
    )

    # 热门推荐页标记
    I_POPULAR_MARKER = ImageAsset(
        file=RES_DIR / "popular_marker.png",
        region=((100, 0), (380, 100)),
        threshold=0.9,
        name='popular_marker',
    )

    # 商店返回按钮
    I_SHOP_BACK = ImageAsset(
        file=RES_DIR / "shop_back.png",
        region=((0, 0), (100, 100)),
        threshold=0.88,
        name='shop_back',
    )

    # 神秘商店入口
    I_MERCHANT_ENTRY = ImageAsset(
        file=RES_DIR / "merchant_entry.png",
        region=((0, 350), (180, 600)),
        threshold=0.9,
        name='merchant_entry',
    )

    # 普通蓝票商品
    I_BLUE_TICKET = ImageAsset(
        file=RES_DIR / "blue_ticket.png",
        region=((100, 80), (1050, 580)),
        threshold=0.88,
        name='blue_ticket',
    )

    # 特殊样式蓝票商品
    I_BLUE_TICKET_SPECIAL = ImageAsset(
        file=RES_DIR / "blue_ticket_special.png",
        region=None,
        threshold=0.9,
        name='blue_ticket_special',
    )

    # 刷新按钮
    I_REFRESH = ImageAsset(
        file=RES_DIR / "refresh.png",
        region=((1120, 450), (1280, 650)),
        threshold=0.9,
        name='refresh',
    )

    # 确认按钮
    I_CONFIRM = ImageAsset(
        file=RES_DIR / "confirm.png",
        region=((550, 350), (920, 520)),
        threshold=0.9,
        name='confirm',
    )

    # 一键返回庭院按钮
    I_COURTYARD_BACK = ImageAsset(
        file=RES_DIR / "courtyard_back.png",
        region=((60, 0), (180, 100)),
        threshold=0.9,
        name='courtyard_back',
    )

    # 售价 50 勾玉数字
    I_PRICE_50 = ImageAsset(
        file=RES_DIR / "price_50.png",
        region=None,
        threshold=0.94,
        name='price_50',
    )

    # 售价 70 勾玉数字
    I_PRICE_70 = ImageAsset(
        file=RES_DIR / "price_70.png",
        region=None,
        threshold=0.94,
        name='price_70',
    )

    # 售价 80 勾玉数字
    I_PRICE_80 = ImageAsset(
        file=RES_DIR / "price_80.png",
        region=None,
        threshold=0.94,
        name='price_80',
    )

    # 售价 90 勾玉数字
    I_PRICE_90 = ImageAsset(
        file=RES_DIR / "price_90.png",
        region=None,
        threshold=0.94,
        name='price_90',
    )

    BLUE_TICKET_TEMPLATE_THRESHOLDS = {
            "blue_ticket": 0.88,
            "blue_ticket_special": 0.90,
        }

    PRICE_SEARCH_OFFSET = (25, 115, 110, 180)

    PRICE_DIGIT_LEFT = {
            "50": 34,
            "70": 0,
            "80": 34,
            "90": 34,
        }

    PRICE_MATCH_THRESHOLD = 0.94

    PRICE_WIN_MARGIN = 0.03

    POPULAR_FALLBACK_THRESHOLD = 0.78

    REFRESH_RED_VALUE_THRESHOLD = 145.0

    REFRESH_RED_MIN_PIXELS = 100

    _TEMPLATE_CACHE: dict[str, object] = {}

    PRICE_TEMPLATES = {
        '50': I_PRICE_50.path,
        '70': I_PRICE_70.path,
        '80': I_PRICE_80.path,
        '90': I_PRICE_90.path,
    }

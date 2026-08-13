"""本任务的图片、识别区域和固定操作坐标。"""

from __future__ import annotations

from pathlib import Path

from module.base.assets import ClickAsset, ImageAsset, TaskAssets


ASSET_DIR = Path(__file__).resolve().parent
RES_DIR = ASSET_DIR / "res"
TASKS_DIR = ASSET_DIR.parent
PROJECT_ROOT = ASSET_DIR.parents[1]
MODULE_RES_DIR = PROJECT_ROOT / "module" / "res"


class ConsignmentHouseAssets(TaskAssets):
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

    # 寄售屋入口
    I_CONSIGNMENT_ENTRY = ImageAsset(
        file=RES_DIR / "consignment_entry.png",
        region=((150, 600), (330, 720)),
        threshold=0.9,
        name='consignment_entry',
    )

    # 未选中的兑换页签
    I_EXCHANGE_INACTIVE = ImageAsset(
        file=RES_DIR / "exchange_inactive.png",
        region=((1140, 250), (1280, 450)),
        threshold=0.94,
        name='exchange_inactive',
    )

    # 已选中的兑换页签
    I_EXCHANGE_ACTIVE = ImageAsset(
        file=RES_DIR / "exchange_active.png",
        region=((1140, 250), (1280, 450)),
        threshold=0.96,
        name='exchange_active',
    )

    # 寄售券商品
    I_CONSIGNMENT_TICKET = ImageAsset(
        file=RES_DIR / "consignment_ticket.png",
        region=((550, 130), (900, 380)),
        threshold=0.92,
        name='consignment_ticket',
    )

    # 购买确认弹窗
    I_PURCHASE_DIALOG = ImageAsset(
        file=RES_DIR / "purchase_dialog.png",
        region=((450, 450), (850, 650)),
        threshold=0.94,
        name='purchase_dialog',
    )

    # 最大购买数量按钮
    I_MAX_QUANTITY = ImageAsset(
        file=RES_DIR / "max_quantity.png",
        region=((700, 380), (850, 520)),
        threshold=0.94,
        name='max_quantity',
    )

    # 购买按钮
    I_PURCHASE = ImageAsset(
        file=RES_DIR / "purchase.png",
        region=((500, 480), (780, 620)),
        threshold=0.94,
        name='purchase',
    )

    # 奖励结算界面
    I_REWARD = ImageAsset(
        file=RES_DIR / "reward.png",
        region=((350, 130), (900, 330)),
        threshold=0.92,
        name='reward',
    )

    # 一键返回庭院按钮
    I_COURTYARD_BACK = ImageAsset(
        file=RES_DIR / "courtyard_back.png",
        region=((60, 0), (190, 100)),
        threshold=0.9,
        name='courtyard_back',
    )

    EXCHANGE_ACTIVE_MARGIN = 0.04

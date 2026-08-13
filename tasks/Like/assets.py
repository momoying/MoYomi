"""本任务的图片、识别区域和固定操作坐标。"""

from __future__ import annotations

from pathlib import Path

from module.base.assets import ClickAsset, ImageAsset, TaskAssets


ASSET_DIR = Path(__file__).resolve().parent
RES_DIR = ASSET_DIR / "res"
TASKS_DIR = ASSET_DIR.parent
PROJECT_ROOT = ASSET_DIR.parents[1]
MODULE_RES_DIR = PROJECT_ROOT / "module" / "res"


class LikeAssets(TaskAssets):
    # 庭院主界面
    I_MAIN = ImageAsset(
        file=TASKS_DIR / "CoopReward" / "res" / "explore.png",
        region=((500, 80), (800, 280)),
        threshold=0.8,
        name='main',
    )

    # 好友入口
    I_FRIEND = ImageAsset(
        file=RES_DIR / "friend.png",
        region=((700, 560), (1050, 710)),
        threshold=0.8,
        name='friend',
    )

    # 功能菜单卷轴
    I_MENU_SCROLL = ImageAsset(
        file=RES_DIR / "menu_scroll.png",
        region=((1100, 540), (1280, 720)),
        threshold=0.8,
        name='menu_scroll',
    )

    # 好友分类折叠状态
    I_FRIEND_COLLAPSED = ImageAsset(
        file=RES_DIR / "friend_collapsed.png",
        region=((430, 145), (495, 195)),
        threshold=0.8,
        name='friend_collapsed',
    )

    # 好友分类展开状态
    I_FRIEND_EXPANDED = ImageAsset(
        file=RES_DIR / "friend_expanded.png",
        region=((430, 145), (495, 195)),
        threshold=0.8,
        name='friend_expanded',
    )

    # 未点赞按钮
    I_LIKE = ImageAsset(
        file=RES_DIR / "Like.png",
        region=((500, 70), (850, 270)),
        threshold=0.8,
        name='like',
    )

    # 已点赞状态
    I_LIKED = ImageAsset(
        file=RES_DIR / "Liked.png",
        region=((500, 70), (850, 270)),
        threshold=0.8,
        name='liked',
    )

    # 返回按钮
    I_BACK = ImageAsset(
        file=RES_DIR / "back.png",
        region=((1100, 50), (1240, 180)),
        threshold=0.8,
        name='back',
    )

    # 好友分类标题点击区域
    C_FRIEND_HEADER_CLICK = ClickAsset(area=(320, 155, 490, 195), name='friend_header_click_region')

    # 跨区好友分类标题点击区域
    C_CROSS_REGION_HEADER_CLICK = ClickAsset(area=(320, 575, 490, 615), name='cross_region_header_click_region')

    # 第一位跨区好友点击区域
    C_CROSS_REGION_FRIEND_CLICK_REGIONS_1 = ClickAsset(area=(340, 260, 430, 315), name='cross_region_friend_click_regions_1')

    # 第二位跨区好友点击区域
    C_CROSS_REGION_FRIEND_CLICK_REGIONS_2 = ClickAsset(area=(340, 350, 430, 405), name='cross_region_friend_click_regions_2')

    FRIEND_HEADER_CLICK_REGION = C_FRIEND_HEADER_CLICK.area

    CROSS_REGION_HEADER_CLICK_REGION = C_CROSS_REGION_HEADER_CLICK.area

    CROSS_REGION_FRIEND_CLICK_REGIONS = (
        C_CROSS_REGION_FRIEND_CLICK_REGIONS_1.area,
        C_CROSS_REGION_FRIEND_CLICK_REGIONS_2.area,
    )

    MATCH_THRESHOLD = 0.80

    FRIEND_STATE_THRESHOLD = 0.90

"""本任务的图片、识别区域和固定操作坐标。"""

from __future__ import annotations

from pathlib import Path

from module.base.assets import ClickAsset, ImageAsset, TaskAssets


ASSET_DIR = Path(__file__).resolve().parent
RES_DIR = ASSET_DIR / "res"
TASKS_DIR = ASSET_DIR.parent
PROJECT_ROOT = ASSET_DIR.parents[1]
MODULE_RES_DIR = PROJECT_ROOT / "module" / "res"


class ExpMonsterAssets(TaskAssets):
    # 庭院主界面
    I_MAIN = ImageAsset(
        file=TASKS_DIR / "CoopReward" / "res" / "explore.png",
        region=((500, 80), (800, 280)),
        threshold=0.9,
        name='main',
    )

    # 组队入口
    I_TEAM = ImageAsset(
        file=RES_DIR / "team.png",
        region=((300, 560), (600, 710)),
        threshold=0.9,
        name='team',
    )

    # 功能菜单卷轴
    I_MENU_SCROLL = ImageAsset(
        file=RES_DIR / "menu_scroll.png",
        region=((1100, 540), (1280, 720)),
        threshold=0.9,
        name='menu_scroll',
    )

    # 经验妖怪分类标记
    I_FLAG = ImageAsset(
        file=RES_DIR / "flag.png",
        region=((390, 105), (610, 195)),
        threshold=0.9,
        name='flag',
    )

    # 经验妖怪分类选项
    I_SELECT = ImageAsset(
        file=RES_DIR / "select.png",
        region=((120, 100), (380, 700)),
        threshold=0.9,
        name='select',
    )

    # 加入队伍按钮
    I_JOIN = ImageAsset(
        file=RES_DIR / "join.png",
        region=((980, 160), (1200, 300)),
        threshold=0.9,
        name='join',
    )

    # 刷新按钮
    I_REFRESH = ImageAsset(
        file=RES_DIR / "reflash.png",
        region=((390, 570), (650, 690)),
        threshold=0.9,
        name='refresh',
    )

    # 准备按钮
    I_PREPARE = ImageAsset(
        file=RES_DIR / "prepare.png",
        region=((1050, 490), (1280, 690)),
        threshold=0.9,
        name='prepare',
    )

    # 战斗进行界面
    I_BATTLE = ImageAsset(
        file=RES_DIR / "battle.png",
        region=((0, 0), (360, 100)),
        threshold=0.9,
        name='battle',
    )

    # 胜利结算界面
    I_WIN = ImageAsset(
        file=RES_DIR / "win.png",
        region=((250, 0), (950, 210)),
        threshold=0.9,
        name='win',
    )

    # 战斗失败界面
    I_DEFEAT = ImageAsset(
        file=RES_DIR / "defeat.png",
        region=((250, 0), (950, 330)),
        threshold=0.9,
        name='defeat',
    )

    # 返回按钮
    I_BACK = ImageAsset(
        file=RES_DIR / "back.png",
        region=((0, 0), (120, 100)),
        threshold=0.9,
        name='back',
    )

    # 退出房间确认弹窗
    I_EXIT_CONFIRM = ImageAsset(
        file=RES_DIR / "exit_confirm.png",
        region=((600, 350), (920, 520)),
        threshold=0.9,
        name='exit_confirm',
    )

    # 手机绑定引导弹窗
    I_PHONE_BIND = ImageAsset(
        file=RES_DIR / "phone_bind.png",
        region=((880, 390), (1160, 640)),
        threshold=0.9,
        name='phone_bind',
    )

    # 手机绑定取消按钮
    I_PHONE_BIND_CANCEL = ImageAsset(
        file=RES_DIR / "phone_bind_cancel.png",
        region=((380, 400), (680, 610)),
        threshold=0.9,
        name='phone_bind_cancel',
    )

    # 结算界面左侧安全点击区域
    C_FINISH_BLANK_AREAS_LEFT = ClickAsset(area=(15, 420, 70, 650), name='finish_blank_areas_left')

    # 结算界面右侧安全点击区域
    C_FINISH_BLANK_AREAS_RIGHT = ClickAsset(area=(1220, 300, 1270, 580), name='finish_blank_areas_right')

    FINISH_BLANK_AREAS = {
        '左侧': C_FINISH_BLANK_AREAS_LEFT.area,
        '右侧': C_FINISH_BLANK_AREAS_RIGHT.area,
    }

    MATCH_THRESHOLD = 0.90

    BACK_MIN_BRIGHTNESS_RATIO = 0.60

    MAX_DUNGEON_LIST_SWIPES = 6

    DUNGEON_LIST_SWIPE_X_RANGE = (210, 310)

    DUNGEON_LIST_SWIPE_START_Y_RANGE = (520, 620)

    DUNGEON_LIST_SWIPE_END_Y_RANGE = (180, 300)

    DUNGEON_LIST_SWIPE_DURATION_RANGE = (650, 1050)

    DUNGEON_LIST_SWIPE_INTERVAL = 1.0

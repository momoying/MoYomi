"""本任务的图片、识别区域和固定操作坐标。"""

from __future__ import annotations

from pathlib import Path

from module.base.assets import ClickAsset, ImageAsset, TaskAssets


ASSET_DIR = Path(__file__).resolve().parent
RES_DIR = ASSET_DIR / "res"
TASKS_DIR = ASSET_DIR.parent
PROJECT_ROOT = ASSET_DIR.parents[1]
MODULE_RES_DIR = PROJECT_ROOT / "module" / "res"


class CoopRewardAssets(TaskAssets):
    # 庭院主界面
    I_MAIN = ImageAsset(
        file=RES_DIR / "explore.png",
        region=((500, 80), (800, 280)),
        threshold=0.8,
        name='main',
    )

    # 御魂入口
    I_SOUL_ENTRY = ImageAsset(
        file=RES_DIR / "soul_entry.png",
        region=((0, 570), (180, 720)),
        threshold=0.9,
        name='soul_entry',
    )

    # 八岐大蛇副本卡片
    I_DUNGEON_CARD = ImageAsset(
        file=RES_DIR / "dungeon_card.png",
        region=((0, 60), (380, 650)),
        threshold=0.8,
        name='dungeon_card',
    )

    # 已选中的御魂十层
    I_FLOOR10_ACTIVE = ImageAsset(
        file=RES_DIR / "floor10_active.png",
        region=((50, 80), (280, 700)),
        threshold=0.9,
        name='floor10_active',
    )

    # 未选中的御魂十层
    I_FLOOR10_INACTIVE = ImageAsset(
        file=RES_DIR / "floor10_inactive.png",
        region=((50, 80), (280, 700)),
        threshold=0.9,
        name='floor10_inactive',
    )

    # 已锁定阵容标记
    I_FORMATION_LOCKED = ImageAsset(
        file=RES_DIR / "formation_locked.png",
        region=((600, 560), (820, 720)),
        threshold=0.88,
        name='formation_locked',
    )

    # 未锁定阵容标记
    I_FORMATION_UNLOCKED = ImageAsset(
        file=RES_DIR / "formation_unlocked.png",
        region=((600, 560), (820, 720)),
        threshold=0.85,
        name='formation_unlocked',
    )

    # 加成灯笼入口
    I_BONUS_LANTERN = ImageAsset(
        file=RES_DIR / "bonus_lantern.png",
        region=((350, 0), (520, 120)),
        threshold=0.9,
        name='bonus_lantern',
    )

    # 御魂加成条目
    I_SOUL_BONUS = ImageAsset(
        file=RES_DIR / "soul_bonus.png",
        region=((300, 100), (960, 550)),
        threshold=0.9,
        name='soul_bonus',
    )

    # 御魂加成开始按钮
    I_BONUS_START = ImageAsset(
        file=RES_DIR / "bonus_start.png",
        region=((750, 100), (930, 520)),
        threshold=0.9,
        name='bonus_start',
    )

    # 挑战按钮
    I_CHALLENGE = ImageAsset(
        file=RES_DIR / "challenge.png",
        region=((1080, 480), (1280, 720)),
        threshold=0.9,
        name='challenge',
    )

    # 胜利过渡界面
    I_VICTORY_TRANSITION = ImageAsset(
        file=RES_DIR / "victory_transition.png",
        region=((180, 40), (1080, 420)),
        threshold=0.9,
        name='victory_transition',
    )

    # 胜利结算界面
    I_WIN = ImageAsset(
        file=RES_DIR / "win.png",
        region=((350, 300), (850, 680)),
        threshold=0.9,
        name='win',
    )

    # 奖励页红色关闭按钮
    I_REWARD_RECOVERY_RED = ImageAsset(
        file=MODULE_RES_DIR / "task_recovery" / "close_red.png",
        region=((0, 0), (1280, 720)),
        threshold=0.8,
        name='reward_recovery_red',
    )

    # 奖励页粉色关闭按钮
    I_REWARD_RECOVERY_PINK = ImageAsset(
        file=MODULE_RES_DIR / "task_recovery" / "close_pink.png",
        region=((0, 0), (1280, 720)),
        threshold=0.8,
        name='reward_recovery_pink',
    )

    # 一键返回庭院按钮
    I_COURTYARD_BACK = ImageAsset(
        file=RES_DIR / "courtyard_back.png",
        region=((60, 0), (180, 100)),
        threshold=0.9,
        name='courtyard_back',
    )

    # 胜利过渡快速点击区域
    C_VICTORY_TRANSITION_CLICK = ClickAsset(area=(1030, 540, 1250, 700), name='victory_transition_click_area')

    # 结算界面左侧安全点击区域
    C_FINISH_BLANK_AREAS_LEFT = ClickAsset(area=(15, 420, 70, 650), name='finish_blank_areas_left')

    # 结算界面右侧安全点击区域
    C_FINISH_BLANK_AREAS_RIGHT = ClickAsset(area=(1220, 300, 1270, 580), name='finish_blank_areas_right')

    # 加成面板左侧空白点击区域
    C_BONUS_PANEL_BLANK_AREAS_LEFT = ClickAsset(area=(250, 180, 340, 500), name='bonus_panel_blank_areas_left')

    # 加成面板右侧空白点击区域
    C_BONUS_PANEL_BLANK_AREAS_RIGHT = ClickAsset(area=(940, 180, 1060, 500), name='bonus_panel_blank_areas_right')

    VICTORY_TRANSITION_CLICK_AREA = C_VICTORY_TRANSITION_CLICK.area

    FINISH_BLANK_AREAS = {
        '左侧': C_FINISH_BLANK_AREAS_LEFT.area,
        '右侧': C_FINISH_BLANK_AREAS_RIGHT.area,
    }

    BONUS_PANEL_BLANK_AREAS = {
        '左侧': C_BONUS_PANEL_BLANK_AREAS_LEFT.area,
        '右侧': C_BONUS_PANEL_BLANK_AREAS_RIGHT.area,
    }

    MAX_FLOOR_SWIPES = 6

    MAX_BONUS_SWIPES = 6

    FLOOR_LIST_SWIPE = (170, 600, 170, 260)

    BONUS_SWIPE_X_RANGE = (520, 780)

    BONUS_SWIPE_START_Y_RANGE = (430, 500)

    BONUS_SWIPE_END_Y_RANGE = (180, 280)

    BONUS_SWIPE_DURATION_RANGE = (650, 1100)

    BONUS_ACTIVE_MIN_YELLOW_RATIO = 0.12

    REWARD_RECOVERY_BUTTONS = (
            ("reward_recovery_red", "红色交叉剑按钮"),
            ("reward_recovery_pink", "粉色交叉剑按钮"),
        )

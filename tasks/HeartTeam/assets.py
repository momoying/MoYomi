"""本任务的图片、识别区域和固定操作坐标。"""

from __future__ import annotations

from pathlib import Path

from module.base.assets import ClickAsset, ImageAsset, TaskAssets


ASSET_DIR = Path(__file__).resolve().parent
RES_DIR = ASSET_DIR / "res"
TASKS_DIR = ASSET_DIR.parent
PROJECT_ROOT = ASSET_DIR.parents[1]
MODULE_RES_DIR = PROJECT_ROOT / "module" / "res"


class HeartTeamAssets(TaskAssets):
    # 庭院主界面
    I_MAIN = ImageAsset(
        file=TASKS_DIR / "CoopReward" / "res" / "explore.png",
        region=((500, 80), (800, 280)),
        threshold=0.8,
        name='main',
    )

    # 组队入口
    I_TEAM = ImageAsset(
        file=RES_DIR / "team.png",
        region=((300, 560), (600, 710)),
        threshold=0.8,
        name='team',
    )

    # 功能菜单卷轴
    I_MENU_SCROLL = ImageAsset(
        file=RES_DIR / "menu_scroll.png",
        region=((1100, 540), (1280, 720)),
        threshold=0.8,
        name='menu_scroll',
    )

    # 同心队入口
    I_HEART_TEAM = ImageAsset(
        file=RES_DIR / "heart_team.png",
        region=((0, 520), (190, 720)),
        threshold=0.8,
        name='heart_team',
    )

    # 集结按钮
    I_RALLY = ImageAsset(
        file=RES_DIR / "rally.png",
        region=((1030, 540), (1280, 720)),
        threshold=0.8,
        name='rally',
    )

    # 队员已确认标记
    I_CONFIRMED = ImageAsset(
        file=RES_DIR / "confirmed.png",
        region=None,
        threshold=0.8,
        name='confirmed',
    )

    # 副本选择入口
    I_DUNGEON = ImageAsset(
        file=RES_DIR / "dungeon.png",
        region=((900, 540), (1110, 720)),
        threshold=0.8,
        name='dungeon',
    )

    # 觉醒副本类型
    I_AWAKENING_TYPE = ImageAsset(
        file=RES_DIR / "awakening_type.png",
        region=((390, 110), (650, 195)),
        threshold=0.8,
        name='awakening_type',
    )

    # 已选中的第一层
    I_FIRST_LEVEL_SELECTED = ImageAsset(
        file=RES_DIR / "first_level_selected.png",
        region=((500, 110), (680, 195)),
        threshold=0.8,
        name='first_level_selected',
    )

    # 第一层选项
    I_FIRST_LEVEL_OPTION = ImageAsset(
        file=RES_DIR / "first_level_option.png",
        region=((390, 170), (590, 570)),
        threshold=0.8,
        name='first_level_option',
    )

    # 创建队伍按钮
    I_CREATE = ImageAsset(
        file=RES_DIR / "create.png",
        region=((760, 520), (990, 660)),
        threshold=0.8,
        name='create',
    )

    # 挑战按钮
    I_CHALLENGE = ImageAsset(
        file=RES_DIR / "challenge.png",
        region=((1100, 500), (1280, 720)),
        threshold=0.85,
        name='challenge',
    )

    # 胜利过渡界面
    I_VICTORY_TRANSITION = ImageAsset(
        file=RES_DIR / "victory_transition.png",
        region=((180, 20), (1080, 420)),
        threshold=0.9,
        name='victory_transition',
    )

    # 奖励结算界面
    I_REWARD = ImageAsset(
        file=RES_DIR / "reward.png",
        region=((350, 300), (900, 680)),
        threshold=0.9,
        name='reward',
    )

    # 返回按钮
    I_BACK = ImageAsset(
        file=RES_DIR / "back.png",
        region=((0, 0), (120, 105)),
        threshold=0.9,
        name='back',
    )

    # 退出队伍按钮
    I_EXIT_TEAM = ImageAsset(
        file=RES_DIR / "exit_team.png",
        region=((690, 0), (850, 135)),
        threshold=0.9,
        name='exit_team',
    )

    # 确认按钮
    I_CONFIRM = ImageAsset(
        file=RES_DIR / "confirm.png",
        region=((600, 350), (900, 520)),
        threshold=0.9,
        name='confirm',
    )

    # 体力预存入口
    I_RESERVE = ImageAsset(
        file=RES_DIR / "reserve.png",
        region=((850, 150), (1040, 610)),
        threshold=0.9,
        name='reserve',
    )

    # 一键预存按钮
    I_ONE_CLICK_RESERVE = ImageAsset(
        file=RES_DIR / "one_click_reserve.png",
        region=((1120, 470), (1280, 700)),
        threshold=0.9,
        name='one_click_reserve',
    )

    # 觉醒副本集结按钮
    C_AWAKENING_RALLY = ClickAsset(area=(398, 309, 884, 376), name='awakening_rally_button')

    # 觉醒副本分类按钮
    C_AWAKENING_CATEGORY = ClickAsset(area=(145, 270, 365, 330), name='awakening_category_button')

    # 创建队伍确认按钮
    C_CREATE_TEAM = ClickAsset(area=(982, 595, 1160, 662), name='create_team_button')

    # 胜利过渡快速点击区域
    C_VICTORY_TRANSITION_CLICK = ClickAsset(area=(1030, 540, 1250, 700), name='victory_transition_click_area')

    # 奖励界面左侧安全点击区域
    C_REWARD_BLANK_AREAS_LEFT = ClickAsset(area=(15, 420, 90, 650), name='reward_blank_areas_left')

    # 奖励界面右侧安全点击区域
    C_REWARD_BLANK_AREAS_RIGHT = ClickAsset(area=(1190, 350, 1270, 650), name='reward_blank_areas_right')

    AWAKENING_RALLY_BUTTON = C_AWAKENING_RALLY.area

    AWAKENING_CATEGORY_BUTTON = C_AWAKENING_CATEGORY.area

    CREATE_TEAM_BUTTON = C_CREATE_TEAM.area

    VICTORY_TRANSITION_CLICK_AREA = C_VICTORY_TRANSITION_CLICK.area

    REWARD_BLANK_AREAS = {
        '左侧': C_REWARD_BLANK_AREAS_LEFT.area,
        '右侧': C_REWARD_BLANK_AREAS_RIGHT.area,
    }

    # 队友 1 头像点击区域
    C_MEMBER_1_AVATAR = ClickAsset(area=(545, 202, 630, 292), name='member_1_avatar')

    # 队友 2 头像点击区域
    C_MEMBER_2_AVATAR = ClickAsset(area=(650, 202, 735, 292), name='member_2_avatar')

    MEMBER_SLOTS = (
        {
            'label': '队友1',
            'avatar': C_MEMBER_1_AVATAR.area,
            'confirmed': (592, 245, 632, 285),
        },
        {
            'label': '队友2',
            'avatar': C_MEMBER_2_AVATAR.area,
            'confirmed': (697, 245, 737, 285),
        },
    )

    MATCH_THRESHOLD = 0.80

    LEVEL_LIST_BOUNDS = (400, 170, 575, 570)

    LEVEL_OPTION_VERTICAL_PADDING = 8

    STAMINA_TEXT_REGION = (930, 410, 1100, 495)

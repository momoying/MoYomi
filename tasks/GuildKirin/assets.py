"""本任务的图片、识别区域和固定操作坐标。"""

from __future__ import annotations

from pathlib import Path

from module.base.assets import ClickAsset, ImageAsset, TaskAssets


ASSET_DIR = Path(__file__).resolve().parent
RES_DIR = ASSET_DIR / "res"
TASKS_DIR = ASSET_DIR.parent
PROJECT_ROOT = ASSET_DIR.parents[1]
MODULE_RES_DIR = PROJECT_ROOT / "module" / "res"


class GuildKirinAssets(TaskAssets):
    # 庭院主界面
    I_MAIN = ImageAsset(
        file=TASKS_DIR / "CoopReward" / "res" / "explore.png",
        region=((500, 80), (800, 280)),
        threshold=0.8,
        name='main',
    )

    # 阴阳寮入口
    I_GUILD_ENTRY = ImageAsset(
        file=RES_DIR / "guild_entry.png",
        region=((450, 560), (680, 720)),
        threshold=0.8,
        name='guild_entry',
    )

    # 功能菜单卷轴
    I_MENU_SCROLL = ImageAsset(
        file=RES_DIR / "menu_scroll.png",
        region=((1100, 540), (1280, 720)),
        threshold=0.8,
        name='menu_scroll',
    )

    # 狩猎战入口
    I_HUNTING_ENTRY = ImageAsset(
        file=RES_DIR / "hunting_entry.png",
        region=((0, 210), (260, 350)),
        threshold=0.82,
        name='hunting_entry',
    )

    # 挑战按钮
    I_CHALLENGE = ImageAsset(
        file=RES_DIR / "challenge.png",
        region=((1040, 500), (1280, 720)),
        threshold=0.82,
        name='challenge',
    )

    # 已挑战状态
    I_ALREADY_CHALLENGED = ImageAsset(
        file=RES_DIR / "already_challenged.png",
        region=((1040, 500), (1280, 720)),
        threshold=0.82,
        name='already_challenged',
    )

    # 准备按钮
    I_PREPARE = ImageAsset(
        file=RES_DIR / "prepare.png",
        region=((1040, 480), (1280, 720)),
        threshold=0.82,
        name='prepare',
    )

    # 胜利结算界面
    I_WIN = ImageAsset(
        file=RES_DIR / "win.png",
        region=((200, 20), (1050, 380)),
        threshold=0.82,
        name='win',
    )

    # 战斗失败界面
    I_DEFEAT = ImageAsset(
        file=RES_DIR / "defeat.png",
        region=((250, 0), (700, 350)),
        threshold=0.75,
        name='defeat',
    )

    # 狩猎战返回按钮
    I_HUNT_BACK = ImageAsset(
        file=RES_DIR / "hunt_back.png",
        region=((0, 0), (130, 110)),
        threshold=0.8,
        name='hunt_back',
    )

    # 阴阳寮返回按钮
    I_GUILD_BACK = ImageAsset(
        file=RES_DIR / "guild_back.png",
        region=((0, 0), (130, 110)),
        threshold=0.8,
        name='guild_back',
    )

    # 失败界面左侧安全点击区域
    C_FAILURE_BLANK_AREAS_LEFT = ClickAsset(area=(20, 300, 180, 650), name='failure_blank_areas_left')

    # 失败界面右侧安全点击区域
    C_FAILURE_BLANK_AREAS_RIGHT = ClickAsset(area=(1100, 300, 1260, 650), name='failure_blank_areas_right')

    # 胜利界面左下安全点击区域
    C_VICTORY_BLANK_AREAS_LEFT_BOTTOM = ClickAsset(area=(40, 560, 320, 680), name='victory_blank_areas_left_bottom')

    # 胜利界面右下安全点击区域
    C_VICTORY_BLANK_AREAS_RIGHT_BOTTOM = ClickAsset(area=(960, 560, 1240, 680), name='victory_blank_areas_right_bottom')

    FAILURE_BLANK_AREAS = {
        '左侧': C_FAILURE_BLANK_AREAS_LEFT.area,
        '右侧': C_FAILURE_BLANK_AREAS_RIGHT.area,
    }

    VICTORY_BLANK_AREAS = {
        '左下': C_VICTORY_BLANK_AREAS_LEFT_BOTTOM.area,
        '右下': C_VICTORY_BLANK_AREAS_RIGHT_BOTTOM.area,
    }

"""本任务的图片、识别区域和固定操作坐标。"""

from __future__ import annotations

from pathlib import Path

from module.base.assets import ClickAsset, ImageAsset, TaskAssets


ASSET_DIR = Path(__file__).resolve().parent
RES_DIR = ASSET_DIR / "res"
TASKS_DIR = ASSET_DIR.parent
PROJECT_ROOT = ASSET_DIR.parents[1]
MODULE_RES_DIR = PROJECT_ROOT / "module" / "res"


class SecretBattleAssets(TaskAssets):
    # 挑战按钮
    I_CHALLENGE = ImageAsset(
        file=RES_DIR / "challenge.png",
        region=((930, 450), (1280, 720)),
        threshold=0.8,
        name='challenge',
    )

    # 黑蛋已获得标记
    I_OBTAINED = ImageAsset(
        file=RES_DIR / "black_egg_obtained.png",
        region=((120, 80), (640, 680)),
        threshold=0.8,
        name='obtained',
    )

    # 奖励结算界面
    I_REWARD = ImageAsset(
        file=RES_DIR / "battle_reward.png",
        region=((300, 250), (980, 720)),
        threshold=0.8,
        name='reward',
    )

    # 挑战失败界面
    I_FAILED = ImageAsset(
        file=RES_DIR / "battle_failed.png",
        region=((350, 40), (1100, 380)),
        threshold=0.76,
        name='failed',
    )

    # 准备按钮
    I_PREPARE = ImageAsset(
        file=RES_DIR / "battle_prepare.png",
        region=((1020, 450), (1280, 720)),
        threshold=0.8,
        name='prepare',
    )

    # 结算界面左下安全点击区域
    C_BLANK_AREAS_LEFT_BOTTOM = ClickAsset(area=(60, 560, 320, 660), name='blank_areas_left_bottom')

    # 结算界面右下安全点击区域
    C_BLANK_AREAS_RIGHT_BOTTOM = ClickAsset(area=(960, 560, 1220, 660), name='blank_areas_right_bottom')

    BLANK_AREAS = {
        '左下': C_BLANK_AREAS_LEFT_BOTTOM.area,
        '右下': C_BLANK_AREAS_RIGHT_BOTTOM.area,
    }

    CHALLENGE_TEMPLATE = I_CHALLENGE.file
    CHALLENGE_REGION = I_CHALLENGE.region
    CHALLENGE_THRESHOLD = I_CHALLENGE.threshold
    OBTAINED_TEMPLATE = I_OBTAINED.file
    OBTAINED_REGION = I_OBTAINED.region
    OBTAINED_THRESHOLD = I_OBTAINED.threshold
    REWARD_TEMPLATE = I_REWARD.file
    REWARD_REGION = I_REWARD.region
    REWARD_THRESHOLD = I_REWARD.threshold
    FAILED_TEMPLATE = I_FAILED.file
    FAILED_REGION = I_FAILED.region
    FAILED_THRESHOLD = I_FAILED.threshold
    PREPARE_TEMPLATE = I_PREPARE.file
    PREPARE_REGION = I_PREPARE.region
    PREPARE_THRESHOLD = I_PREPARE.threshold

"""本任务的图片、识别区域和固定操作坐标。"""

from __future__ import annotations

from pathlib import Path

from module.base.assets import ClickAsset, ImageAsset, TaskAssets


ASSET_DIR = Path(__file__).resolve().parent
RES_DIR = ASSET_DIR / "res"
TASKS_DIR = ASSET_DIR.parent
PROJECT_ROOT = ASSET_DIR.parents[1]
MODULE_RES_DIR = PROJECT_ROOT / "module" / "res"


class OneTapDailyAssets(TaskAssets):
    # 庭院主界面
    I_MAIN = ImageAsset(
        file=TASKS_DIR / "CoopReward" / "res" / "explore.png",
        region=((500, 80), (800, 280)),
        threshold=0.8,
        name='main',
    )

    # 每日任务列表入口
    I_TASK_LIST = ImageAsset(
        file=RES_DIR / "flag.png",
        region=((0, 360), (1280, 590)),
        threshold=0.8,
        name='task_list',
    )

    # 一键完成按钮
    I_ONE_TAP = ImageAsset(
        file=RES_DIR / "finish.png",
        region=((1030, 520), (1280, 720)),
        threshold=0.8,
        name='one_tap',
    )

    # 返回按钮
    I_BACK = ImageAsset(
        file=RES_DIR / "back.png",
        region=((0, 0), (120, 100)),
        threshold=0.8,
        name='back',
    )

    # 每日签到关闭按钮
    I_SIGN_IN_CLOSE = ImageAsset(
        file=RES_DIR / "sign_in_close.png",
        region=((760, 40), (980, 190)),
        threshold=0.8,
        name='sign_in_close',
    )

    # 领取成功弹窗
    I_REWARD_SUCCESS = ImageAsset(
        file=RES_DIR / "reward_success.png",
        region=((240, 0), (600, 120)),
        threshold=0.8,
        name='reward_success',
    )

    # 任务已完成标记
    I_COMPLETED = ImageAsset(
        file=RES_DIR / "completed.png",
        region=((900, 100), (1140, 240)),
        threshold=0.8,
        name='completed',
    )

    # 每日任务页签点击区域
    C_DAILY_TAB_CLICK = ClickAsset(area=(1140, 120, 1210, 205), name='daily_tab_click_region')

    # 奖励弹窗右侧外部空白点击区域
    C_REWARD_OUTSIDE_RIGHT_REGIONS_1 = ClickAsset(area=(1185, 220, 1265, 500), name='reward_outside_right_regions_1')

    DAILY_TAB_CLICK_REGION = C_DAILY_TAB_CLICK.area

    REWARD_OUTSIDE_RIGHT_REGIONS = (
        C_REWARD_OUTSIDE_RIGHT_REGIONS_1.area,
    )

    MATCH_THRESHOLD = 0.80

    BACK_MIN_SATURATION_RATIO = 0.55

    BACK_MIN_BRIGHTNESS_RATIO = 0.55

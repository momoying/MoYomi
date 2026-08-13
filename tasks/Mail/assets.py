"""本任务的图片、识别区域和固定操作坐标。"""

from __future__ import annotations

from pathlib import Path

from module.base.assets import ClickAsset, ImageAsset, TaskAssets


ASSET_DIR = Path(__file__).resolve().parent
RES_DIR = ASSET_DIR / "res"
TASKS_DIR = ASSET_DIR.parent
PROJECT_ROOT = ASSET_DIR.parents[1]
MODULE_RES_DIR = PROJECT_ROOT / "module" / "res"


class MailAssets(TaskAssets):
    # 庭院主界面
    I_MAIN = ImageAsset(
        file=TASKS_DIR / "CoopReward" / "res" / "explore.png",
        region=((500, 80), (800, 280)),
        threshold=0.8,
        name='main',
    )

    # 未读邮件入口
    I_MAIL_UNREAD = ImageAsset(
        file=RES_DIR / "mail_unread.png",
        region=((1080, 0), (1210, 100)),
        threshold=0.95,
        name='mail_unread',
    )

    # 普通邮件入口
    I_MAIL_NORMAL = ImageAsset(
        file=RES_DIR / "mail_normal.png",
        region=((1080, 0), (1210, 100)),
        threshold=0.95,
        name='mail_normal',
    )

    # 领取全部邮件按钮
    I_CLAIM_ALL = ImageAsset(
        file=RES_DIR / "claim_all.png",
        region=((0, 520), (230, 720)),
        threshold=0.86,
        name='claim_all',
    )

    # 全部标记已读按钮
    I_MARK_ALL_READ = ImageAsset(
        file=RES_DIR / "mark_all_read.png",
        region=((140, 560), (340, 690)),
        threshold=0.86,
        name='mark_all_read',
    )

    # 确认按钮
    I_CONFIRM = ImageAsset(
        file=RES_DIR / "confirm.png",
        region=((600, 480), (930, 670)),
        threshold=0.86,
        name='confirm',
    )

    # 奖励结算界面
    I_REWARD = ImageAsset(
        file=RES_DIR / "reward.png",
        region=((300, 30), (950, 280)),
        threshold=0.86,
        name='reward',
    )

    # 插画提示取消按钮
    I_ILLUSTRATION_CANCEL = ImageAsset(
        file=RES_DIR / "cancel.png",
        region=((0, 0), (1280, 720)),
        threshold=0.9,
        name='illustration_cancel',
    )

    # 关闭按钮
    I_CLOSE = ImageAsset(
        file=RES_DIR / "close.png",
        region=((1080, 20), (1270, 210)),
        threshold=0.86,
        name='close',
    )

    # 奖励界面左侧安全点击区域
    C_REWARD_BLANK_AREAS_LEFT = ClickAsset(area=(40, 250, 190, 620), name='reward_blank_areas_left')

    # 奖励界面右侧安全点击区域
    C_REWARD_BLANK_AREAS_RIGHT = ClickAsset(area=(1060, 250, 1160, 620), name='reward_blank_areas_right')

    REWARD_BLANK_AREAS = {
        '左侧': C_REWARD_BLANK_AREAS_LEFT.area,
        '右侧': C_REWARD_BLANK_AREAS_RIGHT.area,
    }

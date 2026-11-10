"""1280×720 觉醒一层、胜利和奖励页的识别资源。"""

from pathlib import Path

from module.assets import CommonUIAssets
from module.base.assets import ClickAsset, ImageAsset, TaskAssets


RES_DIR = Path(__file__).resolve().parent / "res"


class SuperOniAssets(TaskAssets):
    # 觉醒材料页标题，避免在其他副本误点挑战。
    I_AWAKENING = ImageAsset(RES_DIR / "awakening.png", ((140, 5), (310, 70)), .88, "awakening")
    # 已选中的觉醒一层红色标签。
    I_FLOOR_ONE = ImageAsset(RES_DIR / "floor_one.png", ((80, 85), (245, 165)), .88, "floor_one")
    # 觉醒挑战按钮文字，不包含体力数量。
    I_CHALLENGE = ImageAsset(RES_DIR / "challenge.png", ((1100, 555), (1270, 685)), .88, "challenge")
    # 胜利过渡页的大字。
    I_VICTORY = ImageAsset(RES_DIR / "victory.png", ((660, 65), (1050, 295)), .85, "victory")
    # 奖励页中间宝箱，不依赖右上角票数或奖励种类。
    I_REWARD = ImageAsset(RES_DIR / "reward.png", ((470, 385), (780, 650)), .82, "reward")
    # 复用现有战斗失败模板，失败时停止刷票。
    I_FAILED = ImageAsset(RES_DIR.parents[1] / "SecretBattle" / "res" / "battle_failed.png",
                          ((350, 40), (1100, 380)), .80, "failed")
    # 已上锁的阵容标记，复用公共模板。
    I_FORMATION_LOCKED = ImageAsset(CommonUIAssets.I_FORMATION_LOCKED.file,
                                   ((690, 645), (740, 695)), .88, "formation_locked")
    # 未上锁的阵容标记，从觉醒页截图提取。
    I_FORMATION_UNLOCKED = ImageAsset(RES_DIR / "formation_unlocked.png",
                                     ((690, 645), (740, 695)), .88, "formation_unlocked")
    # 觉醒页左上方加成灯笼。
    I_BONUS_LANTERN = ImageAsset(RES_DIR / "bonus_lantern.png", ((505, 20), (580, 90)), .88, "bonus_lantern")
    # 觉醒材料加成行，仅截说明文字，不包含会变化的剩余时间。
    I_AWAKENING_BONUS = ImageAsset(RES_DIR / "awakening_bonus.png",
                                  ((370, 115), (765, 510)), .88, "awakening_bonus")
    # 胜利页下方安全空白，避开人物头像与底部提示。
    C_VICTORY_BLANK = ClickAsset((360, 585, 930, 665), "victory_blank")
    # 奖励页左侧安全空白，避开左下角加成与统计按钮。
    C_REWARD_LEFT = ClickAsset((90, 550, 330, 620), "reward_left")
    # 奖励页右侧安全空白，避开中间宝箱。
    C_REWARD_RIGHT = ClickAsset((970, 550, 1210, 620), "reward_right")
    # 加成面板左侧空白，避开层数栏。
    C_BONUS_LEFT = ClickAsset((255, 190, 335, 490), "bonus_left")
    # 加成面板右侧空白，避开挑战与组队按钮。
    C_BONUS_RIGHT = ClickAsset((945, 320, 1050, 490), "bonus_right")

    TICKET_REGION = (1138, 6, 1226, 36)

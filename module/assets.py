"""公共恢复流程与菜单操作使用的视觉资源。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

from module.base.assets import ClickAsset, ImageAsset, TaskAssets


MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parent
TASKS_DIR = PROJECT_ROOT / "tasks"
RES_DIR = MODULE_DIR / "res"
STARTUP_RES_DIR = RES_DIR / "startup_recovery"
RECOVERY_RES_DIR = RES_DIR / "task_recovery"

# 保留旧模块使用的目录别名。
ASSET_DIR = STARTUP_RES_DIR
CORE_DIR = MODULE_DIR
HELPER_DIR = PROJECT_ROOT
DAILY_DIR = TASKS_DIR
SCRIPT_DIR = MODULE_DIR


@dataclass(frozen=True)
class StartupMatchSpec:
    path: Path
    region: Tuple[Tuple[int, int], Tuple[int, int]]
    threshold: float = 0.80


@dataclass(frozen=True)
class RecoveryMatchSpec:
    path: Path
    label: str
    threshold: float = 0.80


class StartupAssets(TaskAssets):
    """程序启动时恢复到可执行状态所需的资源。"""

    # 登录按钮
    I_LOGIN = ImageAsset(
        file=TASKS_DIR / "Account" / "res" / "sign.png",
        region=((360, 390), (920, 500)),
        name="login",
    )

    # 庭院主界面
    I_MAIN = ImageAsset(
        file=TASKS_DIR / "CoopReward" / "res" / "explore.png",
        region=((500, 80), (800, 280)),
        name="main",
    )

    # 一键返回庭院按钮
    I_COURTYARD_BACK = ImageAsset(
        file=STARTUP_RES_DIR / "courtyard_back.png",
        region=((60, 0), (180, 100)),
        threshold=0.88,
        name="courtyard_back",
    )

    # 战斗界面
    I_BATTLE = ImageAsset(
        file=TASKS_DIR / "Exp" / "res" / "battle.png",
        region=((0, 0), (360, 100)),
        name="battle",
    )

    # 战斗准备按钮
    I_PREPARE_BUTTON = ImageAsset(
        file=TASKS_DIR / "Exp" / "res" / "prepare.png",
        region=((1050, 490), (1280, 690)),
        name="prepare_button",
    )

    # 准备倒计时房间
    I_READY_ROOM = ImageAsset(
        file=STARTUP_RES_DIR / "ready_room.png",
        region=((0, 0), (360, 100)),
        name="ready_room",
    )

    # 退出房间确认弹窗
    I_ROOM_EXIT_CONFIRM = ImageAsset(
        file=TASKS_DIR / "Exp" / "res" / "exit_confirm.png",
        region=((600, 350), (920, 520)),
        threshold=0.90,
        name="room_exit_confirm",
    )

    # 退出组队确认弹窗
    I_HEART_EXIT_CONFIRM = ImageAsset(
        file=TASKS_DIR / "HeartTeam" / "res" / "confirm.png",
        region=((600, 350), (900, 520)),
        threshold=0.90,
        name="heart_exit_confirm",
    )

    # 普通战斗结算界面
    I_SETTLEMENT = ImageAsset(
        file=TASKS_DIR / "Exp" / "res" / "win.png",
        region=((250, 0), (950, 210)),
        name="settlement",
    )

    # 协战奖励结算界面
    I_COOP_SETTLEMENT = ImageAsset(
        file=TASKS_DIR / "CoopReward" / "res" / "win.png",
        region=((350, 300), (850, 680)),
        threshold=0.90,
        name="coop_settlement",
    )

    # 御魂入口
    I_COOP_SOUL_ENTRY = ImageAsset(
        file=TASKS_DIR / "CoopReward" / "res" / "soul_entry.png",
        region=((0, 570), (180, 720)),
        threshold=0.90,
        name="coop_soul_entry",
    )

    # 御魂副本卡片
    I_COOP_DUNGEON_CARD = ImageAsset(
        file=TASKS_DIR / "CoopReward" / "res" / "dungeon_card.png",
        region=((0, 60), (380, 650)),
        threshold=0.90,
        name="coop_dungeon_card",
    )

    # 协战挑战按钮
    I_COOP_CHALLENGE = ImageAsset(
        file=TASKS_DIR / "CoopReward" / "res" / "challenge.png",
        region=((1080, 480), (1280, 720)),
        threshold=0.90,
        name="coop_challenge",
    )

    # 用户中心入口
    I_SETTINGS_CENTER = ImageAsset(
        file=TASKS_DIR / "Account" / "res" / "center.png",
        region=((170, 380), (330, 530)),
        name="settings_center",
    )

    # 切换账号按钮
    I_SWITCH_ACCOUNT = ImageAsset(
        file=TASKS_DIR / "Account" / "res" / "swithch_account.png",
        region=((880, 130), (1130, 290)),
        name="switch_account",
    )

    # 账号列表标记
    I_ACCOUNT_LIST = ImageAsset(
        file=TASKS_DIR / "Account" / "res" / "count_flag.png",
        region=((379, 380), (470, 604)),
        threshold=0.82,
        name="account_list",
    )

    # iOS 平台入口
    I_IOS = ImageAsset(
        file=TASKS_DIR / "Account" / "res" / "IOS.png",
        region=((480, 320), (640, 470)),
        name="ios",
    )

    # Android 平台入口
    I_ANDROID = ImageAsset(
        file=TASKS_DIR / "Account" / "res" / "Android.png",
        region=((640, 320), (800, 470)),
        name="android",
    )

    # 签到弹窗关闭按钮
    I_SIGN_IN_CLOSE = ImageAsset(
        file=TASKS_DIR / "OneTapDaily" / "res" / "sign_in_close.png",
        region=((760, 40), (980, 190)),
        name="sign_in_close",
    )

    # 奖励领取成功界面
    I_REWARD_SUCCESS = ImageAsset(
        file=STARTUP_RES_DIR / "reward_success.png",
        region=((240, 0), (600, 120)),
        name="reward_success",
    )

    # 好友页面关闭按钮
    I_FRIEND_CLOSE = ImageAsset(
        file=TASKS_DIR / "Like" / "res" / "back.png",
        region=((1100, 50), (1240, 180)),
        name="friend_close",
    )

    # 悬赏封印页面关闭按钮
    I_BOUNTY_CLOSE = ImageAsset(
        file=TASKS_DIR / "Bounty" / "res" / "back.png",
        region=((1050, 60), (1250, 210)),
        name="bounty_close",
    )

    # 组队页面返回按钮
    I_EXP_BACK = ImageAsset(
        file=TASKS_DIR / "Exp" / "res" / "back.png",
        region=((0, 0), (120, 100)),
        name="exp_back",
    )

    # 一键日常返回按钮
    I_DAILY_BACK = ImageAsset(
        file=TASKS_DIR / "OneTapDaily" / "res" / "back.png",
        region=((0, 0), (120, 100)),
        name="daily_back",
    )

    # 商店热门推荐页标记
    I_MERCHANT_POPULAR = ImageAsset(
        file=TASKS_DIR / "Merchant" / "res" / "popular_marker.png",
        region=((100, 0), (360, 100)),
        threshold=0.88,
        name="merchant_popular",
    )

    # 神秘商人入口
    I_MERCHANT_TOWN = ImageAsset(
        file=TASKS_DIR / "Merchant" / "res" / "merchant_entry.png",
        region=((0, 360), (180, 620)),
        threshold=0.88,
        name="merchant_town",
    )

    # 神秘商店刷新按钮
    I_MERCHANT_PAGE = ImageAsset(
        file=TASKS_DIR / "Merchant" / "res" / "refresh.png",
        region=((1120, 450), (1280, 700)),
        threshold=0.88,
        name="merchant_page",
    )

    # 奖励界面外侧安全点击区域
    C_REWARD_OUTSIDE_RIGHT = ClickAsset(
        area=(1185, 220, 1265, 500),
        name="reward_outside_right",
    )

    MATCH_THRESHOLD = 0.80
    REWARD_OUTSIDE_RIGHT_REGIONS = (C_REWARD_OUTSIDE_RIGHT.area,)
    SPECS = {}

    SAFE_ROOM_STATES = (
        ("prepare_button", "准备界面"),
        ("ready_room", "准备倒计时房间"),
    )
    ROOM_EXIT_CONFIRM_STATES = (
        ("room_exit_confirm", "退出房间确认"),
        ("heart_exit_confirm", "退出组队确认"),
    )
    CLICK_ACTIONS = (
        ("courtyard_back", "一键返回庭院按钮"),
        ("sign_in_close", "签到弹窗关闭按钮"),
        ("switch_account", "切换账号"),
        ("settings_center", "用户中心"),
        ("friend_close", "好友页关闭按钮"),
        ("bounty_close", "悬赏页关闭按钮"),
        ("exp_back", "组队页返回按钮"),
        ("daily_back", "一键日常返回按钮"),
    )


# TaskAssets 在类创建完成时生成兼容资源映射，这里再恢复旧流程使用的规格表。
StartupAssets.SPECS = {
    name: StartupMatchSpec(asset.file, asset.region, asset.threshold)
    for name, asset in StartupAssets.IMAGES.items()
}


class RecoveryAssets(TaskAssets):
    """任务失败后返回庭院所需的资源。"""

    # 协战奖励界面
    I_COOP_REWARD = ImageAsset(
        file=TASKS_DIR / "CoopReward" / "res" / "win.png",
        region=((0, 0), (1280, 720)),
        threshold=0.90,
        name="coop_reward",
    )

    # 手机绑定引导的取消按钮
    I_PHONE_BIND_CANCEL = ImageAsset(
        file=TASKS_DIR / "Exp" / "res" / "phone_bind_cancel.png",
        region=((380, 400), (680, 610)),
        threshold=0.90,
        name="phone_bind_cancel",
    )

    # 关联手机奖励页的前往绑定按钮
    I_PHONE_BIND = ImageAsset(
        file=TASKS_DIR / "Exp" / "res" / "phone_bind.png",
        region=((880, 390), (1160, 640)),
        threshold=0.90,
        name="phone_bind",
    )

    # 返回庭院按钮
    I_COURTYARD = ImageAsset(
        file=RECOVERY_RES_DIR / "courtyard.png",
        region=((0, 0), (1280, 720)),
        name="courtyard",
    )

    # 通用返回按钮
    I_BACK = ImageAsset(
        file=RECOVERY_RES_DIR / "back.png",
        region=((0, 0), (1280, 720)),
        name="back",
    )

    # 粉色关闭按钮
    I_CLOSE_PINK = ImageAsset(
        file=RECOVERY_RES_DIR / "close_pink.png",
        region=((0, 0), (1280, 720)),
        name="close_pink",
    )

    # 红色关闭按钮
    I_CLOSE_RED = ImageAsset(
        file=RECOVERY_RES_DIR / "close_red.png",
        region=((0, 0), (1280, 720)),
        name="close_red",
    )

    # 协战奖励左侧安全点击区域
    C_COOP_REWARD_LEFT = ClickAsset(
        area=(15, 420, 70, 650),
        name="coop_reward_left",
    )

    # 协战奖励右侧安全点击区域
    C_COOP_REWARD_RIGHT = ClickAsset(
        area=(1220, 300, 1270, 580),
        name="coop_reward_right",
    )

    MATCH_THRESHOLD = 0.80
    FULL_SCREEN = ((0, 0), (1280, 720))
    COURTYARD_REGION = ((500, 80), (800, 280))
    COURTYARD_TEMPLATE = StartupAssets.I_MAIN.file
    COOP_REWARD_TEMPLATE = I_COOP_REWARD.file
    COOP_REWARD_SAFE_AREAS = {
        "左侧": C_COOP_REWARD_LEFT.area,
        "右侧": C_COOP_REWARD_RIGHT.area,
    }
    ACTION_SPECS = (
        ("courtyard", RecoveryMatchSpec(I_COURTYARD.file, "返回庭院按钮")),
        ("back", RecoveryMatchSpec(I_BACK.file, "返回按钮")),
        ("close_pink", RecoveryMatchSpec(I_CLOSE_PINK.file, "粉色关闭按钮")),
        ("close_red", RecoveryMatchSpec(I_CLOSE_RED.file, "红色关闭按钮")),
        # 通用退出按钮均未命中时，再处理偶发的手机绑定两级引导。
        ("phone_bind_cancel", RecoveryMatchSpec(I_PHONE_BIND_CANCEL.file, "手机绑定取消按钮", 0.90)),
        ("phone_bind", RecoveryMatchSpec(I_PHONE_BIND.file, "前往绑定按钮", 0.90)),
        # 协战奖励最少见，放在最后作为专用兜底。
        ("coop_reward", RecoveryMatchSpec(I_COOP_REWARD.file, "协战奖励界面", 0.90)),
    )


class MenuAssets(TaskAssets):
    """通用菜单操作所需的资源。"""

    # 庭院主界面
    I_MAIN = ImageAsset(
        file=TASKS_DIR / "CoopReward" / "res" / "explore.png",
        region=((500, 80), (800, 280)),
        name="main",
    )

    # 功能菜单安全点击区域
    C_MENU_SAFE = ClickAsset(
        area=(1205, 645, 1245, 685),
        name="menu_safe",
    )

    MAIN_TEMPLATE = I_MAIN.file
    MAIN_SEARCH_REGION = I_MAIN.region
    MAIN_THRESHOLD = I_MAIN.threshold
    MENU_SAFE_CLICK_REGION = C_MENU_SAFE.area

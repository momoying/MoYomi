"""本任务的图片、识别区域和固定操作坐标。"""

from __future__ import annotations

from pathlib import Path

from module.base.assets import ClickAsset, ImageAsset, TaskAssets


ASSET_DIR = Path(__file__).resolve().parent
RES_DIR = ASSET_DIR / "res"
TASKS_DIR = ASSET_DIR.parent
PROJECT_ROOT = ASSET_DIR.parents[1]
MODULE_RES_DIR = PROJECT_ROOT / "module" / "res"


class SignAssets(TaskAssets):
    # 账号登录按钮
    I_LOGIN = ImageAsset(
        file=RES_DIR / "sign.png",
        region=((360, 390), (920, 500)),
        threshold=0.8,
        name='login',
    )

    # IOS 系统入口
    I_IOS = ImageAsset(
        file=RES_DIR / "IOS.png",
        region=((480, 320), (640, 470)),
        threshold=0.8,
        name='ios',
    )

    # Android 系统入口
    I_ANDROID = ImageAsset(
        file=RES_DIR / "Android.png",
        region=((640, 320), (800, 470)),
        threshold=0.8,
        name='android',
    )

    # 区服选择界面
    I_REGION_SELECTION = ImageAsset(
        file=RES_DIR / "select_region.png",
        region=((430, 20), (850, 120)),
        threshold=0.8,
        name='region_selection',
    )

    # 进入游戏文字点击区域
    C_ENTER_GAME_CLICK = ClickAsset(area=(555, 570, 725, 625), name='enter_game_click_region')

    # 区服切换点击区域
    C_REGION_SWITCH_CLICK = ClickAsset(area=(720, 510, 815, 540), name='region_switch_click_region')

    # 左侧区服卡片点击区域
    C_REGION_CARD_CLICK_REGIONS_LEFT = ClickAsset(area=(420, 130, 730, 250), name='region_card_click_regions_left')

    # 右侧区服卡片点击区域
    C_REGION_CARD_CLICK_REGIONS_RIGHT = ClickAsset(area=(755, 130, 1065, 250), name='region_card_click_regions_right')

    ENTER_GAME_CLICK_REGION = C_ENTER_GAME_CLICK.area

    REGION_SWITCH_CLICK_REGION = C_REGION_SWITCH_CLICK.area

    REGION_CARD_CLICK_REGIONS = {
        'left': C_REGION_CARD_CLICK_REGIONS_LEFT.area,
        'right': C_REGION_CARD_CLICK_REGIONS_RIGHT.area,
    }

    ENTER_GAME_TEXT_REGION = (500, 540, 780, 640)

    SERVER_TEXT_REGION = (520, 490, 715, 550)

    REGION_CARD_NAME_OCR_REGIONS = {
            "left": (515, 140, 660, 176),
            "right": (845, 140, 990, 176),
        }

    MATCH_THRESHOLD = 0.80

    VALID_REGIONS = ("same", "cross")



class SwitchAssets(TaskAssets):
    # 用户中心入口
    I_CENTER = ImageAsset(
        file=RES_DIR / "center.png",
        region=((170, 380), (330, 530)),
        threshold=0.8,
        name='center',
    )

    # 切换账号按钮
    I_SWITCH_ACCOUNT = ImageAsset(
        file=RES_DIR / "swithch_account.png",
        region=((880, 130), (1130, 290)),
        threshold=0.8,
        name='switch_account',
    )

    # 账号列表标记
    I_COUNT_FLAG = ImageAsset(
        file=RES_DIR / "count_flag.png",
        region=None,
        threshold=0.8,
        name='count_flag',
    )

    # 庭院头像点击区域
    C_AVATAR_CLICK = ClickAsset(area=(42, 42, 68, 72), name='avatar_click_region')

    # 登录账号栏点击区域
    C_LOGIN_ACCOUNT = ClickAsset(area=(379, 276, 901, 382), name='login_account_region')

    # 登录按钮点击区域
    C_LOGIN = ClickAsset(area=(379, 410, 901, 480), name='login_button_region')

    AVATAR_CLICK_REGION = C_AVATAR_CLICK.area

    LOGIN_ACCOUNT_REGION = C_LOGIN_ACCOUNT.area

    LOGIN_BUTTON_REGION = C_LOGIN.area

    ACCOUNT_LIST_REGION = (379, 276, 901, 604)

    COUNT_FLAG_SEARCH_REGION = (379, 276, 470, 604)

    ACCOUNT_TEXT_RIGHT = 820

    MATCH_THRESHOLD = 0.80

    COUNT_FLAG_THRESHOLD = 0.82

    ACCOUNT_LIST_MAX_SWIPES = 12

    ACCOUNT_LIST_SWIPE_DURATION_MS = 1200

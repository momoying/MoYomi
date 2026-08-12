"""启动界面恢复：只对已知安全界面执行操作，最终回到账号登录页。"""

from __future__ import annotations

import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple


CORE_DIR = Path(__file__).resolve().parent
HELPER_DIR = CORE_DIR.parent
DAILY_DIR = HELPER_DIR / "Daily"
PROJECT_ROOT = HELPER_DIR
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Core import automation as utils
from Core.logging import TaskLogger


LOGGER = TaskLogger("启动恢复")
print = LOGGER.legacy_print


ASSET_DIR = CORE_DIR / "startup_recovery_assets"
SCREENSHOT_DIR = HELPER_DIR / "startup_recovery_screenshots"
SCREENSHOT_INTERVAL = 0.5
MATCH_THRESHOLD = 0.80
RECOVERY_TIMEOUT_SECONDS = 90.0
ACTION_CONFIRM_SECONDS = 12.0
UNKNOWN_STATE_GRACE_SECONDS = 5.0
REWARD_CONFIRM_SECONDS = 12.0
REWARD_READY_DELAY_SECONDS = 2.0
REWARD_RETRY_DELAY_SECONDS = 3.0
MAX_RECOVERY_STEPS = 12
REWARD_OUTSIDE_RIGHT_REGIONS = (
    (1185, 220, 1265, 500),
)

Rect = Tuple[int, int, int, int]


@dataclass(frozen=True)
class MatchSpec:
    path: Path
    region: Tuple[Tuple[int, int], Tuple[int, int]]
    threshold: float = MATCH_THRESHOLD


@dataclass(frozen=True)
class RecoveryResult:
    success: bool
    blocked: bool
    reason: str
    screenshot: Optional[str] = None


SPECS = {
    # 目标状态与主界面。
    "login": MatchSpec(
        HELPER_DIR / "Sign_A_Switch" / "sign.png",
        ((360, 390), (920, 500)),
    ),
    "main": MatchSpec(
        DAILY_DIR / "CoopReward" / "explore.png",
        ((500, 80), (800, 280)),
    ),
    "courtyard_back": MatchSpec(
        ASSET_DIR / "courtyard_back.png",
        ((60, 0), (180, 100)),
        0.88,
    ),

    # 战斗、准备房间和结算状态。
    "battle": MatchSpec(
        DAILY_DIR / "Exp" / "battle.png",
        ((0, 0), (360, 100)),
    ),
    "prepare_button": MatchSpec(
        DAILY_DIR / "Exp" / "prepare.png",
        ((1050, 490), (1280, 690)),
    ),
    "ready_room": MatchSpec(ASSET_DIR / "ready_room.png", ((0, 0), (360, 100))),
    "room_exit_confirm": MatchSpec(
        DAILY_DIR / "Exp" / "exit_confirm.png",
        ((600, 350), (920, 520)),
        0.90,
    ),
    "heart_exit_confirm": MatchSpec(
        DAILY_DIR / "HeartTeam" / "confirm.png",
        ((600, 350), (900, 520)),
        0.90,
    ),
    "settlement": MatchSpec(
        DAILY_DIR / "Exp" / "win.png",
        ((250, 0), (950, 210)),
    ),
    "coop_settlement": MatchSpec(
        DAILY_DIR / "CoopReward" / "win.png",
        ((350, 300), (850, 680)),
        0.90,
    ),
    "coop_soul_entry": MatchSpec(
        DAILY_DIR / "CoopReward" / "soul_entry.png",
        ((0, 570), (180, 720)),
        0.90,
    ),
    "coop_dungeon_card": MatchSpec(
        DAILY_DIR / "CoopReward" / "dungeon_card.png",
        ((0, 60), (380, 650)),
        0.90,
    ),
    "coop_challenge": MatchSpec(
        DAILY_DIR / "CoopReward" / "challenge.png",
        ((1080, 480), (1280, 720)),
        0.90,
    ),

    # 登录流程的中间页面。
    "settings_center": MatchSpec(
        HELPER_DIR / "Sign_A_Switch" / "center.png",
        ((170, 380), (330, 530)),
    ),
    "switch_account": MatchSpec(
        HELPER_DIR / "Sign_A_Switch" / "swithch_account.png",
        ((880, 130), (1130, 290)),
    ),
    "account_list": MatchSpec(
        HELPER_DIR / "Sign_A_Switch" / "count_flag.png",
        # 登录页本身也有一个账号图标，只搜索第一行以下的列表区域。
        ((379, 380), (470, 604)),
        0.82,
    ),
    "ios": MatchSpec(
        HELPER_DIR / "Sign_A_Switch" / "IOS.png",
        ((480, 320), (640, 470)),
    ),
    "android": MatchSpec(
        HELPER_DIR / "Sign_A_Switch" / "Android.png",
        ((640, 320), (800, 470)),
    ),

    # 已知任务页面与弹窗。
    "sign_in_close": MatchSpec(
        DAILY_DIR / "One-tap_daily" / "sign_in_close.png",
        ((760, 40), (980, 190)),
    ),
    "reward_success": MatchSpec(
        ASSET_DIR / "reward_success.png",
        ((240, 0), (600, 120)),
    ),
    "friend_close": MatchSpec(
        DAILY_DIR / "Like" / "back.png",
        ((1100, 50), (1240, 180)),
    ),
    "bounty_close": MatchSpec(
        DAILY_DIR / "Bounty" / "back.png",
        ((1050, 60), (1250, 210)),
    ),
    "exp_back": MatchSpec(
        DAILY_DIR / "Exp" / "back.png",
        ((0, 0), (120, 100)),
    ),
    "daily_back": MatchSpec(
        DAILY_DIR / "One-tap_daily" / "back.png",
        ((0, 0), (120, 100)),
    ),
    "merchant_popular": MatchSpec(
        DAILY_DIR / "Merchant" / "popular_marker.png",
        ((100, 0), (360, 100)),
        0.88,
    ),
    "merchant_town": MatchSpec(
        DAILY_DIR / "Merchant" / "merchant_entry.png",
        ((0, 360), (180, 620)),
        0.88,
    ),
    "merchant_page": MatchSpec(
        DAILY_DIR / "Merchant" / "refresh.png",
        ((1120, 450), (1280, 700)),
        0.88,
    ),
}

SAFE_ROOM_STATES = (
    ("prepare_button", "准备界面"),
    ("ready_room", "准备倒计时房间"),
)

ROOM_EXIT_CONFIRM_STATES = (
    ("room_exit_confirm", "退出房间确认"),
    ("heart_exit_confirm", "退出组队确认"),
)

CLICK_ACTIONS = (
    # 一键返回庭院与普通返回键同时出现时，优先使用这个确定性更高的按钮。
    ("courtyard_back", "一键返回庭院按钮"),
    ("sign_in_close", "签到弹窗关闭按钮"),
    ("switch_account", "切换账号"),
    ("settings_center", "用户中心"),
    ("friend_close", "好友页关闭按钮"),
    ("bounty_close", "悬赏页关闭按钮"),
    ("exp_back", "组队页返回按钮"),
    ("daily_back", "一键日常返回按钮"),
)


def _match(frame, name: str) -> Tuple[Optional[float], Optional[Rect]]:
    spec = SPECS[name]
    score, rect = utils.crop_and_match(
        spec.region[0],
        spec.region[1],
        str(spec.path),
        frame=frame,
    )
    if score is None or rect is None or score < spec.threshold:
        return score, None
    LOGGER.match(
        name,
        spec.path.stem,
        score,
        spec.threshold,
        rect,
        search_region=(
            spec.region[0][0],
            spec.region[0][1],
            spec.region[1][0],
            spec.region[1][1],
        ),
    )
    return score, rect


def _click_rect(rect: Rect, label: str) -> None:
    left, top, right, bottom = rect
    margin_x = max(1, (right - left) // 4)
    margin_y = max(1, (bottom - top) // 4)
    x = random.randint(left + margin_x, right - margin_x)
    y = random.randint(top + margin_y, bottom - margin_y)
    LOGGER.click(label, label, rect, (x, y))
    utils.adb_click(x, y)


def _click_and_confirm(name: str, label: str, rect: Rect) -> bool:
    spec = SPECS[name]
    return utils.click_template_until_disappears(
        spec.region[0],
        spec.region[1],
        str(spec.path),
        rect,
        threshold=spec.threshold,
        timeout=ACTION_CONFIRM_SECONDS,
        label=f"启动恢复-{label}",
        click_callback=lambda current_rect: _click_rect(current_rect, label),
        log_callback=lambda message: LOGGER.message(label, message),
    )


def _click_reward_blank_and_confirm(rect: Rect) -> bool:
    click_index = 0

    def click_next_blank(_current_rect: Rect) -> None:
        nonlocal click_index
        region = REWARD_OUTSIDE_RIGHT_REGIONS[
            click_index % len(REWARD_OUTSIDE_RIGHT_REGIONS)
        ]
        click_index += 1
        _click_rect(region, f"领取成功弹窗右侧外部空白区域 {click_index}")

    print(f"等待 {REWARD_READY_DELAY_SECONDS:g} 秒，让奖励界面完成动画")
    time.sleep(REWARD_READY_DELAY_SECONDS)
    spec = SPECS["reward_success"]
    return utils.click_template_until_disappears(
        spec.region[0],
        spec.region[1],
        str(spec.path),
        rect,
        threshold=spec.threshold,
        timeout=REWARD_CONFIRM_SECONDS,
        label="启动恢复-领取成功弹窗",
        click_callback=click_next_blank,
        still_visible_delay=REWARD_RETRY_DELAY_SECONDS,
        log_callback=lambda message: LOGGER.message("领取奖励", message),
    )


def _save_screenshot(stage: str, frame=None) -> Optional[str]:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    milliseconds = int((time.time() % 1) * 1000)
    timestamp = time.strftime("%Y%m%d_%H%M%S") + f"_{milliseconds:03d}"
    path = SCREENSHOT_DIR / f"{stage}_{timestamp}.png"
    saved = utils.save_screenshot(str(path), frame=frame)
    return str(saved) if saved is not None else None


def _blocked(reason: str, frame=None, stage: str = "blocked") -> RecoveryResult:
    screenshot = _save_screenshot(stage, frame)
    detail = f"；现场截图：{screenshot}" if screenshot else ""
    message = f"启动恢复已停止：{reason}，请人工处理{detail}"
    print(f"[ERROR] {message}")
    return RecoveryResult(False, True, message, screenshot)


def _wait_for_known_frame(
    recovery_deadline: float,
) -> Tuple[Optional[object], Optional[object]]:
    """加载画面最多容错 5 秒；出现任一已知模板后交回主循环处理。"""
    grace_deadline = min(
        recovery_deadline,
        time.monotonic() + UNKNOWN_STATE_GRACE_SECONDS,
    )
    last_frame = None
    print(
        f"当前界面暂时无法识别，等待最多 "
        f"{UNKNOWN_STATE_GRACE_SECONDS:g} 秒让界面完成加载"
    )
    while time.monotonic() < grace_deadline:
        time.sleep(SCREENSHOT_INTERVAL)
        frame = utils.take_screenshot()
        if frame is None:
            continue
        last_frame = frame
        for state_name in SPECS:
            score, rect = _match(frame, state_name)
            if rect is not None:
                print(
                    f"加载等待期间识别到 {state_name}，"
                    f"匹配分数 {score:.3f}，继续恢复"
                )
                return frame, last_frame
    return None, last_frame


def recover_to_login(
    exit_to_login: Callable[[], bool],
    collect_battle_rewards: Optional[Callable[[object], bool]] = None,
    collect_coop_battle_rewards: Optional[Callable[[object], bool]] = None,
) -> RecoveryResult:
    """识别当前页面并安全退回登录页；战斗或未知页面立即阻塞。"""
    utils.connect_to_mumu()
    deadline = time.monotonic() + RECOVERY_TIMEOUT_SECONDS
    steps = 0
    last_frame = None
    pending_frame = None
    print("开始启动界面检测，目标为账号登录页")

    while time.monotonic() < deadline and steps < MAX_RECOVERY_STEPS:
        frame = pending_frame
        pending_frame = None
        if frame is None:
            frame = utils.take_screenshot()
        if frame is None:
            time.sleep(SCREENSHOT_INTERVAL)
            continue
        last_frame = frame

        settlement_score, settlement_rect = _match(frame, "settlement")
        if settlement_rect is not None:
            print(
                f"检测到战斗奖励界面，匹配分数 {settlement_score:.3f}，"
                "按正常安全区域流程领取"
            )
            steps += 1
            if collect_battle_rewards is None or not collect_battle_rewards(frame):
                return _blocked(
                    "战斗奖励领取失败",
                    frame,
                    "settlement_collect_failed",
                )
            continue

        coop_score, coop_rect = _match(frame, "coop_settlement")
        if coop_rect is not None:
            print(
                f"检测到协战奖励界面，匹配分数 {coop_score:.3f}，"
                "按协战安全区域流程领取"
            )
            steps += 1
            if (
                collect_coop_battle_rewards is None
                or not collect_coop_battle_rewards(frame)
            ):
                return _blocked(
                    "协战奖励领取失败",
                    frame,
                    "coop_settlement_collect_failed",
                )
            continue

        battle_score, battle_rect = _match(frame, "battle")
        if battle_rect is not None:
            return _blocked(
                f"检测到战斗界面（匹配分数 {battle_score:.3f}）",
                frame,
                "blocked_battle",
            )

        # 准备房左上角返回后，确认弹窗会覆盖在原页面上，背景里的返回
        # 按钮仍能高分匹配。必须先处理确认，不能继续点击背景返回按钮。
        exit_confirmation = None
        for state_name, label in ROOM_EXIT_CONFIRM_STATES:
            score, rect = _match(frame, state_name)
            if rect is not None:
                exit_confirmation = (state_name, label, score, rect)
                break
        if exit_confirmation is not None:
            state_name, label, score, rect = exit_confirmation
            print(f"检测到{label}，匹配分数 {score:.3f}，执行确认")
            steps += 1
            if not _click_and_confirm(state_name, label, rect):
                return _blocked(
                    f"未能完成{label}",
                    frame,
                    "room_exit_confirm_failed",
                )
            continue

        room_state = None
        for state_name, label in SAFE_ROOM_STATES:
            score, rect = _match(frame, state_name)
            if rect is not None:
                room_state = (label, score)
                break
        if room_state is not None:
            label, score = room_state
            back_score, back_rect = _match(frame, "exp_back")
            if back_rect is None:
                return _blocked(
                    f"检测到{label}但未找到返回按钮",
                    frame,
                    "room_back_missing",
                )
            print(
                f"检测到{label}，匹配分数 {score:.3f}，"
                f"点击一次返回并等待退出确认（返回按钮 {back_score:.3f}）"
            )
            steps += 1
            _click_rect(back_rect, f"{label}返回按钮")
            time.sleep(SCREENSHOT_INTERVAL)
            continue

        score, rect = _match(frame, "login")
        if rect is not None:
            print(f"启动恢复完成：已在账号登录页，匹配分数 {score:.3f}")
            return RecoveryResult(True, False, "已到达账号登录页")

        score, rect = _match(frame, "main")
        if rect is not None:
            print(f"检测到主界面，匹配分数 {score:.3f}，准备退出当前账号")
            steps += 1
            if not exit_to_login():
                return _blocked("从主界面退出到登录页失败", frame, "exit_to_login_failed")
            continue

        # 账号列表、系统选择页及已知任务页面使用返回键安全逐层退出。
        intermediate = None
        for state_name, label in (
            ("account_list", "账号列表"),
            ("ios", "系统选择页"),
            ("android", "系统选择页"),
            ("coop_challenge", "御魂十层页面"),
            ("coop_dungeon_card", "御魂副本选择页"),
            ("coop_soul_entry", "探索地图"),
            ("merchant_page", "神秘商店页面"),
            ("merchant_town", "商店街页面"),
            ("merchant_popular", "商店热门推荐页"),
        ):
            score, rect = _match(frame, state_name)
            if rect is not None:
                intermediate = (label, score)
                break
        if intermediate is not None:
            label, score = intermediate
            print(f"检测到{label}，匹配分数 {score:.3f}，发送返回键")
            steps += 1
            if not utils.adb_back():
                return _blocked(f"{label}返回失败", frame, "back_failed")
            time.sleep(SCREENSHOT_INTERVAL)
            continue

        reward_score, reward_rect = _match(frame, "reward_success")
        if reward_rect is not None:
            print(f"检测到领取成功弹窗，匹配分数 {reward_score:.3f}")
            steps += 1
            if not _click_reward_blank_and_confirm(reward_rect):
                return _blocked(
                    "领取成功弹窗未能关闭",
                    frame,
                    "reward_popup_failed",
                )
            continue

        action_taken = False
        for state_name, label in CLICK_ACTIONS:
            score, rect = _match(frame, state_name)
            if rect is None:
                continue
            print(f"检测到{label}，匹配分数 {score:.3f}")
            steps += 1
            if not _click_and_confirm(state_name, label, rect):
                return _blocked(f"点击{label}后界面未变化", frame, "click_failed")
            action_taken = True
            break
        if action_taken:
            continue

        # 点击返回庭院后常有数秒纯加载画面。等待期间只识别、不点击；
        # 连续 5 秒仍没有任何已知模板才视为真正的未知界面。
        known_frame, grace_last_frame = _wait_for_known_frame(deadline)
        if known_frame is not None:
            pending_frame = known_frame
            last_frame = known_frame
            continue
        if grace_last_frame is not None:
            last_frame = grace_last_frame
        return _blocked(
            f"等待 {UNKNOWN_STATE_GRACE_SECONDS:g} 秒后仍无法安全识别当前界面",
            last_frame,
            "blocked_unknown",
        )

    return _blocked(
        f"超过恢复限制（{MAX_RECOVERY_STEPS} 步/{RECOVERY_TIMEOUT_SECONDS:.0f} 秒）",
        last_frame,
        "recovery_timeout",
    )


if __name__ == "__main__":
    from Daily.Exp.Exp_Monster import collect_battle_rewards
    from Sign_A_Switch.Switch import exit_to_login

    result = recover_to_login(exit_to_login, collect_battle_rewards)
    raise SystemExit(0 if result.success else 1)

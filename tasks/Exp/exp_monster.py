"""阴阳师日常任务：加入经验妖怪队伍并进入战斗。

界面和模板均以 1280x720 分辨率制作。截图由 ``TaskDevice`` 提供，
并统一限制为每 0.5 秒一帧。
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

import cv2


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from module import automation as utils
from module.base.device import TaskDevice
from module.menu import try_open_activity_menu_once
from module.logging import TaskLogger


from tasks.Exp.assets import ExpMonsterAssets

ASSETS = ExpMonsterAssets
TEMPLATES = ASSETS.TEMPLATES
REGIONS = ASSETS.REGIONS
FINISH_BLANK_AREAS = ASSETS.FINISH_BLANK_AREAS
MATCH_THRESHOLD = ASSETS.MATCH_THRESHOLD
BACK_MIN_BRIGHTNESS_RATIO = ASSETS.BACK_MIN_BRIGHTNESS_RATIO
MAX_DUNGEON_LIST_SWIPES = ASSETS.MAX_DUNGEON_LIST_SWIPES
DUNGEON_LIST_SWIPE_X_RANGE = ASSETS.DUNGEON_LIST_SWIPE_X_RANGE
DUNGEON_LIST_SWIPE_START_Y_RANGE = ASSETS.DUNGEON_LIST_SWIPE_START_Y_RANGE
DUNGEON_LIST_SWIPE_END_Y_RANGE = ASSETS.DUNGEON_LIST_SWIPE_END_Y_RANGE
DUNGEON_LIST_SWIPE_DURATION_RANGE = ASSETS.DUNGEON_LIST_SWIPE_DURATION_RANGE
DUNGEON_LIST_SWIPE_INTERVAL = ASSETS.DUNGEON_LIST_SWIPE_INTERVAL

LOGGER = TaskLogger("经验妖怪")
DEVICE = TaskDevice(utils, LOGGER)
print = LOGGER.legacy_print


# TaskDevice.screenshot() 会根据这个配置自动限速。
SCREENSHOT_INTERVAL = 0.5
utils.config["screenshot_speed"] = SCREENSHOT_INTERVAL


# 识别范围来自项目中的 1280x720 样图，后续如 UI 发生变化只需修改这里。

# 结算界面左右两块空白点击区，坐标格式为 (左, 上, 右, 下)。
# 如不同分辨率下位置有变化，只需要修改这里。

MAIN_WAIT_SECONDS = 20.0
MENU_WAIT_SECONDS = 12.0
TEAM_WAIT_SECONDS = 20.0
PREPARE_CLICK_DELAY = 1.0
PREPARE_CONFIRM_SECONDS = 12.0
HOST_START_WAIT_SECONDS = 20.0
EXIT_CONFIRM_WAIT_SECONDS = 12.0
ROOM_RETURN_WAIT_SECONDS = 20.0
JOIN_CLICK_MIN_ATTEMPTS = 3
JOIN_CLICK_MAX_ATTEMPTS = 5
JOIN_RESULT_WAIT_SECONDS = 15.0
REFRESH_CLICK_INTERVAL = 1.0
MAX_TEAM_REFRESHES = 20
BATTLE_SCREENSHOT_INTERVAL = 2.0
BATTLE_WAIT_SECONDS = 200.0
DEFEAT_RETURN_WAIT_SECONDS = 30.0
BACK_WAIT_SECONDS = 10.0
PHONE_BIND_RECOVERY_SECONDS = 15.0

Rect = Tuple[int, int, int, int]


def _match(frame, name: str) -> Tuple[Optional[float], Optional[Rect]]:
    """在指定区域匹配模板，低于阈值时按未找到处理。"""
    top_left, bottom_right = REGIONS[name]
    score, rect = DEVICE.match(
        top_left,
        bottom_right,
        TEMPLATES[name],
        frame=frame,
    )
    if score is None or rect is None or score < MATCH_THRESHOLD:
        return score, None
    LOGGER.match(
        name,
        name,
        score,
        MATCH_THRESHOLD,
        rect,
        search_region=(top_left[0], top_left[1], bottom_right[0], bottom_right[1]),
    )
    return score, rect


def _back_is_active(frame, rect: Rect) -> bool:
    """灰暗返回按钮仍可能高分匹配，使用亮度确认它当前可点击。"""
    left, top, right, bottom = rect
    current = frame[top:bottom, left:right]
    template = cv2.imread(TEMPLATES["back"])
    if current.size == 0 or template is None:
        return False
    current_v = float(cv2.cvtColor(current, cv2.COLOR_BGR2HSV)[:, :, 2].mean())
    template_v = float(cv2.cvtColor(template, cv2.COLOR_BGR2HSV)[:, :, 2].mean())
    active = current_v >= template_v * BACK_MIN_BRIGHTNESS_RATIO
    if not active:
        print(
            "左上角退出按钮背景灰暗，暂不点击："
            f"亮度 {current_v:.1f}/{template_v:.1f}"
        )
    return active


def _click_rect(rect: Rect, label: str) -> None:
    """点击匹配框中央附近，避免每次都落在完全相同的像素。"""
    left, top, right, bottom = rect
    margin_x = max(1, (right - left) // 4)
    margin_y = max(1, (bottom - top) // 4)
    x = random.randint(left + margin_x, right - margin_x)
    y = random.randint(top + margin_y, bottom - margin_y)
    LOGGER.click(label, label, rect, (x, y))
    DEVICE.click(x, y)


def _click_and_confirm(name: str, label: str, rect: Rect, timeout: float) -> bool:
    top_left, bottom_right = REGIONS[name]
    return DEVICE.click_until_disappears(
        top_left,
        bottom_right,
        TEMPLATES[name],
        rect,
        threshold=MATCH_THRESHOLD,
        timeout=timeout,
        label=label,
        click_callback=lambda current_rect: _click_rect(current_rect, label),
        log_callback=lambda message: LOGGER.message(label, message),
    )


def _take_frame():
    frame = DEVICE.screenshot()
    if frame is None:
        print("[WARN] 截图失败，等待下一帧")
        time.sleep(SCREENSHOT_INTERVAL)
    return frame


def _score_text(score: Optional[float]) -> str:
    return "无" if score is None else f"{score:.3f}"


def _wait_and_click(
    name: str,
    label: str,
    timeout: float,
    delay_before_click: float = 0.0,
) -> bool:
    """等待模板出现，点击并确认它在后续截图中消失。"""
    deadline = time.monotonic() + timeout
    last_frame = None
    best_score: Optional[float] = None
    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame

        score, rect = _match(frame, name)
        if score is not None and (best_score is None or score > best_score):
            best_score = score
        if rect is not None:
            print(f"识别到{label}，匹配分数 {score:.3f}")
            if delay_before_click > 0:
                print(f"等待 {delay_before_click:g} 秒后点击{label}")
                time.sleep(delay_before_click)
            if _click_and_confirm(name, label, rect, timeout):
                return True
            return False

    print(
        f"[ERROR] {timeout:.0f} 秒内未识别到{label}，"
        f"最高匹配分数 {_score_text(best_score)}，要求 {MATCH_THRESHOLD:.2f}"
    )
    return False


def _ensure_team_menu_expanded() -> bool:
    """确认庭院后寻找组队；不可见时依次尝试卷轴和兜底坐标。"""
    deadline = time.monotonic() + MENU_WAIT_SECONDS
    last_frame = None
    best_main_score: Optional[float] = None
    best_team_score: Optional[float] = None
    best_scroll_score: Optional[float] = None
    fallback_clicked = False

    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame

        main_score, main_rect = _match(frame, "main")
        if main_score is not None and (
            best_main_score is None or main_score > best_main_score
        ):
            best_main_score = main_score
        if main_rect is None:
            continue

        team_score, team_rect = _match(frame, "team")
        if team_score is not None and (
            best_team_score is None or team_score > best_team_score
        ):
            best_team_score = team_score
        if team_rect is not None:
            print(f"组队入口已显示，功能栏无需展开，匹配分数 {team_score:.3f}")
            return True

        scroll_score, scroll_rect = _match(frame, "menu_scroll")
        if scroll_score is not None and (
            best_scroll_score is None or scroll_score > best_scroll_score
        ):
            best_scroll_score = scroll_score
        if scroll_rect is not None:
            print(f"识别到右下角卷轴，功能栏处于折叠状态，匹配分数 {scroll_score:.3f}")
            remaining = max(0.1, deadline - time.monotonic())
            if _click_and_confirm("menu_scroll", "展开功能栏卷轴", scroll_rect, remaining):
                print("右侧功能栏已展开")
                return True
            return False

        if not fallback_clicked and try_open_activity_menu_once(frame, LOGGER):
            fallback_clicked = True
            print("未识别到普通卷轴，已在庭院点击一次活动菜单共有区域")
            time.sleep(SCREENSHOT_INTERVAL)
            continue

    print(
        "[ERROR] 未在庭院找到组队入口、右下角卷轴或活动菜单，"
        f"探索灯笼最高分 {_score_text(best_main_score)}，"
        f"组队最高分 {_score_text(best_team_score)}，"
        f"卷轴最高分 {_score_text(best_scroll_score)}"
    )
    return False


def _select_exp_monster_if_needed() -> bool:
    """确认当前为经验妖怪页，必要时向下浏览左侧副本栏。

    组队界面会继承同心队最后选择的觉醒副本。此时经验妖怪入口位于
    左侧列表更下方，需要用向上的手势把下方分类滚入可见区域。
    """
    deadline = time.monotonic() + TEAM_WAIT_SECONDS
    last_frame = None
    best_flag_score: Optional[float] = None
    best_select_score: Optional[float] = None
    swipe_count = 0
    last_swipe_time = float("-inf")
    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame

        flag_score, flag_rect = _match(frame, "flag")
        if flag_score is not None and (
            best_flag_score is None or flag_score > best_flag_score
        ):
            best_flag_score = flag_score
        if flag_rect is not None:
            print(f"当前已是经验妖怪页，匹配分数 {flag_score:.3f}")
            return True

        select_score, select_rect = _match(frame, "select")
        if select_score is not None and (
            best_select_score is None or select_score > best_select_score
        ):
            best_select_score = select_score
        if select_rect is not None:
            print(f"切换到经验妖怪页，匹配分数 {select_score:.3f}")
            _click_rect(select_rect, "经验妖怪分类")
            # 下一帧仍先检查 flag；若 select 仍在就再点，直到切换生效。
            continue

        now = time.monotonic()
        if (
            swipe_count < MAX_DUNGEON_LIST_SWIPES
            and now - last_swipe_time >= DUNGEON_LIST_SWIPE_INTERVAL
        ):
            swipe_count += 1
            x = random.randint(*DUNGEON_LIST_SWIPE_X_RANGE)
            start_y = random.randint(*DUNGEON_LIST_SWIPE_START_Y_RANGE)
            end_y = random.randint(*DUNGEON_LIST_SWIPE_END_Y_RANGE)
            duration_ms = random.randint(*DUNGEON_LIST_SWIPE_DURATION_RANGE)
            print(
                "左侧副本栏向下浏览，"
                f"第 {swipe_count}/{MAX_DUNGEON_LIST_SWIPES} 次滑动 "
                f"({x}, {start_y}) -> ({x}, {end_y})，"
                f"耗时 {duration_ms}ms"
            )
            DEVICE.swipe(x, start_y, x, end_y, duration_ms)
            last_swipe_time = time.monotonic()

    print(
        "[ERROR] 无法进入经验妖怪组队页，"
        f"flag 最高分 {_score_text(best_flag_score)}，"
        f"select 最高分 {_score_text(best_select_score)}，"
        f"已滑动 {swipe_count} 次"
    )
    return False


def _wait_for_join_button(refresh_count: int) -> Tuple[Optional[Rect], int]:
    """寻找可加入队伍，整个加入流程最多刷新十次。"""
    deadline = time.monotonic() + TEAM_WAIT_SECONDS
    last_refresh_time = float("-inf")
    last_frame = None
    best_flag_score: Optional[float] = None
    best_join_score: Optional[float] = None
    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame

        # 必须先确认 flag：它表示当前仍停留在经验妖怪组队页。
        flag_score, flag_rect = _match(frame, "flag")
        if flag_score is not None and (
            best_flag_score is None or flag_score > best_flag_score
        ):
            best_flag_score = flag_score
        if flag_rect is None:
            continue

        score, join_rect = _match(frame, "join")
        if score is not None and (best_join_score is None or score > best_join_score):
            best_join_score = score
        if join_rect is not None:
            print(f"识别到经验妖怪队伍的加入按钮，匹配分数 {score:.3f}")
            return join_rect, refresh_count

        refresh_score, refresh_rect = _match(frame, "refresh")
        now = time.monotonic()
        if (
            refresh_rect is not None
            and now - last_refresh_time >= REFRESH_CLICK_INTERVAL
        ):
            if refresh_count >= MAX_TEAM_REFRESHES:
                print(f"[ERROR] 已刷新 {MAX_TEAM_REFRESHES} 次，仍未找到可加入队伍")
                return None, refresh_count
            refresh_count += 1
            print(
                f"当前没有加入按钮，第 {refresh_count}/{MAX_TEAM_REFRESHES} 次刷新，"
                f"匹配分数 {refresh_score:.3f}"
            )
            _click_rect(refresh_rect, "刷新")
            last_refresh_time = now

    print(
        "[ERROR] 未找到可加入的经验妖怪队伍，"
        f"flag 最高分 {_score_text(best_flag_score)}，"
        f"join 最高分 {_score_text(best_join_score)}"
    )
    return None, refresh_count


def _wait_for_join_outcome() -> Tuple[str, Optional[Rect]]:
    """将一次加入点击归类为进入房间、刷新重找、重试或异常。"""
    deadline = time.monotonic() + JOIN_RESULT_WAIT_SECONDS
    last_frame = None
    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame

        prepare_score, prepare_rect = _match(frame, "prepare")
        if prepare_rect is not None:
            print(f"确认已进入准备界面，匹配分数 {prepare_score:.3f}")
            return "joined", prepare_rect

        flag_score, flag_rect = _match(frame, "flag")
        if flag_rect is None:
            # 加入和 flag 同时消失后，不要求准备按钮立刻出现。先用正常
            # 亮度的左上角退出按钮确认已经进入组队房间，再单独等待房主。
            back_score, back_rect = _match(frame, "back")
            if back_rect is not None and _back_is_active(frame, back_rect):
                print(
                    "确认已进入经验妖怪组队房间，等待房主开启挑战，"
                    f"返回按钮匹配分数 {back_score:.3f}"
                )
                return "room", back_rect
            continue

        join_score, join_rect = _match(frame, "join")
        if join_rect is not None:
            print(
                "仍在经验妖怪列表且加入按钮还在，"
                f"匹配分数 {join_score:.3f}"
            )
            return "retry", join_rect

        # 加入消失但 flag 仍在：仍停留在列表，目标队伍已开战或失效。
        refresh_score, refresh_rect = _match(frame, "refresh")
        if refresh_rect is not None:
            print(
                "加入按钮已消失但仍在经验妖怪界面，需要刷新重新寻找"
                f"（flag {flag_score:.3f}，刷新 {refresh_score:.3f}）"
            )
            return "refresh", refresh_rect

    print("[ERROR] 点击加入后未能确认准备界面，也未确认仍在经验妖怪列表")
    return "error", None


def _click_prepare_rect(prepare_rect: Rect) -> bool:
    print(f"等待 {PREPARE_CLICK_DELAY:g} 秒后点击准备")
    time.sleep(PREPARE_CLICK_DELAY)
    if not _click_and_confirm(
        "prepare",
        "准备",
        prepare_rect,
        PREPARE_CONFIRM_SECONDS,
    ):
        return False
    print("已点击准备，进入经验妖怪战斗")
    return True


def _leave_waiting_room(initial_frame=None) -> bool:
    """只点一次正常返回按钮，再匹配并点击退出确认，最后确认回到列表。"""
    frame = initial_frame if initial_frame is not None else _take_frame()
    if frame is None:
        return False

    back_score, back_rect = _match(frame, "back")
    if back_rect is None or not _back_is_active(frame, back_rect):
        print("[ERROR] 等待房主超时，但未找到可点击的正常退出按钮")
        return False

    print(f"点击一次左上角退出，匹配分数 {back_score:.3f}")
    _click_rect(back_rect, "退出房间")
    time.sleep(SCREENSHOT_INTERVAL)

    confirm_deadline = time.monotonic() + EXIT_CONFIRM_WAIT_SECONDS
    last_frame = frame
    while time.monotonic() < confirm_deadline:
        current = _take_frame()
        if current is None:
            continue
        last_frame = current
        confirm_score, confirm_rect = _match(current, "exit_confirm")
        if confirm_rect is None:
            # 弹窗出现后左上角按钮会变灰，即使仍高分匹配也不能再点。
            _, gray_back_rect = _match(current, "back")
            if gray_back_rect is not None:
                _back_is_active(current, gray_back_rect)
            continue
        print(f"识别到退出组队确认按钮，匹配分数 {confirm_score:.3f}")
        remaining = max(0.1, confirm_deadline - time.monotonic())
        if not _click_and_confirm(
            "exit_confirm",
            "退出组队确定",
            confirm_rect,
            remaining,
        ):
            return False
        break
    else:
        print("[ERROR] 点击左上角退出后未识别到退出确认按钮")
        return False

    return_deadline = time.monotonic() + ROOM_RETURN_WAIT_SECONDS
    while time.monotonic() < return_deadline:
        current = _take_frame()
        if current is None:
            continue
        flag_score, flag_rect = _match(current, "flag")
        if flag_rect is not None:
            print(f"退出房间成功，已回到经验妖怪列表，flag {flag_score:.3f}")
            return True

    print("[ERROR] 点击退出确认后未回到经验妖怪列表")
    return False


def _wait_for_host_and_prepare() -> str:
    """进入房间后等待房主二十秒；未开战则确认退出。"""
    deadline = time.monotonic() + HOST_START_WAIT_SECONDS
    last_frame = None
    print(f"已进入组队房间，等待房主开启挑战，最长 {HOST_START_WAIT_SECONDS:.0f} 秒")

    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame

        prepare_score, prepare_rect = _match(frame, "prepare")
        if prepare_rect is not None:
            print(f"房主已开启挑战，识别到准备，匹配分数 {prepare_score:.3f}")
            return "prepared" if _click_prepare_rect(prepare_rect) else "error"

        battle_score, battle_rect = _match(frame, "battle")
        if battle_rect is not None:
            print(f"已直接进入战斗，匹配分数 {battle_score:.3f}")
            return "prepared"

    print(f"房主 {HOST_START_WAIT_SECONDS:.0f} 秒内未开启挑战，自动退出当前房间")
    return "left" if _leave_waiting_room(last_frame) else "error"


def _refresh_after_room_exit(refresh_count: int) -> Optional[int]:
    """退出未开战房间后刷新列表，避免再次加入同一个失效房间。"""
    if refresh_count >= MAX_TEAM_REFRESHES:
        print(f"[ERROR] 已达到 {MAX_TEAM_REFRESHES} 次刷新上限")
        return None

    deadline = time.monotonic() + TEAM_WAIT_SECONDS
    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        _, flag_rect = _match(frame, "flag")
        if flag_rect is None:
            continue
        refresh_score, refresh_rect = _match(frame, "refresh")
        if refresh_rect is None:
            continue
        refresh_count += 1
        print(
            f"第 {refresh_count}/{MAX_TEAM_REFRESHES} 次刷新："
            f"房主未开战，改找其他队伍（匹配分数 {refresh_score:.3f}）"
        )
        _click_rect(refresh_rect, "刷新")
        time.sleep(REFRESH_CLICK_INTERVAL)
        return refresh_count

    print("[ERROR] 退出未开战房间后未找到刷新按钮")
    return None


def _join_team() -> Optional[bool]:
    """按三种明确结果加入队伍，并以准备按钮作为成功依据。"""
    refresh_count = 0
    while True:
        join_rect, refresh_count = _wait_for_join_button(refresh_count)
        if join_rect is None:
            return False

        join_attempts = random.randint(
            JOIN_CLICK_MIN_ATTEMPTS,
            JOIN_CLICK_MAX_ATTEMPTS,
        )
        print(f"本次队伍最多随机尝试点击加入 {join_attempts} 次")
        for attempt in range(1, join_attempts + 1):
            print(f"第 {attempt}/{join_attempts} 次点击加入")
            _click_rect(join_rect, "加入")
            time.sleep(1.0)

            outcome, outcome_rect = _wait_for_join_outcome()
            if outcome == "joined":
                if outcome_rect is None:
                    return False
                return _click_prepare_rect(outcome_rect)
            if outcome == "room":
                room_result = _wait_for_host_and_prepare()
                if room_result == "prepared":
                    return True
                if room_result == "error":
                    return False
                refreshed = _refresh_after_room_exit(refresh_count)
                if refreshed is None:
                    return False
                refresh_count = refreshed
                break
            if outcome == "refresh":
                if outcome_rect is None:
                    return False
                if refresh_count >= MAX_TEAM_REFRESHES:
                    print(
                        f"[ERROR] 已刷新 {MAX_TEAM_REFRESHES} 次，"
                        "本次进入失败后不再继续刷新"
                    )
                    return False
                refresh_count += 1
                print(
                    f"第 {refresh_count}/{MAX_TEAM_REFRESHES} 次刷新："
                    "加入按钮消失但没有进入房间"
                )
                _click_rect(outcome_rect, "刷新")
                time.sleep(REFRESH_CLICK_INTERVAL)
                break
            if outcome == "error":
                return False

            join_rect = outcome_rect
            if join_rect is None:
                return False

            if attempt == join_attempts:
                print(
                    f"连续点击加入 {join_attempts} 次后加入按钮仍存在，"
                    "今日两次机会已用完"
                )
                print("准备退出组队页并返回主界面")
                if _wait_and_click("back", "返回", BACK_WAIT_SECONDS):
                    print("已点击返回，任务结束")
                else:
                    print("[ERROR] 未能点击返回按钮")
                    return False
                # None 表示今日两次机会已经用完，不是执行故障。
                return None

            print("加入按钮仍存在，继续点击加入")


def _click_random_finish_side() -> None:
    """每次随机选择结算界面左侧或右侧的一块空白区域点击。"""
    side, (left, top, right, bottom) = random.choice(
        tuple(FINISH_BLANK_AREAS.items())
    )
    x = random.randint(left, right)
    y = random.randint(top, bottom)
    LOGGER.click("战斗结算", f"{side}空白区域", (left, top, right, bottom), (x, y))
    DEVICE.click(x, y)


def collect_battle_rewards(
    initial_frame=None,
    timeout: Optional[float] = None,
) -> bool:
    """识别胜利奖励并点击安全区域，直到 win 模板消失。"""
    previous_interval = utils.config.get("screenshot_speed", SCREENSHOT_INTERVAL)
    utils.config["screenshot_speed"] = BATTLE_SCREENSHOT_INTERVAL
    win_seen = False
    frame = initial_frame
    deadline = None if timeout is None else time.monotonic() + max(0.1, timeout)
    print(f"每 {BATTLE_SCREENSHOT_INTERVAL:g} 秒检查一次胜利奖励，并点击结算安全区域")

    try:
        while deadline is None or time.monotonic() < deadline:
            if frame is None:
                frame = _take_frame()
            if frame is None:
                continue

            score, win_rect = _match(frame, "win")
            if win_rect is not None:
                if not win_seen:
                    print(f"识别到战斗胜利界面，匹配分数 {score:.3f}")
                    win_seen = True
                _click_random_finish_side()
                frame = None
                continue

            # 战斗过程中 win 本来就不存在；只有曾经识别成功后再消失，
            # 才表示结算界面已经点击完成。
            if win_seen:
                print("win 模板已消失，战斗结算完成")
                return True
            frame = None
        print("[ERROR] 领取战斗奖励超时")
        return False
    finally:
        utils.config["screenshot_speed"] = previous_interval


def _dismiss_defeat_and_refresh(initial_frame=None) -> bool:
    """退出失败结算；回庭院后重新进入经验妖怪列表并刷新一次。"""
    # 战斗已经结束，恢复日常界面的 0.5 秒截图频率再处理返回链。
    utils.config["screenshot_speed"] = SCREENSHOT_INTERVAL
    print("识别到经验妖怪战斗失败，点击一侧空白区域退出结算")
    _click_random_finish_side()
    deadline = time.monotonic() + DEFEAT_RETURN_WAIT_SECONDS
    frame = None

    while time.monotonic() < deadline:
        if frame is None:
            frame = _take_frame()
        if frame is None:
            continue

        defeat_score, defeat_rect = _match(frame, "defeat")
        if defeat_rect is not None:
            print(
                "失败结算点击后仍可见，"
                f"匹配分数 {defeat_score:.3f}，重新点击任意一侧空白区域"
            )
            _click_random_finish_side()
            frame = None
            continue

        flag_score, flag_rect = _match(frame, "flag")
        refresh_score, refresh_rect = _match(frame, "refresh")
        if flag_rect is not None and refresh_rect is not None:
            print(
                "失败结算已关闭，回到经验妖怪列表并刷新："
                f"flag {flag_score:.3f}，刷新 {refresh_score:.3f}"
            )
            _click_rect(refresh_rect, "刷新")
            time.sleep(REFRESH_CLICK_INTERVAL)
            return True

        main_score, main_rect = _match(frame, "main")
        if main_rect is not None:
            print(
                "失败结算已关闭，识别到庭院探索灯笼，"
                f"匹配分数 {main_score:.3f}；重新进入组队"
            )
            if not _ensure_team_menu_expanded():
                return False
            if not _wait_and_click("team", "组队", MAIN_WAIT_SECONDS):
                return False
            if not _select_exp_monster_if_needed():
                return False
            return _refresh_after_defeat_reentry()

        frame = None

    print("[ERROR] 关闭失败结算后未识别到庭院或经验妖怪列表")
    return False


def _refresh_after_defeat_reentry() -> bool:
    """失败后重新进入经验妖怪页，主动刷新一次再继续寻找队伍。"""
    deadline = time.monotonic() + TEAM_WAIT_SECONDS
    last_frame = None
    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame
        flag_score, flag_rect = _match(frame, "flag")
        refresh_score, refresh_rect = _match(frame, "refresh")
        if flag_rect is None or refresh_rect is None:
            continue
        print(
            "失败后已重新进入经验妖怪列表，执行一次刷新："
            f"flag {flag_score:.3f}，刷新 {refresh_score:.3f}"
        )
        _click_rect(refresh_rect, "刷新")
        time.sleep(REFRESH_CLICK_INTERVAL)
        return True

    print("[ERROR] 失败后重新进入经验妖怪页但未找到刷新按钮")
    return False


def _wait_for_battle_finish() -> str:
    """等待战斗结算，返回 won、lost 或 error。"""
    previous_interval = utils.config.get("screenshot_speed", SCREENSHOT_INTERVAL)
    utils.config["screenshot_speed"] = BATTLE_SCREENSHOT_INTERVAL
    deadline = time.monotonic() + BATTLE_WAIT_SECONDS
    print(
        f"战斗进行中，每 {BATTLE_SCREENSHOT_INTERVAL:g} 秒检查一次胜利或失败结算，"
        f"最长等待 {BATTLE_WAIT_SECONDS:g} 秒"
    )

    try:
        while time.monotonic() < deadline:
            frame = _take_frame()
            if frame is None:
                continue

            win_score, win_rect = _match(frame, "win")
            if win_rect is not None:
                print(f"识别到战斗胜利界面，匹配分数 {win_score:.3f}")
                remaining = max(0.1, deadline - time.monotonic())
                return (
                    "won"
                    if collect_battle_rewards(
                        initial_frame=frame,
                        timeout=remaining,
                    )
                    else "error"
                )

            defeat_score, defeat_rect = _match(frame, "defeat")
            if defeat_rect is not None:
                print(f"识别到战斗失败界面，匹配分数 {defeat_score:.3f}")
                return "lost" if _dismiss_defeat_and_refresh(frame) else "error"
        print(
            f"[ERROR] 战斗等待超过 {BATTLE_WAIT_SECONDS:g} 秒，"
            "仍未识别到胜利或失败结算"
        )
        return "error"
    finally:
        utils.config["screenshot_speed"] = previous_interval


def _recover_phone_binding(initial_frame=None) -> bool:
    """庭院确认超时后，兜底关闭偶发的手机绑定引导。"""
    deadline = time.monotonic() + PHONE_BIND_RECOVERY_SECONDS
    frame = initial_frame
    binding_seen = False

    while time.monotonic() < deadline:
        if frame is None:
            frame = _take_frame()
        if frame is None:
            continue
        cancel_score, cancel_rect = _match(frame, "phone_bind_cancel")
        if cancel_rect is not None:
            binding_seen = True
            print(
                "检测到手机绑定窗口，点击取消，"
                f"匹配分数 {cancel_score:.3f}"
            )
            _click_rect(cancel_rect, "取消手机绑定")
            time.sleep(1.0)
            frame = None
            continue

        bind_score, bind_rect = _match(frame, "phone_bind")
        if bind_rect is not None:
            binding_seen = True
            print(
                "检测到关联手机奖励界面，点击前往绑定，"
                f"匹配分数 {bind_score:.3f}"
            )
            _click_rect(bind_rect, "前往绑定")
            time.sleep(1.0)
            frame = None
            continue

        if not binding_seen:
            return False

        main_score, main_rect = _match(frame, "main")
        if main_rect is not None:
            print(f"关闭手机绑定窗口后已返回庭院，匹配分数 {main_score:.3f}")
            return True
        frame = None

    if binding_seen:
        print("[ERROR] 已处理手机绑定引导，但未能重新确认庭院界面")
    return False


def _return_to_main(timeout: float = MAIN_WAIT_SECONDS) -> bool:
    """战斗结算后离开组队界面，以探索灯笼确认已回到庭院。"""
    deadline = time.monotonic() + timeout
    last_frame = None

    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame

        main_score, main_rect = _match(frame, "main")
        if main_rect is not None:
            print(f"已返回庭院，探索灯笼匹配分数 {main_score:.3f}")
            return True

        back_score, back_rect = _match(frame, "back")
        if back_rect is not None:
            print(f"结算后仍在组队界面，点击返回，匹配分数 {back_score:.3f}")
            _click_rect(back_rect, "返回")
            time.sleep(1.0)

    print("常规庭院确认超时，检查是否出现手机绑定引导")
    if _recover_phone_binding(last_frame):
        return True

    print("[ERROR] 经验妖怪结束后未能识别到庭院探索灯笼")
    return False


def run() -> bool:
    """执行一次经验妖怪任务，完成战斗结算时返回 True。"""
    utils.connect_to_mumu()

    print("开始经验妖怪任务，截图间隔 0.5 秒")
    if not _ensure_team_menu_expanded():
        return False
    if not _wait_and_click("team", "组队", MAIN_WAIT_SECONDS):
        return False
    if not _select_exp_monster_if_needed():
        return False
    failed_battles = 0
    while True:
        join_result = _join_team()
        if join_result is None:
            if failed_battles:
                print("[ERROR] 战斗失败后已无法继续加入队伍，本次任务不写完成时间")
                return False
            print("今日经验妖怪次数已用完，按任务已完成处理")
            return True
        if not join_result:
            return False

        battle_result = _wait_for_battle_finish()
        if battle_result == "error":
            return False
        if battle_result == "lost":
            failed_battles += 1
            print(f"经验妖怪第 {failed_battles} 场战斗失败，已刷新并重新寻找队伍")
            continue
        return _return_to_main()


if __name__ == "__main__":
    try:
        success = run()
    except KeyboardInterrupt:
        print("任务已由用户中止")
        success = False

    raise SystemExit(0 if success else 1)

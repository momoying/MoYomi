"""确认锁阵与觉醒加成后刷票，50/50 时关闭加成并返回副本页。"""

from __future__ import annotations

from functools import lru_cache
import random
import re
import time
import unicodedata

import cv2

from module import automation as utils
from module.base.device import TaskDevice
from module.logging import TaskLogger
from module.ocr import OCR_LOCK, create_ocr
from module.task_execution import TaskCancelled, check_stopped, report_failure
from tasks.SuperOni.assets import SuperOniAssets as ASSETS


LOGGER = TaskLogger("超鬼王刷票")
DEVICE = TaskDevice(utils, LOGGER)
SCREENSHOT_INTERVAL = .5
BATTLE_SCREENSHOT_INTERVAL = 2.0
BATTLE_TIMEOUT = 300.0
PAGE_TIMEOUT = 30.0
OCR_RETRY_LIMIT = 10
OCR_RETRY_INTERVAL = 2.0
TARGET_TICKETS = 50


@lru_cache(maxsize=1)
def local_ocr():
    with OCR_LOCK:
        return create_ocr(cpu_acceleration=True)


def parse_ticket_count(result):
    """仅接受高置信度、分母为 50 且范围有效的完整计数。"""
    values = set()
    for page in result or []:
        for item in page or []:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                continue
            text, confidence = item
            if not isinstance(text, str) or not isinstance(confidence, (int, float)) or not .85 <= confidence <= 1:
                continue
            text = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).replace("⁄", "/").replace("∕", "/")
            matched = re.fullmatch(r"(\d{1,2})/50", text)
            if matched and 0 <= int(matched[1]) <= TARGET_TICKETS:
                values.add(int(matched[1]))
    return values.pop() if len(values) == 1 else None


def read_tickets(frame, engine):
    left, top, right, bottom = ASSETS.TICKET_REGION
    crop = frame[top:bottom, left:right]
    enlarged = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    with OCR_LOCK:
        return parse_ticket_count(engine.ocr(enlarged, cls=False, det=False))


def _matches(frame, asset):
    score, rect = DEVICE.match_asset(asset, frame=frame)
    return rect if score is not None and rect is not None and score >= asset.threshold else None


def _wait(seconds, stop_event):
    if stop_event is None:
        time.sleep(seconds)
    elif stop_event.wait(seconds):
        raise TaskCancelled()
    check_stopped()


def _awakening_challenge(frame):
    if (_matches(frame, ASSETS.I_AWAKENING_BONUS) is not None
            or _matches(frame, ASSETS.I_AWAKENING) is None
            or _matches(frame, ASSETS.I_FLOOR_ONE) is None):
        return None
    return _matches(frame, ASSETS.I_CHALLENGE)


def _click(rect, stop_event):
    if stop_event is not None and stop_event.is_set():
        raise TaskCancelled()
    if DEVICE.click(*DEVICE.random_point(rect)) is False:
        raise OSError("游戏界面点击失败")


def _formation_state(frame):
    matches = []
    for state, asset in (("locked", ASSETS.I_FORMATION_LOCKED), ("unlocked", ASSETS.I_FORMATION_UNLOCKED)):
        score, rect = DEVICE.match_asset(asset, frame=frame)
        if score is not None and rect is not None and score >= asset.threshold:
            matches.append((score, state, rect))
    matches.sort(reverse=True)
    if matches and (len(matches) == 1 or matches[0][0] - matches[1][0] >= .04):
        return matches[0][1:]
    return None, None


def _ensure_locked(frame, stop_event):
    deadline = time.monotonic() + PAGE_TIMEOUT
    clicks = 0
    while time.monotonic() < deadline:
        if frame is not None and frame.shape[:2] == (720, 1280) and _awakening_challenge(frame) is not None:
            state, rect = _formation_state(frame)
            if state == "locked":
                return frame
            if state == "unlocked":
                if clicks >= 3:
                    return None
                _click(rect, stop_event)
                clicks += 1
        _wait(SCREENSHOT_INTERVAL, stop_event)
        frame = DEVICE.screenshot()
    return None


def _bonus_time_rect(row):
    _, top, right, bottom = row
    return right + 18, top + 3, right + 132, bottom


def _bonus_state(frame, row):
    """沿用现有加成识别的 HSV 颜色范围，红黄均不明确时不切换。"""
    left, top, right, bottom = _bonus_time_rect(row)
    if left < 0 or top < 0 or right > frame.shape[1] or bottom > frame.shape[0] or bottom <= top:
        return None
    hsv = cv2.cvtColor(frame[top:bottom, left:right], cv2.COLOR_BGR2HSV)
    hue, saturation, value = cv2.split(hsv)
    yellow = float(((hue >= 12) & (hue <= 40) & (saturation >= 80) & (value >= 100)).mean())
    red = float((((hue <= 8) | (hue >= 170)) & (saturation >= 80) & (value >= 80)).mean())
    if yellow >= .25 and yellow - red >= .1:
        return True
    if red >= .25 and red - yellow >= .1:
        return False
    return None


def _set_bonus(frame, enabled, stop_event, progress):
    """识别觉醒行后切换计时条，确认颜色，再退出并确认返回觉醒页。"""
    progress("开启觉醒加成" if enabled else "关闭觉醒加成")
    deadline = time.monotonic() + PAGE_TIMEOUT
    opens = toggles = dismisses = 0
    confirmed = False
    while time.monotonic() < deadline:
        delay = SCREENSHOT_INTERVAL
        if frame is not None and frame.shape[:2] == (720, 1280):
            row = _matches(frame, ASSETS.I_AWAKENING_BONUS)
            if row is not None:
                state = _bonus_state(frame, row)
                if state is enabled:
                    confirmed = True
                    if dismisses >= 3:
                        return None
                    _click(random.choice((ASSETS.C_BONUS_LEFT, ASSETS.C_BONUS_RIGHT)).area, stop_event)
                    dismisses += 1
                elif state is not None:
                    confirmed = False
                    if toggles >= 3:
                        return None
                    _click(_bonus_time_rect(row), stop_event)
                    toggles += 1
                    delay = 1.0
            elif _awakening_challenge(frame) is not None:
                if confirmed:
                    return frame
                lantern = _matches(frame, ASSETS.I_BONUS_LANTERN)
                if lantern is not None:
                    if opens >= 3:
                        return None
                    _click(lantern, stop_event)
                    opens += 1
        _wait(delay, stop_event)
        frame = DEVICE.screenshot()
    return None


def _prepare(frame, stop_event, progress):
    # 从已经打开的加成面板启动时，先确认加成并退出，避免点击面板后面的锁。
    panel_open = _matches(frame, ASSETS.I_AWAKENING_BONUS) is not None
    if panel_open:
        frame = _set_bonus(frame, True, stop_event, progress)
        if frame is None:
            return None
    progress("检查阵容上锁")
    frame = _ensure_locked(frame, stop_event)
    if frame is None:
        return None
    progress("阵容已上锁")
    return frame if panel_open else _set_bonus(frame, True, stop_event, progress)


def _advance(frame, marker, click_count, areas, stop_event):
    """快速连点，每次点击后检查页面；宝箱出现即停，先 OCR 再关闭。"""
    utils.config["screenshot_speed"] = 0
    for _ in range(random.randint(*click_count)):
        if frame is None or _matches(frame, marker) is None:
            break
        if stop_event is not None and stop_event.is_set():
            raise TaskCancelled()
        area = random.choice(areas)
        point = DEVICE.random_point(area.area)
        if DEVICE.click(*point) is False:
            raise OSError("结算页面点击失败")
        _wait(random.uniform(.1, .2), stop_event)
        frame = DEVICE.screenshot()
    return frame


def run(stop_event=None, progress_callback=None):
    """从觉醒一层、胜利页或奖励页启动；刷满后确认返回觉醒一层。"""
    if stop_event is not None and stop_event.is_set():
        return True
    current_tickets = None
    attempts = 0

    def progress(stage):
        LOGGER.set_stage(stage)
        if progress_callback is not None:
            progress_callback({"stage": stage, "tickets": current_tickets, "attempts": attempts})

    def fail(reason, frame=None):
        progress("已停止：" + reason)
        report_failure(reason, frame=frame)
        LOGGER.error("运行", reason)
        return False

    progress("初始化 OCR")
    engine = local_ocr()
    check_stopped()
    if stop_event is not None and stop_event.is_set():
        return True
    if not utils.connect_to_mumu():
        return fail("无法连接 MuMu ADB，请检查模拟器设置")
    phase = "entry"
    deadline = time.monotonic() + PAGE_TIMEOUT
    candidate = None
    candidate_hits = ocr_retries = victory_batches = dismiss_batches = 0
    pending_frame = None
    prepared = False
    previous_interval = utils.config.get("screenshot_speed", .5)
    progress("等待觉醒一层")
    try:
        while stop_event is None or not stop_event.is_set():
            if time.monotonic() >= deadline:
                return fail({"entry": "请停留在觉醒一层界面后启动", "battle": "战斗超时，或未能进入战斗",
                             "reward": "未能确认奖励页票数", "return": "未能返回觉醒一层"}[phase])
            utils.config["screenshot_speed"] = BATTLE_SCREENSHOT_INTERVAL if phase == "battle" else SCREENSHOT_INTERVAL
            frame = pending_frame if pending_frame is not None else DEVICE.screenshot()
            pending_frame = None
            if frame is None:
                _wait(SCREENSHOT_INTERVAL, stop_event)
                continue
            if frame.shape[:2] != (720, 1280):
                return fail("请将游戏分辨率设置为 1280×720", frame)
            if _matches(frame, ASSETS.I_FAILED) is not None:
                return fail("觉醒挑战失败", frame)

            if _matches(frame, ASSETS.I_REWARD) is not None:
                if phase != "return":
                    if phase != "reward":
                        phase = "reward"
                        deadline = time.monotonic() + PAGE_TIMEOUT
                    count = read_tickets(frame, engine)
                    invalid = (count is None or current_tickets is not None and count < current_tickets
                               or candidate is not None and count != candidate)
                    if invalid:
                        candidate = None
                        candidate_hits = 0
                        progress("票数未确认，正在重新识别")
                        if ocr_retries >= OCR_RETRY_LIMIT:
                            return fail("票数 OCR 重试 10 次仍无法确认，已保留奖励页", frame)
                        ocr_retries += 1
                        _wait(OCR_RETRY_INTERVAL, stop_event)
                        deadline = time.monotonic() + PAGE_TIMEOUT
                    else:
                        candidate_hits = candidate_hits + 1 if count == candidate else 1
                        candidate = count
                        if candidate_hits >= 2:
                            current_tickets = count
                        progress("确认票数" if candidate_hits < 2 else "返回觉醒一层")
                    if candidate_hits < 2:
                        continue
                    LOGGER.info("奖励", f"超鬼王票数 {current_tickets}/50")
                    phase = "return"
                    deadline = time.monotonic() + PAGE_TIMEOUT
                if dismiss_batches >= 3:
                    return fail("奖励页点击后仍未关闭", frame)
                dismiss_batches += 1
                pending_frame = _advance(frame, ASSETS.I_REWARD, (1, 2),
                                         (ASSETS.C_REWARD_LEFT, ASSETS.C_REWARD_RIGHT), stop_event)
                continue

            if _matches(frame, ASSETS.I_VICTORY) is not None and phase != "return":
                if phase != "reward":
                    phase = "reward"
                    deadline = time.monotonic() + PAGE_TIMEOUT
                if victory_batches >= 3:
                    return fail("胜利页点击后仍未出现奖励页", frame)
                victory_batches += 1
                progress("胜利，打开宝箱奖励")
                pending_frame = _advance(frame, ASSETS.I_VICTORY, (2, 3), (ASSETS.C_VICTORY_BLANK,), stop_event)
                continue

            challenge = _awakening_challenge(frame)
            if (phase == "entry" and not prepared
                    and (challenge is not None or _matches(frame, ASSETS.I_AWAKENING_BONUS) is not None)):
                pending_frame = _prepare(frame, stop_event, progress)
                if pending_frame is None:
                    return fail("无法确认阵容上锁或觉醒加成开启，未开始挑战")
                prepared = True
                deadline = time.monotonic() + PAGE_TIMEOUT
                continue
            if challenge is None:
                continue
            if phase == "return":
                if current_tickets == TARGET_TICKETS:
                    if _set_bonus(frame, False, stop_event, progress) is None:
                        return fail("已刷满 50/50，但未能确认觉醒加成关闭并返回觉醒一层")
                    progress("已刷满，已关闭觉醒加成，已返回觉醒一层")
                    LOGGER.info("完成", "超鬼王票数 50/50，已关闭觉醒加成并返回觉醒一层")
                    return True
                phase = "entry"
                if not prepared:
                    pending_frame = frame
                    deadline = time.monotonic() + PAGE_TIMEOUT
                    continue
            if phase == "reward":
                return fail("奖励页票数尚未确认，已停止继续挑战", frame)
            if phase == "battle":
                continue  # 挑战点击后等待实际切页，不能在同一按钮上重复消耗体力。
            progress("发起觉醒一层挑战")
            if stop_event is not None and stop_event.is_set():
                break
            if DEVICE.click(*DEVICE.random_point(challenge)) is False:
                return fail("挑战按钮点击失败", frame)
            attempts += 1
            candidate = None
            candidate_hits = ocr_retries = victory_batches = dismiss_batches = 0
            phase = "battle"
            deadline = time.monotonic() + BATTLE_TIMEOUT
            progress("战斗中")
        return True
    finally:
        utils.config["screenshot_speed"] = previous_interval

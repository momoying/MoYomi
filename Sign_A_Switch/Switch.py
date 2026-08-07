"""阴阳师账号切换：退出当前账号，识别并选择下一个白名单账号。"""

from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Tuple

import cv2
import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Core import automation as utils
from Core.logging import TaskLogger


LOGGER = TaskLogger("账号切换")
print = LOGGER.legacy_print


SCREENSHOT_INTERVAL = 0.5
utils.config["screenshot_speed"] = SCREENSHOT_INTERVAL

ERROR_SCREENSHOT_DIR = SCRIPT_DIR / "error_screenshots"
ACCOUNT_STATUS_PATH = SCRIPT_DIR.parent / "config" / "account_status.json"

TEMPLATES = {
    "center": str(SCRIPT_DIR / "center.png"),
    "switch_account": str(SCRIPT_DIR / "swithch_account.png"),
    "count_flag": str(SCRIPT_DIR / "count_flag.png"),
}

# 左上角人物头像不能使用模板识别，只在脸部中央的小范围内随机点击，
# 避免落到头像边缘、等级标记或旁边的 UI。
AVATAR_CLICK_REGION = (42, 42, 68, 72)

# 以下识别范围均按 1280x720 截图设置。
REGIONS = {
    "center": ((170, 380), (330, 530)),
    "switch_account": ((880, 130), (1130, 290)),
}
LOGIN_ACCOUNT_REGION = (379, 276, 901, 382)
LOGIN_BUTTON_REGION = (379, 410, 901, 480)
ACCOUNT_LIST_REGION = (379, 276, 901, 604)
COUNT_FLAG_SEARCH_REGION = (379, 276, 470, 604)
# 黄色“常用”标签从 x≈830 开始，只截取其左侧的邮箱文字。
ACCOUNT_TEXT_RIGHT = 820

MATCH_THRESHOLD = 0.80
COUNT_FLAG_THRESHOLD = 0.82
OCR_MIN_CONFIDENCE = 0.60
OCR_SCALE = 3
ACCOUNT_ROW_HEIGHT = 110
PAGE_WAIT_SECONDS = 20.0
MAIN_READY_WAIT_SECONDS = 60.0
LOGIN_TRANSITION_WAIT_SECONDS = 2.0
ACCOUNT_LIST_OPEN_ATTEMPTS = 6
ACCOUNT_LIST_OPEN_WAIT_SECONDS = 0.8
ACCOUNT_LIST_MAX_SWIPES = 12
ACCOUNT_LIST_SCROLL_WAIT_SECONDS = 1.0
ACCOUNT_LIST_SWIPE_DURATION_MS = 1200
AVATAR_RETRY_INTERVAL_SECONDS = 2.0

Rect = Tuple[int, int, int, int]


@dataclass(frozen=True)
class AccountEntry:
    """一次 OCR 识别出的账号及其可点击白框。"""

    name: str
    raw_name: str
    confidence: float
    click_rect: Rect
    flag_rect: Rect


@dataclass(frozen=True)
class AccountScanResult:
    reason: str
    entry: Optional[AccountEntry]
    seen_accounts: Tuple[str, ...]


_ocr_engine = None


def _get_ocr_engine():
    """按需加载本地 PaddleOCR 模型，避免仅导入模块时初始化模型。"""
    global _ocr_engine
    if _ocr_engine is not None:
        return _ocr_engine

    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    from paddleocr import PaddleOCR

    model_dir = PROJECT_ROOT / "modle"
    _ocr_engine = PaddleOCR(
        det_model_dir=str(model_dir / "ch_PP-OCRv4_det_infer"),
        rec_model_dir=str(model_dir / "ch_PP-OCRv4_rec_infer"),
        cls_model_dir=str(model_dir / "ch_ppocr_mobile_v2.0_cls_infer"),
        lang="ch",
        show_log=False,
        use_gpu=False,
    )
    return _ocr_engine


def _match(frame, name: str) -> Tuple[Optional[float], Optional[Rect]]:
    top_left, bottom_right = REGIONS[name]
    score, rect = utils.crop_and_match(
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


def _score_text(score: Optional[float]) -> str:
    return "无" if score is None else f"{score:.3f}"


def _click_region(rect: Rect, label: str, use_inner_margin: bool = True) -> None:
    left, top, right, bottom = rect
    if use_inner_margin:
        margin_x = max(1, (right - left) // 4)
        margin_y = max(1, (bottom - top) // 4)
    else:
        margin_x = 0
        margin_y = 0

    x = random.randint(left + margin_x, right - margin_x)
    y = random.randint(top + margin_y, bottom - margin_y)
    LOGGER.click(label, label, rect, (x, y))
    utils.adb_click(x, y)


def _click_and_confirm(name: str, label: str, rect: Rect, timeout: float) -> bool:
    top_left, bottom_right = REGIONS[name]
    return utils.click_template_until_disappears(
        top_left,
        bottom_right,
        TEMPLATES[name],
        rect,
        threshold=MATCH_THRESHOLD,
        timeout=timeout,
        label=label,
        click_callback=lambda current_rect: _click_region(current_rect, label),
        log_callback=lambda message: LOGGER.message(label, message),
    )


def _take_frame():
    frame = utils.take_screenshot()
    if frame is None:
        print("[WARN] 截图失败，等待下一帧")
        time.sleep(SCREENSHOT_INTERVAL)
    return frame


def _timestamp() -> str:
    milliseconds = int((time.time() % 1) * 1000)
    return time.strftime("%Y%m%d_%H%M%S") + f"_{milliseconds:03d}"


def _save_timeout_screenshot(stage: str, frame=None) -> Optional[Path]:
    ERROR_SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = ERROR_SCREENSHOT_DIR / f"timeout_{stage}_{_timestamp()}.png"
    saved_path = utils.save_screenshot(str(output_path), frame=frame)
    if saved_path is None:
        print(f"[ERROR] 超时截图保存失败: {output_path}")
        return None
    print(f"超时截图已保存: {output_path}")
    return output_path


def _wait_and_click(name: str, label: str, timeout: float) -> bool:
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
            if _click_and_confirm(name, label, rect, timeout):
                return True
            _save_timeout_screenshot(f"confirm_{name}")
            return False

    print(
        f"[ERROR] {timeout:.0f} 秒内未识别到{label}，"
        f"最高匹配分数 {_score_text(best_score)}，要求 {MATCH_THRESHOLD:.2f}"
    )
    _save_timeout_screenshot(f"wait_{name}", last_frame)
    return False


def _normalize_account(text: str) -> str:
    """清理 OCR 噪声，优先提取邮箱，并修正常见的 c0m 误识别。"""
    normalized = re.sub(r"\s+", "", text).strip().lower()
    normalized = normalized.translate(str.maketrans({"＠": "@", "。": ".", "，": "."}))
    email_match = re.search(
        r"[a-z0-9][a-z0-9._%+\-]*@[a-z0-9.\-]+\.[a-z0-9]{2,}",
        normalized,
        flags=re.IGNORECASE,
    )
    if email_match is not None:
        # “常用”可能被识别成“吊用/调用”；邮箱提取会自然丢弃这些中文尾缀。
        normalized = email_match.group(0)
    normalized = re.sub(r"\.c0m$", ".com", normalized, flags=re.IGNORECASE)
    return normalized


def _load_account_allowlist() -> dict[str, str]:
    """返回“标准化账号 -> JSON 中原始账号名”的白名单映射。"""
    try:
        with ACCOUNT_STATUS_PATH.open("r", encoding="utf-8") as file:
            data = json.load(file)
        accounts = data.get("accounts", {})
        if not isinstance(accounts, dict) or not accounts:
            raise ValueError("accounts 必须是非空对象")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[ERROR] 账号状态文件不可用: {ACCOUNT_STATUS_PATH} ({exc})")
        return {}

    return {_normalize_account(name): name for name in accounts}


def _rect_iou(first: Rect, second: Rect) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0, right - left) * max(0, bottom - top)
    if intersection == 0:
        return 0.0
    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    return intersection / float(first_area + second_area - intersection)


def _find_count_flags(frame) -> list[Rect]:
    """模板匹配所有 count_flag，并用 NMS 合并同一图标的重复命中。"""
    x1, y1, x2, y2 = COUNT_FLAG_SEARCH_REGION
    crop = frame[y1:y2, x1:x2]
    template = cv2.imread(TEMPLATES["count_flag"])
    if crop.size == 0 or template is None:
        return []

    template_height, template_width = template.shape[:2]
    if template_height > crop.shape[0] or template_width > crop.shape[1]:
        return []

    scores = cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED)
    candidate_y, candidate_x = np.where(scores >= COUNT_FLAG_THRESHOLD)
    candidates = []
    for local_x, local_y in zip(candidate_x, candidate_y):
        rect = (
            x1 + int(local_x),
            y1 + int(local_y),
            x1 + int(local_x) + template_width,
            y1 + int(local_y) + template_height,
        )
        candidates.append((float(scores[local_y, local_x]), rect))

    selected: list[Rect] = []
    for _, rect in sorted(candidates, key=lambda item: item[0], reverse=True):
        if all(_rect_iou(rect, kept) < 0.30 for kept in selected):
            selected.append(rect)

    selected = sorted(selected, key=lambda rect: (rect[1], rect[0]))
    for rect in selected:
        local_x = rect[0] - x1
        local_y = rect[1] - y1
        LOGGER.match(
            "账号列表",
            "count_flag",
            float(scores[local_y, local_x]),
            COUNT_FLAG_THRESHOLD,
            rect,
            search_region=COUNT_FLAG_SEARCH_REGION,
        )
    return selected


def _ocr_text_band(frame, rect: Rect) -> tuple[str, float]:
    """只 OCR 单个 count_flag 同一水平带右侧的账号名。"""
    flag_left, flag_top, flag_right, _ = rect
    del flag_left
    _, _, list_right, _ = ACCOUNT_LIST_REGION

    image_height, image_width = frame.shape[:2]
    x1 = max(0, flag_right + 12)
    y1 = max(0, flag_top - 12)
    x2 = min(image_width, list_right - 12, ACCOUNT_TEXT_RIGHT)
    y2 = min(image_height, flag_top + 34)
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return "", 0.0

    enlarged = cv2.resize(
        crop,
        None,
        fx=OCR_SCALE,
        fy=OCR_SCALE,
        interpolation=cv2.INTER_CUBIC,
    )
    result = _get_ocr_engine().ocr(enlarged, cls=False)
    if not result or not result[0]:
        return "", 0.0

    pieces = []
    confidences = []
    for line in result[0]:
        try:
            box, (text, confidence) = line
            left = min(point[0] for point in box)
            center_y = sum(point[1] for point in box) / len(box)
            # crop 已限定在 count_flag 的账号名水平带内，再排除贴近底部的说明文字。
            if center_y > enlarged.shape[0] * 0.82:
                continue
            if float(confidence) < OCR_MIN_CONFIDENCE:
                continue
            pieces.append((float(left), str(text)))
            confidences.append(float(confidence))
        except (TypeError, ValueError, IndexError):
            continue

    if not pieces:
        return "", 0.0

    raw_text = "".join(text for _, text in sorted(pieces))
    return raw_text, min(confidences)


def recognize_account_entries(frame) -> tuple[list[AccountEntry], list[Rect]]:
    """识别所有带 count_flag 的账号，并生成整行白框点击范围。"""
    flags = _find_count_flags(frame)
    entries: list[AccountEntry] = []
    list_left, list_top, list_right, list_bottom = ACCOUNT_LIST_REGION

    centers = [(rect[1] + rect[3]) // 2 for rect in flags]
    row_boundaries = [max(list_top, centers[0] - ACCOUNT_ROW_HEIGHT // 2)] if centers else []
    row_boundaries.extend((first + second) // 2 for first, second in zip(centers, centers[1:]))
    if centers:
        row_boundaries.append(min(list_bottom, centers[-1] + ACCOUNT_ROW_HEIGHT // 2))

    for index, flag_rect in enumerate(flags):
        raw_name, confidence = _ocr_text_band(frame, flag_rect)
        if not raw_name:
            continue

        row_top = row_boundaries[index]
        row_bottom = row_boundaries[index + 1]

        click_rect = (list_left, row_top, list_right, row_bottom)
        entries.append(
            AccountEntry(
                name=_normalize_account(raw_name),
                raw_name=raw_name,
                confidence=confidence,
                click_rect=click_rect,
                flag_rect=flag_rect,
            )
        )
        LOGGER.match(
            "账号OCR",
            f"OCR:{raw_name}",
            confidence,
            OCR_MIN_CONFIDENCE,
            click_rect,
            search_region=ACCOUNT_LIST_REGION,
        )

    return entries, flags


def _login_button_visible(frame) -> bool:
    """通过固定区域的红色按钮占比判断“登录”是否仍显示。"""
    x1, y1, x2, y2 = LOGIN_BUTTON_REGION
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return False

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    lower_red = cv2.inRange(hsv, (0, 90, 100), (12, 255, 255))
    upper_red = cv2.inRange(hsv, (168, 90, 100), (180, 255, 255))
    red_ratio = float(np.count_nonzero(lower_red | upper_red)) / float(crop.shape[0] * crop.shape[1])
    visible = red_ratio >= 0.25
    if visible:
        LOGGER.match(
            "登录按钮",
            "颜色:红色登录按钮",
            red_ratio,
            0.25,
            LOGIN_BUTTON_REGION,
            search_region=LOGIN_BUTTON_REGION,
        )
    return visible


def _select_account_row_and_confirm(
    click_rect: Rect,
    label: str,
    timeout: float = PAGE_WAIT_SECONDS,
) -> bool:
    """点击账号行，直到下一帧重新出现登录按钮，证明列表已收起。"""
    deadline = time.monotonic() + timeout
    attempts = 0
    while time.monotonic() < deadline:
        attempts += 1
        _click_region(click_rect, label)
        frame = _take_frame()
        if frame is None:
            continue
        if _login_button_visible(frame):
            print(f"账号列表已收起，选择已生效（共 {attempts} 次）")
            return True
        print("点击后账号列表仍显示，继续点击")
    print(f"[ERROR] {label}点击后账号列表未收起")
    return False


def open_account_list() -> tuple[bool, Optional[AccountEntry], Optional[object]]:
    """识别当前账号，并反复点击登录上方白框直到登录按钮消失。"""
    frame = _take_frame()
    if frame is None:
        return False, None, None

    current_entries, _ = recognize_account_entries(frame)
    current_account = current_entries[0] if current_entries else None
    if current_account is not None:
        print(f"当前账号: {current_account.name}，OCR置信度 {current_account.confidence:.3f}")

    last_frame = frame
    for attempt in range(1, ACCOUNT_LIST_OPEN_ATTEMPTS + 1):
        # 这里绝不能先点 LOGIN_BUTTON_REGION；只点击其上方的白色账号框。
        _click_region(LOGIN_ACCOUNT_REGION, f"登录上方账号白框（第 {attempt} 次）")
        time.sleep(ACCOUNT_LIST_OPEN_WAIT_SECONDS)
        last_frame = _take_frame()
        if last_frame is None:
            continue
        if not _login_button_visible(last_frame):
            print("登录按钮已消失，账号列表打开成功")
            return True, current_account, last_frame
        print("登录按钮仍在，继续点击上方账号白框")

    print(f"[ERROR] 连续 {ACCOUNT_LIST_OPEN_ATTEMPTS} 次点击后登录按钮仍未消失")
    _save_timeout_screenshot("open_account_list", last_frame)
    return False, current_account, last_frame


def scan_account_list(
    known_accounts: Optional[Iterable[str]] = None,
    initial_frame=None,
) -> AccountScanResult:
    """
    缓慢向下浏览账号列表。

    遇到名单外账号、OCR 不完整或首个未见账号立即停止；只有当前页全部账号都已见过时
    才继续滑动。entry.click_rect 是识别出的账号白框范围，可直接用于后续点击。
    """
    allowlist = _load_account_allowlist()
    seen = {_normalize_account(name) for name in (known_accounts or []) if name}
    previous_signature: Optional[tuple[str, ...]] = None
    repeated_pages = 0
    frame = initial_frame

    if not allowlist:
        return AccountScanResult("allowlist_unavailable", None, tuple(sorted(seen)))

    for page_index in range(ACCOUNT_LIST_MAX_SWIPES + 1):
        if frame is None:
            frame = _take_frame()
        if frame is None:
            continue

        entries, flags = recognize_account_entries(frame)
        print("本页识别账号:", [entry.name for entry in entries])
        if not flags:
            return AccountScanResult("account_list_not_found", None, tuple(sorted(seen)))
        if len(entries) != len(flags):
            print(f"[ERROR] 检测到 {len(flags)} 个账号白框，但仅识别出 {len(entries)} 个账号名，停止滑动")
            return AccountScanResult("ocr_incomplete", None, tuple(sorted(seen)))

        for entry in entries:
            if entry.name not in allowlist:
                print(f"[ERROR] 识别到名单外账号: {entry.name}（原始 OCR: {entry.raw_name}）")
                return AccountScanResult("invalid_account", entry, tuple(sorted(seen)))
            if entry.name not in seen:
                print(f"识别到尚未见过的新账号: {allowlist[entry.name]}，停止滑动")
                return AccountScanResult("new_account", entry, tuple(sorted(seen)))

        signature = tuple(entry.name for entry in entries)
        if signature == previous_signature:
            repeated_pages += 1
        else:
            repeated_pages = 0
            previous_signature = signature
        seen.update(signature)

        if repeated_pages >= 2:
            print("账号列表连续三页没有变化，判断已到列表底部")
            return AccountScanResult("end_of_list", None, tuple(sorted(seen)))
        if page_index >= ACCOUNT_LIST_MAX_SWIPES:
            print("[WARN] 已达到账号列表最大滑动次数")
            return AccountScanResult("max_swipes", None, tuple(sorted(seen)))

        # 手指缓慢上划，列表内容向下滚动；起止点始终位于账号列表大框内。
        utils.adb_swipe(840, 548, 840, 338, duration_ms=ACCOUNT_LIST_SWIPE_DURATION_MS)
        time.sleep(ACCOUNT_LIST_SCROLL_WAIT_SECONDS)
        frame = None

    return AccountScanResult("max_swipes", None, tuple(sorted(seen)))


def find_account_in_list(target_account: str, initial_frame=None) -> AccountScanResult:
    """在已打开的账号列表中定向寻找白名单账号。"""
    allowlist = _load_account_allowlist()
    target = _normalize_account(target_account)
    seen: set[str] = set()
    previous_signature: Optional[tuple[str, ...]] = None
    repeated_pages = 0
    frame = initial_frame

    if target not in allowlist:
        print(f"[ERROR] 目标账号不在白名单中: {target_account}")
        return AccountScanResult("target_not_allowed", None, tuple())

    for page_index in range(ACCOUNT_LIST_MAX_SWIPES + 1):
        if frame is None:
            frame = _take_frame()
        if frame is None:
            continue

        entries, flags = recognize_account_entries(frame)
        print("本页识别账号:", [entry.name for entry in entries])
        if not flags:
            return AccountScanResult("account_list_not_found", None, tuple(sorted(seen)))
        if len(entries) != len(flags):
            print(f"[ERROR] 检测到 {len(flags)} 个账号白框，但仅识别出 {len(entries)} 个账号名")
            return AccountScanResult("ocr_incomplete", None, tuple(sorted(seen)))

        for entry in entries:
            if entry.name not in allowlist:
                print(f"[ERROR] 识别到名单外账号: {entry.name}（原始 OCR: {entry.raw_name}）")
                return AccountScanResult("invalid_account", entry, tuple(sorted(seen)))
            if entry.name == target:
                print(f"找到目标账号: {allowlist[target]}")
                return AccountScanResult("target_account", entry, tuple(sorted(seen)))

        signature = tuple(entry.name for entry in entries)
        if signature == previous_signature:
            repeated_pages += 1
        else:
            repeated_pages = 0
            previous_signature = signature
        seen.update(signature)

        if repeated_pages >= 2:
            return AccountScanResult("end_of_list", None, tuple(sorted(seen)))
        if page_index >= ACCOUNT_LIST_MAX_SWIPES:
            return AccountScanResult("max_swipes", None, tuple(sorted(seen)))

        utils.adb_swipe(840, 548, 840, 338, duration_ms=ACCOUNT_LIST_SWIPE_DURATION_MS)
        time.sleep(ACCOUNT_LIST_SCROLL_WAIT_SECONDS)
        frame = None

    return AccountScanResult("max_swipes", None, tuple(sorted(seen)))


def exit_to_login() -> bool:
    """依次打开设置、用户中心并点击切换账号。"""
    utils.connect_to_mumu()
    print("开始退出当前账号，截图间隔 0.5 秒")

    # 双系统第二次登录时可能仍在加载主界面；定时重试头像，直到用户中心真正出现。
    deadline = time.monotonic() + MAIN_READY_WAIT_SECONDS
    next_avatar_click = 0.0
    last_frame = None
    best_score: Optional[float] = None
    center_opened = False
    while time.monotonic() < deadline:
        now = time.monotonic()
        if now >= next_avatar_click:
            _click_region(AVATAR_CLICK_REGION, "左上角人物头像", use_inner_margin=False)
            next_avatar_click = now + AVATAR_RETRY_INTERVAL_SECONDS

        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame
        score, rect = _match(frame, "center")
        if score is not None and (best_score is None or score > best_score):
            best_score = score
        if rect is not None:
            print(f"识别到用户中心，匹配分数 {score:.3f}")
            center_opened = _click_and_confirm(
                "center",
                "用户中心",
                rect,
                PAGE_WAIT_SECONDS,
            )
            break

    if not center_opened:
        print(
            f"[ERROR] {MAIN_READY_WAIT_SECONDS:.0f} 秒内未打开用户中心，"
            f"最高匹配分数 {_score_text(best_score)}"
        )
        _save_timeout_screenshot("wait_center", last_frame)
        return False
    if not _wait_and_click("switch_account", "切换账号", PAGE_WAIT_SECONDS):
        return False

    time.sleep(LOGIN_TRANSITION_WAIT_SECONDS)
    print("已进入登录界面")
    return True


def select_account(target_account: str, exit_current: bool = False) -> Optional[str]:
    """
    在登录页选中指定账号。

    exit_current=False 用于中控首次启动（调用方保证当前已在登录页）；后续切换账号时传 True。
    """
    target = _normalize_account(target_account)
    if exit_current and not exit_to_login():
        return None

    frame = _take_frame()
    if frame is None:
        return None
    current_entries, current_flags = recognize_account_entries(frame)
    if len(current_flags) == 1 and len(current_entries) == 1:
        current = current_entries[0]
        if current.name == target:
            print(f"登录页已选中目标账号 {target_account}，无需打开账号列表")
            return target_account

    opened, _, list_frame = open_account_list()
    if not opened:
        return None
    result = find_account_in_list(target_account, initial_frame=list_frame)
    if result.reason != "target_account" or result.entry is None:
        print(f"定向账号选择失败: {target_account}，原因 {result.reason}")
        return None

    if not _select_account_row_and_confirm(
        result.entry.click_rect,
        f"账号 {result.entry.name}",
    ):
        return None
    print(f"已选中目标账号 {target_account}")
    return target_account


def select_next_account() -> Optional[str]:
    """退出当前账号并选中下一个账号；不执行登录或系统选择。"""
    if not exit_to_login():
        return None

    opened, current_account, list_frame = open_account_list()
    if not opened:
        return None

    known_accounts = [current_account.name] if current_account is not None else []
    result = scan_account_list(known_accounts=known_accounts, initial_frame=list_frame)
    if result.reason != "new_account" or result.entry is None:
        print(f"账号列表扫描停止: {result.reason}")
        return None

    # 点击范围与识别截图中的红框完全一致。登录由 Sign.py 独立负责。
    if not _select_account_row_and_confirm(
        result.entry.click_rect,
        f"账号 {result.entry.name}",
    ):
        return None
    print(f"已选择账号 {result.entry.name}")
    return result.entry.name


def run() -> bool:
    return select_next_account() is not None


if __name__ == "__main__":
    try:
        success = run()
    except KeyboardInterrupt:
        print("任务已由用户中止")
        success = False

    raise SystemExit(0 if success else 1)

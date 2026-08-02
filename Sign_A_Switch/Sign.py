"""登录当前已选账号，并进入指定系统。

本模块不负责账号切换，也不读取账号状态 JSON。首次启动或切换账号后都可以直接调用：

    run("IOS")
    run("Android")
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

import cv2


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Core import game_automation as utils
from Core.task_logging import TaskLogger


LOGGER = TaskLogger("登录")
print = LOGGER.legacy_print


SCREENSHOT_INTERVAL = 0.5
utils.config["screenshot_speed"] = SCREENSHOT_INTERVAL

ERROR_SCREENSHOT_DIR = SCRIPT_DIR / "error_screenshots"

TEMPLATES = {
    "login": str(SCRIPT_DIR / "sign.png"),
    "ios": str(SCRIPT_DIR / "IOS.png"),
    "android": str(SCRIPT_DIR / "Android.png"),
}

# 以下坐标均按 1280x720 截图设置。
REGIONS = {
    "login": ((360, 390), (920, 500)),
    "ios": ((480, 320), (640, 470)),
    "android": ((640, 320), (800, 470)),
}
ENTER_GAME_TEXT_REGION = (500, 540, 780, 640)
# “进入游戏”四个字内部的小范围，识别成功后在这里随机点击。
ENTER_GAME_CLICK_REGION = (555, 570, 725, 625)

MATCH_THRESHOLD = 0.80
OCR_MIN_CONFIDENCE = 0.60
OCR_SCALE = 3
LOGIN_STEP_WAIT_SECONDS = 30.0
LOGIN_ACTION_DELAY_SECONDS = 1.0
ENTER_GAME_RETRY_SECONDS = 3.0
ENTER_GAME_DISAPPEAR_CONFIRM_FRAMES = 2
VALID_SYSTEMS = ("IOS", "Android")

Rect = Tuple[int, int, int, int]

_ocr_engine = None


def normalize_system(system: str) -> Optional[str]:
    aliases = {
        "ios": "IOS",
        "iphone": "IOS",
        "苹果": "IOS",
        "android": "Android",
        "安卓": "Android",
    }
    return aliases.get(str(system).strip().lower())


def _get_ocr_engine():
    """按需加载本地 PaddleOCR 模型。"""
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


def _click_region(rect: Rect, label: str) -> None:
    left, top, right, bottom = rect
    margin_x = max(1, (right - left) // 4)
    margin_y = max(1, (bottom - top) // 4)
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
    output_path = ERROR_SCREENSHOT_DIR / f"timeout_sign_{stage}_{_timestamp()}.png"
    saved_path = utils.save_screenshot(str(output_path), frame=frame)
    if saved_path is None:
        print(f"[ERROR] 登录超时截图保存失败: {output_path}")
        return None
    print(f"登录超时截图已保存: {output_path}")
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


def _wait_and_select_system(system_name: str, timeout: float) -> bool:
    """登录按钮可能短暂消失后重现，因此持续识别到系统选择真正出现。"""
    deadline = time.monotonic() + timeout
    last_frame = None
    best_login_score: Optional[float] = None
    best_system_score: Optional[float] = None
    system_label = "IOS" if system_name == "ios" else "Android"

    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame

        login_score, login_rect = _match(frame, "login")
        if login_score is not None and (
            best_login_score is None or login_score > best_login_score
        ):
            best_login_score = login_score
        if login_rect is not None:
            print(f"识别到登录按钮，匹配分数 {login_score:.3f}")
            _click_region(login_rect, "登录")
            time.sleep(LOGIN_ACTION_DELAY_SECONDS)
            continue

        system_score, system_rect = _match(frame, system_name)
        if system_score is not None and (
            best_system_score is None or system_score > best_system_score
        ):
            best_system_score = system_score
        if system_rect is not None:
            print(f"识别到{system_label}系统，匹配分数 {system_score:.3f}")
            _click_region(system_rect, f"{system_label} 系统")
            time.sleep(LOGIN_ACTION_DELAY_SECONDS)
            return True

    print(
        f"[ERROR] {timeout:.0f} 秒内未进入{system_label}系统选择，"
        f"登录按钮最高分 {_score_text(best_login_score)}，"
        f"系统按钮最高分 {_score_text(best_system_score)}"
    )
    _save_timeout_screenshot(f"wait_{system_name}", last_frame)
    return False


def _ocr_texts_in_region(frame, region: Rect) -> list[tuple[str, float]]:
    x1, y1, x2, y2 = region
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return []

    enlarged = cv2.resize(
        crop,
        None,
        fx=OCR_SCALE,
        fy=OCR_SCALE,
        interpolation=cv2.INTER_CUBIC,
    )
    result = _get_ocr_engine().ocr(enlarged, cls=False)
    if not result or not result[0]:
        return []

    texts = []
    for line in result[0]:
        try:
            _, (text, confidence) = line
            texts.append((str(text), float(confidence)))
        except (TypeError, ValueError, IndexError):
            continue
    return texts


def _wait_and_enter_game(
    system_name: str,
    timeout: float = LOGIN_STEP_WAIT_SECONDS,
) -> bool:
    """优先处理登录弹窗和系统选择，再点击真正可见的“进入游戏”。"""
    deadline = time.monotonic() + timeout
    last_frame = None
    last_texts: list[str] = []
    enter_game_seen = False
    enter_game_absent_frames = 0
    last_enter_game_click = float("-inf")
    system_label = "IOS" if system_name == "ios" else "Android"

    while time.monotonic() < deadline:
        frame = _take_frame()
        if frame is None:
            continue
        last_frame = frame

        # 登录弹窗会遮住真正的“进入游戏”，但 OCR 仍可能识别到背景文字。
        # 所以必须先处理登录按钮，当前帧不再执行“进入游戏”OCR 点击。
        login_score, login_rect = _match(frame, "login")
        if login_rect is not None:
            print(
                f"进入游戏前再次识别到登录按钮，匹配分数 {login_score:.3f}，"
                "重新点击登录"
            )
            _click_region(login_rect, "登录")
            enter_game_seen = False
            enter_game_absent_frames = 0
            time.sleep(LOGIN_ACTION_DELAY_SECONDS)
            continue

        # 如果系统按钮仍在，说明上一次系统选择点击尚未生效。
        system_score, system_rect = _match(frame, system_name)
        if system_rect is not None:
            print(
                f"进入游戏前仍识别到{system_label}系统，"
                f"匹配分数 {system_score:.3f}，重新点击"
            )
            _click_region(system_rect, f"{system_label} 系统")
            enter_game_seen = False
            enter_game_absent_frames = 0
            time.sleep(LOGIN_ACTION_DELAY_SECONDS)
            continue

        recognized = _ocr_texts_in_region(frame, ENTER_GAME_TEXT_REGION)
        last_texts = [text for text, _ in recognized]
        enter_game_visible = any(
            "进入游戏" in text.replace(" ", "")
            for text, confidence in recognized
            if confidence >= OCR_MIN_CONFIDENCE
        )
        if enter_game_visible:
            best_confidence = max(
                confidence
                for text, confidence in recognized
                if "进入游戏" in text.replace(" ", "")
                and confidence >= OCR_MIN_CONFIDENCE
            )
            LOGGER.match(
                "进入游戏",
                "OCR:进入游戏",
                best_confidence,
                OCR_MIN_CONFIDENCE,
                ENTER_GAME_CLICK_REGION,
                search_region=ENTER_GAME_TEXT_REGION,
            )
            enter_game_seen = True
            enter_game_absent_frames = 0
            now = time.monotonic()
            if now - last_enter_game_click >= ENTER_GAME_RETRY_SECONDS:
                print("识别到进入游戏，在文字内部随机点击")
                _click_region(ENTER_GAME_CLICK_REGION, "进入游戏")
                last_enter_game_click = now
                time.sleep(LOGIN_ACTION_DELAY_SECONDS)
            continue
        if enter_game_seen:
            enter_game_absent_frames += 1
            if enter_game_absent_frames >= ENTER_GAME_DISAPPEAR_CONFIRM_FRAMES:
                print("进入游戏文字已连续两帧消失，点击已生效")
                return True

    print(f"[ERROR] {timeout:.0f} 秒内未识别到进入游戏，最后 OCR 结果: {last_texts}")
    _save_timeout_screenshot("wait_enter_game", last_frame)
    return False


def run(system: str = "IOS") -> bool:
    """登录当前界面已选中的账号，仅负责指定的一个系统。"""
    normalized_system = normalize_system(system)
    if normalized_system is None:
        print(f"[ERROR] 不支持的系统 {system!r}，仅支持 {VALID_SYSTEMS}")
        return False

    utils.connect_to_mumu()
    print(f"开始登录当前账号的 {normalized_system} 系统")
    template_name = normalized_system.lower()
    if not _wait_and_select_system(template_name, LOGIN_STEP_WAIT_SECONDS):
        return False
    if not _wait_and_enter_game(template_name, LOGIN_STEP_WAIT_SECONDS):
        return False

    print(f"当前账号的 {normalized_system} 系统已点击进入游戏")
    return True

if __name__ == "__main__":
    try:
        success = run()
    except KeyboardInterrupt:
        print("登录已由用户中止")
        success = False

    raise SystemExit(0 if success else 1)

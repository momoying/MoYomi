"""Daily 自动化任务统一日志格式。"""

from __future__ import annotations

import builtins
import re
import threading
import time
from datetime import datetime
from typing import Optional, Tuple


Rect = Tuple[int, int, int, int]
_PRINT_LOCK = threading.Lock()


class TaskLogger:
    """为任务状态、识图和点击输出提供统一且可实时刷新的格式。"""

    _STAGE_HINTS = (
        ("登录", "登录"),
        ("账号", "账号切换"),
        ("队伍", "寻找队伍"),
        ("加入", "加入队伍"),
        ("刷新", "刷新列表"),
        ("准备", "准备战斗"),
        ("战斗", "战斗结算"),
        ("奖励", "领取奖励"),
        ("返回", "返回界面"),
        ("退出", "退出界面"),
        ("点赞", "好友点赞"),
        ("协战", "协战奖励"),
        ("悬赏", "悬赏检测"),
        ("奸商", "奸商检测"),
        ("商店", "奸商检测"),
        ("麒麟", "寮麒麟"),
        ("一键", "一键日常"),
        ("截图", "截图"),
        ("OCR", "OCR识别"),
    )
    _STAGE_NAMES = {
        "main": "庭院首页",
        "menu_scroll": "展开功能栏",
        "team": "进入组队",
        "flag": "经验妖怪列表",
        "select": "选择经验妖怪",
        "join": "加入队伍",
        "refresh": "刷新列表",
        "prepare": "准备战斗",
        "battle": "战斗中",
        "win": "胜利结算",
        "defeat": "失败结算",
        "back": "返回界面",
        "exit_confirm": "退出确认",
        "bounty": "进入悬赏",
        "cooperation": "协作识别",
        "sharing": "现世协作识别",
        "magatama": "勾玉识别",
        "login": "登录按钮",
        "enter_game": "进入游戏",
        "guild_entry": "进入阴阳寮",
        "hunting_entry": "进入狩猎战",
        "challenge": "发起挑战",
        "already_challenged": "挑战状态",
        "soul_entry": "御魂入口",
        "dungeon_card": "选择副本",
        "floor10_active": "选择御魂十层",
        "floor10_inactive": "选择御魂十层",
        "formation_locked": "锁定阵容",
        "formation_unlocked": "锁定阵容",
        "bonus_lantern": "打开加成",
        "soul_bonus": "寻找御魂加成",
        "bonus_start": "开启御魂加成",
        "courtyard_back": "返回庭院",
        "store_entry": "进入商店",
        "popular_marker": "热门推荐页",
        "shop_back": "退出热门推荐",
        "merchant_entry": "进入神秘商店",
        "blue_ticket": "检测蓝票",
        "confirm": "确认刷新",
    }

    def __init__(self, task: str, *, match_repeat_seconds: float = 3.0):
        self.task = task
        self.match_repeat_seconds = max(0.0, float(match_repeat_seconds))
        self._last_matches: dict[tuple[str, str, Rect], float] = {}

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().strftime("%H:%M:%S")

    @staticmethod
    def _rect(rect: Optional[Rect]) -> str:
        if rect is None:
            return "无"
        return f"({rect[0]}, {rect[1]}, {rect[2]}, {rect[3]})"

    def _emit(self, level: str, stage: str, message: str, *, end: str = "\n") -> None:
        stage = self._STAGE_NAMES.get(stage, stage)
        line = f"{self._timestamp()} [{level}] [{self.task}/{stage}] {message}"
        with _PRINT_LOCK:
            builtins.print(line, end=end, flush=True)

    def info(self, stage: str, message: str) -> None:
        self._emit("INFO", stage, message)

    def warning(self, stage: str, message: str) -> None:
        self._emit("WARN", stage, message)

    def error(self, stage: str, message: str) -> None:
        self._emit("ERROR", stage, message)

    @staticmethod
    def _classify(message: str) -> tuple[str, str]:
        level = "INFO"
        if re.search(r"\[?ERROR\]?|错误|异常|未能", message, re.IGNORECASE):
            level = "ERROR"
        elif re.search(r"\[?WARN(?:ING)?\]?|警告", message, re.IGNORECASE):
            level = "WARN"
        cleaned = re.sub(
            r"^\[(?:ERROR|WARN(?:ING)?|INFO)\]\s*",
            "",
            message,
            flags=re.IGNORECASE,
        )
        return level, cleaned

    def message(self, stage: str, message: str) -> None:
        level, message = self._classify(message)
        self._emit(level, stage, message)

    def match(
        self,
        stage: str,
        template: str,
        score: float,
        threshold: float,
        click_region: Rect,
        *,
        search_region: Optional[Rect] = None,
    ) -> None:
        """记录成功识图；相同模板和区域短时间内只输出一次。"""
        key = (stage, template, click_region)
        now = time.monotonic()
        last = self._last_matches.get(key)
        if last is not None and now - last < self.match_repeat_seconds:
            return
        self._last_matches[key] = now
        extra = ""
        if search_region is not None:
            extra = f" | 搜索区域={self._rect(search_region)}"
        self._emit(
            "VISION",
            stage,
            "识图"
            f" | 模板={template}"
            f" | 分数={score:.3f}"
            f" | 阈值={threshold:.3f}"
            f" | 点击区域={self._rect(click_region)}"
            f"{extra}",
        )

    def click(
        self,
        stage: str,
        label: str,
        click_region: Rect,
        point: tuple[int, int],
    ) -> None:
        self._emit(
            "ACTION",
            stage,
            f"点击 | 目标={label} | 点击区域={self._rect(click_region)}"
            f" | 落点=({point[0]}, {point[1]})",
        )

    def _infer_stage(self, message: str) -> str:
        for token, stage in self._STAGE_HINTS:
            if token in message:
                return stage
        return "运行"

    def legacy_print(self, *values, sep=" ", end="\n", file=None, flush=False) -> None:
        """兼容原有 print 调用，并统一时间、等级、任务与阶段前缀。"""
        if file is not None:
            builtins.print(*values, sep=sep, end=end, file=file, flush=flush)
            return
        message = sep.join(str(value) for value in values)
        level, message = self._classify(message)
        self._emit(level, self._infer_stage(message), message, end=end)

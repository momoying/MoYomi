"""Daily 自动化任务统一日志格式。"""

from __future__ import annotations

import builtins
import os
import re
import threading
import time
from datetime import datetime
from typing import Optional, Tuple

from module.task_execution import current_stage, in_task_call, report_failure, set_stage


Rect = Tuple[int, int, int, int]
_PRINT_LOCK = threading.Lock()


class TaskLogger:
    """为任务状态、识图和点击输出提供统一且可实时刷新的格式。"""

    _STAGE_NAMES = {
        "准备御魂十层": "御魂十层",
        "发起协战挑战": "挑战",
        "战斗及奖励结算": "结算",
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
        "confirm": "确认",
    }

    def __init__(self, task: str, *, match_repeat_seconds: float = 3.0):
        self.task = task
        self.match_repeat_seconds = max(0.0, float(match_repeat_seconds))
        self._last_matches: dict[tuple[str, str, Rect], float] = {}
        self._business_stage: Optional[str] = None
        self.debug_enabled = os.getenv("MOYOMI_LOG_LEVEL", "INFO").upper() == "DEBUG"

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().strftime("%H:%M:%S")

    @staticmethod
    def _rect(rect: Optional[Rect]) -> str:
        if rect is None:
            return "无"
        return f"({rect[0]}, {rect[1]}, {rect[2]}, {rect[3]})"

    def _emit(self, level: str, stage: str, message: str, *, end: str = "\n") -> None:
        if level == "DEBUG" and not self.debug_enabled:
            return
        business_stage = current_stage() if in_task_call() else self._business_stage
        stage = business_stage or stage
        stage = self._STAGE_NAMES.get(stage, stage)
        if level == "ERROR":
            report_failure(message)
        context = self.task if stage in ("", "运行", self.task) else f"{self.task}/{stage}"
        line = f"{self._timestamp()} [{level}] [{context}] {message}"
        with _PRINT_LOCK:
            builtins.print(line, end=end, flush=True)

    def info(self, stage: str, message: str) -> None:
        self._emit("INFO", stage, message)

    def debug(self, stage: str, message: str) -> None:
        self._emit("DEBUG", stage, message)

    def set_stage(self, stage: str) -> None:
        """记录业务阶段用于失败定位，不额外输出阶段开始日志。"""
        previous = current_stage() if in_task_call() else self._business_stage
        if previous == stage:
            return
        self._business_stage = stage
        set_stage(stage)

    def warning(self, stage: str, message: str) -> None:
        self._emit("WARN", stage, message)

    def error(self, stage: str, message: str) -> None:
        self._emit("ERROR", stage, message)

    @staticmethod
    def _classify(message: str) -> tuple[str, str]:
        level = "INFO"
        explicit = re.match(r"^\[(ERROR|WARN(?:ING)?|INFO|DEBUG)\]", message, re.IGNORECASE)
        if explicit:
            level = "WARN" if explicit[1].upper().startswith("WARN") else explicit[1].upper()
        elif re.search(r"\[?ERROR\]?|错误|异常|未能", message, re.IGNORECASE):
            level = "ERROR"
        elif re.search(r"\[?WARN(?:ING)?\]?|警告", message, re.IGNORECASE):
            level = "WARN"
        cleaned = re.sub(
            r"^\[(?:ERROR|WARN(?:ING)?|INFO|DEBUG)\]\s*",
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
        """仅调试模式记录成功识图；相同模板和区域短时间内只输出一次。"""
        if not self.debug_enabled:
            return
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
            "DEBUG",
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
        message = f"点击 {label} ({point[0]}, {point[1]})"
        if self.debug_enabled:
            message += f" | 区域={self._rect(click_region)}"
        self._emit("ACTION", stage, message)

    def legacy_print(self, *values, sep=" ", end="\n", file=None, flush=False) -> None:
        """兼容原有 print 调用，并统一时间、等级、任务与阶段前缀。"""
        if file is not None:
            builtins.print(*values, sep=sep, end=end, file=file, flush=flush)
            return
        message = sep.join(str(value) for value in values)
        level, message = self._classify(message)
        self._emit(level, "", message, end=end)

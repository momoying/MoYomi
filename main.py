"""Daily 中控：按 JSON 中的账号、系统顺序登录并执行到期任务。"""

from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import random
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from Core.logging import TaskLogger
from Core.notifications import maybe_send_detection_summary


LOGGER = TaskLogger("中控")
print = LOGGER.legacy_print


HELPER_DIR = Path(__file__).resolve().parent
DAILY_TASKS_DIR = HELPER_DIR / "Daily"
WEEKLY_TASKS_DIR = HELPER_DIR / "Weekly"
PROJECT_ROOT = HELPER_DIR.parent
CONFIG_DIR = HELPER_DIR / "config"
STATUS_PATH = CONFIG_DIR / "account_status.json"
WEEKLY_STATUS_PATH = CONFIG_DIR / "weekly_account_status.json"
DAILY_MODE = "daily"
WEEKLY_MODE = "weekly"
VALID_TASK_MODES = {DAILY_MODE, WEEKLY_MODE}
CONSIGNMENT_HOUSE_TASK = "consignment_house"
WEEKLY_STATUS_VERSION = 1
HEART_TEAM_TASK = "heart_team"
HEART_TEAM_BATTLES_COMPLETED_CLEANUP_FAILED = (
    "battles_completed_cleanup_failed"
)
COOP_BATTLE_COMPLETED_RECOVERY_REQUIRED = "battle_completed_recovery_required"

MODULE_PATHS = {
    "startup_recovery": HELPER_DIR / "Core" / "startup.py",
    "task_timeout_recovery": HELPER_DIR / "Core" / "recovery.py",
    "switch": HELPER_DIR / "Sign_A_Switch" / "Switch.py",
    "sign": HELPER_DIR / "Sign_A_Switch" / "Sign.py",
    "mail_collected": DAILY_TASKS_DIR / "Mail" / "Mail.py",
    "liked": DAILY_TASKS_DIR / "Like" / "Like.py",
    "one_tap_daily_completed": DAILY_TASKS_DIR / "One-tap_daily" / "OneTapDaily.py",
    "coop_reward_completed": DAILY_TASKS_DIR / "CoopReward" / "CoopReward.py",
    "experience_monster_completed": DAILY_TASKS_DIR / "Exp" / "Exp_Monster.py",
    "bounty_checked": DAILY_TASKS_DIR / "Bounty" / "Bounty.py",
    "merchant_checked": DAILY_TASKS_DIR / "Merchant" / "Merchant.py",
    "guild_kirin_completed": DAILY_TASKS_DIR / "GuildKirin" / "GuildKirin.py",
    HEART_TEAM_TASK: DAILY_TASKS_DIR / "HeartTeam" / "HeartTeam.py",
    CONSIGNMENT_HOUSE_TASK: (
        WEEKLY_TASKS_DIR / "ConsignmentHouse" / "ConsignmentHouse.py"
    ),
}

TASK_ORDER = (
    "mail_collected",
    "liked",
    "one_tap_daily_completed",
    "coop_reward_completed",
    "experience_monster_completed",
    "bounty_checked",
    "merchant_checked",
    "guild_kirin_completed",
    HEART_TEAM_TASK,
)
SHUFFLED_TASK_ORDER = (
    "mail_collected",
    "liked",
    "bounty_checked",
    "one_tap_daily_completed",
    "merchant_checked",
)
BATTLE_TASK_ORDER = (
    "coop_reward_completed",
    "experience_monster_completed",
    "guild_kirin_completed",
    HEART_TEAM_TASK,
)
TASK_LABELS = {
    "mail_collected": "领取邮件",
    "liked": "好友点赞",
    "one_tap_daily_completed": "一键日常",
    "coop_reward_completed": "协战奖励",
    "experience_monster_completed": "经验妖怪",
    "bounty_checked": "悬赏检测",
    "merchant_checked": "奸商检测",
    "guild_kirin_completed": "寮麒麟",
    HEART_TEAM_TASK: "同心队",
    CONSIGNMENT_HOUSE_TASK: "寄售屋",
}
DEFAULT_TASK_ENABLED = {
    task_name: task_name != HEART_TEAM_TASK
    for task_name in TASK_ORDER
}

BOUNTY_TASK = "bounty_checked"
MERCHANT_TASK = "merchant_checked"
STATUS_VERSION = 8
SAME_REGION = "same"
CROSS_REGION = "cross"
VALID_REGIONS = (SAME_REGION, CROSS_REGION)
REGION_LABELS = {
    SAME_REGION: "狐之宴",
    CROSS_REGION: "砂狐乐园",
}
REGION_STATE_KEYS = {
    SAME_REGION: "同区",
    CROSS_REGION: "跨区",
}
CROSS_REGION_TASKS = ("liked", BOUNTY_TASK)
TASK_RESULT_FIELDS = {
    BOUNTY_TASK: "bounty_result",
    MERCHANT_TASK: "merchant_result",
}
TASK_TIME_FIELDS = {
    BOUNTY_TASK: "time",
    MERCHANT_TASK: "time",
    "coop_reward_completed": "completed_at",
    HEART_TEAM_TASK: "completed_at",
}
HEART_TEAM_ROLES = {"leader", "member"}
HEART_TEAM_ROLE_DETAILS = {
    "leader": "队长",
    "member": "成员",
}
GUILD_KIRIN_TASK = "guild_kirin_completed"
MAIL_TASK = "mail_collected"
COOP_REWARD_TASK = "coop_reward_completed"
COOP_REWARD_BASE_RUNS = 5
COOP_REWARD_EXTRA_RUNS = 5
BOUNTY_RESULT_DETAILS = {
    "normal_magatama_collaboration": "普通勾协",
    "sharing_magatama_collaboration": "现世勾协",
    "no_magatama_collaboration": "没有勾玉协作",
}
MERCHANT_RESULT_DETAILS = {
    "blue_ticket_50": "发现50蓝票",
    "blue_ticket_70": "发现70蓝票",
    "blue_ticket_80": "发现80蓝票",
    "blue_ticket_90": "发现90蓝票",
    "no_blue_ticket": "没有蓝票",
    "skipped_after_50": "已有账号发现50，已跳过",
}
MERCHANT_STOP_RESULT = "blue_ticket_50"
MERCHANT_SKIPPED_RESULT = "skipped_after_50"
CONSIGNMENT_ALREADY_PURCHASED = "already_purchased"
CONSIGNMENT_PURCHASED = "purchased"
CONSIGNMENT_ERROR = "error"


@dataclass
class ControllerServices:
    select_account: Callable[[str, bool], Optional[str]]
    exit_to_login: Callable[[], bool]
    sign_in: Callable[[str, str], bool]
    task_runners: dict[str, Callable[..., Any]]
    startup_recovery: Optional[Callable[[], Any]] = None
    task_timeout_recovery: Optional[Callable[[Any], Any]] = None
    task_recovery_retries: int = 1
    task_failure_recoveries: dict[str, Callable[[Any], Any]] = field(
        default_factory=dict
    )
    task_completion_recoveries: dict[str, Callable[[Any], Any]] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class TaskWork:
    task_name: str
    run_count: int


@dataclass(frozen=True)
class WorkItem:
    account_name: str
    system: str
    tasks: tuple[TaskWork, ...]
    region: str = SAME_REGION


EventCallback = Callable[[dict[str, Any]], None]


def _emit_event(
    callback: Optional[EventCallback],
    event_type: str,
    **payload: Any,
) -> None:
    if callback is not None:
        callback({"type": event_type, **payload})


def _load_module(name: str, path: Path):
    if not path.is_file():
        raise FileNotFoundError(f"任务模块不存在: {path}")
    module_name = f"daily_controller_{name}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载任务模块: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def build_services(
    screenshot_interval: Optional[float] = None,
    battle_detection_interval: Optional[float] = None,
    mumu_index: Optional[str] = None,
    adb_port: Optional[str] = None,
    adb_path: Optional[str] = None,
    mumu_path: Optional[str] = None,
    recovery_retry_count: int = 1,
    recovery_timeout_seconds: float = 90.0,
    recovery_unknown_grace_seconds: float = 10.0,
    timeout_screenshot_keep_count: int = 20,
) -> ControllerServices:
    """加载各任务模块，并把中控依赖收敛成简单调用接口。"""
    recovery_module = _load_module(
        "startup_recovery",
        MODULE_PATHS["startup_recovery"],
    )
    task_recovery_module = _load_module(
        "task_timeout_recovery",
        MODULE_PATHS["task_timeout_recovery"],
    )
    switch_module = _load_module("switch", MODULE_PATHS["switch"])
    sign_module = _load_module("sign", MODULE_PATHS["sign"])
    task_module_names = (*TASK_ORDER, CONSIGNMENT_HOUSE_TASK)
    task_modules = {
        key: _load_module(key, MODULE_PATHS[key])
        for key in task_module_names
    }
    utility_modules = {
        id(module_utils): module_utils
        for module in (
            recovery_module,
            task_recovery_module,
            switch_module,
            sign_module,
            *task_modules.values(),
        )
        if (module_utils := getattr(module, "utils", None)) is not None
    }.values()
    if adb_path or mumu_path:
        for module_utils in utility_modules:
            configure_paths = getattr(module_utils, "configure_runtime_paths", None)
            if callable(configure_paths):
                configure_paths(adb_path, mumu_path)
    if adb_port:
        for module_utils in utility_modules:
            configure_target = getattr(module_utils, "configure_mumu_target", None)
            if callable(configure_target):
                if not configure_target(adb_port, mumu_index or "auto"):
                    raise OSError(f"无法连接 MuMu ADB：{adb_port}")
    if screenshot_interval is not None:
        interval = max(0.1, float(screenshot_interval))
        for module in (switch_module, sign_module, *task_modules.values()):
            if hasattr(module, "SCREENSHOT_INTERVAL"):
                module.SCREENSHOT_INTERVAL = interval
            module_utils = getattr(module, "utils", None)
            if module_utils is not None and hasattr(module_utils, "config"):
                module_utils.config["screenshot_speed"] = interval
    if battle_detection_interval is not None:
        battle_interval = max(0.1, float(battle_detection_interval))
        coop_module = task_modules[COOP_REWARD_TASK]
        exp_module = task_modules["experience_monster_completed"]
        kirin_module = task_modules[GUILD_KIRIN_TASK]
        heart_team_module = task_modules[HEART_TEAM_TASK]
        coop_module.BATTLE_SCREENSHOT_INTERVAL = battle_interval
        exp_module.BATTLE_SCREENSHOT_INTERVAL = battle_interval
        kirin_module.BATTLE_CHECK_INTERVAL_SECONDS = battle_interval
        heart_team_module.BATTLE_SCREENSHOT_INTERVAL = battle_interval
    screenshot_keep_count = max(0, int(timeout_screenshot_keep_count))
    task_recovery_module.prune_failure_screenshots(screenshot_keep_count)
    task_runners = {
        key: (
            module.check_bounty
            if key == BOUNTY_TASK
            else (
                module.check_merchant
                if key == MERCHANT_TASK
                else (
                    module.check_consignment_house
                    if key == CONSIGNMENT_HOUSE_TASK
                    else module.run
                )
            )
        )
        for key, module in task_modules.items()
    }

    def recover_generic(stop_event=None):
        return task_recovery_module.recover_to_courtyard(
            stop_event=stop_event,
            timeout=max(0.1, float(recovery_timeout_seconds)),
            unknown_grace=max(
                0.1,
                float(recovery_unknown_grace_seconds),
            ),
            screenshot_keep_count=screenshot_keep_count,
        )

    def recover_heart_team(stop_event=None):
        return task_modules[HEART_TEAM_TASK].recover_to_courtyard(
            stop_event=stop_event,
            timeout=max(1.0, float(recovery_timeout_seconds)),
            fallback=recover_generic,
        )

    return ControllerServices(
        select_account=lambda account, exit_current: switch_module.select_account(
            account,
            exit_current=exit_current,
        ),
        exit_to_login=switch_module.exit_to_login,
        sign_in=lambda system, region: sign_module.run(system, region=region),
        task_runners=task_runners,
        startup_recovery=lambda: recovery_module.recover_to_login(
            switch_module.exit_to_login,
            lambda frame: task_modules[
                "experience_monster_completed"
            ].collect_battle_rewards(
                initial_frame=frame,
                timeout=60.0,
            ),
            lambda frame: task_modules[COOP_REWARD_TASK].collect_battle_rewards(
                initial_frame=frame,
                timeout=60.0,
            ),
        ),
        task_timeout_recovery=recover_generic,
        task_recovery_retries=max(0, int(recovery_retry_count)),
        task_failure_recoveries={
            MAIL_TASK: lambda stop_event=None: task_modules[
                MAIL_TASK
            ].recover_to_courtyard(
                stop_event=stop_event,
                fallback=recover_generic,
            ),
            COOP_REWARD_TASK: recover_generic,
            HEART_TEAM_TASK: recover_heart_team,
        },
        task_completion_recoveries={
            COOP_REWARD_TASK: recover_generic,
            HEART_TEAM_TASK: recover_heart_team,
        },
    )


def _empty_system_state() -> dict[str, Any]:
    return {
        "mail_collected": None,
        "liked": {
            "同区": None,
            "跨区": None,
        },
        "coop_reward_completed": {
            "completed_at": None,
            "battle_date": None,
            "battles_completed": 0,
            "battle_target": 0,
        },
        "experience_monster_completed": None,
        "one_tap_daily_completed": None,
        "bounty_checked": {
            "同区": {
                "time": None,
                "bounty_result": None,
            },
            "跨区": {
                "time": None,
                "bounty_result": None,
            },
        },
        "merchant_checked": {
            "time": None,
            "merchant_result": None,
        },
        "guild_kirin_completed": None,
        HEART_TEAM_TASK: {
            "role": None,
            "completed_at": None,
            "battle_date": None,
            "battles_completed": 0,
            "battle_target": 0,
        },
        "latest_task_completed_at": None,
        "task_enabled": dict(DEFAULT_TASK_ENABLED),
        "cross_region_enabled": False,
    }


def _normalize_timestamp(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return None
    return value


def _normalize_battle_date(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _normalized_nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _region_task_value(
    system_state: dict[str, Any],
    task_name: str,
    region: str,
) -> Any:
    value = system_state.get(task_name)
    if task_name not in CROSS_REGION_TASKS:
        if task_name == MERCHANT_TASK and isinstance(value, dict):
            # 兼容曾被错误写成“同区/跨区”的奸商记录。
            malformed_record = value.get(REGION_STATE_KEYS[SAME_REGION])
            if isinstance(malformed_record, dict):
                return malformed_record
        return value

    region_key = REGION_STATE_KEYS[region]
    if isinstance(value, dict) and any(
        key in value for key in REGION_STATE_KEYS.values()
    ):
        return value.get(region_key)
    if region == SAME_REGION:
        # v5 以前同区记录直接保存在任务字段中。
        return value

    # 兼容上一版短暂使用过的独立 cross_region 状态对象。
    legacy_cross = system_state.get("cross_region")
    if isinstance(legacy_cross, dict):
        return legacy_cross.get(task_name)
    return None


def task_record_time(
    system_state: dict[str, Any],
    task_name: str,
    region: str = SAME_REGION,
) -> Optional[str]:
    """读取任务时间；点赞和悬赏可分别读取同区、跨区记录。"""
    value = _region_task_value(system_state, task_name, region)
    time_field = TASK_TIME_FIELDS.get(task_name)
    if time_field is not None and isinstance(value, dict):
        value = value.get(time_field)
    return _normalize_timestamp(value)


def task_record_result(
    system_state: dict[str, Any],
    task_name: str,
    region: str = SAME_REGION,
) -> Optional[str]:
    """读取聚合任务结果；悬赏可分别读取同区、跨区。"""
    result_field = TASK_RESULT_FIELDS.get(task_name)
    if result_field is None:
        return None
    record = _region_task_value(system_state, task_name, region)
    if isinstance(record, dict):
        return record.get(result_field)
    return system_state.get(result_field) if region == SAME_REGION else None


def set_task_record_result(
    system_state: dict[str, Any],
    task_name: str,
    result: Optional[str],
    region: str = SAME_REGION,
) -> None:
    """写入聚合任务结果，同时保留已有时间及任务自身的数据结构。"""
    result_field = TASK_RESULT_FIELDS[task_name]
    if task_name not in CROSS_REGION_TASKS:
        current_record = system_state.get(task_name)
        has_region_keys = isinstance(current_record, dict) and any(
            key in current_record for key in REGION_STATE_KEYS.values()
        )
        record = (
            dict(current_record)
            if isinstance(current_record, dict) and not has_region_keys
            else {}
        )
        time_field = TASK_TIME_FIELDS.get(task_name)
        if time_field is not None:
            record[time_field] = task_record_time(system_state, task_name)
        record[result_field] = result
        system_state[task_name] = record
        system_state.pop(result_field, None)
        return

    records = system_state.get(task_name)
    if not isinstance(records, dict) or not any(
        key in records for key in REGION_STATE_KEYS.values()
    ):
        records = {
            REGION_STATE_KEYS[SAME_REGION]: None,
            REGION_STATE_KEYS[CROSS_REGION]: None,
        }
    records[REGION_STATE_KEYS[region]] = {
        "time": task_record_time(system_state, task_name, region),
        result_field: result,
    }
    system_state[task_name] = records
    system_state.pop(result_field, None)


def heart_team_role(system_state: dict[str, Any]) -> Optional[str]:
    """返回同心队身份，兼容直接填写中文身份。"""
    record = system_state.get(HEART_TEAM_TASK)
    if not isinstance(record, dict):
        return None
    role = record.get("role")
    if role == "队长":
        role = "leader"
    elif role == "成员":
        role = "member"
    return role if role in HEART_TEAM_ROLES else None


def set_heart_team_role(
    system_state: dict[str, Any],
    role: Optional[str],
) -> None:
    """保存同心队身份并保留已有完成时间。"""
    normalized_role = role if role in HEART_TEAM_ROLES else None
    current = system_state.get(HEART_TEAM_TASK)
    record = dict(current) if isinstance(current, dict) else {}
    record.update(
        {
            "role": normalized_role,
            "completed_at": task_record_time(system_state, HEART_TEAM_TASK),
            "battle_date": _normalize_battle_date(record.get("battle_date")),
            "battles_completed": _normalized_nonnegative_int(
                record.get("battles_completed")
            ),
            "battle_target": _normalized_nonnegative_int(
                record.get("battle_target")
            ),
        }
    )
    system_state[HEART_TEAM_TASK] = record


def battle_progress(
    system_state: dict[str, Any],
    task_name: str,
    now: datetime,
) -> tuple[int, int]:
    """读取当前本地日期的战斗进度；跨日记录自动视为零。"""
    record = system_state.get(task_name)
    if not isinstance(record, dict):
        return 0, 0
    battle_date = _normalize_battle_date(record.get("battle_date"))
    if battle_date != now.astimezone().date().isoformat():
        return 0, 0
    completed = _normalized_nonnegative_int(record.get("battles_completed"))
    target = _normalized_nonnegative_int(record.get("battle_target"))
    return min(completed, target) if target else completed, target


def set_battle_progress(
    system_state: dict[str, Any],
    task_name: str,
    now: datetime,
    completed: int,
    target: int,
) -> None:
    """保存当前账号/系统当天的战斗场次，并保留任务其他字段。"""
    current = system_state.get(task_name)
    record = dict(current) if isinstance(current, dict) else {}
    target = _normalized_nonnegative_int(target)
    completed = min(_normalized_nonnegative_int(completed), target)
    record.update(
        {
            "battle_date": now.astimezone().date().isoformat(),
            "battles_completed": completed,
            "battle_target": target,
        }
    )
    system_state[task_name] = record


def heart_team_battle_target(now: datetime) -> int:
    """周一至周四 20 场，周五至周日 30 场。"""
    return 30 if now.astimezone().weekday() >= 4 else 20


def cross_region_is_enabled(system_state: dict[str, Any]) -> bool:
    """返回当前大账号/系统是否启用砂狐乐园角色。"""
    return system_state.get("cross_region_enabled") is True


def _normalize_system_state(raw: Any) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    state = _empty_system_state()
    state[MAIL_TASK] = _normalize_timestamp(raw.get(MAIL_TASK))
    state["liked"] = {
        REGION_STATE_KEYS[region]: task_record_time(raw, "liked", region)
        for region in VALID_REGIONS
    }
    state["one_tap_daily_completed"] = _normalize_timestamp(
        raw.get("one_tap_daily_completed")
    )
    raw_coop = raw.get(COOP_REWARD_TASK)
    raw_coop_record = raw_coop if isinstance(raw_coop, dict) else {}
    state[COOP_REWARD_TASK] = {
        "completed_at": task_record_time(raw, COOP_REWARD_TASK),
        "battle_date": _normalize_battle_date(
            raw_coop_record.get("battle_date")
        ),
        "battles_completed": _normalized_nonnegative_int(
            raw_coop_record.get("battles_completed")
        ),
        "battle_target": _normalized_nonnegative_int(
            raw_coop_record.get("battle_target")
        ),
    }
    state["guild_kirin_completed"] = _normalize_timestamp(
        raw.get("guild_kirin_completed")
    )
    state[BOUNTY_TASK] = {}
    for region in VALID_REGIONS:
        bounty_time = task_record_time(raw, BOUNTY_TASK, region)
        bounty_result = task_record_result(raw, BOUNTY_TASK, region)
        if bounty_result == "no_bounty":
            # 悬赏入口恒定存在；旧版把入口漏检误记为成功，必须重新检测。
            bounty_time = None
            bounty_result = None
        if bounty_result == "magatama_collaboration":
            # 兼容旧版未区分“协/享”的状态；无法还原时按普通勾协处理。
            bounty_result = "normal_magatama_collaboration"
        state[BOUNTY_TASK][REGION_STATE_KEYS[region]] = {
            "time": bounty_time,
            "bounty_result": (
                bounty_result if bounty_result in BOUNTY_RESULT_DETAILS else None
            ),
        }
    merchant_time = task_record_time(raw, MERCHANT_TASK)
    merchant_result = task_record_result(raw, MERCHANT_TASK)
    if merchant_result == "cheapest_blue_ticket_found":
        merchant_result = "blue_ticket_50"
    normalized_merchant_result = (
        merchant_result if merchant_result in MERCHANT_RESULT_DETAILS else None
    )
    if merchant_time is not None and normalized_merchant_result is None:
        # 旧版只区分“有/无蓝票”，升级为最低价 50 检测后必须重新执行。
        merchant_time = None
    state[MERCHANT_TASK] = {
        "time": merchant_time,
        "merchant_result": normalized_merchant_result,
    }
    raw_heart = raw.get(HEART_TEAM_TASK)
    raw_heart_record = raw_heart if isinstance(raw_heart, dict) else {}
    state[HEART_TEAM_TASK] = {
        "role": heart_team_role(raw),
        "completed_at": task_record_time(raw, HEART_TEAM_TASK),
        "battle_date": _normalize_battle_date(
            raw_heart_record.get("battle_date")
        ),
        "battles_completed": _normalized_nonnegative_int(
            raw_heart_record.get("battles_completed")
        ),
        "battle_target": _normalized_nonnegative_int(
            raw_heart_record.get("battle_target")
        ),
    }
    state["latest_task_completed_at"] = _normalize_timestamp(
        raw.get("latest_task_completed_at")
    )

    experience_value = raw.get("experience_monster_completed")
    if isinstance(experience_value, list):
        # 兼容旧结构：列表中最后一个有效时间就是最近完成时间。
        valid_timestamps = [
            timestamp
            for timestamp in (
                _normalize_timestamp(value) for value in experience_value
            )
            if timestamp is not None
        ]
        state["experience_monster_completed"] = (
            valid_timestamps[-1] if valid_timestamps else None
        )
    else:
        state["experience_monster_completed"] = _normalize_timestamp(
            experience_value
        )
    raw_task_enabled = raw.get("task_enabled")
    raw_task_enabled = (
        raw_task_enabled
        if isinstance(raw_task_enabled, dict)
        else {}
    )
    state["task_enabled"] = {
        task_name: (
            raw_task_enabled[task_name]
            if isinstance(raw_task_enabled.get(task_name), bool)
                else DEFAULT_TASK_ENABLED[task_name]
        )
        for task_name in TASK_ORDER
    }
    state["cross_region_enabled"] = raw.get("cross_region_enabled") is True
    return state


def load_state(path: Path = STATUS_PATH) -> tuple[dict[str, Any], bool]:
    """加载 v7 状态；所有账号均可按系统启用跨区任务。"""
    with Path(path).open("r", encoding="utf-8") as file:
        raw = json.load(file)

    raw_accounts = raw.get("accounts")
    if not isinstance(raw_accounts, dict) or not raw_accounts:
        raise ValueError("account_status.json 的 accounts 必须是非空对象")

    migrated = raw.get("version") != STATUS_VERSION
    accounts: dict[str, Any] = {}
    for account_name, account_raw in raw_accounts.items():
        if not isinstance(account_raw, dict):
            raise ValueError(f"账号 {account_name} 的配置必须是对象")

        raw_systems = account_raw.get("systems")
        if isinstance(raw_systems, dict) and raw_systems:
            systems = {}
            for system, system_state in raw_systems.items():
                normalized_state = _normalize_system_state(system_state)
                systems[str(system)] = normalized_state
                if normalized_state != system_state:
                    migrated = True
        else:
            login_systems = account_raw.get("login_systems", [])
            if not isinstance(login_systems, list) or not login_systems:
                raise ValueError(f"账号 {account_name} 未配置 systems")
            systems = {
                str(system): _normalize_system_state(account_raw)
                for system in login_systems
            }
            migrated = True

        invalid_systems = [system for system in systems if system not in {"IOS", "Android"}]
        if invalid_systems:
            raise ValueError(f"账号 {account_name} 包含不支持的系统: {invalid_systems}")
        if "cross_region_available" in account_raw:
            migrated = True
        accounts[account_name] = {"systems": systems}

    return {"version": STATUS_VERSION, "accounts": accounts}, migrated


def save_state(state: dict[str, Any], path: Path = STATUS_PATH) -> None:
    """原子写入状态，避免任务中断时留下半份 JSON。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_path, path)


def _empty_weekly_system_state() -> dict[str, Any]:
    return {
        CONSIGNMENT_HOUSE_TASK: {
            "completed_at": None,
            "result": None,
        }
    }


def _normalize_weekly_system_state(raw: Any) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    record = raw.get(CONSIGNMENT_HOUSE_TASK)
    record = record if isinstance(record, dict) else {}
    completed_at = _normalize_timestamp(record.get("completed_at"))
    result = record.get("result")
    if result not in {
        CONSIGNMENT_ALREADY_PURCHASED,
        CONSIGNMENT_PURCHASED,
    }:
        result = None
        # 只有明确的购买结果才允许完成时间阻止再次检查。
        completed_at = None
    return {
        CONSIGNMENT_HOUSE_TASK: {
            "completed_at": completed_at,
            "result": result,
        }
    }


def load_weekly_state(
    path: Path = WEEKLY_STATUS_PATH,
    daily_state: Optional[dict[str, Any]] = None,
) -> tuple[dict[str, Any], bool]:
    """加载周常状态，并按日常账号清单补齐缺失节点、保留旧节点。"""
    path = Path(path)
    if path.is_file():
        with path.open("r", encoding="utf-8") as file:
            raw = json.load(file)
    else:
        raw = {}

    migrated = raw.get("version") != WEEKLY_STATUS_VERSION
    raw_accounts = raw.get("accounts")
    raw_accounts = raw_accounts if isinstance(raw_accounts, dict) else {}
    accounts: dict[str, Any] = {}
    for account_name, account_raw in raw_accounts.items():
        account_raw = account_raw if isinstance(account_raw, dict) else {}
        raw_systems = account_raw.get("systems")
        raw_systems = raw_systems if isinstance(raw_systems, dict) else {}
        systems = {
            str(system): _normalize_weekly_system_state(system_state)
            for system, system_state in raw_systems.items()
        }
        accounts[str(account_name)] = {"systems": systems}
        if account_raw != accounts[str(account_name)]:
            migrated = True

    if daily_state is None:
        daily_state, _ = load_state(STATUS_PATH)
    for account_name, account_state in daily_state["accounts"].items():
        weekly_account = accounts.setdefault(account_name, {"systems": {}})
        systems = weekly_account.setdefault("systems", {})
        for system in account_state["systems"]:
            if system not in systems:
                systems[system] = _empty_weekly_system_state()
                migrated = True

    state = {"version": WEEKLY_STATUS_VERSION, "accounts": accounts}
    return state, migrated


def save_weekly_state(
    state: dict[str, Any],
    path: Path = WEEKLY_STATUS_PATH,
) -> None:
    save_state(state, path)


def weekly_consignment_is_due(record: dict[str, Any], now: datetime) -> bool:
    """寄售屋在本地时间每周一 00:00 进入新周期。"""
    if now.tzinfo is None:
        now = now.astimezone()
    completed = _parse_timestamp(record.get("completed_at"), now)
    week_start = (now - timedelta(days=now.weekday())).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    return completed is None or completed < week_start


def weekly_task_record(
    weekly_state: dict[str, Any],
    account_name: str,
    system: str,
) -> dict[str, Any]:
    return weekly_state["accounts"][account_name]["systems"][system][
        CONSIGNMENT_HOUSE_TASK
    ]


def build_weekly_work_queue(
    daily_state: dict[str, Any],
    weekly_state: dict[str, Any],
    now: datetime,
    *,
    shuffle_accounts: Callable[[list[str]], None] = random.shuffle,
    shuffle_systems: Callable[[list[str]], None] = random.shuffle,
) -> list[WorkItem]:
    """只按日常状态中的现役账号/系统生成寄售屋周常队列。"""
    account_names = list(daily_state["accounts"])
    shuffle_accounts(account_names)
    queue: list[WorkItem] = []
    for account_name in account_names:
        system_names = list(daily_state["accounts"][account_name]["systems"])
        shuffle_systems(system_names)
        for system in system_names:
            record = weekly_task_record(weekly_state, account_name, system)
            if weekly_consignment_is_due(record, now):
                queue.append(
                    WorkItem(
                        account_name,
                        system,
                        (TaskWork(CONSIGNMENT_HOUSE_TASK, 1),),
                    )
                )
    return queue


def _parse_timestamp(value: Any, now: datetime) -> Optional[datetime]:
    value = _normalize_timestamp(value)
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=now.tzinfo)
    return parsed.astimezone(now.tzinfo)


def _next_experience_refresh(after: datetime) -> datetime:
    """返回严格晚于 after 的下一个 00:00 或 12:00 刷新点。"""
    midnight = after.replace(hour=0, minute=0, second=0, microsecond=0)
    noon = midnight.replace(hour=12)
    if after < noon:
        return noon
    return midnight + timedelta(days=1)


def experience_runs_due(system_state: dict[str, Any], now: datetime) -> int:
    """统计上次完成至今跨过的刷新点数量，首次运行1次，最多补2次。"""
    if now.tzinfo is None:
        now = now.astimezone()
    completed = _parse_timestamp(
        system_state.get("experience_monster_completed"),
        now,
    )
    if completed is None:
        return 1
    if completed >= now:
        return 0

    runs_due = 0
    refresh = _next_experience_refresh(completed)
    while refresh <= now and runs_due < 2:
        runs_due += 1
        refresh = _next_experience_refresh(refresh)
    return runs_due


def _latest_bounty_refresh(now: datetime) -> datetime:
    """返回不晚于 now 的最近一个悬赏刷新点（06:00 或 18:00）。"""
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    morning_refresh = day_start.replace(hour=6)
    evening_refresh = day_start.replace(hour=18)
    if now >= evening_refresh:
        return evening_refresh
    if now >= morning_refresh:
        return morning_refresh
    return (day_start - timedelta(days=1)).replace(hour=18)


def _latest_mail_refresh(now: datetime) -> datetime:
    """返回不晚于 now 的最近一个邮件日刷新点（每天 06:00）。"""
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    morning_refresh = day_start.replace(hour=6)
    if now >= morning_refresh:
        return morning_refresh
    return (day_start - timedelta(days=1)).replace(hour=6)


def mail_is_due(system_state: dict[str, Any], now: datetime) -> bool:
    """邮件每天 06:00 检查一次；没有红点也算本周期已检查。"""
    if now.tzinfo is None:
        now = now.astimezone()
    completed = _parse_timestamp(system_state.get(MAIL_TASK), now)
    return completed is None or completed < _latest_mail_refresh(now)


def bounty_is_due(
    system_state: dict[str, Any],
    now: datetime,
    region: str = SAME_REGION,
) -> bool:
    """悬赏每天 06:00/18:00 重置；只需检查当前最新周期。"""
    if now.tzinfo is None:
        now = now.astimezone()
    checked = _parse_timestamp(
        task_record_time(system_state, BOUNTY_TASK, region),
        now,
    )
    if checked is None:
        return True
    return checked < _latest_bounty_refresh(now)


def task_is_available(task_name: str, now: datetime) -> bool:
    """返回任务当前是否开放；普通日常任务始终开放。"""
    if now.tzinfo is None:
        now = now.astimezone()

    if task_name == MERCHANT_TASK:
        return now.weekday() in {2, 5}  # 周三、周六

    if task_name == GUILD_KIRIN_TASK:
        if now.weekday() > 3:  # 周一至周四
            return False
        window_start = now.replace(hour=6, minute=0, second=0, microsecond=0)
        window_end = now.replace(hour=23, minute=0, second=0, microsecond=0)
        return window_start <= now < window_end

    return True


def task_is_enabled(system_state: dict[str, Any], task_name: str) -> bool:
    """返回当前账号/系统角色是否启用指定任务；旧数据默认全部启用。"""
    task_enabled = system_state.get("task_enabled")
    if not isinstance(task_enabled, dict):
        return DEFAULT_TASK_ENABLED.get(task_name, True)
    default = DEFAULT_TASK_ENABLED.get(task_name, True)
    value = task_enabled.get(task_name, default)
    return value if isinstance(value, bool) else default


def combined_task_is_enabled(
    system_state: dict[str, Any],
    task_name: str,
) -> bool:
    """卡片层面的启用状态：同区任务或固定跨区任务任一启用即可。"""
    return task_is_enabled(system_state, task_name) or (
        cross_region_is_enabled(system_state)
        and task_name in CROSS_REGION_TASKS
    )


def combined_task_runs_due(
    task_name: str,
    system_state: dict[str, Any],
    now: datetime,
) -> int:
    """合并同一卡片下狐之宴与砂狐乐园的到期次数。"""
    runs = (
        task_runs_due(task_name, system_state, now)
        if task_is_enabled(system_state, task_name)
        else 0
    )
    if cross_region_is_enabled(system_state) and task_name in CROSS_REGION_TASKS:
        runs += task_runs_due(
            task_name,
            system_state,
            now,
            region=CROSS_REGION,
        )
    return runs


def combined_bounty_detail(system_state: dict[str, Any]) -> str:
    """生成旧卡片使用的同区/跨区悬赏摘要。"""
    same_result = (
        task_record_result(system_state, BOUNTY_TASK, SAME_REGION)
        if task_is_enabled(system_state, BOUNTY_TASK)
        else None
    )
    if not cross_region_is_enabled(system_state):
        return BOUNTY_RESULT_DETAILS.get(same_result, "当前周期已检查")

    cross_result = task_record_result(system_state, BOUNTY_TASK, CROSS_REGION)
    short_labels = {
        "normal_magatama_collaboration": "普勾",
        "sharing_magatama_collaboration": "现世勾",
    }
    same_label = short_labels.get(same_result)
    cross_label = short_labels.get(cross_result)
    if same_label is None and cross_label is None:
        return "无勾协"
    if same_label is not None and same_label == cross_label:
        return f"{same_label}（双）"

    details = []
    if same_label is not None:
        details.append(f"{same_label}（同）")
    if cross_label is not None:
        details.append(f"{cross_label}（跨）")
    return " · ".join(details)


def combined_bounty_highlight_result(
    system_state: dict[str, Any],
) -> Optional[str]:
    """沿用旧配色；任一区有现世勾时优先使用现世勾高亮。"""
    results = [
        task_record_result(system_state, BOUNTY_TASK, SAME_REGION)
        if task_is_enabled(system_state, BOUNTY_TASK)
        else None
    ]
    if cross_region_is_enabled(system_state):
        results.append(
            task_record_result(system_state, BOUNTY_TASK, CROSS_REGION)
        )
    if "sharing_magatama_collaboration" in results:
        return "sharing_magatama_collaboration"
    if "normal_magatama_collaboration" in results:
        return "normal_magatama_collaboration"
    return None


def guild_kirin_is_due(system_state: dict[str, Any], now: datetime) -> bool:
    """寮麒麟仅周一至周四的 06:00（含）至 23:00（不含）执行一次。"""
    if now.tzinfo is None:
        now = now.astimezone()
    if not task_is_available(GUILD_KIRIN_TASK, now):
        return False
    window_start = now.replace(hour=6, minute=0, second=0, microsecond=0)
    completed = _parse_timestamp(system_state.get(GUILD_KIRIN_TASK), now)
    return completed is None or completed < window_start


def task_is_due(
    task_name: str,
    system_state: dict[str, Any],
    now: datetime,
    *,
    region: str = SAME_REGION,
) -> bool:
    """判断同一账号、同一系统的任务在当前时刻是否需要执行。"""
    if now.tzinfo is None:
        now = now.astimezone()

    if task_name == "one_tap_daily_completed":
        completed = _parse_timestamp(
            system_state.get("one_tap_daily_completed"),
            now,
        )
        if completed is None or completed.date() != now.date():
            return True
        if completed >= now:
            return False

        # 17:00 至次日 00:00 是每天独立的一次收获机会：
        # 晚间尚未执行时不受 4 小时限制，执行过则本日不再重复。
        evening_start = now.replace(hour=17, minute=0, second=0, microsecond=0)
        next_midnight = now.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        ) + timedelta(days=1)
        if evening_start <= now < next_midnight:
            return completed < evening_start

        # 同一天的其他时段，距离上次完成满 4 小时才再次收获。
        return now - completed >= timedelta(hours=4)

    if task_name == "liked":
        completed = _parse_timestamp(
            task_record_time(system_state, "liked", region),
            now,
        )
        return completed is None or completed.date() != now.date()

    if task_name == COOP_REWARD_TASK:
        completed = _parse_timestamp(
            task_record_time(system_state, COOP_REWARD_TASK),
            now,
        )
        if completed is not None and completed.date() == now.date():
            return False
        battles_completed, battle_target = battle_progress(
            system_state,
            COOP_REWARD_TASK,
            now,
        )
        return battle_target <= 0 or battles_completed < battle_target

    if task_name == MAIL_TASK:
        return mail_is_due(system_state, now)

    if task_name == "experience_monster_completed":
        return experience_runs_due(system_state, now) > 0

    if task_name == BOUNTY_TASK:
        return bounty_is_due(system_state, now, region)

    if task_name == MERCHANT_TASK:
        if not task_is_available(MERCHANT_TASK, now):
            return False
        completed = _parse_timestamp(
            task_record_time(system_state, MERCHANT_TASK),
            now,
        )
        return completed is None or completed.date() != now.date()

    if task_name == GUILD_KIRIN_TASK:
        return guild_kirin_is_due(system_state, now)

    if task_name == HEART_TEAM_TASK:
        role = heart_team_role(system_state)
        if role not in HEART_TEAM_ROLES:
            return False
        completed = _parse_timestamp(
            task_record_time(system_state, HEART_TEAM_TASK),
            now,
        )
        if role == "member":
            # 一键预存可不限次数连续补充；成员每三天集中补满一次，
            # 减少额外登录和 OCR 时间。
            if completed is None:
                return True
            return (now.date() - completed.date()).days >= 3
        battles_completed, battle_target = battle_progress(
            system_state,
            HEART_TEAM_TASK,
            now,
        )
        if (
            battle_target == heart_team_battle_target(now)
            and battles_completed >= battle_target
        ):
            return False
        return completed is None or completed.date() != now.date()

    raise KeyError(f"未知任务: {task_name}")


def task_runs_due(
    task_name: str,
    system_state: dict[str, Any],
    now: datetime,
    *,
    region: str = SAME_REGION,
) -> int:
    """返回任务在当前刷新周期需要执行的次数。"""
    if task_name == "experience_monster_completed":
        return experience_runs_due(system_state, now)
    return 1 if task_is_due(task_name, system_state, now, region=region) else 0


def _ordered_due_tasks(
    system_state: dict[str, Any],
    now: datetime,
    shuffle_tasks: Callable[[list[TaskWork]], None],
    coop_reward_runs: int,
) -> tuple[TaskWork, ...]:
    """分别打乱非战斗任务和战斗任务。"""
    shuffled_tasks = [
        TaskWork(task_name, run_count)
        for task_name in SHUFFLED_TASK_ORDER
        if task_is_enabled(system_state, task_name)
        and (run_count := task_runs_due(task_name, system_state, now)) > 0
    ]
    shuffle_tasks(shuffled_tasks)

    battle_tasks: list[TaskWork] = []
    for task_name in BATTLE_TASK_ORDER:
        if not task_is_enabled(system_state, task_name):
            continue
        if task_name == COOP_REWARD_TASK:
            if not task_is_due(COOP_REWARD_TASK, system_state, now):
                continue
            completed_battles, saved_target = battle_progress(
                system_state,
                COOP_REWARD_TASK,
                now,
            )
            target = saved_target or coop_reward_runs
            run_count = max(0, target - completed_battles)
        else:
            run_count = task_runs_due(task_name, system_state, now)
        if run_count > 0:
            battle_tasks.append(TaskWork(task_name, run_count))
    shuffle_tasks(battle_tasks)
    return tuple(shuffled_tasks + battle_tasks)


def _coop_reward_run_allocations(
    state: dict[str, Any],
    now: datetime,
) -> dict[tuple[str, str], int]:
    """
    每个账号/系统保底 5 场，再从全部节点中不重复抽取 5 个各加 1 场。

    使用日期和账号列表生成每日稳定的随机种子，保证同一天重启中控时
    额外场次不会重新分配；日期变化后会自然生成新的抽签结果。
    """
    nodes = [
        (account_name, system)
        for account_name, account_state in state["accounts"].items()
        for system, system_state in account_state["systems"].items()
        if task_is_enabled(system_state, COOP_REWARD_TASK)
    ]
    allocations = {
        node: COOP_REWARD_BASE_RUNS
        for node in nodes
    }
    if not nodes:
        return allocations

    seed_text = "|".join(
        (
            now.date().isoformat(),
            "coop_reward",
            *(f"{account_name}\0{system}" for account_name, system in nodes),
        )
    )
    seed = int.from_bytes(
        hashlib.sha256(seed_text.encode("utf-8")).digest()[:8],
        "big",
    )
    rng = random.Random(seed)
    for node in rng.sample(nodes, min(COOP_REWARD_EXTRA_RUNS, len(nodes))):
        allocations[node] += 1
    return allocations


def build_work_queue(
    state: dict[str, Any],
    now: datetime,
    shuffle_tasks: Callable[[list[TaskWork]], None] = random.shuffle,
    *,
    shuffle_accounts: Callable[[list[str]], None] = random.shuffle,
    shuffle_systems: Callable[[list[str]], None] = random.shuffle,
) -> list[WorkItem]:
    """
    每次启动独立打乱大账号顺序，以及各账号内部的系统顺序。

    队列是启动时的快照：没有到期任务的账号/系统不会登录。
    同一大账号的到期系统保持相邻，完成后才进入下一个大账号。
    邮件、点赞、悬赏、奸商检测和一键日常按账号/系统独立打乱；
    协战奖励、经验妖怪和寮麒麟组成第二个随机战斗队列。
    """
    if now.tzinfo is None:
        now = now.astimezone()

    queue: list[WorkItem] = []
    deferred_member_reserves: list[WorkItem] = []
    coop_allocations = _coop_reward_run_allocations(state, now)
    account_names = list(state["accounts"])
    shuffle_accounts(account_names)
    for account_name in account_names:
        account_state = state["accounts"][account_name]
        system_names = list(account_state["systems"])
        shuffle_systems(system_names)
        for system in system_names:
            system_state = account_state["systems"][system]
            tasks = _ordered_due_tasks(
                system_state,
                now,
                shuffle_tasks,
                coop_allocations.get((account_name, system), 0),
            )
            if tasks:
                if heart_team_role(system_state) == "member":
                    member_reserve = tuple(
                        task
                        for task in tasks
                        if task.task_name == HEART_TEAM_TASK
                    )
                    regular_tasks = tuple(
                        task
                        for task in tasks
                        if task.task_name != HEART_TEAM_TASK
                    )
                    if regular_tasks:
                        queue.append(
                            WorkItem(account_name, system, regular_tasks)
                        )
                    if member_reserve:
                        deferred_member_reserves.append(
                            WorkItem(account_name, system, member_reserve)
                        )
                else:
                    queue.append(WorkItem(account_name, system, tasks))

            if cross_region_is_enabled(system_state):
                cross_tasks = [
                    TaskWork(task_name, 1)
                    for task_name in CROSS_REGION_TASKS
                    if task_is_due(
                        task_name,
                        system_state,
                        now,
                        region=CROSS_REGION,
                    )
                ]
                shuffle_tasks(cross_tasks)
                if cross_tasks:
                    queue.append(
                        WorkItem(
                            account_name,
                            system,
                            tuple(cross_tasks),
                            region=CROSS_REGION,
                        )
                    )

    # 不改变上方账号/系统的随机遍历顺序。成员在原位置先执行其他任务，
    # 同心队预存统一追加为收尾队列，确保发生在当天队长战斗之后。
    return queue + deferred_member_reserves


def record_task_completion(
    task_name: str,
    system_state: dict[str, Any],
    completed_at: datetime,
    *,
    region: str = SAME_REGION,
) -> str:
    """写入精确到秒的最近完成时间。"""
    timestamp = completed_at.astimezone().isoformat(timespec="seconds")
    if task_name in CROSS_REGION_TASKS:
        records = system_state.get(task_name)
        if not isinstance(records, dict) or not any(
            key in records for key in REGION_STATE_KEYS.values()
        ):
            records = {
                REGION_STATE_KEYS[SAME_REGION]: None,
                REGION_STATE_KEYS[CROSS_REGION]: None,
            }
        region_key = REGION_STATE_KEYS[region]
        if task_name == "liked":
            records[region_key] = timestamp
        else:
            current = records.get(region_key)
            record = dict(current) if isinstance(current, dict) else {}
            record["time"] = timestamp
            record["bounty_result"] = task_record_result(
                system_state,
                BOUNTY_TASK,
                region,
            )
            records[region_key] = record
        system_state[task_name] = records
        system_state["latest_task_completed_at"] = timestamp
        return timestamp

    time_field = TASK_TIME_FIELDS.get(task_name)
    if time_field is None:
        system_state[task_name] = timestamp
    else:
        current_record = system_state.get(task_name)
        record = dict(current_record) if isinstance(current_record, dict) else {}
        record[time_field] = timestamp
        result_field = TASK_RESULT_FIELDS.get(task_name)
        if result_field is not None:
            record[result_field] = task_record_result(system_state, task_name)
            system_state.pop(result_field, None)
        if task_name == HEART_TEAM_TASK:
            record["role"] = heart_team_role(system_state)
        system_state[task_name] = record
    system_state["latest_task_completed_at"] = timestamp
    return timestamp


def mark_remaining_merchant_tasks_skipped(
    state: dict[str, Any],
    completed_at: datetime,
) -> int:
    """发现 50 蓝票后，将本周期仍到期的奸商任务统一标记为跳过。"""
    skipped_count = 0
    for account_state in state["accounts"].values():
        for system_state in account_state["systems"].values():
            if not task_is_enabled(system_state, MERCHANT_TASK):
                continue
            if not task_is_due(MERCHANT_TASK, system_state, completed_at):
                # 已检测过的 50/70/80/90 结果保持不变。
                continue
            record_task_completion(MERCHANT_TASK, system_state, completed_at)
            set_task_record_result(
                system_state,
                MERCHANT_TASK,
                MERCHANT_SKIPPED_RESULT,
            )
            skipped_count += 1
    return skipped_count


def merchant_task_was_globally_skipped(
    system_state: dict[str, Any],
    now: datetime,
) -> bool:
    """只在写入跳过标记的同一刷新周期跳过；下个周三/周六会重新到期。"""
    return (
        task_record_result(system_state, MERCHANT_TASK)
        == MERCHANT_SKIPPED_RESULT
        and not task_is_due(MERCHANT_TASK, system_state, now)
    )


def _invoke_task_runner(
    task_name: str,
    runner: Callable[..., Any],
    run_index: int,
    run_count: int,
    system_state: dict[str, Any],
    region: str = SAME_REGION,
    *,
    recovery_retry: bool = False,
    completed_battles: int = 0,
    on_battle_completed: Optional[Callable[[int, int], None]] = None,
) -> tuple[bool, Optional[str]]:
    """执行一次任务调用，并统一解释不同任务的返回值。"""
    task_result: Optional[str] = None
    if task_name == COOP_REWARD_TASK:
        raw_result = runner(
            # 普通恢复会回到庭院；无论当前是第几场，恢复后的重试都
            # 必须重新走探索、御魂入口和加成准备流程。
            enable_bonus=run_index == 1 or recovery_retry,
            disable_bonus_after=run_index == run_count,
        )
        raw_value = getattr(raw_result, "value", raw_result)
        if raw_value == COOP_BATTLE_COMPLETED_RECOVERY_REQUIRED:
            task_result = COOP_BATTLE_COMPLETED_RECOVERY_REQUIRED
            success = True
        else:
            success = raw_result is True
    elif task_name == BOUNTY_TASK:
        raw_result = runner()
        task_result = getattr(raw_result, "value", str(raw_result))
        success = task_result in BOUNTY_RESULT_DETAILS
    elif task_name == MERCHANT_TASK:
        raw_result = runner()
        task_result = getattr(raw_result, "value", str(raw_result))
        success = task_result in MERCHANT_RESULT_DETAILS
    elif task_name == HEART_TEAM_TASK:
        raw_result = runner(
            role=heart_team_role(system_state),
            completed_battles=completed_battles,
            on_battle_completed=on_battle_completed,
        )
        raw_value = getattr(raw_result, "value", raw_result)
        if raw_value == HEART_TEAM_BATTLES_COMPLETED_CLEANUP_FAILED:
            # 战斗目标已经完成，不能走普通失败重试，否则会重复打 20/30 场。
            task_result = HEART_TEAM_BATTLES_COMPLETED_CLEANUP_FAILED
            success = True
        else:
            success = raw_result is True
    elif task_name == "liked" and region == CROSS_REGION:
        success = bool(runner(cross_region_only=True))
    else:
        raw_result = runner()
        success = bool(raw_result)
    return success, task_result


def _run_task_recovery(
    recovery: Callable[[Any], Any],
    stop_event: Any,
) -> tuple[bool, str]:
    """调用任务恢复器，并兼容布尔值与带 success/reason 的结果。"""
    try:
        result = recovery(stop_event)
        success = bool(getattr(result, "success", result))
        reason = str(
            getattr(
                result,
                "reason",
                "已恢复到庭院" if success else "未能恢复到庭院",
            )
        )
        return success, reason
    except Exception as exc:
        return False, f"超时恢复发生异常：{exc}"


def _services_from_runtime_settings(
    runtime_settings: Optional[dict[str, Any]],
) -> ControllerServices:
    settings = runtime_settings or {}
    return build_services(
        screenshot_interval=settings.get("screenshot_interval"),
        battle_detection_interval=settings.get("battle_detection_interval"),
        mumu_index=settings.get("mumu_index"),
        adb_port=settings.get("adb_port"),
        adb_path=settings.get("adb_path"),
        mumu_path=settings.get("mumu_path"),
        recovery_retry_count=settings.get("recovery_retry_count", 1),
        recovery_timeout_seconds=settings.get("recovery_timeout_seconds", 90.0),
        recovery_unknown_grace_seconds=settings.get(
            "recovery_unknown_grace_seconds", 10.0
        ),
        timeout_screenshot_keep_count=settings.get(
            "timeout_screenshot_keep_count", 20
        ),
    )


def run_weekly(
    status_path: Path = STATUS_PATH,
    weekly_status_path: Path = WEEKLY_STATUS_PATH,
    services: Optional[ControllerServices] = None,
    now_provider: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    event_callback: Optional[EventCallback] = None,
    stop_event: Any = None,
    runtime_settings: Optional[dict[str, Any]] = None,
) -> bool:
    """执行到期寄售屋周常，并在购买或确认已购买后返回庭院。"""
    try:
        daily_state, daily_migrated = load_state(status_path)
        if daily_migrated:
            save_state(daily_state, status_path)
        weekly_state, weekly_migrated = load_weekly_state(
            weekly_status_path,
            daily_state,
        )
        if weekly_migrated or not Path(weekly_status_path).is_file():
            save_weekly_state(weekly_state, weekly_status_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[ERROR] 无法加载周常状态: {exc}")
        _emit_event(event_callback, "error", phase="load_state", message=str(exc))
        return False

    queue_time = now_provider()
    work_queue = build_weekly_work_queue(daily_state, weekly_state, queue_time)
    _emit_event(
        event_callback,
        "queue_built",
        queue=work_queue,
        created_at=queue_time,
        task_mode=WEEKLY_MODE,
    )
    if not work_queue:
        print("当前没有到期周常任务，无需登录任何账号")
        _emit_event(event_callback, "controller_completed", empty=True)
        return True

    print("待执行周常队列：")
    for index, item in enumerate(work_queue, start=1):
        print(f"  {index}. {item.account_name} / {item.system}: 寄售屋")

    try:
        services = services or _services_from_runtime_settings(runtime_settings)
    except (OSError, ImportError) as exc:
        print(f"[ERROR] 无法加载 Weekly 任务模块: {exc}")
        _emit_event(event_callback, "error", phase="load_modules", message=str(exc))
        return False

    if services.startup_recovery is not None:
        try:
            recovery_result = services.startup_recovery()
            recovery_success = bool(getattr(recovery_result, "success", recovery_result))
            recovery_message = str(
                getattr(recovery_result, "reason", "启动界面恢复失败")
            )
        except Exception as exc:
            recovery_success = False
            recovery_message = f"启动界面恢复发生异常：{exc}"
        if not recovery_success:
            first_item = work_queue[0]
            _emit_event(
                event_callback,
                "error",
                account=first_item.account_name,
                system=first_item.system,
                phase="startup_recovery",
                message=recovery_message,
            )
            return False

    previous_account: Optional[str] = None
    first_login = True
    runner = services.task_runners[CONSIGNMENT_HOUSE_TASK]
    for item in work_queue:
        if stop_event is not None and stop_event.is_set():
            print("周常中控已安全停止")
            _emit_event(event_callback, "controller_stopped")
            return False

        account_name = item.account_name
        system = item.system
        _emit_event(
            event_callback,
            "account_started",
            account=account_name,
            system=system,
            region=SAME_REGION,
            phase="select_account",
        )
        if first_login:
            selected = services.select_account(account_name, False)
        elif previous_account != account_name:
            selected = services.select_account(account_name, True)
        else:
            selected = account_name if services.exit_to_login() else None
        if selected is None:
            message = f"无法选中账号 {account_name}"
            _emit_event(
                event_callback,
                "error",
                account=account_name,
                system=system,
                phase="select_account",
                message=message,
            )
            return False

        _emit_event(
            event_callback,
            "account_phase",
            account=account_name,
            system=system,
            phase="sign_in",
        )
        if not services.sign_in(system, SAME_REGION):
            message = f"{account_name} / {system} / 狐之宴 登录失败"
            _emit_event(
                event_callback,
                "error",
                account=account_name,
                system=system,
                phase="sign_in",
                message=message,
            )
            return False

        _emit_event(
            event_callback,
            "task_started",
            account=account_name,
            system=system,
            region=SAME_REGION,
            task=CONSIGNMENT_HOUSE_TASK,
            run_index=1,
            run_count=1,
        )
        result = CONSIGNMENT_ERROR
        max_attempts = max(1, services.task_recovery_retries + 1)
        for attempt_index in range(1, max_attempts + 1):
            try:
                raw_result = runner()
                result = getattr(raw_result, "value", str(raw_result))
            except Exception as exc:
                result = CONSIGNMENT_ERROR
                failure_message = f"寄售屋执行异常：{exc}"
            else:
                failure_message = "寄售屋执行失败"

            if result in {
                CONSIGNMENT_ALREADY_PURCHASED,
                CONSIGNMENT_PURCHASED,
            }:
                break
            if attempt_index >= max_attempts:
                _emit_event(
                    event_callback,
                    "error",
                    account=account_name,
                    system=system,
                    task=CONSIGNMENT_HOUSE_TASK,
                    phase="task",
                    message=failure_message,
                )
                return False
            if services.task_timeout_recovery is None:
                return False
            recovered, recovery_message = _run_task_recovery(
                services.task_timeout_recovery,
                stop_event,
            )
            if not recovered:
                _emit_event(
                    event_callback,
                    "error",
                    account=account_name,
                    system=system,
                    task=CONSIGNMENT_HOUSE_TASK,
                    phase="task_recovery",
                    message=f"{failure_message}；{recovery_message}",
                )
                return False
            print(f"[INFO] {recovery_message}，重新执行寄售屋")

        completed_at = now_provider().astimezone().isoformat(timespec="seconds")
        record = weekly_task_record(weekly_state, account_name, system)
        record["completed_at"] = completed_at
        record["result"] = result
        save_weekly_state(weekly_state, weekly_status_path)
        detail = (
            "本周购买完成"
            if result == CONSIGNMENT_PURCHASED
            else "本周已购买"
        )
        _emit_event(
            event_callback,
            "task_completed",
            account=account_name,
            system=system,
            region=SAME_REGION,
            task=CONSIGNMENT_HOUSE_TASK,
            timestamp=completed_at,
            detail=detail,
            result=result,
        )
        previous_account = account_name
        first_login = False

    print("\n全部账号与系统的到期周常任务已处理完成")
    _emit_event(event_callback, "controller_completed", empty=False)
    return True


def run(
    status_path: Path = STATUS_PATH,
    services: Optional[ControllerServices] = None,
    now_provider: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    event_callback: Optional[EventCallback] = None,
    stop_event: Any = None,
    runtime_settings: Optional[dict[str, Any]] = None,
    task_mode: str = DAILY_MODE,
    weekly_status_path: Path = WEEKLY_STATUS_PATH,
) -> bool:
    """按 JSON 顺序登录每个账号的每个系统，并执行到期任务。"""
    if task_mode not in VALID_TASK_MODES:
        raise ValueError(f"不支持的任务模式: {task_mode}")
    if task_mode == WEEKLY_MODE:
        return run_weekly(
            status_path=status_path,
            weekly_status_path=weekly_status_path,
            services=services,
            now_provider=now_provider,
            event_callback=event_callback,
            stop_event=stop_event,
            runtime_settings=runtime_settings,
        )
    try:
        state, migrated = load_state(status_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[ERROR] 无法加载账号状态: {exc}")
        _emit_event(event_callback, "error", phase="load_state", message=str(exc))
        return False

    if migrated:
        save_state(state, status_path)
        print("账号状态 JSON 已迁移为 v7 全账号跨区状态结构")

    notification_finished = False

    def try_detection_notification(at: datetime) -> None:
        nonlocal notification_finished
        if notification_finished:
            return
        result = maybe_send_detection_summary(
            state,
            at,
            enabled=bool(
                runtime_settings
                and runtime_settings.get("serverchan_enabled", False)
            ),
        )
        if result.status == "sent":
            print(f"[SUCCESS] {result.message}")
            notification_finished = True
        elif result.status in {"missing_key", "error"}:
            print(f"[WARN] {result.message}")
            notification_finished = True
        elif result.status == "already_sent":
            notification_finished = True

    queue_time = now_provider()
    work_queue = build_work_queue(state, queue_time)
    _emit_event(
        event_callback,
        "queue_built",
        queue=work_queue,
        created_at=queue_time,
    )
    if not work_queue:
        print("当前没有到期任务，无需登录任何账号")
        try_detection_notification(now_provider())
        _emit_event(event_callback, "controller_completed", empty=True)
        return True

    print("待执行队列：")
    for index, item in enumerate(work_queue, start=1):
        task_summary = "、".join(
            TASK_LABELS[task.task_name]
            + (f"×{task.run_count}" if task.run_count > 1 else "")
            for task in item.tasks
        )
        print(
            f"  {index}. {item.account_name} / {item.system} / "
            f"{REGION_LABELS[item.region]}: {task_summary}"
        )

    try:
        screenshot_interval = None
        battle_detection_interval = None
        mumu_index = None
        adb_port = None
        adb_path = None
        mumu_path = None
        recovery_retry_count = 1
        recovery_timeout_seconds = 90.0
        recovery_unknown_grace_seconds = 10.0
        timeout_screenshot_keep_count = 20
        if runtime_settings is not None:
            screenshot_interval = runtime_settings.get("screenshot_interval")
            battle_detection_interval = runtime_settings.get(
                "battle_detection_interval"
            )
            mumu_index = runtime_settings.get("mumu_index")
            adb_port = runtime_settings.get("adb_port")
            adb_path = runtime_settings.get("adb_path")
            mumu_path = runtime_settings.get("mumu_path")
            recovery_retry_count = runtime_settings.get(
                "recovery_retry_count",
                1,
            )
            recovery_timeout_seconds = runtime_settings.get(
                "recovery_timeout_seconds",
                90.0,
            )
            recovery_unknown_grace_seconds = runtime_settings.get(
                "recovery_unknown_grace_seconds",
                10.0,
            )
            timeout_screenshot_keep_count = runtime_settings.get(
                "timeout_screenshot_keep_count",
                20,
            )
        services = services or build_services(
            screenshot_interval=screenshot_interval,
            battle_detection_interval=battle_detection_interval,
            mumu_index=mumu_index,
            adb_port=adb_port,
            adb_path=adb_path,
            mumu_path=mumu_path,
            recovery_retry_count=recovery_retry_count,
            recovery_timeout_seconds=recovery_timeout_seconds,
            recovery_unknown_grace_seconds=recovery_unknown_grace_seconds,
            timeout_screenshot_keep_count=timeout_screenshot_keep_count,
        )
    except (OSError, ImportError) as exc:
        print(f"[ERROR] 无法加载 Daily 任务模块: {exc}")
        _emit_event(event_callback, "error", phase="load_modules", message=str(exc))
        return False

    if services.startup_recovery is not None:
        first_item = work_queue[0]
        try:
            recovery_result = services.startup_recovery()
            recovery_success = bool(
                getattr(recovery_result, "success", recovery_result)
            )
            recovery_message = str(
                getattr(recovery_result, "reason", "启动界面恢复失败")
            )
        except Exception as exc:
            recovery_success = False
            recovery_message = f"启动界面恢复发生异常：{exc}"
        if not recovery_success:
            print(f"[ERROR] {recovery_message}")
            _emit_event(
                event_callback,
                "error",
                account=first_item.account_name,
                system=first_item.system,
                phase="startup_recovery",
                message=recovery_message,
            )
            return False

    previous_account: Optional[str] = None
    first_login = True

    for work_item in work_queue:
        account_name = work_item.account_name
        system = work_item.system
        region = work_item.region
        system_state = state["accounts"][account_name]["systems"][system]
        if stop_event is not None and stop_event.is_set():
            print("Daily 中控已安全停止")
            _emit_event(event_callback, "controller_stopped")
            return False

        active_tasks: list[TaskWork] = []
        for task_work in work_item.tasks:
            if (
                task_work.task_name == MERCHANT_TASK
                and merchant_task_was_globally_skipped(
                    system_state,
                    now_provider(),
                )
            ):
                detail = MERCHANT_RESULT_DETAILS[MERCHANT_SKIPPED_RESULT]
                print(f"{account_name} / {system}: {detail}")
                _emit_event(
                    event_callback,
                    "task_completed",
                    account=account_name,
                    system=system,
                    task=MERCHANT_TASK,
                    timestamp=task_record_time(system_state, MERCHANT_TASK),
                    detail=detail,
                    result=MERCHANT_SKIPPED_RESULT,
                    skipped=True,
                )
                try_detection_notification(now_provider())
                continue
            active_tasks.append(task_work)

        if not active_tasks:
            print(f"\n跳过 {account_name} / {system}：队列内任务均已完成")
            continue

        print(
            f"\n===== {account_name} / {system} / "
            f"{REGION_LABELS[region]} ====="
        )
        _emit_event(
            event_callback,
            "account_started",
            account=account_name,
            system=system,
            region=region,
            phase="select_account",
        )
        if first_login:
            # 中控默认从登录页启动；若该账号已经选中，Switch 不会展开列表。
            selected = services.select_account(account_name, False)
        elif previous_account != account_name:
            selected = services.select_account(account_name, True)
        else:
            # 同一账号的第二系统：退出后沿用当前账号，无需重复选择账号。
            selected = account_name if services.exit_to_login() else None

        if selected is None:
            message = f"无法选中账号 {account_name}"
            print(f"[ERROR] {message}")
            _emit_event(
                event_callback,
                "error",
                account=account_name,
                system=system,
                phase="select_account",
                message=message,
            )
            return False
        _emit_event(
            event_callback,
            "account_phase",
            account=account_name,
            system=system,
            phase="sign_in",
        )
        if not services.sign_in(system, region):
            message = (
                f"{account_name} / {system} / {REGION_LABELS[region]} 登录失败"
            )
            print(f"[ERROR] {message}")
            _emit_event(
                event_callback,
                "error",
                account=account_name,
                system=system,
                region=region,
                phase="sign_in",
                message=message,
            )
            return False

        for task_work in active_tasks:
            task_name = task_work.task_name
            run_count = task_work.run_count
            label = TASK_LABELS[task_name]
            runner = services.task_runners[task_name]
            task_result: Optional[str] = None
            progress_now = now_provider()
            coop_completed_before = 0
            coop_target = 0
            coop_reenter_next = False
            heart_completed_before = 0
            heart_progress_callback: Optional[Callable[[int, int], None]] = None
            if task_name == COOP_REWARD_TASK:
                coop_completed_before, saved_target = battle_progress(
                    system_state,
                    COOP_REWARD_TASK,
                    progress_now,
                )
                coop_target = saved_target or (coop_completed_before + run_count)
                if coop_completed_before:
                    print(
                        f"协战奖励继承当前账号进度 "
                        f"{coop_completed_before}/{coop_target} 场"
                    )
            elif (
                task_name == HEART_TEAM_TASK
                and heart_team_role(system_state) == "leader"
            ):
                heart_completed_before, _ = battle_progress(
                    system_state,
                    HEART_TEAM_TASK,
                    progress_now,
                )

                def save_heart_progress(completed: int, target: int) -> None:
                    nonlocal heart_completed_before
                    heart_completed_before = completed
                    set_battle_progress(
                        system_state,
                        HEART_TEAM_TASK,
                        now_provider(),
                        completed,
                        target,
                    )
                    save_state(state, status_path)
                    print(f"同心队当前账号进度已保存：{completed}/{target} 场")

                heart_progress_callback = save_heart_progress
            for run_index in range(1, run_count + 1):
                if stop_event is not None and stop_event.is_set():
                    print("Daily 中控已安全停止")
                    _emit_event(event_callback, "controller_stopped")
                    return False
                suffix = f"（第 {run_index}/{run_count} 次）" if run_count > 1 else ""
                print(f"执行{label}{suffix}")
                _emit_event(
                    event_callback,
                    "task_started",
                    account=account_name,
                    system=system,
                    region=region,
                    task=task_name,
                    run_index=run_index,
                    run_count=run_count,
                )
                failure_message = ""
                max_attempts = max(1, services.task_recovery_retries + 1)
                for attempt_index in range(1, max_attempts + 1):
                    try:
                        success, attempt_result = _invoke_task_runner(
                            task_name,
                            runner,
                            run_index,
                            run_count,
                            system_state,
                            region,
                            recovery_retry=(
                                attempt_index > 1 or coop_reenter_next
                            ),
                            completed_battles=heart_completed_before,
                            on_battle_completed=heart_progress_callback,
                        )
                        task_result = attempt_result
                        failure_message = f"{label}执行失败"
                    except KeyboardInterrupt:
                        raise
                    except Exception as exc:
                        success = False
                        failure_message = f"{label}发生异常: {exc}"

                    if success:
                        if task_name == COOP_REWARD_TASK:
                            coop_reenter_next = False
                        if task_name == COOP_REWARD_TASK:
                            completed = coop_completed_before + run_index
                            set_battle_progress(
                                system_state,
                                COOP_REWARD_TASK,
                                now_provider(),
                                completed,
                                coop_target,
                            )
                            save_state(state, status_path)
                            print(
                                f"协战奖励当前账号进度已保存："
                                f"{completed}/{coop_target} 场"
                            )

                        if (
                            task_name == COOP_REWARD_TASK
                            and task_result
                            == COOP_BATTLE_COMPLETED_RECOVERY_REQUIRED
                            and run_index < run_count
                        ):
                            cleanup_recovery = (
                                services.task_completion_recoveries.get(
                                    COOP_REWARD_TASK
                                )
                            )
                            if cleanup_recovery is None:
                                print(
                                    "[ERROR] 本场协战已经完成但未配置专属退场恢复"
                                )
                                return False
                            recovered, recovery_message = _run_task_recovery(
                                cleanup_recovery,
                                stop_event,
                            )
                            if not recovered:
                                print(
                                    "[ERROR] 本场协战已经完成并保存进度，但"
                                    f"{recovery_message}"
                                )
                                return False
                            print(
                                f"[SUCCESS] {recovery_message}，"
                                "从庭院继续下一场协战"
                            )
                            coop_reenter_next = True
                            task_result = None

                        if attempt_index > 1:
                            print(
                                f"[SUCCESS] {label}恢复后第 "
                                f"{attempt_index - 1} 次重试成功"
                            )
                            _emit_event(
                                event_callback,
                                "task_retried",
                                account=account_name,
                                system=system,
                                task=task_name,
                                success=True,
                            )
                        break

                    failure_recovery = services.task_failure_recoveries.get(
                        task_name,
                        services.task_timeout_recovery,
                    )
                    can_recover = (
                        attempt_index <= services.task_recovery_retries
                        and failure_recovery is not None
                        and not (
                            stop_event is not None and stop_event.is_set()
                        )
                    )
                    if not can_recover:
                        can_cleanup_before_stop = (
                            failure_recovery is not None
                            and not (
                                stop_event is not None and stop_event.is_set()
                            )
                        )
                        if can_cleanup_before_stop:
                            print(
                                f"[WARN] {label}已无剩余重试次数，"
                                "停止前先恢复到庭院"
                            )
                            recovered, recovery_message = _run_task_recovery(
                                failure_recovery,
                                stop_event,
                            )
                            if recovered:
                                print(
                                    f"[INFO] {recovery_message}；"
                                    f"{label}仍按失败处理，不写入完成时间"
                                )
                            else:
                                failure_message = (
                                    f"{failure_message}；{recovery_message}"
                                )
                        print(f"[ERROR] {failure_message}，不写入完成时间")
                        _emit_event(
                            event_callback,
                            "error",
                            account=account_name,
                            system=system,
                            task=task_name,
                            phase="task",
                            message=failure_message,
                        )
                        return False

                    print(
                        f"[WARN] {failure_message}，开始第 "
                        f"{attempt_index}/{services.task_recovery_retries} 次"
                        "恢复并重试当前任务"
                    )
                    _emit_event(
                        event_callback,
                        "task_recovery_started",
                        account=account_name,
                        system=system,
                        task=task_name,
                        message=failure_message,
                    )
                    recovered, recovery_message = _run_task_recovery(
                        failure_recovery,
                        stop_event,
                    )
                    if not recovered:
                        message = f"{failure_message}；{recovery_message}"
                        print(f"[ERROR] {message}")
                        _emit_event(
                            event_callback,
                            "error",
                            account=account_name,
                            system=system,
                            task=task_name,
                            phase="task_recovery",
                            message=message,
                        )
                        return False
                    print(f"[INFO] {recovery_message}，重新执行{label}")
                    _emit_event(
                        event_callback,
                        "task_recovered",
                        account=account_name,
                        system=system,
                        task=task_name,
                        message=recovery_message,
                    )

            timestamp = record_task_completion(
                task_name,
                system_state,
                now_provider(),
                region=region,
            )
            detail = None
            if task_name == BOUNTY_TASK and task_result is not None:
                set_task_record_result(
                    system_state,
                    BOUNTY_TASK,
                    task_result,
                    region=region,
                )
                detail = combined_bounty_detail(system_state)
            elif task_name == MERCHANT_TASK and task_result is not None:
                set_task_record_result(system_state, MERCHANT_TASK, task_result)
                detail = MERCHANT_RESULT_DETAILS[task_result]
                if task_result == MERCHANT_STOP_RESULT:
                    skipped_count = mark_remaining_merchant_tasks_skipped(
                        state,
                        now_provider(),
                    )
                    if skipped_count:
                        print(
                            f"发现50蓝票，已将后续 {skipped_count} 个"
                            "账号/系统的奸商检测标记为跳过"
                        )
            elif task_name == "liked" and region == CROSS_REGION:
                detail = "跨区好友 ×2 已点赞"
            save_state(state, status_path)
            print(f"{label}完成时间已写入: {timestamp}")
            _emit_event(
                event_callback,
                "task_completed",
                account=account_name,
                system=system,
                region=region,
                task=task_name,
                timestamp=timestamp,
                detail=detail,
                result=(
                    combined_bounty_highlight_result(system_state)
                    if task_name == BOUNTY_TASK
                    else task_result
                ),
            )
            if task_name in {BOUNTY_TASK, MERCHANT_TASK}:
                try_detection_notification(now_provider())

            cleanup_failure = None
            if (
                task_name == HEART_TEAM_TASK
                and task_result
                == HEART_TEAM_BATTLES_COMPLETED_CLEANUP_FAILED
            ):
                cleanup_failure = "同心队战斗场数已经完成，但退出组队流程失败"
            elif (
                task_name == COOP_REWARD_TASK
                and task_result == COOP_BATTLE_COMPLETED_RECOVERY_REQUIRED
            ):
                cleanup_failure = "协战奖励场数已经完成，但奖励领取或退场流程失败"

            if cleanup_failure is not None:
                print(
                    f"[ERROR] {cleanup_failure}；完成时间已经写入，"
                    "不会重复挑战，开始执行任务专属恢复"
                )
                _emit_event(
                    event_callback,
                    "task_recovery_started",
                    account=account_name,
                    system=system,
                    task=task_name,
                    message=cleanup_failure,
                )
                completion_recovery = services.task_completion_recoveries.get(
                    task_name
                )
                if completion_recovery is None:
                    message = f"未配置{label}完成后的专属恢复，停止后续任务"
                    print(f"[ERROR] {message}")
                    _emit_event(
                        event_callback,
                        "error",
                        account=account_name,
                        system=system,
                        task=task_name,
                        phase="task_completion_recovery",
                        message=message,
                    )
                    return False

                recovered, recovery_message = _run_task_recovery(
                    completion_recovery,
                    stop_event,
                )
                if not recovered:
                    message = (
                        f"{cleanup_failure}；{recovery_message}。"
                        "完成时间已保留，但为避免残留界面影响其他任务，"
                        "中控停止继续执行"
                    )
                    print(f"[ERROR] {message}")
                    _emit_event(
                        event_callback,
                        "error",
                        account=account_name,
                        system=system,
                        task=task_name,
                        phase="task_completion_recovery",
                        message=message,
                    )
                    return False

                print(
                    f"[SUCCESS] {recovery_message}，"
                    f"{label}残留已经清理，继续执行后续任务"
                )
                _emit_event(
                    event_callback,
                    "task_recovered",
                    account=account_name,
                    system=system,
                    task=task_name,
                    message=recovery_message,
                )

        previous_account = account_name
        first_login = False

    print("\n全部账号与系统的到期任务已处理完成")
    try_detection_notification(now_provider())
    _emit_event(event_callback, "controller_completed", empty=False)
    return True


if __name__ == "__main__":
    try:
        success = run()
    except KeyboardInterrupt:
        print("Daily 中控已由用户中止")
        success = False
    raise SystemExit(0 if success else 1)

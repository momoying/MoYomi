"""Daily 中控：按 JSON 中的账号、系统顺序登录并执行到期任务。"""

from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from Core.logging import TaskLogger


LOGGER = TaskLogger("中控")
print = LOGGER.legacy_print


HELPER_DIR = Path(__file__).resolve().parent
DAILY_TASKS_DIR = HELPER_DIR / "Daily"
PROJECT_ROOT = HELPER_DIR.parent
STATUS_PATH = HELPER_DIR / "account_status.json"
HEART_TEAM_TASK = "heart_team"
HEART_TEAM_BATTLES_COMPLETED_CLEANUP_FAILED = (
    "battles_completed_cleanup_failed"
)

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
}
DEFAULT_TASK_ENABLED = {
    task_name: task_name != HEART_TEAM_TASK
    for task_name in TASK_ORDER
}

BOUNTY_TASK = "bounty_checked"
MERCHANT_TASK = "merchant_checked"
STATUS_VERSION = 4
TASK_RESULT_FIELDS = {
    BOUNTY_TASK: "bounty_result",
    MERCHANT_TASK: "merchant_result",
}
TASK_TIME_FIELDS = {
    BOUNTY_TASK: "time",
    MERCHANT_TASK: "time",
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


@dataclass
class ControllerServices:
    select_account: Callable[[str, bool], Optional[str]]
    exit_to_login: Callable[[], bool]
    sign_in: Callable[[str], bool]
    task_runners: dict[str, Callable[[], Any]]
    startup_recovery: Optional[Callable[[], Any]] = None
    task_timeout_recovery: Optional[Callable[[Any], Any]] = None
    task_recovery_retries: int = 1
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
    task_modules = {
        key: _load_module(key, MODULE_PATHS[key])
        for key in TASK_ORDER
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
                else module.run
            )
        )
        for key, module in task_modules.items()
    }
    return ControllerServices(
        select_account=lambda account, exit_current: switch_module.select_account(
            account,
            exit_current=exit_current,
        ),
        exit_to_login=switch_module.exit_to_login,
        sign_in=sign_module.run,
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
        task_timeout_recovery=lambda stop_event=None: (
            task_recovery_module.recover_to_courtyard(
                stop_event=stop_event,
                timeout=max(0.1, float(recovery_timeout_seconds)),
                unknown_grace=max(
                    0.1,
                    float(recovery_unknown_grace_seconds),
                ),
                screenshot_keep_count=screenshot_keep_count,
            )
        ),
        task_recovery_retries=max(0, int(recovery_retry_count)),
        task_completion_recoveries={
            HEART_TEAM_TASK: lambda stop_event=None: task_modules[
                HEART_TEAM_TASK
            ].recover_after_completed_battles(
                stop_event=stop_event,
                timeout=max(1.0, float(recovery_timeout_seconds)),
            )
        },
    )


def _empty_system_state() -> dict[str, Any]:
    return {
        "mail_collected": None,
        "liked": None,
        "coop_reward_completed": None,
        "experience_monster_completed": None,
        "one_tap_daily_completed": None,
        "bounty_checked": {
            "time": None,
            "bounty_result": None,
        },
        "merchant_checked": {
            "time": None,
            "merchant_result": None,
        },
        "guild_kirin_completed": None,
        HEART_TEAM_TASK: {
            "role": None,
            "completed_at": None,
        },
        "latest_task_completed_at": None,
        "task_enabled": dict(DEFAULT_TASK_ENABLED),
    }


def _normalize_timestamp(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return None
    return value


def task_record_time(
    system_state: dict[str, Any],
    task_name: str,
) -> Optional[str]:
    """读取任务时间；兼容 v2 的顶层时间字符串。"""
    value = system_state.get(task_name)
    time_field = TASK_TIME_FIELDS.get(task_name)
    if time_field is not None and isinstance(value, dict):
        value = value.get(time_field)
    return _normalize_timestamp(value)


def task_record_result(
    system_state: dict[str, Any],
    task_name: str,
) -> Optional[str]:
    """读取任务结果；兼容 v2 的顶层结果字段。"""
    result_field = TASK_RESULT_FIELDS.get(task_name)
    if result_field is None:
        return None
    record = system_state.get(task_name)
    if isinstance(record, dict):
        return record.get(result_field)
    return system_state.get(result_field)


def set_task_record_result(
    system_state: dict[str, Any],
    task_name: str,
    result: Optional[str],
) -> None:
    """写入聚合任务结果，同时保留该任务已有时间。"""
    result_field = TASK_RESULT_FIELDS[task_name]
    system_state[task_name] = {
        "time": task_record_time(system_state, task_name),
        result_field: result,
    }
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
    system_state[HEART_TEAM_TASK] = {
        "role": normalized_role,
        "completed_at": task_record_time(system_state, HEART_TEAM_TASK),
    }


def _normalize_system_state(raw: Any) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    state = _empty_system_state()
    state[MAIL_TASK] = _normalize_timestamp(raw.get(MAIL_TASK))
    state["liked"] = _normalize_timestamp(raw.get("liked"))
    state["one_tap_daily_completed"] = _normalize_timestamp(
        raw.get("one_tap_daily_completed")
    )
    state[COOP_REWARD_TASK] = _normalize_timestamp(raw.get(COOP_REWARD_TASK))
    state["guild_kirin_completed"] = _normalize_timestamp(
        raw.get("guild_kirin_completed")
    )
    bounty_time = task_record_time(raw, BOUNTY_TASK)
    bounty_result = task_record_result(raw, BOUNTY_TASK)
    if bounty_result == "no_bounty":
        # 悬赏入口恒定存在；旧版把入口漏检误记为成功，必须重新检测。
        bounty_time = None
        bounty_result = None
    if bounty_result == "magatama_collaboration":
        # 兼容旧版未区分“协/享”的状态；无法还原时按普通勾协处理。
        bounty_result = "normal_magatama_collaboration"
    state[BOUNTY_TASK] = {
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
    state[HEART_TEAM_TASK] = {
        "role": heart_team_role(raw),
        "completed_at": task_record_time(raw, HEART_TEAM_TASK),
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
    return state


def load_state(path: Path = STATUS_PATH) -> tuple[dict[str, Any], bool]:
    """加载 v4 状态；兼容旧版扁平任务字段并自动迁移。"""
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


def bounty_is_due(system_state: dict[str, Any], now: datetime) -> bool:
    """悬赏每天 06:00/18:00 重置；只需检查当前最新周期。"""
    if now.tzinfo is None:
        now = now.astimezone()
    checked = _parse_timestamp(task_record_time(system_state, BOUNTY_TASK), now)
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


def guild_kirin_is_due(system_state: dict[str, Any], now: datetime) -> bool:
    """寮麒麟仅周一至周四的 06:00（含）至 23:00（不含）执行一次。"""
    if now.tzinfo is None:
        now = now.astimezone()
    if not task_is_available(GUILD_KIRIN_TASK, now):
        return False
    window_start = now.replace(hour=6, minute=0, second=0, microsecond=0)
    completed = _parse_timestamp(system_state.get(GUILD_KIRIN_TASK), now)
    return completed is None or completed < window_start


def task_is_due(task_name: str, system_state: dict[str, Any], now: datetime) -> bool:
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
        completed = _parse_timestamp(system_state.get("liked"), now)
        return completed is None or completed.date() != now.date()

    if task_name == COOP_REWARD_TASK:
        completed = _parse_timestamp(system_state.get(COOP_REWARD_TASK), now)
        return completed is None or completed.date() != now.date()

    if task_name == MAIL_TASK:
        return mail_is_due(system_state, now)

    if task_name == "experience_monster_completed":
        return experience_runs_due(system_state, now) > 0

    if task_name == BOUNTY_TASK:
        return bounty_is_due(system_state, now)

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
        if completed is None:
            return True
        if role == "member":
            # 一键预存可不限次数连续补充；成员每三天集中补满一次，
            # 减少额外登录和 OCR 时间。
            return (now.date() - completed.date()).days >= 3
        return completed.date() != now.date()

    raise KeyError(f"未知任务: {task_name}")


def task_runs_due(
    task_name: str,
    system_state: dict[str, Any],
    now: datetime,
) -> int:
    """返回任务在当前刷新周期需要执行的次数。"""
    if task_name == "experience_monster_completed":
        return experience_runs_due(system_state, now)
    return 1 if task_is_due(task_name, system_state, now) else 0


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
            run_count = (
                coop_reward_runs
                if task_is_due(COOP_REWARD_TASK, system_state, now)
                else 0
            )
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
            if not tasks:
                continue

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
                continue

            queue.append(WorkItem(account_name, system, tasks))

    # 不改变上方账号/系统的随机遍历顺序。成员在原位置先执行其他任务，
    # 同心队预存统一追加为收尾队列，确保发生在当天队长战斗之后。
    return queue + deferred_member_reserves


def record_task_completion(
    task_name: str,
    system_state: dict[str, Any],
    completed_at: datetime,
) -> str:
    """写入精确到秒的最近完成时间。"""
    timestamp = completed_at.astimezone().isoformat(timespec="seconds")
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
) -> tuple[bool, Optional[str]]:
    """执行一次任务调用，并统一解释不同任务的返回值。"""
    task_result: Optional[str] = None
    if task_name == COOP_REWARD_TASK:
        raw_result = runner(
            enable_bonus=run_index == 1,
            disable_bonus_after=run_index == run_count,
        )
        success = bool(raw_result)
    elif task_name == BOUNTY_TASK:
        raw_result = runner()
        task_result = getattr(raw_result, "value", str(raw_result))
        success = task_result in BOUNTY_RESULT_DETAILS
    elif task_name == MERCHANT_TASK:
        raw_result = runner()
        task_result = getattr(raw_result, "value", str(raw_result))
        success = task_result in MERCHANT_RESULT_DETAILS
    elif task_name == HEART_TEAM_TASK:
        raw_result = runner(role=heart_team_role(system_state))
        raw_value = getattr(raw_result, "value", raw_result)
        if raw_value == HEART_TEAM_BATTLES_COMPLETED_CLEANUP_FAILED:
            # 战斗目标已经完成，不能走普通失败重试，否则会重复打 20/30 场。
            task_result = HEART_TEAM_BATTLES_COMPLETED_CLEANUP_FAILED
            success = True
        else:
            success = raw_result is True
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


def run(
    status_path: Path = STATUS_PATH,
    services: Optional[ControllerServices] = None,
    now_provider: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    event_callback: Optional[EventCallback] = None,
    stop_event: Any = None,
    runtime_settings: Optional[dict[str, Any]] = None,
) -> bool:
    """按 JSON 顺序登录每个账号的每个系统，并执行到期任务。"""
    try:
        state, migrated = load_state(status_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[ERROR] 无法加载账号状态: {exc}")
        _emit_event(event_callback, "error", phase="load_state", message=str(exc))
        return False

    if migrated:
        save_state(state, status_path)
        print("账号状态 JSON 已迁移为 v4 同心队状态结构")

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
        _emit_event(event_callback, "controller_completed", empty=True)
        return True

    print("待执行队列：")
    for index, item in enumerate(work_queue, start=1):
        task_summary = "、".join(
            TASK_LABELS[task.task_name]
            + (f"×{task.run_count}" if task.run_count > 1 else "")
            for task in item.tasks
        )
        print(f"  {index}. {item.account_name} / {item.system}: {task_summary}")

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
                continue
            active_tasks.append(task_work)

        if not active_tasks:
            print(f"\n跳过 {account_name} / {system}：队列内任务均已完成")
            continue

        print(f"\n===== {account_name} / {system} =====")
        _emit_event(
            event_callback,
            "account_started",
            account=account_name,
            system=system,
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
        if not services.sign_in(system):
            message = f"{account_name} / {system} 登录失败"
            print(f"[ERROR] {message}")
            _emit_event(
                event_callback,
                "error",
                account=account_name,
                system=system,
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
                        )
                        if attempt_result is not None:
                            task_result = attempt_result
                        failure_message = f"{label}执行失败"
                    except KeyboardInterrupt:
                        raise
                    except Exception as exc:
                        success = False
                        failure_message = f"{label}发生异常: {exc}"

                    if success:
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

                    can_recover = (
                        attempt_index <= services.task_recovery_retries
                        and services.task_timeout_recovery is not None
                        and not (
                            stop_event is not None and stop_event.is_set()
                        )
                    )
                    if not can_recover:
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
                        services.task_timeout_recovery,
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

            timestamp = record_task_completion(task_name, system_state, now_provider())
            detail = None
            if task_name == BOUNTY_TASK and task_result is not None:
                set_task_record_result(system_state, BOUNTY_TASK, task_result)
                detail = BOUNTY_RESULT_DETAILS[task_result]
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
            save_state(state, status_path)
            print(f"{label}完成时间已写入: {timestamp}")
            _emit_event(
                event_callback,
                "task_completed",
                account=account_name,
                system=system,
                task=task_name,
                timestamp=timestamp,
                detail=detail,
                result=task_result,
            )

            if (
                task_name == HEART_TEAM_TASK
                and task_result
                == HEART_TEAM_BATTLES_COMPLETED_CLEANUP_FAILED
            ):
                cleanup_failure = (
                    "同心队战斗场数已经完成，但退出组队流程失败"
                )
                print(
                    f"[ERROR] {cleanup_failure}；完成时间已经写入，"
                    "不会重新挑战，开始执行战后专属恢复"
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
                    HEART_TEAM_TASK
                )
                if completion_recovery is None:
                    message = "未配置同心队战后专属恢复，停止后续任务"
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
                        "完成时间已保留，但为避免组队状态影响其他任务，"
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
                    "组队残留已经清理，继续执行后续任务"
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
    _emit_event(event_callback, "controller_completed", empty=False)
    return True


if __name__ == "__main__":
    try:
        success = run()
    except KeyboardInterrupt:
        print("Daily 中控已由用户中止")
        success = False
    raise SystemExit(0 if success else 1)

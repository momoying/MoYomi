"""账号任务状态的结构、迁移与原子持久化。"""

from __future__ import annotations

import hashlib
import json
import os
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from controller.constants import *


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


def weekly_task_record(
    weekly_state: dict[str, Any],
    account_name: str,
    system: str,
) -> dict[str, Any]:
    return weekly_state["accounts"][account_name]["systems"][system][
        CONSIGNMENT_HOUSE_TASK
    ]


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

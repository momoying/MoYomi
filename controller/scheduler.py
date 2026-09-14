"""任务可用性、到期规则与运行队列生成。"""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from controller.constants import *
from controller.state_store import *
from controller.state_store import _normalize_timestamp
from controller.types import TaskWork, WorkItem


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

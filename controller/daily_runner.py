"""日常任务调度流程。"""

from __future__ import annotations

import hashlib
import json
import os
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from controller.constants import *
from controller.types import ControllerServices, EventCallback, TaskWork
from controller.runtime import _emit_event, print
from controller.state_store import *
from controller.scheduler import *
from controller.task_services import build_services, _invoke_task_runner, _run_task_recovery
from controller.weekly_runner import run_weekly
from module.diagnostics import capture_error_screenshot
from module.notifications import maybe_send_detection_summary


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
        error_screenshot_keep_count = 20
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
            error_screenshot_keep_count = runtime_settings.get(
                "error_screenshot_keep_count",
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
            error_screenshot_keep_count=error_screenshot_keep_count,
        )
    except (OSError, ImportError) as exc:
        print(f"[ERROR] 无法加载 Daily 任务模块: {exc}")
        _emit_event(event_callback, "error", phase="load_modules", message=str(exc))
        return False

    if services.startup_recovery is not None:
        first_item = work_queue[0]
        recovery_screenshot = None
        try:
            recovery_result = services.startup_recovery()
            recovery_success = bool(
                getattr(recovery_result, "success", recovery_result)
            )
            recovery_screenshot = getattr(recovery_result, "screenshot", None)
            recovery_message = str(
                getattr(recovery_result, "reason", "启动界面恢复失败")
            )
        except Exception as exc:
            recovery_success = False
            recovery_message = f"启动界面恢复发生异常：{exc}"
        if not recovery_success:
            if not recovery_screenshot:
                capture_error_screenshot("startup_recovery", "failed")
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
            if not (stop_event is not None and stop_event.is_set()):
                capture_error_screenshot("account_switch", "select_failed")
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
            if not (stop_event is not None and stop_event.is_set()):
                capture_error_screenshot("account_sign", "login_failed")
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
                    failure_stage = "failed"
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
                        failure_stage = "exception"

                    if not success and not (
                        stop_event is not None and stop_event.is_set()
                    ):
                        capture_error_screenshot(
                            task_name,
                            failure_stage,
                            attempt=attempt_index,
                        )

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

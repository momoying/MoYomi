"""周常任务调度流程。"""

from __future__ import annotations

import hashlib
import json
import os
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from controller.constants import *
from controller.types import ControllerServices, EventCallback
from controller.runtime import _emit_event, print
from controller.state_store import *
from controller.scheduler import build_weekly_work_queue
from controller.task_services import _run_task_recovery, _services_from_runtime_settings


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
        recovery_screenshot = None
        try:
            recovery_result = services.startup_recovery()
            recovery_success = bool(getattr(recovery_result, "success", recovery_result))
            recovery_screenshot = getattr(recovery_result, "screenshot", None)
            recovery_message = str(
                getattr(recovery_result, "reason", "启动界面恢复失败")
            )
        except Exception as exc:
            recovery_success = False
            recovery_message = f"启动界面恢复发生异常：{exc}"
        if not recovery_success:
            first_item = work_queue[0]
            if not recovery_screenshot:
                capture_error_screenshot("startup_recovery", "failed")
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
            if not (stop_event is not None and stop_event.is_set()):
                capture_error_screenshot("account_switch", "select_failed")
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
            if not (stop_event is not None and stop_event.is_set()):
                capture_error_screenshot("account_sign", "login_failed")
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
            failure_stage = "failed"
            try:
                raw_result = runner()
                result = getattr(raw_result, "value", str(raw_result))
            except Exception as exc:
                result = CONSIGNMENT_ERROR
                failure_message = f"寄售屋执行异常：{exc}"
                failure_stage = "exception"
            else:
                failure_message = "寄售屋执行失败"

            if result in {
                CONSIGNMENT_ALREADY_PURCHASED,
                CONSIGNMENT_PURCHASED,
            }:
                break
            if not (stop_event is not None and stop_event.is_set()):
                capture_error_screenshot(
                    CONSIGNMENT_HOUSE_TASK,
                    failure_stage,
                    attempt=attempt_index,
                )
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

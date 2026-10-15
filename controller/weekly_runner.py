"""周常任务调度流程。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from controller.constants import *
from controller.runtime import _emit_event, print
from controller.scheduler import build_weekly_work_queue
from controller.state_store import *
from controller.task_services import (
    _invoke_account_action,
    _services_from_runtime_settings,
)
from controller.types import ControllerServices, EventCallback
from module.diagnostics import capture_error_screenshot
from module.task_execution import run_task_call


def run_weekly(
    status_path: Path = STATUS_PATH,
    weekly_status_path: Path = WEEKLY_STATUS_PATH,
    services: Optional[ControllerServices] = None,
    now_provider: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    event_callback: Optional[EventCallback] = None,
    stop_event: Any = None,
    runtime_settings: Optional[dict[str, Any]] = None,
    single_task_name: Optional[str] = None,
) -> bool:
    """执行到期寄售屋周常，并在购买或确认已购买后返回庭院。"""
    if single_task_name not in (None, CONSIGNMENT_HOUSE_TASK):
        raise ValueError(f"不支持的周常任务: {single_task_name}")
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
            recovery_result, report = run_task_call(services.startup_recovery, stop_event=stop_event, finish_current=True)
            if report.cancelled:
                _emit_event(event_callback, "controller_stopped")
                return False
            if report.exception:
                raise report.exception
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
                frame = getattr(recovery_result, "frame", None) if report.exception is None else report.frame
                if frame is None:
                    frame = report.frame
                capture_error_screenshot("startup_recovery", report.stage or "failed",
                                         **({"frame": frame} if frame is not None else {}))
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
            account_outcome = _invoke_account_action(services.select_account, account_name, False, stop_event=stop_event)
        elif previous_account != account_name:
            account_outcome = _invoke_account_action(services.select_account, account_name, True, stop_event=stop_event)
        else:
            account_outcome = _invoke_account_action(services.exit_to_login, stop_event=stop_event)
        selected = (account_outcome.result or account_name) if account_outcome.completed else None
        if selected is None:
            if account_outcome.failure_kind == "cancelled":
                _emit_event(event_callback, "controller_stopped")
                return False
            message = f"无法选中账号 {account_name}；{account_outcome.stage or '账号切换'}：{account_outcome.reason or '执行失败'}"
            if not (stop_event is not None and stop_event.is_set()):
                capture_error_screenshot("account_switch", account_outcome.stage or "select_failed",
                                         **({"frame": account_outcome.frame} if account_outcome.frame is not None else {}))
            _emit_event(
                event_callback,
                "error",
                account=account_name,
                system=system,
                phase="select_account",
                message=message,
            )
            return False

        if stop_event is not None and stop_event.is_set():
            _emit_event(event_callback, "controller_stopped")
            return False
        _emit_event(
            event_callback,
            "account_phase",
            account=account_name,
            system=system,
            phase="sign_in",
        )
        login_outcome = _invoke_account_action(services.sign_in, system, SAME_REGION, stop_event=stop_event)
        if not login_outcome.completed:
            if login_outcome.failure_kind == "cancelled":
                _emit_event(event_callback, "controller_stopped")
                return False
            message = f"{account_name} / {system} / 狐之宴 登录失败；{login_outcome.stage or '登录'}：{login_outcome.reason or '执行失败'}"
            if not (stop_event is not None and stop_event.is_set()):
                capture_error_screenshot("account_sign", login_outcome.stage or "login_failed",
                                         **({"frame": login_outcome.frame} if login_outcome.frame is not None else {}))
            _emit_event(
                event_callback,
                "error",
                account=account_name,
                system=system,
                phase="sign_in",
                message=message,
            )
            return False

        # 日常与周常复用同一套失败留图、恢复及重试策略。
        from controller.daily_runner import _execute_task

        outcome = _execute_task(
            item.tasks[0], item, daily_state, status_path, services,
            now_provider, event_callback, stop_event,
        )
        if outcome is None:
            return False

        completed_at = now_provider().astimezone().isoformat(timespec="seconds")
        result = outcome.result
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
        if stop_event is not None and stop_event.is_set():
            _emit_event(event_callback, "controller_stopped")
            return False
        previous_account = account_name
        first_login = False

    print("\n全部账号与系统的到期周常任务已处理完成")
    _emit_event(event_callback, "controller_completed", empty=False)
    return True

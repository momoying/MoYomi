"""任务模块加载、运行服务和恢复调用适配。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from controller.constants import *
from controller.state_store import heart_team_role
from controller.types import ControllerServices
from module.diagnostics import capture_error_screenshot, configure_error_screenshots


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
    error_screenshot_keep_count: int = 20,
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
    screenshot_keep_count = max(0, int(error_screenshot_keep_count))
    configure_error_screenshots(screenshot_keep_count)
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
        capture_error_screenshot("task_recovery", "exception")
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
        error_screenshot_keep_count=settings.get(
            "error_screenshot_keep_count", 20
        ),
    )

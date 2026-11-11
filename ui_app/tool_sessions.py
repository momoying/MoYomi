"""超鬼王多实例运行：各线程独立设备与任务状态，共享受锁保护的 OCR。"""

from concurrent.futures import ThreadPoolExecutor

from module import automation
from module.base.device import TaskDevice
from module.diagnostics import ErrorScreenshotManager
from module.logging import TaskLogger
from module.task_execution import ExecutionReport, run_task_call


def run_super_oni_targets(settings, targets, stop_event, load_tool, emit):
    if not 1 <= len(targets) <= 2:
        raise ValueError("请选择一至两个 MuMu 实例")
    if (len({str(item["index"]) for item in targets}) != len(targets)
            or len({item["adb_port"] for item in targets}) != len(targets)):
        raise ValueError("不能重复控制同一个 MuMu 实例")
    def worker(target):
        index = str(target["index"])
        name = f'{target["name"]} · 实例 {index}'
        backend = None
        latest = {"tickets": None, "attempts": 0}
        last_tickets = None
        report = ExecutionReport(stage="初始化实例")
        success = False
        reason = None

        def progress(values):
            nonlocal last_tickets
            latest.update(values)
            tickets = values.get("tickets")
            if tickets is not None and tickets != last_tickets:
                last_tickets = tickets
                emit("super_oni_progress", dict(latest, instance_index=index, instance_name=name, stage="运行中"))
                emit("tool_log", ("INFO", f"{name}：超鬼王票数 {tickets}/50"))

        try:
            backend = automation.create_session()

            def run():
                backend.configure_runtime_paths(str(settings["adb_path"]), str(settings["mumu_path"]))
                if not backend.configure_mumu_target(target["adb_port"], index):
                    raise OSError(f'无法连接 MuMu ADB：{target["adb_port"]}')
                task = load_tool("super_oni")
                task.utils = backend
                task.LOGGER = TaskLogger(f"超鬼王刷票/实例 {index}")
                task.DEVICE = TaskDevice(backend, task.LOGGER)
                task.BATTLE_SCREENSHOT_INTERVAL = float(settings["battle_detection_interval"])
                return task.run(stop_event=stop_event, progress_callback=progress,
                                enable_bonus=target.get("enable_bonus", True))

            result, report = run_task_call(run, stop_event=stop_event)
            success = bool(result) or report.cancelled
            if not success:
                reason = str(report.exception) if report.exception is not None else report.reason or "执行失败"
        except Exception as exc:
            reason = str(exc)
        finally:
            if not success and not stop_event.is_set():
                emit("tool_log", ("ERROR", f"{name}：{reason}"))
                frame = report.frame
                if frame is None and backend is not None:
                    frame = backend.get_last_screenshot()
                if frame is not None:
                    try:
                        ErrorScreenshotManager(
                            backend=backend, keep_count=int(settings["error_screenshot_keep_count"]),
                        ).save(f"super_oni_mumu_{index}", report.stage or "failed", frame=frame)
                    except Exception as exc:
                        emit("tool_log", ("ERROR", f"{name}：保存报错截图失败：{exc}"))
            if backend is not None:
                try:
                    backend.reset_screenshot_backend()
                except Exception as exc:
                    emit("tool_log", ("ERROR", f"{name}：释放截图连接失败：{exc}"))
            stopped = report.cancelled or stop_event.is_set()
            payload = dict(latest, instance_index=index, instance_name=name,
                           success=success, stopped=stopped, reason=reason)
            emit("super_oni_result", payload)
        return payload

    with ThreadPoolExecutor(max_workers=len(targets), thread_name_prefix="super_oni") as pool:
        results = list(pool.map(worker, targets))
    failed = [f'{item["instance_name"]}：{item["reason"]}' for item in results if not item["success"]]
    return {"success": not failed, "stopped": stop_event.is_set(), "tool_name": "super_oni",
            "reason": "；".join(failed) or None}

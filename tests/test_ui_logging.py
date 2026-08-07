from __future__ import annotations

import asyncio
import queue
import unittest

import ui


class _FakePage:
    def __init__(self, *, fail_first_update: bool = False) -> None:
        self.fail_first_update = fail_first_update
        self.update_calls = 0

    def update(self) -> None:
        self.update_calls += 1
        if self.fail_first_update and self.update_calls == 1:
            raise RuntimeError("temporary page failure")


def _dashboard_harness(*, fail_first_update: bool = False):
    dashboard = ui.AssistantDashboard.__new__(ui.AssistantDashboard)
    dashboard.page = _FakePage(fail_first_update=fail_first_update)
    dashboard.ui_queue = queue.Queue()
    dashboard._reported_ui_errors = set()
    dashboard.rendered_logs = []
    dashboard._append_log_now = lambda level, message: dashboard.rendered_logs.append(
        (level, message)
    )
    dashboard._append_tool_log_now = dashboard._append_log_now
    dashboard._apply_worker_finished = lambda **payload: None
    dashboard._apply_tool_finished = lambda **payload: None
    dashboard._apply_secret_attempts = lambda payload: None
    return dashboard


class UiLogPumpTests(unittest.IsolatedAsyncioTestCase):
    async def _run_pump_briefly(self, dashboard, seconds: float = 0.15) -> None:
        task = asyncio.create_task(dashboard._ui_update_pump())
        await asyncio.sleep(seconds)
        task.cancel()
        await task

    async def test_bad_event_does_not_drop_following_log(self) -> None:
        dashboard = _dashboard_harness()

        def fail_event(_payload) -> None:
            raise KeyError("bad controller event")

        dashboard._apply_controller_event = fail_event
        dashboard.ui_queue.put(("controller_event", {"type": "bad"}))
        dashboard.ui_queue.put(("log", ("INFO", "still visible")))

        await self._run_pump_briefly(dashboard)

        self.assertTrue(
            any("UI 事件处理失败" in message for _, message in dashboard.rendered_logs)
        )
        self.assertIn(("INFO", "still visible"), dashboard.rendered_logs)

    async def test_page_update_failure_does_not_stop_pump(self) -> None:
        dashboard = _dashboard_harness(fail_first_update=True)
        dashboard._apply_controller_event = lambda payload: None
        dashboard.ui_queue.put(("log", ("INFO", "first")))

        task = asyncio.create_task(dashboard._ui_update_pump())
        await asyncio.sleep(0.1)
        dashboard.ui_queue.put(("log", ("INFO", "second")))
        await asyncio.sleep(0.1)
        task.cancel()
        await task

        self.assertIn(("INFO", "first"), dashboard.rendered_logs)
        self.assertIn(("INFO", "second"), dashboard.rendered_logs)
        self.assertGreaterEqual(dashboard.page.update_calls, 2)


if __name__ == "__main__":
    unittest.main()

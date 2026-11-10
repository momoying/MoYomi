from __future__ import annotations

import subprocess
import unittest
from unittest.mock import Mock, patch

from module import automation
from module.base.device import TaskDevice


def result(stdout="", stderr="", code=0):
    return subprocess.CompletedProcess([], code, stdout, stderr)


class AdbConnectionTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.multiple(
            automation, adb_path="adb.exe", adb_port="127.0.0.1:16384",
            _adb_connected_key=None,
        ).start()
        self.run = patch.object(automation.subprocess, "run").start()
        self.sleep = patch.object(automation.time, "sleep").start()
        self.output = patch("builtins.print").start()

    def test_ready_device_is_cached_without_disconnect(self):
        self.run.side_effect = [result("connected"), result("device\n")]

        self.assertTrue(automation.connect_to_mumu())
        self.assertTrue(automation.connect_to_mumu())
        self.assertEqual(self.run.call_count, 2)
        self.sleep.assert_not_called()

    def test_already_connected_but_offline_recovers_only_target(self):
        self.run.side_effect = [
            result("already connected"), result(stderr="error: device offline", code=1),
            result("disconnected"), result("connected"), result("device\n"),
        ]

        self.assertTrue(automation.connect_to_mumu())
        self.assertEqual(
            [call.args[0] for call in self.run.call_args_list],
            [
                ["adb.exe", "connect", "127.0.0.1:16384"],
                ["adb.exe", "-s", "127.0.0.1:16384", "get-state"],
                ["adb.exe", "disconnect", "127.0.0.1:16384"],
                ["adb.exe", "connect", "127.0.0.1:16384"],
                ["adb.exe", "-s", "127.0.0.1:16384", "get-state"],
            ],
        )

    def test_persistent_offline_stops_and_invalidates_cached_connection(self):
        automation._adb_connected_key = (automation.adb_path, automation.adb_port)
        offline = result(stderr="error: device offline", code=1)
        self.run.side_effect = [
            result("already connected"), offline, result("disconnected"),
            result("connected"), offline, result("already connected"), offline,
        ]

        self.assertFalse(automation.connect_to_mumu(force=True))
        self.assertIsNone(automation._adb_connected_key)
        self.assertEqual(self.run.call_count, 7)
        self.assertEqual(self.sleep.call_count, 2)
        self.assertIn("device offline", self.output.call_args.args[0])

    def test_unauthorized_device_reports_error_without_retry(self):
        self.run.side_effect = [
            result("connected"), result(stderr="error: device unauthorized", code=1),
        ]

        self.assertFalse(automation.connect_to_mumu())
        self.assertEqual(self.run.call_count, 2)
        self.sleep.assert_not_called()
        self.assertIn("unauthorized", self.output.call_args.args[0])

    def test_connection_timeout_is_bounded_and_reported(self):
        self.run.side_effect = subprocess.TimeoutExpired("adb connect", 8)

        self.assertFalse(automation.connect_to_mumu())
        self.assertEqual(self.run.call_count, 3)
        self.assertIsNone(automation._adb_connected_key)
        self.assertIn("timed out", self.output.call_args.args[0])

    def test_click_still_reconnects_and_retries_by_default(self):
        self.run.side_effect = [result(stderr='device offline', code=1), result()]
        with patch.object(automation, 'connect_to_mumu', return_value=True) as connect:
            self.assertTrue(automation.adb_click(10, 20))
        self.assertEqual(self.run.call_count, 2)
        self.assertEqual(self.run.call_args_list[0].args[0], self.run.call_args_list[1].args[0])
        connect.assert_called_once_with(force=True)

    def test_consuming_click_failure_or_timeout_does_not_resend(self):
        for failure in (result(stderr='device offline', code=1), subprocess.TimeoutExpired('tap', 8)):
            with self.subTest(failure=failure):
                self.run.reset_mock()
                self.run.side_effect = failure if isinstance(failure, Exception) else [failure]
                with patch.object(automation, 'connect_to_mumu') as connect:
                    self.assertFalse(automation.adb_click(10, 20, retry_on_failure=False))
                self.assertEqual(self.run.call_count, 1)
                connect.assert_not_called()
                self.assertIsNone(automation._adb_connected_key)

    def test_consuming_swipe_failure_does_not_resend(self):
        self.run.return_value = result(stderr='device offline', code=1)
        with patch.object(automation, 'connect_to_mumu') as connect:
            self.assertFalse(automation.adb_swipe(10, 20, 30, 40, retry_on_failure=False))
        self.assertEqual(self.run.call_count, 1)
        connect.assert_not_called()

    def test_taskdevice_passes_opt_out_and_preserves_default_backend_calls(self):
        backend = Mock()
        device = TaskDevice(backend)
        device.click(10, 20)
        backend.adb_click.assert_called_once_with(10, 20)
        device.click(30, 40, retry_on_failure=False)
        backend.adb_click.assert_called_with(30, 40, retry_on_failure=False)
        device.swipe(10, 20, 30, 40, retry_on_failure=False)
        backend.adb_swipe.assert_called_once_with(10, 20, 30, 40, duration_ms=800, retry_on_failure=False)


if __name__ == "__main__":
    unittest.main()

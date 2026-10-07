from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from module import automation


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


if __name__ == "__main__":
    unittest.main()

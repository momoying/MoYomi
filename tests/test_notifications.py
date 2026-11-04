"""推送回归：全角色统计、回执不确定状态及相同内容去重；不访问网络。"""

import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from controller import daily_runner, state_store
from controller.constants import BOUNTY_TASK, STATUS_VERSION
from module import notifications as notify


NOW = datetime.fromisoformat("2026-10-30T18:19:00+08:00")


def complete_state():
    accounts = {}
    for index in range(3):
        systems = {}
        for name in ("IOS", "Android"):
            role = state_store._empty_system_state()
            role["cross_region_enabled"] = True
            role["bounty_checked"] = {
                region: {"time": NOW.isoformat(), "bounty_result": "no_magatama_collaboration"}
                for region in ("同区", "跨区")
            }
            systems[name] = role
        accounts[str(index)] = {"systems": systems}
    state = {"version": STATUS_VERSION, "accounts": accounts}
    accounts["0"]["systems"]["IOS"][BOUNTY_TASK]["跨区"]["bounty_result"] = "sharing_magatama_collaboration"
    accounts["2"]["systems"]["Android"][BOUNTY_TASK]["跨区"]["bounty_result"] = "normal_magatama_collaboration"
    return state


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.state = complete_state()
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(directory) / "notification.json"
        self.sender = Mock(return_value={"code": 0})
        self.enterContext(patch.object(notify, "get_serverchan_sendkey", return_value="test-key"))

    def send(self, now=NOW):
        return notify.maybe_send_detection_summary(
            self.state, now, enabled=True, state_path=self.path, sender=self.sender,
        )

    def test_all_twelve_roles_include_both_positive_cross_region_results(self):
        body = notify.build_detection_summary(self.state, NOW)[2]
        for text in ("同区 6 / 跨区 6，合计 12", "普通勾协：1", "现世勾协：1", "无勾协：10"):
            self.assertIn(text, body)

    def test_nine_completed_roles_do_not_produce_an_incomplete_summary(self):
        for account in self.state["accounts"].values():
            account["systems"]["IOS"][BOUNTY_TASK]["跨区"] = {"time": None, "bounty_result": None}
        self.assertEqual(self.send().status, "not_ready")
        self.sender.assert_not_called()

    def test_disabled_cross_region_is_explicit_in_the_total(self):
        for account in self.state["accounts"].values():
            account["systems"]["IOS"]["cross_region_enabled"] = False
        body = notify.build_detection_summary(self.state, NOW)[2]
        self.assertIn("同区 6 / 跨区 3，合计 9", body)

    def test_missing_invalid_old_and_future_results_block_sending(self):
        original = copy.deepcopy(self.state)
        for record in (
            {"time": NOW.isoformat(), "bounty_result": "error"},
            {"time": (NOW - timedelta(hours=1)).isoformat(), "bounty_result": "no_magatama_collaboration"},
            {"time": (NOW + timedelta(minutes=1)).isoformat(), "bounty_result": "no_magatama_collaboration"},
        ):
            with self.subTest(record=record):
                self.state = copy.deepcopy(original)
                self.state["accounts"]["0"]["systems"]["IOS"][BOUNTY_TASK]["跨区"] = record
                self.assertEqual(self.send().status, "not_ready")
        self.sender.assert_not_called()

    def test_success_saves_exact_summary_and_twelve_source_records_and_deduplicates(self):
        self.assertEqual(self.send().status, "sent")
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["last_attempt_status"], "sent")
        self.assertEqual(len(saved["last_attempt_targets"]), 12)
        self.assertEqual(saved["last_attempt_summary"], self.sender.call_args.args[1])
        self.assertEqual(self.send(NOW + timedelta(minutes=1)).status, "already_sent")
        self.sender.assert_called_once()

    def test_same_slot_changed_results_can_send_a_correction(self):
        self.assertEqual(self.send().status, "sent")
        self.state["accounts"]["0"]["systems"]["IOS"][BOUNTY_TASK]["跨区"]["bounty_result"] = "normal_magatama_collaboration"
        self.assertEqual(self.send().status, "sent")
        self.assertEqual(self.send().status, "already_sent")
        self.assertEqual(self.sender.call_count, 2)

    def test_old_sent_slot_format_remains_deduplicated(self):
        self.path.write_text(json.dumps({"last_sent_slot": notify.notification_slot(NOW).isoformat()}))
        self.assertEqual(self.send().status, "already_sent")
        self.sender.assert_not_called()

    def test_unconfirmed_delivery_is_not_marked_sent_or_retried(self):
        self.sender.side_effect = notify.ServerChanDeliveryUnconfirmed("发送结果未确认")
        self.assertEqual(self.send().status, "unconfirmed")
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["last_attempt_status"], "unconfirmed")
        self.assertNotIn("last_sent_slot", saved)
        self.assertEqual(self.send().status, "unconfirmed")
        self.sender.assert_called_once()

    def test_request_is_recorded_before_sending_and_definite_failure_can_retry(self):
        def fail(*args):
            self.assertEqual(json.loads(self.path.read_text())["last_attempt_status"], "sending")
            raise notify.ServerChanError("连接超时")

        self.sender.side_effect = fail
        self.assertEqual(self.send().status, "error")
        self.sender.side_effect = None
        self.assertEqual(self.send().status, "sent")

    def test_pre_send_save_failure_does_not_send(self):
        with patch.object(notify, "_save_delivery_state", side_effect=OSError):
            self.assertEqual(self.send().status, "error")
        self.sender.assert_not_called()

    def test_post_send_save_failure_is_not_reported_as_network_failure(self):
        save = notify._save_delivery_state

        def fail_second(path, data):
            if data["last_attempt_status"] == "sending":
                save(path, data)
            else:
                raise OSError

        with patch.object(notify, "_save_delivery_state", side_effect=fail_second):
            result = self.send()
        self.assertEqual(result.status, "unconfirmed")
        self.assertIn("本地", result.message)
        self.assertEqual(self.send().status, "unconfirmed")
        self.sender.assert_called_once()

    def test_request_exceptions_distinguish_connection_timeout_from_unconfirmed_delivery(self):
        for error, expected in (
            (requests.ConnectTimeout("test-key"), notify.ServerChanError),
            (requests.ReadTimeout("test-key"), notify.ServerChanDeliveryUnconfirmed),
            (requests.ConnectionError("test-key"), notify.ServerChanDeliveryUnconfirmed),
        ):
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(expected) as raised:
                    notify.send_serverchan("test", send_key="test-key", requester=Mock(side_effect=error))
                self.assertNotIn("test-key", str(raised.exception))
                self.assertIs(type(raised.exception), expected)

    def test_success_http_failure_and_unparseable_acknowledgement(self):
        for status, payload, expected in (
            (200, {"code": 0}, None),
            (500, {"message": "failed test-key"}, notify.ServerChanError),
            (200, None, notify.ServerChanDeliveryUnconfirmed),
        ):
            with self.subTest(status=status, payload=payload):
                response = Mock(status_code=status)
                response.json.return_value = payload
                requester = Mock(return_value=response)
                if expected is None:
                    self.assertEqual(notify.send_serverchan("test", requester=requester), payload)
                    self.assertEqual(requester.call_args.kwargs["timeout"], (5.0, 30.0))
                else:
                    with self.assertRaises(expected) as raised:
                        notify.send_serverchan("test", requester=requester)
                    self.assertNotIn("test-key", str(raised.exception))

    def test_controller_reads_persisted_snapshot_and_checks_after_already_sent(self):
        status_path = self.path.with_name("accounts.json")
        state_store.save_state(self.state, status_path)
        services = daily_runner.ControllerServices(
            select_account=lambda *a: True, sign_in=lambda *a: True,
            exit_to_login=lambda: True, task_runners={BOUNTY_TASK: lambda: "no_magatama_collaboration"},
        )
        # 保留两个任务，模拟当前时段曾推送后继续更新结果；每次都应再核对摘要。
        items = [daily_runner.WorkItem(
            "0", "IOS", (daily_runner.TaskWork(BOUNTY_TASK, 1),), region=region,
        ) for region in ("same", "cross")]
        with patch.object(daily_runner, "build_work_queue", return_value=items), patch.object(
            daily_runner, "print",
        ), patch.object(daily_runner, "maybe_send_detection_summary", return_value=notify.NotificationResult(
            "already_sent", "已推送",
        )) as send:
            self.assertTrue(daily_runner.run(
                status_path=status_path, services=services, now_provider=lambda: NOW,
                runtime_settings={"serverchan_enabled": True},
            ))
        self.assertEqual(send.call_count, 3)
        self.assertEqual(send.call_args.args[0], state_store.load_state(status_path)[0])


if __name__ == "__main__":
    unittest.main()

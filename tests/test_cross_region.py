from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import main as controller
from Core import notifications
from Daily.Like import Like
from Sign_A_Switch import Sign


NOW = datetime.fromisoformat("2026-08-07T20:00:00+08:00")


def _raw_v4_state(account_count: int = 6) -> dict:
    return {
        "version": 4,
        "accounts": {
            f"account-{index}": {"systems": {"IOS": {}}}
            for index in range(account_count)
        },
    }


class StateMigrationTests(unittest.TestCase):
    def test_v4_migration_allows_every_account_to_use_system_switch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "account_status.json"
            path.write_text(
                json.dumps(_raw_v4_state(), ensure_ascii=False),
                encoding="utf-8",
            )

            state, migrated = controller.load_state(path)

        self.assertTrue(migrated)
        for account in state["accounts"].values():
            self.assertNotIn("cross_region_available", account)
            system_state = account["systems"]["IOS"]
            self.assertFalse(system_state["cross_region_enabled"])
            self.assertNotIn("cross_region", system_state)
            self.assertEqual(set(system_state["liked"]), {"同区", "跨区"})
            self.assertEqual(
                set(system_state[controller.BOUNTY_TASK]),
                {"同区", "跨区"},
            )

    def test_v5_separate_cross_state_is_merged_into_task_fields(self) -> None:
        same_time = "2026-08-07T18:01:00+08:00"
        cross_time = "2026-08-07T18:02:00+08:00"
        raw = {
            "version": 5,
            "accounts": {
                "account": {
                    "cross_region_available": True,
                    "systems": {
                        "IOS": {
                            "liked": same_time,
                            "bounty_checked": {
                                "time": same_time,
                                "bounty_result": "no_magatama_collaboration",
                            },
                            "cross_region_enabled": True,
                            "cross_region": {
                                "liked": cross_time,
                                "bounty_checked": {
                                    "time": cross_time,
                                    "bounty_result": "normal_magatama_collaboration",
                                },
                            },
                        }
                    },
                }
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "account_status.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            state, migrated = controller.load_state(path)

        system_state = state["accounts"]["account"]["systems"]["IOS"]
        self.assertTrue(migrated)
        self.assertNotIn("cross_region_available", state["accounts"]["account"])
        self.assertNotIn("cross_region", system_state)
        self.assertEqual(system_state["liked"], {"同区": same_time, "跨区": cross_time})
        self.assertEqual(
            controller.task_record_result(
                system_state,
                controller.BOUNTY_TASK,
                controller.CROSS_REGION,
            ),
            "normal_magatama_collaboration",
        )

    def test_cross_region_queue_has_only_fixed_tasks(self) -> None:
        raw = _raw_v4_state(account_count=1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "account_status.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            state, _ = controller.load_state(path)

        system_state = state["accounts"]["account-0"]["systems"]["IOS"]
        system_state["task_enabled"] = {
            task_name: False for task_name in controller.TASK_ORDER
        }
        system_state["cross_region_enabled"] = True

        queue = controller.build_work_queue(
            state,
            NOW,
            shuffle_tasks=lambda _items: None,
            shuffle_accounts=lambda _items: None,
            shuffle_systems=lambda _items: None,
        )

        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0].region, controller.CROSS_REGION)
        self.assertEqual(
            [task.task_name for task in queue[0].tasks],
            ["liked", controller.BOUNTY_TASK],
        )

    def test_account_after_former_first_four_can_enable_cross_region(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "account_status.json"
            path.write_text(json.dumps(_raw_v4_state()), encoding="utf-8")
            state, _ = controller.load_state(path)

        for account in state["accounts"].values():
            system_state = account["systems"]["IOS"]
            system_state["task_enabled"] = {
                task_name: False for task_name in controller.TASK_ORDER
            }
        state["accounts"]["account-5"]["systems"]["IOS"][
            "cross_region_enabled"
        ] = True

        queue = controller.build_work_queue(
            state,
            NOW,
            shuffle_tasks=lambda _items: None,
            shuffle_accounts=lambda _items: None,
            shuffle_systems=lambda _items: None,
        )

        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0].account_name, "account-5")
        self.assertEqual(queue[0].region, controller.CROSS_REGION)

    def test_controller_logs_into_cross_region_and_uses_cross_like_mode(self) -> None:
        raw = _raw_v4_state(account_count=1)
        sign_ins: list[tuple[str, str]] = []
        like_modes: list[bool] = []

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "account_status.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            state, _ = controller.load_state(path)
            system_state = state["accounts"]["account-0"]["systems"]["IOS"]
            system_state["task_enabled"] = {
                task_name: False for task_name in controller.TASK_ORDER
            }
            system_state["cross_region_enabled"] = True
            controller.save_state(state, path)

            def like_runner(*, cross_region_only: bool = False) -> bool:
                like_modes.append(cross_region_only)
                return True

            task_runners = {
                task_name: (lambda: True)
                for task_name in controller.TASK_ORDER
            }
            task_runners["liked"] = like_runner
            task_runners[controller.BOUNTY_TASK] = (
                lambda: "no_magatama_collaboration"
            )
            services = controller.ControllerServices(
                select_account=lambda account, _exit: account,
                exit_to_login=lambda: True,
                sign_in=lambda system, region: sign_ins.append((system, region))
                or True,
                task_runners=task_runners,
                task_recovery_retries=0,
            )

            success = controller.run(
                status_path=path,
                services=services,
                now_provider=lambda: NOW,
            )
            saved, _ = controller.load_state(path)

        self.assertTrue(success)
        self.assertEqual(sign_ins, [("IOS", controller.CROSS_REGION)])
        self.assertEqual(like_modes, [True])
        saved_system = saved["accounts"]["account-0"]["systems"]["IOS"]
        self.assertIsNotNone(saved_system["liked"]["跨区"])
        self.assertEqual(
            controller.task_record_result(
                saved_system,
                controller.BOUNTY_TASK,
                controller.CROSS_REGION,
            ),
            "no_magatama_collaboration",
        )


class BountySummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = controller._empty_system_state()
        self.state["cross_region_enabled"] = True

    def _set_results(self, same: str, cross: str) -> None:
        controller.set_task_record_result(
            self.state,
            controller.BOUNTY_TASK,
            same,
            region=controller.SAME_REGION,
        )
        controller.set_task_record_result(
            self.state,
            controller.BOUNTY_TASK,
            cross,
            region=controller.CROSS_REGION,
        )

    def test_same_result_is_summarized_as_both(self) -> None:
        self._set_results(
            "normal_magatama_collaboration",
            "normal_magatama_collaboration",
        )
        self.assertEqual(controller.combined_bounty_detail(self.state), "普勾（双）")

    def test_mixed_results_keep_zone_labels_and_sharing_highlight(self) -> None:
        self._set_results(
            "normal_magatama_collaboration",
            "sharing_magatama_collaboration",
        )
        self.assertEqual(
            controller.combined_bounty_detail(self.state),
            "普勾（同） · 现世勾（跨）",
        )
        self.assertEqual(
            controller.combined_bounty_highlight_result(self.state),
            "sharing_magatama_collaboration",
        )

    def test_no_collaboration_in_both_regions_is_compact(self) -> None:
        self._set_results(
            "no_magatama_collaboration",
            "no_magatama_collaboration",
        )
        self.assertEqual(controller.combined_bounty_detail(self.state), "无勾协")

    def test_disabled_same_region_does_not_leak_stale_result(self) -> None:
        self._set_results(
            "sharing_magatama_collaboration",
            "normal_magatama_collaboration",
        )
        self.state["task_enabled"][controller.BOUNTY_TASK] = False

        self.assertEqual(controller.combined_bounty_detail(self.state), "普勾（跨）")
        self.assertEqual(
            controller.combined_bounty_highlight_result(self.state),
            "normal_magatama_collaboration",
        )

    def test_detection_notification_counts_enabled_cross_region(self) -> None:
        checked = NOW.isoformat(timespec="seconds")
        self.state["task_enabled"][controller.MERCHANT_TASK] = False
        self.state[controller.BOUNTY_TASK] = {
            "同区": {
                "time": checked,
                "bounty_result": "no_magatama_collaboration",
            },
            "跨区": {
                "time": checked,
                "bounty_result": "normal_magatama_collaboration",
            },
        }
        state = {
            "accounts": {
                "account": {
                    "systems": {"IOS": self.state},
                }
            }
        }

        summary = notifications.build_detection_summary(state, NOW)

        self.assertIsNotNone(summary)
        body = summary[2]
        self.assertIn(
            f"{notifications.BOUNTY_RESULTS['normal_magatama_collaboration']}：1",
            body,
        )
        self.assertIn(
            f"{notifications.BOUNTY_RESULTS['no_magatama_collaboration']}：1",
            body,
        )


class RegionLoginTests(unittest.TestCase):
    def test_region_card_ocr_uses_name_only_crops(self) -> None:
        seen_regions = []

        def fake_ocr(_frame, region):
            seen_regions.append(region)
            if region == Sign.REGION_CARD_NAME_OCR_REGIONS["left"]:
                return [("砂狐乐园", 0.99)]
            return [("狐之宴", 0.98)]

        with (
            patch.object(Sign, "_ocr_texts_in_region", side_effect=fake_ocr),
            patch.object(Sign.LOGGER, "match"),
        ):
            card_regions, card_texts = Sign._recognize_region_cards(object())

        self.assertEqual(card_regions, {"left": "cross", "right": "same"})
        self.assertEqual(card_texts["left"], ["砂狐乐园"])
        self.assertEqual(card_texts["right"], ["狐之宴"])
        self.assertEqual(
            seen_regions,
            list(Sign.REGION_CARD_NAME_OCR_REGIONS.values()),
        )
        for left, top, right, bottom in seen_regions:
            self.assertLessEqual(bottom - top, 36)
            self.assertLessEqual(right - left, 145)

    def test_switch_to_same_region_clicks_ocr_selected_right_card(self) -> None:
        frames = iter(["old-region", "selector", "new-region"])
        clicks: list[tuple[tuple[int, int, int, int], str]] = []

        def fake_match(frame, name):
            if frame == "selector" and name == "region_selection":
                return 0.99, (500, 40, 670, 84)
            return None, None

        def fake_region(frame):
            if frame == "old-region":
                return "cross", ["砂狐乐园"]
            if frame == "new-region":
                return "same", ["狐之宴"]
            return None, []

        with (
            patch.object(Sign, "_take_frame", side_effect=lambda: next(frames)),
            patch.object(Sign, "_match", side_effect=fake_match),
            patch.object(Sign, "_recognize_current_region", side_effect=fake_region),
            patch.object(
                Sign,
                "_recognize_region_cards",
                return_value=(
                    {"left": "cross", "right": "same"},
                    {"left": ["砂狐乐园"], "right": ["狐之宴"]},
                ),
            ),
            patch.object(
                Sign,
                "_click_region",
                side_effect=lambda rect, label: clicks.append((rect, label)),
            ),
            patch.object(Sign.time, "sleep", return_value=None),
        ):
            success = Sign._ensure_region("ios", "same", timeout=5.0)

        self.assertTrue(success)
        self.assertEqual(clicks[0][0], Sign.REGION_SWITCH_CLICK_REGION)
        self.assertEqual(
            clicks[1][0],
            Sign.REGION_CARD_CLICK_REGIONS["right"],
        )

    def test_switch_to_cross_region_clicks_ocr_selected_left_card(self) -> None:
        frames = iter(["old-region", "selector", "new-region"])
        clicks: list[tuple[tuple[int, int, int, int], str]] = []

        def fake_match(frame, name):
            if frame == "selector" and name == "region_selection":
                return 0.99, (500, 40, 670, 84)
            return None, None

        def fake_region(frame):
            if frame == "old-region":
                return "same", ["狐之宴"]
            if frame == "new-region":
                return "cross", ["砂狐乐园"]
            return None, []

        with (
            patch.object(Sign, "_take_frame", side_effect=lambda: next(frames)),
            patch.object(Sign, "_match", side_effect=fake_match),
            patch.object(Sign, "_recognize_current_region", side_effect=fake_region),
            patch.object(
                Sign,
                "_recognize_region_cards",
                return_value=(
                    {"left": "cross", "right": "same"},
                    {"left": ["砂狐乐园"], "right": ["狐之宴"]},
                ),
            ),
            patch.object(
                Sign,
                "_click_region",
                side_effect=lambda rect, label: clicks.append((rect, label)),
            ),
            patch.object(Sign.time, "sleep", return_value=None),
        ):
            success = Sign._ensure_region("ios", "cross", timeout=5.0)

        self.assertTrue(success)
        self.assertEqual(clicks[0][0], Sign.REGION_SWITCH_CLICK_REGION)
        self.assertEqual(
            clicks[1][0],
            Sign.REGION_CARD_CLICK_REGIONS["left"],
        )


class LikeModeTests(unittest.TestCase):
    def test_cross_region_only_mode_skips_normal_friend(self) -> None:
        with (
            patch.object(Like.utils, "connect_to_mumu"),
            patch.object(Like, "_ensure_friend_menu_expanded", return_value=True),
            patch.object(Like, "_wait_and_click", return_value=True),
            patch.object(Like, "_wait_for_active_category", return_value="friend"),
            patch.object(Like, "_switch_category", return_value=True) as switch,
            patch.object(Like, "_like_cross_region_friends", return_value=True) as cross,
            patch.object(Like, "_like_current_category", return_value=True) as normal,
            patch.object(Like, "_wait_for_main", return_value=True),
        ):
            success = Like.run(cross_region_only=True)

        self.assertTrue(success)
        switch.assert_called_once_with("cross_region")
        cross.assert_called_once_with()
        normal.assert_not_called()


if __name__ == "__main__":
    unittest.main()

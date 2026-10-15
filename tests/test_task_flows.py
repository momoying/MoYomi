"""任务编排回归：使用替身验证阶段顺序和恢复状态，不连接模拟器。"""

import unittest
from contextlib import ExitStack
from unittest.mock import Mock, call, patch

from tasks.CoopReward import coop_reward as coop
from tasks.GuildKirin import guild_kirin as kirin
from tasks.HeartTeam import heart_team as heart


class TaskFlowTests(unittest.TestCase):
    def stub(self, module, **results):
        stack = self.enterContext(ExitStack())
        stack.enter_context(patch.object(module.utils, "connect_to_mumu"))
        stack.enter_context(patch.object(module, "print"))
        return {
            name: stack.enter_context(patch.object(module, name, return_value=result))
            for name, result in results.items()
        }

    def test_member_reserve_warns_at_200_or_more_but_fails_below_200(self):
        warning = Mock()
        with patch.object(heart, "_wait_and_click", return_value=True), patch.object(
            heart,
            "_wait_for_reserved_stamina",
            side_effect=[(320, 400), (320, 400)],
        ), patch.object(
            heart, "_return_member_to_courtyard", return_value=True
        ), patch.object(heart, "print"):
            self.assertTrue(heart._run_member_reserve(on_warning=warning))
        warning.assert_called_once()
        self.assertIn("320/400", warning.call_args.args[0])

        warning.reset_mock()
        with patch.object(heart, "_wait_and_click", return_value=True), patch.object(
            heart,
            "_wait_for_reserved_stamina",
            side_effect=[(320, 400), (199, 400)],
        ), patch.object(
            heart, "_return_member_to_courtyard", return_value=True
        ), patch.object(heart, "print"):
            self.assertFalse(heart._run_member_reserve(on_warning=warning))
        warning.assert_not_called()

    def test_coop_preparation_stops_at_first_failed_step(self):
        # 每个准备步骤都可能失败；失败后不可继续点击或开启加成。
        expected = ["main", "soul_entry", "dungeon_card", "floor", "formation", "bonus"]
        for failed_step in [None, *expected]:
            with self.subTest(failed_step=failed_step):
                seen = []

                def step(name):
                    seen.append(name)
                    return name != failed_step

                with ExitStack() as stack:
                    stack.enter_context(patch.object(
                        coop, "_wait_and_click", side_effect=lambda name, *a, **k: step(name),
                    ))
                    for helper, name in [
                        ("_ensure_floor10_active", "floor"),
                        ("_ensure_formation_locked", "formation"),
                        ("_enable_soul_bonus", "bonus"),
                    ]:
                        stack.enter_context(patch.object(
                            coop, helper, side_effect=lambda name=name: step(name),
                        ))
                    self.assertEqual(coop._prepare_soul_dungeon(), failed_step is None)
                limit = len(expected) if failed_step is None else expected.index(failed_step) + 1
                self.assertEqual(seen, expected[:limit])

    def test_coop_continuation_skips_preparation_and_cleanup(self):
        mocks = self.stub(
            coop, _prepare_soul_dungeon=True, _wait_and_click=True,
            collect_battle_rewards=True, _disable_soul_bonus=True, _return_to_courtyard=True,
        )
        self.assertIs(coop.run(enable_bonus=False), True)
        mocks["_prepare_soul_dungeon"].assert_not_called()
        mocks["collect_battle_rewards"].assert_called_once_with()
        mocks["_disable_soul_bonus"].assert_not_called()
        mocks["_return_to_courtyard"].assert_not_called()

    def test_coop_completed_battle_preserves_recovery_result(self):
        mocks = self.stub(
            coop, _prepare_soul_dungeon=True, _wait_and_click=True,
            collect_battle_rewards=coop.BATTLE_COMPLETED_RECOVERY_REQUIRED,
            _disable_soul_bonus=True, _return_to_courtyard=True,
        )
        self.assertEqual(coop.run(disable_bonus_after=True), coop.BATTLE_COMPLETED_RECOVERY_REQUIRED)
        mocks["_disable_soul_bonus"].assert_not_called()
        mocks["_return_to_courtyard"].assert_not_called()

    def test_heart_member_does_not_create_team_or_battle(self):
        mocks = self.stub(
            heart, _cleanup_stale_gathering_before_start=True,
            _ensure_team_menu_expanded=True, _wait_and_click=True,
            _run_member_reserve=True, _prepare_leader_team=True, _run_battles=True,
        )
        self.assertIs(heart.run(role="member"), True)
        mocks["_run_member_reserve"].assert_called_once_with()
        mocks["_prepare_leader_team"].assert_not_called()
        mocks["_run_battles"].assert_not_called()

    def test_heart_leader_keeps_progress_when_cleanup_fails(self):
        mocks = self.stub(
            heart, _cleanup_stale_gathering_before_start=True,
            _ensure_team_menu_expanded=True, _wait_and_click=True,
            _confirm_members_and_select_dungeon=True, _configure_and_create_team=True,
            _run_battles=True, _leave_team_to_courtyard=False,
        )
        callback = Mock()
        self.assertEqual(
            heart.run(completed_battles=7, on_battle_completed=callback),
            heart.BATTLES_COMPLETED_CLEANUP_FAILED,
        )
        mocks["_run_battles"].assert_called_once_with(
            completed_battles=7, on_battle_completed=callback,
        )
        self.assertEqual(mocks["_wait_and_click"].call_args.args[0], "rally")
        self.assertFalse(mocks["_wait_and_click"].call_args.kwargs["confirm_disappears"])

    def test_heart_formation_is_checked_once_before_first_battle(self):
        with ExitStack() as stack:
            ensure_locked = stack.enter_context(
                patch.object(heart, "_ensure_formation_locked", return_value=True)
            )
            stack.enter_context(patch.object(heart, "battle_target_count", return_value=3))
            stack.enter_context(patch.object(heart, "print"))
            stack.enter_context(patch.object(heart, "_wait_and_click", return_value=True))
            stack.enter_context(patch.object(heart, "collect_battle_rewards", return_value=True))
            stack.enter_context(patch.object(heart, "_wait_for_template", return_value=True))

            self.assertIs(heart._run_battles(), True)

        ensure_locked.assert_called_once_with()

    def test_heart_unlocked_formation_is_clicked_once_and_verified(self):
        matches = iter([
            (0.20, None), (0.80, (28, 648, 56, 680)),
            (0.91, (28, 648, 56, 680)), (0.18, None),
        ])
        with ExitStack() as stack:
            stack.enter_context(patch.object(heart, "_take_frame", side_effect=[object(), object()]))
            stack.enter_context(patch.object(heart, "_match", side_effect=lambda *_: next(matches)))
            click = stack.enter_context(patch.object(heart, "_click_rect"))
            stack.enter_context(patch.object(heart.time, "sleep"))
            stack.enter_context(patch.object(heart, "print"))

            self.assertTrue(heart._ensure_formation_locked())

        click.assert_called_once_with((28, 648, 56, 680), "锁定阵容")

    def test_heart_lock_timeout_stops_before_next_match_or_click(self):
        for expires_during in ("screenshot", "formation_locked", "formation_unlocked", "click_log"):
            with self.subTest(expires_during=expires_during), ExitStack() as stack:
                clock = [0.0]

                def expire(phase):
                    if phase == expires_during:
                        clock[0] = heart.FORMATION_WAIT_SECONDS

                def screenshot(**kwargs):
                    expire("screenshot")
                    return object()

                def match(frame, name):
                    expire(name)
                    return (0.2, None) if name == "formation_locked" else (0.8, (28, 648, 56, 680))

                def log(message):
                    if message == "阵容尚未上锁，点击锁定":
                        expire("click_log")

                stack.enter_context(patch.object(heart.time, "monotonic", side_effect=lambda: clock[0]))
                stack.enter_context(patch.object(heart, "_take_frame", side_effect=screenshot))
                matcher = stack.enter_context(patch.object(heart, "_match", side_effect=match))
                click = stack.enter_context(patch.object(heart, "_click_rect"))
                sleep = stack.enter_context(patch.object(heart.time, "sleep"))
                stack.enter_context(patch.object(heart, "print", side_effect=log))

                self.assertFalse(heart._ensure_formation_locked())

                click.assert_not_called()
                sleep.assert_not_called()
                self.assertEqual(matcher.call_count, {
                    "screenshot": 0, "formation_locked": 1,
                    "formation_unlocked": 2, "click_log": 2,
                }[expires_during])

    def test_heart_lock_wait_uses_only_remaining_time(self):
        clock = [0.0]

        def screenshot(**kwargs):
            clock[0] = heart.FORMATION_WAIT_SECONDS - 0.1
            return object()

        with ExitStack() as stack:
            stack.enter_context(patch.object(heart.time, "monotonic", side_effect=lambda: clock[0]))
            capture = stack.enter_context(patch.object(heart, "_take_frame", side_effect=screenshot))
            stack.enter_context(patch.object(heart, "_match", return_value=(0.2, None)))
            sleep = stack.enter_context(patch.object(
                heart.time, "sleep", side_effect=lambda delay: clock.__setitem__(0, clock[0] + delay),
            ))
            click = stack.enter_context(patch.object(heart, "_click_rect"))
            stack.enter_context(patch.object(heart, "print"))

            self.assertFalse(heart._ensure_formation_locked())

        capture.assert_called_once_with(deadline=heart.FORMATION_WAIT_SECONDS)
        sleep.assert_called_once()
        self.assertAlmostEqual(sleep.call_args.args[0], 0.1)
        click.assert_not_called()

    def test_heart_formation_match_reads_asset_without_stale_name_maps(self):
        frame = object()
        with ExitStack() as stack:
            stack.enter_context(patch.object(heart, "REGIONS", {}))
            stack.enter_context(patch.object(heart, "TEMPLATES", {}))
            device_match = stack.enter_context(
                patch.object(heart.DEVICE, "match", return_value=(0.91, (28, 648, 56, 680)))
            )
            stack.enter_context(patch.object(heart.LOGGER, "match"))

            self.assertEqual(
                heart._match(frame, "formation_locked"),
                (0.91, (28, 648, 56, 680)),
            )

        device_match.assert_called_once_with(
            (15, 625),
            (75, 710),
            heart.ASSETS.I_FORMATION_LOCKED.path,
            frame=frame,
        )

    def test_heart_resume_skips_formation_check_after_completed_battles(self):
        with ExitStack() as stack:
            ensure_locked = stack.enter_context(
                patch.object(heart, "_ensure_formation_locked")
            )
            stack.enter_context(patch.object(heart, "battle_target_count", return_value=2))
            stack.enter_context(patch.object(heart, "print"))
            stack.enter_context(patch.object(heart, "_wait_and_click", return_value=True))
            stack.enter_context(patch.object(heart, "collect_battle_rewards", return_value=True))
            stack.enter_context(patch.object(heart, "_wait_for_template", return_value=True))

            self.assertIs(heart._run_battles(completed_battles=1), True)

        ensure_locked.assert_not_called()

    def test_kirin_already_challenged_skips_battle(self):
        mocks = self.stub(
            kirin, _ensure_guild_menu_expanded=True, _wait_and_click=True,
            _wait_for_hunting_status="already_challenged",
            _challenge_and_confirm_completion=True, _return_to_main=True,
        )
        events = Mock()
        events.attach_mock(mocks["_wait_and_click"], "click")
        events.attach_mock(mocks["_wait_for_hunting_status"], "status")
        with patch.object(kirin.time, "sleep") as sleep:
            events.attach_mock(sleep, "sleep")
            self.assertIs(kirin.run(), True)
        self.assertEqual(events.mock_calls, [
            call.click("guild_entry", "阴阳寮", kirin.PAGE_WAIT_SECONDS),
            call.click("hunting_entry", "狩猎战", kirin.PAGE_WAIT_SECONDS),
            call.sleep(1.0),
            call.status(),
        ])
        mocks["_challenge_and_confirm_completion"].assert_not_called()
        mocks["_return_to_main"].assert_called_once_with()

    def test_kirin_requires_completion_flag_after_settlement(self):
        mocks = self.stub(
            kirin, _wait_and_click=True, _wait_for_battle_result=("victory", (1, 2, 3, 4)),
            _close_battle_result=True, _confirm_completed_hunting_status=False,
        )
        self.assertIs(kirin._challenge_and_confirm_completion(), False)
        mocks["_close_battle_result"].assert_called_once_with("victory", (1, 2, 3, 4))
        mocks["_confirm_completed_hunting_status"].return_value = True
        self.assertIs(kirin._challenge_and_confirm_completion(), True)

    def test_kirin_completion_waits_one_second_then_checks_fresh_frame(self):
        frame = object()
        settled_frame = object()
        matches = [(0.91, (1, 2, 3, 4)), (0.94, (5, 6, 7, 8))]
        with ExitStack() as stack:
            capture = stack.enter_context(patch.object(
                kirin, "_take_frame", side_effect=[frame, settled_frame],
            ))
            sleep = stack.enter_context(patch.object(kirin.time, "sleep"))
            match = stack.enter_context(patch.object(kirin, "_match", side_effect=matches))
            stack.enter_context(patch.object(kirin, "print"))
            events = Mock()
            events.attach_mock(capture, "capture")
            events.attach_mock(sleep, "sleep")
            events.attach_mock(match, "match")

            self.assertIs(kirin._confirm_completed_hunting_status(), True)

        self.assertEqual(
            events.mock_calls,
            [call.capture(), call.match(frame, "hunt_back"), call.sleep(1.0),
             call.capture(), call.match(settled_frame, "already_challenged")],
        )

    def test_kirin_completion_times_out_waiting_for_normal_page(self):
        frame = object()
        with ExitStack() as stack:
            stack.enter_context(patch.object(kirin, "_take_frame", return_value=frame))
            match = stack.enter_context(patch.object(kirin, "_match", return_value=(0.71, None)))
            stack.enter_context(patch.object(kirin.time, "monotonic", side_effect=[0, 0, kirin.PAGE_WAIT_SECONDS + 1]))
            log = stack.enter_context(patch.object(kirin, "print"))

            self.assertIs(kirin._confirm_completed_hunting_status(), False)

        match.assert_called_once_with(frame, "hunt_back")
        self.assertIn("未等到狩猎战正常界面", log.call_args.args[0])

    def test_kirin_completion_reports_missing_flag_after_normal_page(self):
        frame = object()
        with ExitStack() as stack:
            stack.enter_context(patch.object(kirin.time, "sleep"))
            stack.enter_context(patch.object(kirin, "_take_frame", return_value=frame))
            match = stack.enter_context(patch.object(
                kirin, "_match", side_effect=[(0.91, (1, 2, 3, 4)), (0.77, None)],
            ))
            log = stack.enter_context(patch.object(kirin, "print"))

            self.assertIs(kirin._confirm_completed_hunting_status(), False)

        self.assertEqual(match.call_count, 2)
        self.assertIn("正常界面，但未识别到已挑战标志", log.call_args.args[0])


if __name__ == "__main__":
    unittest.main()

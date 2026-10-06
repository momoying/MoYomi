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

    def test_kirin_already_challenged_skips_battle(self):
        mocks = self.stub(
            kirin, _ensure_guild_menu_expanded=True, _wait_and_click=True,
            _wait_for_hunting_status="already_challenged",
            _challenge_and_confirm_completion=True, _return_to_main=True,
        )
        self.assertIs(kirin.run(), True)
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

    def test_kirin_completion_waits_for_normal_page_then_checks_same_frame(self):
        frame = object()
        matches = [(0.91, (1, 2, 3, 4)), (0.94, (5, 6, 7, 8))]
        with ExitStack() as stack:
            stack.enter_context(patch.object(kirin, "_take_frame", return_value=frame))
            match = stack.enter_context(patch.object(kirin, "_match", side_effect=matches))
            stack.enter_context(patch.object(kirin, "print"))

            self.assertIs(kirin._confirm_completed_hunting_status(), True)

        self.assertEqual(
            [call.args for call in match.call_args_list],
            [(frame, "hunt_back"), (frame, "already_challenged")],
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

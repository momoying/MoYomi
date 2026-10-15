"""共享动作预算和准备按钮次数上限；不连接模拟器。"""

import importlib
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, call, patch

from module import automation
from tasks.SecretBattle import secret_battle as secret
from tasks.StorySkip import story_skip as story
from tasks.Exp import exp_monster as exp
from tasks.Mail import mail
from tasks.ConsignmentHouse import consignment_house as consignment
from tasks.OneTapDaily import one_tap_daily as daily


RECT = (10, 20, 40, 50)


class TaskTimeoutTests(unittest.TestCase):
    def test_search_and_click_share_budget_and_never_click_after_expiry(self):
        modules = [
            "Account.sign", "Account.switch", "Exp.exp_monster",
            "OneTapDaily.one_tap_daily", "Like.like", "CoopReward.coop_reward",
            "Merchant.merchant", "Bounty.bounty", "GuildKirin.guild_kirin",
        ]
        for path in modules:
            module = importlib.import_module(f"tasks.{path}")
            for elapsed in (0.8, 1.1):
                with self.subTest(task=path, elapsed=elapsed), ExitStack() as stack:
                    clock = [0.0]
                    stack.enter_context(patch.object(module.time, "monotonic", side_effect=lambda: clock[0]))
                    stack.enter_context(patch.object(module, "print"))
                    if hasattr(module, "_report_timeout"):
                        stack.enter_context(patch.object(module, "_report_timeout"))
                    name = next(iter(module.REGIONS))

                    def find(*args):
                        clock[0] = elapsed
                        if path.startswith(("Merchant", "Bounty")):
                            return object(), RECT, 0.95
                        if path.startswith("GuildKirin"):
                            return object(), name, RECT, 0.95
                        return 0.95, RECT

                    finder = "_match"
                    if path.startswith(("Merchant", "Bounty")):
                        finder = "_wait_for_template"
                    elif path.startswith("GuildKirin"):
                        finder = "_wait_for_any"
                    stack.enter_context(patch.object(module, finder, side_effect=find))
                    stack.enter_context(patch.object(module, "_take_frame", return_value=object()))
                    click = stack.enter_context(patch.object(module, "_click_and_confirm", return_value=True))
                    kwargs = {"max_attempts": 3} if path.startswith("CoopReward") else {}
                    self.assertEqual(module._wait_and_click(name, "测试按钮", 1.0, **kwargs), elapsed < 1.0)
                    if elapsed < 1.0:
                        self.assertAlmostEqual(click.call_args.args[3], 0.2)
                    else:
                        click.assert_not_called()

    def test_exp_preclick_delay_consumes_remaining_budget(self):
        clock = [0.0]

        def find(*args):
            clock[0] = 0.8
            return 0.95, RECT

        with patch.object(exp.time, "monotonic", side_effect=lambda: clock[0]), patch.object(
            exp.time, "sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
        ) as sleep, patch.object(exp, "_take_frame", return_value=object()), patch.object(
            exp, "_match", side_effect=find,
        ), patch.object(exp, "_click_and_confirm") as click, patch.object(exp, "print"):
            self.assertFalse(exp._wait_and_click("prepare", "准备", 1.0, delay_before_click=1.0))
        self.assertAlmostEqual(sleep.call_args.args[0], 0.2)
        click.assert_not_called()

    def test_mail_close_and_consignment_reward_use_remaining_budget(self):
        for module, action, finder, clicker in [
            (mail, "_close_mailbox", "_wait_for_any", "_click_until_disappears"),
            (consignment, "_dismiss_reward", "_wait_for_template", None),
        ]:
            for expired in (False, True):
                with self.subTest(task=module.__name__, expired=expired), ExitStack() as stack:
                    budget = module.MAIL_PAGE_WAIT_SECONDS if module is mail else module.REWARD_WAIT_SECONDS
                    clock = [0.0]
                    stack.enter_context(patch.object(module.time, "monotonic", side_effect=lambda: clock[0]))

                    def find(*args):
                        clock[0] = budget + 1.0 if expired else budget - 0.2
                        if module is mail:
                            return object(), args[0][0], RECT, 0.95
                        return object(), RECT, 0.95

                    stack.enter_context(patch.object(module, finder, side_effect=find))
                    if clicker:
                        click = stack.enter_context(patch.object(module, clicker, return_value=True))
                    else:
                        click = stack.enter_context(patch.object(module.DEVICE, "click_until_disappears", return_value=True))
                    stack.enter_context(patch.object(module.LOGGER, "info"))
                    self.assertEqual(getattr(module, action)(), not expired)
                    if expired:
                        click.assert_not_called()
                    else:
                        remaining = click.call_args.args[3] if clicker else click.call_args.kwargs["timeout"]
                        self.assertAlmostEqual(remaining, 0.2)

    def test_reward_animation_consumes_click_budget(self):
        clock = [0.0]
        with patch.object(daily.time, "monotonic", side_effect=lambda: clock[0]), patch.object(
            daily.time, "sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
        ), patch.object(daily.DEVICE, "click_until_disappears") as click, patch.object(daily, "print"):
            self.assertFalse(daily._close_reward_success(RECT, 0.1))
        click.assert_not_called()

    def test_shared_click_helper_does_not_create_budget_for_zero_timeout(self):
        with patch.object(automation, "adb_click") as click, patch.object(
            automation, "take_screenshot",
        ) as screenshot, patch("builtins.print"):
            self.assertFalse(automation.click_template_until_disappears(
                (0, 0), (100, 100), "unused.png", RECT, timeout=0,
            ))
        click.assert_not_called()
        screenshot.assert_not_called()

    def test_secret_prepare_click_limit_and_reset_between_battles(self):
        # 连续可见则第四帧失败；第三次点击生效则可以完成下一场，计数重新开始。
        for stuck in (True, False):
            with self.subTest(stuck=stuck), ExitStack() as stack:
                stack.enter_context(patch.object(secret.utils, "connect_to_mumu", return_value=True))
                stack.enter_context(patch.dict(secret.utils.config))
                stack.enter_context(patch.object(secret, "print"))
                stack.enter_context(patch.object(secret.time, "sleep"))
                stack.enter_context(patch.object(secret, "_click_blank"))
                frames = iter(range(1, 30))
                stack.enter_context(patch.object(secret.DEVICE, "screenshot", side_effect=lambda: next(frames)))

                def match(frame, template, *_):
                    phase = (frame - 1) % 5
                    visible = (
                        template == secret.CHALLENGE_TEMPLATE and phase == 0
                        or template == secret.PREPARE_TEMPLATE and (frame > 1 if stuck else phase in (1, 2, 3))
                        or template == secret.REWARD_TEMPLATE and not stuck and phase == 4
                    )
                    return (0.95, RECT) if visible else (None, None)

                stack.enter_context(patch.object(secret, "_match", side_effect=match))
                click = stack.enter_context(patch.object(secret.DEVICE, "click"))
                stop = Mock()
                stop.is_set.side_effect = [False] * 20 + [True]
                self.assertEqual(secret.run(stop_event=stop, attempts=2), not stuck)
                self.assertEqual(click.call_count, 4 if stuck else 8)

    def test_secret_timeout_is_checked_even_if_screenshot_fails(self):
        clock = [0.0]

        def screenshot():
            if clock[0] == 0.0:
                return object()
            clock[0] = 302.0
            return None

        with patch.object(secret.utils, "connect_to_mumu", return_value=True), patch.dict(
            secret.utils.config,
        ), patch.object(secret.time, "monotonic", side_effect=lambda: clock[0]), patch.object(
            secret.DEVICE, "screenshot", side_effect=screenshot,
        ), patch.object(secret.DEVICE, "click", side_effect=lambda *a: clock.__setitem__(0, 1.0)) as click, patch.object(
            secret, "_match", side_effect=lambda frame, template, *a: (0.95, RECT) if template == secret.CHALLENGE_TEMPLATE else (None, None),
        ), patch.object(secret, "print"):
            self.assertFalse(secret.run(attempts=1))
        self.assertEqual(click.call_count, 1)

    def test_story_prepare_allows_three_clicks_then_only_checks(self):
        with ExitStack() as stack:
            stack.enter_context(patch.object(story.utils, "connect_to_mumu", return_value=True))
            stack.enter_context(patch.dict(story.utils.config))
            stack.enter_context(patch.object(story, "print", create=True))
            stack.enter_context(patch.object(story.DEVICE, "screenshot", return_value=object()))
            stack.enter_context(patch.object(story, "process_frame", return_value="challenge"))
            stack.enter_context(patch.object(story, "process_challenge_confirmation_frame", return_value=False))
            prepare = stack.enter_context(patch.object(story, "process_battle_prepare_frame", return_value=True))
            stop = Mock()
            stop.is_set.side_effect = [False] * 10 + [True]
            self.assertFalse(story.run(stop_event=stop))
            self.assertEqual(prepare.call_args_list, [
                call(unittest.mock.ANY, perform_click=True),
                call(unittest.mock.ANY, perform_click=True),
                call(unittest.mock.ANY, perform_click=True),
                call(unittest.mock.ANY, perform_click=False),
            ])


if __name__ == "__main__":
    unittest.main()

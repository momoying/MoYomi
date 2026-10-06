"""统一超时恢复对手机绑定引导的覆盖。"""

import unittest
from unittest.mock import patch

from module import recovery


class PhoneBindingRecoveryTests(unittest.TestCase):
    def test_recovery_action_priority(self):
        names = [name for name, _ in recovery.ACTION_SPECS]
        self.assertEqual(
            names,
            [
                "courtyard",
                "back",
                "close_pink",
                "close_red",
                "phone_bind_cancel",
                "phone_bind",
                "coop_reward",
            ],
        )

    def test_recovery_clicks_binding_guide_until_courtyard_returns(self):
        cancel = next(spec for name, spec in recovery.ACTION_SPECS if name == "phone_bind_cancel")
        bind = next(spec for name, spec in recovery.ACTION_SPECS if name == "phone_bind")
        actions = iter([
            ("phone_bind", bind, 0.95, (900, 420, 1100, 600)),
            ("phone_bind_cancel", cancel, 0.96, (400, 430, 650, 590)),
            (None, None, None, None),
        ])

        with (
            patch.object(recovery.DEVICE, "screenshot", side_effect=[object(), object(), object()]),
            patch.object(recovery, "find_highest_priority_action", side_effect=actions),
            patch.object(recovery, "_click_rect") as click,
            patch.object(recovery, "_is_courtyard", return_value=True),
            patch.object(recovery.time, "sleep"),
            patch.object(recovery.LOGGER, "info"),
        ):
            result = recovery.recover_to_courtyard(timeout=5.0, unknown_grace=1.0)

        self.assertTrue(result.success)
        self.assertIn("2 次", result.reason)
        self.assertEqual(
            [call.args[1].split("（")[0] for call in click.call_args_list],
            ["前往绑定按钮", "手机绑定取消按钮"],
        )


if __name__ == "__main__":
    unittest.main()

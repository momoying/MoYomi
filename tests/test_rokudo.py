from threading import Event
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import numpy as np

from module.assets import StartupAssets
from module.task_execution import run_task_call
from tasks.RokuDo import rokudo
from ui_app.pages.settings import SettingsPageMixin
from ui_app.pages.tools import ToolsPageMixin


class RokuDoTests(TestCase):
    def test_starting_in_courtyard_reports_wrong_page_immediately(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        marker = rokudo.automation._load_template(StartupAssets.I_MAIN.path)
        height, width = marker.shape[:2]
        frame[155:155 + height, 653:653 + width] = marker

        with patch.object(rokudo.DEVICE, "screenshot", side_effect=[frame]) as capture:
            result, report = run_task_call(rokudo._wait_for_page, rokudo.ENTRY_PAGES, 15, None)

        self.assertIsNone(result)
        self.assertIn("截到的是庭院", report.reason)
        np.testing.assert_array_equal(report.frame, frame)
        capture.assert_called_once()

    def test_tools_refresh_stale_mumu_target_before_launch(self):
        class Dashboard(ToolsPageMixin, SettingsPageMixin):
            pass

        dashboard = Dashboard()
        dashboard.active_tool = "story_skip"
        dashboard.running = dashboard.tool_running = False
        dashboard.mumu_path_field = SimpleNamespace(value="C:/MuMu")
        dashboard.adb_path_field = SimpleNamespace(value="C:/MuMu/adb.exe")
        dashboard.settings_message = SimpleNamespace()
        dashboard.mumu_instance = SimpleNamespace(value="0")
        dashboard.mumu_instances = [{"index": "0", "name": "MuMu 0", "adb_port": "127.0.0.1:16384"}]
        dashboard.tool_stop_event = Event()
        dashboard.page = SimpleNamespace(run_thread=Mock())
        dashboard._update_mumu_status = Mock()
        dashboard._begin_tool_run = Mock()
        dashboard._safe_update = Mock()
        dashboard.save_settings = Mock(side_effect=lambda: dashboard._selected_mumu() == running_instance)
        running_instance = {"index": "1", "name": "MuMu 1", "adb_port": "127.0.0.1:16416"}

        with (
            patch("ui_app.pages.settings.resolve_mumu_manager_path") as manager_path,
            patch("ui_app.pages.settings.resolve_mumu_adb_path", return_value=None),
            patch("ui_app.pages.settings.discover_running_mumu_instances", return_value=[running_instance]),
        ):
            manager_path.return_value.is_file.return_value = True
            dashboard.start_selected_tool()

        self.assertEqual(dashboard.mumu_instance.value, "1")
        dashboard.page.run_thread.assert_called_once_with(dashboard._tool_worker, "story_skip")

    def test_elite_rewards_and_clear_limit(self):
        rect = (0, 0, 10, 10)
        route = [
            ("map", "混沌"), ("elite_monster", None), ("elite_challenge", None),
            ("elite_buff_first", None), ("elite_buff_second", None), ("combat_reward", None),
            ("boss", None), ("final_reward", None), ("results", None), ("start", None),
        ]
        pages = iter([
            ("resume", None), *route,
            ("confirm", None), ("lineup", None), ("relic", None), ("initial_buff", None),
            *route,
        ])

        def next_page(expected, _timeout, _stop_event, **_kwargs):
            page, node = next(pages)
            self.assertIn(page, expected)
            template = "chaos_node" if page == "map" else page
            return page, node, rokudo.FIXED_CLICK_AREAS.get(page, (rect,)), template

        on_click = Mock()
        timing = Mock()
        device = Mock()
        device.random_point.side_effect = [(5 + i, 5) for i in range(24)]
        waits = Mock()
        with (
            patch.object(rokudo.automation, "connect_to_mumu", return_value=True),
            patch.object(rokudo, "DEVICE", device),
            patch.object(rokudo, "_wait_for_page", side_effect=next_page),
            patch.object(rokudo.time, "monotonic", side_effect=[100.0, 160.0]),
            patch.object(rokudo, "_wait", waits),
            patch.object(rokudo.random, "choice", side_effect=lambda areas: areas[-1]),
            patch.object(rokudo.random, "uniform", return_value=.15),
        ):
            self.assertTrue(rokudo.run(2, Event(), on_click, timing_callback=timing))

        self.assertEqual(device.click.call_count, 24)
        self.assertEqual(on_click.call_count, 24)
        timing.assert_called_once_with(60.0, 60.0, 1)
        self.assertEqual(on_click.call_args_list[0].args, ("resume", device.click.call_args_list[0].args))
        self.assertEqual(on_click.call_args_list[1].args, ("chaos_node", device.click.call_args_list[1].args))
        self.assertEqual(on_click.call_args_list[10].args, ("start", device.click.call_args_list[10].args))
        for page, click_index in (("combat_reward", 6), ("final_reward", 8), ("results", 9)):
            self.assertEqual(device.random_point.call_args_list[click_index].args,
                             (rokudo.FIXED_CLICK_AREAS[page][-1],))
        self.assertEqual([c.args[0] for c in waits.call_args_list if c.args[0] >= 1], [5, 10, 5, 10])
        click_delays = [c.args[0] for c in waits.call_args_list if c.args[0] < 1]
        self.assertAlmostEqual(click_delays[6], .35)
        self.assertAlmostEqual(click_delays[20], .35)
        self.assertEqual(click_delays[8], .15)
        self.assertIsNone(next(pages, None))

    def test_average_uses_only_completed_runs_started_at_the_opening_page(self):
        full_run = (*rokudo.START_PAGES, "boss", "final_reward", "results")
        for entry in ("start", "confirm", "lineup", "boss", "results"):
            with self.subTest(entry=entry):
                passes = iter((*full_run[full_run.index(entry):], *full_run, *full_run, "start"))
                timing = Mock()
                clock = [0.0, 100.0, 120.0, 160.0]
                expected_timings = [(100.0, 100.0, 1), (40.0, 70.0, 2)]
                if entry == "start":
                    clock.extend((170.0, 210.0))
                    expected_timings.append((40.0, 60.0, 3))

                def next_page(expected, *_args, **_kwargs):
                    page = next(passes)
                    self.assertIn(page, expected)
                    return page, None, (), page

                with (
                    patch.object(rokudo.automation, "connect_to_mumu", return_value=True),
                    patch.object(rokudo, "_wait_for_page", side_effect=next_page),
                    patch.object(rokudo, "_click_match", return_value=True),
                    patch.object(rokudo, "_wait"),
                    patch.object(rokudo.time, "monotonic", side_effect=clock),
                ):
                    self.assertTrue(rokudo.run(3, timing_callback=timing))
                self.assertEqual([call.args for call in timing.call_args_list], expected_timings)

    def test_scaled_high_priority_island_clicks_only_matched_text(self):
        def place(frame, asset, x, y, scale=1, core=None):
            color, _ = rokudo._island_template(asset.path, scale, core)
            height, width = color.shape[:2]
            frame[y:y + height, x:x + width] = color
            return x, y, x + width, y + height

        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        place(frame, rokudo.IMAGES["map_title"], 98, 26)
        place(frame, rokudo.IMAGES["map_summon_silver"], 1141, 589)
        positions = ((80, 164), (621, 328), (1160, 295))
        for target in positions:
            snapshot = frame.copy()
            for x, y in positions:
                if (x, y) == target:
                    sign = place(
                        snapshot, rokudo.NODES["宁息"][0], x, y, .9, rokudo.ISLAND_TEXT["shop_node"],
                    )
                else:
                    place(snapshot, rokudo.NODES["鏖战"][0], x, y)
            match = rokudo._recognize(snapshot, rokudo.ROUTE_PAGES)
            self.assertEqual(match, ("map", "宁息", (sign,), "shop_node"))
            with patch.object(rokudo.DEVICE, "click", return_value=True) as click:
                self.assertTrue(rokudo._click_match(match, None))
            x, y = click.call_args.args
            left, top, right, bottom = sign
            self.assertTrue(left <= x < right and top <= y < bottom)

    def test_mystery_island_survives_background_and_flame_changes(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        for name, x, y in (("map_title", 98, 26), ("map_summon_silver", 1141, 589)):
            marker, _ = rokudo._island_template(rokudo.IMAGES[name].path, 1)
            height, width = marker.shape[:2]
            frame[y:y + height, x:x + width] = marker
        asset = next(asset for asset in rokudo.NODES["神秘"] if asset.name == "mystery_center")
        core = rokudo.ISLAND_TEXT[asset.name]
        marker, _ = rokudo._island_template(asset.path, 1, core)
        height, width = marker.shape[:2]
        frame[373:373 + height, 643:643 + width] = marker

        page, node, (area,), _ = rokudo._recognize(frame, rokudo.ROUTE_PAGES)

        self.assertEqual((page, node), ("map", "神秘"))
        self.assertEqual(area, (643, 373, 643 + width, 373 + height))

    def test_moving_island_uses_latest_text_box_before_clicking(self):
        def place(frame, path, x, y, scale=1, core=None):
            marker, _ = rokudo._island_template(path, scale, core)
            height, width = marker.shape[:2]
            frame[y:y + height, x:x + width] = marker
            return x, y, x + width, y + height

        map_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        place(map_frame, rokudo.IMAGES["map_title"].path, 98, 26)
        place(map_frame, rokudo.IMAGES["map_summon_silver"].path, 1141, 589)
        asset = next(asset for asset in rokudo.NODES["神秘"] if asset.name == "mystery_center")
        first, latest = map_frame.copy(), map_frame.copy()
        label = rokudo.ISLAND_TEXT[asset.name]
        place(first, asset.path, 622, 170, .65, label)
        left, top, right, bottom = place(latest, asset.path, 780, 240, .75, label)
        first_match = rokudo._recognize(first, rokudo.ROUTE_PAGES)
        self.assertIsNotNone(first_match)
        self.assertEqual(first_match[1], "神秘")
        self.assertEqual(rokudo._map_node(latest, first_match)[0], "神秘")

        with (
            patch.object(rokudo.automation, "connect_to_mumu", return_value=True),
            patch.object(rokudo.DEVICE, "screenshot", side_effect=[first, latest]) as capture,
            patch.object(rokudo.DEVICE, "click", return_value=False) as click,
            patch.object(rokudo, "_wait"),
            patch.object(rokudo.random, "uniform") as click_delay,
        ):
            self.assertFalse(rokudo.run(1))

        self.assertEqual(capture.call_count, 2)
        click_delay.assert_not_called()
        click.assert_called_once()
        x, y = click.call_args.args
        self.assertTrue(left <= x < right and top <= y < bottom, (x, y))

    def test_map_tap_retries_at_fresh_island_coordinates(self):
        frame = Mock()
        frame.shape = (720, 1280, 3)
        selected = ("map", "神秘", ((357, 454, 420, 533),), "mystery_left")
        shifted = (("神秘", (357, 413, 420, 492), "mystery_left"),
                   ("神秘", (357, 418, 420, 497), "mystery_left"))
        arrived = ("mystery", None, rokudo.FIXED_CLICK_AREAS["mystery"], "mystery_title")
        expected = rokudo.NODE_PAGES["神秘"]

        clock = iter(range(30))
        on_click = Mock()
        with (
            patch.object(rokudo.DEVICE, "screenshot", side_effect=[frame, frame, Mock(shape=frame.shape)]),
            patch.object(rokudo.time, "monotonic", side_effect=lambda: next(clock)),
            patch.object(rokudo, "_recognize", side_effect=[None, None, arrived]),
            patch.object(rokudo, "_map_node", side_effect=shifted) as locate,
            patch.object(rokudo, "_wait"),
            patch.object(rokudo, "_click_match", return_value=True) as click,
        ):
            self.assertEqual(
                rokudo._wait_for_page(expected, 20, None, previous=selected, click_callback=on_click), arrived
            )
        self.assertEqual(locate.call_count, 2)
        self.assertTrue(all(call.args == (frame, selected) for call in locate.call_args_list))
        self.assertEqual([call.args[-1] for call in click.call_args_list], [(388, 452), (388, 476)])

    def test_reward_popup_retries_in_lower_blank_area_until_page_changes(self):
        def reward_frame(name):
            asset = rokudo.IMAGES[name]
            marker = rokudo.automation._load_template(asset.path)
            height, width = marker.shape[:2]
            left, top = asset.region[0]
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            frame[top:top + height, left:left + width] = marker
            return frame

        popup = reward_frame("final_reward")
        results = reward_frame("results")
        previous = rokudo._recognize(popup, ("final_reward",))
        expected = ("results",)
        left, top, right, bottom = previous[2][-1]

        for next_frame in (results, popup):
            with self.subTest(switched=next_frame is results):
                now = 0.0
                frames = iter(zip((.49, .5, .99, 1.0, 1.5), [popup] * 4 + [next_frame]))
                tap_times = []
                on_click = Mock()

                def capture():
                    nonlocal now
                    now, frame = next(frames)
                    return frame

                def tap(*_point, **_options):
                    tap_times.append(now)
                    return True

                with (
                    patch.object(rokudo.DEVICE, "screenshot", side_effect=capture),
                    patch.object(rokudo.time, "monotonic", side_effect=lambda: now),
                    patch.object(rokudo, "_wait"),
                    patch.object(rokudo.DEVICE, "click", side_effect=tap) as click,
                ):
                    result, report = run_task_call(
                        rokudo._wait_for_page, expected, 30, None, previous=previous, click_callback=on_click,
                    )
                self.assertEqual(result, rokudo._recognize(next_frame, expected))
                self.assertEqual(tap_times, [.5, 1.0])
                points = [call.args for call in click.call_args_list]
                self.assertNotEqual(*points)
                self.assertTrue(all(left < x < right and top < y < bottom for x, y in points))
                self.assertEqual([call.args for call in on_click.call_args_list],
                                 [("final_reward", point) for point in points])
                if next_frame is popup:
                    self.assertIn("获得最终奖励」补点 2 次后仍未切换界面", report.reason)
                    np.testing.assert_array_equal(report.frame, popup)
                else:
                    self.assertIsNone(report.reason)

"""依照界面提示运行六道之门的茨木路线。"""

import random
import time
from functools import cache

import cv2

from module import automation
from module.assets import StartupAssets
from module.base.device import TaskDevice
from module.task_execution import TaskCancelled, check_stopped, report_failure, set_stage

from tasks.RokuDo.assets import IMAGES, ISLANDS, ISLAND_TEXT, NODES, TEMPLATE_LABELS


DEVICE = TaskDevice(automation)
POLL_INTERVAL = .12
MAP_POLL_INTERVAL = .06
PAGE_TIMEOUT = 15
BATTLE_TIMEOUT = 60
ISLAND_RETRY_DELAY = 1.0
REWARD_RETRY_DELAY = .5
TRANSITION_RETRY_LIMIT = 2
ISLAND_DOWNSAMPLE = 4
DISTANT_ISLAND_SCALES = (.6, .65, .7, .75, .8, .85)
ROUTE_PAGES = ("map", "boss")
START_PAGES = ("start", "confirm", "lineup", "relic", "initial_buff")
REWARD_CHOICE_PAGES = ("normal_buff", "elite_buff_first", "elite_buff_second")
REWARD_PAGES = (*REWARD_CHOICE_PAGES, "combat_reward", "final_reward", "results")
NODE_PAGES = {
    "神秘": ("mystery",),
    "宁息": ("shop",),
    "鏖战": ("normal_monster", "normal_challenge"),
    "混沌": ("treasure", "elite_monster", "elite_challenge"),
    "淬炼之域": ("hub",),
}
PAGE_NODES = {
    page: node for node, pages in NODE_PAGES.items() for page in pages
} | {
    "normal_buff": "鏖战",
    "elite_buff_first": "混沌",
    "elite_buff_second": "混沌",
    "combat_reward": "战斗奖励",
    "boss": "首领挑战",
    "final_reward": "首领挑战",
    "results": "首领挑战",
}
ENTRY_PAGES = (
    "final_reward", "results", "combat_reward", *ROUTE_PAGES,
    *(page for pages in NODE_PAGES.values() for page in pages),
    "normal_buff", "elite_buff_first", "elite_buff_second", "resume", *START_PAGES,
)
NEXT_PAGES = {
    "start": ("confirm",),
    "resume": ROUTE_PAGES,
    "confirm": ("lineup",),
    "lineup": ("relic",),
    "relic": ("initial_buff",),
    "initial_buff": ROUTE_PAGES,
    "mystery": ROUTE_PAGES,
    "shop": ROUTE_PAGES,
    "hub": ROUTE_PAGES,
    "treasure": ROUTE_PAGES,
    "normal_monster": ("normal_challenge",),
    "elite_monster": ("elite_challenge",),
    "normal_challenge": ("normal_buff",),
    "elite_challenge": ("elite_buff_first",),
    "normal_buff": ("combat_reward",),
    "elite_buff_first": ("elite_buff_second",),
    "elite_buff_second": ("combat_reward",),
    "combat_reward": ROUTE_PAGES,
    "boss": ("final_reward",),
    "final_reward": ("results",),
    "results": ("start",),
}
FIXED_CLICK_AREAS = {
    "mystery": ((14, 22, 71, 78),),
    "combat_reward": ((35, 245, 475, 555), (760, 245, 1180, 565), (280, 570, 1045, 710)),
    "final_reward": ((18, 185, 342, 686), (949, 194, 1270, 704), (342, 572, 947, 704)),
    "results": ((800, 165, 1260, 603), (43, 603, 1095, 715)),
}
# 「选择」模板只含文字和部分边框，按各页面按钮轮廓补齐点击区域。
CHOICE_PADDING = {
    "relic": (31, 8, 28, 10),
    "initial_buff": (29, 13, 35, 11),
    "normal_buff": (27, 9, 43, 13),
    "elite_buff_first": (27, 9, 43, 13),
    "elite_buff_second": (27, 9, 43, 13),
}
MONSTER_OFFSETS = {
    "normal_monster": (8, 4, 114, 151),
    "elite_monster": (4, -14, 96, 141),
}


def _match(frame, asset):
    score, rect = DEVICE.match_asset(asset, frame=frame)
    if rect is not None and score is not None and score >= asset.threshold:
        return score, rect
    return None


def _find(frame, name):
    match = _match(frame, IMAGES[name])
    return match[1] if match is not None else None


@cache
def _island_template(path, scale, core=None):
    color = automation._load_template(path)
    if scale != 1:
        color = cv2.resize(color, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
    if core is not None:
        left, top, right, bottom = (round(n * scale) for n in core)
        color = color[top:bottom, left:right]
    return color, _shrink_island(cv2.cvtColor(color, cv2.COLOR_BGR2GRAY))


def _shrink_island(gray):
    ratio = 1 / ISLAND_DOWNSAMPLE
    return cv2.resize(gray, None, fx=ratio, fy=ratio, interpolation=cv2.INTER_AREA)


def _match_island(frame, gray, region, asset, scale):
    label = ISLAND_TEXT[asset.name]
    color, template = _island_template(asset.path, scale, label)
    if gray.shape[0] < template.shape[0] or gray.shape[1] < template.shape[1]:
        return None
    height, width = color.shape[:2]
    response = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
    (left, top), (right, bottom) = region
    threshold = .88 if scale < .9 else asset.threshold
    for _ in range(3):
        _, score, _, (x, y) = cv2.minMaxLoc(response)
        if score < threshold - .23:
            break
        # 低分辨率找岛名，原分辨率复核文字框。
        px, py = left + ISLAND_DOWNSAMPLE * x, top + ISLAND_DOWNSAMPLE * y
        margin = ISLAND_DOWNSAMPLE + 2
        x1, y1 = max(left, px - margin), max(top, py - margin)
        crop = frame[y1:min(bottom, py + height + margin), x1:min(right, px + width + margin)]
        if crop.shape[0] >= height and crop.shape[1] >= width:
            comparison = cv2.matchTemplate(crop, color, cv2.TM_CCOEFF_NORMED)
            _, score, _, (dx, dy) = cv2.minMaxLoc(comparison)
            if score >= threshold:
                px, py = x1 + dx, y1 + dy
                if px < 1060 or py >= 265:
                    return score, (px, py, px + width, py + height)
        rx, ry = template.shape[1] // 4, template.shape[0] // 4
        response[max(0, y - ry):y + ry + 1, max(0, x - rx):x + rx + 1] = -1
    return None


def _best_island(frame, gray, region, assets, scales):
    matches = [
        (*match, asset.name)
        for asset in assets for scale in scales
        if (match := _match_island(frame, gray, region, asset, scale))
    ]
    if matches:
        return max(matches, key=lambda item: (round(item[0], 4), -item[1][0]))
    return None


def _map_node(frame, previous=None):
    if not _find(frame, "map_title"):
        return None
    if not (_find(frame, "map_summon_silver") or _find(frame, "map_summon_gold")):
        return None
    (left, top), (right, bottom) = ISLANDS
    nodes = NODES.items()
    if previous is not None:
        # 补点时岛屿可能已从中央移到两侧，全区域重找同类岛名。
        _, node, _, _ = previous
        nodes = ((node, NODES[node]),)
    region = ((left, top), (right, bottom))
    gray = _shrink_island(cv2.cvtColor(frame[top:bottom, left:right], cv2.COLOR_BGR2GRAY))
    found = []
    for node, assets in nodes:
        match = _best_island(frame, gray, region, assets, (1,))
        found.append((node, assets, match))
    for node, assets, match in found:
        if match is None:
            match = _best_island(frame, gray, region, assets, (.9, 1.1))
        if match is None:
            match = _best_island(frame, gray, region, assets, DISTANT_ISLAND_SCALES)
        if match is not None:
            _, rect, template = match
            return node, rect, template
    return None


def _recognize(frame, expected):
    for page in expected:
        node = None
        template = page
        if page == "map":
            match = _map_node(frame)
            if match is None:
                continue
            node, rect, template = match
        elif page in ("start", "resume", "lineup"):
            marker = "lineup" if page == "lineup" else "map_title"
            template = "start" if page == "lineup" else page
            rect = _find(frame, template) if _find(frame, marker) else None
        elif page == "mystery":
            template = "mystery_title"
            rect = _find(frame, template)
        elif page in ("shop", "hub", "treasure"):
            marker = "treasure" if page == "treasure" else f"{page}_title"
            template = "leave"
            rect = _find(frame, template) if _find(frame, marker) else None
        elif page in ("normal_monster", "elite_monster"):
            title = "normal_title" if page == "normal_monster" else "chaos_title"
            marker = _find(frame, page) if _find(frame, title) else None
            if marker is None or _find(frame, "challenge"):
                continue
            left, _, right, bottom = marker
            dx1, dy1, dx2, dy2 = MONSTER_OFFSETS[page]
            rect = (left + dx1, bottom + dy1, right + dx2, bottom + dy2)
        elif page in ("normal_challenge", "elite_challenge", "boss"):
            title = {"normal_challenge": "normal_title", "elite_challenge": "chaos_title", "boss": "boss_title"}[page]
            template = "challenge"
            rect = _find(frame, template) if _find(frame, title) else None
        elif page in REWARD_CHOICE_PAGES:
            template = "combat_buff"
            rect = _find(frame, template)
            if rect is None:
                continue
            elite = bool(_find(frame, "elite_round"))
            first = elite and bool(_find(frame, "elite_first"))
            actual = ("elite_buff_first" if first else "elite_buff_second") if elite else "normal_buff"
            if page != actual:
                continue
        else:
            rect = _find(frame, page)
        if rect is not None:
            if page in CHOICE_PADDING:
                left, top, right, bottom = rect
                pad_left, pad_top, pad_right, pad_bottom = CHOICE_PADDING[page]
                rect = (left - pad_left, top - pad_top, right + pad_right, bottom + pad_bottom)
            return page, node, FIXED_CLICK_AREAS.get(page, (rect,)), template
    return None


def _wait(seconds, stop_event):
    check_stopped()
    if stop_event is None:
        time.sleep(seconds)
    elif stop_event.wait(seconds):
        raise TaskCancelled()


def _click_match(match, click_callback, point=None):
    _, _, areas, template = match
    if point is None:
        point = DEVICE.random_point(random.choice(areas))
    clicked = DEVICE.click(*point, retry_on_failure=False)
    if click_callback is not None:
        click_callback(template, point)
    if clicked is False:
        report_failure("六道之门点击失败")
        return False
    return True


def _retry_target(frame, previous, retries):
    page = previous[0]
    if page == "map":
        island = _map_node(frame, previous)
        if island is None:
            return None
        node, area, template = island
        match = (page, node, (area,), template)
        left, top, right, bottom = area
        point = ((left + right) // 2, (top + bottom) // 2 + retries * ((bottom - top) // 4))
        return match, point

    match = _recognize(frame, (page,))
    if match is None:
        return None
    # 奖励弹窗补点下方空白处，奖励选择只在当前轮的按钮内补点。
    left, top, right, bottom = match[2][-1]
    point = ((left + right) // 2 + retries * ((right - left) // 4), (top + bottom) // 2)
    return match, point


def _wait_for_page(expected, timeout, stop_event, *, previous=None, click_callback=None):
    deadline = time.monotonic() + timeout
    retry_delay = ISLAND_RETRY_DELAY if previous is not None and previous[0] == "map" else REWARD_RETRY_DELAY
    retry_at = time.monotonic() + retry_delay
    retries = 0
    candidate_node = None
    poll_interval = MAP_POLL_INTERVAL if "map" in expected else POLL_INTERVAL
    while time.monotonic() < deadline:
        _wait(0, stop_event)
        next_poll = time.monotonic() + poll_interval
        frame = DEVICE.screenshot()
        if frame is not None:
            if frame.shape[:2] != (720, 1280):
                report_failure("请将游戏分辨率设置为 1280×720", frame=frame)
                return None
            match = _recognize(frame, expected)
            if match is not None:
                page, node, _, _ = match
                if page != "map" or node == candidate_node:
                    return match
                candidate_node = node
            else:
                candidate_node = None
                if expected == ENTRY_PAGES and _match(frame, StartupAssets.I_MAIN):
                    report_failure("截到的是庭院，请检查所选 MuMu 实例并进入六道之门", frame=frame)
                    return None
            if match is None and previous is not None and time.monotonic() >= retry_at:
                target = _retry_target(frame, previous, retries)
                if target is not None:
                    retry_match, point = target
                    if retries >= TRANSITION_RETRY_LIMIT:
                        _, node, _, template = retry_match
                        label = node or TEMPLATE_LABELS[template]
                        report_failure(f"「{label}」补点 {retries} 次后仍未切换界面", frame=frame)
                        return None
                    _wait(0, stop_event)
                    if not _click_match(retry_match, click_callback, point):
                        return None
                    retries += 1
                    retry_at = time.monotonic() + retry_delay
        else:
            candidate_node = None
        _wait(max(0, next_poll - time.monotonic()), stop_event)
    if previous is not None and previous[0] in REWARD_PAGES:
        report_failure(f"点击「{TEMPLATE_LABELS[previous[3]]}」后，等待下一界面超时")
    else:
        report_failure("等待六道之门界面超时")
    return None


def run(max_runs, stop_event=None, click_callback=None):
    if type(max_runs) is not int or max_runs < 1:
        raise ValueError("最多通关次数必须为正整数")
    if stop_event is not None and stop_event.is_set():
        return True
    if not automation.connect_to_mumu():
        report_failure("无法连接 MuMu ADB，请检查模拟器设置")
        return False

    completed = 0
    expected = ENTRY_PAGES
    timeout = PAGE_TIMEOUT
    previous = None
    previous_interval = automation.config.get("screenshot_speed", .5)
    set_stage("识别六道之门")
    try:
        while True:
            automation.config["screenshot_speed"] = MAP_POLL_INTERVAL if "map" in expected else POLL_INTERVAL
            match = _wait_for_page(expected, timeout, stop_event,
                                   previous=previous, click_callback=click_callback)
            if match is None:
                return False
            page, node, _, _ = match
            if page == "start" and expected == ("start",):
                completed += 1
                if completed == max_runs:
                    return True
            if node or page in PAGE_NODES:
                set_stage(node or PAGE_NODES[page])
            elif page in START_PAGES:
                set_stage("开启六道之门")
            elif page == "resume":
                set_stage("继续六道之门")

            click_delay = 0 if page == "map" else random.uniform(.12, .20)
            if page == "combat_reward":
                click_delay += .20
            _wait(click_delay, stop_event)
            if not _click_match(match, click_callback):
                return False
            previous = match if page == "map" or page in REWARD_PAGES else None
            expected = NODE_PAGES[node] if page == "map" else NEXT_PAGES[page]
            timeout = PAGE_TIMEOUT
            if page in ("normal_challenge", "elite_challenge", "boss"):
                _wait(10 if page == "boss" else 5, stop_event)
                timeout = BATTLE_TIMEOUT
    except TaskCancelled:
        return True
    finally:
        automation.config["screenshot_speed"] = previous_interval

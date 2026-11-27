"""六道之门茨木的 1280×720 界面模板。"""

from pathlib import Path

from module.base.assets import ImageAsset


RES = Path(__file__).with_name("res")
ISLANDS = ((20, 115), (1260, 625))
TITLE = ((90, 20), (244, 72))
LOWER_RIGHT = ((1118, 566), (1275, 708))
REWARD_BUTTON = ((1012, 542), (1166, 609))


def image(name, region, threshold=.85):
    return ImageAsset(RES / f"{name}.png", region, threshold, name)


IMAGES = {
    "start": image("start", LOWER_RIGHT, .92),
    "resume": image("resume", LOWER_RIGHT, .90),
    "confirm": image("confirm", LOWER_RIGHT, .90),
    "lineup": image("lineup", ((495, 22), (820, 68)), .88),
    "relic": image("relic", ((155, 580), (310, 648)), .87),
    "initial_buff": image("initial_buff", ((892, 544), (1018, 607)), .88),
    "map_title": image("map_title", TITLE),
    "map_summon_silver": image("map_summon_silver", ((1128, 580), (1211, 645)), .85),
    "map_summon_gold": image("map_summon_gold", ((1128, 580), (1211, 645)), .85),
    "mystery_title": image("mystery_title", TITLE),
    "shop_title": image("shop_title", TITLE),
    "hub_title": image("hub_title", TITLE),
    "normal_title": image("normal_title", TITLE),
    "chaos_title": image("chaos_title", TITLE),
    "boss_title": image("boss_title", TITLE),
    "leave": image("leave", LOWER_RIGHT, .82),
    "normal_monster": image("normal_monster", ((635, 155), (900, 296)), .81),
    "elite_monster": image("elite_monster", ((495, 145), (835, 314)), .81),
    "treasure": image("treasure", ((550, 180), (770, 425)), .86),
    "challenge": image("challenge", LOWER_RIGHT, .78),
    "combat_buff": image("combat_buff", REWARD_BUTTON, .88),
    "elite_round": image("elite_round", ((540, 13), (760, 60)), .84),
    "elite_first": image("elite_first", ((622, 18), (663, 56)), .86),
    "combat_reward": image("combat_reward", ((480, 105), (805, 230)), .88),
    "final_reward": image("final_reward", ((470, 100), (820, 250)), .88),
    "results": image("results", ((509, 646), (731, 712)), .82),
}

# 从完整标志裁出岛名，文字模板同时用于识别和约束点击范围。
NODES = {
    "神秘": tuple(image(name, ISLANDS, .82) for name in ("mystery_left", "mystery_right", "mystery_center")),
    "宁息": (image("shop_node", ISLANDS, .82),),
    "鏖战": tuple(image(name, ISLANDS, .82) for name in (
        "normal_center", "normal_right", "normal_small", "normal_center_wide",
    )),
    "混沌": (image("chaos_node", ISLANDS, .82),),
    "淬炼之域": (image("hub_node", ISLANDS, .83),),
}

ISLAND_TEXT = {
    "mystery_left": (29, 34, 62, 93),
    "mystery_right": (49, 34, 82, 93),
    "mystery_center": (35, 33, 67, 92),
    "shop_node": (14, 28, 47, 91),
    "normal_center": (41, 103, 76, 167),
    "normal_right": (34, 96, 69, 159),
    "normal_small": (27, 82, 65, 145),
    "normal_center_wide": (33, 104, 73, 166),
    "chaos_node": (71, 42, 104, 101),
    "hub_node": (86, 32, 119, 156),
}

TEMPLATE_LABELS = {
    "start": "开启",
    "resume": "继续",
    "confirm": "确认",
    "lineup": "式神上阵",
    "relic": "选择法器",
    "initial_buff": "选择初始增益",
    "map_title": "净佛刹标题",
    "map_summon_silver": "灰色唤息按钮",
    "map_summon_gold": "金色唤息按钮",
    "mystery_title": "神秘之屿标题",
    "shop_title": "宁息之屿标题",
    "hub_title": "淬炼之屿标题",
    "normal_title": "鏖战之屿标题",
    "chaos_title": "混沌之屿标题",
    "boss_title": "首领挑战标题",
    "leave": "离开",
    "normal_monster": "普通怪",
    "elite_monster": "精英怪",
    "treasure": "混沌宝匣",
    "challenge": "挑战",
    "combat_buff": "选择战斗奖励",
    "elite_round": "精英奖励轮次",
    "elite_first": "精英第一轮奖励",
    "combat_reward": "获得战斗奖励",
    "final_reward": "获得最终奖励",
    "results": "通关结算",
    "mystery_left": "神秘岛",
    "mystery_right": "神秘岛",
    "mystery_center": "神秘岛",
    "shop_node": "宁息岛",
    "normal_center": "鏖战岛",
    "normal_right": "鏖战岛",
    "normal_small": "鏖战岛",
    "normal_center_wide": "鏖战岛",
    "chaos_node": "混沌岛",
    "hub_node": "淬炼之域",
}

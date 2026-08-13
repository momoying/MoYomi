"""本任务的图片、识别区域和固定操作坐标。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

from module.base.assets import ClickAsset, ImageAsset, TaskAssets


ASSET_DIR = Path(__file__).resolve().parent
RES_DIR = ASSET_DIR / "res"
TASKS_DIR = ASSET_DIR.parent
PROJECT_ROOT = ASSET_DIR.parents[1]
MODULE_RES_DIR = PROJECT_ROOT / "module" / "res"
Point = Tuple[int, int]


@dataclass(frozen=True)
class StoryAction:
    key: str
    label: str
    template: Path
    top_left: Point
    bottom_right: Point
    threshold: float = 0.8


class StorySkipAssets(TaskAssets):
    # 确认跳过按钮
    I_CONFIRM_SKIP = ImageAsset(
        file=RES_DIR / "confirm_skip.png",
        region=((0, 0), (1280, 720)),
        threshold=0.8,
        name='confirm_skip',
    )

    # 亮色对话气泡
    I_DIALOG_BUBBLE = ImageAsset(
        file=RES_DIR / "dialog_bubble.png",
        region=((0, 0), (1280, 720)),
        threshold=0.92,
        name='dialog_bubble',
    )

    # 暗色对话气泡
    I_DIALOG_BUBBLE2 = ImageAsset(
        file=RES_DIR / "dialog_bubble2.png",
        region=((0, 0), (1280, 720)),
        threshold=0.92,
        name='dialog_bubble2',
    )

    # 对话跳过按钮
    I_DIALOGUE_SKIP = ImageAsset(
        file=RES_DIR / "dialogue_skip.png",
        region=((0, 360), (1280, 720)),
        threshold=0.8,
        name='dialogue_skip',
    )

    # 剧情跳过按钮
    I_STORY_SKIP = ImageAsset(
        file=RES_DIR / "story_skip.png",
        region=((1080, 0), (1280, 160)),
        threshold=0.8,
        name='story_skip',
    )

    # 挑战按钮
    I_CHALLENGE = ImageAsset(
        file=RES_DIR / "challenge.png",
        region=((0, 0), (1280, 720)),
        threshold=0.8,
        name='challenge',
    )

    # 天眼按钮
    I_TIANYAN = ImageAsset(
        file=RES_DIR / "tianyan.png",
        region=((0, 0), (1280, 720)),
        threshold=0.8,
        name='tianyan',
    )

    # 未知问号标志
    I_UNKNOWN_SYMBOL = ImageAsset(
        file=RES_DIR / "unknown_symbol.png",
        region=((0, 0), (1280, 720)),
        threshold=0.8,
        name='unknown_symbol',
    )

    # 战斗准备按钮
    I_BATTLE_PREPARE = ImageAsset(
        file=RES_DIR / "battle_prepare.png",
        region=((0, 0), (1280, 720)),
        threshold=0.82,
        name='battle_prepare',
    )

    # 战斗奖励界面
    I_BATTLE_REWARD = ImageAsset(
        file=RES_DIR / "battle_reward.png",
        region=((0, 0), (1280, 720)),
        threshold=0.82,
        name='battle_reward',
    )

    # 战斗奖励界面左侧安全点击区域
    C_BATTLE_REWARD_BLANK_AREAS_LEFT = ClickAsset(area=(30, 160, 210, 650), name='battle_reward_blank_areas_left')

    # 战斗奖励界面右侧安全点击区域
    C_BATTLE_REWARD_BLANK_AREAS_RIGHT = ClickAsset(area=(1070, 160, 1250, 650), name='battle_reward_blank_areas_right')

    BATTLE_REWARD_BLANK_AREAS = {
        '左侧': C_BATTLE_REWARD_BLANK_AREAS_LEFT.area,
        '右侧': C_BATTLE_REWARD_BLANK_AREAS_RIGHT.area,
    }

    # 元组顺序就是处理优先级，禁止按其他字段排序。
    ACTIONS = (
        StoryAction('confirm_skip', '确认跳过', I_CONFIRM_SKIP.file, I_CONFIRM_SKIP.region[0], I_CONFIRM_SKIP.region[1], I_CONFIRM_SKIP.threshold),
        StoryAction('dialog_bubble', '三点气泡(亮)', I_DIALOG_BUBBLE.file, I_DIALOG_BUBBLE.region[0], I_DIALOG_BUBBLE.region[1], I_DIALOG_BUBBLE.threshold),
        StoryAction('dialog_bubble2', '三点气泡(暗)', I_DIALOG_BUBBLE2.file, I_DIALOG_BUBBLE2.region[0], I_DIALOG_BUBBLE2.region[1], I_DIALOG_BUBBLE2.threshold),
        StoryAction('dialogue_skip', '对话跳过', I_DIALOGUE_SKIP.file, I_DIALOGUE_SKIP.region[0], I_DIALOGUE_SKIP.region[1], I_DIALOGUE_SKIP.threshold),
        StoryAction('story_skip', '右上剧情跳过', I_STORY_SKIP.file, I_STORY_SKIP.region[0], I_STORY_SKIP.region[1], I_STORY_SKIP.threshold),
        StoryAction('challenge', '挑战', I_CHALLENGE.file, I_CHALLENGE.region[0], I_CHALLENGE.region[1], I_CHALLENGE.threshold),
        StoryAction('tianyan', '天眼', I_TIANYAN.file, I_TIANYAN.region[0], I_TIANYAN.region[1], I_TIANYAN.threshold),
        StoryAction('unknown_symbol', '未知问号标志', I_UNKNOWN_SYMBOL.file, I_UNKNOWN_SYMBOL.region[0], I_UNKNOWN_SYMBOL.region[1], I_UNKNOWN_SYMBOL.threshold),
    )

    BATTLE_PREPARE_TEMPLATE = I_BATTLE_PREPARE.file
    BATTLE_PREPARE_REGION = I_BATTLE_PREPARE.region
    BATTLE_PREPARE_THRESHOLD = I_BATTLE_PREPARE.threshold
    BATTLE_REWARD_TEMPLATE = I_BATTLE_REWARD.file
    BATTLE_REWARD_REGION = I_BATTLE_REWARD.region
    BATTLE_REWARD_THRESHOLD = I_BATTLE_REWARD.threshold

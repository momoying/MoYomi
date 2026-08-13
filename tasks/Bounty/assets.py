"""本任务的图片、识别区域和固定操作坐标。"""

from __future__ import annotations

from pathlib import Path

from module.base.assets import ClickAsset, ImageAsset, TaskAssets


ASSET_DIR = Path(__file__).resolve().parent
RES_DIR = ASSET_DIR / "res"
TASKS_DIR = ASSET_DIR.parent
PROJECT_ROOT = ASSET_DIR.parents[1]
MODULE_RES_DIR = PROJECT_ROOT / "module" / "res"


class BountyAssets(TaskAssets):
    # 悬赏封印入口
    I_BOUNTY = ImageAsset(
        file=RES_DIR / "bounty.png",
        region=((180, 240), (400, 430)),
        threshold=0.82,
        name='bounty',
    )

    # 返回按钮
    I_BACK = ImageAsset(
        file=RES_DIR / "back.png",
        region=((1050, 60), (1250, 210)),
        threshold=0.82,
        name='back',
    )

    # 普通协作标记
    I_COOPERATION = ImageAsset(
        file=RES_DIR / "cooperation.png",
        region=((100, 220), (1260, 370)),
        threshold=0.82,
        name='cooperation',
    )

    # 现世协作标记
    I_SHARING = ImageAsset(
        file=RES_DIR / "sharing.png",
        region=((100, 220), (1260, 370)),
        threshold=0.82,
        name='sharing',
    )

    # 勾玉奖励标记
    I_MAGATAMA = ImageAsset(
        file=RES_DIR / "magatama.png",
        region=None,
        threshold=0.82,
        name='magatama',
    )

    MATCH_THRESHOLD = 0.82

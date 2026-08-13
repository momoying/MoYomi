"""MoYomi 中控兼容入口。"""

from __future__ import annotations

from controller.api import *
from controller.api import __all__
from controller.runtime import print


if __name__ == "__main__":
    try:
        success = run()
    except KeyboardInterrupt:
        print("Daily 中控已由用户中止")
        success = False
    raise SystemExit(0 if success else 1)

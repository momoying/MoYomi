"""中控共享常量与仓库路径。"""

from __future__ import annotations

from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
HELPER_DIR = ROOT_DIR
TASKS_DIR = ROOT_DIR / "tasks"
PROJECT_ROOT = HELPER_DIR.parent
CONFIG_DIR = ROOT_DIR / "config"
STATUS_PATH = CONFIG_DIR / "account_status.json"
WEEKLY_STATUS_PATH = CONFIG_DIR / "weekly_account_status.json"

DAILY_MODE = "daily"

WEEKLY_MODE = "weekly"

VALID_TASK_MODES = {DAILY_MODE, WEEKLY_MODE}

CONSIGNMENT_HOUSE_TASK = "consignment_house"

WEEKLY_STATUS_VERSION = 1

HEART_TEAM_TASK = "heart_team"

HEART_TEAM_BATTLES_COMPLETED_CLEANUP_FAILED = (
    "battles_completed_cleanup_failed"
)

COOP_BATTLE_COMPLETED_RECOVERY_REQUIRED = "battle_completed_recovery_required"

MODULE_PATHS = {
    "startup_recovery": HELPER_DIR / "module" / "startup.py",
    "task_timeout_recovery": HELPER_DIR / "module" / "recovery.py",
    "switch": TASKS_DIR / "Account" / "switch.py",
    "sign": TASKS_DIR / "Account" / "sign.py",
    "mail_collected": TASKS_DIR / "Mail" / "mail.py",
    "liked": TASKS_DIR / "Like" / "like.py",
    "one_tap_daily_completed": TASKS_DIR / "OneTapDaily" / "one_tap_daily.py",
    "coop_reward_completed": TASKS_DIR / "CoopReward" / "coop_reward.py",
    "experience_monster_completed": TASKS_DIR / "Exp" / "exp_monster.py",
    "bounty_checked": TASKS_DIR / "Bounty" / "bounty.py",
    "merchant_checked": TASKS_DIR / "Merchant" / "merchant.py",
    "guild_kirin_completed": TASKS_DIR / "GuildKirin" / "guild_kirin.py",
    HEART_TEAM_TASK: TASKS_DIR / "HeartTeam" / "heart_team.py",
    CONSIGNMENT_HOUSE_TASK: (
        TASKS_DIR / "ConsignmentHouse" / "consignment_house.py"
    ),
}

TASK_ORDER = (
    "mail_collected",
    "liked",
    "one_tap_daily_completed",
    "coop_reward_completed",
    "experience_monster_completed",
    "bounty_checked",
    "merchant_checked",
    "guild_kirin_completed",
    HEART_TEAM_TASK,
)

SHUFFLED_TASK_ORDER = (
    "mail_collected",
    "liked",
    "bounty_checked",
    "one_tap_daily_completed",
    "merchant_checked",
)

BATTLE_TASK_ORDER = (
    "coop_reward_completed",
    "experience_monster_completed",
    "guild_kirin_completed",
    HEART_TEAM_TASK,
)

TASK_LABELS = {
    "mail_collected": "领取邮件",
    "liked": "好友点赞",
    "one_tap_daily_completed": "一键日常",
    "coop_reward_completed": "协战奖励",
    "experience_monster_completed": "经验妖怪",
    "bounty_checked": "悬赏检测",
    "merchant_checked": "奸商检测",
    "guild_kirin_completed": "寮麒麟",
    HEART_TEAM_TASK: "同心队",
    CONSIGNMENT_HOUSE_TASK: "寄售屋",
}

DEFAULT_TASK_ENABLED = {
    task_name: task_name != HEART_TEAM_TASK
    for task_name in TASK_ORDER
}

BOUNTY_TASK = "bounty_checked"

MERCHANT_TASK = "merchant_checked"

STATUS_VERSION = 8

SAME_REGION = "same"

CROSS_REGION = "cross"

VALID_REGIONS = (SAME_REGION, CROSS_REGION)

REGION_LABELS = {
    SAME_REGION: "狐之宴",
    CROSS_REGION: "砂狐乐园",
}

REGION_STATE_KEYS = {
    SAME_REGION: "同区",
    CROSS_REGION: "跨区",
}

CROSS_REGION_TASKS = ("liked", BOUNTY_TASK)

TASK_RESULT_FIELDS = {
    BOUNTY_TASK: "bounty_result",
    MERCHANT_TASK: "merchant_result",
}

TASK_TIME_FIELDS = {
    BOUNTY_TASK: "time",
    MERCHANT_TASK: "time",
    "coop_reward_completed": "completed_at",
    HEART_TEAM_TASK: "completed_at",
}

HEART_TEAM_ROLES = {"leader", "member"}

HEART_TEAM_ROLE_DETAILS = {
    "leader": "队长",
    "member": "成员",
}

GUILD_KIRIN_TASK = "guild_kirin_completed"

MAIL_TASK = "mail_collected"

COOP_REWARD_TASK = "coop_reward_completed"

COOP_REWARD_BASE_RUNS = 5

COOP_REWARD_EXTRA_RUNS = 5

BOUNTY_RESULT_DETAILS = {
    "normal_magatama_collaboration": "普通勾协",
    "sharing_magatama_collaboration": "现世勾协",
    "no_magatama_collaboration": "没有勾玉协作",
}

MERCHANT_RESULT_DETAILS = {
    "blue_ticket_50": "发现50蓝票",
    "blue_ticket_70": "发现70蓝票",
    "blue_ticket_80": "发现80蓝票",
    "blue_ticket_90": "发现90蓝票",
    "no_blue_ticket": "没有蓝票",
    "skipped_after_50": "已有账号发现50，已跳过",
}

MERCHANT_STOP_RESULT = "blue_ticket_50"

MERCHANT_SKIPPED_RESULT = "skipped_after_50"

CONSIGNMENT_ALREADY_PURCHASED = "already_purchased"

CONSIGNMENT_PURCHASED = "purchased"

CONSIGNMENT_ERROR = "error"

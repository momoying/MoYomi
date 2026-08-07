"""ServerChan notification helpers with slot-based detection summaries."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

import requests


ENV_NAME = "SERVERCHAN_SENDKEY"
PROJECT_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_DIR / ".env"
STATE_PATH = PROJECT_DIR / "serverchan_notification_state.json"
BOUNTY_TASK = "bounty_checked"
MERCHANT_TASK = "merchant_checked"
BOUNTY_RESULTS = {
    "normal_magatama_collaboration": "普通勾协",
    "sharing_magatama_collaboration": "现世勾协",
    "no_magatama_collaboration": "无勾协",
}
MERCHANT_PRICES = (50, 70, 80, 90)


class ServerChanError(RuntimeError):
    """A safe-to-log ServerChan error which never contains the SendKey."""


@dataclass(frozen=True)
class NotificationResult:
    status: str
    message: str


def _project_sendkey(path: Path = ENV_PATH) -> str:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, value = line.partition("=")
        if separator and name.strip() == ENV_NAME:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            return value.strip()
    return ""


def get_serverchan_sendkey() -> str:
    """Load the project .env first, then fall back to the process environment."""

    project_key = _project_sendkey()
    if project_key:
        os.environ[ENV_NAME] = project_key
        return project_key
    return os.getenv(ENV_NAME, "").strip()


def serverchan_endpoint(send_key: str) -> str:
    key = str(send_key or "").strip()
    if not key:
        raise ValueError("未配置 Server酱 SendKey")
    if key.startswith("sctp"):
        match = re.match(r"^sctp(\d+)t", key)
        if match is None:
            raise ValueError("sctp SendKey 格式无效")
        return f"https://{match.group(1)}.push.ft07.com/send/{key}.send"
    return f"https://sctapi.ftqq.com/{key}.send"


def send_serverchan(
    title: str,
    desp: str = "",
    *,
    send_key: Optional[str] = None,
    timeout: float = 10.0,
    requester: Callable[..., Any] = requests.post,
) -> dict[str, Any]:
    """POST one ServerChan message without exposing its SendKey in errors."""

    title = str(title)
    if not title.strip() or "\n" in title or "\r" in title:
        raise ValueError("Server酱标题不能为空或包含换行")
    key = str(
        send_key if send_key is not None else get_serverchan_sendkey()
    ).strip()
    endpoint = serverchan_endpoint(key)
    try:
        response = requester(
            endpoint,
            json={"title": title, "desp": str(desp)},
            headers={
                "Content-Type": "application/json;charset=utf-8",
                "Accept": "application/json",
            },
            timeout=timeout,
        )
    except requests.RequestException:
        raise ServerChanError("Server酱请求失败，请检查网络后重试") from None

    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        payload = None

    if response.status_code >= 400:
        detail = ""
        if isinstance(payload, dict):
            detail = str(payload.get("message") or payload.get("msg") or "")
        if not detail:
            detail = str(getattr(response, "text", "") or "")
            detail = re.sub(r"<[^>]+>", " ", detail)
        detail = " ".join(detail.split()).replace(key, "***")[:160]
        if not detail:
            detail = "网关未返回原因，请检查 SendKey 是否仍然有效"
        raise ServerChanError(
            f"Server酱请求失败（HTTP {response.status_code}）：{detail}"
        )

    if payload is None:
        raise ServerChanError("Server酱返回了无法解析的数据")
    if not isinstance(payload, dict) or payload.get("code") != 0:
        code = payload.get("code") if isinstance(payload, dict) else "unknown"
        detail = ""
        if isinstance(payload, dict):
            detail = str(payload.get("message") or payload.get("msg") or "")
        detail = " ".join(detail.split()).replace(key, "***")[:160]
        suffix = f"：{detail}" if detail else ""
        raise ServerChanError(f"Server酱发送失败（code={code}）{suffix}")
    return payload


def _parse_time(value: Any, now: datetime) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=now.tzinfo)
    return parsed.astimezone(now.tzinfo)


def _record(
    system_state: dict[str, Any],
    task_name: str,
    region_key: Optional[str] = None,
) -> dict[str, Any]:
    value = system_state.get(task_name)
    if region_key is not None and isinstance(value, dict):
        value = value.get(region_key)
    return value if isinstance(value, dict) else {}


def _enabled(system_state: dict[str, Any], task_name: str) -> bool:
    task_enabled = system_state.get("task_enabled")
    if not isinstance(task_enabled, dict):
        return True
    return task_enabled.get(task_name, True) is not False


def notification_slot(now: datetime) -> datetime:
    """Return the current 00-06, 06-18, or 18-24 bounty slot start."""

    if now.tzinfo is None:
        now = now.astimezone()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if now.hour < 6:
        return (day_start - timedelta(days=1)).replace(hour=18)
    if now.hour < 18:
        return day_start.replace(hour=6)
    return day_start.replace(hour=18)


def build_detection_summary(
    state: dict[str, Any],
    now: datetime,
) -> Optional[tuple[str, str, str]]:
    """Return (slot key, title, Markdown body) once all detections are ready."""

    if now.tzinfo is None:
        now = now.astimezone()
    systems = [
        system_state
        for account_state in state.get("accounts", {}).values()
        for system_state in account_state.get("systems", {}).values()
        if isinstance(system_state, dict)
    ]
    slot_start = notification_slot(now)
    bounty_targets = [
        (system_state, "同区")
        for system_state in systems
        if _enabled(system_state, BOUNTY_TASK)
    ]
    bounty_targets.extend(
        (system_state, "跨区")
        for system_state in systems
        if system_state.get("cross_region_enabled") is True
    )
    if not bounty_targets:
        return None

    bounty_counts = {result: 0 for result in BOUNTY_RESULTS}
    for system_state, region_key in bounty_targets:
        record = _record(system_state, BOUNTY_TASK, region_key)
        checked = _parse_time(record.get("time"), now)
        result = record.get("bounty_result")
        if checked is None or checked < slot_start or result not in bounty_counts:
            return None
        bounty_counts[result] += 1

    merchant_available = now.weekday() in {2, 5}
    merchant_targets = (
        [state for state in systems if _enabled(state, MERCHANT_TASK)]
        if merchant_available
        else []
    )
    merchant_results: list[str] = []
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for system_state in merchant_targets:
        record = _record(system_state, MERCHANT_TASK)
        checked = _parse_time(record.get("time"), now)
        result = record.get("merchant_result")
        if checked is None or checked < day_start or not isinstance(result, str):
            return None
        merchant_results.append(result)

    lines = [
        "## 悬赏检测",
        *(f"- {label}：{bounty_counts[key]}" for key, label in BOUNTY_RESULTS.items()),
    ]
    if merchant_targets:
        lines.extend(["", "## 奸商检测"])
        for price in MERCHANT_PRICES:
            found = f"blue_ticket_{price}" in merchant_results
            lines.append(f"- {price} 蓝票：{'有' if found else '无'}")

    slot_key = slot_start.isoformat(timespec="seconds")
    title = f"阴阳师检测结果 {now:%m-%d %H:%M}"
    return slot_key, title, "\n".join(lines)


def _load_sent_slot(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return ""
    return str(payload.get("last_sent_slot", "")) if isinstance(payload, dict) else ""


def _save_sent_slot(path: Path, slot: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps({"last_sent_slot": slot}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def maybe_send_detection_summary(
    state: dict[str, Any],
    now: datetime,
    *,
    enabled: bool,
    state_path: Path = STATE_PATH,
    sender: Callable[..., dict[str, Any]] = send_serverchan,
) -> NotificationResult:
    if not enabled:
        return NotificationResult("disabled", "Server酱推送未启用")
    if not get_serverchan_sendkey():
        return NotificationResult(
            "missing_key",
            "未配置 SERVERCHAN_SENDKEY，请到 https://sct.ftqq.com 免费获取",
        )
    summary = build_detection_summary(state, now)
    if summary is None:
        return NotificationResult("not_ready", "检测任务尚未全部完成")
    slot, title, desp = summary
    state_path = Path(state_path)
    if _load_sent_slot(state_path) == slot:
        return NotificationResult("already_sent", "当前检测时段已推送")
    try:
        sender(title, desp)
        _save_sent_slot(state_path, slot)
    except (ServerChanError, OSError, ValueError) as exc:
        return NotificationResult("error", str(exc))
    return NotificationResult("sent", "Server酱检测结果摘要已发送")


def set_project_sendkey(send_key: str, path: Path = ENV_PATH) -> None:
    """Store the SendKey in the gitignored project .env file."""
    key = str(send_key or "").strip()
    serverchan_endpoint(key)  # Validate without sending.
    if "\n" in key or "\r" in key:
        raise ValueError("SendKey 不能包含换行")
    path = Path(path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []
    kept = [
        line
        for line in lines
        if not re.match(rf"^\s*(?:export\s+)?{ENV_NAME}\s*=", line)
    ]
    kept.append(f"{ENV_NAME}={key}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("\n".join(kept) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    os.environ[ENV_NAME] = key


def clear_project_sendkey(path: Path = ENV_PATH) -> None:
    """Remove the project key from .env and the current process."""

    path = Path(path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []
    kept = [
        line
        for line in lines
        if not re.match(rf"^\s*(?:export\s+)?{ENV_NAME}\s*=", line)
    ]
    if kept:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text("\n".join(kept) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    else:
        path.unlink(missing_ok=True)
    os.environ.pop(ENV_NAME, None)

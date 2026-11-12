"""The data store: a handful of JSON files in ./data, which is a checkout of the repo's `data` branch.

Three writers touch it (GitHub Actions, the website, Claude agents on the Mac), so every write goes
through `transact`: sync to the latest remote state, apply the change, commit, push, and redo the
whole thing if someone else pushed first. A change must therefore be a function that can run again
on fresh data.

Never edit the JSON by hand or outside `transact`; a sync discards uncommitted edits.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, TypeVar

from .util import ROOT, now_iso

DATA_DIR = Path(os.environ.get("OUTREACH_DATA_DIR") or ROOT / "data")
BRANCH = "data"
T = TypeVar("T")

DEFAULTS: dict[str, Any] = {
    "leads": {"leads": []},
    "messages": {"messages": []},
    "connections": {"imported_at": None, "connections": []},
    "seen": {"keys": {}},
    "domains": {"domains": {}},
    "suppression": {"emails": {}},
    "quotas": {"usage": {}},
    "issues": {"issues": []},
    "runs": {"runs": []},
    "metrics": {"days": {}},
}


def path(name: str) -> Path:
    return DATA_DIR / f"{name}.json"


def load(name: str) -> Any:
    target = path(name)
    if not target.exists():
        return json.loads(json.dumps(DEFAULTS[name]))
    with open(target, encoding="utf-8") as handle:
        return json.load(handle)


def save(name: str, value: Any) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    target = path(name)
    temp = target.with_suffix(".json.tmp")
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    temp.replace(target)


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(DATA_DIR), *args], capture_output=True, text=True, check=check)


def git_enabled() -> bool:
    """True when ./data is its own git checkout with a remote to sync against."""
    if os.environ.get("OUTREACH_NO_GIT") == "1" or not (DATA_DIR / ".git").exists():
        return False
    return bool(_git("remote", check=False).stdout.strip())


def sync() -> None:
    """Make ./data match the remote `data` branch exactly."""
    if not git_enabled():
        return
    _git("fetch", "--quiet", "origin", BRANCH)
    _git("reset", "--quiet", "--hard", f"origin/{BRANCH}")


class PushConflict(Exception):
    pass


def transact(change: Callable[[], T], message: str, attempts: int = 6) -> T:
    """Run `change` (which loads, edits and saves files) and publish the result.

    `change` may run more than once, each time on freshly synced data.
    """
    if not git_enabled():
        return change()
    last = ""
    for _ in range(attempts):
        sync()
        result = change()
        _git("add", "-A")
        if not _git("status", "--porcelain").stdout.strip():
            return result
        _git("-c", "user.name=outreach-hq", "-c", "user.email=outreach-hq@users.noreply.github.com",
             "commit", "--quiet", "-m", message)
        pushed = _git("push", "--quiet", "origin", f"HEAD:{BRANCH}", check=False)
        if pushed.returncode == 0:
            return result
        last = pushed.stderr.strip()
    raise PushConflict(f"could not publish '{message}' after {attempts} attempts: {last}")


# ---- small helpers used by several modules -------------------------------------------------

def next_id(items: list[dict], prefix: str) -> str:
    highest = 0
    for item in items:
        ident = str(item.get("id", ""))
        if ident.startswith(prefix) and ident[len(prefix):].isdigit():
            highest = max(highest, int(ident[len(prefix):]))
    return f"{prefix}{highest + 1:04d}"


def find(items: list[dict], ident: str) -> dict | None:
    return next((item for item in items if item.get("id") == ident), None)


def add_timeline(lead: dict, actor: str, event: str, detail: str = "") -> None:
    lead.setdefault("timeline", []).append({"at": now_iso(), "actor": actor, "event": event, "detail": detail})
    lead["updated_at"] = now_iso()


def log_run(agent: str, ok: bool, summary: str, stats: dict | None = None) -> None:
    """Heartbeat the supervisor and the website read. Keeps the last 300 runs."""
    def change() -> None:
        runs = load("runs")
        runs["runs"].append({"at": now_iso(), "agent": agent, "ok": ok, "summary": summary, "stats": stats or {}})
        runs["runs"] = runs["runs"][-300:]
        save("runs", runs)
    transact(change, f"run: {agent} {'ok' if ok else 'FAILED'}")


def open_issue(agent: str, title: str, detail: str, severity: str = "warn", key: str | None = None) -> None:
    """Record a problem for the supervisor. `key` stops the same problem being filed twice."""
    def change() -> None:
        issues = load("issues")
        key_value = key or f"{agent}:{title}"
        for issue in issues["issues"]:
            if issue.get("key") == key_value and issue.get("status") == "open":
                issue["last_seen"] = now_iso()
                issue["count"] = issue.get("count", 1) + 1
                issue["detail"] = detail
                save("issues", issues)
                return
        issues["issues"].append({
            "id": next_id(issues["issues"], "I"), "key": key_value, "agent": agent, "severity": severity,
            "title": title, "detail": detail, "status": "open", "opened_at": now_iso(),
            "last_seen": now_iso(), "count": 1, "remedy": "", "resolved_at": None})
        save("issues", issues)
    transact(change, f"issue: {title}")

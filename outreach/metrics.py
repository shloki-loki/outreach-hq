"""Daily numbers for the Progress page and the supervisor."""

from __future__ import annotations

from collections import Counter
from typing import Any

from . import store
from .leads import display_status
from .util import now, today


def compute() -> dict[str, Any]:
    leads = store.load("leads")["leads"]
    messages = store.load("messages")["messages"]
    by_lead: dict[str, list[dict]] = {}
    for message in messages:
        by_lead.setdefault(message["lead_id"], []).append(message)
    statuses = Counter(display_status(lead, by_lead.get(lead["id"], [])) for lead in leads)
    delivered = [m for m in messages if m.get("status") in ("sent", "replied", "bounced")]
    cold = [m for m in delivered if m.get("kind") == "cold"]
    replied_threads = {(m["lead_id"], m["contact_id"]) for m in messages if m.get("status") == "replied"}
    bounced = [m for m in delivered if m.get("status") == "bounced"]
    week_ago = now().timestamp() - 7 * 86400
    return {
        "leads_total": len(leads),
        "by_status": dict(statuses),
        "by_source": dict(Counter(lead.get("source") or "?" for lead in leads)),
        "by_tier": dict(Counter(lead.get("tier") or "?" for lead in leads)),
        "qualified_total": sum(1 for lead in leads if lead.get("stage") == "qualified"),
        "researched_total": sum(1 for lead in leads if lead.get("research", {}).get("done")),
        "with_email_total": sum(1 for lead in leads if any(c.get("email") for c in lead.get("contacts", []))),
        "emails_sent_total": len(delivered),
        "emails_sent_today": sum(1 for m in delivered if (m.get("sent_at") or "").startswith(today())),
        "cold_sent_total": len(cold),
        "people_replied": len(replied_threads),
        "bounces_total": len(bounced),
        "reply_rate": round(len(replied_threads) / len(cold), 3) if cold else None,
        "bounce_rate": round(len(bounced) / len(delivered), 3) if delivered else None,
        "applied_total": sum(1 for lead in leads if lead.get("applied_at")),
        "referrals_sent": sum(1 for lead in leads for r in lead.get("referrals", []) if r.get("status") in ("sent", "replied")),
        "interviews": sum(1 for lead in leads if lead.get("outcome") == "interview"),
        "offers": sum(1 for lead in leads if lead.get("outcome") == "offer"),
        "to_approve": sum(1 for m in messages if m.get("status") == "draft"),
        "followups_due": sum(1 for lead in leads if lead.get("followup", {}).get("due")),
        "new_leads_7d": sum(1 for lead in leads if (lead.get("first_seen") or "") >= _date(week_ago)),
    }


def _date(timestamp: float) -> str:
    from datetime import datetime
    from .util import IST
    return datetime.fromtimestamp(timestamp, IST).strftime("%Y-%m-%d")


def snapshot() -> dict[str, Any]:
    result: dict[str, Any] = {}

    def change() -> None:
        result.clear()
        result.update(compute())
        metrics = store.load("metrics")
        metrics["days"][today()] = result.copy()
        # keep roughly six months of history
        for day in sorted(metrics["days"])[:-190]:
            del metrics["days"][day]
        store.save("metrics", metrics)
    store.transact(change, f"metrics: {today()}")
    return result

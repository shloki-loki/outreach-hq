"""Small shared helpers. Standard library only, so nothing needs installing anywhere."""

from __future__ import annotations

import html
import json
import os
import re
import time
import tomllib
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
IST = timezone(timedelta(hours=5, minutes=30))
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


def now() -> datetime:
    return datetime.now(IST)


def now_iso() -> str:
    return now().replace(microsecond=0).isoformat()


def today() -> str:
    return now().strftime("%Y-%m-%d")


def parse_iso(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=IST)


def load_config(name: str) -> dict[str, Any]:
    with open(CONFIG_DIR / f"{name}.toml", "rb") as handle:
        data = tomllib.load(handle)
    local = CONFIG_DIR / f"{name}.local.toml"
    if local.exists():  # private overrides that are never committed
        with open(local, "rb") as handle:
            _merge(data, tomllib.load(handle))
    return data


def _merge(base: dict, extra: dict) -> None:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value


def load_env() -> None:
    """Read KEY=value lines from .env into the environment, without overriding what is already set."""
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split(" #")[0].strip().strip('"').strip("'")
        if value and key.strip() not in os.environ:
            os.environ[key.strip()] = value


SECRET_PARAM = re.compile(r"\b(api_?key|key|token|secret|password)=(?!\[masked\])[^&\s\"']+", re.I)


def redact(text: str) -> str:
    """Mask credentials carried in URLs, so none is stored in an issue, a log or a printed error."""
    return SECRET_PARAM.sub(r"\1=[masked]", text)


class HttpError(Exception):
    def __init__(self, status: int, url: str, body: str = ""):
        super().__init__(redact(f"HTTP {status} for {url}"))
        self.status, self.url, self.body = status, url, body


def http_get(url: str, *, headers: dict[str, str] | None = None, data: bytes | None = None,
             timeout: int = 25, retries: int = 2, backoff: float = 4.0) -> bytes:
    """GET (or POST when `data` is given). Retries on 429 and 5xx with a growing pause."""
    merged = {"User-Agent": UA, "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
              "Accept-Language": "en-US,en;q=0.9"}
    merged.update(headers or {})
    last: Exception | None = None
    for attempt in range(retries + 1):
        request = urllib.request.Request(url, data=data, headers=merged)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read()[:400].decode("utf-8", "replace")
            last = HttpError(exc.code, url, body)
            if exc.code not in (429, 500, 502, 503, 504) or attempt == retries:
                raise last from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last = HttpError(-1, url, str(exc))
            if attempt == retries:
                raise last from None
        time.sleep(backoff * (attempt + 1))
    raise last or HttpError(-1, url)


def http_json(url: str, **kwargs: Any) -> Any:
    return json.loads(http_get(url, **kwargs))


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?i)<\s*(br|/p|/div|/li|/h[1-6])\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def ascii_fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


_COMPANY_NOISE = re.compile(
    r"\b(pvt|private|ltd|limited|inc|llc|llp|technologies|technology|tech|labs|india|global|"
    r"solutions|services|software|systems|group|co|company|corp|corporation|the)\b\.?", re.I)


def norm_company(name: str | None) -> str:
    """'Meesho (YC S15) Pvt. Ltd.' -> 'meesho'. Used to match the same company across sources."""
    if not name:
        return ""
    text = ascii_fold(name).lower()
    text = re.sub(r"\(.*?\)", " ", text)
    text = text.split(" via ")[0]
    text = _COMPANY_NOISE.sub(" ", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def norm_title(title: str | None) -> str:
    text = ascii_fold(title or "").lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def word_match(needle: str, haystack: str) -> bool:
    """Whole-word, case-insensitive: 'Ola' matches 'Ola Electric' but not 'Motorola'."""
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(needle.lower())}(?![a-z0-9])", haystack.lower()))


def business_days_between(start: datetime, end: datetime) -> int:
    """Whole business days (Mon-Fri) from start to end, not counting the start day."""
    days, cursor = 0, start.date()
    while cursor < end.date():
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            days += 1
    return days


def clip(text: str | None, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"

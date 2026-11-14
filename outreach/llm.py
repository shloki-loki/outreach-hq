"""The free language model the GitHub workers use (Google's Gemini API, free tier).

Why Gemini: GitHub Models was retired on 2026-07-30, and Gemini's free tier is the one free option that
can also search the web (Grounding with Google Search, free up to 500 requests a day on Gemini 2.5
Flash/Flash-Lite as of 2026-11-14). Research needs that for pay and culture evidence.

Key: GEMINI_API_KEY (Shlok creates it at aistudio.google.com and adds it as a GitHub secret). Note on the
free tier: Google may use free-tier prompts to improve its products. Prompts carry public job postings and
the facts in config/profile.toml, nothing else (no emails, no inbox, no keys).

The free tier costs nothing, so the limit is Google's own: a 429 that says the daily quota is used stops
the run cleanly instead of retrying, and the next scheduled run picks up where it stopped. (The
[providers.gemini*] numbers in settings.toml are not enforced here.)
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .util import load_config

API = "https://generativelanguage.googleapis.com/v1beta"


class LlmUnavailable(Exception):
    """No key, or the free quota for today is used. The caller stops and tries again next run."""


class LlmError(Exception):
    pass


@dataclass
class Reply:
    text: str
    model: str
    sources: list[dict] = field(default_factory=list)   # [{"title", "url"}] from Google Search grounding
    queries: list[str] = field(default_factory=list)

    def json(self) -> Any:
        return parse_json(self.text)


def parse_json(text: str) -> Any:
    """The first JSON object in a model reply (models wrap JSON in prose or code fences)."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start = text.find("{")
    if start < 0:
        raise LlmError(f"no JSON in reply: {text[:200]}")
    depth, in_string, escape = 0, False, False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            escape = char == "\\" and not escape
            if char == '"' and not escape:
                in_string = False
            elif char != "\\":
                escape = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:index + 1])
    raise LlmError(f"unterminated JSON in reply: {text[:200]}")


def key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or None


def _request(url: str, body: dict | None, timeout: int = 120) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                     headers={"Content-Type": "application/json", "x-goog-api-key": key() or ""})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


_MODELS: list[str] | None = None


def available_models() -> list[str]:
    global _MODELS
    if _MODELS is None:
        names: list[str] = []
        token = ""
        for _ in range(5):
            page = _request(f"{API}/models?pageSize=200" + (f"&pageToken={token}" if token else ""), None, 30)
            names += [m["name"].split("/", 1)[1] for m in page.get("models", [])
                      if "generateContent" in m.get("supportedGenerationMethods", [])]
            token = page.get("nextPageToken", "")
            if not token:
                break
        _MODELS = names
    return _MODELS


def pick(preferences: list[str]) -> str:
    """The first preferred model this key can use. Exact names win over prefixes."""
    names = available_models()
    for wanted in preferences:
        if wanted in names:
            return wanted
    for wanted in preferences:
        matches = sorted(n for n in names if n.startswith(wanted) and "preview" not in n and "exp" not in n)
        if matches:
            return matches[0]
    raise LlmUnavailable(f"none of {preferences} is available to this key")


def chain(preferences: list[str]) -> list[str]:
    """Every preferred model this key can use, in order: when one runs out of free quota, the next is used."""
    names = available_models()
    out: list[str] = []
    for wanted in preferences:
        if wanted in names:
            found = [wanted]
        else:
            found = sorted(n for n in names if n.startswith(wanted) and "preview" not in n and "exp" not in n)[:1]
        out += [n for n in found if n not in out]
    if not out:
        raise LlmUnavailable(f"none of {preferences} is available to this key")
    return out


def first(models: str | list[str] | None) -> str:
    return (models[0] if models else "") if isinstance(models, list) else (models or "")


_SPENT: dict[str, str] = {}   # model -> why it is skipped for the rest of this process (daily quota, retired)
_last_call = 0.0


def generate(prompt: str, *, system: str = "", model: str | list[str], search: bool = False, json_mode: bool = False,
             temperature: float = 0.3, max_tokens: int = 4096) -> Reply:
    """One call on the first model in `model` that still has free quota today; falls through the list."""
    names = [model] if isinstance(model, str) else list(model)
    last: Exception | None = None
    for name in names:
        if name in _SPENT:
            continue
        try:
            return _generate_one(prompt, system=system, model=name, search=search, json_mode=json_mode,
                                 temperature=temperature, max_tokens=max_tokens)
        except LlmUnavailable as exc:
            if not key():
                raise
            _SPENT[name] = str(exc)
            last = exc
        except LlmError as exc:
            if re.search(r"HTTP 404|no longer available", str(exc)) and len(names) > 1:
                _SPENT[name] = str(exc)
                last = exc
                continue
            raise
    if isinstance(last, LlmError) and len(names) == 1:
        raise last
    raise LlmUnavailable("free quota used for today on " + ", ".join(names)
                         + (f" (last: {str(last)[:200]})" if last else ""))


def _quota_note(detail: str) -> str:
    value = re.search(r'"quotaValue":\s*"?(\d+)', detail)
    metric = re.search(r'"quotaId":\s*"([^"]+)"', detail)
    return f" [limit {value.group(1) if value else '?'}: {metric.group(1) if metric else 'unknown quota'}]"


def _generate_one(prompt: str, *, system: str = "", model: str, search: bool = False, json_mode: bool = False,
                  temperature: float = 0.3, max_tokens: int = 4096) -> Reply:
    """One call. Paced to stay under the free per-minute limit; retries a per-minute 429 once."""
    global _last_call
    if not key():
        raise LlmUnavailable("GEMINI_API_KEY is not set")
    pace = float(load_config("settings").get("llm", {}).get("seconds_between_calls", 7))
    wait = _last_call + pace - time.time()
    if wait > 0:
        time.sleep(wait)
    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if search:
        body["tools"] = [{"google_search": {}}]
    elif json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    url = f"{API}/models/{model}:generateContent"
    for attempt in range(3):
        _last_call = time.time()
        try:
            data = _request(url, body)
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:1500].decode("utf-8", "replace")
            if exc.code == 429:
                if re.search(r"PerDay|per day|daily", detail, re.I) or attempt == 2:
                    raise LlmUnavailable(f"Gemini free quota used for today ({model}){_quota_note(detail)}") from None
                delay = re.search(r'"retryDelay":\s*"(\d+)s"', detail)
                time.sleep(min(int(delay.group(1)) + 2 if delay else 30, 90))
                continue
            if exc.code in (500, 502, 503, 504) and attempt < 2:
                time.sleep(15 * (attempt + 1))
                continue
            raise LlmError(f"Gemini HTTP {exc.code}: {detail[:400]}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if attempt == 2:
                raise LlmError(f"Gemini unreachable: {exc}") from None
            time.sleep(15)
    candidates = data.get("candidates") or []
    if not candidates:
        raise LlmError(f"Gemini returned no candidate: {json.dumps(data.get('promptFeedback', {}))[:300]}")
    candidate = candidates[0]
    text = "".join(part.get("text", "") for part in (candidate.get("content") or {}).get("parts", []))
    if not text.strip():
        raise LlmError(f"Gemini returned an empty answer (finishReason {candidate.get('finishReason')})")
    grounding = candidate.get("groundingMetadata") or {}
    sources = [{"title": chunk["web"].get("title", ""), "url": chunk["web"].get("uri", "")}
               for chunk in grounding.get("groundingChunks", []) if chunk.get("web")]
    return Reply(text=text, model=model, sources=sources, queries=grounding.get("webSearchQueries", []))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D401 - keep the Location header instead of following
        return None


def resolve(url: str) -> str:
    """Grounding links are Google redirect URLs; return the page they point to (or the input on failure)."""
    if "grounding-api-redirect" not in url and "vertexaisearch" not in url:
        return url
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        opener.open(urllib.request.Request(url, method="HEAD"), timeout=15)
    except urllib.error.HTTPError as exc:
        location = exc.headers.get("Location")
        if location:
            return location
    except Exception:  # noqa: BLE001 - an unresolved link is dropped by the caller
        pass
    return url


def check_models(prefixes: tuple[str, ...] = ("gemini-3", "gemini-2.5", "gemma-3")) -> list[dict]:
    """One tiny call per usable model: says which work today and, for a 429, which free limit was hit."""
    rows = []
    for name in [n for n in available_models() if n.startswith(prefixes) and "preview" not in n and "exp" not in n
                 and not re.search(r"image|tts|audio|live|embedding", n)]:
        try:
            reply = _generate_one("Answer with the single word OK.", model=name, temperature=0, max_tokens=10)
            rows.append({"model": name, "ok": True, "said": reply.text.strip()[:20]})
        except (LlmUnavailable, LlmError) as exc:
            rows.append({"model": name, "ok": False, "why": str(exc)[:300]})
    return rows


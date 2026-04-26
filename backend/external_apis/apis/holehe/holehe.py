# Holehe adapter — checks 120+ websites for email registration
# Runs holehe's async modules in a dedicated thread pool so it never
# conflicts with uvicorn's event loop.

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any, List, Tuple

SERVICE_NAME = "Holehe"

_MAX_CONCURRENT = 10  # semaphore: max parallel site checks (reduced to avoid network saturation)

# Modules excluded from scanning:
# - false-positive: consistently returns exists=True for any email
# - broken: crashes with parse errors on every run (list index, NoneType, etc.)
# - adult: adult sites excluded from a privacy-tool context
_BLOCKLIST: frozenset[str] = frozenset({
    # False positives
    "naturabuy",      # accepts any email as registered
    # Consistently broken parsers (verified across multiple runs)
    "buymeacoffee",   # NoneType attribute error on response parsing
    "rocketreach",    # unexpected response shape ('found' key missing)
    "github",         # list index out of range (holehe module, not our GitHub adapter)
    "samsung",        # list index out of range
    "soundcloud",     # list index out of range
    "evernote",       # list index out of range
    "snapchat",       # list index out of range
    "fanpop",         # empty/malformed response
    "pinterest",      # JSON decode error
    # Consistently blocked/unreachable/defunct
    "google",         # Google blocks automated registration checks every time
    "office365",      # Microsoft blocks automated checks every time
    "deliveroo",      # DNS resolution fails consistently
    "venmo",          # Blocks automated checks
    "biosmods",       # Consistently times out (site too slow / unresponsive)
    "blip",           # blip.fm defunct — times out every run
    # Adult sites — excluded from a professional privacy tool
    "redtube",
    "xnxx",
    "xvideos",
    "pornhub",
})


# ── helpers ───────────────────────────────────────────────────────────────────

def _empty_result(errors: List[str] | None = None) -> dict[str, Any]:
    return {
        "findings": [],
        "api_calls_made": 0,
        "sources_checked": 0,
        "pages_scanned": 0,
        "errors": errors or [],
        "service_name": SERVICE_NAME,
    }


# ── async core ────────────────────────────────────────────────────────────────

async def _safe_check(
    func: Any,
    email: str,
    client: Any,
    out: list,
    errors: list,
    sem: asyncio.Semaphore,
    timeout: float,
) -> None:
    """Run one holehe module with a semaphore + per-module timeout."""
    async with sem:
        try:
            await asyncio.wait_for(func(email, client, out), timeout=timeout)
        except asyncio.TimeoutError:
            errors.append(f"{func.__name__}: timeout after {timeout:.0f}s")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{func.__name__}: {exc}")


async def _run_holehe_async(
    email: str,
    per_module_timeout: float,
) -> Tuple[list, list, int]:
    """Fire all holehe modules concurrently and return (hits, errors, total_checked)."""
    try:
        import httpx
        from holehe.core import import_submodules, get_functions
    except ImportError as exc:
        return [], [f"holehe not installed: {exc}"], 0

    modules   = import_submodules("holehe.modules")
    functions = get_functions(modules)

    # Remove blocklisted modules — always run the full remaining set.
    # max_modules is intentionally ignored: max_sources from scan limits is
    # designed for the ethical scraper (pages to fetch), not holehe site checks.
    functions = [f for f in functions if f.__name__ not in _BLOCKLIST]

    sem: asyncio.Semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
    out:    list = []
    errors: list = []

    async with httpx.AsyncClient(
        timeout=per_module_timeout,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (compatible; affectra/1.0)"},
    ) as client:
        tasks = [
            _safe_check(fn, email, client, out, errors, sem, per_module_timeout)
            for fn in functions
        ]
        await asyncio.gather(*tasks)

    hits = [r for r in out if r.get("exists") is True]
    return hits, errors, len(functions)


# ── sync bridge ───────────────────────────────────────────────────────────────

def _run_in_thread(
    email: str,
    per_module_timeout: float,
) -> Tuple[list, list, int]:
    """Spin a fresh event loop in a worker thread — safe alongside uvicorn."""
    def _worker() -> Tuple[list, list, int]:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                _run_holehe_async(email, per_module_timeout)
            )
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_worker).result()


# ── public query entry point ───────────────────────────────────────────────────

def query(
    email: str | None = None,
    full_name: str | None = None,
    phone: str | None = None,
    usernames: list[str] | None = None,
    limits: dict[str, Any] | None = None,
) -> dict[str, Any]:

    if not email:
        return _empty_result(["Holehe: email address required; none provided."])

    lim             = limits or {}
    total_timeout   = lim.get("timeout_seconds", 90)
    per_mod_timeout = max(8.0, total_timeout / 15)     # at least 8s per module

    try:
        hits, errors, total_checked = _run_in_thread(email, per_mod_timeout)
    except Exception as exc:  # noqa: BLE001
        return _empty_result([f"Holehe: unexpected error — {exc}"])

    findings: list[dict[str, Any]] = []
    for hit in hits:
        site   = hit.get("name", "unknown")
        domain = hit.get("domain") or f"{site}.com"
        if domain and not domain.startswith("http"):
            domain = f"https://{domain}"

        extra: dict[str, Any] = {"email": email, "site": site}
        if hit.get("emailrecovery"):
            extra["email_recovery"] = hit["emailrecovery"]
        if hit.get("phoneNumber"):
            extra["phone_number"] = hit["phoneNumber"]

        snippet = f"Email '{email}' is registered on {site}."
        if hit.get("emailrecovery"):
            snippet += f" Recovery hint: {hit['emailrecovery']}."
        if hit.get("phoneNumber"):
            snippet += f" Phone hint: {hit['phoneNumber']}."

        findings.append({
            "source_type":          "api",
            "source_name":          f"Holehe — {site}",
            "source_url":           domain,
            "matched_fields":       ["email"],
            "matched_data":         extra,
            "snippet":              snippet,
            "category":             "social_trace",
            "match_type":           "confirmed",
            "linked_identifiers":   [],
            "confirmed_by_service": True,
        })

    return {
        "findings":        findings,
        "api_calls_made":  total_checked,
        "sources_checked": len(hits),
        "pages_scanned":   0,
        "errors":          errors[:15],  # cap — could be many timeouts
        "service_name":    SERVICE_NAME,
    }

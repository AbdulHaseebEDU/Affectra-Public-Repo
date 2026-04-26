# takes a list of ExposureResult-like dicts and returns AI commentary for each
# one Gemini call for the whole batch — per-finding commentary + an overall summary
# returns an empty/error result gracefully if the key is missing or the call fails

from __future__ import annotations

import json
from typing import Any

from ..external_apis.api_keys.keys import get_key
from .gemini import generate

# cap: only the top N findings (by risk_score) are sent to Gemini
# keeps the prompt and response within the model's output token budget
_MAX_FINDINGS = 30

# fields we send to Gemini — enough context without flooding the prompt.
# mitigation is intentionally excluded: we want AI to write fresh, finding-specific
# steps rather than just restating the static fallback list we already have.
_FINDING_FIELDS = (
    "id",
    "source_name",
    "source_url",
    "classification",
    "risk_level",
    "risk_score",
    "confidence_level",
    "confidence_score",
    "matched_fields",
    "matched_data",
    "snippet",
)

_SYSTEM_PROMPT = """\
You are a cybersecurity analyst reviewing PII (Personally Identifiable Information) \
exposure findings for a person who ran a digital self-check. For each finding you \
must write BOTH a plain-English commentary AND a specific action list. A non-technical \
person will read this and act on it immediately.

Rules for commentary:
- Be specific — name the site, the data type, the actual risk
- {per_finding_length_rule}
- Be direct — say what the risk IS, not just that "it could be concerning"
- Do not repeat the source name or risk level — the UI already shows those
- No bullet points inside commentary strings

Rules for actions (REQUIRED for every finding — never omit):
- Write exactly {mitigation_steps} steps per finding
- Tailor every step to THIS specific finding (source name, exposed data type)
- First step = the single most urgent thing to do RIGHT NOW
- Each step is one short, actionable sentence — no sub-bullets
- Reference the actual site or exposed field by name
- Do NOT copy generic advice — make it specific to what was actually found

Rules for overall_summary:
- 3-5 sentences connecting all findings into one clear picture
- {omitted_note}

You MUST respond with ONLY valid JSON. Use EXACTLY this structure — commentary and \
actions are nested together inside each finding so neither can be omitted:
{{
  "findings": {{
    "<finding_id>": {{
      "commentary": "<plain-English explanation of this specific finding>",
      "actions": ["<step 1>", "<step 2>", "<step 3>"]
    }},
    ...
  }},
  "overall_summary": "<3-5 sentence narrative>"
}}"""


def _slim_finding(f: dict[str, Any]) -> dict[str, Any]:
    # strip the finding down to only the fields Gemini needs
    return {k: f.get(k) for k in _FINDING_FIELDS if f.get(k) is not None}


def analyse_findings(
    findings: list[dict[str, Any]],
    query_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # returns {"per_finding": {id: str}, "per_finding_mitigations": {id: [str]},
    #          "overall_summary": str, "error": str|None}
    empty: dict[str, Any] = {
        "per_finding": {},
        "per_finding_mitigations": {},
        "overall_summary": "",
        "error": None,
    }

    api_key = get_key("GEMINI_API_KEY")
    if not api_key:
        empty["error"] = "KEY_ISSUE:No Gemini API key is set. Tap \"Add key\" to configure it."
        return empty

    if not findings:
        empty["error"] = "No findings to analyse."
        return empty

    total_count = len(findings)

    # sort by risk_score desc so the most important findings are always included
    sorted_findings = sorted(
        findings,
        key=lambda f: float(f.get("risk_score") or 0),
        reverse=True,
    )
    capped = sorted_findings[:_MAX_FINDINGS]
    omitted = total_count - len(capped)

    # adjust instructions based on how many findings we're sending
    n = len(capped)
    if n > 15:
        per_finding_length_rule = (
            "Keep each per-finding comment to 1 sentence maximum — "
            "there are many findings so brevity is essential"
        )
        mitigation_steps = "3"   # fewer steps when there are many findings
    else:
        per_finding_length_rule = (
            "Keep each per-finding comment to 2-3 sentences maximum"
        )
        mitigation_steps = "4-5"

    if omitted:
        omitted_note = (
            f"Note: {omitted} lower-risk finding(s) were omitted from this list "
            f"to keep the response concise — mention this briefly in the overall summary"
        )
    else:
        omitted_note = "All findings are included below"

    system_prompt = _SYSTEM_PROMPT.format(
        per_finding_length_rule=per_finding_length_rule,
        mitigation_steps=mitigation_steps,
        omitted_note=omitted_note,
    )

    slim = [_slim_finding(f) for f in capped]

    user_parts: list[str] = []
    if query_summary:
        user_parts.append(
            f"Query context: {json.dumps(query_summary, default=str)}"
        )
    user_parts.append(
        f"Findings ({len(slim)} of {total_count} total, highest-risk first):\n"
        f"{json.dumps(slim, indent=2, default=str)}"
    )

    full_prompt = system_prompt + "\n\n" + "\n\n".join(user_parts)

    try:
        raw = generate(full_prompt, api_key)
    except Exception as exc:  # noqa: BLE001
        empty["error"] = _friendly_error(exc)
        return empty

    # parse the JSON response
    try:
        text = raw.strip()
        # Gemini sometimes wraps in ```json ... ```
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(
                ln for ln in lines if not ln.strip().startswith("```")
            ).strip()

        result = json.loads(text)

        # Unpack the nested structure:
        # { "findings": { id: { "commentary": str, "actions": [str] } }, "overall_summary": str }
        per_finding:      dict[str, str]       = {}
        per_finding_mit:  dict[str, list[str]] = {}

        raw_findings = result.get("findings") or {}
        if isinstance(raw_findings, dict):
            for fid, data in raw_findings.items():
                fid = str(fid)
                if not isinstance(data, dict):
                    continue
                commentary = data.get("commentary")
                if commentary:
                    per_finding[fid] = str(commentary)
                actions = data.get("actions") or []
                if isinstance(actions, list) and actions:
                    per_finding_mit[fid] = [str(s) for s in actions if s]

        # Graceful fallback: if the model used the old flat format, accept that too
        if not per_finding:
            flat = result.get("per_finding") or {}
            if isinstance(flat, dict):
                per_finding = {str(k): str(v) for k, v in flat.items() if v}
        if not per_finding_mit:
            flat_mit = result.get("per_finding_mitigations") or {}
            if isinstance(flat_mit, dict):
                for k, v in flat_mit.items():
                    if isinstance(v, list) and v:
                        per_finding_mit[str(k)] = [str(s) for s in v if s]

        return {
            "per_finding": per_finding,
            "per_finding_mitigations": per_finding_mit,
            "overall_summary": result.get("overall_summary", ""),
            "error": None,
        }

    except (json.JSONDecodeError, ValueError):
        # Response came back but wasn't valid JSON — non-fatal, just skip AI
        empty["error"] = "KEY_ISSUE:ai_unavailable"
        return empty


def _friendly_error(exc: Exception) -> str:
    """Map a raw Gemini exception to a UI-friendly error code string.

    The frontend checks for the KEY_ISSUE / QUOTA / TIMEOUT prefixes to decide
    which action hint to render (e.g. an "Open Dev Menu" button for key errors).
    """
    msg = str(exc).lower()

    if "expired" in msg or "api_key_invalid" in msg or "api key" in msg:
        return "KEY_ISSUE:Your Gemini API key has expired. Tap \"Update key\" to renew it."

    if "not configured" in msg or "gemini_api_key" in msg:
        return "KEY_ISSUE:No Gemini API key is set. Tap \"Add key\" to configure it."

    if "429" in msg or "quota" in msg or "rate" in msg or "resource_exhausted" in msg:
        return "QUOTA:Gemini quota reached — AI analysis will retry automatically next scan."

    if "timeout" in msg or "timed out" in msg:
        return "TIMEOUT:Gemini took too long to respond. Try again or switch to a lighter scan mode."

    if "all models exhausted" in msg:
        return "KEY_ISSUE:All Gemini models failed. Your API key may be expired or over quota."

    return f"UNAVAILABLE:AI analysis unavailable ({exc})"

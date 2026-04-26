# attaches actionable remediation steps to each exposure and, where relevant,
# a GDPR / CCPA deletion email template the user can send to the site operator.
#
# guidance is category-first with source-name overrides for well-known services
# — so a HIBP finding gets more specific steps than a generic breach finding.

from __future__ import annotations

import uuid
from datetime import date
from typing import List
from urllib.parse import urlparse

from ..application_requisites.models import (
    ExposureCategory,
    ExposureResult,
    NormalizedQuery,
)


# ── category-level guidance ───────────────────────────────────────────────────

_GUIDANCE: dict[ExposureCategory, List[str]] = {
    ExposureCategory.POTENTIAL_BREACH: [
        "Change the password for every account that uses this email address immediately.",
        "Enable two-factor authentication (2FA) on all accounts tied to this email.",
        "Check haveibeenpwned.com to see the full list of breaches your email appears in.",
        "If you reuse passwords, treat every account sharing the leaked password as compromised.",
        "Consider a password manager (Bitwarden, 1Password) to generate and store unique passwords.",
    ],
    ExposureCategory.PASTE_EXPOSURE: [
        "Treat every credential visible in the paste as fully compromised — change it immediately.",
        "Check whether API keys, tokens, or secret links are included and revoke them.",
        "Report the paste to the hosting site's abuse team via their takedown form.",
        "Monitor your accounts for unusual login activity over the next 30 days.",
        "Set up login-alert notifications on your most critical accounts.",
    ],
    ExposureCategory.DATA_BROKER: [
        "Submit this site's opt-out form to request removal of your listing.",
        "Send a GDPR Article 17 / CCPA deletion request using the template below.",
        "Retain the confirmation email as proof — operators must respond within 30 days (GDPR).",
        "Search your name on other data-broker sites and repeat the opt-out for each.",
        "Consider a service like DeleteMe or Privacy Bee to automate bulk opt-outs.",
    ],
    ExposureCategory.CODE_REPOSITORY: [
        "Audit the repository for hardcoded secrets, API keys, passwords, and private URLs.",
        "Revoke and rotate every credential that appears in the commit history.",
        "Use `git filter-repo` or BFG Repo-Cleaner to permanently remove sensitive data from history.",
        "Add a pre-commit hook (Gitleaks, truffleHog) to prevent future secret leaks.",
        "If the repo is public, assume the data is already indexed — rotate credentials first.",
    ],
    ExposureCategory.DOCUMENT: [
        "Contact the hosting platform to request removal of the document.",
        "If the document is yours, redact personal information before republishing.",
        "Submit a privacy takedown notice if the site provides one.",
        "Search for cached copies on Google / Bing and request removal via their webmaster tools.",
    ],
    ExposureCategory.HISTORICAL_CACHE: [
        "Submit a removal request to the Internet Archive at archive.org/services/contact.php.",
        "Use Google's 'Remove Outdated Content' tool if the live page no longer shows the data.",
        "Verify whether the original live page still exposes the same information.",
        "Cache removal can take weeks — focus on removing data from the live source first.",
    ],
    ExposureCategory.PUBLIC_DIRECTORY: [
        "Look for a 'remove my listing' or 'opt out' link on the site — most directories provide one.",
        "Send a GDPR / CCPA deletion request using the template below if no self-serve option exists.",
        "Mark controllable fields (phone, address) as private on the source platform.",
        "Removal from one directory does not remove you from others — check each individually.",
    ],
    ExposureCategory.FORUM_MENTION: [
        "Ask the forum moderators to redact or anonymise your personal data in the post.",
        "If the account is yours, edit or delete the post directly.",
        "Contact the platform's privacy team if moderation does not resolve it.",
        "Request de-indexing from Google using 'Remove Outdated Content' once the post is gone.",
    ],
    ExposureCategory.SOCIAL_TRACE: [
        "Review the platform's privacy settings and limit who can see each profile field.",
        "Remove or obscure sensitive fields (phone, full name, location) from your public profile.",
        "Consider whether maintaining a public presence on this platform is necessary.",
        "Check that linked accounts (e.g. 'login with Google') don't expose more data than intended.",
    ],
    ExposureCategory.UNKNOWN: [
        "Review the page manually to determine whether the exposure is intentional.",
        "If it contains personal data you didn't consent to share, contact the site operator.",
        "Document the finding with a screenshot before requesting removal — pages can disappear.",
    ],
}


# ── source-name overrides ─────────────────────────────────────────────────────
# More specific than category guidance — used when the adapter is a known service.

_SOURCE_OVERRIDES: dict[str, List[str]] = {
    "XposedOrNot": [
        "Your email was found in a public breach database — change associated passwords immediately.",
        "Visit xposedornot.com to see the full list of breaches your email appears in.",
        "Enable 2FA on accounts using this email, starting with email, banking, and social media.",
        "Use a unique, random password for every service — a password manager makes this manageable.",
    ],
    "HIBP Pwned Passwords": [
        "The string checked was found in a dataset of passwords leaked in past breaches.",
        "If you use this as a password anywhere, change it on every affected account immediately.",
        "Never reuse passwords — one breach gives attackers access to every account sharing it.",
        "Enable 2FA on every account that accepts it.",
    ],
    "HIBP Pwned Passwords (k-anonymity)": [
        "The string checked was found in a dataset of passwords leaked in past breaches.",
        "If you use this as a password anywhere, change it on every affected account immediately.",
        "Never reuse passwords — one breach gives attackers access to every account sharing it.",
        "Enable 2FA on every account that accepts it.",
    ],
    "Gravatar": [
        "Your Gravatar profile is publicly visible and links your email to a profile photo.",
        "Log in to gravatar.com and review which details are marked public.",
        "Set your profile visibility to private, or delete the account if you no longer use it.",
    ],
    "Holehe": [
        "Your email is registered on this platform and is publicly discoverable.",
        "If you no longer use this account, log in and delete it to reduce your exposure surface.",
        "If you don't recognise this service, someone may have registered using your email.",
    ],
    "Psbdmp": [
        "Your identifier was found in a paste indexed by Psbdmp — treat the content as public.",
        "If credentials appear in the paste, rotate them immediately.",
        "Report the paste to psbdmp.ws if it contains sensitive personal data.",
    ],
    "GitHub": [
        "Your identifier appears in a public GitHub repository — check whether secrets are exposed.",
        "Rotate any API keys, tokens, or passwords visible in the repository.",
        "Use `git filter-repo` to purge sensitive data from the commit history if needed.",
        "Enable GitHub's built-in secret scanning to prevent future leaks.",
    ],
}


# ── deletion email template ───────────────────────────────────────────────────

_EMAIL_TEMPLATE = """\
Subject: Personal Data Erasure Request — Ref {ref_id}

Dear {host} Data Controller,

I am writing to formally request the erasure of my personal data from your
service under Article 17 of the UK/EU General Data Protection Regulation
(GDPR) and/or the California Consumer Privacy Act (CCPA §1798.105), where
applicable.

Reference ID : {ref_id}
Date of request : {today}

The specific URL where my information appears:
  {url}

The following personal identifiers belonging to me are present at that location:
{identifiers}

Please confirm receipt of this request and the actions you will take to
permanently remove the listed data. Under the GDPR you are required to
respond within 30 calendar days of receipt.

If you require proof of identity before processing this request, please
advise on your preferred verification method.

Yours sincerely,
{signatory}
""".strip()

_TEMPLATE_CATEGORIES = {
    ExposureCategory.DATA_BROKER,
    ExposureCategory.PUBLIC_DIRECTORY,
    ExposureCategory.DOCUMENT,
    ExposureCategory.FORUM_MENTION,
    ExposureCategory.SOCIAL_TRACE,
    ExposureCategory.HISTORICAL_CACHE,
}


def _host_of(url: str) -> str:
    try:
        return urlparse(url).netloc or "the website operator"
    except Exception:
        return "the website operator"


# ── public entry point ────────────────────────────────────────────────────────

def apply_mitigations(
    exposures: List[ExposureResult],
    query: NormalizedQuery,
) -> List[ExposureResult]:
    """Attach remediation steps and, where appropriate, a deletion email template."""
    today     = date.today().isoformat()
    signatory = query.full_name or query.email or "the data subject"

    for e in exposures:
        # Source-name override wins over category-level guidance when available.
        e.mitigation = list(
            _SOURCE_OVERRIDES.get(e.source_name)
            or _GUIDANCE.get(e.classification)
            or _GUIDANCE[ExposureCategory.UNKNOWN]
        )

        # Deletion template only where a named site operator can be addressed.
        if e.classification in _TEMPLATE_CATEGORIES:
            identifiers = "\n".join(
                f"  • {k}: {v}"
                for k, v in e.matched_data.items()
                if k in ("email", "full_name", "phone", "username")
            ) or "  • (see URL for details)"

            e.deletion_email_template = _EMAIL_TEMPLATE.format(
                ref_id=uuid.uuid4().hex[:12].upper(),
                host=_host_of(e.source_url),
                today=today,
                url=e.source_url,
                identifiers=identifiers,
                signatory=signatory,
            )

    return exposures

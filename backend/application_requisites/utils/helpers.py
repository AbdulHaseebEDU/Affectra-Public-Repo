# shared utilities — URL classifier, shared user-agent string
# classify_url uses domain + path heuristics to assign an ExposureCategory.
# the lookup order matters: more specific categories are checked before broad ones.

from __future__ import annotations

from urllib.parse import urlparse

from ..models import ExposureCategory

USER_AGENT = (
    "Affectra/1.0 "
    "(+academic prototype; PII self-check tool; responsible-use only)"
)

# ── domain keyword lists ──────────────────────────────────────────────────────
# Each tuple entry is a substring matched against the full netloc (lowercased).
# Entries are checked in the order the categories appear in classify_url.

_BREACH = (
    "haveibeenpwned.com", "xposedornot.com", "dehashed.com",
    "leakcheck.io", "leak-lookup.com", "weleakinfo", "snusbase.com",
    "scylla.sh", "breachdirectory",
)
_CODE = (
    "github.com", "gitlab.com", "bitbucket.org", "gist.github.com",
    "codeberg.org", "sourcehut.org",
)
_PASTE = (
    "pastebin.com", "ghostbin", "hastebin", "dpaste", "rentry.co",
    "justpaste", "psbdmp", "paste.", "pasted.co", "privatebin",
    "0bin.net", "pastelink", "controlc.com",
)
_ARCHIVE = (
    "web.archive.org", "archive.org", "archive.ph", "archive.is",
    "cachedview", "webcache.googleusercontent",
)
_BROKER = (
    "intelius", "spokeo", "whitepages", "beenverified", "radaris",
    "mylife", "peoplefinder", "peekyou", "fastpeoplesearch",
    "truepeoplesearch", "pipl", "peoplelooker", "checkpeople",
    "instantcheckmate", "truthfinder", "usphonebook", "thatsthem",
    "clustrmaps", "411.com",
)
_FORUM = (
    "reddit.com", "/r/", "forum.", "/forum", "discourse.", "disqus.com",
    "stackoverflow.com", "stackexchange.com", "quora.com",
    "news.ycombinator.com", "community.", "discuss.", "boards.",
    "phpbb", "vbulletin", "xenforo", "hackernews",
)
_SOCIAL = (
    "twitter.com", "x.com", "facebook.com", "linkedin.com",
    "instagram.com", "medium.com", "t.me", "telegra.ph",
    "tiktok.com", "mastodon.", "threads.net", "youtube.com",
    "dev.to", "about.me", "keybase.io", "gravatar.com",
    "holehe", "last.fm", "flickr.com", "tumblr.com",
)
_DIRECTORY = (
    "yellowpages", "directory.", "/directory", "listing.",
    "yelp.com", "opencorporates", "zoominfo", "crunchbase",
    "manta.com", "chamberofcommerce", "dnb.com",
)
_DOCUMENT = (
    "scribd.com", "slideshare.net", "docplayer", "issuu.com",
    "academia.edu", "researchgate.net", "docdroid",
)


def classify_url(url: str) -> ExposureCategory:
    """Map a URL to the most appropriate ExposureCategory using domain heuristics.

    Check order: breach > code > paste > archive > broker > forum >
    social > directory > document > path-level (.pdf) > unknown.
    """
    if not url:
        return ExposureCategory.UNKNOWN

    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    full = host + path   # lets us match path-embedded signals too

    if any(k in host for k in _BREACH):
        return ExposureCategory.POTENTIAL_BREACH
    if any(k in host for k in _CODE):
        return ExposureCategory.CODE_REPOSITORY
    if any(k in host for k in _PASTE):
        return ExposureCategory.PASTE_EXPOSURE
    if any(k in host for k in _ARCHIVE):
        return ExposureCategory.HISTORICAL_CACHE
    if any(k in host for k in _BROKER):
        return ExposureCategory.DATA_BROKER
    if any(k in full for k in _FORUM):
        return ExposureCategory.FORUM_MENTION
    if any(k in host for k in _SOCIAL):
        return ExposureCategory.SOCIAL_TRACE
    if any(k in host for k in _DIRECTORY):
        return ExposureCategory.PUBLIC_DIRECTORY
    if path.endswith(".pdf") or any(k in host for k in _DOCUMENT):
        return ExposureCategory.DOCUMENT

    return ExposureCategory.UNKNOWN

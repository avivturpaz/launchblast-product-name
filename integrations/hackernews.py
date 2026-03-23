"""Hacker News integration — submit posts via form submission."""

import os
import urllib.parse
import urllib.request

from .base import error_response, ok_response

HN_USERNAME = os.environ.get("HN_USERNAME", "")
HN_PASSWORD = os.environ.get("HN_PASSWORD", "")

HN_BASE = "https://news.ycombinator.com"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    "Content-Type": "application/x-www-form-urlencoded",
}


def _make_opener():
    """Create a urllib opener that handles cookies."""
    import http.cookiejar
    jar = http.cookiejar.CookieJar()
    handler = urllib.request.HTTPCookieProcessor(jar)
    return urllib.request.build_opener(handler)


def _login(opener) -> bool:
    """Login to HN. Returns True on success."""
    data = urllib.parse.urlencode({
        "acct": HN_USERNAME,
        "pw": HN_PASSWORD,
        "goto": "news",
    }).encode()
    req = urllib.request.Request(f"{HN_BASE}/login", data=data, method="POST")
    for k, v in _HEADERS.items():
        req.add_header(k, v)
    try:
        with opener.open(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        # Successful login redirects away from /login; bad creds show the form again
        return "Bad login" not in body and "login" not in resp.geturl()
    except Exception:
        return False


def _get_fnid(opener) -> str:
    """Fetch the submit page and extract the fnid hidden field."""
    req = urllib.request.Request(f"{HN_BASE}/submit")
    req.add_header("User-Agent", _HEADERS["User-Agent"])
    try:
        with opener.open(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        # <input type="hidden" name="fnid" value="...">
        import re
        m = re.search(r'name="fnid"\s+value="([^"]+)"', body)
        return m.group(1) if m else ""
    except Exception:
        return ""


def submit_post(title: str, url: str = "", text: str = None) -> dict:
    """Submit a post to Hacker News.

    For link posts supply url. For Ask/Show HN supply text (url may be empty).
    Returns standard response dict with url of submitted post on success.
    """
    if not HN_USERNAME or not HN_PASSWORD:
        return error_response("HN_USERNAME and HN_PASSWORD not set")

    opener = _make_opener()

    if not _login(opener):
        return error_response("HN login failed — check HN_USERNAME / HN_PASSWORD")

    fnid = _get_fnid(opener)
    if not fnid:
        return error_response("Could not fetch HN submit fnid (form may have changed)")

    fields = {"fnid": fnid, "fnop": "submit-page", "title": title}
    if url:
        fields["url"] = url
    if text:
        fields["text"] = text

    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(f"{HN_BASE}/r", data=data, method="POST")
    for k, v in _HEADERS.items():
        req.add_header(k, v)

    try:
        with opener.open(req, timeout=15) as resp:
            final_url = resp.geturl()
        # HN redirects to the item page on success, or back to /submit on failure
        if "item?id=" in final_url:
            return ok_response(url=final_url)
        return error_response(f"Submission may have failed — landed at: {final_url}")
    except Exception as e:
        return error_response(str(e))

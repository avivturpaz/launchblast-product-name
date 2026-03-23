"""Dev.to integration — publish articles via API."""

import json
import os
import urllib.error
import urllib.request

from .base import error_response, ok_response, retry

DEVTO_API_KEY = os.environ.get("DEVTO_API_KEY", "")


@retry(max_attempts=3, base_delay=1.0, exceptions=(urllib.error.URLError,))
def post_article(title: str, body: str, tags: list, published: bool = False) -> dict:
    """Post an article to dev.to.

    Args:
        title: Article title.
        body: Markdown body.
        tags: List of up to 4 tag strings.
        published: False = draft, True = publish immediately.

    Returns:
        Standard response dict with article_id and url on success.
    """
    if not DEVTO_API_KEY:
        return error_response("DEVTO_API_KEY not set")

    payload = json.dumps({
        "article": {
            "title": title,
            "body_markdown": body,
            "tags": tags[:4],
            "published": published,
        }
    }).encode()

    req = urllib.request.Request(
        "https://dev.to/api/articles",
        data=payload,
        method="POST",
    )
    req.add_header("api-key", DEVTO_API_KEY)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "venture-bot/1.0")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        return ok_response(
            url=data.get("url", ""),
            article_id=data["id"],
            title=data["title"],
            published=data.get("published", False),
        )
    except urllib.error.HTTPError as e:
        return error_response(f"HTTP {e.code}: {e.read().decode()[:200]}")
    except Exception as e:
        return error_response(str(e))

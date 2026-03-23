"""Indie Hackers integration — generate 'Show IH' post drafts.

No public API exists, so this generates a ready-to-paste draft and returns
the link to the submission page.
"""

import json
import os
import urllib.request

from .base import error_response, ok_response

IH_SUBMIT_URL = "https://www.indiehackers.com/post/new"


def generate_post_draft(title: str, body: str) -> dict:
    """Return a formatted Show IH draft ready to paste.

    Args:
        title: Post title (should start with "Show IH:" if applicable).
        body: Post body in plain text / markdown.

    Returns:
        Standard response dict with:
          - title: final title string
          - body: final body string
          - url: link to IH new-post page
          - instructions: human-readable next step
    """
    if not title.strip():
        return error_response("title is required")
    if not body.strip():
        return error_response("body is required")

    return ok_response(
        url=IH_SUBMIT_URL,
        title=title.strip(),
        body=body.strip(),
        instructions=(
            f"Go to {IH_SUBMIT_URL}, paste the title and body, then publish."
        ),
    )

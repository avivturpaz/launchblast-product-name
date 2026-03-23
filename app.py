import os
import re
import sqlite3
import urllib.parse
from datetime import datetime, timezone

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

from integrations.devto import post_article
from integrations.hackernews import submit_post


app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET_KEY", "dev-secret-key")

DB_PATH = os.path.join(os.path.dirname(__file__), "data.db")
DEVTO_PUBLISH_IMMEDIATELY = os.environ.get("DEVTO_PUBLISH_IMMEDIATELY", "false").lower() == "true"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_name TEXT NOT NULL,
                product_url TEXT NOT NULL,
                tagline TEXT NOT NULL,
                description TEXT NOT NULL,
                devto_status TEXT NOT NULL DEFAULT 'pending',
                devto_message TEXT NOT NULL DEFAULT '',
                devto_url TEXT NOT NULL DEFAULT '',
                hn_status TEXT NOT NULL DEFAULT 'pending',
                hn_message TEXT NOT NULL DEFAULT '',
                hn_url TEXT NOT NULL DEFAULT '',
                overall_status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def utc_label() -> str:
    return datetime.now(timezone.utc).strftime("%b %d, %Y %H:%M UTC")


def normalize_url(value: str) -> str:
    value = (value or "").strip()
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value
    return ""


def validate_submission(product_name: str, product_url: str, tagline: str, description: str) -> str:
    if not product_name:
        return "Product name is required."
    if not product_url:
        return "A valid product URL is required."
    if not tagline:
        return "Tagline is required."
    if not description:
        return "Description is required."
    return ""


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "", value)
    return value


def derive_tags(product_name: str, tagline: str, description: str) -> list[str]:
    seeds = [product_name, tagline, description, "launch", "startup", "indiehackers"]
    tags: list[str] = []
    seen = set()
    for seed in seeds:
        for word in re.split(r"[\s/|,.;:()\-]+", seed):
            tag = slugify(word)
            if tag and tag not in seen:
                seen.add(tag)
                tags.append(tag)
            if len(tags) == 4:
                return tags
    return tags or ["launch", "startup", "indiehackers", "webdev"]


def build_devto_body(product_name: str, product_url: str, tagline: str, description: str) -> str:
    return (
        f"# {product_name}\n\n"
        f"**{tagline}**\n\n"
        f"{description}\n\n"
        "## Product details\n\n"
        f"- Website: {product_url}\n"
        f"- Launched: {utc_label()}\n\n"
        "## Why I built it\n\n"
        "LaunchBlast packages the launch brief, article draft, and community submission flow in one place so a product announcement can move from form to publishable posts without retyping."
    )


def build_hn_title(product_name: str, tagline: str) -> str:
    title = f"Show HN: {product_name}"
    if tagline:
        title = f"{title} - {tagline}"
    title = re.sub(r"\s+", " ", title).strip()
    return title[:95]


def infer_devto_status(result: dict) -> str:
    if result.get("success"):
        return "published" if result.get("published") else "draft"
    error = (result.get("error") or "").lower()
    if "not set" in error:
        return "not configured"
    return "failed"


def infer_hn_status(result: dict) -> str:
    if result.get("success"):
        return "submitted"
    error = (result.get("error") or "").lower()
    if "not set" in error:
        return "not configured"
    return "failed"


def summarize_overall(devto_status: str, hn_status: str) -> str:
    if devto_status in {"published", "draft"} and hn_status == "submitted":
        return "complete"
    if devto_status == "not configured" and hn_status == "not configured":
        return "needs-config"
    if any(status in {"published", "draft", "submitted"} for status in (devto_status, hn_status)):
        return "partial"
    return "failed"


def fetch_submission(submission_id: int):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM submissions WHERE id = ?",
            (submission_id,),
        ).fetchone()


def fetch_recent_submissions(limit: int = 8):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM submissions ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()


def set_submission_fields(submission_id: int, **fields):
    if not fields:
        return
    with get_db() as conn:
        assignments = ", ".join(f"{key} = ?" for key in fields)
        params = list(fields.values()) + [submission_id]
        conn.execute(
            f"UPDATE submissions SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            params,
        )


def get_env_status():
    return {
        "devto": bool(os.environ.get("DEVTO_API_KEY", "").strip()),
        "hn": bool(os.environ.get("HN_USERNAME", "").strip() and os.environ.get("HN_PASSWORD", "").strip()),
    }


def dashboard_counts():
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT overall_status, COUNT(*) AS count
            FROM submissions
            GROUP BY overall_status
            """
        ).fetchall()
    counts = {"complete": 0, "partial": 0, "needs-config": 0, "failed": 0, "pending": 0}
    for row in rows:
        status = row["overall_status"]
        if status in counts:
            counts[status] = row["count"]
    counts["total"] = sum(counts.values())
    return counts


@app.route("/")
def index():
    return render_template(
        "index.html",
        form_data={
            "product_name": "",
            "product_url": "",
            "tagline": "",
            "description": "",
        },
        error="",
        env_status=get_env_status(),
        dashboard_counts=dashboard_counts(),
        recent_submissions=fetch_recent_submissions(),
    )


@app.route("/pay")
def pay():
    return render_template(
        "pay.html",
        env_status=get_env_status(),
        dashboard_counts=dashboard_counts(),
    )


@app.route("/submit", methods=["POST"])
def submit():
    product_name = request.form.get("product_name", "").strip()
    product_url_raw = request.form.get("product_url", "").strip()
    product_url = normalize_url(product_url_raw)
    tagline = request.form.get("tagline", "").strip()
    description = request.form.get("description", "").strip()

    error = validate_submission(product_name, product_url, tagline, description)
    if error:
        return (
            render_template(
                "index.html",
                form_data={
                    "product_name": product_name,
                    "product_url": product_url_raw,
                    "tagline": tagline,
                    "description": description,
                },
                error=error,
                env_status=get_env_status(),
                dashboard_counts=dashboard_counts(),
                recent_submissions=fetch_recent_submissions(),
            ),
            400,
        )

    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO submissions (
                product_name, product_url, tagline, description,
                devto_status, devto_message, devto_url,
                hn_status, hn_message, hn_url,
                overall_status
            ) VALUES (?, ?, ?, ?, 'pending', '', '', 'pending', '', '', 'pending')
            """,
            (product_name, product_url, tagline, description),
        )
        submission_id = cursor.lastrowid

    devto_result = post_article(
        title=product_name,
        body=build_devto_body(product_name, product_url, tagline, description),
        tags=derive_tags(product_name, tagline, description),
        published=DEVTO_PUBLISH_IMMEDIATELY,
    )
    devto_status = infer_devto_status(devto_result)
    set_submission_fields(
        submission_id,
        devto_status=devto_status,
        devto_message=devto_result.get("error") or ("Posted to dev.to successfully." if devto_result.get("success") else "dev.to submission failed."),
        devto_url=devto_result.get("url", ""),
    )

    hn_result = submit_post(
        title=build_hn_title(product_name, tagline),
        url=product_url,
    )
    hn_status = infer_hn_status(hn_result)
    set_submission_fields(
        submission_id,
        hn_status=hn_status,
        hn_message=hn_result.get("error") or ("Submitted to Hacker News successfully." if hn_result.get("success") else "Hacker News submission failed."),
        hn_url=hn_result.get("url", ""),
    )

    set_submission_fields(
        submission_id,
        overall_status=summarize_overall(devto_status, hn_status),
    )

    return redirect(url_for("submission_detail", submission_id=submission_id))


@app.route("/submission/<int:submission_id>")
def submission_detail(submission_id: int):
    submission = fetch_submission(submission_id)
    if not submission:
        abort(404)
    return render_template(
        "submission.html",
        submission=submission,
        env_status=get_env_status(),
        dashboard_counts=dashboard_counts(),
    )


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))


init_db()

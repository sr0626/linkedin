"""
Quick test: send the email report using posts already in data/posts.db.
No scraping, no AI calls. Uses the same generate_email_html() + send_email_report()
path that main.py uses.

Usage:
    .venv/bin/python3 test_email.py
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone

from src.config import load_config
from src.models import Post, ScoredPost
from src.reporting import generate_email_html
from src.emailer import send_email_report


def load_posts_from_db(db_path: str) -> list[ScoredPost]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM posts ORDER BY priority_score DESC"
    ).fetchall()
    conn.close()

    scored: list[ScoredPost] = []
    for row in rows:
        post_date = None
        if row["post_date"]:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    post_date = datetime.strptime(row["post_date"], fmt)
                    break
                except ValueError:
                    continue

        post = Post(
            post_url=row["post_url"] or "",
            keyword=row["keyword"] or "",
            author=row["author"] or "",
            post_snippet=row["post_snippet"] or "",
            likes=int(row["likes"] or 0),
            views=int(row["views"] or 0),
            post_date=post_date,
            post_age_days=float(row["post_age_days"]) if row["post_age_days"] is not None else None,
            collected_at=datetime.now(timezone.utc),
            raw_date_str=row["post_date"] or "",
        )
        sp = ScoredPost(
            post=post,
            relevance_score=float(row["relevance_score"] or 0),
            engagement_score=float(row["engagement_score"] or 0),
            response_value_score=float(row["response_value_score"] or 0),
            freshness_score=float(row["freshness_score"] or 0),
            trending_score=float(row["trending_score"] or 0),
            priority_score=float(row["priority_score"] or 0),
            respond_recommendation=row["respond_recommendation"] or "no",
            response_mode=row["response_mode"] or "engage",
            response_reason=row["response_reason"] or "",
            suggested_response=row["suggested_response"] or "",
            suggested_response_2=row["suggested_response_2"] or "",
            is_within_lookback=bool(row["is_within_lookback"]),
            category=row["category"] or "other",
        )
        scored.append(sp)

    return scored


def main() -> None:
    config = load_config("config.yaml")
    db_path = f"{config.output.data_dir}/posts.db"

    print(f"Loading posts from {db_path} ...")
    posts = load_posts_from_db(db_path)

    if not posts:
        print("No posts found in database. Run main.py first.")
        sys.exit(1)

    # Apply same category exclusions as main.py
    if config.categories.exclude_categories:
        before = len(posts)
        posts = [p for p in posts if p.category not in config.categories.exclude_categories]
        print(f"Excluded {before - len(posts)} posts in categories: {config.categories.exclude_categories}")

    actionable = [p for p in posts if p.respond_recommendation in ("yes", "maybe")]
    print(f"Total posts: {len(posts)}  |  Actionable (Respond/Consider): {len(actionable)}")

    if not config.email.to or not config.email_from or not config.email_password:
        print("\nERROR: Missing email config.")
        print("  config.yaml → email.to must be set")
        print("  .env → EMAIL_FROM and EMAIL_PASSWORD must be set")
        sys.exit(1)

    run_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\nGenerating email HTML ...")
    email_html = generate_email_html(posts, config, run_ts)

    print(f"Sending to {config.email.to} from {config.email_from} ...")
    ok = send_email_report(
        html_content=email_html,
        to_addr=config.email.to,
        from_addr=config.email_from,
        password=config.email_password,
        subject=f"[TEST] Amazon Connect Intelligence · {run_ts}",
    )

    if ok:
        print(f"\nEmail sent successfully to {config.email.to}")
    else:
        print("\nEmail send failed — check logs above for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()

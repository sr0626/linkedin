from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from src.models import Post, ScoredPost

logger = logging.getLogger("linkedin_scraper")

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS posts (
    post_url              TEXT PRIMARY KEY,
    collected_at          TEXT,
    keyword               TEXT,
    author                TEXT,
    post_snippet          TEXT,
    likes                 INTEGER,
    views                 INTEGER,
    post_date             TEXT,
    post_age_days         REAL,
    relevance_score       REAL,
    engagement_score      REAL,
    response_value_score  REAL,
    freshness_score       REAL,
    trending_score        REAL,
    priority_score        REAL,
    respond_recommendation TEXT,
    response_reason       TEXT,
    response_mode         TEXT,
    suggested_response    TEXT,
    suggested_response_2  TEXT,
    is_within_lookback    INTEGER,
    category              TEXT DEFAULT 'other',
    last_updated          TEXT
);
"""

UPSERT_SQL = """
INSERT INTO posts (
    post_url, collected_at, keyword, author, post_snippet,
    likes, views, post_date, post_age_days,
    relevance_score, engagement_score, response_value_score,
    freshness_score, trending_score, priority_score,
    respond_recommendation, response_reason, response_mode,
    suggested_response, suggested_response_2, is_within_lookback, category, last_updated
) VALUES (
    :post_url, :collected_at, :keyword, :author, :post_snippet,
    :likes, :views, :post_date, :post_age_days,
    :relevance_score, :engagement_score, :response_value_score,
    :freshness_score, :trending_score, :priority_score,
    :respond_recommendation, :response_reason, :response_mode,
    :suggested_response, :suggested_response_2, :is_within_lookback, :category, :last_updated
)
ON CONFLICT(post_url) DO UPDATE SET
    collected_at          = excluded.collected_at,
    keyword               = excluded.keyword,
    author                = excluded.author,
    post_snippet          = excluded.post_snippet,
    likes                 = excluded.likes,
    views                 = excluded.views,
    post_date             = excluded.post_date,
    post_age_days         = excluded.post_age_days,
    relevance_score       = excluded.relevance_score,
    engagement_score      = excluded.engagement_score,
    response_value_score  = excluded.response_value_score,
    freshness_score       = excluded.freshness_score,
    trending_score        = excluded.trending_score,
    priority_score        = excluded.priority_score,
    respond_recommendation = excluded.respond_recommendation,
    response_reason       = excluded.response_reason,
    response_mode         = excluded.response_mode,
    suggested_response    = excluded.suggested_response,
    suggested_response_2  = excluded.suggested_response_2,
    is_within_lookback    = excluded.is_within_lookback,
    category              = excluded.category,
    last_updated          = excluded.last_updated;
"""


class StorageManager:
    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute(CREATE_TABLE_SQL)
        self._migrate()
        self._conn.commit()
        logger.debug(f"Storage initialized at {db_path}")

    def _migrate(self) -> None:
        """Add new columns to existing databases without dropping data."""
        existing = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(posts)").fetchall()
        }
        if "suggested_response_2" not in existing:
            self._conn.execute(
                "ALTER TABLE posts ADD COLUMN suggested_response_2 TEXT DEFAULT ''"
            )
            logger.debug("Migrated posts table: added suggested_response_2 column")

    def needs_ai_rescore(self, post: Post) -> bool:
        """Return True if this post is new or its likes/views have changed."""
        row = self._conn.execute(
            "SELECT likes, views FROM posts WHERE post_url = ?", (post.post_url,)
        ).fetchone()
        if row is None:
            return True
        return int(row["likes"]) != post.likes or int(row["views"]) != post.views

    def get_cached_scored_post(self, post: Post) -> Optional[ScoredPost]:
        """Return a ScoredPost built from cached DB data, or None if not found."""
        row = self._conn.execute(
            "SELECT * FROM posts WHERE post_url = ?", (post.post_url,)
        ).fetchone()
        if row is None:
            return None
        try:
            return ScoredPost(
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
        except Exception as e:
            logger.warning(f"Failed to deserialize cached post {post.post_url}: {e}")
            return None

    def upsert(self, sp: ScoredPost) -> None:
        now = datetime.now(timezone.utc).isoformat()
        params = {
            "post_url": sp.post_url,
            "collected_at": sp.collected_at.isoformat(),
            "keyword": sp.keyword,
            "author": sp.author,
            "post_snippet": sp.post_snippet,
            "likes": sp.likes,
            "views": sp.views,
            "post_date": sp.post_date_str,
            "post_age_days": sp.post_age_days,
            "relevance_score": sp.relevance_score,
            "engagement_score": sp.engagement_score,
            "response_value_score": sp.response_value_score,
            "freshness_score": sp.freshness_score,
            "trending_score": sp.trending_score,
            "priority_score": sp.priority_score,
            "respond_recommendation": sp.respond_recommendation,
            "response_reason": sp.response_reason,
            "response_mode": sp.response_mode,
            "suggested_response": sp.suggested_response,
            "suggested_response_2": sp.suggested_response_2,
            "is_within_lookback": int(sp.is_within_lookback),
            "category": sp.category,
            "last_updated": now,
        }
        self._conn.execute(UPSERT_SQL, params)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

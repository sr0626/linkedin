from __future__ import annotations

import logging
from typing import Optional

try:
    from langdetect import detect, LangDetectException
    _LANGDETECT_AVAILABLE = True
except ImportError:
    _LANGDETECT_AVAILABLE = False

from src.config import FilterConfig
from src.models import Post

logger = logging.getLogger("linkedin_scraper")


def _is_within_lookback(post: Post, lookback_days: int, include_if_no_date: bool) -> bool:
    """Return True if post falls within the lookback window."""
    if post.post_age_days is None:
        return include_if_no_date
    return post.post_age_days <= lookback_days


def _is_english(text: str) -> bool:
    """Return True if the text is detected as English (or detection fails gracefully)."""
    if not _LANGDETECT_AVAILABLE:
        return True
    if not text or len(text.strip()) < 20:
        return True  # Too short to detect reliably — keep it
    try:
        return detect(text) == "en"
    except Exception:
        return True  # On any detection error, include the post


def apply_filters(
    posts: list[Post],
    config: FilterConfig,
) -> tuple[list[Post], list[Post]]:
    """
    Apply all filter criteria.
    Returns (passed, rejected) — each is a list of Post objects.
    """
    passed: list[Post] = []
    rejected: list[Post] = []

    for post in posts:
        reasons: list[str] = []

        if post.likes < config.min_likes:
            reasons.append(f"likes={post.likes} < {config.min_likes}")

        if post.views < config.min_views:
            reasons.append(f"views={post.views} < {config.min_views}")

        within = _is_within_lookback(post, config.lookback_days, config.include_if_no_date)
        if not within:
            reasons.append(
                f"age={post.post_age_days}d > lookback={config.lookback_days}d"
            )

        if not _is_english(post.post_snippet):
            reasons.append("non-english")

        if reasons:
            logger.debug(f"Rejected [{post.post_url}]: {'; '.join(reasons)}")
            rejected.append(post)
        else:
            passed.append(post)

    return passed, rejected

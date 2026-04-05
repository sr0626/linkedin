from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse, urlunparse

from src.models import Post

logger = logging.getLogger("linkedin_scraper")


def normalize_count(value: str) -> int:
    """Convert '1.2K', '3.4M', '1,234' or plain numbers to int."""
    if not value:
        return 0
    value = value.strip().replace(",", "").replace("\u202f", "").replace("\xa0", "")
    # Strip any non-numeric suffix text (e.g., "impressions", "reactions")
    # Keep only the leading numeric+suffix portion
    match = re.match(r"([\d.]+)\s*([KkMmBb]?)", value)
    if not match:
        return 0
    num_str, suffix = match.group(1), match.group(2).upper()
    multipliers = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    try:
        return int(float(num_str) * multipliers.get(suffix, 1))
    except ValueError:
        return 0


def parse_relative_date(text: str) -> Optional[datetime]:
    """
    Parse LinkedIn relative timestamps into UTC datetimes.
    Handles: '3h', '2d', '1w', '1mo', '2mo', '1yr', '2 hours ago',
             ISO datetime strings like '2024-01-15T10:00:00'.
    """
    if not text:
        return None

    text = text.strip()

    # Try ISO / absolute datetime first
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    now = datetime.now(timezone.utc)
    text_lower = text.lower()

    patterns = [
        (r"(\d+)\s*(?:second|sec|s)s?\b", "seconds"),
        (r"(\d+)\s*(?:minute|min|m)s?\b", "minutes"),
        (r"(\d+)\s*(?:hour|hr|h)s?\b", "hours"),
        (r"(\d+)\s*(?:day|d)s?\b", "days"),
        (r"(\d+)\s*(?:week|wk|w)s?\b", "weeks"),
        (r"(\d+)\s*(?:month|mo)s?\b", "months"),
        (r"(\d+)\s*(?:year|yr|y)s?\b", "years"),
    ]

    for pattern, unit in patterns:
        m = re.search(pattern, text_lower)
        if m:
            n = int(m.group(1))
            if unit == "seconds":
                return now - timedelta(seconds=n)
            elif unit == "minutes":
                return now - timedelta(minutes=n)
            elif unit == "hours":
                return now - timedelta(hours=n)
            elif unit == "days":
                return now - timedelta(days=n)
            elif unit == "weeks":
                return now - timedelta(weeks=n)
            elif unit == "months":
                return now - timedelta(days=n * 30)
            elif unit == "years":
                return now - timedelta(days=n * 365)

    return None


def canonical_url(url: str) -> str:
    """Strip query params and fragments from a LinkedIn URL."""
    if not url:
        return url
    # Ensure absolute URL
    if url.startswith("//"):
        url = "https:" + url
    elif not url.startswith("http"):
        url = "https://www.linkedin.com" + url
    parsed = urlparse(url)
    return urlunparse(parsed._replace(query="", fragment=""))


def compute_age_days(post_date: Optional[datetime]) -> Optional[float]:
    if post_date is None:
        return None
    now = datetime.now(timezone.utc)
    if post_date.tzinfo is None:
        post_date = post_date.replace(tzinfo=timezone.utc)
    delta = now - post_date
    return round(delta.total_seconds() / 86400, 2)


def extract_profile_id(url: str) -> Optional[str]:
    """Extract the LinkedIn profile ID slug from a /in/{id}/ URL."""
    if not url:
        return None
    m = re.search(r'linkedin\.com/in/([^/?#]+)', url)
    if m:
        return m.group(1).strip("/")
    return None


def parse_posts(raw_posts: list[dict]) -> list[Post]:
    """Convert list of raw dicts from scraper into Post objects."""
    posts: list[Post] = []
    seen_urls: set[str] = set()

    for raw in raw_posts:
        try:
            url = canonical_url(raw.get("post_url", ""))
            # If no post URL found, derive a stable key from author + snippet
            if not url:
                author_key = raw.get("author", "unknown").replace(" ", "_")[:30]
                snippet_key = raw.get("post_snippet", "")[:40].replace(" ", "_")
                url = f"https://www.linkedin.com/search/unknown/{author_key}/{snippet_key}"
            if url in seen_urls:
                continue
            seen_urls.add(url)

            raw_date_str = raw.get("raw_date_str", "")
            post_date = parse_relative_date(raw_date_str)
            age_days = compute_age_days(post_date)

            likes = normalize_count(raw.get("likes_str", "0"))
            views = normalize_count(raw.get("views_str", "0"))

            author_profile_url = canonical_url(raw.get("author_profile_url", ""))

            post = Post(
                post_url=url,
                keyword=raw.get("keyword", ""),
                author=raw.get("author", "Unknown"),
                post_snippet=raw.get("post_snippet", "")[:300],
                likes=likes,
                views=views,
                post_date=post_date,
                post_age_days=age_days,
                collected_at=datetime.now(timezone.utc),
                raw_date_str=raw_date_str,
                author_profile_url=author_profile_url,
            )
            posts.append(post)
        except Exception as e:
            logger.warning(f"Failed to parse raw post: {e} | raw={raw}")

    return posts

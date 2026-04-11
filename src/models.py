from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Post:
    post_url: str
    keyword: str
    author: str
    post_snippet: str
    likes: int
    views: int
    post_date: Optional[datetime]
    post_age_days: Optional[float]
    collected_at: datetime
    raw_date_str: str = ""
    author_profile_url: str = ""  # used to auto-discover prolific technical posters

    # Convenience property — used by reporting/storage
    @property
    def post_date_str(self) -> str:
        if self.post_date:
            return self.post_date.strftime("%Y-%m-%d %H:%M:%S")
        return self.raw_date_str or ""


@dataclass
class ScoredPost:
    post: Post
    relevance_score: float
    engagement_score: float
    response_value_score: float
    freshness_score: float
    trending_score: float
    priority_score: float
    respond_recommendation: str   # yes / maybe / no
    response_mode: str
    response_reason: str
    suggested_response: str
    suggested_response_2: str
    is_within_lookback: bool
    category: str = "other"       # technical / hiring / other

    # Delegation helpers so callers can use scored_post.post_url etc.
    @property
    def post_url(self) -> str:
        return self.post.post_url

    @property
    def keyword(self) -> str:
        return self.post.keyword

    @property
    def author(self) -> str:
        return self.post.author

    @property
    def post_snippet(self) -> str:
        return self.post.post_snippet

    @property
    def likes(self) -> int:
        return self.post.likes

    @property
    def views(self) -> int:
        return self.post.views

    @property
    def post_date_str(self) -> str:
        return self.post.post_date_str

    @property
    def collected_at(self) -> datetime:
        return self.post.collected_at

    @property
    def post_age_days(self) -> Optional[float]:
        return self.post.post_age_days

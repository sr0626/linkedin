from __future__ import annotations

import json
import logging
import time
from typing import Optional

from openai import OpenAI

from src.config import AIConfig, CategoriesConfig
from src.models import Post, ScoredPost

logger = logging.getLogger("linkedin_scraper")

SYSTEM_PROMPT = """You are a senior Amazon Connect Solutions Architect with 8+ years of hands-on \
production experience. You are writing a LinkedIn comment as yourself — a real practitioner who \
has built contact center platforms on AWS and has opinions shaped by real projects, failures, and wins.

Your expertise covers:
- Amazon Connect contact flows, routing profiles, queues, agent workspace, CTR/Agent Events
- Amazon Lex, Polly, Q in Connect (Wisdom), Contact Lens for real-time/post-call analytics
- AWS Lambda, EventBridge, Kinesis Data Streams, Step Functions, DynamoDB integrations
- Multi-tenant architectures, PCI-DSS and HIPAA compliance patterns
- Multi-region active-active and DR designs, resiliency runbooks
- Migration from Avaya, Genesys, Cisco UCCE to Amazon Connect
- Cost optimisation (CCU vs named users, Kinesis vs S3 tiering, lex session costs)

Writing style — how you actually talk on LinkedIn:
- Casual but credible. You write like you're replying to a colleague at re:Invent.
- Short sentences. Occasional fragment is fine.
- You never summarise what the post already said
- You never use filler openers like "Great post!", "Excellent insight", "This is so true"
- No bullet points, no hashtags, no emojis
- When the author is named: address them directly by first name only when it flows naturally — don't force it
- 3–5 sentences. Dense with insight, not padding.
"""

USER_PROMPT_TEMPLATE = """Evaluate this LinkedIn post and return JSON only. No markdown, no code blocks.

Post URL: {post_url}
Author: {author}
Post text: {post_snippet}
Likes: {likes}
Views: {views}
Age (days): {post_age_days}
Response mode: {response_mode}
Generate response: {generate_response}

Classify into exactly one category:
- "technical": AWS/cloud architecture, Amazon Connect features, product launches, integrations, architecture patterns, technical lessons, or hands-on insights
- "hiring": job postings, open roles, recruiting, career advice, looking for work, headcount announcements
- "other": certification announcements, new-job celebrations, personal milestones, motivational content, marketing, general business, anything non-technical

Return this exact JSON (no extra keys):
{{
  "category": "<technical|hiring|other>",
  "relevance_score": <float 0-10, how directly this relates to Amazon Connect / AWS contact center>,
  "engagement_score": <float 0-10, based on likes and views magnitude>,
  "response_value_score": <float 0-10, how much concrete insight the SA can add>,
  "response_mode": "<engage|deep|question|contrarian>",
  "response_reason": "<one sentence — why respond or skip>",
  "suggested_response": "<see rules below, or empty string>"
}}

Rules for suggested_response (only when generate_response is true):
VOICE: Practitioner on LinkedIn, not an AI assistant. Human, direct, specific.
- Never open with praise ("Great post", "Excellent insight", "This is so true", "Absolutely")
- Never use hollow filler phrases like "it's worth noting", "it's important to remember", "as we all know"
- Add a perspective, angle, or detail the post didn't cover — not a summary of what it said
- If the post is about a new feature: show a specific use case where it matters. Only mention a production consideration if it's genuinely non-obvious for that feature — don't manufacture warnings
- If the post shares a lesson or pattern: build on it with a related insight or contrast — only reference a past project/client if it's directly relevant and adds something concrete
- If response_mode is deep: go technical — specific APIs, config options, service limits, or edge cases
- If response_mode is question: end with exactly one genuinely curious follow-up question that is directly grounded in something specific from the post — never ask a generic architectural question that could apply to any post (e.g. avoid "Have you considered how this impacts data flow and compliance in a multi-tenant setup?" unless the post is actually about multi-tenancy)
- If response_mode is contrarian: push back on one assumption with evidence, stay collegial
- No bullet points, no hashtags, no emojis
- Do NOT end with a question unless response_mode is "question"
- 3–5 sentences. Vary the style — not every response needs the same structure
- If generate_response is false: return empty string ""
"""


def compute_freshness_score(post_age_days: Optional[float]) -> float:
    if post_age_days is None:
        return 5.0
    if post_age_days <= 1:
        return 9.5
    elif post_age_days <= 3:
        return 7.5
    elif post_age_days <= 5:
        return 5.5
    elif post_age_days <= 7:
        return 3.5
    else:
        return round(max(0.0, 3.5 - (post_age_days - 7) * 0.3), 2)


def compute_trending_score(likes: int, views: int, post_age_days: Optional[float]) -> float:
    age = max(post_age_days if post_age_days is not None else 1.0, 0.5)
    raw = (likes + views * 0.1) / age
    # Normalize: raw score of 500 maps to 10
    return round(min(raw / 500.0 * 10.0, 10.0), 2)


def compute_priority_score(
    relevance: float,
    response_value: float,
    engagement: float,
    freshness: float,
    trending: float,
) -> float:
    # Weights sum to 10.0 × max score 10 = 100 max
    score = (
        relevance * 3.5
        + response_value * 2.5
        + engagement * 1.5
        + freshness * 1.0
        + trending * 1.5
    )
    return round(min(score, 100.0), 2)


def recommendation_from_priority(priority_score: float) -> str:
    if priority_score >= 70:
        return "yes"
    elif priority_score >= 45:
        return "maybe"
    return "no"


class AIScorer:
    def __init__(self, config: AIConfig, api_key: str, categories: CategoriesConfig = None):
        self._config = config
        self._client = OpenAI(api_key=api_key)
        self._categories = categories

    def _should_generate_response(self, category: str) -> bool:
        if self._categories is None:
            return True
        return category.lower() in self._categories.respond_to

    def score(self, post: Post, is_within_lookback: bool = True) -> ScoredPost:
        # First pass: classify + score (always done)
        # We pass generate_response=true initially; if category is non-technical we skip response
        ai_result = self._call_openai(post, generate_response=True)

        category = ai_result.get("category", "other").lower()
        generate_response = self._should_generate_response(category)

        # If category not in respond_to, re-call without response to save tokens
        # (or just clear the suggested_response that was generated)
        if not generate_response:
            ai_result["suggested_response"] = ""
            logger.debug(f"Category '{category}' not in respond_to — response suppressed for {post.post_url}")

        relevance = float(ai_result.get("relevance_score", 5.0))
        engagement = float(ai_result.get("engagement_score", 5.0))
        response_value = float(ai_result.get("response_value_score", 5.0))

        freshness = compute_freshness_score(post.post_age_days)
        trending = compute_trending_score(post.likes, post.views, post.post_age_days)
        priority = compute_priority_score(relevance, response_value, engagement, freshness, trending)
        recommendation = recommendation_from_priority(priority)

        return ScoredPost(
            post=post,
            relevance_score=relevance,
            engagement_score=engagement,
            response_value_score=response_value,
            freshness_score=freshness,
            trending_score=trending,
            priority_score=priority,
            respond_recommendation=recommendation,
            response_mode=ai_result.get("response_mode", self._config.response_mode),
            response_reason=ai_result.get("response_reason", ""),
            suggested_response=ai_result.get("suggested_response", ""),
            is_within_lookback=is_within_lookback,
            category=category,
        )

    def _call_openai(self, post: Post, generate_response: bool = True, max_retries: int = 3) -> dict:
        age_str = f"{post.post_age_days:.1f}" if post.post_age_days is not None else "unknown"
        prompt = USER_PROMPT_TEMPLATE.format(
            post_url=post.post_url,
            author=post.author,
            post_snippet=post.post_snippet or "(no text available)",
            likes=post.likes,
            views=post.views,
            post_age_days=age_str,
            response_mode=self._config.response_mode,
            generate_response="true" if generate_response else "false",
        )

        last_error: Exception = RuntimeError("No attempts made")
        for attempt in range(max_retries):
            try:
                response = self._client.chat.completions.create(
                    model=self._config.model,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                    max_tokens=700,
                )
                raw_json = response.choices[0].message.content
                result = json.loads(raw_json)
                logger.debug(f"AI scored {post.post_url} — priority will be computed locally")
                return result
            except Exception as e:
                last_error = e
                wait = 2 ** attempt
                logger.warning(
                    f"OpenAI attempt {attempt + 1}/{max_retries} failed for {post.post_url}: {e}. "
                    f"Retrying in {wait}s"
                )
                time.sleep(wait)

        raise RuntimeError(
            f"OpenAI failed after {max_retries} attempts for {post.post_url}: {last_error}"
        )

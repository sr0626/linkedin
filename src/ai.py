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
- Casual but credible. You write like you're replying to a colleague at re:Invent, not filing a report.
- Short sentences. Occasional fragment is fine. First-person voice throughout.
- You never summarise what the post already said — jump straight to what you're adding
- You never use filler openers like "Great post!", "Excellent insight", "This is so true", "Absolutely"
- BANNED phrases — never use these or anything that sounds like them:
  "Have you considered", "It's worth noting", "It's important to remember", "As we all know",
  "One thing to keep in mind", "Don't forget to", "Make sure to", "You might want to",
  "I'd encourage you to", "I'd love to hear", "Would love your thoughts", "Feel free to"
- No bullet points, no hashtags, no emojis
- When the author is named: address them by first name only when it flows naturally — don't force it
- 3–5 sentences. Dense with insight, not padding.
- Sound like a person who has strong opinions from actual project experience, not a consultant being careful.
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
  "suggested_response_1": "<see rules below, or empty string>",
  "suggested_response_2": "<see rules below, or empty string>"
}}

Rules for suggested_response_1 and suggested_response_2 (only when generate_response is true):
VOICE: You are a practitioner on LinkedIn, not an AI assistant. Write in first person. Be direct and specific.

ABSOLUTELY FORBIDDEN — do not use these patterns under any circumstances:
- "Have you considered ..."
- "You might want to ..."
- "One thing to keep in mind ..."
- "It's worth noting ..."
- "Don't forget to ..."
- "Make sure to ..."
- "I'd encourage you to ..."
- "Would love your thoughts"
- "Feel free to ..."
- Any opener that sounds like generic AI-generated advice

WHAT TO DO INSTEAD:
- Share what YOU did, saw, or learned on a real project — first person ("We ran into this...", "I've seen this break when...")
- State a technical opinion directly — no hedging, no softening ("The gotcha here is...", "This changes everything for...")
- Add a specific detail, edge case, or implication the post didn't cover
- If the post is about a new feature: name one real scenario where it changes how you'd architect something
- If the post shares a lesson or pattern: extend it with a related angle, contrast, or a specific edge case from experience
- If response_mode is deep: go specific — API names, config knobs, service limits, failure modes, numbers
- If response_mode is question: end with exactly one question rooted in a specific detail from THIS post — not a generic pattern that could apply to any post. The question should feel like genuine curiosity from someone who already knows a lot about the topic.
- If response_mode is contrarian: directly challenge one assumption, cite a specific scenario where it breaks, stay collegial
- Do NOT end with a question unless response_mode is "question"
- No bullet points, no hashtags, no emojis
- 3–5 sentences. Vary the structure. Not every response needs to start with "I".

FOR THE TWO RESPONSES — they must be meaningfully different, not paraphrases of each other:
- suggested_response_1: lead with a concrete technical detail, edge case, or production experience
- suggested_response_2: take a different angle — a contrasting perspective, a downstream implication, or a different aspect of the same topic
- Different opening sentences, different structure, different emphasis
- If generate_response is false: return empty string "" for both
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
            suggested_response=ai_result.get("suggested_response_1", ""),
            suggested_response_2=ai_result.get("suggested_response_2", ""),
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
                    temperature=0.5,
                    max_tokens=1200,
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

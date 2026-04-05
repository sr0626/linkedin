"""
LinkedIn Post Scraper — Entry Point

⚠️  LinkedIn Scraping Limitations & Risks
──────────────────────────────────────────
1. Terms of Service: Automated scraping violates LinkedIn's ToS.
   Use only a personal account; never a corporate SSO account.
2. Account risk: LinkedIn detects bots. This tool uses randomized delays
   and a realistic user-agent to reduce (not eliminate) detection risk.
3. Verification challenges: LinkedIn may require phone/email verification
   after login. The scraper will pause 90s for manual completion.
4. Engagement metrics: Views/impressions are not always visible in search
   results. If views are consistently 0, lower min_views in config.yaml.
5. Selector instability: LinkedIn changes its HTML structure frequently.
   If scraping stops working, selectors in src/scraper.py may need updating.

Usage:
    python main.py
    python main.py --config path/to/config.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime

from src.config import load_config
from src.logging_setup import setup_logging
from src.models import ScoredPost
from src.scraper import LinkedInScraper
from src.parser import parse_posts, extract_profile_id
from src.filtering import apply_filters
from src.ai import AIScorer
from src.storage import StorageManager
from src.reporting import generate_html, generate_email_html
from src.emailer import send_email_report


def sort_key(sp: ScoredPost):
    rec_order = {"yes": 0, "maybe": 1, "no": 2}
    return (
        rec_order.get(sp.respond_recommendation, 3),
        -sp.priority_score,
        -sp.trending_score,
        -sp.freshness_score,
        -sp.views,
    )


async def _score_posts(
    posts,
    ai_scorer: AIScorer,
    storage: StorageManager,
    filters,
    logger,
) -> list[ScoredPost]:
    """Score a list of filtered Post objects, using cache where possible."""
    scored: list[ScoredPost] = []
    for post in posts:
        is_within_lookback = (
            post.post_age_days is None and filters.include_if_no_date
        ) or (
            post.post_age_days is not None
            and post.post_age_days <= filters.lookback_days
        )
        try:
            needs_rescore = storage.needs_ai_rescore(post)
            if needs_rescore:
                logger.debug(f"  Scoring (AI): {post.post_url}")
                sp = ai_scorer.score(post, is_within_lookback=is_within_lookback)
            else:
                logger.debug(f"  Using cached scores: {post.post_url}")
                cached = storage.get_cached_scored_post(post)
                sp = cached if cached is not None else ai_scorer.score(post, is_within_lookback=is_within_lookback)
            storage.upsert(sp)
            scored.append(sp)
        except Exception as e:
            logger.error(f"  Failed to score {post.post_url}: {e}")
    return scored


async def run(config_path: str) -> None:
    config = load_config(config_path)
    logger = setup_logging(config.output.logs_dir)

    os.makedirs(config.output.reports_dir, exist_ok=True)
    os.makedirs(config.output.data_dir, exist_ok=True)

    db_path = os.path.join(config.output.data_dir, "posts.db")
    storage = StorageManager(db_path)
    ai_scorer = AIScorer(config.ai, config.openai_api_key, config.categories)

    run_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    all_scored: list[ScoredPost] = []
    # Track all scored post URLs to deduplicate across keyword + profile passes
    seen_post_urls: set[str] = set()
    total_raw = 0
    total_filtered = 0

    # Profiles to scrape — seeded from config, auto-discovered authors added below
    profiles_to_scrape: set[str] = set(config.profiles)

    logger.info("=" * 60)
    logger.info(f"LinkedIn Scraper started — {run_ts}")
    logger.info(f"Keywords: {config.keywords}")
    logger.info(
        f"Filters: min_likes={config.filters.min_likes}, "
        f"min_views={config.filters.min_views}, "
        f"lookback_days={config.filters.lookback_days}"
    )
    if config.categories.exclude_categories:
        logger.info(f"Excluding categories: {config.categories.exclude_categories}")
    logger.info("=" * 60)

    async with LinkedInScraper(config) as scraper:
        logged_in = await scraper.login(config.linkedin_email, config.linkedin_password)
        if not logged_in:
            logger.critical("LinkedIn login failed. Exiting.")
            storage.close()
            sys.exit(1)

        # ── Phase 1: Keyword scraping ──────────────────────────────────────
        for keyword in config.keywords:
            logger.info(f"\n── Keyword: {keyword} ──")
            try:
                raw_posts = await scraper.scrape_keyword(keyword)
                total_raw += len(raw_posts)
            except Exception as e:
                logger.error(f"Scraping failed for keyword '{keyword}': {e}")
                continue

            posts = parse_posts(raw_posts)
            logger.info(f"  Parsed: {len(posts)} unique posts")

            passed, rejected = apply_filters(posts, config.filters)
            total_filtered += len(passed)
            logger.info(f"  Passed filter: {len(passed)} | Rejected: {len(rejected)}")

            scored_batch = await _score_posts(passed, ai_scorer, storage, config.filters, logger)

            for sp in scored_batch:
                if sp.post_url in seen_post_urls:
                    continue
                seen_post_urls.add(sp.post_url)
                all_scored.append(sp)

                # Auto-discover: collect profile IDs from technical posts worth engaging
                if sp.category == "technical" and sp.respond_recommendation in ("yes", "maybe"):
                    pid = extract_profile_id(sp.post.author_profile_url)
                    if pid and pid not in profiles_to_scrape:
                        logger.info(f"  Auto-discovered profile: {pid} (author: {sp.author})")
                        profiles_to_scrape.add(pid)

        # ── Phase 2: Profile scraping ──────────────────────────────────────
        if profiles_to_scrape:
            logger.info(f"\n── Scraping {len(profiles_to_scrape)} author profiles ──")
            logger.info(f"   Profiles: {sorted(profiles_to_scrape)}")

        for profile_id in sorted(profiles_to_scrape):
            logger.info(f"\n── Profile: {profile_id} ──")
            try:
                raw_posts = await scraper.scrape_profile(profile_id, f"profile:{profile_id}")
                total_raw += len(raw_posts)
            except Exception as e:
                logger.error(f"Profile scraping failed for '{profile_id}': {e}")
                continue

            posts = parse_posts(raw_posts)
            logger.info(f"  Parsed: {len(posts)} unique posts")

            passed, rejected = apply_filters(posts, config.filters)
            total_filtered += len(passed)
            logger.info(f"  Passed filter: {len(passed)} | Rejected: {len(rejected)}")

            scored_batch = await _score_posts(passed, ai_scorer, storage, config.filters, logger)

            for sp in scored_batch:
                if sp.post_url in seen_post_urls:
                    continue
                seen_post_urls.add(sp.post_url)
                all_scored.append(sp)

    # ── Apply category exclusions ─────────────────────────────────────────
    if config.categories.exclude_categories:
        before_count = len(all_scored)
        all_scored = [
            sp for sp in all_scored
            if sp.category not in config.categories.exclude_categories
        ]
        excluded_count = before_count - len(all_scored)
        if excluded_count:
            logger.info(f"\nExcluded {excluded_count} posts in categories: {config.categories.exclude_categories}")

    # Sort results
    all_scored.sort(key=sort_key)

    # Generate reports
    if all_scored:
        html_path = generate_html(all_scored, config, config.output.reports_dir, run_ts)
        abs_path = os.path.abspath(html_path)
        file_url = f"file://{abs_path}"
        logger.info(f"\nReport saved: {file_url}")

        if config.email.enabled:
            if config.email.to and config.email_from and config.email_password:
                email_html = generate_email_html(all_scored, config, run_ts)
                send_email_report(
                    html_content=email_html,
                    to_addr=config.email.to,
                    from_addr=config.email_from,
                    password=config.email_password,
                    subject=f"Amazon Connect Intelligence · {run_ts}",
                )
            else:
                logger.warning(
                    "Email is enabled but EMAIL_FROM, EMAIL_PASSWORD, or email.to are missing"
                )
    else:
        logger.warning("No posts passed filters — no reports generated")

    yes_count = sum(1 for s in all_scored if s.respond_recommendation == "yes")
    maybe_count = sum(1 for s in all_scored if s.respond_recommendation == "maybe")
    no_count = sum(1 for s in all_scored if s.respond_recommendation == "no")

    logger.info("\n" + "=" * 60)
    logger.info("Run Summary")
    logger.info(f"  Raw posts collected:  {total_raw}")
    logger.info(f"  Posts after filter:   {total_filtered}")
    logger.info(f"  Posts scored:         {len(all_scored)}")
    logger.info(f"  Recommend (yes):      {yes_count}")
    logger.info(f"  Consider  (maybe):    {maybe_count}")
    logger.info(f"  Skip      (no):       {no_count}")
    logger.info("=" * 60)

    storage.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="LinkedIn Post Scraper")
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml (default: config.yaml)",
    )
    args = parser.parse_args()
    asyncio.run(run(args.config))


if __name__ == "__main__":
    main()

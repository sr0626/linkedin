from __future__ import annotations

import os
from dataclasses import dataclass

import yaml
from dotenv import load_dotenv

load_dotenv()


@dataclass
class FilterConfig:
    min_likes: int
    min_views: int
    lookback_days: int
    include_if_no_date: bool


@dataclass
class ScrapingConfig:
    max_posts_per_keyword: int
    headless: bool
    scroll_pause_ms: int
    max_retries: int


@dataclass
class OutputConfig:
    reports_dir: str
    data_dir: str
    logs_dir: str


@dataclass
class AIConfig:
    model: str
    response_mode: str


@dataclass
class CategoriesConfig:
    respond_to: list[str]        # e.g. ["technical"] — only these get suggested_response
    exclude_categories: list[str]  # e.g. ["hiring", "other"] — these are dropped from report


@dataclass
class EmailConfig:
    enabled: bool
    to: str


@dataclass
class AppConfig:
    keywords: list[str]
    profiles: list[str]
    filters: FilterConfig
    scraping: ScrapingConfig
    output: OutputConfig
    ai: AIConfig
    categories: CategoriesConfig
    email: EmailConfig
    linkedin_email: str
    linkedin_password: str
    openai_api_key: str
    email_from: str
    email_password: str


def load_config(config_path: str = "config.yaml") -> AppConfig:
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not raw.get("keywords"):
        raise ValueError("config.yaml: 'keywords' must be a non-empty list")

    f_raw = raw.get("filters", {})
    s_raw = raw.get("scraping", {})
    o_raw = raw.get("output", {})
    ai_raw = raw.get("ai", {})
    cat_raw = raw.get("categories", {})
    em_raw = raw.get("email", {})

    linkedin_email = os.environ.get("LINKEDIN_EMAIL", "")
    linkedin_password = os.environ.get("LINKEDIN_PASSWORD", "")
    openai_api_key = os.environ.get("OPENAI_API_KEY", "")

    if not linkedin_email:
        raise ValueError("LINKEDIN_EMAIL environment variable is not set")
    if not linkedin_password:
        raise ValueError("LINKEDIN_PASSWORD environment variable is not set")
    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY environment variable is not set")

    return AppConfig(
        keywords=raw["keywords"],
        profiles=raw.get("profiles", []),
        filters=FilterConfig(
            min_likes=int(f_raw.get("min_likes", 10)),
            min_views=int(f_raw.get("min_views", 50)),
            lookback_days=int(f_raw.get("lookback_days", 7)),
            include_if_no_date=bool(f_raw.get("include_if_no_date", True)),
        ),
        scraping=ScrapingConfig(
            max_posts_per_keyword=int(s_raw.get("max_posts_per_keyword", 50)),
            headless=bool(s_raw.get("headless", True)),
            scroll_pause_ms=int(s_raw.get("scroll_pause_ms", 1500)),
            max_retries=int(s_raw.get("max_retries", 3)),
        ),
        output=OutputConfig(
            reports_dir=o_raw.get("reports_dir", "reports"),
            data_dir=o_raw.get("data_dir", "data"),
            logs_dir=o_raw.get("logs_dir", "logs"),
        ),
        ai=AIConfig(
            model=ai_raw.get("model", "gpt-4o-mini"),
            response_mode=ai_raw.get("response_mode", "engage"),
        ),
        categories=CategoriesConfig(
            respond_to=[c.lower() for c in cat_raw.get("respond_to", ["technical"])],
            exclude_categories=[c.lower() for c in cat_raw.get("exclude_categories", [])],
        ),
        email=EmailConfig(
            enabled=bool(em_raw.get("enabled", False)),
            to=os.environ.get("EMAIL_TO", ""),
        ),
        linkedin_email=linkedin_email,
        linkedin_password=linkedin_password,
        openai_api_key=openai_api_key,
        email_from=os.environ.get("EMAIL_FROM", ""),
        email_password=os.environ.get("EMAIL_PASSWORD", ""),
    )

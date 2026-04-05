# Amazon Connect LinkedIn Intelligence

Scrapes LinkedIn for Amazon Connect and AWS contact center posts, scores them for engagement value, and generates AI-powered response suggestions in the voice of a senior Amazon Connect Solutions Architect.

> **Disclaimer**: Automated scraping may violate LinkedIn's Terms of Service. Use only with a personal account for personal productivity purposes.

---

## What it does

- **Two-phase scraping**: keyword search + direct profile activity pages
- **Auto-discovery**: after keyword results are scored, profiles of relevant technical authors are automatically scraped for more posts
- **English-only filtering** via `langdetect`
- **AI scoring** across 5 dimensions: relevance, engagement, response value, freshness, trending
- **AI response suggestions** written in practitioner voice (OpenAI GPT-4o-mini) — only for technical posts
- **Category filtering**: hiring and other non-technical posts are excluded from the report entirely
- **SQLite cache**: posts with unchanged metrics are not re-scored on subsequent runs
- **Interactive HTML report** with filter buttons, search, copy-to-clipboard responses, and persistent "Mark Responded" tracking

---

## Quick start

### 1. Set up the virtual environment

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
```

### 2. Configure credentials

```bash
cp .env.example .env
```

Edit `.env`:
```
LINKEDIN_EMAIL=your@email.com
LINKEDIN_PASSWORD=yourpassword
OPENAI_API_KEY=sk-...
```

### 3. Run

```bash
.venv/bin/python3 main.py
```

The terminal prints a `file://` link to the HTML report when done. Cmd+click to open.

---

## Configuration (`config.yaml`)

| Field | Default | Description |
|---|---|---|
| `keywords` | 10 AC-focused terms | Exact-phrase LinkedIn search queries |
| `profiles` | 14 curated authors | Always-scrape profile IDs (plus auto-discovered ones) |
| `filters.min_likes` | 5 | Minimum likes to include a post |
| `filters.lookback_days` | 7 | Only include posts from the last N days |
| `filters.include_if_no_date` | true | Include posts where date couldn't be parsed |
| `scraping.max_posts_per_keyword` | 50 | Cap per keyword search |
| `scraping.headless` | false | Set to `true` for unattended/cron runs |
| `ai.response_mode` | engage | `engage` / `deep` / `question` / `contrarian` |
| `categories.exclude_categories` | hiring, other | Categories dropped from report entirely |

---

## Scraping pipeline

```
Keywords (10)
    └── Search results scrape     ← _EXTRACT_JS (search results DOM)
    └── Clipboard URL enrichment  ← "Copy link to post" menu intercept
    └── AI scoring
    └── Auto-discover tech authors ──┐
                                     ▼
Profiles (config + auto-discovered)
    └── Recent activity scrape    ← _EXTRACT_PROFILE_JS (role=article DOM)
    └── AI scoring
    └── Merge + deduplicate
    └── Exclude hiring/other
    └── Sort by priority
    └── HTML report
```

---

## Post scoring

| Dimension | Weight | Description |
|---|---|---|
| Relevance | 35% | Amazon Connect / AWS contact center alignment |
| Response Value | 25% | How much the SA can add |
| Engagement | 15% | Likes + views magnitude |
| Trending | 15% | Engagement relative to post age |
| Freshness | 10% | Recency (0–1d → 9.5, 6–7d → 3.5) |

**Priority score** (0–100) = weighted sum
- `yes` ≥ 70 · `maybe` 45–69 · `no` < 45

---

## HTML report features

- **Card layout** — one card per post, colour-coded by recommendation
- **Post date/time** shown in every card header
- **Direct post links** (blue) or author activity fallback (purple) when direct link unavailable
- **Filter bar**: All / Respond / Consider / Skip / Responded / Not Responded
- **Search**: live filter by author name or post text
- **Copy button** on every suggested response
- **Mark Responded** — persists in `localStorage` under a fixed key across all runs and reports. Marking a post as responded in one report carries over to the next.

---

## AI response voice

Responses are written as a senior Amazon Connect Solutions Architect:
- Adds perspective or insight the post didn't cover — not a summary
- References the author by first name only when it flows naturally
- For new features: concrete use case only when genuinely relevant
- No bullet points, no hashtags, no emojis
- Does not end with a question unless `response_mode: question`
- Questions in `question` mode are specific to the post — no generic architectural prompts

---

## Troubleshooting

**Login fails — "login form not found"**
LinkedIn occasionally renders the login form slowly. The scraper retries navigation once and waits up to 30s for the form. If it still fails, set `headless: false` to watch what LinkedIn is showing.

**Verification / CAPTCHA required**
The scraper pauses for 120s and saves a screenshot to `logs/login_challenge.png`. Complete the verification manually in the browser window.

**Profile pages return 0 posts**
The profile extractor uses `role="article"` containers with `.update-components-text`. If LinkedIn changes the profile activity layout, update `_EXTRACT_PROFILE_JS` in `src/scraper.py`.

**Views are always 0**
LinkedIn doesn't always show impressions in search results. `min_views: 0` is the correct setting.

**Post link opens author profile, not post**
This happens when both clipboard enrichment and DOM link extraction fail for a keyword result. The report shows a purple "View author activity" button in this case — it opens their recent activity page where you can find the post manually.

---

## Project structure

```
LinkedInScrapper/
├── main.py                     Orchestration entry point
├── config.yaml                 All runtime configuration
├── requirements.txt
├── .env.example
└── src/
    ├── config.py               YAML + .env → typed AppConfig
    ├── models.py               Post, ScoredPost dataclasses
    ├── logging_setup.py        File + console logging
    ├── scraper.py              Playwright scraper (keyword + profile)
    ├── parser.py               Raw dict → Post + extract_profile_id()
    ├── filtering.py            Likes / views / lookback / language filter
    ├── ai.py                   OpenAI scoring + response generation
    ├── storage.py              SQLite upsert + cache
    ├── reporting.py            HTML report generation
    └── emailer.py              Optional Gmail SMTP delivery
```

---

## Scheduling (cron)

```bash
# Run daily at 7am, headless
0 7 * * * cd /path/to/LinkedInScrapper && .venv/bin/python3 main.py >> logs/cron.log 2>&1
```

Set `headless: true` in `config.yaml` for unattended runs.

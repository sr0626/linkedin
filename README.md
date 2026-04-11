# Amazon Connect LinkedIn Intelligence

Scrapes LinkedIn for Amazon Connect and AWS contact center posts, scores them for engagement value, and generates AI-powered response suggestions in the voice of a senior Amazon Connect Solutions Architect.

> **Disclaimer**: Automated scraping may violate LinkedIn's Terms of Service. Use only with a personal account for personal productivity purposes.

---

## What it does

- **Two-phase scraping**: keyword search + direct profile activity pages
- **Auto-discovery**: after keyword results are scored, profiles of relevant technical authors are automatically scraped for more posts
- **English-only filtering** via `langdetect`
- **AI scoring** across 5 dimensions: relevance, engagement, response value, freshness, trending
- **Two AI response options** per post — written in practitioner voice (OpenAI GPT-4o-mini), each taking a different angle — only for technical posts
- **Category filtering**: hiring and other non-technical posts are excluded from the report entirely
- **SQLite cache**: posts with unchanged metrics are not re-scored on subsequent runs
- **Interactive HTML report** — enterprise card layout, filter buttons, search, copy-to-clipboard, persistent "Mark Responded" tracking
- **Email delivery** — sends an email-safe HTML summary (Respond + Consider posts) via Gmail SMTP after each run

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

Edit `.env` with your credentials (see `.env.example` for all required keys):
- `LINKEDIN_EMAIL` / `LINKEDIN_PASSWORD` — LinkedIn account
- `OPENAI_API_KEY` — OpenAI API key
- `EMAIL_FROM` — Gmail address to send from
- `EMAIL_PASSWORD` — Gmail App Password (16-char code from [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords), not your account password)
- `EMAIL_TO` — recipient address

### 3. Run

```bash
.venv/bin/python3 main.py
```

The terminal prints a `file://` link to the HTML report when done. Cmd+click to open.

If email is enabled, a summary is also sent to `EMAIL_TO` automatically.

To generate the HTML report from existing DB data without scraping:
```bash
.venv/bin/python3 test_email.py   # sends email using existing DB
```

---

## Configuration (`config.yaml`)

| Field | Default | Description |
|---|---|---|
| `keywords` | 10 AC-focused terms | Exact-phrase LinkedIn search queries |
| `profiles` | curated list | Always-scrape profile IDs (plus auto-discovered ones) |
| `filters.min_likes` | 5 | Minimum likes to include a post |
| `filters.min_views` | 0 | Minimum views to include a post |
| `filters.lookback_days` | 7 | Only include posts from the last N days |
| `filters.include_if_no_date` | true | Include posts where date couldn't be parsed |
| `scraping.max_posts_per_keyword` | 50 | Cap per keyword search |
| `scraping.headless` | false | Set to `true` for unattended/cron runs |
| `ai.model` | gpt-4o-mini | OpenAI model used for scoring and response generation |
| `ai.response_mode` | engage | `engage` / `deep` / `question` / `contrarian` |
| `categories.respond_to` | technical | Categories that get suggested responses |
| `categories.exclude_categories` | hiring, other | Categories dropped from report entirely |
| `email.enabled` | true | Set to `false` to disable email delivery |

---

## Scraping pipeline

```
Keywords
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
    └── HTML report (file:// link printed to terminal)
    └── Email summary (Respond + Consider posts) → EMAIL_TO
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

- **Enterprise card layout** — dark navy sticky topbar, amber "AC" logo, cards lift on hover
- **Color-coded cards** — green (Respond), amber (Consider), red (Skip) left border
- **Post date/time** shown in every card header
- **Direct post links** (blue) or author activity fallback (purple) when direct link unavailable
- **Sticky toolbar**: All / Respond / Consider / Skip / Responded / Not Responded filter buttons + live search
- **Score bars** — Relevance, Engagement, Freshness, Trending with color-coded values
- **Two response options** (Option 1 / Option 2) — each with its own Copy button, separated by a dashed divider
- **Mark Responded** — persists in `localStorage` under a fixed key across all runs and reports

## Email report features

- Sends after every run when `email.enabled: true` and `EMAIL_TO` is set
- Shows only Respond + Consider posts — actionable content only
- Inline styles, no JavaScript — renders correctly in Gmail and Outlook
- Includes stats strip, score bars, and both suggested response options
- Test independently: `.venv/bin/python3 test_email.py`

---

## AI response voice

Each post gets two distinct suggested responses. Both are written as a senior Amazon Connect Solutions Architect:

- **Option 1**: leads with a concrete technical detail, edge case, or production experience
- **Option 2**: takes a different angle — contrasting perspective, downstream implication, or different aspect of the same topic

Rules applied to both:
- Adds perspective or detail the post didn't cover — never a summary
- First-person, direct — written like a reply to a colleague at re:Invent
- References the author by first name only when it flows naturally
- No bullet points, no hashtags, no emojis
- Does not end with a question unless `response_mode: question`
- Questions in `question` mode are specific to the post — no generic architectural prompts
- Banned patterns (never generated): "Have you considered", "You might want to", "Feel free to", "It's worth noting", "One thing to keep in mind", and similar AI-filler phrases

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
├── test_email.py               Standalone email test (no scraping required)
└── src/
    ├── config.py               YAML + .env → typed AppConfig
    ├── models.py               Post, ScoredPost dataclasses
    ├── logging_setup.py        File + console logging
    ├── scraper.py              Playwright scraper (keyword + profile)
    ├── parser.py               Raw dict → Post + extract_profile_id()
    ├── filtering.py            Likes / views / lookback / language filter
    ├── ai.py                   OpenAI scoring + dual response generation
    ├── storage.py              SQLite upsert + cache + auto-migration
    ├── reporting.py            HTML + email report generation
    ├── reporting_v1_backup.py  Backup: original table-based style
    ├── reporting_v2_backup.py  Backup: previous card-based style
    └── emailer.py              Gmail SMTP delivery
```

---

## Scheduling (cron)

```bash
# Run daily at 7am, headless
0 7 * * * cd /path/to/LinkedInScrapper && .venv/bin/python3 main.py >> logs/cron.log 2>&1
```

Set `headless: true` in `config.yaml` for unattended runs.
